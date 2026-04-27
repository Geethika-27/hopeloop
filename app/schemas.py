from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ReportCreate(BaseModel):
    source_type: str = "field_report"
    raw_text: str = Field(min_length=12)
    location: str


class VolunteerCreate(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    location: str
    availability_hours: float = 4.0
    skills: list[str] = []


class VolunteerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    location: str
    availability_hours: float
    is_active: bool
    skills: list[str]


class NeedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    category: str
    location: str
    urgency_score: float
    status: str
    created_at: datetime
    skills: list[str]


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    location: str
    priority_score: float
    required_people: int
    assigned_count: int
    status: str


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    volunteer_id: int
    match_score: float
    status: str
