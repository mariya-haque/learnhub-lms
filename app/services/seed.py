"""First-run demo data.

Runs on every startup but only ever creates what is missing, so restarting the
app never duplicates anything. The point is that a fresh clone is immediately
clickable -- there is a course to open, a lecture to play and two tests to sit
before anyone has uploaded a single file.

Set SEED_DEMO_DATA=false to turn it off.
"""

from datetime import datetime, timedelta, timezone

from app.models import (
    Chapter,
    Choice,
    ClassSession,
    Course,
    Lecture,
    MeetingProvider,
    Plan,
    Question,
    QuestionType,
    Review,
    Role,
    SubStatus,
    Subscription,
    Test,
    TestKind,
    Track,
    TrackEnrollment,
)
from app.services.auth import ensure_user
from app.services.content import create_url_lecture
from app.services.course import enroll, unique_slug
from app.services.schedule import new_room_name
from app.schemas.content import LectureCreate

DEMO_ACCOUNTS = [
    ("admin", "admin123", Role.admin, "Site Admin"),
    ("teacher", "teacher123", Role.teacher, "Priya Sharma"),
    ("student", "student123", Role.student, "Aarav Patel"),
]

LECTURES = [
    (
        "What a function really is",
        "Mappings, domain and range -- the mental model everything else builds on.",
        "https://www.youtube.com/watch?v=52tpYl2tTqk",
    ),
    (
        "Limits, intuitively",
        "Approaching a value without arriving at it, and why that is useful.",
        "https://www.youtube.com/watch?v=riXcZT2ICjA",
    ),
    (
        "The derivative from first principles",
        "Building the difference quotient up from the slope of a straight line.",
        "https://www.youtube.com/watch?v=9vKqVkMQHKk",
    ),
]

PRACTICE_QUESTIONS = [
    {
        "text": "If f(x) = 3x + 2, what is f(4)?",
        "qtype": QuestionType.single,
        "marks": 1,
        "explanation": "Substitute x = 4: 3(4) + 2 = 12 + 2 = 14.",
        "choices": [("12", False), ("14", True), ("18", False), ("20", False)],
    },
    {
        "text": "A function must assign exactly one output to each input.",
        "qtype": QuestionType.truefalse,
        "marks": 1,
        "explanation": "That single-valued requirement is what separates a function "
                       "from a general relation.",
        "choices": [("True", True), ("False", False)],
    },
    {
        "text": "Which of these are polynomials? (Select all that apply.)",
        "qtype": QuestionType.multi,
        "marks": 2,
        "explanation": "A polynomial has only non-negative integer powers of x, so "
                       "1/x and sqrt(x) are both out.",
        "choices": [
            ("x^2 - 4x + 1", True),
            ("1/x", False),
            ("7", True),
            ("sqrt(x) + 2", False),
        ],
    },
    {
        "text": "What is the derivative of x^2 with respect to x?",
        "qtype": QuestionType.single,
        "marks": 1,
        "explanation": "The power rule: d/dx of x^n is n*x^(n-1), so x^2 becomes 2x.",
        "choices": [("x", False), ("2x", True), ("x^2", False), ("2", False)],
    },
    {
        "text": "Evaluate the limit of (x^2 - 9)/(x - 3) as x approaches 3.",
        "qtype": QuestionType.numeric,
        "marks": 2,
        "explanation": "Factor the numerator: (x-3)(x+3)/(x-3) = x + 3, which tends "
                       "to 6 as x approaches 3.",
        "numeric_answer": 6,
    },
]

