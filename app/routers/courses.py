from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_admin, get_current_candidate, get_client_ip, log_security_event
from app.enrollment import enroll_all_candidates_at_level_in_course
from app.models import Course, Administrator, Candidate, CourseEnrollment, Examination
from app.schemas import CourseCreate, CourseUpdate, CoursePublic, CourseWithEnrollmentCount

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


@router.patch("/{course_id}", response_model=CoursePublic)
def update_course(
    course_id: str,
    payload: CourseUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
):
    """Edits a course's name/code. Level is intentionally not editable here — create a new course instead."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(course, field, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Course code already exists")
    db.refresh(course)

    log_security_event(
        db, "course_updated", admin.username, get_client_ip(request), f"/courses/{course_id}",
        f"fields={list(updates.keys())}",
    )
    return course


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(
    course_id: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: Administrator = Depends(get_current_admin),
):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    has_exams = db.query(Examination).filter(Examination.course_id == course_id).first() is not None
    if has_exams:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This course has examinations attached to it and cannot be deleted.",
        )

    db.delete(course)  # cascades to enrollments
    db.commit()
    log_security_event(db, "course_deleted", admin.username, get_client_ip(request), f"/courses/{course_id}")
    return None


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
