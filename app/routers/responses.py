from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import (
    get_current_candidate, get_client_ip, log_security_event, enforce_rate_limit,
    require_candidate_enrolled, require_not_terminated, get_current_role_and_id,
)
from app.models import Examination, ExamStatus, Question, Response, Result, Candidate
from app.schemas import (
    ResponseSubmit, ResponsePublic, ResultPublic, ResultBreakdown, QuestionBreakdown,
)
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
    exam = db.query(Examination).filter(Examination.id == exam_id, Examination.status == ExamStatus.published).first()
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Examination not found or not published")
    require_candidate_enrolled(db, candidate.id, exam)
    require_not_terminated(db, candidate.id, exam_id)

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
    """
    Scores the candidate's stored responses and writes a Result row.

    The raw score is the sum of `points` for every correctly answered
    question (== the count of correct answers when every question
    uses the default 1.0-point weight), out of `max_score` — the sum
    of `points` across every question in the exam. `total_questions`
    stays a plain question count for display (e.g. "18/20 questions
    answered correctly").
    """
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

    total = len(questions)
    max_score = sum(q.points for q in questions)
    score = sum(q.points for q in questions if answer_map.get(q.id) == q.correct_option)

    # A termination from proctoring strikes is scored as-is (whatever
    # was answered up to that point) but flagged, so admins can see it
    # separately in the exam-wide results / broadsheet export.
    from app.models import ExamProctoringFlag
    flag = (
        db.query(ExamProctoringFlag)
        .filter(ExamProctoringFlag.exam_id == exam_id, ExamProctoringFlag.candidate_id == candidate.id)
        .first()
    )
    terminated = bool(flag and flag.terminated)

    checksum = compute_checksum(exam_id, candidate.id, score, total, max_score)
    result = Result(
        exam_id=exam_id,
        candidate_id=candidate.id,
        score=score,
        total_questions=total,
        max_score=max_score,
        terminated=terminated,
        checksum=checksum,
    )
    db.add(result)
    db.commit()
    db.refresh(result)

    log_security_event(
        db, "exam_submitted", candidate.matric_no, get_client_ip(request),
        f"/exams/{exam_id}/submit", f"score={score}/{max_score} terminated={terminated}",
    )
    return result


@router.get("/results/me", response_model=List[ResultPublic])
def my_results(
    db: Session = Depends(get_db),
    candidate: Candidate = Depends(get_current_candidate),
):
    return db.query(Result).filter(Result.candidate_id == candidate.id).all()


@router.get("/results/{result_id}/breakdown", response_model=ResultBreakdown)
def result_breakdown(
    result_id: str,
    db: Session = Depends(get_db),
    role_and_id: tuple[str, str] = Depends(get_current_role_and_id),
):
    """
    Full question-by-question breakdown for one result: question text,
    the candidate's chosen option, the correct option, marks earned,
    and any explanation. A candidate may only view their own result;
    an admin may view any.
    """
    result = db.query(Result).filter(Result.id == result_id).first()
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result not found")

    role, user_id = role_and_id
    if role == "candidate" and result.candidate_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This is not your result")

    questions = db.query(Question).filter(Question.exam_id == result.exam_id).all()
    responses = (
        db.query(Response)
        .filter(Response.exam_id == result.exam_id, Response.candidate_id == result.candidate_id)
        .all()
    )
    answer_map = {r.question_id: r.selected_option for r in responses}

    breakdown = []
    for q in questions:
        selected = answer_map.get(q.id)
        is_correct = selected == q.correct_option
        breakdown.append(QuestionBreakdown(
            question_id=q.id,
            text=q.text,
            option_a=q.option_a,
            option_b=q.option_b,
            option_c=q.option_c,
            option_d=q.option_d,
            candidate_selected=selected,
            correct_option=q.correct_option,
            is_correct=is_correct,
            points_possible=q.points,
            points_earned=q.points if is_correct else 0.0,
            explanation=q.explanation,
            image_url=q.image_url,
        ))

    return ResultBreakdown(result=ResultPublic.model_validate(result), questions=breakdown)