GRAND_QUESTIONS = [
    {
        "text": "If f(x) = x^2 and g(x) = x + 1, what is f(g(2))?",
        "qtype": QuestionType.single,
        "marks": 2,
        "negative_marks": 0.5,
        "explanation": "Work outward-in: g(2) = 3, then f(3) = 9.",
        "choices": [("5", False), ("7", False), ("9", True), ("4", False)],
    },
    {
        "text": "The domain of f(x) = 1/(x - 2) excludes which value?",
        "qtype": QuestionType.numeric,
        "marks": 2,
        "negative_marks": 0.5,
        "explanation": "The denominator vanishes at x = 2, so the function is "
                       "undefined there.",
        "numeric_answer": 2,
    },
    {
        "text": "Which statements about continuity are true? (Select all that apply.)",
        "qtype": QuestionType.multi,
        "marks": 3,
        "negative_marks": 1,
        "explanation": "Continuity requires the limit to exist, the value to exist, "
                       "and the two to agree. Differentiability implies continuity, "
                       "but not the reverse -- |x| at 0 is the standard counterexample.",
        "choices": [
            ("A differentiable function is always continuous", True),
            ("A continuous function is always differentiable", False),
            ("Continuity requires the limit to equal the function value", True),
            ("Polynomials are continuous everywhere", True),
        ],
    },
    {
        "text": "d/dx of 5x^3 is 15x^2.",
        "qtype": QuestionType.truefalse,
        "marks": 1,
        "negative_marks": 0.25,
        "explanation": "The power rule gives 5 * 3 * x^2 = 15x^2.",
        "choices": [("True", True), ("False", False)],
    },
    {
        "text": "What is the slope of the tangent to y = x^2 at x = 3?",
        "qtype": QuestionType.numeric,
        "marks": 2,
        "negative_marks": 0.5,
        "explanation": "dy/dx = 2x, so at x = 3 the slope is 6.",
        "numeric_answer": 6,
    },
    {
        "text": "Which rule differentiates a product of two functions?",
        "qtype": QuestionType.single,
        "marks": 2,
        "negative_marks": 0.5,
        "explanation": "The product rule: (uv)' = u'v + uv'.",
        "choices": [
            ("The chain rule", False),
            ("The product rule", True),
            ("The quotient rule", False),
            ("The power rule", False),
        ],
    },
    {
        "text": "The limit of a function at a point always equals the function's value there.",
        "qtype": QuestionType.truefalse,
        "marks": 1,
        "negative_marks": 0.25,
        "explanation": "Only for continuous functions. A removable discontinuity has "
                       "a limit that differs from -- or exists without -- the value.",
        "choices": [("True", False), ("False", True)],
    },
    {
        "text": "If f'(x) > 0 on an interval, the function is ...",
        "qtype": QuestionType.single,
        "marks": 2,
        "negative_marks": 0.5,
        "explanation": "A positive derivative means the slope is positive throughout, "
                       "so the function increases.",
        "choices": [
            ("Decreasing", False),
            ("Increasing", True),
            ("Constant", False),
            ("Undefined", False),
        ],
    },
]


def _add_questions(db, test: Test, specs: list[dict]) -> None:
    for index, spec in enumerate(specs, start=1):
        question = Question(
            test_id=test.id,
            order_index=index,
            text=spec["text"],
            qtype=spec["qtype"],
            marks=spec.get("marks", 1),
            negative_marks=spec.get("negative_marks", 0) if test.negative_marking else 0,
            explanation=spec.get("explanation"),
            numeric_answer=spec.get("numeric_answer"),
            numeric_tolerance=spec.get("numeric_tolerance", 0),
        )
        db.add(question)
        db.flush()

        for c_index, (text, is_correct) in enumerate(spec.get("choices", []), start=1):
            db.add(
                Choice(
                    question_id=question.id,
                    order_index=c_index,
                    text=text,
                    is_correct=is_correct,
                )
            )


# Live classes, positioned relative to whenever the seeder first runs so the
# demo always has one starting imminently rather than a date in 2026 that has
# long since passed. (offset from now, duration, title, description, provider)
DEMO_CLASSES = [
    (
        timedelta(days=-2, hours=-1), 60,
        "Welcome and course walkthrough",
        "How the course is laid out, and how the tests are marked.",
        MeetingProvider.builtin,
    ),
    (
        timedelta(minutes=5), 45,
        "Live doubt-clearing session",
        "Bring anything from the limits lecture that did not land. "
        "Camera optional, questions compulsory.",
        MeetingProvider.builtin,
    ),
    (
        timedelta(days=1, hours=2), 60,
        "Derivatives workshop",
        "Working through the difference quotient together, slowly.",
        MeetingProvider.builtin,
    ),
    (
        timedelta(days=3), 45,
        "Grand test strategy briefing",
        "Negative marking, pacing, and what to skip. Hosted on Google Meet.",
        MeetingProvider.external,
    ),
]


