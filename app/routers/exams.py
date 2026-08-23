from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_admin, get_current_candidate, get_client_ip, log_security_event
from app.models import Examination, Question, Administrator, Candidate
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
    exam = Examination(
        title=payload.title,
        description=payload.description,
        duration_minutes=payload.duration_minutes,
        created_by=admin.id,
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)
    log_security_event(db, "exam_created", admin.username, get_client_ip(request), "/exams", exam.id)
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
def list_exams(db: Session = Depends(get_db)):
    return db.query(Examination).filter(Examination.is_active == True).all()  # noqa: E712


@router.get("/{exam_id}", response_model=ExaminationPublic)
def get_exam(exam_id: str, db: Session = Depends(get_db)):
    exam = db.query(Examination).filter(Examination.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Examination not found")
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
    return db.query(Question).filter(Question.exam_id == exam_id).all()
