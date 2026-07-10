# Models package – import all models here so Alembic autogenerate can detect them.
from app.models.user import User  # noqa: F401
from app.models.lead import Lead  # noqa: F401
from app.models.campaign import Campaign  # noqa: F401
from app.models.campaign_event import CampaignEvent  # noqa: F401
from app.models.email_account import EmailAccount  # noqa: F401
from app.models.crm_connection import CRMConnection  # noqa: F401

__all__ = [
    "User",
    "Lead",
    "Campaign",
    "CampaignEvent",
    "EmailAccount",
    "CRMConnection",
]
