from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field

from app.models import Level, ExamStatus, ProctoringEventType


# ---------- Auth ----------

class CandidateRegister(BaseModel):
    matric_no: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)
    level: Level


class AdminRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    identifier: str  # matric_no, admin username, or parent phone_number
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class ParentRegister(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    address: str = Field(..., min_length=3, max_length=255)
    phone_number: str = Field(..., min_length=7, max_length=20)
    password: str = Field(..., min_length=8, max_length=128)
    # At least one of these must exactly match an existing candidate's
    # full_name (case-insensitive) or registration is rejected.
    children_names: list[str] = Field(..., min_length=1)


class ChildMatch(BaseModel):
    name_submitted: str
    matched: bool
    candidate_id: Optional[str] = None
    matric_no: Optional[str] = None


class ParentRegisterResponse(TokenResponse):
    children: list[ChildMatch]


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)


class AdminPasswordReset(BaseModel):
    """
    Both fields optional. If new_password is omitted, a random
    temporary password is generated and returned once in the response
    (it is never stored or logged in plaintext) — useful when an
    admin is resetting credentials for a candidate locked out in the
    exam hall and just needs *something* to hand them immediately.
    """
    new_password: Optional[str] = Field(None, min_length=8, max_length=128)


class AdminPasswordResetResponse(BaseModel):
    candidate_id: str
    temporary_password: str
    note: str = "Share this password with the candidate securely. It will not be shown again."


class CandidateMe(BaseModel):
    id: str
    matric_no: str
    email: EmailStr
    full_name: str
    level: Level
    is_active: bool
    created_at: datetime
    enrolled_courses: list["CoursePublic"]

    class Config:
        from_attributes = True


class ParentMe(BaseModel):
    id: str
    full_name: str
    address: str
    phone_number: str
    is_active: bool
    created_at: datetime
    children: list["ChildSummary"]

    class Config:
        from_attributes = True


# ---------- Exams / Questions ----------

class QuestionCreate(BaseModel):
    text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_option: str = Field(..., pattern="^[A-D]$")
    points: float = Field(1.0, gt=0)
    explanation: Optional[str] = None
    image_url: Optional[str] = None


class QuestionUpdate(BaseModel):
    """All fields optional — send only what you want to change."""
    text: Optional[str] = None
    option_a: Optional[str] = None
    option_b: Optional[str] = None
    option_c: Optional[str] = None
    option_d: Optional[str] = None
    correct_option: Optional[str] = Field(None, pattern="^[A-D]$")
    points: Optional[float] = Field(None, gt=0)
    explanation: Optional[str] = None
    image_url: Optional[str] = None


class QuestionPublic(BaseModel):
    id: str
    text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    points: float
    image_url: Optional[str] = None

    class Config:
        from_attributes = True


class QuestionAdminView(QuestionPublic):
    correct_option: str
    explanation: Optional[str] = None

    class Config:
        from_attributes = True


class BulkQuestionUploadResult(BaseModel):
    created: int
    failed: int
    errors: list[str] = []
    questions: list[QuestionAdminView] = []


class ExaminationCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: Optional[str] = None
    duration_minutes: int = Field(..., gt=0, le=600)
    course_id: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    pass_mark_percentage: int = Field(50, ge=0, le=100)
    shuffle_questions: bool = True
    shuffle_options: bool = True


class ExaminationUpdate(BaseModel):
    """All fields optional — send only what you want to change."""
    title: Optional[str] = Field(None, min_length=3, max_length=200)
    description: Optional[str] = None
    duration_minutes: Optional[int] = Field(None, gt=0, le=600)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    pass_mark_percentage: Optional[int] = Field(None, ge=0, le=100)
    shuffle_questions: Optional[bool] = None
    shuffle_options: Optional[bool] = None


class ExaminationPublic(BaseModel):
    id: str
    title: str
    description: Optional[str]
    duration_minutes: int
    is_active: bool
    status: ExamStatus
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    pass_mark_percentage: int
    shuffle_questions: bool
    shuffle_options: bool
    course_id: str
    level: Level
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Courses ----------

class CourseCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    code: str = Field(..., min_length=2, max_length=30)
    level: Level


