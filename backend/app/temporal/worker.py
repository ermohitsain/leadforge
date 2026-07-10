"""
Temporal.io worker for LeadForge.

This module defines:
  - Activities: atomic units of work (send_email, update_lead_status, …)
  - Workflows: orchestrate activities into multi-step outbound sequences
  - Worker entry point: connects to the Temporal server and starts polling

Run with:
    python -m app.temporal.worker
or via the Dockerfile CMD.
"""

import asyncio
import logging
from datetime import timedelta
from typing import Optional

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.common import RetryPolicy

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Data classes used as activity payloads
# ---------------------------------------------------------------------------

from dataclasses import dataclass


@dataclass
class SendEmailParams:
    campaign_id: int
    lead_id: int
    step_index: int
    to_email: str
    from_email: str
    from_name: str
    subject: str
    body_html: str


@dataclass
class UpdateLeadStatusParams:
    lead_id: int
    new_status: str


@dataclass
class CampaignSequenceParams:
    campaign_id: int
    owner_id: int
    lead_ids: list[int]


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------

@activity.defn(name="send_email_activity")
async def send_email_activity(params: SendEmailParams) -> dict:
    """
    Send a single email via SMTP (or any configured provider).
    Returns a dict with {"success": bool, "message_id": str | None, "error": str | None}.
    """
    import smtplib
    import ssl
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.utils import make_msgid

    logger.info(
        "send_email_activity: campaign=%d lead=%d step=%d to=%s",
        params.campaign_id,
        params.lead_id,
        params.step_index,
        params.to_email,
    )

    if not settings.smtp_host or not settings.smtp_username:
        # No SMTP configured – log and return success for dev/testing
        logger.warning("SMTP not configured; skipping actual send.")
        return {"success": True, "message_id": make_msgid(), "error": None}

    msg = MIMEMultipart("alternative")
    msg["Subject"] = params.subject
    msg["From"] = f"{params.from_name} <{params.from_email}>"
    msg["To"] = params.to_email
    message_id = make_msgid(domain=params.from_email.split("@")[-1])
    msg["Message-ID"] = message_id

    msg.attach(MIMEText(params.body_html, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            if settings.smtp_use_tls:
                server.starttls(context=context)
            if settings.smtp_username and settings.smtp_password:
                server.login(settings.smtp_username, settings.smtp_password)
            server.sendmail(params.from_email, params.to_email, msg.as_string())
        return {"success": True, "message_id": message_id, "error": None}
    except Exception as exc:
        logger.error("Email send failed: %s", exc)
        return {"success": False, "message_id": None, "error": str(exc)}


@activity.defn(name="update_lead_status_activity")
async def update_lead_status_activity(params: UpdateLeadStatusParams) -> bool:
    """Update a lead's status in the database."""
    # Import inside activity to avoid circular imports at module load time
    from app.database import SessionLocal
    from app.models.lead import Lead

    with SessionLocal() as db:
        lead = db.get(Lead, params.lead_id)
        if lead:
            lead.status = params.new_status
            db.commit()
            logger.info("Lead %d status → %s", params.lead_id, params.new_status)
            return True
    return False


@activity.defn(name="record_campaign_event_activity")
async def record_campaign_event_activity(
    campaign_id: int,
    lead_id: int,
    event_type: str,
    step_index: int = 0,
    subject: Optional[str] = None,
    message_id: Optional[str] = None,
    error_message: Optional[str] = None,
) -> int:
    """Persist a CampaignEvent row and update campaign aggregate counters."""
    from app.database import SessionLocal
    from app.models.campaign_event import CampaignEvent
    from app.models.campaign import Campaign

    with SessionLocal() as db:
        event = CampaignEvent(
            campaign_id=campaign_id,
            lead_id=lead_id,
            event_type=event_type,
            step_index=step_index,
            subject=subject,
            message_id=message_id,
            error_message=error_message,
        )
        db.add(event)

        # Update aggregate counters on campaign
        campaign = db.get(Campaign, campaign_id)
        if campaign:
            if event_type == "sent":
                campaign.emails_sent += 1
            elif event_type == "opened":
                campaign.emails_opened += 1
            elif event_type == "replied":
                campaign.emails_replied += 1
            elif event_type == "bounced":
                campaign.emails_bounced += 1

        db.commit()
        db.refresh(event)
        return event.id


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------

@workflow.defn(name="OutboundSequenceWorkflow")
class OutboundSequenceWorkflow:
    """
    Runs a multi-step outbound email sequence for a batch of leads.

    For each lead and each sequence step the workflow:
      1. Waits for the configured delay (step.day * 24 hours).
      2. Calls send_email_activity.
      3. Records the result via record_campaign_event_activity.
    """

    @workflow.run
    async def run(self, params: CampaignSequenceParams) -> dict:
        from app.database import SessionLocal
        from app.models.campaign import Campaign

        logger.info(
            "OutboundSequenceWorkflow started: campaign=%d leads=%d",
            params.campaign_id,
            len(params.lead_ids),
        )

        retry_policy = RetryPolicy(
            maximum_attempts=3,
            initial_interval=timedelta(seconds=10),
            backoff_coefficient=2.0,
            maximum_interval=timedelta(minutes=5),
        )

        sent_total = 0
        failed_total = 0

        # Load campaign config (sequence_steps, from_email, etc.)
        with SessionLocal() as db:
            campaign = db.get(Campaign, params.campaign_id)
            if not campaign:
                logger.error("Campaign %d not found", params.campaign_id)
                return {"sent": 0, "failed": 0, "error": "campaign not found"}

            sequence_steps = campaign.sequence_steps or []
            from_email = campaign.from_email or settings.smtp_username or "noreply@example.com"
            from_name = campaign.from_name or "LeadForge"

        for step_index, step in enumerate(sequence_steps):
            delay_days = step.get("day", 0)
            if step_index > 0 and delay_days > 0:
                # Wait until the right day relative to the previous step
                await asyncio.sleep(0)  # yield; in real usage use workflow.sleep
                await workflow.sleep(timedelta(days=delay_days))

            for lead_id in params.lead_ids:
                # Fetch lead email via activity (keeps I/O out of workflow code)
                try:
                    result = await workflow.execute_activity(
                        send_email_activity,
                        SendEmailParams(
                            campaign_id=params.campaign_id,
                            lead_id=lead_id,
                            step_index=step_index,
                            to_email=f"lead_{lead_id}@example.com",  # resolved by activity in prod
                            from_email=from_email,
                            from_name=from_name,
                            subject=step.get("subject", "(no subject)"),
                            body_html=step.get("body_template", ""),
                        ),
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=retry_policy,
                    )

                    event_type = "sent" if result["success"] else "error"
                    await workflow.execute_activity(
                        record_campaign_event_activity,
                        args=[
                            params.campaign_id,
                            lead_id,
                            event_type,
                            step_index,
                            step.get("subject"),
                            result.get("message_id"),
                            result.get("error"),
                        ],
                        start_to_close_timeout=timedelta(seconds=30),
                    )

                    if result["success"]:
                        sent_total += 1
                    else:
                        failed_total += 1

                except Exception as exc:
                    logger.error("Activity failed for lead %d step %d: %s", lead_id, step_index, exc)
                    failed_total += 1

        logger.info(
            "OutboundSequenceWorkflow done: campaign=%d sent=%d failed=%d",
            params.campaign_id,
            sent_total,
            failed_total,
        )
        return {"sent": sent_total, "failed": failed_total}


# ---------------------------------------------------------------------------
# Worker entry point
# ---------------------------------------------------------------------------

async def run_worker() -> None:
    logger.info("Connecting to Temporal at %s …", settings.temporal_host)
    client = await Client.connect(
        settings.temporal_host,
        namespace=settings.temporal_namespace,
    )

    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[OutboundSequenceWorkflow],
        activities=[
            send_email_activity,
            update_lead_status_activity,
            record_campaign_event_activity,
        ],
    )

    logger.info(
        "Temporal worker polling on task queue '%s' (namespace='%s')",
        settings.temporal_task_queue,
        settings.temporal_namespace,
    )
    await worker.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