def _ensure_class_sessions(db, course: Course, teacher) -> None:
    """Add the demo timetable, once.

    Guarded on the course having no classes at all rather than on the course
    being new, so a database seeded before the calendar existed picks these up
    on the next restart.
    """
    if db.query(ClassSession).filter(ClassSession.course_id == course.id).first():
        return

    now = datetime.now(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)

    for offset, minutes, title, description, provider in DEMO_CLASSES:
        session = ClassSession(
            course_id=course.id,
            teacher_id=teacher.id,
            title=title,
            description=description,
            starts_at=now + offset,
            duration_minutes=minutes,
            provider=provider,
        )
        if provider == MeetingProvider.external:
            session.meeting_url = "https://meet.google.com/xyz-demo-link"
        else:
            session.room_name = new_room_name()
        db.add(session)

    db.commit()


# --------------------------------------------------------------------------
# Tracks
#
# One programme (ECAT) with two subjects, each broken into chapters, so the
# track -> subject -> chapter -> content shape is visible immediately. The
# standalone Calculus course is deliberately left outside any track: a course
# with no track still has to work, and this is what proves it.
# --------------------------------------------------------------------------

ECAT_SUBJECTS = [
    {
        "title": "Physics — ECAT",
        "subject": "Physics",
        "accent": "blue",
        "description": "Mechanics, waves and electromagnetism at ECAT depth.",
        "chapters": [
            {
                "title": "Kinematics",
                "description": "Motion in a straight line, graphs, and projectiles.",
                "lectures": [
                    ("Displacement, velocity, acceleration",
                     "The three quantities every later problem is built from.",
                     "https://www.youtube.com/watch?v=ZM8ECpBuQYE"),
                    ("Projectile motion",
                     "Splitting a two-dimensional problem into two one-dimensional ones.",
                     "https://www.youtube.com/watch?v=bqYtNrhWy5Y"),
                ],
                "practice": {
                    "title": "Kinematics — Practice",
                    "questions": [
                        {
                            "text": "A body starts from rest and accelerates at 2 m/s^2. "
                                    "What is its speed after 5 s?",
                            "qtype": QuestionType.numeric,
                            "marks": 2,
                            "explanation": "v = u + at = 0 + 2(5) = 10 m/s.",
                            "numeric_answer": 10,
                        },
                        {
                            "text": "At the highest point of a projectile's path, its "
                                    "vertical velocity is zero.",
                            "qtype": QuestionType.truefalse,
                            "marks": 1,
                            "explanation": "Vertical velocity reverses sign there, so it "
                                           "passes through zero. Horizontal velocity is "
                                           "unchanged throughout.",
                            "choices": [("True", True), ("False", False)],
                        },
                        {
                            "text": "The area under a velocity-time graph gives ...",
                            "qtype": QuestionType.single,
                            "marks": 1,
                            "explanation": "Area = velocity x time = displacement. The "
                                           "gradient, not the area, gives acceleration.",
                            "choices": [
                                ("Acceleration", False),
                                ("Displacement", True),
                                ("Force", False),
                                ("Momentum", False),
                            ],
                        },
                    ],
                },
            },
            {
                "title": "Newton's Laws",
                "description": "Force, mass and the equation everything reduces to.",
                "lectures": [
                    ("The three laws, carefully",
                     "What each law actually claims, and the usual misreadings.",
                     "https://www.youtube.com/watch?v=g_TEuAB0T5A"),
                ],
                "practice": {
                    "title": "Newton's Laws — Practice",
                    "questions": [
                        {
                            "text": "A 4 kg mass experiences a net force of 12 N. "
                                    "What is its acceleration in m/s^2?",
                            "qtype": QuestionType.numeric,
                            "marks": 2,
                            "explanation": "a = F/m = 12/4 = 3 m/s^2.",
                            "numeric_answer": 3,
                        },
                        {
                            "text": "Which are true of an action-reaction pair? "
                                    "(Select all that apply.)",
                            "qtype": QuestionType.multi,
                            "marks": 2,
                            "explanation": "They are equal in magnitude, opposite in "
                                           "direction, and act on *different* bodies -- "
                                           "which is why they never cancel.",
                            "choices": [
                                ("Equal in magnitude", True),
                                ("Opposite in direction", True),
                                ("Act on the same body", False),
                                ("Act on different bodies", True),
                            ],
                        },
                    ],
                },
            },
        ],
        "grand": {
            "title": "Physics — Full Grand Test",
            "chapter": None,
            "questions": [
                {
                    "text": "A car travels 100 m in 5 s at constant speed. "
                            "What is that speed in m/s?",
                    "qtype": QuestionType.numeric,
                    "marks": 2,
                    "negative_marks": 0.5,
                    "explanation": "v = s/t = 100/5 = 20 m/s.",
                    "numeric_answer": 20,
                },
                {
                    "text": "The SI unit of force is the newton, equal to ...",
                    "qtype": QuestionType.single,
                    "marks": 2,
                    "negative_marks": 0.5,
                    "explanation": "F = ma, so 1 N = 1 kg x 1 m/s^2.",
                    "choices": [
                        ("kg m/s", False),
                        ("kg m/s^2", True),
                        ("kg m^2/s^2", False),
                        ("kg/s^2", False),
                    ],
                },
                {
                    "text": "Momentum is conserved in every collision, elastic or not.",
                    "qtype": QuestionType.truefalse,
                    "marks": 2,
                    "negative_marks": 0.5,
                    "explanation": "Momentum is always conserved with no external force. "
                                   "Kinetic energy is what an inelastic collision loses.",
                    "choices": [("True", True), ("False", False)],
                },
            ],
        },
    },
    {
        "title": "Chemistry — ECAT",
        "subject": "Chemistry",
        "accent": "teal",
        "description": "Atomic structure, bonding and stoichiometry.",
        "chapters": [
            {
                "title": "Atomic Structure",
                "description": "Shells, subshells and where the periodic table comes from.",
                "lectures": [
                    ("Electron configuration",
                     "Filling order, and why it is not simply left to right.",
                     "https://www.youtube.com/watch?v=Aoi4j8es4gQ"),
                ],
                "practice": {
                    "title": "Atomic Structure — Practice",
                    "questions": [
                        {
                            "text": "How many electrons does a neutral carbon atom have?",
                            "qtype": QuestionType.numeric,
                            "marks": 1,
                            "explanation": "Carbon's atomic number is 6, and a neutral "
                                           "atom has as many electrons as protons.",
                            "numeric_answer": 6,
                        },
                        {
                            "text": "Which subshell fills immediately after 4s?",
                            "qtype": QuestionType.single,
                            "marks": 2,
                            "explanation": "By the Aufbau order, 3d fills after 4s -- "
                                           "the reason the first transition series exists.",
                            "choices": [("4p", False), ("3d", True),
                                        ("5s", False), ("4d", False)],
                        },
                    ],
                },
            },
            {
                "title": "Chemical Bonding",
                "description": "Ionic, covalent and metallic bonds, and what decides which.",
                "lectures": [
                    ("Ionic vs covalent",
                     "Electronegativity difference as the deciding quantity.",
                     "https://www.youtube.com/watch?v=QqjcCvzWwww"),
                ],
                "practice": {
                    "title": "Bonding — Practice",
                    "questions": [
                        {
                            "text": "A large electronegativity difference between two "
                                    "atoms favours an ionic bond.",
                            "qtype": QuestionType.truefalse,
                            "marks": 1,
                            "explanation": "A big difference means one atom takes the "
                                           "electrons outright rather than sharing them.",
                            "choices": [("True", True), ("False", False)],
                        },
                    ],
                },
            },
        ],
        "grand": {
            "title": "Chemistry — Full Grand Test",
            "chapter": None,
            "questions": [
                {
                    "text": "What is the atomic number of oxygen?",
                    "qtype": QuestionType.numeric,
                    "marks": 2,
                    "negative_marks": 0.5,
                    "explanation": "Oxygen has 8 protons.",
                    "numeric_answer": 8,
                },
                {
                    "text": "Which bond type involves a sea of delocalised electrons?",
                    "qtype": QuestionType.single,
                    "marks": 2,
                    "negative_marks": 0.5,
                    "explanation": "Metallic bonding -- and it is what makes metals "
                                   "conduct and deform without shattering.",
                    "choices": [("Ionic", False), ("Covalent", False),
                                ("Metallic", True), ("Hydrogen", False)],
                },
            ],
        },
    },
]

