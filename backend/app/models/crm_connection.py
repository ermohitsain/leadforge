from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, ForeignKey, func, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CRMConnection(Base):
    """A connected CRM integration (HubSpot, Salesforce, Pipedrive, etc.)."""

    __tablename__ = "crm_connections"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # CRM type: hubspot | salesforce | pipedrive | zoho | custom
    crm_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # user-friendly name

    # Authentication
    api_key_encrypted: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    oauth_access_token_encrypted: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    oauth_refresh_token_encrypted: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    oauth_token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Instance/portal identifiers
    instance_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # Salesforce instance URL
    portal_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # HubSpot portal ID

    # Sync configuration (stored as JSON for flexibility)
    sync_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # e.g. {"sync_leads": true, "sync_deals": false, "field_mapping": {...}}

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_error: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    owner: Mapped["User"] = relationship("User", back_populates="crm_connections")  # noqa: F821

    def __repr__(self) -> str:
        return f"<CRMConnection id={self.id} crm_type={self.crm_type!r} owner_id={self.owner_id}>"
