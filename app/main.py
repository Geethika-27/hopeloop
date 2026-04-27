import hashlib
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional local convenience dependency
    def load_dotenv(*args, **kwargs):
        return False

load_dotenv()

from .db import Base, engine, get_db
from .gemini import GeminiNeedAnalyzer
from .matcher import run_allocation
from .models import ActivityEvent, AlertMessage, Assignment, CommunityReport, Need, Skill, Task, Volunteer
from .schemas import ReportCreate, VolunteerCreate

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Smart Volunteer Allocation", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
analyzer = None


class AlertCreate(BaseModel):
    channel: str = Field(pattern="^(sms|whatsapp)$")
    audience: str = Field(default="all", pattern="^(all|unassigned|location)$")
    location_scope: str | None = None
    task_id: int | None = None
    content: str = Field(min_length=8, max_length=500)


WARD_CENTER = (17.3850, 78.4867)


def _location_to_latlng(location: str) -> tuple[float, float]:
    text = (location or "").strip().lower()
    if text.startswith("ward "):
        try:
            ward_number = int(text.replace("ward ", "").strip())
            lat = WARD_CENTER[0] + ((ward_number % 7) - 3) * 0.013
            lng = WARD_CENTER[1] + ((ward_number % 9) - 4) * 0.015
            return round(lat, 6), round(lng, 6)
        except ValueError:
            pass

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    spread_a = int(digest[:4], 16) / 65535
    spread_b = int(digest[4:8], 16) / 65535
    lat = WARD_CENTER[0] + (spread_a - 0.5) * 0.18
    lng = WARD_CENTER[1] + (spread_b - 0.5) * 0.18
    return round(lat, 6), round(lng, 6)


@app.on_event("startup")
def startup() -> None:
    global analyzer
    analyzer = GeminiNeedAnalyzer()
    Base.metadata.create_all(bind=engine)


def _ensure_skill(db: Session, name: str) -> Skill:
    normalized = name.strip().lower().replace(" ", "_")
    skill = db.query(Skill).filter(Skill.name == normalized).first()
    if skill:
        return skill
    skill = Skill(name=normalized)
    db.add(skill)
    db.flush()
    return skill


def _serialize_need(need: Need) -> dict:
    return {
        "id": need.id,
        "title": need.title,
        "description": need.description,
        "category": need.category,
        "location": need.location,
        "urgency_score": need.urgency_score,
        "status": need.status,
        "skills": [skill.name for skill in need.skills],
        "created_at": need.created_at.isoformat() if need.created_at else None,
    }


