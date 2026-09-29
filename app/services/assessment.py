"""Test authoring and listing.

Scoring lives in ``services/grading.py``; this module is about the shape of a
test, not about marking one.
"""

from sqlalchemy import Integer, func

from app.models import (
    Attempt,
    AttemptStatus,
    Choice,
    Course,
    Enrollment,
    Question,
    QuestionType,
    Test,
    TestKind,
)


def get_test(db, test_id: int):
    return db.query(Test).filter(Test.id == test_id).first()


def list_tests(db, course_id: int, published_only: bool = False):
    query = db.query(Test).filter(Test.course_id == course_id)
    if published_only:
        query = query.filter(Test.is_published.is_(True))
    return query.order_by(Test.kind, Test.created_at.desc()).all()


def list_available_tests(db, student_id: int, kind: TestKind | None = None):
    """Published tests across every course the student is enrolled in."""
    query = (
        db.query(Test)
        .join(Course, Course.id == Test.course_id)
        .join(Enrollment, Enrollment.course_id == Course.id)
        .filter(
            Enrollment.student_id == student_id,
            Test.is_published.is_(True),
        )
    )
    if kind is not None:
        query = query.filter(Test.kind == kind)
    return query.order_by(Test.created_at.desc()).all()


def create_test(db, course_id: int, data) -> Test:
    test = Test(
        course_id=course_id,
        title=data.title,
        description=data.description,
        kind=data.kind,
        duration_minutes=data.duration_minutes,
        pass_percent=data.pass_percent,
        max_attempts=data.max_attempts,
        negative_marking=data.negative_marking,
        shuffle_questions=data.shuffle_questions,
        is_published=data.is_published,
    )
    _apply_kind_defaults(test)
    db.add(test)
    db.commit()
    db.refresh(test)
    return test


def _apply_kind_defaults(test: Test) -> None:
    """Keep the two test kinds behaving the way their names promise.

    A 'grand test' that is untimed and infinitely retryable is just a practice
    test with a different label, so the defaults are enforced rather than
    merely suggested.
    """
    if test.kind == TestKind.grand:
        if not test.duration_minutes:
            from app.config import get_settings

            test.duration_minutes = get_settings().grand_test_default_minutes
        if test.max_attempts is None:
            test.max_attempts = 1
    else:
        test.duration_minutes = None
        test.negative_marking = False


def update_test(db, test: Test, data) -> Test:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(test, field, value)
    _apply_kind_defaults(test)
    db.commit()
    db.refresh(test)
    return test


def delete_test(db, test: Test) -> None:
    db.delete(test)
    db.commit()


def save_test(db, test: Test, data) -> Test:
    """Replace a test's settings and its entire question set in one write.

    The builder always posts the full document, so a wholesale replace avoids
    a diffing pass that would be far easier to get subtly wrong.
    """
    for field in (
        "title", "description", "kind", "duration_minutes", "pass_percent",
        "max_attempts", "negative_marking", "shuffle_questions", "is_published",
    ):
        setattr(test, field, getattr(data, field))
    _apply_kind_defaults(test)

    # Existing attempts reference questions by id. Rather than orphan them,
    # the old questions are deleted and their answers cascade away -- which is
    # why editing a test that already has attempts is blocked in the router.
    for question in list(test.questions):
        db.delete(question)
    db.flush()

    for index, payload in enumerate(data.questions, start=1):
        question = Question(
            test_id=test.id,
            order_index=index,
            text=payload.text.strip(),
            qtype=payload.qtype,
            marks=payload.marks,
            negative_marks=payload.negative_marks if test.negative_marking else 0.0,
            explanation=(payload.explanation or "").strip() or None,
            numeric_answer=payload.numeric_answer,
            numeric_tolerance=payload.numeric_tolerance,
        )
        db.add(question)
        db.flush()

        if payload.qtype == QuestionType.numeric:
            continue

        choices = payload.choices
        if payload.qtype == QuestionType.truefalse and len(choices) != 2:
            # Normalise a malformed true/false into the canonical pair, so the
            # runner never has to special-case a two-option question that
            # somehow arrived with one option or three.
            true_is_correct = next(
                (c.is_correct for c in choices if c.text.strip().lower() == "true"),
                True,
            )
            choices = [
                _plain_choice("True", true_is_correct),
                _plain_choice("False", not true_is_correct),
            ]

        for c_index, choice in enumerate(choices, start=1):
            db.add(
                Choice(
                    question_id=question.id,
                    order_index=c_index,
                    text=choice.text.strip(),
                    is_correct=bool(choice.is_correct),
                )
            )

    db.commit()
    db.refresh(test)
    return test