class CourseUpdate(BaseModel):
    """All fields optional — send only what you want to change."""
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    code: Optional[str] = Field(None, min_length=2, max_length=30)


class CoursePublic(BaseModel):
    id: str
    name: str
    code: str
    level: Level
    created_at: datetime

    class Config:
        from_attributes = True


class CourseWithEnrollmentCount(CoursePublic):
    enrolled_candidates: int


class EnrollRequest(BaseModel):
    course_ids: list[str] = Field(..., min_length=1)


class EnrollResult(BaseModel):
    course_id: str
    enrolled: bool
    reason: Optional[str] = None


# ---------- Responses / Results ----------

class ResponseSubmit(BaseModel):
    question_id: str
    selected_option: str = Field(..., pattern="^[A-D]$")
    session_id: str


class ResponsePublic(BaseModel):
    id: str
    question_id: str
    selected_option: str
    submitted_at: datetime
    checksum: str

    class Config:
        from_attributes = True


class ResultPublic(BaseModel):
    id: str
    exam_id: str
    score: float
    total_questions: int
    max_score: float
    percentage: float
    terminated: bool
    submitted_at: datetime
    checksum: str

    class Config:
        from_attributes = True


class QuestionBreakdown(BaseModel):
    question_id: str
    text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    candidate_selected: Optional[str] = None
    correct_option: str
    is_correct: bool
    points_possible: float
    points_earned: float
    explanation: Optional[str] = None
    image_url: Optional[str] = None


class ResultBreakdown(BaseModel):
    result: ResultPublic
    questions: list[QuestionBreakdown]


class ExamResultRow(BaseModel):
    """One row of an admin's exam-wide results / rank sheet."""
    result_id: str
    candidate_id: str
    matric_no: str
    full_name: str
    score: float
    total_questions: int
    max_score: float
    percentage: float
    passed: bool
    terminated: bool
    submitted_at: datetime
    rank: int


class ExamResultsSummary(BaseModel):
    exam_id: str
    exam_title: str
    pass_mark_percentage: int
    submissions: int
    average_percentage: float
    highest_percentage: float
    lowest_percentage: float
    results: list[ExamResultRow]


# ---------- Security ----------

class SecurityLogPublic(BaseModel):
    id: str
    event_type: str
    actor: Optional[str]
    ip_address: Optional[str]
    endpoint: Optional[str]
    details: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class IntegrityCheckResult(BaseModel):
    record_id: str
    table: str
    stored_checksum: str
    recomputed_checksum: str
    intact: bool


# ---------- Anti-cheat / proctoring ----------

class ProctoringEventSubmit(BaseModel):
    event_type: ProctoringEventType
    strike_count: int = Field(..., ge=1, le=3)
    timestamp: datetime


class ProctoringEventResponse(BaseModel):
    exam_id: str
    strikes: int
    terminated: bool


# ---------- Admin: student profile & management ----------

class CandidateAdminView(BaseModel):
    id: str
    matric_no: str
    email: EmailStr
    full_name: str
    level: Level
    is_active: bool
    is_locked: bool
    failed_login_attempts: int
    created_at: datetime

    class Config:
        from_attributes = True


class CandidateAdminDetail(CandidateAdminView):
    enrolled_courses: list[CoursePublic]


class CandidateUpdate(BaseModel):
    """All fields optional — send only what you want to change."""
    full_name: Optional[str] = Field(None, min_length=2, max_length=100)
    email: Optional[EmailStr] = None
    level: Optional[Level] = None


class ResultWithExam(ResultPublic):
    exam_title: str


class BulkStudentImportResult(BaseModel):
    created: int
    failed: int
    errors: list[str] = []
    students: list[CandidateAdminView] = []


# ---------- Parent portal ----------

class ChildSummary(BaseModel):
    id: str
    matric_no: str
    full_name: str
    level: Level

    class Config:
        from_attributes = True


class ChildExamStatus(BaseModel):
    exam_id: str
    title: str
    course_id: str
    level: Level
    duration_minutes: int
    is_active: bool
    done: bool
    result: Optional[ResultPublic] = None


class ParentLinkChildRequest(BaseModel):
    matric_no: str = Field(..., min_length=3, max_length=50)


CandidateMe.model_rebuild()
ParentMe.model_rebuild()
