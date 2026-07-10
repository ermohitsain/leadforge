#!/usr/bin/env python
"""
seed_demo.py – Populate the LeadForge database with realistic demo data.

Usage:
    cd backend
    DATABASE_URL=postgresql://leadforge:leadforge_dev_password@localhost:5432/leadforge \
        python ../scripts/seed_demo.py

The script is idempotent: running it multiple times will not duplicate data
(it checks for existing rows by email / name before inserting).
"""

import os
import sys
import logging
from datetime import datetime, timezone, timedelta
import random

# Make sure the backend app is importable
BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, BACKEND_DIR)

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BACKEND_DIR, "..", ".env"))
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("seed_demo")

# ─── Bootstrap ───────────────────────────────────────────────────────────────

from app.database import SessionLocal, create_all_tables, engine  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.lead import Lead  # noqa: E402
from app.models.campaign import Campaign  # noqa: E402
from app.models.campaign_event import CampaignEvent  # noqa: E402
from app.models.email_account import EmailAccount  # noqa: E402
from app.models.crm_connection import CRMConnection  # noqa: E402
from passlib.context import CryptContext  # noqa: E402

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ─── Demo data definitions ────────────────────────────────────────────────────

DEMO_USERS = [
    {
        "email": "alice@leadforge.dev",
        "password": "demopassword123",
        "full_name": "Alice Nguyen",
        "is_superuser": True,
    },
    {
        "email": "bob@leadforge.dev",
        "password": "demopassword123",
        "full_name": "Bob Martinez",
    },
]

DEMO_LEADS = [
    {"email": "john.smith@acmecorp.com", "first_name": "John", "last_name": "Smith",
     "company": "Acme Corp", "job_title": "VP of Engineering", "industry": "SaaS",
     "company_size": "51-200", "country": "US"},
    {"email": "sarah.jones@globaltech.io", "first_name": "Sarah", "last_name": "Jones",
     "company": "GlobalTech", "job_title": "Head of Sales", "industry": "Technology",
     "company_size": "201-1000", "country": "US"},
    {"email": "mike.chen@startupx.co", "first_name": "Mike", "last_name": "Chen",
     "company": "StartupX", "job_title": "CEO", "industry": "Fintech",
     "company_size": "1-10", "country": "US"},
    {"email": "emma.wilson@enterprise.com", "first_name": "Emma", "last_name": "Wilson",
     "company": "Enterprise Inc", "job_title": "CTO", "industry": "Healthcare",
     "company_size": "1001-5000", "country": "US"},
    {"email": "david.taylor@mediahouse.net", "first_name": "David", "last_name": "Taylor",
     "company": "MediaHouse", "job_title": "Director of Marketing", "industry": "Media",
     "company_size": "11-50", "country": "US"},
    {"email": "lisa.park@devtools.sh", "first_name": "Lisa", "last_name": "Park",
     "company": "DevTools", "job_title": "Product Manager", "industry": "Developer Tools",
     "company_size": "51-200", "country": "US"},
    {"email": "carlos.reyes@logistics.mx", "first_name": "Carlos", "last_name": "Reyes",
     "company": "Logistics MX", "job_title": "COO", "industry": "Logistics",
     "company_size": "201-1000", "country": "MX"},
    {"email": "anna.petrov@cloudbase.eu", "first_name": "Anna", "last_name": "Petrov",
     "company": "CloudBase EU", "job_title": "Engineering Manager", "industry": "Cloud",
     "company_size": "51-200", "country": "DE"},
    {"email": "james.brown@retailpro.com", "first_name": "James", "last_name": "Brown",
     "company": "RetailPro", "job_title": "IT Director", "industry": "Retail",
     "company_size": "1001-5000", "country": "US"},
    {"email": "nina.kowalski@edutech.pl", "first_name": "Nina", "last_name": "Kowalski",
     "company": "EduTech PL", "job_title": "Co-Founder", "industry": "EdTech",
     "company_size": "1-10", "country": "PL"},
]

DEMO_CAMPAIGN = {
    "name": "Q1 SaaS Demo Outreach",
    "description": "Cold outreach to VP/C-level SaaS prospects for a product demo.",
    "from_name": "Alice Nguyen",
    "from_email": "alice@leadforge.dev",
    "daily_send_limit": 50,
    "status": "active",
    "ai_persona": {
        "tone": "professional",
        "goal": "book_demo",
        "company_context": "LeadForge is an AI-powered outbound sales automation platform.",
        "value_prop": "Save 10+ hours/week on prospecting and personalised outreach.",
    },
    "sequence_steps": [
        {
            "day": 0,
            "subject": "Quick question about {{company}}",
            "body_template": (
                "<p>Hi {{first_name}},</p>"
                "<p>I noticed {{company}} is growing fast in the {{industry}} space. "
                "I wanted to reach out because LeadForge helps sales teams like yours "
                "automate personalised outreach at scale.</p>"
                "<p>Would you be open to a 20-min call this week?</p>"
                "<p>Best,<br>Alice</p>"
            ),
        },
        {
            "day": 3,
            "subject": "Re: Quick question about {{company}}",
            "body_template": (
                "<p>Hi {{first_name}}, just wanted to bump this up in case it got buried.</p>"
                "<p>Happy to share a quick 2-min demo video if a call isn't convenient.</p>"
                "<p>Best,<br>Alice</p>"
            ),
        },
        {
            "day": 7,
            "subject": "Last follow-up – {{company}}",
            "body_template": (
                "<p>Hi {{first_name}}, I'll keep this brief – last follow-up, I promise.</p>"
                "<p>If outbound automation isn't a priority right now, no worries at all. "
                "Feel free to reach out whenever the timing is right.</p>"
                "<p>Best,<br>Alice</p>"
            ),
        },
    ],
}