# Chapters for the standalone Calculus course, so content that predates
# chapters gets filed rather than sitting forever in "Unfiled".
CALCULUS_CHAPTERS = [
    ("Functions and Limits", "Where the course starts: mappings and approaching values.",
     ["What a function really is", "Limits, intuitively"],
     ["Functions and Limits -- Practice"]),
    ("Derivatives", "Rates of change, from first principles to the power rule.",
     ["The derivative from first principles"],
     ["Calculus Foundations -- Grand Test"]),
]


def _make_chapter(db, course: Course, title: str, description: str, order: int) -> Chapter:
    chapter = Chapter(
        course_id=course.id,
        title=title,
        description=description,
        order_index=order,
        is_published=True,
    )
    db.add(chapter)
    db.flush()
    return chapter


def _ensure_calculus_chapters(db, course: Course) -> None:
    """File the original demo course's content into two chapters."""
    if db.query(Chapter).filter(Chapter.course_id == course.id).first():
        return

    for order, (title, desc, lecture_titles, test_titles) in enumerate(
        CALCULUS_CHAPTERS, start=1
    ):
        chapter = _make_chapter(db, course, title, desc, order)
        db.query(Lecture).filter(
            Lecture.course_id == course.id, Lecture.title.in_(lecture_titles)
        ).update({"chapter_id": chapter.id}, synchronize_session=False)
        db.query(Test).filter(
            Test.course_id == course.id, Test.title.in_(test_titles)
        ).update({"chapter_id": chapter.id}, synchronize_session=False)

    db.commit()


