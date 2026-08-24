from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_admin, get_current_candidate, get_client_ip, log_security_event
from app.enrollment import enroll_all_candidates_at_level_in_course
from app.models import Course, Administrator, Candidate, CourseEnrollment
from app.schemas import CourseCreate, CoursePublic, CourseWithEnrollmentCount

router = APIRouter(prefix="/courses", tags=["courses"])


@router.post("", response_model=CourseWithEnrollmentCount, status_code=status.HTTP_201_CREATED)
def create_course(
    payload: CourseCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
):
    course = Course(name=payload.name, code=payload.code, level=payload.level, created_by=admin.id)
    db.add(course)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Course code already exists")
    db.refresh(course)

    # Auto-distribution: enroll every existing candidate at this level.
    enrolled_count = enroll_all_candidates_at_level_in_course(db, course)

    log_security_event(
        db, "course_created", admin.username, get_client_ip(request), "/courses",
        f"course={course.code} level={course.level.value} auto_enrolled={enrolled_count}",
    )

    return CourseWithEnrollmentCount(
        id=course.id, name=course.name, code=course.code, level=course.level,
        created_at=course.created_at, enrolled_candidates=enrolled_count,
    )


@router.get("", response_model=List[CoursePublic])
def list_courses(
    level: str | None = None,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
):
    query = db.query(Course)
    if level:
        query = query.filter(Course.level == level)
    return query.all()


@router.get("/mine", response_model=List[CoursePublic])
def list_my_courses(
    db: Session = Depends(get_db),
    candidate: Candidate = Depends(get_current_candidate),
):
    """Courses the current candidate has been auto-distributed onto, based on their level."""
    return (
        db.query(Course)
        .join(CourseEnrollment, CourseEnrollment.course_id == Course.id)
        .filter(CourseEnrollment.candidate_id == candidate.id)
        .all()
    )
