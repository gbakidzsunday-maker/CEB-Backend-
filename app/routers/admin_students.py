import csv
import io
import secrets
import string
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_admin, get_client_ip, log_security_event
from app.enrollment import enroll_candidate_in_courses_at_level
from app.models import Candidate, Administrator, Course, CourseEnrollment, Result, Examination, Level
from app.schemas import (
    CandidateAdminView, CandidateAdminDetail, CandidateUpdate, ResultWithExam,
    AdminPasswordReset, AdminPasswordResetResponse, EnrollRequest, EnrollResult,
    BulkStudentImportResult,
)
from app.security import hash_password

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


def _generate_temp_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(12))


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


@router.post("/bulk-import", response_model=BulkStudentImportResult, status_code=status.HTTP_201_CREATED)
async def bulk_import_students(
    request: Request,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
    file: UploadFile = File(...),
):
    """
    Bulk-registers a matriculation cohort from a CSV file. Required
    columns: matric_no, email, full_name, level. Optional: password
    (a random temporary password is generated per row if omitted —
    it is returned in `errors` as a notice, never logged in plaintext
    elsewhere). Newly created candidates are auto-enrolled in every
    existing course at their level, same as self-registration.
    """
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))

    created: list[Candidate] = []
    errors: list[str] = []

    for i, row in enumerate(reader, start=2):
        try:
            matric_no = row["matric_no"].strip()
            email = row["email"].strip()
            full_name = row["full_name"].strip()
            level_raw = row["level"].strip()
            if level_raw not in Level.__members__:
                errors.append(f"Row {i}: unknown level '{level_raw}'")
                continue
            password = (row.get("password") or "").strip() or _generate_temp_password()

            candidate = Candidate(
                matric_no=matric_no,
                email=email,
                full_name=full_name,
                password_hash=hash_password(password),
                level=Level[level_raw],
            )
            db.add(candidate)
            db.flush()
            enroll_candidate_in_courses_at_level(db, candidate)
            created.append(candidate)
        except KeyError as exc:
            errors.append(f"Row {i}: missing column {exc}")
        except IntegrityError:
            db.rollback()
            errors.append(f"Row {i}: matric_no or email already registered")

    if created:
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate matric_no or email in file")
        for c in created:
            db.refresh(c)

    log_security_event(
        db, "students_bulk_imported", admin.username, get_client_ip(request),
        "/admin/students/bulk-import", f"created={len(created)} failed={len(errors)}",
    )
    return BulkStudentImportResult(
        created=len(created), failed=len(errors), errors=errors,
        students=[_to_admin_view(c) for c in created],
    )


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


@router.post("/{candidate_id}/reset-password", response_model=AdminPasswordResetResponse)
def reset_student_password(
    candidate_id: str,
    payload: AdminPasswordReset,
    request: Request,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
):
    """
    Assigns a new password (or generates a temporary one) for a
    candidate who is locked out or has forgotten their credentials in
    the exam hall. Also clears any existing lockout so they can log
    in immediately.
    """
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    new_password = payload.new_password or _generate_temp_password()
    candidate.password_hash = hash_password(new_password)
    candidate.failed_login_attempts = 0
    candidate.locked_until = None
    db.commit()

    log_security_event(
        db, "candidate_password_reset", admin.username, get_client_ip(request),
        f"/admin/students/{candidate_id}/reset-password",
    )
    return AdminPasswordResetResponse(candidate_id=candidate.id, temporary_password=new_password)


@router.post("/{candidate_id}/enroll", response_model=List[EnrollResult])
def enroll_student(
    candidate_id: str,
    payload: EnrollRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
):
    """Assigns one or more courses to a student directly, regardless of their level-based auto-distribution."""
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    results = []
    newly_enrolled = []
    for course_id in payload.course_ids:
        course = db.query(Course).filter(Course.id == course_id).first()
        if not course:
            results.append(EnrollResult(course_id=course_id, enrolled=False, reason="Course not found"))
            continue
        existing = (
            db.query(CourseEnrollment)
            .filter(CourseEnrollment.course_id == course_id, CourseEnrollment.candidate_id == candidate_id)
            .first()
        )
        if existing:
            results.append(EnrollResult(course_id=course_id, enrolled=False, reason="Already enrolled"))
            continue
        db.add(CourseEnrollment(course_id=course_id, candidate_id=candidate_id))
        newly_enrolled.append(course_id)
        results.append(EnrollResult(course_id=course_id, enrolled=True))

    if newly_enrolled:
        db.commit()
        log_security_event(
            db, "candidate_enrolled", admin.username, get_client_ip(request),
            f"/admin/students/{candidate_id}/enroll", f"courses={newly_enrolled}",
        )
    return results


@router.delete("/{candidate_id}/enroll/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def unenroll_student(
    candidate_id: str,
    course_id: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
):
    enrollment = (
        db.query(CourseEnrollment)
        .filter(CourseEnrollment.course_id == course_id, CourseEnrollment.candidate_id == candidate_id)
        .first()
    )
    if not enrollment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Enrollment not found")

    db.delete(enrollment)
    db.commit()
    log_security_event(
        db, "candidate_unenrolled", admin.username, get_client_ip(request),
        f"/admin/students/{candidate_id}/enroll/{course_id}",
    )
    return None


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
            max_score=r.max_score, percentage=r.percentage, terminated=r.terminated,
            submitted_at=r.submitted_at, checksum=r.checksum, exam_title=title,
        )
        for r, title in rows
    ]
