from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, ForeignKey, func, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class EmailAccount(Base):
    """A sending email account connected to a user's LeadForge workspace."""

    __tablename__ = "email_accounts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    email_address: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Provider: smtp | google | microsoft
    provider: Mapped[str] = mapped_column(String(50), default="smtp", nullable=False)

    # SMTP settings (used when provider == "smtp")
    smtp_host: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    smtp_port: Mapped[int] = mapped_column(Integer, default=587, nullable=False)
    smtp_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    smtp_password_encrypted: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    smtp_use_tls: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # OAuth tokens (used when provider == "google" or "microsoft")
    oauth_access_token_encrypted: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    oauth_refresh_token_encrypted: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    oauth_token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Rate limits
    daily_send_limit: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    emails_sent_today: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    send_limit_reset_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    owner: Mapped["User"] = relationship("User", back_populates="email_accounts")  # noqa: F821

    def __repr__(self) -> str:
        return f"<EmailAccount id={self.id} email={self.email_address!r} provider={self.provider!r}>"
