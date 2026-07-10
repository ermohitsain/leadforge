# LeadForge — Technical Implementation Plan

**Stack:** Python FastAPI + PostgreSQL (Supabase) + Celery/Redis + OpenRouter (LLM) + n8n  
**Target:** One-person agency owners  
**Repository:** https://github.com/ermohitsain/leadforge

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                     FRONTEND (Next.js)                    │
│  Dashboard │ Campaign Builder │ Lead View │ Settings     │
└──────────────────────┬───────────────────────────────────┘
                       │ REST API
┌──────────────────────▼───────────────────────────────────┐
│                  FASTAPI BACKEND                          │
│                                                          │
│  Routers:         Services:         Models:              │
│  /api/leads       ApolloService     User                 │
│  /api/campaigns   Scorer            Lead                 │
│  /api/crm         Verifier          Campaign             │
│  /api/auth        DraftGenerator    CampaignEvent        │
│  /api/analytics   CrmSync          EmailAccount          │
│                   GmailSend        CRMConnection         │
│                   ReplyDetect                            │
│                   ProspectSearch                         │
└──────┬────────────────────┬──────────────────────────────┘
       │                    │
┌──────▼──────┐    ┌───────▼──────────┐
│  PostgreSQL  │    │  Redis / Celery  │
│  (Supabase)  │    │  Async tasks:    │
│  - Leads     │    │  - Bulk import   │
│  - Campaigns │    │  - Email verify  │
│  - Events    │    │  - Campaign send │
│  - Users     │    │  - CRM sync      │
└─────────────┘    └──────────────────┘
       │                    │
       │           ┌────────▼──────────┐
       │           │  n8n (optional)    │
       │           │  - Cron triggers  │
       │           │  - Complex flows  │
       │           │  - Slack hooks    │
       │           └───────────────────┘
```

## 2. Directory Structure

```
leadforge/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI entry, middleware, CORS
│   │   ├── config.py               # Settings from env vars
│   │   ├── database.py             # SQLAlchemy engine + session
│   │   ├── dependencies.py         # Dependency injection
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
│   │   └── tasks/
│   │       ├── __init__.py
│   │       ├── celery_app.py
│   │       ├── import_tasks.py
│   │       ├── verification_tasks.py
│   │       ├── campaign_tasks.py
│   │       └── crm_tasks.py
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   ├── requirements.txt
│   ├── Dockerfile
│   └── alembic.ini
├── frontend/                       # Next.js app (Phase 1+)
├── scripts/
│   ├── seed_demo.py
│   ├── migrate.sh
│   └── deploy.sh
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   └── feature_request.md
│   └── workflows/
│       ├── ci.yml
│       └── deploy.yml
├── docker-compose.yml
├── README.md
├── PROJECT_PLAN.md
└── TECHNICAL_PLAN.md               # This file
```

## 3. Phase-by-Phase Implementation

### Phase 0: MVP (Weeks 1-3)

**Week 1: Foundation + Data Models**
- Set up FastAPI project, Docker, DB connection
- Create all SQLAlchemy models + Alembic migrations
- Health endpoint, CORS, logging
- User auth (API key + JWT)

**Week 2: Lead Ingestion + Scoring**
- Apollo.io API integration service
- CSV upload with auto-column mapping
- ICP parser (LLM converts NL → structured params)
- Prospect search via Apollo
- AI scoring engine (6 frameworks)
- Lead verification pipeline (SMTP + ZeroBounce)

**Week 3: Campaigns + Send + CRM**
- Campaign model + sequence builder
- LLM personalization engine (4 depth levels)
- Multi-step sequence execution
- Gmail API send integration
- Reply detection + LLM classification
- HubSpot CRM sync
- Solo agency features (auto-pilot, smart queue, OOO)
- Basic dashboard

### Phase 1: Core Release (Weeks 4-9)

- Instantly.ai import
- Smartlead.ai import
- Multi-step sequence builder UI (drag-and-drop)
- Enhanced reply classification + auto-actions
- Salesforce CRM sync
- Pipedrive CRM sync
- Zoho CRM sync
- Multi-account sending rotation
- Lead detail view with timeline
- Sequence template library

### Phase 2: Growth (Weeks 10-19)

- A/B testing engine
- Auto-pilot mode
- Client white-label dashboards
- Smart recommendations engine
- Built-in email warmup
- Broadcast mode
- CSV/Excel export

### Phase 3: Scale (Month 4+)

- Public API + webhooks
- Team features (multi-user)
- Close CRM sync
- Mobile app
- Custom webhook CRM builder
- Performance optimization
- Production monitoring

## 4. Key Technical Decisions

| Decision | Choice | Rationale |
|---|---|---|
| **Backend** | Python FastAPI | Async, Pydantic validation, OpenAPI auto-docs, familiar stack |
| **Database** | PostgreSQL (Supabase) | JSONB for flexible schemas, good JSON query performance, hosted option |
| **Queue** | Celery + Redis | Reliable async task processing for bulk ops |
| **LLM** | OpenRouter (Claude 4 / DeepSeek V4) | Already have keys, best for scoring + copy |
| **Sending** | Gmail API (OAuth) | Most accessible for solo owners, no SMTP config needed |
| **Auth** | JWT + API key | Simple, stateless, no extra infra |
| **Frontend** | Next.js + Tailwind | Responsive, SEO, fast iteration |
| **CRM Sync** | Direct REST API per CRM | No middleware, lower latency |
| **Workflow** | n8n (optional) | For complex multi-step automations, not required for core |

## 5. LLM Integration Points

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

## 6. API Endpoints (Core)

| Endpoint | Method | Description | Phase |
|---|---|---|---|
| `/api/leads/import/apollo` | POST | Import from Apollo | 0 |
| `/api/leads/import/csv` | POST | Import from CSV | 0 |
| `/api/leads/import/instantly` | POST | Import from Instantly | 1 |
| `/api/leads/import/smartlead` | POST | Import from Smartlead | 1 |
| `/api/leads/import/prospect` | POST | Prospect via ICP | 0 |
| `/api/leads/{id}` | GET | Get lead detail | 0 |
| `/api/leads/{id}/score` | POST | Score single lead | 0 |
| `/api/leads/batch/score` | POST | Score batch of leads | 0 |
| `/api/leads/{id}/verify` | POST | Verify single email | 0 |
| `/api/leads/batch/verify` | POST | Verify batch emails | 0 |
| `/api/leads/{id}/status` | PATCH | Update lead status | 0 |
| `/api/campaigns` | CRUD | Campaign management | 0 |
| `/api/campaigns/{id}/send` | POST | Trigger campaign send | 0 |
| `/api/campaigns/{id}/analytics` | GET | Campaign analytics | 0 |
| `/api/campaigns/templates` | CRUD | Sequence templates | 1 |
| `/api/crm/{provider}/sync` | POST | Sync to CRM | 0 |
| `/api/crm/{provider}/test` | POST | Test CRM connection | 0 |
| `/api/analytics/dashboard` | GET | Dashboard KPIs | 0 |
| `/api/analytics/recommendations` | GET | Smart recommendations | 2 |

## 7. Data Flow: End-to-End Campaign

```
User: "Find CTOs at Series A B2B SaaS companies in US, score them, 
       verify emails, create a 5-step campaign, send from my Gmail, 
       sync to HubSpot"