def _plain_choice(text: str, is_correct: bool):
    from app.schemas.assessment import ChoiceIn

    return ChoiceIn(text=text, is_correct=is_correct)


def validate_questions(data) -> str | None:
    """Return the first authoring mistake, or None. Shown inline in the builder."""
    if not data.questions:
        return "Add at least one question before saving."

    for index, question in enumerate(data.questions, start=1):
        if not question.text.strip():
            return f"Question {index} has no text."

        if question.qtype == QuestionType.numeric:
            if question.numeric_answer is None:
                return f"Question {index} needs a numeric answer."
            continue

        real_choices = [c for c in question.choices if c.text.strip()]
        if len(real_choices) < 2:
            return f"Question {index} needs at least two options."

        correct = [c for c in real_choices if c.is_correct]
        if not correct:
            return f"Question {index} has no correct option marked."
        if question.qtype in (QuestionType.single, QuestionType.truefalse) and len(correct) > 1:
            return f"Question {index} is single-choice but has {len(correct)} correct options."

    return None


# --------------------------------------------------------------------------
# Attempt bookkeeping used by listings
# --------------------------------------------------------------------------

def attempt_count(db, test_id: int, student_id: int) -> int:
    return (
        db.query(func.count(Attempt.id))
        .filter(Attempt.test_id == test_id, Attempt.student_id == student_id)
        .scalar()
        or 0
    )


def best_attempt(db, test_id: int, student_id: int):
    return (
        db.query(Attempt)
        .filter(
            Attempt.test_id == test_id,
            Attempt.student_id == student_id,
            Attempt.status != AttemptStatus.in_progress,
        )
        .order_by(Attempt.percent.desc())
        .first()
    )


def open_attempt(db, test_id: int, student_id: int):
    return (
        db.query(Attempt)
        .filter(
            Attempt.test_id == test_id,
            Attempt.student_id == student_id,
            Attempt.status == AttemptStatus.in_progress,
        )
        .order_by(Attempt.started_at.desc())
        .first()
    )


def student_attempts(db, student_id: int, limit: int | None = None):
    query = (
        db.query(Attempt)
        .filter(
            Attempt.student_id == student_id,
            Attempt.status != AttemptStatus.in_progress,
        )
        .order_by(Attempt.submitted_at.desc(), Attempt.id.desc())
    )
    return query.limit(limit).all() if limit else query.all()


def test_attempts(db, test_id: int):
    return (
        db.query(Attempt)
        .filter(
            Attempt.test_id == test_id,
            Attempt.status != AttemptStatus.in_progress,
        )
        .order_by(Attempt.percent.desc(), Attempt.submitted_at.desc())
        .all()
    )


def test_summary(db, test_id: int) -> dict:
    """Headline numbers for the teacher's results page."""
    rows = (
        db.query(
            func.count(Attempt.id),
            func.avg(Attempt.percent),
            func.max(Attempt.percent),
            func.sum(func.cast(Attempt.passed, Integer)),
        )
        .filter(Attempt.test_id == test_id, Attempt.status != AttemptStatus.in_progress)
        .first()
    )
    count, average, best, passed = rows or (0, None, None, None)
    count = count or 0
    return {
        "attempts": count,
        "average": round(average or 0, 1),
        "best": round(best or 0, 1),
        "passed": int(passed or 0),
        "pass_rate": round(((passed or 0) / count) * 100) if count else 0,
    }
