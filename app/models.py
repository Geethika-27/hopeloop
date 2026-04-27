from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import relationship

from .db import Base

volunteer_skill = Table(
    "volunteer_skill",
    Base.metadata,
    Column("volunteer_id", ForeignKey("volunteers.id"), primary_key=True),
    Column("skill_id", ForeignKey("skills.id"), primary_key=True),
)

need_skill = Table(
    "need_skill",
    Base.metadata,
    Column("need_id", ForeignKey("needs.id"), primary_key=True),
    Column("skill_id", ForeignKey("skills.id"), primary_key=True),
)


class CommunityReport(Base):
    __tablename__ = "community_reports"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String(64), default="field_report")
    raw_text = Column(Text, nullable=False)
    location = Column(String(120), nullable=False)
    reported_at = Column(DateTime, default=datetime.utcnow)

    need = relationship("Need", back_populates="report", uselist=False)


class Skill(Base):
    __tablename__ = "skills"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(80), unique=True, index=True, nullable=False)


class Need(Base):
    __tablename__ = "needs"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(180), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(80), nullable=False)
    location = Column(String(120), nullable=False)
    urgency_score = Column(Float, default=50.0)
    status = Column(String(32), default="open")
    created_at = Column(DateTime, default=datetime.utcnow)

    report_id = Column(Integer, ForeignKey("community_reports.id"), unique=True)
    report = relationship("CommunityReport", back_populates="need")
    skills = relationship("Skill", secondary=need_skill)
    task = relationship("Task", back_populates="need", uselist=False)


class Volunteer(Base):
    __tablename__ = "volunteers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(180), unique=True, nullable=False)
    phone = Column(String(40), nullable=True)
    location = Column(String(120), nullable=False)
    availability_hours = Column(Float, default=4.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    skills = relationship("Skill", secondary=volunteer_skill)
    assignments = relationship("Assignment", back_populates="volunteer")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    need_id = Column(Integer, ForeignKey("needs.id"), unique=True)
    title = Column(String(180), nullable=False)
    description = Column(Text, nullable=False)
    location = Column(String(120), nullable=False)
    priority_score = Column(Float, default=50.0)
    required_people = Column(Integer, default=1)
    assigned_count = Column(Integer, default=0)
    status = Column(String(32), default="open")
    created_at = Column(DateTime, default=datetime.utcnow)

    need = relationship("Need", back_populates="task")
    assignments = relationship("Assignment", back_populates="task")


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    volunteer_id = Column(Integer, ForeignKey("volunteers.id"), nullable=False)
    match_score = Column(Float, nullable=False)
    status = Column(String(32), default="pending")
    assigned_at = Column(DateTime, default=datetime.utcnow)

    task = relationship("Task", back_populates="assignments")
    volunteer = relationship("Volunteer", back_populates="assignments")


class AlertMessage(Base):
    __tablename__ = "alert_messages"

    id = Column(Integer, primary_key=True, index=True)
    channel = Column(String(20), nullable=False)  # sms | whatsapp
    audience = Column(String(32), default="all")
    location_scope = Column(String(120), nullable=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    content = Column(Text, nullable=False)
    status = Column(String(32), default="queued")  # queued | sent | failed
    provider_message = Column(String(240), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)

    task = relationship("Task")


class ActivityEvent(Base):
    __tablename__ = "activity_events"

    id = Column(Integer, primary_key=True, index=True)
    actor = Column(String(120), default="system")
    action = Column(String(120), nullable=False)
    entity_type = Column(String(64), nullable=False)
    entity_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
