# LeadForge — Technical Implementation Plan

**Stack:** Python FastAPI + PostgreSQL (Supabase) + Temporal.io + OpenRouter (LLM)  
**Target:** One-person agency owners  
**Repository:** https://github.com/ermohitsain/leadforge

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                    FRONTEND (Next.js)                         │
│  Dashboard │ Campaign Builder │ Lead View │ Settings         │
└──────────────────────┬───────────────────────────────────────┘
                       │ REST API
┌──────────────────────▼───────────────────────────────────────┐
│                     FASTAPI BACKEND                           │
│                                                              │
│  Routers:              Services:           Models:           │
│  /api/leads            ApolloService       User              │
│  /api/campaigns        Scorer              Lead              │
│  /api/crm              Verifier            Campaign          │
│  /api/auth             DraftGenerator      CampaignEvent     │
│  /api/analytics        CrmSync             EmailAccount      │
│                        GmailSend           CRMConnection     │
│                        ReplyDetect                           │
│                        ProspectSearch                        │
└──────┬────────────────────────┬──────────────────────────────┘
       │                        │
┌──────▼──────┐       ┌─────────▼──────────────┐
│  PostgreSQL  │       │    TEMPORAL.IO          │
│  (Supabase)  │       │                         │
│  - Leads     │       │  Workflows:             │
│  - Campaigns │       │  - LeadIngestionWF      │
│  - Events    │       │  - CampaignExecutionWF  │
│  - Users     │       │  - LeadScoringWF        │
│  ─────────── │       │  - EmailVerificationWF  │
│  Temporal    │       │  - CrmSyncWF            │
│  Visibility  │       │  - AutoPilotWF          │
│  DB          │       │  - EmailWarmupWF        │
└──────────────┘       │                         │
                       │  Activities:             │
                       │  - ApolloSearch          │
                       │  - LlmScore              │
                       │  - ZeroBounceVerify      │
                       │  - GmailSend             │
                       │  - HubspotSync           │
                       │  - ReplyDetect           │
                       └─────────┬────────────────┘
                                 │
                 ┌───────────────┼───────────────┐
                 ▼               ▼               ▼
          Apollo.io         ZeroBounce       HubSpot/SFDC
          Gmail API         Hunter.io        Pipedrive/Zoho
```

### Why Temporal.io Over Celery/Redis

| Capability | Celery + Redis | Temporal.io |
|---|---|---|
| **Stateful workflows** | ❌ Stateless tasks only | ✅ Full workflow state machine |
| **Campaign sequences** | ❌ Must chain tasks manually | ✅ Native multi-step sequences with sleeps |
| **Human-in-loop** | ❌ No native support | ✅ Signal-based (wait for approval) |
| **Retry + backoff** | ✅ Basic | ✅ Exponential backoff + timeout policies |
| **Visibility** | ❌ Flower UI is basic | ✅ Web UI, stack traces, replay |
| **Cron scheduling** | ❌ Must manage externally | ✅ Native cron schedules |
| **Workflow versioning** | ❌ Breaking changes lose tasks | ✅ Patch/version workflows |
| **Async send throttling** | ❌ Hard to coordinate across tasks | ✅ Workflow-level rate limiting |
| **Testing** | ❌ Mocks needed | ✅ `ReplayWorkflow` + test env |

---

## 2. Temporal Workflow Architecture

```
                          ┌─────────────────────┐
                          │   AutoPilotWF        │
                          │   (Cron: Daily)      │
                          │                      │
                          │  Runs daily sourcing │
                          │  auto-score, auto-   │
                          │  add to campaigns    │
                          └─────────┬───────────┘
                                    │ spawns
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
          ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
          │ LeadIngestWF  │ │ CampaignExec │ │ CrmSyncWF    │
          │              │ │ WF           │ │             │
          │ 1. Apollo    │ │ 1. Wait D0   │ │ 1. Fetch     │
          │    search    │ │ 2. Score     │ │    changes   │
          │ 2. CSV parse │ │ 3. Personal  │ │ 2. Map       │
          │ 3. Dedup     │ │ 4. Send      │ │    fields    │
          │ 4. Store     │ │ 5. Wait D3   │ │ 3. Push      │
          │              │ │ 6. Follow-up │ │ 4. Log       │
          └──────────────┘ │ 7. Wait D7   │ └──────────────┘
                           │ 8. Follow-up │
                           │ 9. Wait D14  │
                           │10. Breakup   │
                           │              │
                           │ Signal:      │
                           │ "reply" →    │
                           │ pause seq    │
                           └──────────────┘
