from sqlalchemy.orm import Session

from app.models import Candidate, Course, CourseEnrollment


def enroll_candidate_in_courses_at_level(db: Session, candidate: Candidate) -> int:
    """
    Called right after a candidate registers. Auto-enrolls them in
    every existing course that matches their level. Returns the
    number of enrollments created.
    """
    courses = db.query(Course).filter(Course.level == candidate.level).all()
    created = 0
    for course in courses:
        exists = (
            db.query(CourseEnrollment)
            .filter(CourseEnrollment.course_id == course.id, CourseEnrollment.candidate_id == candidate.id)
            .first()
        )
        if not exists:
            db.add(CourseEnrollment(course_id=course.id, candidate_id=candidate.id))
            created += 1
    if created:
        db.commit()
    return created


def enroll_all_candidates_at_level_in_course(db: Session, course: Course) -> int:
    """
    Called right after an admin creates a course. Auto-enrolls every
    existing candidate at that course's level. Returns the number of
    enrollments created.
    """
    candidates = db.query(Candidate).filter(Candidate.level == course.level).all()
    created = 0
    for candidate in candidates:
        exists = (
            db.query(CourseEnrollment)
            .filter(CourseEnrollment.course_id == course.id, CourseEnrollment.candidate_id == candidate.id)
            .first()
        )
        if not exists:
            db.add(CourseEnrollment(course_id=course.id, candidate_id=candidate.id))
            created += 1
    if created:
        db.commit()
    return created
