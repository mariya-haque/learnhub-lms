"""Student-facing course catalogue and course detail."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.auth import get_current_user, require_user_api
from app.schemas import ReviewSave
from app.services import assessment as assessment_service
from app.services import chapter as chapter_service
from app.services import content as content_service
from app.services import course as course_service
from app.services import feedback as feedback_service
from app.templating import templates

router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("", response_class=HTMLResponse)
async def catalogue(
    request: Request,
    q: str | None = Query(None),
    subject: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    courses = course_service.list_published_courses(db, search=q, subject=subject)
    # Access by either route counts as "Enrolled" on a card -- a student who
    # joined a track should not be invited to enroll in what they already have.
    enrolled_ids = course_service.accessible_course_ids(db, current_user)

    ratings = feedback_service.summaries_for(db, [c.id for c in courses])

    cards = [
        {
            "course": course,
            "stats": course_service.course_stats(db, course.id),
            "enrolled": course.id in enrolled_ids,
            "rating": ratings.get(course.id, {"average": 0, "count": 0}),
        }
        for course in courses
    ]

    return templates.TemplateResponse(
        request=request,
        name="courses.html",
        context={
            "current_user": current_user,
            "cards": cards,
            "subjects": course_service.list_subjects(db),
            "q": q or "",
            "subject": subject or "",
        },
    )


@router.get("/{slug}", response_class=HTMLResponse)
async def course_detail(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    course = course_service.get_course_by_slug(db, slug)
    if not course:
        return templates.TemplateResponse(
            request=request,
            name="errors/404.html",
            context={"current_user": current_user},
            status_code=404,
        )

    manageable = course_service.can_manage(course, current_user)
    enrolled = course_service.is_enrolled(db, course.id, current_user.id)
    via_track = course_service.is_track_member(db, course, current_user.id)

    # An unpublished course is visible only to the person who owns it.
    if not course.is_published and not manageable:
        return templates.TemplateResponse(
            request=request,
            name="errors/403.html",
            context={
                "current_user": current_user,
                "message": "That course is not available yet.",
            },
            status_code=403,
        )

    has_access = manageable or enrolled or via_track
    published_only = not manageable

    lectures = content_service.list_lectures(db, course.id, published_only=published_only)
    notes = content_service.list_notes(db, course.id)
    tests = assessment_service.list_tests(db, course.id, published_only=published_only)

    # Progress is worth showing to anyone who can actually watch, however they
    # got in -- a track member has the same watch history as anyone else.
    tracking = enrolled or via_track
    progress = (
        content_service.progress_map(db, course.id, current_user.id) if tracking else {}
    )
    summary = (
        course_service.course_progress(db, course.id, current_user.id)
        if tracking
        else None
    )

    # Where "Continue" should send them: first unfinished lecture, else the first.
    resume = next(
        (lec for lec in lectures if not (progress.get(lec.id) and progress[lec.id].completed)),
        lectures[0] if lectures else None,
    )

    test_rows = [
        {
            "test": test,
            "attempts_used": assessment_service.attempt_count(db, test.id, current_user.id),
            "best": assessment_service.best_attempt(db, test.id, current_user.id),
            "open": assessment_service.open_attempt(db, test.id, current_user.id),
        }
        for test in tests
    ]

    return templates.TemplateResponse(
        request=request,
        name="course_detail.html",
        context={
            "current_user": current_user,
            "course": course,
            "lectures": lectures,
            "notes": notes,
            "outline": chapter_service.outline(
                db, course.id, lectures, notes, tests,
                published_only=published_only,
            ),
            "test_rows": test_rows,
            "progress": progress,
            "summary": summary,
            "enrolled": enrolled,
            "via_track": via_track,
            "track": course.track,
            "can_manage": manageable,
            "has_access": has_access,
            "resume": resume,
            "stats": course_service.course_stats(db, course.id),
            # A teacher moderating their own subject needs to see hidden rows too.
            "reviews": feedback_service.list_reviews(
                db, course.id, published_only=not manageable
            ),
            "rating": feedback_service.summary(db, course.id),
            "my_review": feedback_service.review_by(db, course.id, current_user.id),
            "can_review": (
                current_user.role.value == "student" and has_access and not manageable
            ),
        },
    )


# --------------------------------------------------------------------------
# Reviews
# --------------------------------------------------------------------------

@router.put("/{course_id}/review")
async def save_review(
    course_id: int,
    data: ReviewSave,
    db: Session = Depends(get_db),
    current_user=Depends(require_user_api),
):
    """Leave or update this student's review. One per subject, edited in place."""
    course = course_service.get_course(db, course_id)
    if not course:
        return JSONResponse(status_code=404, content={"message": "Subject not found."})

    try:
        review = feedback_service.upsert_review(db, course, current_user, data)
    except feedback_service.FeedbackError as exc:
        db.rollback()
        return JSONResponse(status_code=403, content={"message": str(exc)})

    return {
        "id": review.id,
        "rating": review.rating,
        "summary": feedback_service.summary(db, course.id),
        "message": "Thanks — your feedback is live.",
    }


@router.delete("/{course_id}/review")
async def remove_review(
    course_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_user_api),
):
    review = feedback_service.review_by(db, course_id, current_user.id)
    if not review:
        return JSONResponse(status_code=404, content={"message": "No review to remove."})

    feedback_service.delete_review(db, review)
    return {
        "message": "Review removed.",
        "summary": feedback_service.summary(db, course_id),
    }


@router.post("/{course_id}/enroll")
async def enroll(
    course_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_user_api),
):
    course = course_service.get_course(db, course_id)
    if not course:
        return JSONResponse(status_code=404, content={"message": "Course not found."})
    try:
        course_service.enroll(db, course, current_user)
    except course_service.AccessDenied as exc:
        return JSONResponse(status_code=403, content={"message": str(exc)})
    return {"message": "Enrolled", "slug": course.slug}


@router.post("/{course_id}/unenroll")
async def unenroll(
    course_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_user_api),
):
    course = course_service.get_course(db, course_id)
    if not course:
        return JSONResponse(status_code=404, content={"message": "Course not found."})
    course_service.unenroll(db, course, current_user)
    return {"message": "Removed"}


@router.get("/{slug}/enroll-redirect", response_class=RedirectResponse)
async def enroll_redirect(
    slug: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Non-JS fallback so enrolling still works without the fetch handler."""
    course = course_service.get_course_by_slug(db, slug)
    if course:
        try:
            course_service.enroll(db, course, current_user)
        except course_service.AccessDenied:
            pass
        return RedirectResponse(url=f"/courses/{course.slug}", status_code=302)
    return RedirectResponse(url="/courses", status_code=302)