def _ensure_ecat_track(db, teacher, student) -> None:
    """Build the ECAT programme, once."""
    existing = db.query(Track).filter(Track.slug == "ecat-engineering").first()
    if existing:
        _ensure_plans(db, existing, student)
        return

    track = Track(
        title="ECAT Engineering",
        slug="ecat-engineering",
        code="ECAT",
        description=(
            "Entry test preparation for engineering programmes. Each subject is "
            "split into chapters, and every chapter carries its own videos, "
            "practice test and notes, with a full-length grand test per subject."
        ),
        accent="indigo",
        created_by=teacher.id,
        is_published=True,
    )
    db.add(track)
    db.flush()

    for spec in ECAT_SUBJECTS:
        course = Course(
            title=spec["title"],
            slug=unique_slug(db, spec["title"]),
            description=spec["description"],
            subject=spec["subject"],
            accent=spec["accent"],
            teacher_id=teacher.id,
            track_id=track.id,
            is_published=True,
        )
        db.add(course)
        db.flush()

        for order, chapter_spec in enumerate(spec["chapters"], start=1):
            chapter = _make_chapter(
                db, course, chapter_spec["title"], chapter_spec["description"], order
            )

            for title, description, url in chapter_spec["lectures"]:
                lecture = create_url_lecture(
                    db,
                    course.id,
                    LectureCreate(
                        title=title,
                        description=description,
                        video_url=url,
                        is_published=True,
                    ),
                )
                lecture.chapter_id = chapter.id

            practice_spec = chapter_spec.get("practice")
            if practice_spec:
                practice = Test(
                    course_id=course.id,
                    chapter_id=chapter.id,
                    title=practice_spec["title"],
                    description="Untimed and unlimited, with an explanation on every answer.",
                    kind=TestKind.practice,
                    pass_percent=50,
                    negative_marking=False,
                    is_published=True,
                )
                db.add(practice)
                db.flush()
                _add_questions(db, practice, practice_spec["questions"])

        grand_spec = spec.get("grand")
        if grand_spec:
            grand = Test(
                course_id=course.id,
                chapter_id=None,   # covers the whole subject, not one chapter
                title=grand_spec["title"],
                description="Timed, one attempt, negative marking on.",
                kind=TestKind.grand,
                duration_minutes=45,
                pass_percent=40,
                max_attempts=1,
                negative_marking=True,
                is_published=True,
            )
            db.add(grand)
            db.flush()
            _add_questions(db, grand, grand_spec["questions"])

    db.commit()

    # Put the demo student in the track so the whole programme is unlocked.
    membership = TrackEnrollment(track_id=track.id, student_id=student.id)
    db.add(membership)
    db.commit()

    _ensure_plans(db, track, student)


# Prices in minor units (paisa): 250000 = Rs 2,500.
DEMO_PLANS = [
    ("Monthly", "Full access to every subject in this track.", 250_000, 30),
    ("Quarterly", "Three months, at two months' price.", 500_000, 90),
    ("Annual", "The whole exam season, and the best rate.", 1_800_000, 365),
]


