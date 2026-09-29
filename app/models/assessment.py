import enum

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class TestKind(str, enum.Enum):
    practice = "practice"   # untimed, unlimited retries, answers revealed as you go
    grand = "grand"         # timed, one attempt, answers withheld until submitted


class QuestionType(str, enum.Enum):
    single = "single"        # radio, one correct choice
    multi = "multi"          # checkboxes, all-correct-none-wrong
    truefalse = "truefalse"  # two fixed choices
    numeric = "numeric"      # a typed number within a tolerance


class AttemptStatus(str, enum.Enum):
    in_progress = "in_progress"
    submitted = "submitted"
    expired = "expired"      # the clock ran out; auto-scored from what was saved


class Test(Base):
    __tablename__ = "tests"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    # Null means the test covers the whole subject rather than one chapter.
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    kind = Column(Enum(TestKind), nullable=False, default=TestKind.practice, index=True)

    # Null = untimed. Practice tests are normally untimed, grand tests are not.
    duration_minutes = Column(Integer, nullable=True)
    pass_percent = Column(Integer, default=40)
    # Null = unlimited attempts.
    max_attempts = Column(Integer, nullable=True)
    negative_marking = Column(Boolean, default=False)
    shuffle_questions = Column(Boolean, default=False)
    is_published = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    course = relationship("Course", back_populates="tests")
    chapter = relationship("Chapter", back_populates="tests")
    questions = relationship(
        "Question",
        back_populates="test",
        cascade="all, delete-orphan",
        order_by="Question.order_index",
    )
    attempts = relationship(
        "Attempt", back_populates="test", cascade="all, delete-orphan"
    )

    @property
    def total_marks(self) -> float:
        return sum(q.marks or 0 for q in self.questions)

    @property
    def question_count(self) -> int:
        return len(self.questions)

    @property
    def is_practice(self) -> bool:
        return self.kind == TestKind.practice


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    test_id = Column(Integer, ForeignKey("tests.id"), nullable=False, index=True)
    order_index = Column(Integer, default=0, index=True)
    text = Column(Text, nullable=False)
    qtype = Column(Enum(QuestionType), nullable=False, default=QuestionType.single)
    marks = Column(Float, default=1.0)
    negative_marks = Column(Float, default=0.0)
    explanation = Column(Text, nullable=True)

    # Numeric questions only.
    numeric_answer = Column(Float, nullable=True)
    numeric_tolerance = Column(Float, default=0.0)

    test = relationship("Test", back_populates="questions")
    choices = relationship(
        "Choice",
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="Choice.order_index",
    )

    @property
    def correct_choice_ids(self) -> list[int]:
        return [c.id for c in self.choices if c.is_correct]


class Choice(Base):
    __tablename__ = "choices"

    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False, index=True)
    order_index = Column(Integer, default=0)
    text = Column(Text, nullable=False)
    is_correct = Column(Boolean, default=False)

    question = relationship("Question", back_populates="choices")


class Attempt(Base):
    __tablename__ = "attempts"

    id = Column(Integer, primary_key=True, index=True)
    test_id = Column(Integer, ForeignKey("tests.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    started_at = Column(DateTime(timezone=True), server_default=func.now())
    # Null on untimed tests. This, not the browser clock, is what ends a test.
    expires_at = Column(DateTime(timezone=True), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)

    score = Column(Float, default=0.0)
    max_score = Column(Float, default=0.0)
    percent = Column(Float, default=0.0)
    passed = Column(Boolean, default=False)
    status = Column(
        Enum(AttemptStatus), nullable=False, default=AttemptStatus.in_progress, index=True
    )

    test = relationship("Test", back_populates="attempts")
    student = relationship("User", back_populates="attempts")
    answers = relationship(
        "Answer", back_populates="attempt", cascade="all, delete-orphan"
    )

    @property
    def is_open(self) -> bool:
        return self.status == AttemptStatus.in_progress

    @property
    def is_finished(self) -> bool:
        return self.status in (AttemptStatus.submitted, AttemptStatus.expired)


class Answer(Base):
    __tablename__ = "answers"

    id = Column(Integer, primary_key=True, index=True)
    attempt_id = Column(Integer, ForeignKey("attempts.id"), nullable=False, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False, index=True)

    # A list even for single-choice questions, so one column covers every type.
    selected_choice_ids = Column(JSON, default=list)
    numeric_value = Column(Float, nullable=True)
    flagged = Column(Boolean, default=False)

    # Filled in at scoring time (and immediately for practice tests).
    is_correct = Column(Boolean, nullable=True)
    marks_awarded = Column(Float, default=0.0)

    attempt = relationship("Attempt", back_populates="answers")
    question = relationship("Question")

    @property
    def is_answered(self) -> bool:
        return bool(self.selected_choice_ids) or self.numeric_value is not None