```

### Workflow Definitions

#### `LeadIngestionWorkflow`
```python
@workflow.defn
class LeadIngestionWorkflow:
    @workflow.run
    async def run(self, user_id: str, source: str, params: dict) -> str:
        # 1. Source leads
        if source == "apollo":
            leads = await workflow.execute_activity(
                ApolloSearchActivity, params,
                start_to_close_timeout=timedelta(seconds=30)
            )
        elif source == "csv":
            leads = await workflow.execute_activity(
                CsvParseActivity, params,
                start_to_close_timeout=timedelta(minutes=5)
            )
        
        # 2. Deduplicate
        deduped = await workflow.execute_activity(
            DedupActivity, {"leads": leads, "user_id": user_id},
            start_to_close_timeout=timedelta(seconds=30)
        )
        
        # 3. Store
        lead_ids = await workflow.execute_activity(
            StoreLeadsActivity, {"leads": deduped, "user_id": user_id},
            start_to_close_timeout=timedelta(seconds=10)
        )
        
        return lead_ids
```

#### `CampaignExecutionWorkflow`
```python
@workflow.defn
class CampaignExecutionWorkflow:
    @workflow.run
    async def run(self, campaign_id: str, lead_ids: list[str]):
        steps = await workflow.execute_activity(
            GetCampaignStepsActivity, campaign_id,
            start_to_close_timeout=timedelta(seconds=5)
        )
        
        for step in steps:
            # Wait for scheduled delay
            await asyncio.sleep(step.delay_seconds)
            
            # Check for reply signal
            reply = await workflow.wait_for_signal(
                "lead_replied", timeout=timedelta(seconds=0)
            )
            if reply:
                break  # Stop sequence if replied
            
            # Personalize and send
            email = await workflow.execute_activity(
                PersonalizeActivity, {
                    "lead_ids": lead_ids,
                    "step": step,
                    "tone": step.tone
                },
                start_to_close_timeout=timedelta(seconds=60)
            )
            
            await workflow.execute_activity(
                GmailSendActivity, email,
                start_to_close_timeout=timedelta(seconds=30)
            )
    
    @workflow.signal
    async def lead_replied(self, lead_id: str, reply_text: str):
        # Signal handler pauses sequence for this lead
        self.replied_leads.append(lead_id)
```

#### `EmailWarmupWorkflow`
```python
@workflow.defn
class EmailWarmupWorkflow:
    @workflow.run
    async def run(self, email_account_id: str):
        """Ramp sends from 5 to 50/day over 14 days."""
        for day in range(1, 15):
            target = min(5 * day, 50)  # Linear ramp
            await workflow.execute_activity(
                SendWarmupEmailsActivity, {
                    "account_id": email_account_id,
                    "count": target,
                    "day": day
                },
                start_to_close_timeout=timedelta(minutes=10)
            )
            # Check deliverability
            inbox_rate = await workflow.execute_activity(
                CheckDeliverabilityActivity, email_account_id,
                start_to_close_timeout=timedelta(seconds=30)
            )
            if inbox_rate < 0.7:
                # Pause warmup if deliverability drops
                await workflow.execute_activity(
                    AlertUserActivity, {
                        "type": "warmup_paused",
                        "account": email_account_id,
                        "reason": f"Inbox rate dropped to {inbox_rate}"
                    }
                )
                return {"status": "paused", "inbox_rate": inbox_rate}
            
            await asyncio.sleep(86400)  # Wait 1 day
        
        return {"status": "warm", "final_rate": 50}
```

#### `AutoPilotWorkflow` (Daily Cron)
```python
@workflow.defn
class AutoPilotWorkflow:
    @workflow.run
    async def run(self):
        """Daily: source new leads, score, verify, add to campaigns."""
        users = await workflow.execute_activity(
            GetActiveAutoPilotUsersActivity,
            start_to_close_timeout=timedelta(seconds=10)
        )
        
        for user in users:
            # Source new leads for each saved ICP
            icps = await workflow.execute_activity(
                GetUserICPsActivity, user["id"],
                start_to_close_timeout=timedelta(seconds=5)
            )
            
            for icp in icps:
                # Spawn child workflow for each ICP
                child_id = f"ingest-{user['id']}-{icp['id']}-{datetime.utcnow().date()}"
                await workflow.execute_child_workflow(
                    LeadIngestionWorkflow.run, user["id"], "apollo", icp["params"],
                    id=child_id
                )
