from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_parent, get_client_ip, log_security_event
from app.models import Candidate, Parent, ParentChild, CourseEnrollment, Examination, Result
from app.schemas import (
    ChildSummary, ChildExamStatus, ResultPublic, ResultWithExam, ParentMe, ParentLinkChildRequest,
)

router = APIRouter(prefix="/parent", tags=["parent"])


@router.get("/me", response_model=ParentMe)
def get_parent_me(
    db: Session = Depends(get_db),
    parent: Parent = Depends(get_current_parent),
):
    """Returns the authenticated parent's profile and contact details, plus their linked children."""
    children = (
        db.query(Candidate)
        .join(ParentChild, ParentChild.candidate_id == Candidate.id)
        .filter(ParentChild.parent_id == parent.id)
        .all()
    )
    return ParentMe(
        id=parent.id, full_name=parent.full_name, address=parent.address,
        phone_number=parent.phone_number, is_active=parent.is_active,
        created_at=parent.created_at, children=children,
    )


@router.post("/children/link", response_model=ChildSummary, status_code=status.HTTP_201_CREATED)
def link_child(
    payload: ParentLinkChildRequest,
    request: Request,
    db: Session = Depends(get_db),
    parent: Parent = Depends(get_current_parent),
):
    """
    Lets an already-registered parent add or link another ward using
    the ward's matriculation number, rather than only matching by
    name at registration time.
    """
    candidate = db.query(Candidate).filter(Candidate.matric_no == payload.matric_no).first()
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No student found with that matriculation number")

    existing = (
        db.query(ParentChild)
        .filter(ParentChild.parent_id == parent.id, ParentChild.candidate_id == candidate.id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This student is already linked to your account")

    db.add(ParentChild(parent_id=parent.id, candidate_id=candidate.id))
    db.commit()

    log_security_event(
        db, "parent_child_linked", parent.phone_number, get_client_ip(request),
        "/parent/children/link", f"candidate={candidate.id}",
    )
    return candidate


def _get_linked_child_or_404(db: Session, parent: Parent, candidate_id: str) -> Candidate:
    link = (
        db.query(ParentChild)
        .filter(ParentChild.parent_id == parent.id, ParentChild.candidate_id == candidate_id)
        .first()
    )
    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No child with that id is linked to your account",
        )
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    return candidate


@router.get("/children", response_model=List[ChildSummary])
def list_children(
    db: Session = Depends(get_db),
    parent: Parent = Depends(get_current_parent),
):
    """All candidates linked to this parent account."""
    return (
        db.query(Candidate)
        .join(ParentChild, ParentChild.candidate_id == Candidate.id)
        .filter(ParentChild.parent_id == parent.id)
        .all()
    )


@router.get("/children/{candidate_id}/exams", response_model=List[ChildExamStatus])
def child_exam_status(
    candidate_id: str,
    db: Session = Depends(get_db),
    parent: Parent = Depends(get_current_parent),
):
    """
    Every exam available to this child (i.e. belonging to a course
    they're enrolled in), each flagged done/undone, with the result
    attached when done.
    """
    child = _get_linked_child_or_404(db, parent, candidate_id)

    enrolled_course_ids = [
        row[0] for row in
        db.query(CourseEnrollment.course_id).filter(CourseEnrollment.candidate_id == child.id).all()
    ]
    if not enrolled_course_ids:
        return []

    exams = (
        db.query(Examination)
        .filter(Examination.course_id.in_(enrolled_course_ids))
        .order_by(Examination.created_at.desc())
        .all()
    )

    results_by_exam = {
        r.exam_id: r
        for r in db.query(Result).filter(Result.candidate_id == child.id).all()
    }

    return [
        ChildExamStatus(
            exam_id=exam.id,
            title=exam.title,
            course_id=exam.course_id,
            level=exam.level,
            duration_minutes=exam.duration_minutes,
            is_active=exam.is_active,
            done=exam.id in results_by_exam,
            result=ResultPublic.model_validate(results_by_exam[exam.id]) if exam.id in results_by_exam else None,
        )
        for exam in exams
    ]


@router.get("/children/{candidate_id}/results", response_model=List[ResultWithExam])
def child_results(
    candidate_id: str,
    db: Session = Depends(get_db),
    parent: Parent = Depends(get_current_parent),
):
    """Every completed result for this child, most recent first."""
    child = _get_linked_child_or_404(db, parent, candidate_id)

    rows = (
        db.query(Result, Examination.title)
        .join(Examination, Examination.id == Result.exam_id)
        .filter(Result.candidate_id == child.id)
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
