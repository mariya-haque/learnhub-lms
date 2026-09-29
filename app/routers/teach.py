"""The teacher studio: courses, lectures, notes and the test builder.

Every route here is gated twice -- once by role (`require_teacher`) and once by
ownership (`course_service.require_manage`), because being a teacher does not
make someone a teacher *of this course*.
"""

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Attempt, AttemptStatus, Test
from app.routers.auth import require_teacher, require_teacher_api
from app.schemas import (
    ChapterAssign,
    ChapterCreate,
    ChapterUpdate,
    PlanCreate,
    PlanUpdate,
    ClassSessionCreate,
    ClassSessionUpdate,
    CourseCreate,
    CourseUpdate,
    LectureCreate,
    LectureUpdate,
    NoteUpdate,
    ReorderPayload,
    ReviewModerate,
    SubjectLink,
    TestCreate,
    TestSave,
    TrackCreate,
    TrackUpdate,
)
from app.services import assessment as assessment_service
from app.services import billing as billing_service
from app.services import chapter as chapter_service
from app.services import content as content_service
from app.services import course as course_service
from app.services import feedback as feedback_service
from app.services import grading, storage
from app.services import schedule as schedule_service
from app.services import track as track_service
from app.templating import templates

router = APIRouter(prefix="/teach", tags=["teach"])


def _forbidden(message: str):
    return JSONResponse(status_code=403, content={"message": message})


def _owned(db: Session, course_id: int, user):
    """Return the course if ``user`` may manage it, else raise AccessDenied."""
    return course_service.require_manage(course_service.get_course(db, course_id), user)


def _deny_page(request, current_user, message, status_code=403):
    return templates.TemplateResponse(
        request=request,
        name="errors/403.html",
        context={"current_user": current_user, "message": message},
        status_code=status_code,
    )


# --------------------------------------------------------------------------
# Studio home
# --------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
async def studio(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher),
):
    courses = course_service.list_courses_for_teacher(db, current_user)

    cards = [
        {"course": course, "stats": course_service.course_stats(db, course.id)}
        for course in courses
    ]

    course_ids = [c.id for c in courses]
    recent = []
    averages = []
    if course_ids:
        recent = (
            db.query(Attempt)
            .join(Test, Test.id == Attempt.test_id)
            .filter(
                Test.course_id.in_(course_ids),
                Attempt.status != AttemptStatus.in_progress,
            )
            .order_by(Attempt.submitted_at.desc())
            .limit(8)
            .all()
        )
        averages = [a.percent for a in
            db.query(Attempt)
            .join(Test, Test.id == Attempt.test_id)
            .filter(
                Test.course_id.in_(course_ids),
                Attempt.status != AttemptStatus.in_progress,
            )
            .all()
        ]

    totals = {
        "courses": len(courses),
        "students": sum(c["stats"]["students"] for c in cards),
        "lectures": sum(c["stats"]["lectures"] for c in cards),
        "tests": sum(c["stats"]["tests"] for c in cards),
        "average": round(sum(averages) / len(averages), 1) if averages else 0,
        "submissions": len(averages),
    }

    return templates.TemplateResponse(
        request=request,
        name="teach/studio.html",
        context={
            "current_user": current_user,
            "cards": cards,
            "recent": recent,
            "totals": totals,
        },
    )


# --------------------------------------------------------------------------
# Courses
# --------------------------------------------------------------------------

@router.post("/api/courses")
async def api_create_course(
    data: CourseCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    try:
        course = course_service.create_course(db, data, current_user)
        return {"id": course.id, "slug": course.slug, "redirect": f"/teach/courses/{course.id}"}
    except Exception as exc:
        db.rollback()
        return JSONResponse(status_code=400, content={"message": str(exc)})


@router.get("/courses/{course_id}", response_class=HTMLResponse)
async def manage_course(
    course_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher),
):
    try:
        course = _owned(db, course_id, current_user)
    except course_service.AccessDenied as exc:
        return _deny_page(request, current_user, str(exc))

    lectures = content_service.list_lectures(db, course.id)
    notes = content_service.list_notes(db, course.id)
    tests = assessment_service.list_tests(db, course.id)

    return templates.TemplateResponse(
        request=request,
        name="teach/course.html",
        context={
            "current_user": current_user,
            "course": course,
            "lectures": lectures,
            "notes": notes,
            "tests": tests,
            "chapters": chapter_service.list_chapters(db, course.id),
            "outline": chapter_service.outline(db, course.id, lectures, notes, tests),
            "stats": course_service.course_stats(db, course.id),
            "test_summaries": {t.id: assessment_service.test_summary(db, t.id) for t in tests},
            "max_video_mb": storage.MAX_MB[storage.VIDEOS],
            "max_note_mb": storage.MAX_MB[storage.NOTES],
        },
    )


