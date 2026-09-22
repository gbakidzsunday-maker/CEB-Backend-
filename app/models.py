import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, Enum,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Role(str, enum.Enum):
    candidate = "candidate"
    admin = "admin"


class ExamStatus(str, enum.Enum):
    draft = "draft"
    published = "published"
    closed = "closed"


class ProctoringEventType(str, enum.Enum):
    TAB_SWITCH = "TAB_SWITCH"
    FULLSCREEN_EXIT = "FULLSCREEN_EXIT"
    MULTI_WINDOW_DETECTED = "MULTI_WINDOW_DETECTED"
    WINDOW_BLUR = "WINDOW_BLUR"


class Level(str, enum.Enum):
    """
    Academic level a candidate is studying at, and a course/exam is
    targeted at.

    ND (National Diploma) has two years, no departmental split.
    HND (Higher National Diploma) also has two years, but candidates
    additionally belong to one of two options within Computer Science:
    SWD (Software Engineering) or NCC (Network and Computer
    Connectivity/Communication). Adjust the exact option codes below
    if Mapoly uses different abbreviations.
    """
    ND1 = "ND1"
    ND2 = "ND2"
    HND1_SWD = "HND1_SWD"
    HND1_NCC = "HND1_NCC"
    HND2_SWD = "HND2_SWD"
    HND2_NCC = "HND2_NCC"


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(String, primary_key=True, default=_uuid)
    matric_no = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    level = Column(Enum(Level), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    responses = relationship("Response", back_populates="candidate")
    results = relationship("Result", back_populates="candidate")
    enrollments = relationship("CourseEnrollment", back_populates="candidate")
    proctoring_flags = relationship("ExamProctoringFlag", back_populates="candidate")


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


class Parent(Base):
    """
    A parent/guardian account. Linked to one or more Candidate rows at
    registration time by matching the child name(s) supplied against
    Candidate.full_name — see routers/auth.py::register_parent and
    the ParentChild join table below.
    """
    __tablename__ = "parents"

    id = Column(String, primary_key=True, default=_uuid)
    full_name = Column(String, nullable=False)
    address = Column(String, nullable=False)
    phone_number = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    children = relationship(
        "ParentChild", back_populates="parent", cascade="all, delete-orphan"
    )


class ParentChild(Base):
    """
    Join table linking a parent to a candidate (child). Created
    automatically at parent-registration time for every candidate whose
    full_name matches one of the names the parent supplied — kept
    explicit (rather than re-matching by name at read time) so the link
    survives a later change to either name.
    """
    __tablename__ = "parent_children"
    __table_args__ = (
        UniqueConstraint("parent_id", "candidate_id", name="uq_parent_candidate"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    parent_id = Column(String, ForeignKey("parents.id"), nullable=False)
    candidate_id = Column(String, ForeignKey("candidates.id"), nullable=False)
    linked_at = Column(DateTime, default=datetime.utcnow)

    parent = relationship("Parent", back_populates="children")
    candidate = relationship("Candidate")


class Course(Base):
    """
    A course belongs to exactly one academic level. Creating a course
    auto-enrolls every existing candidate at that level (see
    routers/courses.py); registering a new candidate at a level
    likewise auto-enrolls them in every existing course at that level.
    """
    __tablename__ = "courses"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    code = Column(String, unique=True, index=True, nullable=False)
    level = Column(Enum(Level), nullable=False, index=True)

    created_by = Column(String, ForeignKey("administrators.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    enrollments = relationship("CourseEnrollment", back_populates="course", cascade="all, delete-orphan")
    examinations = relationship("Examination", back_populates="course")


class CourseEnrollment(Base):
    """
    Join table recording that a candidate has been auto-distributed
    onto a course. Kept explicit (rather than re-deriving purely from
    matching levels at read time) so enrollment history survives even
    if a candidate's level is changed later.
    """
    __tablename__ = "course_enrollments"

    id = Column(String, primary_key=True, default=_uuid)
    course_id = Column(String, ForeignKey("courses.id"), nullable=False)
    candidate_id = Column(String, ForeignKey("candidates.id"), nullable=False)
    enrolled_at = Column(DateTime, default=datetime.utcnow)

    course = relationship("Course", back_populates="enrollments")
    candidate = relationship("Candidate", back_populates="enrollments")


class Examination(Base):
    __tablename__ = "examinations"

    id = Column(String, primary_key=True, default=_uuid)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    duration_minutes = Column(Integer, nullable=False)
    # Kept for backward compatibility with existing consumers of
    # ExaminationPublic.is_active — always kept in sync with
    # `status == ExamStatus.published` by the publish/unpublish/close
    # endpoints below.
    is_active = Column(Boolean, default=False)

    status = Column(Enum(ExamStatus), nullable=False, default=ExamStatus.draft, index=True)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    pass_mark_percentage = Column(Integer, nullable=False, default=50)
    shuffle_questions = Column(Boolean, nullable=False, default=True)
    shuffle_options = Column(Boolean, nullable=False, default=True)

    course_id = Column(String, ForeignKey("courses.id"), nullable=False)
    # Denormalised copy of course.level, set once at creation time, so
    # exam listing/filtering by level never needs a join. A course's
    # level is not expected to change after creation.
    level = Column(Enum(Level), nullable=False, index=True)

    created_by = Column(String, ForeignKey("administrators.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    created_by_admin = relationship("Administrator", back_populates="exams")
    course = relationship("Course", back_populates="examinations")
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
    points = Column(Float, nullable=False, default=1.0)
    # Never sent to candidates before submission — only via the
    # post-submission results breakdown.
    explanation = Column(Text, nullable=True)
    image_url = Column(String, nullable=True)

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

    # Raw score earned, i.e. the sum of `points` for every correctly
    # answered question (== count of correct answers when every
    # question is worth the default 1.0 point).
    score = Column(Float, nullable=False)
    total_questions = Column(Integer, nullable=False)
    # Sum of `points` across every question in the exam at submission
    # time — the denominator for `score`. Equal to total_questions
    # unless multi-point questions are in use.
    max_score = Column(Float, nullable=False, default=0.0)
    submitted_at = Column(DateTime, default=datetime.utcnow)
    checksum = Column(String, nullable=False)
    terminated = Column(Boolean, nullable=False, default=False)

    examination = relationship("Examination", back_populates="results")
    candidate = relationship("Candidate", back_populates="results")

    @property
    def percentage(self) -> float:
        """Not a DB column — derived so it's always consistent with
        score/max_score and never goes stale if either is corrected."""
        return round((self.score / self.max_score) * 100, 2) if self.max_score else 0.0


class ExamProctoringFlag(Base):
    """
    Server-authoritative strike counter for one candidate's attempt at
    one exam. Every POST /exams/{exam_id}/proctoring-event increments
    `strikes`; once it reaches 3 the row is marked `terminated` and
    further response submission / final submission for that exam is
    blocked server-side, so a client cannot bypass the anti-cheat
    logic by hiding or ignoring it locally.
    """
    __tablename__ = "exam_proctoring_flags"
    __table_args__ = (
        UniqueConstraint("exam_id", "candidate_id", name="uq_exam_candidate_proctoring"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    exam_id = Column(String, ForeignKey("examinations.id"), nullable=False)
    candidate_id = Column(String, ForeignKey("candidates.id"), nullable=False)
    strikes = Column(Integer, nullable=False, default=0)
    terminated = Column(Boolean, nullable=False, default=False)
    terminated_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    examination = relationship("Examination")
    candidate = relationship("Candidate", back_populates="proctoring_flags")


class ProctoringEvent(Base):
    """Append-only log of every individual proctoring event received."""
    __tablename__ = "proctoring_events"

    id = Column(String, primary_key=True, default=_uuid)
    exam_id = Column(String, ForeignKey("examinations.id"), nullable=False)
    candidate_id = Column(String, ForeignKey("candidates.id"), nullable=False)
    event_type = Column(Enum(ProctoringEventType), nullable=False)
    strike_count = Column(Integer, nullable=False)
    occurred_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    examination = relationship("Examination")
    candidate = relationship("Candidate")


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
