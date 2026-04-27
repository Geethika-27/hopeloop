from sqlalchemy import and_
from sqlalchemy.orm import Session, joinedload

from .models import Assignment, Need, Task, Volunteer


def _score(volunteer: Volunteer, task: Task) -> float:
    task_skills = {skill.name.lower() for skill in task.need.skills}
    volunteer_skills = {skill.name.lower() for skill in volunteer.skills}

    if task_skills:
        overlap = len(task_skills.intersection(volunteer_skills)) / len(task_skills)
    else:
        overlap = 0.5

    location_match = 1.0 if volunteer.location.lower() == task.location.lower() else 0.3
    availability = min(1.0, volunteer.availability_hours / 8.0)
    urgency = min(1.0, task.priority_score / 100.0)

    total = (
        overlap * 0.45
        + location_match * 0.2
        + availability * 0.2
        + urgency * 0.15
    )
    return round(total * 100, 2)


def run_allocation(db: Session, max_assignments_per_volunteer: int = 2) -> list[Assignment]:
    tasks = (
        db.query(Task)
        .options(joinedload(Task.need).joinedload(Need.skills), joinedload(Task.assignments))
        .filter(Task.status == "open")
        .all()
    )

    volunteers = (
        db.query(Volunteer)
        .options(joinedload(Volunteer.skills), joinedload(Volunteer.assignments))
        .filter(Volunteer.is_active.is_(True))
        .all()
    )

    created: list[Assignment] = []

    for task in tasks:
        slots = max(0, task.required_people - task.assigned_count)
        if slots == 0:
            continue

        ranked = sorted(volunteers, key=lambda v: _score(v, task), reverse=True)

        for volunteer in ranked:
            if slots == 0:
                break

            active_assignments = [
                a for a in volunteer.assignments if a.status in {"pending", "accepted"}
            ]
            if len(active_assignments) >= max_assignments_per_volunteer:
                continue

            existing = db.query(Assignment).filter(
                and_(Assignment.task_id == task.id, Assignment.volunteer_id == volunteer.id)
            ).first()
            if existing:
                continue

            match_score = _score(volunteer, task)
            if match_score < 40:
                continue

            assignment = Assignment(
                task_id=task.id,
                volunteer_id=volunteer.id,
                match_score=match_score,
                status="pending",
            )
            db.add(assignment)
            created.append(assignment)
            task.assigned_count += 1
            slots -= 1

        if task.assigned_count >= task.required_people:
            task.status = "in_progress"

    db.commit()
    for assignment in created:
        db.refresh(assignment)
    return created
