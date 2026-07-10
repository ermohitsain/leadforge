"""ICP Template model - saved search profiles for lead sourcing."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from app.database import Base


class IcpTemplate(Base):
    __tablename__ = "icp_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    natural_language_query = Column(String(2000), nullable=False)
    structured_icp = Column(JSON, nullable=True, comment="Parsed ICP dict (industries, roles, geo, etc.)")
    apollo_params = Column(JSON, nullable=True, comment="Apollo API search parameters")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    user = relationship("User", back_populates="icp_templates")

    def __repr__(self):
        return f"<IcpTemplate id={self.id} name='{self.name}' user_id={self.user_id}>"