@router.put("/api/courses/{course_id}")
async def api_update_course(
    course_id: int,
    data: CourseUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    try:
        course = _owned(db, course_id, current_user)
        course_service.update_course(db, course, data)
        return {"id": course.id, "slug": course.slug}
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))
    except Exception as exc:
        db.rollback()
        return JSONResponse(status_code=400, content={"message": str(exc)})


@router.delete("/api/courses/{course_id}")
async def api_delete_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    try:
        course = _owned(db, course_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))

    # Collect the stored files before the rows cascade away.
    videos = [lec.stored_filename for lec in course.lectures if lec.stored_filename]
    notes = [note.stored_filename for note in course.notes]

    course_service.delete_course(db, course)

    for name in videos:
        storage.delete_upload(storage.VIDEOS, name)
    for name in notes:
        storage.delete_upload(storage.NOTES, name)

    return {"message": "Course deleted"}


# --------------------------------------------------------------------------
# Lectures
# --------------------------------------------------------------------------

@router.post("/api/courses/{course_id}/lectures/url")
async def api_add_url_lecture(
    course_id: int,
    data: LectureCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    try:
        _owned(db, course_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))

    kind, _ = content_service.normalise_embed_url(data.video_url)
    if kind == "link":
        return JSONResponse(
            status_code=400,
            content={
                "message": "That link cannot be embedded. Use a YouTube or Vimeo link, "
                           "or a direct .mp4 URL."
            },
        )

    lecture = content_service.create_url_lecture(db, course_id, data)
    return {"id": lecture.id, "title": lecture.title}


@router.post("/api/courses/{course_id}/lectures/upload")
async def api_upload_lecture(
    course_id: int,
    title: str = Form(...),
    description: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    try:
        _owned(db, course_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))

    try:
        stored, original, size = storage.save_upload(file, storage.VIDEOS)
    except storage.UploadError as exc:
        return JSONResponse(status_code=400, content={"message": str(exc)})

    lecture = content_service.create_upload_lecture(
        db,
        course_id=course_id,
        title=title.strip() or original,
        description=description.strip() or None,
        stored_name=stored,
        original_name=original,
        size=size,
    )
    return {"id": lecture.id, "title": lecture.title}


@router.put("/api/lectures/{lecture_id}")
async def api_update_lecture(
    lecture_id: int,
    data: LectureUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    lecture = content_service.get_lecture(db, lecture_id)
    if not lecture:
        return JSONResponse(status_code=404, content={"message": "Lecture not found."})
    try:
        _owned(db, lecture.course_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))

    # Swapping an upload for a URL leaves an orphan file behind otherwise.
    old_file = lecture.stored_filename if data.video_url else None

    content_service.update_lecture(db, lecture, data)

    if old_file and lecture.source_type.value == "url":
        storage.delete_upload(storage.VIDEOS, old_file)
        lecture.stored_filename = None
        db.commit()

    return {"id": lecture.id, "title": lecture.title}


@router.delete("/api/lectures/{lecture_id}")
async def api_delete_lecture(
    lecture_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    lecture = content_service.get_lecture(db, lecture_id)
    if not lecture:
        return JSONResponse(status_code=404, content={"message": "Lecture not found."})
    try:
        _owned(db, lecture.course_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))

    stored = lecture.stored_filename
    content_service.delete_lecture(db, lecture)
    storage.delete_upload(storage.VIDEOS, stored)
    return {"message": "Lecture deleted"}


@router.post("/api/courses/{course_id}/lectures/reorder")
async def api_reorder_lectures(
    course_id: int,
    data: ReorderPayload,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    try:
        _owned(db, course_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))
    content_service.reorder_lectures(db, course_id, data.ids)
    return {"message": "Reordered"}


# --------------------------------------------------------------------------
# Notes
# --------------------------------------------------------------------------

