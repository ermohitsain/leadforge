from fastapi import APIRouter, HTTPException, status, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Annotated, Optional
from datetime import datetime
import logging

from app.dependencies import DbSession, CurrentUser
from app.models.lead import Lead

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class LeadCreate(BaseModel):
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    job_title: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    website: Optional[str] = None
    linkedin_url: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    notes: Optional[str] = None


class LeadUpdate(BaseModel):
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    job_title: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    website: Optional[str] = None
    linkedin_url: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    status: Optional[str] = None
    score: Optional[float] = None
    notes: Optional[str] = None


class LeadRead(BaseModel):
    id: int
    owner_id: int
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    phone: Optional[str]
    company: Optional[str]
    job_title: Optional[str]
    industry: Optional[str]
    company_size: Optional[str]
    website: Optional[str]
    linkedin_url: Optional[str]
    city: Optional[str]
    state: Optional[str]
    country: Optional[str]
    status: str
    score: Optional[float]
    notes: Optional[str]
    crm_id: Optional[str]
    crm_source: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeadListResponse(BaseModel):
    items: list[LeadRead]
    total: int
    page: int
    page_size: int


VALID_STATUSES = {"new", "contacted", "qualified", "unqualified", "converted", "do_not_contact"}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=LeadListResponse)
def list_leads(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None, description="Search by email, name, or company"),
):
    """List all leads for the authenticated user with pagination & filters."""
    query = db.query(Lead).filter(Lead.owner_id == current_user.id)

    if status:
        query = query.filter(Lead.status == status)
    if search:
        like = f"%{search}%"
        from sqlalchemy import or_
        query = query.filter(
            or_(
                Lead.email.ilike(like),
                Lead.first_name.ilike(like),
                Lead.last_name.ilike(like),
                Lead.company.ilike(like),
            )
        )

    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return LeadListResponse(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=LeadRead, status_code=status.HTTP_201_CREATED)
def create_lead(body: LeadCreate, db: DbSession, current_user: CurrentUser):
    """Create a new lead."""
    existing = db.query(Lead).filter(
        Lead.owner_id == current_user.id, Lead.email == body.email
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Lead with email '{body.email}' already exists",
        )
    lead = Lead(**body.model_dump(), owner_id=current_user.id)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    logger.info("Lead created: id=%d email=%s owner=%d", lead.id, lead.email, current_user.id)
    return lead


@router.get("/{lead_id}", response_model=LeadRead)
def get_lead(lead_id: int, db: DbSession, current_user: CurrentUser):
    """Get a single lead by ID."""
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.owner_id == current_user.id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.patch("/{lead_id}", response_model=LeadRead)
def update_lead(lead_id: int, body: LeadUpdate, db: DbSession, current_user: CurrentUser):
    """Partially update a lead."""
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.owner_id == current_user.id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    update_data = body.model_dump(exclude_unset=True)
    if "status" in update_data and update_data["status"] not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status. Must be one of: {VALID_STATUSES}")

    for field, value in update_data.items():
        setattr(lead, field, value)

    db.commit()
    db.refresh(lead)
    return lead


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lead(lead_id: int, db: DbSession, current_user: CurrentUser):
    """Delete a lead permanently."""
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.owner_id == current_user.id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    db.delete(lead)
    db.commit()


@router.post("/bulk", response_model=dict, status_code=status.HTTP_201_CREATED)
def bulk_import_leads(
    leads: list[LeadCreate],
    db: DbSession,
    current_user: CurrentUser,
):
    """Bulk import leads (skips duplicates by email)."""
    created = 0
    skipped = 0
    for item in leads:
        existing = db.query(Lead).filter(
            Lead.owner_id == current_user.id, Lead.email == item.email
        ).first()
        if existing:
            skipped += 1
            continue
        db.add(Lead(**item.model_dump(), owner_id=current_user.id))
        created += 1

    db.commit()
    return {"created": created, "skipped": skipped, "total": len(leads)}
