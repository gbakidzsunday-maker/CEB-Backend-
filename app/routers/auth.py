from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_client_ip, log_security_event, enforce_rate_limit
from app.models import Candidate, Administrator, Parent
from app.enrollment import enroll_candidate_in_courses_at_level
from app.parent_linking import match_and_link_children
from app.schemas import (
    CandidateRegister, AdminRegister, LoginRequest, TokenResponse,
    ParentRegister, ParentRegisterResponse, ChildMatch,
)
from app.security import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


def _is_locked(locked_until: datetime | None) -> bool:
    return bool(locked_until and locked_until > datetime.utcnow())


def _register_failure(db: Session, user, ip: str, endpoint: str):
    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
    if user.failed_login_attempts >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
        user.locked_until = datetime.utcnow() + timedelta(minutes=settings.LOCKOUT_MINUTES)
        actor = getattr(user, "matric_no", None) or getattr(user, "username", None) or getattr(user, "phone_number", None)
        log_security_event(
            db, "account_locked", actor,
            ip, endpoint, "Account locked after repeated failed login attempts",
        )
    db.commit()


def _register_success(db: Session, user):
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()


# ---------- Candidate ----------

@router.post("/candidate/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register_candidate(payload: CandidateRegister, request: Request, db: Session = Depends(get_db)):
    candidate = Candidate(
        matric_no=payload.matric_no,
        email=payload.email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        level=payload.level,
    )
    db.add(candidate)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="matric_no or email already registered")
    db.refresh(candidate)

    # Auto-distribution: enroll the new candidate in every existing
    # course that matches their level.
    enroll_candidate_in_courses_at_level(db, candidate)

    log_security_event(
        db, "candidate_registered", candidate.matric_no, get_client_ip(request),
        "/auth/candidate/register", f"level={candidate.level.value}",
    )
    token = create_access_token(subject=candidate.id, role="candidate")
    return TokenResponse(access_token=token, role="candidate")


@router.post("/candidate/login", response_model=TokenResponse)
def login_candidate(payload: LoginRequest, request: Request, db: Session = Depends(get_db), _rl=Depends(enforce_rate_limit)):
    ip = get_client_ip(request)
    candidate = db.query(Candidate).filter(Candidate.matric_no == payload.identifier).first()

    if not candidate:
        log_security_event(db, "login_failed", payload.identifier, ip, "/auth/candidate/login", "Unknown matric_no")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not candidate.is_active:
        log_security_event(db, "login_blocked_deactivated", candidate.matric_no, ip, "/auth/candidate/login")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account has been deactivated. Contact an administrator.")

    if _is_locked(candidate.locked_until):
        log_security_event(db, "login_blocked_locked_account", candidate.matric_no, ip, "/auth/candidate/login")
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Account temporarily locked. Try again later.")

    if not verify_password(payload.password, candidate.password_hash):
        _register_failure(db, candidate, ip, "/auth/candidate/login")
        log_security_event(db, "login_failed", candidate.matric_no, ip, "/auth/candidate/login", "Bad password")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    _register_success(db, candidate)
    log_security_event(db, "login_success", candidate.matric_no, ip, "/auth/candidate/login")
    token = create_access_token(subject=candidate.id, role="candidate")
    return TokenResponse(access_token=token, role="candidate")


# ---------- Administrator ----------

@router.post("/admin/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register_admin(payload: AdminRegister, request: Request, db: Session = Depends(get_db)):
    admin = Administrator(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    db.add(admin)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username or email already registered")
    db.refresh(admin)

    log_security_event(db, "admin_registered", admin.username, get_client_ip(request), "/auth/admin/register")
    token = create_access_token(subject=admin.id, role="admin")
    return TokenResponse(access_token=token, role="admin")


@router.post("/admin/login", response_model=TokenResponse)
def login_admin(payload: LoginRequest, request: Request, db: Session = Depends(get_db), _rl=Depends(enforce_rate_limit)):
    ip = get_client_ip(request)
    admin = db.query(Administrator).filter(Administrator.username == payload.identifier).first()

    if not admin:
        log_security_event(db, "login_failed", payload.identifier, ip, "/auth/admin/login", "Unknown username")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if _is_locked(admin.locked_until):
        log_security_event(db, "login_blocked_locked_account", admin.username, ip, "/auth/admin/login")
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Account temporarily locked. Try again later.")

    if not verify_password(payload.password, admin.password_hash):
        _register_failure(db, admin, ip, "/auth/admin/login")
        log_security_event(db, "login_failed", admin.username, ip, "/auth/admin/login", "Bad password")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    _register_success(db, admin)
    log_security_event(db, "login_success", admin.username, ip, "/auth/admin/login")
    token = create_access_token(subject=admin.id, role="admin")
    return TokenResponse(access_token=token, role="admin")


# ---------- Parent ----------

@router.post("/parent/register", response_model=ParentRegisterResponse, status_code=status.HTTP_201_CREATED)
def register_parent(payload: ParentRegister, request: Request, db: Session = Depends(get_db)):
    """
    Registers a parent/guardian account and automatically links it to
    every existing candidate whose full_name exactly matches (case-
    insensitively) one of the submitted children_names. At least one
    submitted name must match an existing candidate, otherwise the
    registration is rejected with 400 and nothing is created.
    """
    parent = Parent(
        full_name=payload.full_name,
        address=payload.address,
        phone_number=payload.phone_number,
        password_hash=hash_password(payload.password),
    )
    db.add(parent)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="phone_number already registered")
    db.refresh(parent)

    match_results = match_and_link_children(db, parent, payload.children_names)

    if not any(m["matched"] for m in match_results):
        # Roll back the parent account too — registration must find at
        # least one matching child.
        db.delete(parent)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="None of the provided children_names match an existing student. Check spelling and try again.",
        )

    linked_ids = [m["candidate_id"] for m in match_results if m["matched"]]
    log_security_event(
        db, "parent_registered", parent.phone_number, get_client_ip(request),
        "/auth/parent/register", f"linked_candidates={linked_ids}",
    )
    token = create_access_token(subject=parent.id, role="parent")
    return ParentRegisterResponse(
        access_token=token,
        role="parent",
        children=[ChildMatch(**m) for m in match_results],
    )


@router.post("/parent/login", response_model=TokenResponse)
def login_parent(payload: LoginRequest, request: Request, db: Session = Depends(get_db), _rl=Depends(enforce_rate_limit)):
    ip = get_client_ip(request)
    parent = db.query(Parent).filter(Parent.phone_number == payload.identifier).first()

    if not parent:
        log_security_event(db, "login_failed", payload.identifier, ip, "/auth/parent/login", "Unknown phone_number")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not parent.is_active:
        log_security_event(db, "login_blocked_deactivated", parent.phone_number, ip, "/auth/parent/login")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account has been deactivated. Contact an administrator.")

    if _is_locked(parent.locked_until):
        log_security_event(db, "login_blocked_locked_account", parent.phone_number, ip, "/auth/parent/login")
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Account temporarily locked. Try again later.")

    if not verify_password(payload.password, parent.password_hash):
        _register_failure(db, parent, ip, "/auth/parent/login")
        log_security_event(db, "login_failed", parent.phone_number, ip, "/auth/parent/login", "Bad password")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    _register_success(db, parent)
    log_security_event(db, "login_success", parent.phone_number, ip, "/auth/parent/login")
    token = create_access_token(subject=parent.id, role="parent")
    return TokenResponse(access_token=token, role="parent")