@router.post("/api/courses/{course_id}/notes")
async def api_upload_note(
    course_id: int,
    title: str = Form(""),
    description: str = Form(""),
    lecture_id: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    try:
        _owned(db, course_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))

    try:
        stored, original, size = storage.save_upload(file, storage.NOTES)
    except storage.UploadError as exc:
        return JSONResponse(status_code=400, content={"message": str(exc)})

    attached = int(lecture_id) if lecture_id.strip().isdigit() else None

    note = content_service.create_note(
        db,
        course_id=course_id,
        title=title.strip() or original,
        description=description.strip() or None,
        stored_name=stored,
        original_name=original,
        size=size,
        content_type=file.content_type,
        lecture_id=attached,
    )
    return {"id": note.id, "title": note.title}


@router.put("/api/notes/{note_id}")
async def api_update_note(
    note_id: int,
    data: NoteUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    note = content_service.get_note(db, note_id)
    if not note:
        return JSONResponse(status_code=404, content={"message": "Note not found."})
    try:
        _owned(db, note.course_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))
    content_service.update_note(db, note, data)
    return {"id": note.id, "title": note.title}


@router.delete("/api/notes/{note_id}")
async def api_delete_note(
    note_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    note = content_service.get_note(db, note_id)
    if not note:
        return JSONResponse(status_code=404, content={"message": "Note not found."})
    try:
        _owned(db, note.course_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))

    stored = note.stored_filename
    content_service.delete_note(db, note)
    storage.delete_upload(storage.NOTES, stored)
    return {"message": "Note deleted"}


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

@router.post("/api/courses/{course_id}/tests")
async def api_create_test(
    course_id: int,
    data: TestCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    try:
        _owned(db, course_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))
    test = assessment_service.create_test(db, course_id, data)
    return {"id": test.id, "redirect": f"/teach/tests/{test.id}/edit"}


@router.get("/tests/{test_id}/edit", response_class=HTMLResponse)
async def edit_test(
    test_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher),
):
    test = assessment_service.get_test(db, test_id)
    if not test:
        return _deny_page(request, current_user, "That test no longer exists.", 404)
    try:
        course = _owned(db, test.course_id, current_user)
    except course_service.AccessDenied as exc:
        return _deny_page(request, current_user, str(exc))

    # Editing questions after people have sat the test would invalidate their
    # marks, so the builder locks itself once attempts exist.
    attempts = len(assessment_service.test_attempts(db, test.id))

    payload = {
        "id": test.id,
        "title": test.title,
        "description": test.description or "",
        "kind": test.kind.value,
        "durationMinutes": test.duration_minutes,
        "passPercent": test.pass_percent,
        "maxAttempts": test.max_attempts,
        "negativeMarking": bool(test.negative_marking),
        "shuffleQuestions": bool(test.shuffle_questions),
        "isPublished": bool(test.is_published),
        "locked": attempts > 0,
        "questions": [
            {
                "text": q.text,
                "qtype": q.qtype.value,
                "marks": q.marks,
                "negativeMarks": q.negative_marks,
                "explanation": q.explanation or "",
                "numericAnswer": q.numeric_answer,
                "numericTolerance": q.numeric_tolerance,
                "choices": [
                    {"text": c.text, "isCorrect": bool(c.is_correct)} for c in q.choices
                ],
            }
            for q in test.questions
        ],
    }

    return templates.TemplateResponse(
        request=request,
        name="teach/test_builder.html",
        context={
            "current_user": current_user,
            "course": course,
            "test": test,
            "payload": payload,
            "attempts": attempts,
        },
    )


@router.put("/api/tests/{test_id}")
async def api_save_test(
    test_id: int,
    data: TestSave,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    test = assessment_service.get_test(db, test_id)
    if not test:
        return JSONResponse(status_code=404, content={"message": "Test not found."})
    try:
        _owned(db, test.course_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))

    if assessment_service.test_attempts(db, test.id):
        return JSONResponse(
            status_code=409,
            content={
                "message": "Students have already sat this test, so its questions are "
                           "locked. Duplicate it to make changes."
            },
        )

    problem = assessment_service.validate_questions(data)
    if problem:
        return JSONResponse(status_code=400, content={"message": problem})

    try:
        assessment_service.save_test(db, test, data)
    except Exception as exc:
        db.rollback()
        return JSONResponse(status_code=400, content={"message": str(exc)})

    return {"id": test.id, "questions": len(test.questions), "totalMarks": test.total_marks}


