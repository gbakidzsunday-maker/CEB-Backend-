from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


# ---------- Auth ----------

class CandidateRegister(BaseModel):
    matric_no: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)


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


class ExaminationPublic(BaseModel):
    id: str
    title: str
    description: Optional[str]
    duration_minutes: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


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
