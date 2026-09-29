from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.assessment import AttemptStatus, QuestionType, TestKind


# --------------------------------------------------------------------------
# Teacher side -- authoring
# --------------------------------------------------------------------------

class ChoiceIn(BaseModel):
    text: str = Field(min_length=1)
    is_correct: bool = False


class QuestionIn(BaseModel):
    text: str = Field(min_length=1)
    qtype: QuestionType = QuestionType.single
    marks: float = Field(default=1.0, gt=0)
    negative_marks: float = Field(default=0.0, ge=0)
    explanation: str | None = None
    numeric_answer: float | None = None
    numeric_tolerance: float = Field(default=0.0, ge=0)
    choices: list[ChoiceIn] = []


class TestBase(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    description: str | None = None
    kind: TestKind = TestKind.practice
    duration_minutes: int | None = Field(default=None, ge=1, le=600)
    pass_percent: int = Field(default=40, ge=0, le=100)
    max_attempts: int | None = Field(default=None, ge=1)
    negative_marking: bool = False
    shuffle_questions: bool = False
    is_published: bool = False


class TestCreate(TestBase):
    pass


class TestUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = None
    kind: TestKind | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=600)
    pass_percent: int | None = Field(default=None, ge=0, le=100)
    max_attempts: int | None = Field(default=None, ge=1)
    negative_marking: bool | None = None
    shuffle_questions: bool | None = None
    is_published: bool | None = None


class TestSave(TestBase):
    """The builder posts the whole test -- settings and questions -- at once.

    Replacing the question set wholesale is far simpler to reason about than
    diffing it, and a test is small enough that the write cost is irrelevant.
    """

    questions: list[QuestionIn] = []


# --------------------------------------------------------------------------
# Student side -- reading
# --------------------------------------------------------------------------

class ChoiceResponse(BaseModel):
    """Note the deliberate absence of `is_correct`.

    This is the shape sent to a student mid-attempt; leaking the answer key
    here would defeat the whole feature.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    text: str


class QuestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_index: int
    text: str
    qtype: QuestionType
    marks: float
    negative_marks: float
    choices: list[ChoiceResponse] = []


class TestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    title: str
    description: str | None = None
    kind: TestKind
    duration_minutes: int | None = None
    pass_percent: int
    max_attempts: int | None = None
    negative_marking: bool
    is_published: bool


class AttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    test_id: int
    status: AttemptStatus
    started_at: datetime | None = None
    expires_at: datetime | None = None
    submitted_at: datetime | None = None
    score: float
    max_score: float
    percent: float
    passed: bool


class AnswerSave(BaseModel):
    """One autosaved answer. Every field is optional so the same endpoint
    handles selecting, clearing and flagging."""

    selected_choice_ids: list[int] | None = None
    numeric_value: float | None = None
    flagged: bool | None = None


class AnswerCheckResult(BaseModel):
    """Practice-mode instant feedback for a single question."""

    question_id: int
    is_correct: bool
    correct_choice_ids: list[int] = []
    correct_numeric: float | None = None
    explanation: str | None = None
    marks_awarded: float = 0.0