@router.delete("/api/tests/{test_id}")
async def api_delete_test(
    test_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    test = assessment_service.get_test(db, test_id)
    if not test:
        return JSONResponse(status_code=404, content={"message": "Test not found."})
    try:
        _owned(db, test.course_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))
    assessment_service.delete_test(db, test)
    return {"message": "Test deleted"}


@router.get("/tests/{test_id}/results", response_class=HTMLResponse)
async def test_results(
    test_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher),
):
    test = assessment_service.get_test(db, test_id)
    if not test:
        return _deny_page(request, current_user, "That test no longer exists.", 404)
    try:
        course = _owned(db, test.course_id, current_user)
    except course_service.AccessDenied as exc:
        return _deny_page(request, current_user, str(exc))

    return templates.TemplateResponse(
        request=request,
        name="teach/test_results.html",
        context={
            "current_user": current_user,
            "course": course,
            "test": test,
            "attempts": assessment_service.test_attempts(db, test.id),
            "summary": assessment_service.test_summary(db, test.id),
            "difficulty": grading.question_difficulty(db, test),
        },
    )


# --------------------------------------------------------------------------
# Tracks
#
# A track is owned by whoever created it. Adding a subject needs *both* rights:
# manage of the track, and ownership of the course being filed into it, so a
# teacher can neither dump courses into someone else's programme nor claim a
# course they do not teach.
# --------------------------------------------------------------------------

def _owned_track(db: Session, track_id: int, user):
    return track_service.require_manage(track_service.get_track(db, track_id), user)


@router.get("/tracks/{track_id}", response_class=HTMLResponse)
async def manage_track(
    track_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher),
):
    try:
        track = _owned_track(db, track_id, current_user)
    except course_service.AccessDenied as exc:
        return _deny_page(request, current_user, str(exc))

    subjects = track_service.list_subjects(db, track.id)

    # Courses this teacher owns that are not in any track yet -- the only ones
    # offered in the "add a subject" picker.
    available = [
        c
        for c in course_service.list_courses_for_teacher(db, current_user)
        if c.track_id is None
    ]

    return templates.TemplateResponse(
        request=request,
        name="teach/track.html",
        context={
            "current_user": current_user,
            "track": track,
            "rows": [
                {
                    "subject": s,
                    "stats": course_service.course_stats(db, s.id),
                    "chapters": chapter_service.list_chapters(db, s.id),
                    "mine": course_service.can_manage(s, current_user),
                }
                for s in subjects
            ],
            "available": available,
            "plans": billing_service.list_plans(db, track.id),
            "subscribers": billing_service.list_all(db, track_id=track.id),
            "stats": track_service.track_stats(db, track.id),
        },
    )


@router.post("/api/tracks")
async def api_create_track(
    data: TrackCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    track = track_service.create_track(db, data, current_user)
    return {
        "id": track.id,
        "slug": track.slug,
        "redirect": f"/teach/tracks/{track.id}",
    }


@router.put("/api/tracks/{track_id}")
async def api_update_track(
    track_id: int,
    data: TrackUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    try:
        track = _owned_track(db, track_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))
    track_service.update_track(db, track, data)
    return {"id": track.id, "slug": track.slug}


@router.delete("/api/tracks/{track_id}")
async def api_delete_track(
    track_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    """Deletes the grouping only -- its subjects are detached, never destroyed."""
    try:
        track = _owned_track(db, track_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))

    freed = len(track_service.list_subjects(db, track.id))
    try:
        track_service.delete_track(db, track)
    except course_service.AccessDenied as exc:
        # 409: the caller may manage this track, it simply is not removable --
        # subscriptions were sold against it and that history has to survive.
        db.rollback()
        return JSONResponse(status_code=409, content={"message": str(exc)})

    return {"message": f"Track deleted. {freed} subject(s) kept and unfiled."}


@router.post("/api/tracks/{track_id}/subjects")
async def api_add_subject(
    track_id: int,
    data: SubjectLink,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    try:
        track = _owned_track(db, track_id, current_user)
        course = _owned(db, data.course_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))

    if course.track_id and course.track_id != track.id:
        return JSONResponse(
            status_code=409,
            content={"message": "That subject already belongs to another track."},
        )

    track_service.add_subject(db, track, course)
    return {"id": course.id, "title": course.title}


@router.delete("/api/tracks/{track_id}/subjects/{course_id}")
async def api_remove_subject(
    track_id: int,
    course_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    try:
        _owned_track(db, track_id, current_user)
        course = _owned(db, course_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))

    track_service.remove_subject(db, course)
    return {"message": "Subject removed from the track."}


# --------------------------------------------------------------------------
# Feedback
#
# Moderation is a visibility switch and nothing more. There is deliberately no
# endpoint that edits a review's text -- a teacher who could rewrite what a
# student said would make every rating on the site worthless.
# --------------------------------------------------------------------------

@router.get("/feedback", response_class=HTMLResponse)
async def feedback_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher),
):
    reviews = feedback_service.reviews_for_teacher(db, current_user)
    courses = course_service.list_courses_for_teacher(db, current_user)
    summaries = feedback_service.summaries_for(db, [c.id for c in courses])

    published = [r for r in reviews if r.is_published]
    overall = (
        round(sum(r.rating for r in published) / len(published), 1) if published else 0
    )

    return templates.TemplateResponse(
        request=request,
        name="teach/feedback.html",
        context={
            "current_user": current_user,
            "reviews": reviews,
            "rows": [
                {"course": c, "rating": summaries.get(c.id, {"average": 0, "count": 0})}
                for c in courses
            ],
            "overall": overall,
            "total": len(published),
            "hidden": len(reviews) - len(published),
        },
    )


