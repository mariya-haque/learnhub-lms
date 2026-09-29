"""The student's home screen."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Lecture, LectureProgress, TestKind
from app.routers.auth import get_current_user
from app.services import assessment as assessment_service
from app.services import course as course_service
from app.templating import templates

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Teachers have their own home; send them there rather than showing an
    # empty student dashboard.
    if current_user.is_teacher:
        return RedirectResponse(url="/teach", status_code=302)

    courses = course_service.list_courses_for_student(db, current_user)

    cards = []
    for course in courses:
        cards.append(
            {
                "course": course,
                "progress": course_service.course_progress(db, course.id, current_user.id),
                "stats": course_service.course_stats(db, course.id),
            }
        )
    cards.sort(key=lambda c: c["progress"]["percent"])

    # Continue watching: the most recently touched, still-unfinished lecture.
    resume_row = (
        db.query(LectureProgress, Lecture)
        .join(Lecture, Lecture.id == LectureProgress.lecture_id)
        .filter(
            LectureProgress.student_id == current_user.id,
            LectureProgress.completed.is_(False),
            Lecture.is_published.is_(True),
        )
        .order_by(LectureProgress.updated_at.desc())
        .first()
    )
    resume = None
    if resume_row:
        entry, lecture = resume_row
        resume = {
            "lecture": lecture,
            "course": lecture.course,
            "position": entry.last_position_seconds or 0,
            "percent": round(
                ((entry.last_position_seconds or 0) / lecture.duration_seconds) * 100
            )
            if lecture.duration_seconds
            else 0,
        }
    elif cards:
        from app.services import content as content_service

        first = next(
            (
                lec
                for card in cards
                for lec in content_service.list_lectures(
                    db, card["course"].id, published_only=True
                )
            ),
            None,
        )
        if first:
            resume = {"lecture": first, "course": first.course, "position": 0, "percent": 0}

    attempts = assessment_service.student_attempts(db, current_user.id, limit=5)
    all_attempts = assessment_service.student_attempts(db, current_user.id)

    practice = assessment_service.list_available_tests(
        db, current_user.id, kind=TestKind.practice
    )
    grand = assessment_service.list_available_tests(
        db, current_user.id, kind=TestKind.grand
    )

    # A grand test the student has not yet sat is the thing most worth surfacing.
    pending = [
        t for t in grand if assessment_service.attempt_count(db, t.id, current_user.id) == 0
    ][:4]

    average = (
        round(sum(a.percent for a in all_attempts) / len(all_attempts), 1)
        if all_attempts
        else 0
    )
    lectures_done = sum(c["progress"]["completed"] for c in cards)
    lectures_total = sum(c["progress"]["total"] for c in cards)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "current_user": current_user,
            "cards": cards,
            "resume": resume,
            "attempts": attempts,
            "pending": pending,
            "trend": [round(a.percent) for a in reversed(all_attempts)][-10:],
            "stats": {
                "courses": len(cards),
                "lectures_done": lectures_done,
                "lectures_total": lectures_total,
                "lectures_percent": round((lectures_done / lectures_total) * 100)
                if lectures_total
                else 0,
                "tests_taken": len(all_attempts),
                "average": average,
                "practice_available": len(practice),
                "grand_available": len(grand),
            },
        },
    )
