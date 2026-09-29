"""Attempt lifecycle and marking.

Everything here is server-authoritative on purpose. The browser holds a
countdown and a copy of the answers purely so the UI feels instant; none of it
is trusted. In particular the deadline is ``Attempt.expires_at`` in the
database, so editing the page's JavaScript cannot buy a student extra time.
"""

import random
from datetime import datetime, timedelta, timezone

from app.models import (
    Answer,
    Attempt,
    AttemptStatus,
    Question,
    QuestionType,
    Test,
    TestKind,
)


class AttemptError(Exception):
    """A refused attempt action. The message is safe to show a user."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; treat those as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def seconds_remaining(attempt: Attempt) -> int | None:
    """Whole seconds left, or None on an untimed test."""
    expires = _aware(attempt.expires_at)
    if not expires:
        return None
    return max(0, int((expires - _now()).total_seconds()))


# --------------------------------------------------------------------------
# Starting
# --------------------------------------------------------------------------

def start_attempt(db, test: Test, student) -> Attempt:
    """Resume the live attempt if there is one, otherwise begin a new one."""
    if not test.questions:
        raise AttemptError("This test has no questions yet.")

    existing = (
        db.query(Attempt)
        .filter(
            Attempt.test_id == test.id,
            Attempt.student_id == student.id,
            Attempt.status == AttemptStatus.in_progress,
        )
        .order_by(Attempt.started_at.desc())
        .first()
    )
    if existing:
        # Might have expired while the student was away.
        enforce_expiry(db, existing)
        if existing.status == AttemptStatus.in_progress:
            return existing

    if test.max_attempts is not None:
        used = (
            db.query(Attempt)
            .filter(Attempt.test_id == test.id, Attempt.student_id == student.id)
            .count()
        )
        if used >= test.max_attempts:
            raise AttemptError(
                f"You have used all {test.max_attempts} attempt(s) for this test."
            )

    attempt = Attempt(
        test_id=test.id,
        student_id=student.id,
        started_at=_now(),
        max_score=test.total_marks,
        status=AttemptStatus.in_progress,
    )
    if test.duration_minutes:
        attempt.expires_at = _now() + timedelta(minutes=test.duration_minutes)

    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def question_order(test: Test, attempt: Attempt) -> list[Question]:
    """Questions in the order this attempt should see them.

    Shuffling is seeded with the attempt id so a refresh mid-test produces the
    same order -- a shuffle that reshuffles is indistinguishable from losing
    your place.
    """
    questions = list(test.questions)
    if test.shuffle_questions:
        random.Random(attempt.id).shuffle(questions)
    return questions


# --------------------------------------------------------------------------
# Answering
# --------------------------------------------------------------------------

def get_or_create_answer(db, attempt: Attempt, question_id: int) -> Answer:
    answer = (
        db.query(Answer)
        .filter(Answer.attempt_id == attempt.id, Answer.question_id == question_id)
        .first()
    )
    if not answer:
        answer = Answer(
            attempt_id=attempt.id, question_id=question_id, selected_choice_ids=[]
        )
        db.add(answer)
        db.flush()
    return answer


def answer_map(db, attempt: Attempt) -> dict[int, Answer]:
    rows = db.query(Answer).filter(Answer.attempt_id == attempt.id).all()
    return {row.question_id: row for row in rows}


def save_answer(db, attempt: Attempt, question: Question, data) -> Answer:
    if attempt.status != AttemptStatus.in_progress:
        raise AttemptError("This attempt has already been submitted.")

    answer = get_or_create_answer(db, attempt, question.id)

    if data.selected_choice_ids is not None:
        valid = {c.id for c in question.choices}
        chosen = [cid for cid in data.selected_choice_ids if cid in valid]
        if question.qtype in (QuestionType.single, QuestionType.truefalse):
            chosen = chosen[:1]
        answer.selected_choice_ids = chosen

    if data.numeric_value is not None or (
        question.qtype == QuestionType.numeric and data.selected_choice_ids == []
    ):
        answer.numeric_value = data.numeric_value

    if data.flagged is not None:
        answer.flagged = bool(data.flagged)

    db.commit()
    db.refresh(answer)
    return answer


# --------------------------------------------------------------------------
# Marking
# --------------------------------------------------------------------------

def mark_answer(question: Question, answer: Answer | None) -> tuple[bool, float]:
    """Score one question. Returns (is_correct, marks_awarded).

    An unanswered question is never penalised, even with negative marking on --
    penalising a blank would make guessing strictly better than skipping.
    """
    if answer is None or not answer.is_answered:
        return False, 0.0

    if question.qtype == QuestionType.numeric:
        if question.numeric_answer is None or answer.numeric_value is None:
            correct = False
        else:
            tolerance = question.numeric_tolerance or 0.0
            correct = abs(answer.numeric_value - question.numeric_answer) <= tolerance
    else:
        expected = set(question.correct_choice_ids)
        given = set(answer.selected_choice_ids or [])
        # Multi-select is all-or-nothing: every correct option and no wrong ones.
        correct = bool(expected) and given == expected

    if correct:
        return True, float(question.marks or 0)
    return False, -float(question.negative_marks or 0)


def score_attempt(db, attempt: Attempt, status: AttemptStatus = AttemptStatus.submitted):
    """Mark every question, persist the result, and close the attempt."""
    test = attempt.test
    answers = answer_map(db, attempt)

    total = 0.0
    max_score = 0.0
    for question in test.questions:
        max_score += float(question.marks or 0)
        answer = answers.get(question.id)
        is_correct, awarded = mark_answer(question, answer)
        if answer is not None:
            answer.is_correct = is_correct
            answer.marks_awarded = awarded
        total += awarded

    # A negatively-marked test can go below zero; a report card should not.
    total = max(0.0, total)

    attempt.score = round(total, 2)
    attempt.max_score = round(max_score, 2)
    attempt.percent = round((total / max_score) * 100, 1) if max_score else 0.0
    attempt.passed = attempt.percent >= (test.pass_percent or 0)
    attempt.status = status
    attempt.submitted_at = _now()

    db.commit()
    db.refresh(attempt)
    return attempt


def submit_attempt(db, attempt: Attempt) -> Attempt:
    if attempt.status != AttemptStatus.in_progress:
        return attempt
    return score_attempt(db, attempt, status=AttemptStatus.submitted)


def enforce_expiry(db, attempt: Attempt) -> Attempt:
    """Auto-submit an attempt whose clock has run out.

    Called on every attempt route, so a student who closes the tab and comes
    back tomorrow finds the test marked rather than still open.
    """
    if attempt.status != AttemptStatus.in_progress:
        return attempt
    expires = _aware(attempt.expires_at)
    if expires and _now() >= expires:
        return score_attempt(db, attempt, status=AttemptStatus.expired)
    return attempt


def check_answer(db, attempt: Attempt, question: Question):
    """Practice-mode instant feedback for one question.

    Refused on a grand test -- that endpoint is the whole answer key, and a
    student with a browser console would otherwise just ask for it.
    """
    if attempt.test.kind != TestKind.practice:
        raise AttemptError("Answers are only revealed after a grand test is submitted.")

    answer = (
        db.query(Answer)
        .filter(Answer.attempt_id == attempt.id, Answer.question_id == question.id)
        .first()
    )
    if answer is None or not answer.is_answered:
        raise AttemptError("Choose an answer first.")

    is_correct, awarded = mark_answer(question, answer)
    answer.is_correct = is_correct
    answer.marks_awarded = awarded
    db.commit()

    return {
        "question_id": question.id,
        "is_correct": is_correct,
        "correct_choice_ids": question.correct_choice_ids,
        "correct_numeric": question.numeric_answer,
        "explanation": question.explanation,
        "marks_awarded": awarded,
    }


# --------------------------------------------------------------------------
# Review
# --------------------------------------------------------------------------

def review_rows(db, attempt: Attempt) -> list[dict]:
    """Per-question breakdown for the result page. Finished attempts only."""
    answers = answer_map(db, attempt)
    rows = []
    for index, question in enumerate(attempt.test.questions, start=1):
        answer = answers.get(question.id)
        selected = set((answer.selected_choice_ids or []) if answer else [])
        rows.append(
            {
                "number": index,
                "question": question,
                "answer": answer,
                "selected_ids": selected,
                "answered": bool(answer and answer.is_answered),
                "is_correct": bool(answer and answer.is_correct),
                "marks_awarded": (answer.marks_awarded if answer else 0.0) or 0.0,
            }
        )
    return rows


def question_difficulty(db, test: Test) -> list[dict]:
    """How often each question was answered correctly, hardest first.

    Gives a teacher the one thing raw scores hide: which question the class as
    a whole did not understand.
    """
    rows = []
    for index, question in enumerate(test.questions, start=1):
        answers = (
            db.query(Answer)
            .join(Attempt, Attempt.id == Answer.attempt_id)
            .filter(
                Answer.question_id == question.id,
                Attempt.status != AttemptStatus.in_progress,
            )
            .all()
        )
        total = len(answers)
        correct = sum(1 for a in answers if a.is_correct)
        rows.append(
            {
                "number": index,
                "question": question,
                "attempts": total,
                "correct": correct,
                "percent": round((correct / total) * 100) if total else 0,
            }
        )
    rows.sort(key=lambda r: (r["percent"], -r["attempts"]))
    return rows
