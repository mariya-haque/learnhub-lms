"""Chapters: the unit inside a subject that content is filed under.

Every relationship here is optional in one direction. A lecture, note or test
may sit in a chapter or not, and deleting a chapter unfiles its contents rather
than destroying them -- reorganising a syllabus must never be a way to lose a
term's work by accident.
"""

from sqlalchemy import func

from app.models import Chapter, Lecture, Note, Test


class ChapterError(Exception):
    """A refused chapter action. The message is safe to show a user."""


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------

def get_chapter(db, chapter_id: int) -> Chapter | None:
    return db.query(Chapter).filter(Chapter.id == chapter_id).first()


def list_chapters(db, course_id: int, published_only: bool = False) -> list[Chapter]:
    query = db.query(Chapter).filter(Chapter.course_id == course_id)
    if published_only:
        query = query.filter(Chapter.is_published.is_(True))
    return query.order_by(Chapter.order_index, Chapter.id).all()


def _next_order(db, course_id: int) -> int:
    current = (
        db.query(func.max(Chapter.order_index))
        .filter(Chapter.course_id == course_id)
        .scalar()
    )
    return (current or 0) + 1


# --------------------------------------------------------------------------
# Grouping
# --------------------------------------------------------------------------

def outline(
    db,
    course_id: int,
    lectures: list,
    notes: list,
    tests: list,
    published_only: bool = False,
) -> list[dict]:
    """Group a subject's content under its chapters, in syllabus order.

    Takes the already-fetched lists rather than re-querying, so a caller that
    has applied its own visibility rules (published-only for students,
    everything for the teacher) keeps them.

    Anything with no chapter lands in a trailing "Unfiled" group, which is
    exactly where content created before chapters existed belongs. That group
    is omitted when it would be empty.
    """
    chapters = list_chapters(db, course_id, published_only=published_only)

    groups = []
    for chapter in chapters:
        groups.append({
            "chapter": chapter,
            "lectures": [x for x in lectures if x.chapter_id == chapter.id],
            "notes": [x for x in notes if x.chapter_id == chapter.id],
            "practice": [t for t in tests
                         if t.chapter_id == chapter.id and t.kind.value == "practice"],
            "grand": [t for t in tests
                      if t.chapter_id == chapter.id and t.kind.value == "grand"],
        })

    unfiled = {
        "chapter": None,
        "lectures": [x for x in lectures if not x.chapter_id],
        "notes": [x for x in notes if not x.chapter_id],
        "practice": [t for t in tests
                     if not t.chapter_id and t.kind.value == "practice"],
        "grand": [t for t in tests if not t.chapter_id and t.kind.value == "grand"],
    }
    if any(unfiled[key] for key in ("lectures", "notes", "practice", "grand")):
        groups.append(unfiled)

    for group in groups:
        group["count"] = (
            len(group["lectures"]) + len(group["notes"])
            + len(group["practice"]) + len(group["grand"])
        )
    return groups


def chapter_stats(db, chapter_id: int) -> dict:
    def count(model):
        return (
            db.query(func.count(model.id))
            .filter(model.chapter_id == chapter_id)
            .scalar()
            or 0
        )

    return {
        "lectures": count(Lecture),
        "notes": count(Note),
        "tests": count(Test),
    }


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------

def create_chapter(db, course_id: int, data) -> Chapter:
    chapter = Chapter(
        course_id=course_id,
        title=data.title.strip(),
        description=(data.description or "").strip() or None,
        is_published=data.is_published,
        order_index=_next_order(db, course_id),
    )
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter


def update_chapter(db, chapter: Chapter, data) -> Chapter:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(chapter, field, value)
    db.commit()
    db.refresh(chapter)
    return chapter


def delete_chapter(db, chapter: Chapter) -> None:
    """Unfile the contents, then drop the chapter itself."""
    for model in (Lecture, Note, Test):
        db.query(model).filter(model.chapter_id == chapter.id).update(
            {"chapter_id": None}
        )
    db.delete(chapter)
    db.commit()


def reorder_chapters(db, course_id: int, ids: list[int]) -> None:
    chapters = {c.id: c for c in list_chapters(db, course_id)}
    for position, chapter_id in enumerate(ids, start=1):
        chapter = chapters.get(chapter_id)
        if chapter:
            chapter.order_index = position
    db.commit()


def assign(db, course_id: int, kind: str, item_id: int, chapter_id: int | None):
    """File one lecture, note or test under a chapter (or unfile it).

    ``chapter_id`` is verified to belong to the same course, so a teacher
    cannot file their content under someone else's chapter by editing the id.
    """
    models = {"lecture": Lecture, "note": Note, "test": Test}
    model = models.get(kind)
    if model is None:
        raise ChapterError("Unknown content type.")

    item = db.query(model).filter(
        model.id == item_id, model.course_id == course_id
    ).first()
    if item is None:
        raise ChapterError("That item is not part of this subject.")

    if chapter_id is not None:
        chapter = get_chapter(db, chapter_id)
        if chapter is None or chapter.course_id != course_id:
            raise ChapterError("That chapter is not part of this subject.")

    item.chapter_id = chapter_id
    db.commit()
    db.refresh(item)
    return item
