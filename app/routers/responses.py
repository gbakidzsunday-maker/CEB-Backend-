from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_candidate, get_client_ip, log_security_event, enforce_rate_limit, require_candidate_enrolled
from app.models import Examination, Question, Response, Result, Candidate
from app.schemas import ResponseSubmit, ResponsePublic, ResultPublic
from app.security import compute_checksum

router = APIRouter(tags=["responses"])


@router.post("/exams/{exam_id}/responses", response_model=ResponsePublic, status_code=status.HTTP_201_CREATED)
def submit_response(
    exam_id: str,
    payload: ResponseSubmit,
    request: Request,
    db: Session = Depends(get_db),
    candidate: Candidate = Depends(get_current_candidate),
    _rl=Depends(enforce_rate_limit),
):
    """
    Real-time response capture: persists (or updates) a candidate's
    answer to a single question immediately, with a checksum over its
    contents so later tampering can be detected (Section 3.5.3).
    """
    exam = db.query(Examination).filter(Examination.id == exam_id, Examination.is_active == True).first()  # noqa: E712
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Examination not found or inactive")
    require_candidate_enrolled(db, candidate.id, exam)

    question = db.query(Question).filter(Question.id == payload.question_id, Question.exam_id == exam_id).first()
    if not question:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found for this exam")

    existing = (
        db.query(Response)
        .filter(
            Response.exam_id == exam_id,
            Response.candidate_id == candidate.id,
            Response.question_id == payload.question_id,
        )
        .first()
    )

    checksum = compute_checksum(exam_id, candidate.id, payload.question_id, payload.selected_option, payload.session_id)

    if existing:
        existing.selected_option = payload.selected_option
        existing.session_id = payload.session_id
        existing.checksum = checksum
        db.commit()
        db.refresh(existing)
        record = existing
    else:
        record = Response(
            exam_id=exam_id,
            candidate_id=candidate.id,
            question_id=payload.question_id,
            selected_option=payload.selected_option,
            session_id=payload.session_id,
            checksum=checksum,
        )
        db.add(record)
        db.commit()
        db.refresh(record)

    log_security_event(
        db, "response_submitted", candidate.matric_no, get_client_ip(request),
        f"/exams/{exam_id}/responses", f"question={payload.question_id}",
    )
    return record


@router.get("/exams/{exam_id}/responses/me", response_model=List[ResponsePublic])
def my_responses(
    exam_id: str,
    db: Session = Depends(get_db),
    candidate: Candidate = Depends(get_current_candidate),
):
    return (
        db.query(Response)
        .filter(Response.exam_id == exam_id, Response.candidate_id == candidate.id)
        .all()
    )


@router.post("/exams/{exam_id}/submit", response_model=ResultPublic, status_code=status.HTTP_201_CREATED)
def submit_exam(
    exam_id: str,
    request: Request,
    db: Session = Depends(get_db),
    candidate: Candidate = Depends(get_current_candidate),
):
    """Scores the candidate's stored responses and writes a Result row."""
    exam = db.query(Examination).filter(Examination.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Examination not found")
    require_candidate_enrolled(db, candidate.id, exam)

    already = (
        db.query(Result)
        .filter(Result.exam_id == exam_id, Result.candidate_id == candidate.id)
        .first()
    )
    if already:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Exam already submitted")

    questions = db.query(Question).filter(Question.exam_id == exam_id).all()
    responses = (
        db.query(Response)
        .filter(Response.exam_id == exam_id, Response.candidate_id == candidate.id)
        .all()
    )
    answer_map = {r.question_id: r.selected_option for r in responses}

    correct = sum(
        1 for q in questions if answer_map.get(q.id) == q.correct_option
    )
    total = len(questions)
    score = round((correct / total) * 100, 2) if total else 0.0

    checksum = compute_checksum(exam_id, candidate.id, score, total)
    result = Result(
        exam_id=exam_id,
        candidate_id=candidate.id,
        score=score,
        total_questions=total,
        checksum=checksum,
    )
    db.add(result)
    db.commit()
    db.refresh(result)

    log_security_event(
        db, "exam_submitted", candidate.matric_no, get_client_ip(request),
        f"/exams/{exam_id}/submit", f"score={score}",
    )
    return result


@router.get("/results/me", response_model=List[ResultPublic])
def my_results(
    db: Session = Depends(get_db),
    candidate: Candidate = Depends(get_current_candidate),
):
    return db.query(Result).filter(Result.candidate_id == candidate.id).all()