def _ensure_plans(db, track: Track, student) -> None:
    """Price the demo track, and leave one request waiting for the admin.

    The track itself stays free (``requires_subscription`` is left off) so that
    adding billing does not paywall a demo somebody is already showing people.
    Flipping that one switch in the track's settings turns the whole thing on.
    """
    if db.query(Plan).filter(Plan.track_id == track.id).first():
        return

    plans = []
    for order, (name, description, price_minor, days) in enumerate(DEMO_PLANS, start=1):
        plan = Plan(
            track_id=track.id,
            name=name,
            description=description,
            price_minor=price_minor,
            currency="PKR",
            duration_days=days,
            order_index=order,
            is_active=True,
        )
        db.add(plan)
        plans.append(plan)
    db.flush()

    # One pending request, so the admin console opens with something real to do.
    monthly = plans[0]
    db.add(
        Subscription(
            student_id=student.id,
            track_id=track.id,
            plan_id=monthly.id,
            status=SubStatus.pending,
            price_minor=monthly.price_minor,
            currency=monthly.currency,
            plan_name=monthly.name,
            requested_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
    )
    db.commit()


# A few reviews so the ratings are not all zero on a fresh install. Keyed by
# course slug; only ever written for students who actually exist.
DEMO_REVIEWS = {
    "calculus-foundations": [
        (5, "The limits lecture finally made it click. Practice test explanations "
            "are worth more than the videos, honestly."),
    ],
    "physics-ecat": [
        (4, "Kinematics chapter is excellent. The grand test is harder than the "
            "real ECAT, which I think is the point."),
    ],
}


def _ensure_reviews(db, student) -> None:
    """Seed one review per demo subject, once."""
    if db.query(Review).first():
        return

    for slug, entries in DEMO_REVIEWS.items():
        course = db.query(Course).filter(Course.slug == slug).first()
        if not course:
            continue
        for rating, comment in entries:
            db.add(
                Review(
                    course_id=course.id,
                    student_id=student.id,
                    rating=rating,
                    comment=comment,
                    is_published=True,
                )
            )
    db.commit()


def seed(db) -> None:
    """Create the demo accounts, and the sample course if it is not there."""
    users = {}
    for username, password, role, full_name in DEMO_ACCOUNTS:
        users[username] = ensure_user(
            db,
            username=username,
            password=password,
            role=role,
            full_name=full_name,
            email=f"{username}@learnhub.test",
        )

    teacher = users["teacher"]
    student = users["student"]

    # One marker course. If it exists, the seeder has already run.
    existing = db.query(Course).filter(Course.slug == "calculus-foundations").first()
    if existing:
        _ensure_class_sessions(db, existing, teacher)
        _ensure_calculus_chapters(db, existing)
        _ensure_ecat_track(db, teacher, student)
        _ensure_reviews(db, student)
        return

    course = Course(
        title="Calculus Foundations",
        slug=unique_slug(db, "Calculus Foundations"),
        description=(
            "A gentle first pass at functions, limits and derivatives. Watch the "
            "lectures in order, skim the notes, then use the practice test to check "
            "yourself before attempting the timed grand test."
        ),
        subject="Mathematics",
        accent="indigo",
        teacher_id=teacher.id,
        is_published=True,
    )
    db.add(course)
    db.commit()
    db.refresh(course)

    for title, description, url in LECTURES:
        create_url_lecture(
            db,
            course.id,
            LectureCreate(
                title=title,
                description=description,
                video_url=url,
                is_published=True,
            ),
        )

    practice = Test(
        course_id=course.id,
        title="Functions and Limits -- Practice",
        description=(
            "Untimed and unlimited. Each answer is checked the moment you pick it, "
            "with an explanation."
        ),
        kind=TestKind.practice,
        duration_minutes=None,
        pass_percent=50,
        max_attempts=None,
        negative_marking=False,
        is_published=True,
    )
    db.add(practice)
    db.flush()
    _add_questions(db, practice, PRACTICE_QUESTIONS)

    grand = Test(
        course_id=course.id,
        title="Calculus Foundations -- Grand Test",
        description=(
            "30 minutes, one attempt, negative marking on. Answers stay hidden "
            "until you submit."
        ),
        kind=TestKind.grand,
        duration_minutes=30,
        pass_percent=40,
        max_attempts=1,
        negative_marking=True,
        shuffle_questions=False,
        is_published=True,
    )
    db.add(grand)
    db.flush()
    _add_questions(db, grand, GRAND_QUESTIONS)

    db.commit()

    # Put the demo student in the course so their dashboard is not empty.
    enroll(db, course, student)

    _ensure_class_sessions(db, course, teacher)
    _ensure_calculus_chapters(db, course)
    _ensure_ecat_track(db, teacher, student)
    _ensure_reviews(db, student)
