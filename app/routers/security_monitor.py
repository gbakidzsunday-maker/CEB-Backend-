from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_admin
from app.models import Administrator, SecurityLog, Response, Result
from app.schemas import SecurityLogPublic, IntegrityCheckResult
from app.security import compute_checksum

router = APIRouter(prefix="/security", tags=["security"])


@router.get("/logs", response_model=List[SecurityLogPublic])
def list_security_logs(
    limit: int = 100,
    event_type: str | None = None,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
):
    query = db.query(SecurityLog).order_by(SecurityLog.created_at.desc())
    if event_type:
        query = query.filter(SecurityLog.event_type == event_type)
    return query.limit(min(limit, 500)).all()


@router.get("/verify/response/{response_id}", response_model=IntegrityCheckResult)
def verify_response_integrity(
    response_id: str,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
):
    record = db.query(Response).filter(Response.id == response_id).first()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Response not found")

    recomputed = compute_checksum(
        record.exam_id, record.candidate_id, record.question_id,
        record.selected_option, record.session_id,
    )
    return IntegrityCheckResult(
        record_id=record.id,
        table="responses",
        stored_checksum=record.checksum,
        recomputed_checksum=recomputed,
        intact=(recomputed == record.checksum),
    )


@router.get("/verify/result/{result_id}", response_model=IntegrityCheckResult)
def verify_result_integrity(
    result_id: str,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
):
    record = db.query(Result).filter(Result.id == result_id).first()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result not found")

    recomputed = compute_checksum(record.exam_id, record.candidate_id, record.score, record.total_questions)
    return IntegrityCheckResult(
        record_id=record.id,
        table="results",
        stored_checksum=record.checksum,
        recomputed_checksum=recomputed,
        intact=(recomputed == record.checksum),
    )
