from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Candidate, Parent, ParentChild


def match_and_link_children(
    db: Session, parent: Parent, children_names: list[str]
) -> list[dict]:
    """
    For each submitted child name, look up candidates whose full_name
    matches case-insensitively (leading/trailing whitespace ignored).
    Every match found is linked to the parent via ParentChild (if not
    already linked). A name may match more than one candidate (e.g.
    duplicate full names) — all matches are linked.

    Returns a list of per-name match info dicts:
        {"name_submitted": str, "matched": bool,
         "candidate_id": str | None, "matric_no": str | None}
    Callers should treat an all-False result as a failed registration.
    """
    results: list[dict] = []

    for raw_name in children_names:
        name = raw_name.strip()
        if not name:
            results.append(
                {"name_submitted": raw_name, "matched": False, "candidate_id": None, "matric_no": None}
            )
            continue

        candidates = (
            db.query(Candidate)
            .filter(func.lower(Candidate.full_name) == name.lower())
            .all()
        )

        if not candidates:
            results.append(
                {"name_submitted": raw_name, "matched": False, "candidate_id": None, "matric_no": None}
            )
            continue

        for candidate in candidates:
            existing = (
                db.query(ParentChild)
                .filter(
                    ParentChild.parent_id == parent.id,
                    ParentChild.candidate_id == candidate.id,
                )
                .first()
            )
            if not existing:
                db.add(ParentChild(parent_id=parent.id, candidate_id=candidate.id))

            results.append(
                {
                    "name_submitted": raw_name,
                    "matched": True,
                    "candidate_id": candidate.id,
                    "matric_no": candidate.matric_no,
                }
            )

    db.commit()
    return results