┌──────────────────────────────────────────────────────────┐
│ 1. PROSPECT                                              │
│    NL ICP → Apollo search → 25 leads returned            │
│    Enrich: company size, funding, tech stack, LinkedIn   │
│    Time: ~3 seconds                                       │
├──────────────────────────────────────────────────────────┤
│ 2. SCORE                                                 │
│    25 leads → AI Unified Score (6 dimensions)            │
│    5 Hot, 12 Warm, 8 Nurture/Cold                        │
│    Time: ~10 seconds (LLM per lead)                       │
├──────────────────────────────────────────────────────────┤
│ 3. VERIFY                                                │
│    25 emails → SMTP check → ZeroBounce API                │
│    22 valid, 2 catch-all, 1 invalid                       │
│    Invalid auto-excluded                                  │
│    Time: ~15 seconds                                       │
├──────────────────────────────────────────────────────────┤
│ 4. PERSONALIZE                                            │
│    22 leads → research per lead → unique emails          │
│    Reference: funding, post, hiring signal               │
│    Time: ~30 seconds (LLM batch)                          │
├──────────────────────────────────────────────────────────┤
│ 5. HUMAN REVIEW                                           │
│    User reviews 22 drafts → approves 20, edits 2          │
│    Time: ~5 minutes                                       │
├──────────────────────────────────────────────────────────┤
│ 6. SEND                                                   │
│    20 emails sent via Gmail API (under daily limit)       │
│    Day 0: initial send → Day 3: follow-up 1 → ...       │
│    Time: automated                                        │
├──────────────────────────────────────────────────────────┤
│ 7. CRM SYNC                                               │
│    20 contacts → HubSpot via API                          │
│    Scores as custom field, activities logged              │
│    Time: ~5 seconds                                        │
├──────────────────────────────────────────────────────────┤
│ TOTAL USER TIME: ~6 minutes                              │
│ TOTAL REALTIME: ~60 seconds + 5 min review                │
│ CAMPAIGN DURATION: 21 days (automated)                    │
└──────────────────────────────────────────────────────────┘
```

## 8. Authentication Flow

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

## 9. Security Considerations

| Concern | Mitigation |
|---|---|
| **Email credentials** | OAuth only (no password storage). SMTP creds encrypted at rest (AES-256). |
| **API keys** | Stored as bcrypt hash. One-way only. |
| **Lead data** | Encrypted at rest (AES-256). TLS 1.3 in transit. |
| **LLM data** | No training on user data via OpenRouter. Prompts contain lead info — user must consent. |
| **Rate limits** | Per-user API rate limiting. Daily send limits enforced server-side. |
| **CAN-SPAM** | Unsubscribe link on every email. Physical address in footer. Opt-out handling. |
| **GDPR** | Right to deletion. Data export. Consent logging for EU contacts. |
| **CRM tokens** | Stored encrypted. Only decrypted at sync time. |

## 10. Deployment

### Local Development
```bash
# Prerequisites: Python 3.11+, PostgreSQL, Redis
git clone https://github.com/ermohitsain/leadforge
cd leadforge/backend
cp .env.example .env  # Edit with your keys
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

### Docker
```bash
docker compose up -d
```

### Production (Supabase + Railway / Fly.io)
- Database: Supabase PostgreSQL
- Backend: Railway or Fly.io (auto-deploy from GitHub)
- Queue: Upstash Redis (serverless)
- LLM: OpenRouter API
- Emailing: Gmail API (user's own accounts)
- File storage: S3 (Backblaze B2)
