from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_admin, get_client_ip, log_security_event
from app.enrollment import enroll_candidate_in_courses_at_level
from app.models import Candidate, Administrator, Course, CourseEnrollment, Result, Examination
from app.schemas import (
    CandidateAdminView, CandidateAdminDetail, CandidateUpdate, ResultWithExam,
)

router = APIRouter(prefix="/admin/students", tags=["admin-students"])


def _to_admin_view(candidate: Candidate) -> CandidateAdminView:
    return CandidateAdminView(
        id=candidate.id,
        matric_no=candidate.matric_no,
        email=candidate.email,
        full_name=candidate.full_name,
        level=candidate.level,
        is_active=candidate.is_active,
        is_locked=bool(candidate.locked_until and candidate.locked_until > datetime.utcnow()),
        failed_login_attempts=candidate.failed_login_attempts,
        created_at=candidate.created_at,
    )


@router.get("", response_model=List[CandidateAdminView])
def list_students(
    level: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
):
    """
    List all candidates. Optional filters:
    - level: exact level match (e.g. HND1_SWD)
    - search: case-insensitive partial match on matric_no or full_name
    """
    query = db.query(Candidate)
    if level:
        query = query.filter(Candidate.level == level)
    if search:
        like = f"%{search}%"
        query = query.filter(
            (Candidate.matric_no.ilike(like)) | (Candidate.full_name.ilike(like))
        )
    return [_to_admin_view(c) for c in query.order_by(Candidate.created_at.desc()).all()]


@router.get("/{candidate_id}", response_model=CandidateAdminDetail)
def get_student_profile(
    candidate_id: str,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
):
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    courses = (
        db.query(Course)
        .join(CourseEnrollment, CourseEnrollment.course_id == Course.id)
        .filter(CourseEnrollment.candidate_id == candidate.id)
        .all()
    )
    base = _to_admin_view(candidate)
    return CandidateAdminDetail(**base.model_dump(), enrolled_courses=courses)


@router.patch("/{candidate_id}", response_model=CandidateAdminView)
def update_student(
    candidate_id: str,
    payload: CandidateUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
):
    """
    Edits a candidate's profile. Changing `level` does NOT remove the
    candidate from courses they were already enrolled in under their
    old level (enrollment history is preserved) — it only adds new
    auto-enrollments for any existing course at the new level.
    """
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    updates = payload.model_dump(exclude_unset=True)
    level_changed = "level" in updates and updates["level"] != candidate.level

    for field, value in updates.items():
        setattr(candidate, field, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")
    db.refresh(candidate)

    if level_changed:
        enroll_candidate_in_courses_at_level(db, candidate)

    log_security_event(
        db, "candidate_profile_updated", admin.username, get_client_ip(request),
        f"/admin/students/{candidate_id}", f"fields={list(updates.keys())}",
    )
    return _to_admin_view(candidate)


@router.post("/{candidate_id}/deactivate", response_model=CandidateAdminView)
def deactivate_student(
    candidate_id: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
):
    """Blocks the candidate from logging in without deleting any of their data."""
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    candidate.is_active = False
    db.commit()
    db.refresh(candidate)
    log_security_event(db, "candidate_deactivated", admin.username, get_client_ip(request), f"/admin/students/{candidate_id}/deactivate")
    return _to_admin_view(candidate)


@router.post("/{candidate_id}/activate", response_model=CandidateAdminView)
def activate_student(
    candidate_id: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
):
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    candidate.is_active = True
    db.commit()
    db.refresh(candidate)
    log_security_event(db, "candidate_activated", admin.username, get_client_ip(request), f"/admin/students/{candidate_id}/activate")
    return _to_admin_view(candidate)


@router.post("/{candidate_id}/unlock", response_model=CandidateAdminView)
def unlock_student(
    candidate_id: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
):
    """Clears a lockout caused by repeated failed login attempts."""
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    candidate.failed_login_attempts = 0
    candidate.locked_until = None
    db.commit()
    db.refresh(candidate)
    log_security_event(db, "candidate_unlocked", admin.username, get_client_ip(request), f"/admin/students/{candidate_id}/unlock")
    return _to_admin_view(candidate)


@router.get("/{candidate_id}/results", response_model=List[ResultWithExam])
def get_student_results(
    candidate_id: str,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
):
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    rows = (
        db.query(Result, Examination.title)
        .join(Examination, Examination.id == Result.exam_id)
        .filter(Result.candidate_id == candidate_id)
        .order_by(Result.submitted_at.desc())
        .all()
    )
    return [
        ResultWithExam(
            id=r.id, exam_id=r.exam_id, score=r.score, total_questions=r.total_questions,
            submitted_at=r.submitted_at, checksum=r.checksum, exam_title=title,
        )
        for r, title in rows
    ]
