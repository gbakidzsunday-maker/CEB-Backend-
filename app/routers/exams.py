from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import (
    get_current_admin, get_current_candidate, get_client_ip, log_security_event,
    get_current_role_and_id, require_candidate_enrolled,
)
from app.models import Examination, Question, Course, Administrator, Candidate, CourseEnrollment
from app.schemas import (
    ExaminationCreate, ExaminationPublic, QuestionCreate, QuestionPublic, QuestionAdminView,
)

router = APIRouter(prefix="/exams", tags=["exams"])


# ---------- Admin: manage exams ----------

@router.post("", response_model=ExaminationPublic, status_code=status.HTTP_201_CREATED)
def create_exam(
    payload: ExaminationCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
):
    course = db.query(Course).filter(Course.id == payload.course_id).first()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    exam = Examination(
        title=payload.title,
        description=payload.description,
        duration_minutes=payload.duration_minutes,
        course_id=course.id,
        level=course.level,  # denormalised copy — see models.Examination
        created_by=admin.id,
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)
    log_security_event(
        db, "exam_created", admin.username, get_client_ip(request), "/exams",
        f"exam={exam.id} course={course.code} level={course.level.value}",
    )
    return exam


@router.post("/{exam_id}/questions", response_model=QuestionAdminView, status_code=status.HTTP_201_CREATED)
def add_question(
    exam_id: str,
    payload: QuestionCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
):
    exam = db.query(Examination).filter(Examination.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Examination not found")

    question = Question(exam_id=exam_id, **payload.model_dump())
    db.add(question)
    db.commit()
    db.refresh(question)
    log_security_event(db, "question_added", admin.username, get_client_ip(request), f"/exams/{exam_id}/questions", question.id)
    return question


@router.get("/{exam_id}/questions/admin", response_model=List[QuestionAdminView])
def list_questions_admin(
    exam_id: str,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
):
    return db.query(Question).filter(Question.exam_id == exam_id).all()


# ---------- Shared read / candidate view ----------

@router.get("", response_model=List[ExaminationPublic])
def list_exams(
    level: str | None = None,
    course_id: str | None = None,
    db: Session = Depends(get_db),
    role_and_id: tuple[str, str] = Depends(get_current_role_and_id),
):
    """
    Admins see every active exam (optionally filtered by level/course_id).
    Candidates only ever see active exams belonging to a course they are
    enrolled in — i.e. exams that match their level.
    """
    role, user_id = role_and_id
    query = db.query(Examination).filter(Examination.is_active == True)  # noqa: E712

    if role == "admin":
        if level:
            query = query.filter(Examination.level == level)
        if course_id:
            query = query.filter(Examination.course_id == course_id)
        return query.all()

    # candidate: restrict to enrolled courses
    enrolled_course_ids = [
        row[0] for row in
        db.query(CourseEnrollment.course_id).filter(CourseEnrollment.candidate_id == user_id).all()
    ]
    if not enrolled_course_ids:
        return []
    query = query.filter(Examination.course_id.in_(enrolled_course_ids))
    if course_id:
        query = query.filter(Examination.course_id == course_id)
    return query.all()


@router.get("/{exam_id}", response_model=ExaminationPublic)
def get_exam(
    exam_id: str,
    db: Session = Depends(get_db),
    role_and_id: tuple[str, str] = Depends(get_current_role_and_id),
):
    exam = db.query(Examination).filter(Examination.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Examination not found")

    role, user_id = role_and_id
    if role == "candidate":
        require_candidate_enrolled(db, user_id, exam)
    return exam


@router.get("/{exam_id}/questions", response_model=List[QuestionPublic])
def list_questions_candidate(
    exam_id: str,
    db: Session = Depends(get_db),
    candidate: Candidate = Depends(get_current_candidate),
):
    """Candidate-facing question list — correct_option is never included."""
    exam = db.query(Examination).filter(Examination.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Examination not found")
    require_candidate_enrolled(db, candidate.id, exam)
    return db.query(Question).filter(Question.exam_id == exam_id).all()
