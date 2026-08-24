from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Candidate, Administrator, SecurityLog, Examination, CourseEnrollment
from app.security import decode_access_token, compute_checksum
from app.rate_limit import rate_limiter

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/candidate/login", auto_error=False)


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def log_security_event(
    db: Session,
    event_type: str,
    actor: str | None,
    ip_address: str | None,
    endpoint: str | None,
    details: str | None = None,
) -> SecurityLog:
    checksum = compute_checksum(event_type, actor, ip_address, endpoint, details)
    entry = SecurityLog(
        event_type=event_type,
        actor=actor,
        ip_address=ip_address,
        endpoint=endpoint,
        details=details,
        checksum=checksum,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def enforce_rate_limit(request: Request, db: Session = Depends(get_db)):
    """
    Per-IP, per-endpoint sliding-window rate limit. Used on hot/sensitive
    endpoints (login, response submission) to mitigate brute-force and
    flood-style (DoS) traffic, per Section 3.6.4.
    """
    ip = get_client_ip(request)
    key = f"{ip}:{request.url.path}"
    if not rate_limiter.is_allowed(key):
        log_security_event(
            db, "rate_limit_exceeded", None, ip, request.url.path,
            "Too many requests in the current window",
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down.",
        )


def get_current_payload(token: str | None = Depends(oauth2_scheme)) -> dict:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        return decode_access_token(token)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


def get_current_candidate(
    payload: dict = Depends(get_current_payload),
    db: Session = Depends(get_db),
) -> Candidate:
    if payload.get("role") != "candidate":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Candidate access required")
    candidate = db.query(Candidate).filter(Candidate.id == payload["sub"]).first()
    if not candidate:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Candidate not found")
    return candidate


def get_current_role_and_id(payload: dict = Depends(get_current_payload)) -> tuple[str, str]:
    """Lightweight alternative to get_current_candidate/get_current_admin
    for endpoints (like exam listing) that behave differently per role
    but are reachable by both."""
    role = payload.get("role")
    if role not in ("candidate", "admin"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return role, payload["sub"]


def require_candidate_enrolled(db: Session, candidate_id: str, exam: Examination) -> None:
    """
    Enforces that a candidate may only interact with an exam whose
    course they are enrolled in (i.e. whose level matches theirs at
    the time they registered or the course was created). Raises 403
    otherwise.
    """
    enrolled = (
        db.query(CourseEnrollment)
        .filter(
            CourseEnrollment.course_id == exam.course_id,
            CourseEnrollment.candidate_id == candidate_id,
        )
        .first()
    )
    if not enrolled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not enrolled in the course this examination belongs to",
        )


def get_current_admin(
    payload: dict = Depends(get_current_payload),
    db: Session = Depends(get_db),
) -> Administrator:
    if payload.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    admin = db.query(Administrator).filter(Administrator.id == payload["sub"]).first()
    if not admin:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Administrator not found")
    return admin