```

---

## 3. Directory Structure

```
leadforge/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                   # FastAPI entry, middleware, CORS
│   │   ├── config.py                 # Settings from env vars
│   │   ├── database.py               # SQLAlchemy engine + session
│   │   ├── dependencies.py           # Dependency injection
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── user.py
│   │   │   ├── lead.py
│   │   │   ├── campaign.py
│   │   │   ├── campaign_event.py
│   │   │   ├── email_account.py
│   │   │   └── crm_connection.py
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── lead.py
│   │   │   ├── campaign.py
│   │   │   └── crm.py
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── leads.py
│   │   │   ├── campaigns.py
│   │   │   ├── prospects.py
│   │   │   ├── verification.py
│   │   │   ├── crm.py
│   │   │   └── analytics.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── apollo_service.py
│   │   │   ├── import_service.py
│   │   │   ├── scoring_service.py
│   │   │   ├── verification_service.py
│   │   │   ├── campaign_service.py
│   │   │   ├── personalization_service.py
│   │   │   ├── gmail_service.py
│   │   │   ├── crm_sync_service.py
│   │   │   ├── reply_detector.py
│   │   │   ├── prospect_service.py
│   │   │   └── analytics_service.py
│   │   └── temporal/
│   │       ├── __init__.py
│   │       ├── worker.py             # Temporal worker entry point
│   │       ├── client.py             # Temporal client wrapper
│   │       ├── workflows/
│   │       │   ├── __init__.py
│   │       │   ├── lead_ingestion.py
│   │       │   ├── campaign_execution.py
│   │       │   ├── lead_scoring.py
│   │       │   ├── email_verification.py
│   │       │   ├── email_warmup.py
│   │       │   ├── crm_sync.py
│   │       │   └── auto_pilot.py
│   │       └── activities/
│   │           ├── __init__.py
│   │           ├── apollo.py
│   │           ├── csv_parse.py
│   │           ├── scoring.py
│   │           ├── verification.py
│   │           ├── personalization.py
│   │           ├── gmail.py
│   │           ├── crm.py
│   │           ├── reply_detect.py
│   │           └── email_warmup.py
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── Dockerfile.temporal          # Temporal worker image
│   └── alembic.ini
├── temporal/
│   ├── docker-compose.yml            # Temporal server + admin UI
│   └── dynamicconfig/                # Temporal server config
├── frontend/                         # Next.js app (Phase 1+)
├── scripts/
│   ├── seed_demo.py
│   ├── migrate.sh
│   ├── start_temporal.sh
│   └── deploy.sh
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   └── feature_request.md
│   └── workflows/
│       ├── ci.yml
│       └── deploy.yml
├── docker-compose.yml                # App + DB + Temporal
├── README.md
├── PROJECT_PLAN.md
└── TECHNICAL_PLAN.md                 # This file
```

---

## 4. Phase-by-Phase Implementation

### Phase 0: MVP (Weeks 1-3)

**Week 1: Foundation + Data Models + Temporal Setup**
- Set up FastAPI project, Docker, DB connection
- Create all SQLAlchemy models + Alembic migrations
- Set up Temporal server (docker-compose), worker, client
- Create Temporal client wrapper in FastAPI
- Health endpoint, CORS, logging
- User auth (API key + JWT)

**Week 2: Lead Ingestion + Scoring (Temporal workflows)**
- `ApolloSearchActivity` + `LeadIngestionWorkflow`
- CSV upload with auto-column mapping (activity)
- ICP parser (LLM) → `LeadScoringWorkflow` (scores each lead in parallel)
- Prospect search via Apollo
- AI scoring engine (6 frameworks)
- `EmailVerificationWorkflow` (SMTP check → ZeroBounce fallback)

**Week 3: Campaigns + CRM (Temporal workflows)**
- `CampaignExecutionWorkflow` — state machine with signals for reply handling
- LLM personalization engine (4 depth levels) as activity
- `GmailSendActivity` with rate limiting
- `ReplyDetectActivity` + signal-based campaign pause
- `CrmSyncWorkflow` (HubSpot)
- `AutoPilotWorkflow` (cron: daily sourcing)
- Smart lead queue (Temporal visibility queries)
- Basic dashboard

### Phase 1: Core Release (Weeks 4-9)
- Add `LeadIngestionWorkflow` sources for Instantly.ai / Smartlead.ai
- Drag-and-drop sequence builder (writes Temporal workflow config)
- Enhanced reply classification + signal handler improvements
- `CrmSyncWorkflow` for Salesforce, Pipedrive, Zoho
- Multi-account `GmailSendActivity` with rotation
- Lead detail view with Temporal workflow event timeline

### Phase 2: Growth (Weeks 10-19)
- `ABTestWorkflow` — spawns parallel variants, auto-winner detection
- `AutoPilotWorkflow` enhancements (multiple ICPs, smart prioritization)
- White-label client dashboards
- `SmartRecommendWorkflow` — weekly analysis + advice
- `EmailWarmupWorkflow` — 14-day gradual ramp
- `BroadcastWorkflow` — one-to-many sends with throttling
- CSV export

### Phase 3: Scale (Month 4+)
- Public API + webhooks (trigger Temporal workflows from webhooks)
- Team features (multi-user with shared workflow visibility)
- `CloseCrmSyncWorkflow`
- Mobile app
- Custom webhook CRM builder
- Performance optimization
- Production Temporal cluster (Temporal Cloud)

---

## 5. Key Technical Decisions

| Decision | Choice | Rationale |
|---|---|---|
| **Backend** | Python FastAPI | Async, Pydantic validation, OpenAPI auto-docs |
| **Database** | PostgreSQL (Supabase) | JSONB for flexible schemas, hosted option |
| **Workflow Engine** | Temporal.io | Stateful multi-step campaigns, signals for reply handling, built-in cron, versioning |
| **LLM** | OpenRouter (Claude 4 / DeepSeek V4) | Already have keys |
| **Sending** | Gmail API (OAuth) | Most accessible for solo owners |
| **Auth** | JWT + API key | Simple, stateless |
| **Frontend** | Next.js + Tailwind | Responsive, fast iteration |
| **CRM Sync** | Temporal workflow per CRM | Reliable, retryable, auditable |
| **Deployment** | Docker + Railway/Fly.io | Simple, works with Temporal Cloud |

---

## 6. LLM Integration Points

| Service | LLM Use | Model | Cost/1K calls |
|---|---|---|---|
| **ICP Parser** | NL → structured search params | Claude 4 Haiku | ~$0.25 |
| **Lead Scorer** | Extract signals, score dimensions | Claude 4 Sonnet | ~$1.00 |
| **Personalization** | Research + write unique emails | Claude 4 Sonnet | ~$2.00 |
| **Reply Classifier** | Classify inbound replies | Claude 4 Haiku | ~$0.25 |
| **Recommendations** | Analyze metrics, generate advice | Claude 4 Haiku | ~$0.50 |

**Estimated LLM cost per batch of 50 leads:**  
- Scoring: $1.00  
- Verification: $0.20 (ZeroBounce)  
- Personalization (deep): $2.00  
- **Total: ~$3.20 per 50 lead campaign**

---

## 7. API Endpoints (Core)

| Endpoint | Method | Description | Phase | Workflow Triggered |
|---|---|---|---|---|
| `/api/leads/import/apollo` | POST | Import from Apollo | 0 | `LeadIngestionWorkflow` |
| `/api/leads/import/csv` | POST | Import from CSV | 0 | `LeadIngestionWorkflow` |
| `/api/leads/import/instantly` | POST | Import from Instantly | 1 | `LeadIngestionWorkflow` |
| `/api/leads/import/smartlead` | POST | Import from Smartlead | 1 | `LeadIngestionWorkflow` |
| `/api/leads/import/prospect` | POST | Prospect via ICP | 0 | `LeadIngestionWorkflow` |
| `/api/leads/{id}` | GET | Get lead detail | 0 | — |
| `/api/leads/{id}/score` | POST | Score single lead | 0 | `LeadScoringWorkflow` |
| `/api/leads/batch/score` | POST | Score batch of leads | 0 | `LeadScoringWorkflow` (parallel) |
| `/api/leads/{id}/verify` | POST | Verify single email | 0 | `EmailVerificationWorkflow` |
| `/api/leads/batch/verify` | POST | Verify batch emails | 0 | `EmailVerificationWorkflow` |
| `/api/leads/{id}/status` | PATCH | Update lead status | 0 | — |
| `/api/campaigns` | CRUD | Campaign management | 0 | — |
| `/api/campaigns/{id}/launch` | POST | Launch campaign | 0 | `CampaignExecutionWorkflow` |
| `/api/campaigns/{id}/analytics` | GET | Campaign analytics | 0 | — |
| `/api/campaigns/{id}/pause` | POST | Pause campaign | 0 | Signal: `campaign_pause` |
| `/api/campaigns/templates` | CRUD | Sequence templates | 1 | — |
| `/api/crm/{provider}/sync` | POST | Sync to CRM | 0 | `CrmSyncWorkflow` |
| `/api/crm/{provider}/test` | POST | Test CRM connection | 0 | — |
| `/api/analytics/dashboard` | GET | Dashboard KPIs | 0 | — |
| `/api/analytics/workflows` | GET | Temporal workflow status | 0 | — |
| `/api/analytics/recommendations` | GET | Smart recommendations | 2 | `SmartRecommendWorkflow` |

---

## 8. Temporal Signal-Based Human-in-Loop

```
CampaignExecutionWorkflow running
           │
           │  Step 1: Send initial email
           │  Step 2: Wait D3
           │
           ├── Signal: lead_replied(lead_id="abc", text="Sounds good!")
           │   → Workflow marks "abc" as replied
           │   → Skips remaining steps for "abc"
           │   → Fires "meeting_requested" notification
           │
           ├── Signal: lead_bounced(lead_id="xyz")
           │   → Removes "xyz" from campaign
           │   → Triggers EmailVerificationWorkflow to re-check
           │
           ├── Signal: campaign_pause(user_id="u1")
           │   → Pauses ALL steps for this campaign
           │   → Resumes on campaign_resume signal
           │
           └── Step 3: Send follow-up (for non-replied leads only)
               Step 4: Wait D7
               ...
