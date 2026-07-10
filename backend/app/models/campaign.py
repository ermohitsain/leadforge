from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Text, DateTime, ForeignKey, Integer, func, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Status: draft | active | paused | completed | archived
    status: Mapped[str] = mapped_column(String(50), default="draft", index=True, nullable=False)

    # Sending configuration
    from_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    from_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reply_to: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # AI & personalization settings (stored as JSON)
    ai_persona: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # e.g. {"tone": "professional", "goal": "book_demo", "company_context": "..."}

    # Sequence settings
    daily_send_limit: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    sequence_steps: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # e.g. [{"day": 0, "subject": "...", "body_template": "..."}, ...]

    # Temporal workflow ID (if a workflow is running)
    temporal_workflow_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Stats (denormalized for fast reads)
    total_leads: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    emails_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    emails_opened: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    emails_replied: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    emails_bounced: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    owner: Mapped["User"] = relationship("User", back_populates="campaigns")  # noqa: F821
    events: Mapped[list["CampaignEvent"]] = relationship(  # noqa: F821
        "CampaignEvent", back_populates="campaign", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Campaign id={self.id} name={self.name!r} status={self.status!r}>"