@router.post("/api/reviews/{review_id}/moderate")
async def api_moderate_review(
    review_id: int,
    data: ReviewModerate,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    review = feedback_service.get_review(db, review_id)
    if not review:
        return JSONResponse(status_code=404, content={"message": "Review not found."})
    try:
        feedback_service.require_moderate(db, review, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))

    feedback_service.set_published(db, review, data.is_published)
    return {
        "id": review.id,
        "is_published": review.is_published,
        "message": "Review hidden." if not review.is_published else "Review restored.",
        "summary": feedback_service.summary(db, review.course_id),
    }


# --------------------------------------------------------------------------
# Plans
#
# What a track costs. Prices arrive in minor units so nothing rounds on the
# way in; the form does the multiplication, not the server.
# --------------------------------------------------------------------------

@router.post("/api/tracks/{track_id}/plans")
async def api_create_plan(
    track_id: int,
    data: PlanCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    try:
        track = _owned_track(db, track_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))
    plan = billing_service.create_plan(db, track, data)
    return {"id": plan.id, "name": plan.name}


@router.put("/api/plans/{plan_id}")
async def api_update_plan(
    plan_id: int,
    data: PlanUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    plan = billing_service.get_plan(db, plan_id)
    if not plan:
        return JSONResponse(status_code=404, content={"message": "Plan not found."})
    try:
        _owned_track(db, plan.track_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))
    billing_service.update_plan(db, plan, data)
    return {"id": plan.id, "name": plan.name}


@router.delete("/api/plans/{plan_id}")
async def api_delete_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    """Withdraw a plan. Subscriptions sold on it keep their own snapshot."""
    plan = billing_service.get_plan(db, plan_id)
    if not plan:
        return JSONResponse(status_code=404, content={"message": "Plan not found."})
    try:
        _owned_track(db, plan.track_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))
    billing_service.delete_plan(db, plan)
    return {"message": "Plan removed. Existing subscriptions are unaffected."}


# --------------------------------------------------------------------------
# Chapters
# --------------------------------------------------------------------------

def _owned_chapter(db: Session, chapter_id: int, user):
    chapter = chapter_service.get_chapter(db, chapter_id)
    if not chapter:
        return None
    _owned(db, chapter.course_id, user)
    return chapter


@router.post("/api/courses/{course_id}/chapters")
async def api_create_chapter(
    course_id: int,
    data: ChapterCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    try:
        _owned(db, course_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))
    chapter = chapter_service.create_chapter(db, course_id, data)
    return {"id": chapter.id, "title": chapter.title, "order": chapter.order_index}


@router.put("/api/chapters/{chapter_id}")
async def api_update_chapter(
    chapter_id: int,
    data: ChapterUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    try:
        chapter = _owned_chapter(db, chapter_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))
    if not chapter:
        return JSONResponse(status_code=404, content={"message": "Chapter not found."})
    chapter_service.update_chapter(db, chapter, data)
    return {"id": chapter.id, "title": chapter.title}


@router.delete("/api/chapters/{chapter_id}")
async def api_delete_chapter(
    chapter_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    try:
        chapter = _owned_chapter(db, chapter_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))
    if not chapter:
        return JSONResponse(status_code=404, content={"message": "Chapter not found."})

    stats = chapter_service.chapter_stats(db, chapter.id)
    chapter_service.delete_chapter(db, chapter)
    moved = stats["lectures"] + stats["notes"] + stats["tests"]
    return {
        "message": "Chapter deleted."
                   + (f" {moved} item(s) moved to Unfiled." if moved else "")
    }