```

### Signal Handlers

```python
@workflow.signal
async def lead_replied(self, lead_id: str, reply_text: str, classification: str):
    self.replied_leads[lead_id] = {
        "text": reply_text,
        "classification": classification,  # interested/OOO/bounce/unsubscribe
        "timestamp": datetime.utcnow().isoformat()
    }
    
    if classification == "bounce":
        self.bounced_leads.append(lead_id)
    elif classification == "unsubscribe":
        self.unsubscribed_leads.append(lead_id)
    elif classification == "OOO":
        self.ooo_leads[lead_id] = {"until": extract_ooo_date(reply_text)}

@workflow.signal
async def campaign_pause(self):
    self.paused = True
    # Wait until resume signal
    await workflow.wait_for_signal("campaign_resume")
    self.paused = False
```

---

## 9. Data Flow: End-to-End Campaign with Temporal

```
User clicks "Launch Campaign"
           │
           ▼
FastAPI: POST /api/campaigns/{id}/launch
           │
           ▼
Temporal Client: start_workflow("CampaignExecutionWorkflow", campaign_id, lead_ids)
           │
           ▼
Temporal Server: Creates workflow execution
  ├─ Workflow ID: "campaign-{campaign_id}"
  ├─ Task Queue: "leadforge-campaigns"
  └─ Run ID: UUID
           │
           ▼
