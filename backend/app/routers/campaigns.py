from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime
import logging

from app.dependencies import DbSession, CurrentUser
from app.models.campaign import Campaign
from app.models.campaign_event import CampaignEvent
from app.models.lead import Lead

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class SequenceStep(BaseModel):
    day: int
    subject: str
    body_template: str


class AIPersona(BaseModel):
    tone: str = "professional"
    goal: str = "book_demo"
    company_context: Optional[str] = None
    value_prop: Optional[str] = None


class CampaignCreate(BaseModel):
    name: str
    description: Optional[str] = None
    from_name: Optional[str] = None
    from_email: Optional[str] = None
    reply_to: Optional[str] = None
    daily_send_limit: int = 50
    sequence_steps: Optional[list[SequenceStep]] = None
    ai_persona: Optional[AIPersona] = None


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    from_name: Optional[str] = None
    from_email: Optional[str] = None
    reply_to: Optional[str] = None
    daily_send_limit: Optional[int] = None
    sequence_steps: Optional[list[SequenceStep]] = None
    ai_persona: Optional[AIPersona] = None
    status: Optional[str] = None


class CampaignRead(BaseModel):
    id: int
    owner_id: int
    name: str
    description: Optional[str]
    status: str
    from_name: Optional[str]
    from_email: Optional[str]
    reply_to: Optional[str]
    daily_send_limit: int
    sequence_steps: Optional[list[Any]]
    ai_persona: Optional[dict]
    temporal_workflow_id: Optional[str]
    total_leads: int
    emails_sent: int
    emails_opened: int
    emails_replied: int
    emails_bounced: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CampaignListResponse(BaseModel):
    items: list[CampaignRead]
    total: int
    page: int
    page_size: int


class CampaignEventRead(BaseModel):
    id: int
    campaign_id: int
    lead_id: int
    event_type: str
    step_index: int
    subject: Optional[str]
    body_snippet: Optional[str]
    message_id: Optional[str]
    error_message: Optional[str]
    occurred_at: datetime

    model_config = {"from_attributes": True}


class AddLeadsToCampaign(BaseModel):
    lead_ids: list[int]


VALID_STATUSES = {"draft", "active", "paused", "completed", "archived"}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=CampaignListResponse)
def list_campaigns(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    status: Optional[str] = Query(None),
):
    query = db.query(Campaign).filter(Campaign.owner_id == current_user.id)
    if status:
        query = query.filter(Campaign.status == status)
    total = query.count()
    items = query.order_by(Campaign.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return CampaignListResponse(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=CampaignRead, status_code=status.HTTP_201_CREATED)
def create_campaign(body: CampaignCreate, db: DbSession, current_user: CurrentUser):
    data = body.model_dump()
    # Serialize nested Pydantic models to plain dicts/lists
    if data.get("sequence_steps"):
        data["sequence_steps"] = [s if isinstance(s, dict) else s.model_dump() for s in (body.sequence_steps or [])]
    if data.get("ai_persona") and hasattr(body.ai_persona, "model_dump"):
        data["ai_persona"] = body.ai_persona.model_dump()

    campaign = Campaign(**data, owner_id=current_user.id)
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    logger.info("Campaign created: id=%d name=%r owner=%d", campaign.id, campaign.name, current_user.id)
    return campaign


@router.get("/{campaign_id}", response_model=CampaignRead)
def get_campaign(campaign_id: int, db: DbSession, current_user: CurrentUser):
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id, Campaign.owner_id == current_user.id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.patch("/{campaign_id}", response_model=CampaignRead)
def update_campaign(campaign_id: int, body: CampaignUpdate, db: DbSession, current_user: CurrentUser):
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id, Campaign.owner_id == current_user.id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    update_data = body.model_dump(exclude_unset=True)
    if "status" in update_data and update_data["status"] not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status. Must be one of: {VALID_STATUSES}")

    for field, value in update_data.items():
        setattr(campaign, field, value)

    db.commit()
    db.refresh(campaign)
    return campaign


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(campaign_id: int, db: DbSession, current_user: CurrentUser):
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id, Campaign.owner_id == current_user.id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    db.delete(campaign)
    db.commit()


@router.post("/{campaign_id}/start", response_model=CampaignRead)
def start_campaign(campaign_id: int, db: DbSession, current_user: CurrentUser):
    """Transition a draft/paused campaign to active."""
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id, Campaign.owner_id == current_user.id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status not in ("draft", "paused"):
        raise HTTPException(status_code=409, detail=f"Cannot start campaign in status '{campaign.status}'")

    campaign.status = "active"
    if campaign.started_at is None:
        from datetime import timezone
        campaign.started_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(campaign)
    logger.info("Campaign %d started by user %d", campaign_id, current_user.id)
    return campaign


@router.post("/{campaign_id}/pause", response_model=CampaignRead)
def pause_campaign(campaign_id: int, db: DbSession, current_user: CurrentUser):
    """Pause an active campaign."""
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id, Campaign.owner_id == current_user.id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status != "active":
        raise HTTPException(status_code=409, detail="Campaign is not active")

    campaign.status = "paused"
    db.commit()
    db.refresh(campaign)
    return campaign


@router.get("/{campaign_id}/events", response_model=list[CampaignEventRead])
def list_campaign_events(
    campaign_id: int,
    db: DbSession,
    current_user: CurrentUser,
    event_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List events for a campaign (filtered by event type)."""
    # Ownership check
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id, Campaign.owner_id == current_user.id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    query = db.query(CampaignEvent).filter(CampaignEvent.campaign_id == campaign_id)
    if event_type:
        query = query.filter(CampaignEvent.event_type == event_type)
    return query.order_by(CampaignEvent.occurred_at.desc()).offset(offset).limit(limit).all()


@router.post("/{campaign_id}/leads", response_model=dict)
def add_leads_to_campaign(
    campaign_id: int,
    body: AddLeadsToCampaign,
    db: DbSession,
    current_user: CurrentUser,
):
    """Enroll leads in a campaign (creates 'enrolled' events)."""
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id, Campaign.owner_id == current_user.id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    added = 0
    for lead_id in body.lead_ids:
        lead = db.query(Lead).filter(Lead.id == lead_id, Lead.owner_id == current_user.id).first()
        if not lead:
            continue
        # Skip already enrolled
        existing = db.query(CampaignEvent).filter(
            CampaignEvent.campaign_id == campaign_id,
            CampaignEvent.lead_id == lead_id,
            CampaignEvent.event_type == "enrolled",
        ).first()
        if existing:
            continue
        db.add(CampaignEvent(
            campaign_id=campaign_id,
            lead_id=lead_id,
            event_type="enrolled",
        ))
        added += 1

    campaign.total_leads += added
    db.commit()
    return {"added": added, "campaign_id": campaign_id}