# ─── Seeding logic ────────────────────────────────────────────────────────────

def seed():
    logger.info("Creating tables if they don't exist …")
    create_all_tables()

    with SessionLocal() as db:
        # --- Users ---
        seeded_users = {}
        for u in DEMO_USERS:
            existing = db.query(User).filter(User.email == u["email"]).first()
            if existing:
                logger.info("User already exists: %s", u["email"])
                seeded_users[u["email"]] = existing
                continue
            user = User(
                email=u["email"],
                hashed_password=pwd_context.hash(u["password"]),
                full_name=u.get("full_name"),
                is_superuser=u.get("is_superuser", False),
            )
            db.add(user)
            db.flush()
            seeded_users[u["email"]] = user
            logger.info("Created user: %s (id=%d)", user.email, user.id)

        db.commit()

        alice = seeded_users["alice@leadforge.dev"]

        # --- Email Account ---
        existing_ea = db.query(EmailAccount).filter(
            EmailAccount.owner_id == alice.id,
            EmailAccount.email_address == "alice@leadforge.dev",
        ).first()
        if not existing_ea:
            db.add(EmailAccount(
                owner_id=alice.id,
                email_address="alice@leadforge.dev",
                display_name="Alice Nguyen",
                provider="smtp",
                smtp_host="smtp.example.com",
                smtp_port=587,
                smtp_username="alice@leadforge.dev",
                smtp_use_tls=True,
                is_active=True,
                is_verified=True,
                daily_send_limit=200,
            ))
            logger.info("Created email account for alice")

        # --- CRM Connection ---
        existing_crm = db.query(CRMConnection).filter(
            CRMConnection.owner_id == alice.id,
            CRMConnection.crm_type == "hubspot",
        ).first()
        if not existing_crm:
            db.add(CRMConnection(
                owner_id=alice.id,
                crm_type="hubspot",
                label="LeadForge HubSpot",
                portal_id="12345678",
                is_active=True,
                sync_config={"sync_leads": True, "sync_deals": False},
            ))
            logger.info("Created HubSpot CRM connection for alice")

        db.commit()

        # --- Leads (owned by Alice) ---
        lead_ids = []
        for l in DEMO_LEADS:
            existing_lead = db.query(Lead).filter(
                Lead.owner_id == alice.id, Lead.email == l["email"]
            ).first()
            if existing_lead:
                logger.info("Lead already exists: %s", l["email"])
                lead_ids.append(existing_lead.id)
                continue
            lead = Lead(**l, owner_id=alice.id, status="new")
            db.add(lead)
            db.flush()
            lead_ids.append(lead.id)
            logger.info("Created lead: %s", lead.email)

        db.commit()

        # --- Campaign ---
        existing_campaign = db.query(Campaign).filter(
            Campaign.owner_id == alice.id,
            Campaign.name == DEMO_CAMPAIGN["name"],
        ).first()
        if existing_campaign:
            logger.info("Campaign already exists: %s", DEMO_CAMPAIGN["name"])
            campaign = existing_campaign
        else:
            campaign = Campaign(**DEMO_CAMPAIGN, owner_id=alice.id)
            campaign.total_leads = len(lead_ids)
            db.add(campaign)
            db.flush()
            logger.info("Created campaign: %s (id=%d)", campaign.name, campaign.id)

        db.commit()

        # --- Campaign Events (mock some activity) ---
        now = datetime.now(timezone.utc)
        event_types = ["enrolled", "sent", "opened", "replied"]
        event_count = 0
        for i, lead_id in enumerate(lead_ids):
            for step_idx, evt in enumerate(event_types[: random.randint(1, len(event_types))]):
                existing_evt = db.query(CampaignEvent).filter(
                    CampaignEvent.campaign_id == campaign.id,
                    CampaignEvent.lead_id == lead_id,
                    CampaignEvent.event_type == evt,
                ).first()
                if existing_evt:
                    continue
                db.add(CampaignEvent(
                    campaign_id=campaign.id,
                    lead_id=lead_id,
                    event_type=evt,
                    step_index=step_idx,
                    subject=DEMO_CAMPAIGN["sequence_steps"][0]["subject"] if evt != "enrolled" else None,
                    occurred_at=now - timedelta(hours=random.randint(1, 72)),
                ))
                event_count += 1

        # Update campaign aggregate counters
        campaign.emails_sent = db.query(CampaignEvent).filter(
            CampaignEvent.campaign_id == campaign.id,
            CampaignEvent.event_type == "sent",
        ).count()
        campaign.emails_opened = db.query(CampaignEvent).filter(
            CampaignEvent.campaign_id == campaign.id,
            CampaignEvent.event_type == "opened",
        ).count()
        campaign.emails_replied = db.query(CampaignEvent).filter(
            CampaignEvent.campaign_id == campaign.id,
            CampaignEvent.event_type == "replied",
        ).count()

        db.commit()
        logger.info("Created %d campaign events", event_count)

    logger.info("✅  Demo seed complete.")


if __name__ == "__main__":
    seed()