Temporal Worker picks up the task
  ├─ Step 1: PersonalizeActivity (LLM writes 20 unique emails)
  │           │
  │           ▼
  ├─ Step 1b: GmailSendActivity (sends 20 emails, respects daily limits)
  │           │
  │           ▼
  ├─ Wait 3 days (workflow.sleep)
  │           │
  │           ├── Signal: lead_replied("abc", "Interested", "interested")
  │           │     → Removes "abc" from sequence, notifies user
  │           │
  │           ▼
  ├─ Step 2: PersonalizeActivity (follow-ups for remaining 19)
  │           │
  │           ▼
  ├─ Step 2b: GmailSendActivity
  │           │
  │           ▼
  ├─ Wait 4 days
  │           │
  │           ├── Signal: lead_replied("def", "Not now", "not_interested")
  │           │     → Removes "def", auto-unsubscribes
  │           │
  │           ▼
  ├─ Step 3-5 continues...
  │
  └─ Workflow completes after Day 21
```

---

## 10. Temporal Server Setup

### Local Development
```yaml
# docker-compose.yml (Temporal services)
services:
  temporal:
    image: temporalio/auto-setup:latest
    ports:
      - "7233:7233"  # Temporal gRPC
    environment:
      - DB=postgresql
      - POSTGRES_USER=temporal
      - POSTGRES_PWD=temporal
      - POSTGRES_SEEDS=postgres
    depends_on:
      - postgres

  temporal-admin-tools:
    image: temporalio/admin-tools:latest
    depends_on: [temporal]
    stdin_open: true

  temporal-web:
    image: temporalio/web:latest
    ports:
      - "8088:8088"
    environment:
      - TEMPORAL_GRPC_ENDPOINT=temporal:7233
    depends_on: [temporal]
