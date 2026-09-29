"""Student-facing tests: browsing, taking and reviewing.

The important rule in this module is that nothing which could reveal an answer
key leaves the server while an attempt is open. The runner page is built from
``QuestionResponse``/``ChoiceResponse``, neither of which carries `is_correct`,
`explanation` or `numeric_answer`.
"""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Attempt, AttemptStatus, TestKind
from app.routers.auth import get_current_user, require_user_api
from app.schemas import AnswerSave
from app.services import assessment as assessment_service
from app.services import course as course_service
from app.services import grading
from app.templating import templates

router = APIRouter(tags=["tests"])


def _deny(request, current_user, message, status_code=403):
    return templates.TemplateResponse(
        request=request,
        name="errors/403.html",
        context={"current_user": current_user, "message": message},
        status_code=status_code,
    )


def _load_attempt(db, attempt_id: int, user):
    """Fetch an attempt owned by ``user``, applying the deadline first."""
    attempt = db.query(Attempt).filter(Attempt.id == attempt_id).first()
    if not attempt or attempt.student_id != user.id:
        return None
    grading.enforce_expiry(db, attempt)
    return attempt


# --------------------------------------------------------------------------
# Listing
# --------------------------------------------------------------------------

@router.get("/tests", response_class=HTMLResponse)
async def test_list(
    request: Request,
    kind: str = Query("practice"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    selected = TestKind.grand if kind == "grand" else TestKind.practice
    tests = assessment_service.list_available_tests(db, current_user.id, kind=selected)

    rows = []
    for test in tests:
        rows.append(
            {
                "test": test,
                "course": test.course,
                "attempts_used": assessment_service.attempt_count(
                    db, test.id, current_user.id
                ),
                "best": assessment_service.best_attempt(db, test.id, current_user.id),
                "open": assessment_service.open_attempt(db, test.id, current_user.id),
            }
        )

    counts = {
        "practice": len(
            assessment_service.list_available_tests(
                db, current_user.id, kind=TestKind.practice
            )
        ),
        "grand": len(
            assessment_service.list_available_tests(
                db, current_user.id, kind=TestKind.grand
            )
        ),
    }

    return templates.TemplateResponse(
        request=request,
        name="tests.html",
        context={
            "current_user": current_user,
            "rows": rows,
            "kind": selected.value,
            "counts": counts,
        },
    )


@router.get("/results", response_class=HTMLResponse)
async def results_history(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    attempts = assessment_service.student_attempts(db, current_user.id)

    passed = sum(1 for a in attempts if a.passed)
    average = round(sum(a.percent for a in attempts) / len(attempts), 1) if attempts else 0
    best = max((a.percent for a in attempts), default=0)

    # Oldest-first, capped, so the sparkline reads left to right.
    trend = [round(a.percent) for a in reversed(attempts)][-12:]

    return templates.TemplateResponse(
        request=request,
        name="results.html",
        context={
            "current_user": current_user,
            "attempts": attempts,
            "stats": {
                "total": len(attempts),
                "passed": passed,
                "average": average,
                "best": round(best, 1),
            },
            "trend": trend,
        },
    )


# --------------------------------------------------------------------------
# Taking a test
# --------------------------------------------------------------------------

@router.get("/tests/{test_id}/start")
async def start_test(
    test_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    test = assessment_service.get_test(db, test_id)
    if not test:
        return _deny(request, current_user, "That test no longer exists.", 404)

    course = course_service.get_course(db, test.course_id)
    try:
        course_service.require_access(db, course, current_user)
    except course_service.AccessDenied as exc:
        return _deny(request, current_user, str(exc))

    if not test.is_published and not course_service.can_manage(course, current_user):
        return _deny(request, current_user, "That test is not open yet.")

    try:
        attempt = grading.start_attempt(db, test, current_user)
    except grading.AttemptError as exc:
        return _deny(request, current_user, str(exc))

    return RedirectResponse(url=f"/attempts/{attempt.id}", status_code=302)


@router.get("/attempts/{attempt_id}", response_class=HTMLResponse)
async def attempt_runner(
    attempt_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    attempt = _load_attempt(db, attempt_id, current_user)
    if not attempt:
        return _deny(request, current_user, "That attempt does not exist.", 404)

    # Already finished (including auto-submitted while away): show the result.
    if attempt.is_finished:
        return RedirectResponse(url=f"/attempts/{attempt.id}/result", status_code=302)

    test = attempt.test
    questions = grading.question_order(test, attempt)
    saved = grading.answer_map(db, attempt)

    # The payload handed to quiz.js. Built by hand rather than from the ORM so
    # it is obvious at a glance that no answer key is included.
    payload = {
        "attemptId": attempt.id,
        "testId": test.id,
        "kind": test.kind.value,
        "isPractice": test.kind == TestKind.practice,
        "title": test.title,
        "passPercent": test.pass_percent,
        "negativeMarking": bool(test.negative_marking),
        "secondsRemaining": grading.seconds_remaining(attempt),
        "questions": [
            {
                "id": q.id,
                "number": index,
                "text": q.text,
                "type": q.qtype.value,
                "marks": q.marks,
                "negativeMarks": q.negative_marks if test.negative_marking else 0,
                "choices": [{"id": c.id, "text": c.text} for c in q.choices],
                "selected": (saved[q.id].selected_choice_ids or []) if q.id in saved else [],
                "numeric": saved[q.id].numeric_value if q.id in saved else None,
                "flagged": bool(saved[q.id].flagged) if q.id in saved else False,
            }
            for index, q in enumerate(questions, start=1)
        ],
    }

    return templates.TemplateResponse(
        request=request,
        name="attempt.html",
        context={
            "current_user": current_user,
            "attempt": attempt,
            "test": test,
            "course": test.course,
            "payload": payload,
        },
    )


@router.post("/api/attempts/{attempt_id}/answer/{question_id}")
async def save_answer(
    attempt_id: int,
    question_id: int,
    data: AnswerSave,
    db: Session = Depends(get_db),
    current_user=Depends(require_user_api),
):
    attempt = _load_attempt(db, attempt_id, current_user)
    if not attempt:
        return JSONResponse(status_code=404, content={"message": "Attempt not found."})

    question = next((q for q in attempt.test.questions if q.id == question_id), None)
    if not question:
        return JSONResponse(status_code=404, content={"message": "Question not found."})

    try:
        grading.save_answer(db, attempt, question, data)
    except grading.AttemptError as exc:
        # 409: the answer was fine, the attempt is simply over.
        return JSONResponse(status_code=409, content={"message": str(exc)})

    return {"saved": True, "secondsRemaining": grading.seconds_remaining(attempt)}


@router.post("/api/attempts/{attempt_id}/check/{question_id}")
async def check_answer(
    attempt_id: int,
    question_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_user_api),
):
    """Practice-mode instant feedback. Refused on grand tests by the service."""
    attempt = _load_attempt(db, attempt_id, current_user)
    if not attempt:
        return JSONResponse(status_code=404, content={"message": "Attempt not found."})

    question = next((q for q in attempt.test.questions if q.id == question_id), None)
    if not question:
        return JSONResponse(status_code=404, content={"message": "Question not found."})

    try:
        return grading.check_answer(db, attempt, question)
    except grading.AttemptError as exc:
        return JSONResponse(status_code=403, content={"message": str(exc)})


@router.post("/api/attempts/{attempt_id}/submit")
async def submit(
    attempt_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_user_api),
):
    attempt = _load_attempt(db, attempt_id, current_user)
    if not attempt:
        return JSONResponse(status_code=404, content={"message": "Attempt not found."})

    grading.submit_attempt(db, attempt)
    return {
        "submitted": True,
        "redirect": f"/attempts/{attempt.id}/result",
        "score": attempt.score,
        "percent": attempt.percent,
        "passed": attempt.passed,
    }


@router.get("/attempts/{attempt_id}/result", response_class=HTMLResponse)
async def attempt_result(
    attempt_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    attempt = _load_attempt(db, attempt_id, current_user)
    if not attempt:
        return _deny(request, current_user, "That attempt does not exist.", 404)

    if attempt.status == AttemptStatus.in_progress:
        return RedirectResponse(url=f"/attempts/{attempt.id}", status_code=302)

    rows = grading.review_rows(db, attempt)
    correct = sum(1 for r in rows if r["is_correct"])
    unanswered = sum(1 for r in rows if not r["answered"])

    return templates.TemplateResponse(
        request=request,
        name="result.html",
        context={
            "current_user": current_user,
            "attempt": attempt,
            "test": attempt.test,
            "course": attempt.test.course,
            "rows": rows,
            "correct": correct,
            "incorrect": len(rows) - correct - unanswered,
            "unanswered": unanswered,
            "attempts_used": assessment_service.attempt_count(
                db, attempt.test_id, current_user.id
            ),
        },
    )
