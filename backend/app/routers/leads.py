from fastapi import APIRouter, HTTPException, status, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Annotated, Optional
from datetime import datetime
import logging

from app.dependencies import DbSession, CurrentUser
from app.models.lead import Lead
from app.services.apollo_service import ApolloService, ApolloError
from app.services.icp_parser import IcpParser, IcpParserError

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ApolloImportRequest(BaseModel):
    """Request to import leads from Apollo.io."""
    api_key: Optional[str] = None
    icp_description: str
    max_leads: int = 25
    save_template: bool = False
    template_name: Optional[str] = None


class ApolloSearchResponse(BaseModel):
    leads: list[LeadRead]
    total_found: int
    imported: int
    template_id: Optional[int] = None
    errors: list[str] = []


class IcpTemplateCreate(BaseModel):
    name: str
    natural_language_query: str
    structured_icp: Optional[dict] = None
    apollo_params: Optional[dict] = None


class IcpTemplateRead(BaseModel):
    id: int
    name: str
    natural_language_query: str
    structured_icp: Optional[dict]
    apollo_params: Optional[dict]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

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


# ---------------------------------------------------------------------------
# Apollo.io Import
# ---------------------------------------------------------------------------

@router.post("/import/apollo", response_model=ApolloSearchResponse)
async def import_from_apollo(
    body: ApolloImportRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    """Import leads from Apollo.io using a natural language ICP description.

    The ICP description is parsed by an LLM into structured search params,
    then sent to Apollo's API. Matching leads are saved to the database
    and returned in the response.
    """
    errors: list[str] = []
    try:
        # Step 1: Parse ICP via LLM
        parser = IcpParser()
        parsed = await parser.natural_language_to_apollo_params(
            body.icp_description
        )
        icp = parsed["icp"]
        apollo_params = parsed["apollo_params"]
        apollo_params["per_page"] = min(body.max_leads, 100)

        # Step 2: Search Apollo
        apollo = ApolloService(api_key=body.api_key)
        leads_data = await apollo.search_people(apollo_params)
        total_found = len(leads_data)

        # Step 3: Save to database
        imported = 0
        saved_leads = []
        for lead_data in leads_data[: body.max_leads]:
            existing = db.query(Lead).filter(
                Lead.owner_id == current_user.id,
                Lead.email == lead_data["email"],
            ).first()
            if existing:
                skipped += 1
                continue

            lead = Lead(
                owner_id=current_user.id,
                first_name=lead_data.get("first_name", ""),
                last_name=lead_data.get("last_name", ""),
                email=lead_data.get("email", ""),
                company=lead_data.get("company", ""),
                title=lead_data.get("title", ""),
                linkedin_url=lead_data.get("linkedin_url", ""),
                phone=lead_data.get("phone", ""),
                source="apollo",
                prospect_signals=lead_data.get("prospect_signals", {}),
                status="new",
            )
            db.add(lead)
            imported += 1
        db.commit()

        # Step 4: Save ICP template if requested
        template_id = None
        if body.save_template:
            from app.models.icp_template import IcpTemplate
            template = IcpTemplate(
                user_id=current_user.id,
                name=body.template_name or body.icp_description[:50],
                natural_language_query=body.icp_description,
                structured_icp=icp,
                apollo_params=apollo_params,
            )
            db.add(template)
            db.commit()
            db.refresh(template)
            template_id = template.id

        return ApolloSearchResponse(
            leads=saved_leads,
            total_found=total_found,
            imported=imported,
            template_id=template_id,
            errors=errors,
        )

    except IcpParserError as e:
        raise HTTPException(status_code=422, detail=f"ICP parsing failed: {str(e)}")
    except ApolloError as e:
        raise HTTPException(status_code=502, detail=f"Apollo API error: {str(e)}")