def _serialize_task(task: Task) -> dict:
    return {
        "id": task.id,
        "need_id": task.need_id,
        "title": task.title,
        "description": task.description,
        "location": task.location,
        "priority_score": task.priority_score,
        "required_people": task.required_people,
        "assigned_count": task.assigned_count,
        "status": task.status,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def _serialize_volunteer(volunteer: Volunteer) -> dict:
    return {
        "id": volunteer.id,
        "name": volunteer.name,
        "email": volunteer.email,
        "phone": volunteer.phone,
        "location": volunteer.location,
        "availability_hours": volunteer.availability_hours,
        "is_active": volunteer.is_active,
        "skills": [skill.name for skill in volunteer.skills],
    }


def _serialize_assignment(assignment: Assignment) -> dict:
    return {
        "id": assignment.id,
        "task_id": assignment.task_id,
        "volunteer_id": assignment.volunteer_id,
        "match_score": assignment.match_score,
        "status": assignment.status,
    }


def _serialize_assignment_rich(assignment: Assignment) -> dict:
    payload = _serialize_assignment(assignment)
    payload["task_title"] = assignment.task.title if assignment.task else None
    payload["volunteer_name"] = assignment.volunteer.name if assignment.volunteer else None
    payload["location"] = assignment.task.location if assignment.task else None
    payload["assigned_at"] = assignment.assigned_at.isoformat() if assignment.assigned_at else None
    return payload


def _serialize_alert(alert: AlertMessage) -> dict:
    return {
        "id": alert.id,
        "channel": alert.channel,
        "audience": alert.audience,
        "location_scope": alert.location_scope,
        "task_id": alert.task_id,
        "content": alert.content,
        "status": alert.status,
        "provider_message": alert.provider_message,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "sent_at": alert.sent_at.isoformat() if alert.sent_at else None,
    }


def _serialize_activity(event: ActivityEvent) -> dict:
    return {
        "id": event.id,
        "actor": event.actor,
        "action": event.action,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "details": event.details,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _log_activity(
    db: Session,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: int | None,
    details: str,
) -> None:
    db.add(
        ActivityEvent(
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
        )
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/meta")
def api_meta():
    return {
        "gemini_enabled": bool(analyzer and analyzer.enabled),
        "gemini_required": True,
        "model": analyzer.model_name if analyzer else None,
    }


@app.post("/api/reports")
def create_report(payload: ReportCreate, db: Session = Depends(get_db)):
    if analyzer is None:
        raise HTTPException(status_code=503, detail="Gemini service is not initialized")

    report = CommunityReport(
        source_type=payload.source_type,
        raw_text=payload.raw_text,
        location=payload.location,
    )
    db.add(report)
    db.flush()

    try:
        analysis = analyzer.analyze(payload.raw_text, payload.location)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    need = Need(
        title=analysis["title"],
        description=analysis["description"],
        category=analysis["category"],
        location=payload.location,
        urgency_score=float(analysis["urgency_score"]),
        report_id=report.id,
        status="open",
    )
    db.add(need)
    db.flush()

    for skill_name in analysis.get("required_skills", ["community_outreach"]):
        skill = _ensure_skill(db, skill_name)
        need.skills.append(skill)

    task = Task(
        need_id=need.id,
        title=analysis.get("task_title") or f"Respond to need #{need.id}",
        description=analysis.get("task_description") or need.description,
        location=need.location,
        priority_score=need.urgency_score,
        required_people=int(analysis.get("required_people", 3)),
        status="open",
    )
    db.add(task)
    db.flush()
    _log_activity(
        db,
        actor="coordinator",
        action="created_report_and_task",
        entity_type="task",
        entity_id=task.id,
        details=f"Created task for {payload.location} with urgency {need.urgency_score}",
    )
    db.commit()
    db.refresh(need)
    db.refresh(task)

    return {
        "message": "Report processed successfully",
        "need": _serialize_need(need),
        "task": _serialize_task(task),
    }


@app.get("/api/needs")
def get_needs(db: Session = Depends(get_db)):
    needs = db.query(Need).order_by(Need.urgency_score.desc()).limit(100).all()
    return [_serialize_need(need) for need in needs]


@app.get("/api/tasks")
def get_tasks(db: Session = Depends(get_db)):
    tasks = db.query(Task).order_by(Task.priority_score.desc()).limit(100).all()
    return [_serialize_task(task) for task in tasks]


@app.post("/api/volunteers")
def create_volunteer(payload: VolunteerCreate, db: Session = Depends(get_db)):
    exists = db.query(Volunteer).filter(Volunteer.email == payload.email).first()
    if exists:
        raise HTTPException(status_code=409, detail="Volunteer email already exists")

    volunteer = Volunteer(
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        location=payload.location,
        availability_hours=payload.availability_hours,
        is_active=True,
    )
    db.add(volunteer)
    db.flush()

    for skill_name in payload.skills:
        if skill_name.strip():
            volunteer.skills.append(_ensure_skill(db, skill_name))

    _log_activity(
        db,
        actor="coordinator",
        action="registered_volunteer",
        entity_type="volunteer",
        entity_id=volunteer.id,
        details=f"Volunteer {volunteer.name} added in {volunteer.location}",
    )
    db.commit()
    db.refresh(volunteer)
    return _serialize_volunteer(volunteer)


@app.get("/api/volunteers")
def get_volunteers(db: Session = Depends(get_db)):
    volunteers = db.query(Volunteer).order_by(Volunteer.created_at.desc()).limit(200).all()
    return [_serialize_volunteer(v) for v in volunteers]


@app.post("/api/allocate")
def allocate_volunteers(db: Session = Depends(get_db)):
    assignments = run_allocation(db)
    _log_activity(
        db,
        actor="allocator",
        action="ran_allocation",
        entity_type="assignment",
        entity_id=None,
        details=f"Created {len(assignments)} assignments",
    )
    db.commit()
    return {
        "created": len(assignments),
        "assignments": [_serialize_assignment(a) for a in assignments],
    }


@app.get("/api/assignments")
def get_assignments(db: Session = Depends(get_db)):
    assignments = (
        db.query(Assignment)
        .order_by(Assignment.assigned_at.desc())
        .limit(200)
        .all()
    )
    return [_serialize_assignment_rich(a) for a in assignments]


@app.post("/api/assignments/{assignment_id}/complete")
def complete_assignment(assignment_id: int, db: Session = Depends(get_db)):
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    if assignment.status == "completed":
        return {"message": "Assignment already completed", "assignment": _serialize_assignment_rich(assignment)}

    assignment.status = "completed"
    task = assignment.task
    if task and task.status in {"open", "in_progress"} and task.assigned_count > 0:
        task.assigned_count -= 1
        if task.assigned_count < task.required_people:
            task.status = "open"

    _log_activity(
        db,
        actor="coordinator",
        action="completed_assignment",
        entity_type="assignment",
        entity_id=assignment.id,
        details=f"Completed assignment for task {assignment.task_id}",
    )

    db.commit()
    db.refresh(assignment)
    return {"message": "Assignment marked complete", "assignment": _serialize_assignment_rich(assignment)}


@app.post("/api/assignments/{assignment_id}/undo")
def undo_complete_assignment(assignment_id: int, db: Session = Depends(get_db)):
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    if assignment.status != "completed":
        return {"message": "Assignment is not completed", "assignment": _serialize_assignment_rich(assignment)}

    assignment.status = "pending"
    task = assignment.task
    if task:
        task.assigned_count += 1
        if task.assigned_count >= task.required_people:
            task.status = "in_progress"
        else:
            task.status = "open"
        if task.need and task.need.status == "resolved":
            task.need.status = "open"

    _log_activity(
        db,
        actor="coordinator",
        action="undid_assignment_completion",
        entity_type="assignment",
        entity_id=assignment.id,
        details=f"Restored assignment for task {assignment.task_id}",
    )

    db.commit()
    db.refresh(assignment)
    return {"message": "Assignment restored", "assignment": _serialize_assignment_rich(assignment)}


@app.post("/api/assignments/complete-all")
def complete_all_assignments(db: Session = Depends(get_db)):
    pending = (
        db.query(Assignment)
        .filter(Assignment.status.in_(["pending", "accepted"]))
        .all()
    )
    count = 0
    for assignment in pending:
        assignment.status = "completed"
        task = assignment.task
        if task and task.status in {"open", "in_progress"} and task.assigned_count > 0:
            task.assigned_count -= 1
            if task.assigned_count < task.required_people:
                task.status = "open"
        count += 1

    _log_activity(
        db,
        actor="coordinator",
        action="completed_all_assignments",
        entity_type="assignment",
        entity_id=None,
        details=f"Completed {count} assignments in bulk",
    )

    db.commit()
    return {"message": "Pending assignments completed", "count": count}


@app.post("/api/tasks/{task_id}/complete")
def complete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = "completed"
    if task.need:
        task.need.status = "resolved"
    for assignment in task.assignments:
        if assignment.status in {"pending", "accepted"}:
            assignment.status = "completed"

    _log_activity(
        db,
        actor="coordinator",
        action="completed_task",
        entity_type="task",
        entity_id=task.id,
        details=f"Marked task {task.title} as completed",
    )

    db.commit()
    db.refresh(task)
    return {"message": "Task marked complete", "task": _serialize_task(task)}


@app.post("/api/tasks/{task_id}/undo")
def undo_complete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != "completed":
        return {"message": "Task is not completed", "task": _serialize_task(task)}

    task.status = "open"
    if task.need and task.need.status == "resolved":
        task.need.status = "open"

    reopened = 0
    for assignment in task.assignments:
        if assignment.status == "completed" and reopened < task.required_people:
            assignment.status = "pending"
            reopened += 1
    task.assigned_count = reopened
    if task.assigned_count >= task.required_people:
        task.status = "in_progress"

    _log_activity(
        db,
        actor="coordinator",
        action="undid_task_completion",
        entity_type="task",
        entity_id=task.id,
        details=f"Reopened task {task.title}",
    )

    db.commit()
    db.refresh(task)
    return {"message": "Task restored", "task": _serialize_task(task), "reopened_assignments": reopened}


@app.get("/api/history/completed")
def get_completed_history(db: Session = Depends(get_db)):
    completed_assignments = (
        db.query(Assignment)
        .filter(Assignment.status == "completed")
        .order_by(Assignment.assigned_at.desc())
        .limit(200)
        .all()
    )
    completed_tasks = (
        db.query(Task)
        .filter(Task.status == "completed")
        .order_by(Task.created_at.desc())
        .limit(200)
        .all()
    )
    return {
        "assignments": [_serialize_assignment_rich(a) for a in completed_assignments],
        "tasks": [_serialize_task(t) for t in completed_tasks],
    }


@app.get("/api/dashboard")
def get_dashboard(db: Session = Depends(get_db)):
    open_needs = db.query(Need).filter(Need.status == "open").count()
    open_tasks = db.query(Task).filter(Task.status == "open").count()
    volunteers = db.query(Volunteer).filter(Volunteer.is_active.is_(True)).count()
    assignments = db.query(Assignment).count()

    urgent_needs = (
        db.query(Need)
        .order_by(Need.urgency_score.desc())
        .limit(5)
        .all()
    )
    critical_tasks = (
        db.query(Task)
        .order_by(Task.priority_score.desc())
        .limit(5)
        .all()
    )

    return {
        "metrics": {
            "open_needs": open_needs,
            "open_tasks": open_tasks,
            "active_volunteers": volunteers,
            "total_assignments": assignments,
        },
        "urgent_needs": [_serialize_need(n) for n in urgent_needs],
        "critical_tasks": [_serialize_task(t) for t in critical_tasks],
    }


@app.get("/api/dashboard/role")
def get_dashboard_role(role: str = "coordinator", db: Session = Depends(get_db)):
    role_name = role.strip().lower()
    if role_name not in {"coordinator", "field", "volunteer"}:
        raise HTTPException(status_code=400, detail="Unsupported role")

    all_needs = db.query(Need).order_by(Need.urgency_score.desc()).limit(100).all()
    all_tasks = db.query(Task).order_by(Task.priority_score.desc()).limit(100).all()
    all_volunteers = db.query(Volunteer).filter(Volunteer.is_active.is_(True)).all()

    if role_name == "coordinator":
        cards = [
            {"label": "Needs To Triage", "value": sum(1 for n in all_needs if n.status == "open")},
            {"label": "Open Operations", "value": sum(1 for t in all_tasks if t.status == "open")},
            {"label": "Available Volunteers", "value": len(all_volunteers)},
        ]
        priorities = [
            "Run allocation after every new high-urgency report.",
            "Broadcast alerts to unassigned volunteers in hotspot wards.",
            "Review top 3 unstafed tasks before end of day.",
        ]
    elif role_name == "field":
        cards = [
            {"label": "Critical Field Needs", "value": sum(1 for n in all_needs if n.urgency_score >= 80)},
            {"label": "Tasks In Progress", "value": sum(1 for t in all_tasks if t.status == "in_progress")},
            {"label": "Local Volunteers", "value": len(all_volunteers)},
        ]
        priorities = [
            "Escalate needs with urgency > 90 immediately.",
            "Close completed tasks to unblock new assignments.",
            "Capture precise location labels for better route matching.",
        ]
    else:
        open_tasks = [t for t in all_tasks if t.status in {"open", "in_progress"}]
        cards = [
            {"label": "Active Missions", "value": len(open_tasks)},
            {"label": "High Priority Missions", "value": sum(1 for t in open_tasks if t.priority_score >= 80)},
            {"label": "Your Shift Capacity", "value": round(sum(v.availability_hours for v in all_volunteers), 1)},
        ]
        priorities = [
            "Accept tasks near your location first.",
            "Update availability each shift to improve matching.",
            "Join focused alerts for your strongest skills.",
        ]

    return {
        "role": role_name,
        "cards": cards,
        "priorities": priorities,
    }


@app.get("/api/map/heat")
def get_map_heat(db: Session = Depends(get_db)):
    needs = db.query(Need).order_by(Need.urgency_score.desc()).limit(200).all()
    tasks = db.query(Task).all()
    volunteers = db.query(Volunteer).filter(Volunteer.is_active.is_(True)).all()

    needs_by_location = defaultdict(list)
    for need in needs:
        needs_by_location[need.location].append(need)

    task_load = defaultdict(int)
    for task in tasks:
        if task.status in {"open", "in_progress"}:
            task_load[task.location] += max(0, task.required_people - task.assigned_count)

    volunteer_count = defaultdict(int)
    for volunteer in volunteers:
        volunteer_count[volunteer.location] += 1

    points = []
    for location, location_needs in needs_by_location.items():
        avg_urgency = sum(n.urgency_score for n in location_needs) / len(location_needs)
        need_count = len(location_needs)
        load_gap = task_load[location]
        active_volunteers = volunteer_count[location]
        pressure = round(min(100, avg_urgency * 0.6 + need_count * 8 + load_gap * 6), 2)
        lat, lng = _location_to_latlng(location)
        points.append(
            {
                "location": location,
                "lat": lat,
                "lng": lng,
                "avg_urgency": round(avg_urgency, 2),
                "need_count": need_count,
                "staff_gap": load_gap,
                "volunteers": active_volunteers,
                "pressure": pressure,
            }
        )

    points.sort(key=lambda p: p["pressure"], reverse=True)
    return {
        "center": {"lat": WARD_CENTER[0], "lng": WARD_CENTER[1]},
        "points": points,
    }


@app.get("/api/forecast")
def get_forecast(db: Session = Depends(get_db)):
    needs = db.query(Need).all()
    if not needs:
        return {"month": datetime.utcnow().strftime("%B"), "categories": [], "insights": []}

    current_month = datetime.utcnow().month
    category_counts = defaultdict(int)
    current_month_counts = defaultdict(int)
    previous_month_counts = defaultdict(int)
    urgency_sum = defaultdict(float)

    for need in needs:
        category = need.category
        category_counts[category] += 1
        urgency_sum[category] += need.urgency_score
        month = need.created_at.month if need.created_at else current_month
        if month == current_month:
            current_month_counts[category] += 1
        elif month == ((current_month - 2) % 12) + 1:
            previous_month_counts[category] += 1

    categories = []
    for category, total_count in category_counts.items():
        base = total_count / max(1, len(needs))
        momentum = current_month_counts[category] - previous_month_counts[category]
        seasonal_factor = 1.15 if current_month in {6, 7, 8, 9} else 1.0
        if category in {"healthcare", "water_and_sanitation"} and current_month in {6, 7, 8, 9}:
            seasonal_factor += 0.2
        projected_requests = max(1, round((total_count * 0.35 + current_month_counts[category] * 0.65) * seasonal_factor))
        avg_urgency = round(urgency_sum[category] / total_count, 2)
        confidence = round(min(0.95, 0.55 + (total_count / max(4, len(needs))) + abs(momentum) * 0.03), 2)
        categories.append(
            {
                "category": category,
                "projected_requests": projected_requests,
                "avg_urgency": avg_urgency,
                "momentum": momentum,
                "share": round(base, 2),
                "confidence": confidence,
            }
        )

    categories.sort(key=lambda c: (c["projected_requests"], c["avg_urgency"]), reverse=True)
    top = categories[:3]
    insights = [
        f"Forecast peak area: {top[0]['category']} with projected {top[0]['projected_requests']} requests."
    ]
    if len(top) > 1:
        insights.append(
            f"Secondary demand likely in {top[1]['category']}; pre-position volunteers and supplies."
        )
    if any(c["momentum"] > 0 for c in top):
        insights.append("Demand momentum is rising in at least one category this month.")
    else:
        insights.append("Demand trend appears stable; continue current resource distribution.")

    return {
        "month": datetime.utcnow().strftime("%B"),
        "categories": categories,
        "insights": insights,
    }


@app.post("/api/alerts")
def queue_alert(payload: AlertCreate, db: Session = Depends(get_db)):
    if payload.audience == "location" and not payload.location_scope:
        raise HTTPException(status_code=400, detail="location_scope is required for location audience")

    if payload.task_id is not None:
        task = db.query(Task).filter(Task.id == payload.task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

    alert = AlertMessage(
        channel=payload.channel,
        audience=payload.audience,
        location_scope=payload.location_scope,
        task_id=payload.task_id,
        content=payload.content,
        status="queued",
        provider_message="queued_for_dispatch",
    )
    db.add(alert)
    _log_activity(
        db,
        actor="coordinator",
        action="queued_alert",
        entity_type="alert",
        entity_id=None,
        details=f"Queued {payload.channel} alert for audience {payload.audience}",
    )
    db.commit()
    db.refresh(alert)
    return _serialize_alert(alert)


@app.post("/api/alerts/dispatch")
def dispatch_alerts(db: Session = Depends(get_db)):
    queued = (
        db.query(AlertMessage)
        .filter(AlertMessage.status == "queued")
        .order_by(AlertMessage.created_at.asc())
        .limit(25)
        .all()
    )
    dispatched = []
    for alert in queued:
        recipients_query = db.query(Volunteer).filter(Volunteer.is_active.is_(True))
        if alert.audience == "unassigned":
            recipients_query = recipients_query.filter(
                ~Volunteer.assignments.any(Assignment.status.in_(["pending", "accepted"]))
            )
        elif alert.audience == "location" and alert.location_scope:
            recipients_query = recipients_query.filter(Volunteer.location == alert.location_scope)

        recipient_count = recipients_query.count()
        alert.status = "sent"
        alert.sent_at = datetime.utcnow()
        alert.provider_message = f"simulated_dispatch:{recipient_count}_recipients"
        dispatched.append(alert)

    _log_activity(
        db,
        actor="dispatcher",
        action="dispatched_alerts",
        entity_type="alert",
        entity_id=None,
        details=f"Dispatched {len(dispatched)} alerts",
    )

    db.commit()
    return {
        "processed": len(dispatched),
        "alerts": [_serialize_alert(a) for a in dispatched],
    }


@app.get("/api/alerts")
def list_alerts(db: Session = Depends(get_db)):
    alerts = db.query(AlertMessage).order_by(AlertMessage.created_at.desc()).limit(100).all()
    return [_serialize_alert(a) for a in alerts]


@app.get("/api/activity")
def list_activity(db: Session = Depends(get_db)):
    events = db.query(ActivityEvent).order_by(ActivityEvent.created_at.desc()).limit(200).all()
    return [_serialize_activity(e) for e in events]


@app.post("/api/demo/seed")
def seed_demo(db: Session = Depends(get_db)):
    if db.query(Volunteer).count() == 0:
        samples = [
            {
                "name": "Aarav Reddy",
                "email": "aarav@example.org",
                "location": "Ward 12",
                "skills": ["first_aid", "community_outreach"],
                "availability_hours": 6,
            },
            {
                "name": "Maya Joseph",
                "email": "maya@example.org",
                "location": "Ward 9",
                "skills": ["distribution", "inventory"],
                "availability_hours": 5,
            },
            {
                "name": "Nikhil Das",
                "email": "nikhil@example.org",
                "location": "Ward 12",
                "skills": ["teaching", "mentoring"],
                "availability_hours": 4,
            },
        ]
        for sample in samples:
            volunteer = Volunteer(
                name=sample["name"],
                email=sample["email"],
                location=sample["location"],
                availability_hours=sample["availability_hours"],
            )
            db.add(volunteer)
            db.flush()
            for skill_name in sample["skills"]:
                volunteer.skills.append(_ensure_skill(db, skill_name))

    db.commit()
    return {"message": "Demo volunteers seeded"}