```

### Temporal Cloud (Production)
```
TEMPORAL_CLOUD_URL=your-namespace.tmprl.cloud:7233
TEMPORAL_CLOUD_API_KEY=your-api-key
TEMPORAL_NAMESPACE=leadforge-prod
TEMPORAL_TASK_QUEUE=leadforge-campaigns
```

### Worker Startup
```python
# temporal/worker.py
import asyncio
from temporalio.client import Client
from temporalio.worker import Worker

async def main():
    client = await Client.connect(
        "localhost:7233",  # or Temporal Cloud URL
        namespace="leadforge"
    )
    
    worker = Worker(
        client,
        task_queue="leadforge-campaigns",
        workflows=[
            LeadIngestionWorkflow,
            CampaignExecutionWorkflow,
            LeadScoringWorkflow,
            EmailVerificationWorkflow,
            EmailWarmupWorkflow,
            CrmSyncWorkflow,
            AutoPilotWorkflow,
        ],
        activities=[
            apollo_search,
            csv_parse,
            score_leads,
            zero_bounce_verify,
            personalize_email,
            gmail_send,
            hubspot_sync,
            reply_detect,
            send_warmup_emails,
        ],
    )
    
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 11. Authentication Flow

```
User Signup
    │
    ▼
┌──────────────────────────────────────────────────┐
│  Email + Password (Supabase Auth) or Google OAuth │
│  → JWT access token (15 min) + refresh token      │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│  API Key Generation (for programmatic access)     │
│  User → Settings → Generate API Key              │
│  Stored as bcrypt hash, never plaintext           │
└──────────────────────────────────────────────────┘
```

---

## 12. Security Considerations

| Concern | Mitigation |
|---|---|
| **Email credentials** | OAuth only (no password storage). SMTP creds encrypted at rest (AES-256). |
| **API keys** | Stored as bcrypt hash. One-way only. |
| **Lead data** | Encrypted at rest (AES-256). TLS 1.3 in transit. |
| **LLM data** | No training on user data via OpenRouter. User must consent to lead data in prompts. |
| **Rate limits** | Per-user API rate limiting. Daily send limits enforced server-side. |
| **CAN-SPAM** | Unsubscribe link on every email. Physical address in footer. Opt-out handling. |
| **GDPR** | Right to deletion. Data export. Consent logging for EU contacts. |
| **CRM tokens** | Stored encrypted. Only decrypted at sync time. |
| **Temporal secrets** | Temporal Cloud uses mTLS. Self-hosted uses JWT. |

---

## 13. Deployment

### Local Development
```bash
# Prerequisites: Python 3.11+, PostgreSQL, Docker
git clone https://github.com/ermohitsain/leadforge
cd leadforge

# Start Temporal server + DB
docker compose up -d temporal postgres

# Start backend
cd backend
cp .env.example .env  # Edit with your keys
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head

# Start Temporal worker (separate terminal)
python -m app.temporal.worker

# Start FastAPI
uvicorn app.main:app --reload
```

### Docker (All Services)
```bash
docker compose -f docker-compose.yml -f temporal/docker-compose.yml up -d
```

### Production
- **Database:** Supabase PostgreSQL
- **Backend:** Railway or Fly.io (auto-deploy from GitHub)
- **Workflow Engine:** Temporal Cloud ($0-50/mo starter tier)
- **LLM:** OpenRouter API
- **Emailing:** Gmail API (user's own accounts)
- **File storage:** S3 (Backblaze B2)
