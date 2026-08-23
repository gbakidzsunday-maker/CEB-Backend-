import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, Enum
)
from sqlalchemy.orm import relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Role(str, enum.Enum):
    candidate = "candidate"
    admin = "admin"


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(String, primary_key=True, default=_uuid)
    matric_no = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)

    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    responses = relationship("Response", back_populates="candidate")
    results = relationship("Result", back_populates="candidate")


class Administrator(Base):
    __tablename__ = "administrators"

    id = Column(String, primary_key=True, default=_uuid)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)

    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    exams = relationship("Examination", back_populates="created_by_admin")


class Examination(Base):
    __tablename__ = "examinations"

    id = Column(String, primary_key=True, default=_uuid)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    duration_minutes = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True)

    created_by = Column(String, ForeignKey("administrators.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    created_by_admin = relationship("Administrator", back_populates="exams")
    questions = relationship("Question", back_populates="examination", cascade="all, delete-orphan")
    responses = relationship("Response", back_populates="examination")
    results = relationship("Result", back_populates="examination")


class Question(Base):
    __tablename__ = "questions"

    id = Column(String, primary_key=True, default=_uuid)
    exam_id = Column(String, ForeignKey("examinations.id"), nullable=False)
    text = Column(Text, nullable=False)
    option_a = Column(String, nullable=False)
    option_b = Column(String, nullable=False)
    option_c = Column(String, nullable=False)
    option_d = Column(String, nullable=False)
    # Never sent to candidates via the API — see schemas.QuestionPublic
    correct_option = Column(String, nullable=False)

    examination = relationship("Examination", back_populates="questions")
    responses = relationship("Response", back_populates="question")


class Response(Base):
    """
    A single candidate answer, persisted the moment it is submitted
    (real-time capture), together with a checksum over its own
    contents for tamper detection (Section 3.5.3 of the design).
    """
    __tablename__ = "responses"

    id = Column(String, primary_key=True, default=_uuid)
    exam_id = Column(String, ForeignKey("examinations.id"), nullable=False)
    candidate_id = Column(String, ForeignKey("candidates.id"), nullable=False)
    question_id = Column(String, ForeignKey("questions.id"), nullable=False)

    selected_option = Column(String, nullable=False)
    submitted_at = Column(DateTime, default=datetime.utcnow)
    session_id = Column(String, nullable=False)
    checksum = Column(String, nullable=False)

    examination = relationship("Examination", back_populates="responses")
    candidate = relationship("Candidate", back_populates="responses")
    question = relationship("Question", back_populates="responses")


class Result(Base):
    __tablename__ = "results"

    id = Column(String, primary_key=True, default=_uuid)
    exam_id = Column(String, ForeignKey("examinations.id"), nullable=False)
    candidate_id = Column(String, ForeignKey("candidates.id"), nullable=False)

    score = Column(Float, nullable=False)
    total_questions = Column(Integer, nullable=False)
    submitted_at = Column(DateTime, default=datetime.utcnow)
    checksum = Column(String, nullable=False)

    examination = relationship("Examination", back_populates="results")
    candidate = relationship("Candidate", back_populates="results")


class SecurityLog(Base):
    """
    Append-only audit trail. Written on every auth event, every
    Response/Result write, and every rate-limit / suspicious-input
    event, per Section 3.5.3 and 3.6.2 of the design.
    """
    __tablename__ = "security_logs"

    id = Column(String, primary_key=True, default=_uuid)
    event_type = Column(String, nullable=False, index=True)
    actor = Column(String, nullable=True)  # user id or "anonymous"
    ip_address = Column(String, nullable=True)
    endpoint = Column(String, nullable=True)
    details = Column(Text, nullable=True)
    checksum = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