@router.post("/api/courses/{course_id}/chapters/reorder")
async def api_reorder_chapters(
    course_id: int,
    data: ReorderPayload,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    try:
        _owned(db, course_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))
    chapter_service.reorder_chapters(db, course_id, data.ids)
    return {"message": "Reordered"}


@router.post("/api/courses/{course_id}/chapters/assign")
async def api_assign_to_chapter(
    course_id: int,
    data: ChapterAssign,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    """File one lecture, note or test under a chapter (null = unfile)."""
    try:
        _owned(db, course_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))

    try:
        chapter_service.assign(db, course_id, data.kind, data.item_id, data.chapter_id)
    except chapter_service.ChapterError as exc:
        return JSONResponse(status_code=400, content={"message": str(exc)})

    return {"message": "Moved."}


# --------------------------------------------------------------------------
# Live classes
#
# Gated the same way as everything else here: the role check lets a teacher in,
# and `_owned` proves it is *their* course before anything is written.
# --------------------------------------------------------------------------

def _owned_session(db: Session, session_id: int, user):
    """Return (session, course) when ``user`` may manage the class."""
    session = schedule_service.get_session(db, session_id)
    if not session:
        return None, None
    course = _owned(db, session.course_id, user)
    return session, course


@router.post("/api/classes")
async def api_create_class(
    data: ClassSessionCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    try:
        course = _owned(db, data.course_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))

    try:
        session = schedule_service.create_session(db, course, data, current_user)
    except schedule_service.ScheduleError as exc:
        db.rollback()
        return JSONResponse(status_code=400, content={"message": str(exc)})

    return {
        "id": session.id,
        "event": schedule_service.to_payload(session, current_user, course),
    }


@router.put("/api/classes/{session_id}")
async def api_update_class(
    session_id: int,
    data: ClassSessionUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    try:
        session, course = _owned_session(db, session_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))
    if not session:
        return JSONResponse(status_code=404, content={"message": "Class not found."})

    try:
        schedule_service.update_session(db, session, data)
    except schedule_service.ScheduleError as exc:
        db.rollback()
        return JSONResponse(status_code=400, content={"message": str(exc)})

    return {
        "id": session.id,
        "event": schedule_service.to_payload(session, current_user, course),
    }


@router.post("/api/classes/{session_id}/cancel")
async def api_cancel_class(
    session_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    """Cancel rather than remove: students who planned around it see why."""
    try:
        session, course = _owned_session(db, session_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))
    if not session:
        return JSONResponse(status_code=404, content={"message": "Class not found."})

    schedule_service.cancel_session(db, session)
    return {
        "id": session.id,
        "event": schedule_service.to_payload(session, current_user, course),
    }


@router.delete("/api/classes/{session_id}")
async def api_delete_class(
    session_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher_api),
):
    try:
        session, _ = _owned_session(db, session_id, current_user)
    except course_service.AccessDenied as exc:
        return _forbidden(str(exc))
    if not session:
        return JSONResponse(status_code=404, content={"message": "Class not found."})

    schedule_service.delete_session(db, session)
    return {"message": "Class removed"}


@router.get("/courses/{course_id}/students", response_class=HTMLResponse)
async def course_students(
    course_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_teacher),
):
    try:
        course = _owned(db, course_id, current_user)
    except course_service.AccessDenied as exc:
        return _deny_page(request, current_user, str(exc))

    rows = []
    for enrollment in course.enrollments:
        student = enrollment.student
        attempts = [
            a
            for a in student.attempts
            if a.test.course_id == course.id and a.status != AttemptStatus.in_progress
        ]
        rows.append(
            {
                "student": student,
                "enrolled_at": enrollment.enrolled_at,
                "progress": course_service.course_progress(db, course.id, student.id),
                "attempts": len(attempts),
                "average": round(sum(a.percent for a in attempts) / len(attempts), 1)
                if attempts
                else 0,
            }
        )
    rows.sort(key=lambda r: r["progress"]["percent"], reverse=True)

    return templates.TemplateResponse(
        request=request,
        name="teach/students.html",
        context={"current_user": current_user, "course": course, "rows": rows},
    )
