from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field

from app.models import Level


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
    identifier: str  # matric_no or admin username
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


# ---------- Exams / Questions ----------

class QuestionCreate(BaseModel):
    text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_option: str = Field(..., pattern="^[A-D]$")


class QuestionPublic(BaseModel):
    id: str
    text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str

    class Config:
        from_attributes = True


class QuestionAdminView(QuestionPublic):
    correct_option: str

    class Config:
        from_attributes = True


class ExaminationCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: Optional[str] = None
    duration_minutes: int = Field(..., gt=0, le=600)
    course_id: str


class ExaminationPublic(BaseModel):
    id: str
    title: str
    description: Optional[str]
    duration_minutes: int
    is_active: bool
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
    submitted_at: datetime
    checksum: str

    class Config:
        from_attributes = True


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
