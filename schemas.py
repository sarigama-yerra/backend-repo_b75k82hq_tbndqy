"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- BlogPost -> "blogs" collection
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

# ---------------------------------------------------------------------
# Core schemas for Task Time Manager
# ---------------------------------------------------------------------

class Task(BaseModel):
    """
    Tasks collection schema
    Collection name: "task"
    """
    title: str = Field(..., description="Task title")
    description: Optional[str] = Field(None, description="Task details")
    status: str = Field("active", description="active | archived | completed")
    estimated_minutes: Optional[int] = Field(None, ge=0, description="Estimated effort in minutes")
    labels: List[str] = Field(default_factory=list, description="Tags/labels for grouping")

class Timeentry(BaseModel):
    """
    Time entries per task
    Collection name: "timeentry"
    """
    task_id: str = Field(..., description="Related task ID (string form of ObjectId)")
    start_time: Optional[datetime] = Field(None, description="Start time for running entry")
    end_time: Optional[datetime] = Field(None, description="End time when stopped")
    duration_sec: Optional[int] = Field(None, ge=0, description="Logged duration in seconds (for manual logs or after stop)")
    note: Optional[str] = Field(None, description="Optional note or description for the time entry")
    is_running: bool = Field(False, description="Whether the timer is currently running")
    date: Optional[str] = Field(None, description="Logical date (YYYY-MM-DD) for grouping, optional")

# ---------------------------------------------------------------------
# Example schemas (kept for reference)
# ---------------------------------------------------------------------

class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Email address")
    address: str = Field(..., description="Address")
    age: Optional[int] = Field(None, ge=0, le=120, description="Age in years")
    is_active: bool = Field(True, description="Whether user is active")

class Product(BaseModel):
    title: str = Field(..., description="Product title")
    description: Optional[str] = Field(None, description="Product description")
    price: float = Field(..., ge=0, description="Price in dollars")
    category: str = Field(..., description="Product category")
    in_stock: bool = Field(True, description="Whether product is in stock")
