from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime


class Project(BaseModel):
    id: str
    name: str
    short_context: str
    project_summary: str = ""
    status: Literal["active", "paused", "archived"] = "active"
    owners: List[str] = []


KUType = Literal["Discussion", "Decision", "Hypothesis", "Note"]
KUStatus = Literal["Active", "Concluded", "Frozen", "Archived"]


class KUContent(BaseModel):
    summary: str = ""
    decisions: List[str] = []
    open_questions: List[str] = []
    next_steps: List[str] = []
    notes: List[str] = []


class KU(BaseModel):
    id: str
    project_id: Optional[str]
    type: KUType
    title: str
    status: KUStatus = "Active"

    content_ai: KUContent = Field(default_factory=KUContent)
    content_human: str = ""

    last_activity_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)
