from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, ForeignKey, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CampaignEvent(Base):
    """Records every touchpoint between a campaign and a lead."""

    __tablename__ = "campaign_events"

    __table_args__ = (
        Index("ix_campaign_events_campaign_lead", "campaign_id", "lead_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True, nullable=False
    )
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Event type: sent | opened | clicked | replied | bounced | unsubscribed | error
    event_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)

    # Sequence step index (0-based) for multi-step campaigns
    step_index: Mapped[int] = mapped_column(default=0, nullable=False)

    # Email-specific metadata
    subject: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    body_snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # SMTP Message-ID

    # Error info
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="events")  # noqa: F821
    lead: Mapped["Lead"] = relationship("Lead", back_populates="campaign_events")  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<CampaignEvent id={self.id} campaign_id={self.campaign_id} "
            f"lead_id={self.lead_id} event_type={self.event_type!r}>"
        )
