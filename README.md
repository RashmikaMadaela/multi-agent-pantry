# 🍽️ multi-agent-pantry

**Autonomous Restaurant Inventory Auditing & Supplier Procurement**

*Kaggle × Google · 5-Day AI Agents Intensive · **Agents for Business** Track*

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)](https://python.org)
[![Google ADK](https://img.shields.io/badge/Google_ADK-latest-4285F4?logo=google)](https://google.github.io/adk-docs/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react)](https://react.dev)
[![MCP](https://img.shields.io/badge/MCP-Model_Context_Protocol-orange)](https://modelcontextprotocol.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

> Three specialized AI agents that autonomously audit restaurant inventory, draft supplier restock emails grouped by supplier, and self-critique until the output meets a strict quality standard — all surfaced through a live web dashboard with one-click email sending.


---

## 📋 Table of Contents

1. [The Problem](#-the-problem)
2. [The Solution](#-the-solution)
3. [Architecture](#-architecture)
4. [Course Concepts Used](#-course-concepts-used)
5. [Project Journey](#-project-journey)
6. [Setup & Reproduction](#-setup--reproduction)
7. [Sample Output](#-sample-output)
8. [Project Structure](#-project-structure)
9. [Limitations & Future Work](#-limitations--future-work)

---

## 🔥 The Problem

Restaurant kitchens operate on razor-thin margins where **inventory management is a daily operational burden**. A typical back-of-house manager spends 30–45 minutes every shift manually checking stock levels against par values, identifying shortages, and drafting restock emails to multiple suppliers — all before the kitchen even opens.

This manual process introduces compounding failure modes:

- **Human error** — missed items, wrong quantities, or incorrect units on restock orders lead to mid-service stockouts or over-ordering perishables that go to waste.
- **Time cost** — a 40-minute daily task across 300 service days is **200+ hours per year** of skilled labour spent on data entry.
- **Inconsistent quality** — restock emails written at the end of a stressful shift often lack specifics (no exact quantities, no delivery urgency), causing back-and-forth with suppliers that delays fulfilment.
- **Duplicate requests** — without tracking which items have already been ordered, managers risk re-sending requests for items already en route from a supplier.

**The core insight:** inventory auditing and procurement drafting are structured, repeatable tasks where an AI agent pipeline can match human accuracy at a fraction of the time.

---

## ✅ The Solution

`multi-agent-pantry` is a **fully autonomous three-agent AI pipeline** built on Google's Agent Development Kit (ADK), backed by a FastAPI REST API, a SQLite database, and a React dashboard. Given a restaurant's inventory, it:

1. **Audits** all stock levels against minimum thresholds using a live MCP tool call — data is stored in and queried from a SQLite database.
2. **Groups** all low-stock items from the same supplier into a **single combined email** — one email per supplier, not one per item.
3. **Tracks "requested" state** — items covered by a sent email are excluded from future drafts until stock drops again, preventing duplicate orders.
4. **Drafts** a professional, complete restock email to each supplier with exact quantities for every item in that supplier's group.
5. **Self-critiques** the draft against three strict quality criteria and automatically **retries** with targeted feedback until the email passes — or after 3 attempts outputs the best available version with a warning.
6. **Surfaces everything in a web UI** — managers can review, edit, and send the drafted emails to suppliers with a single click, directly from the dashboard.

**Business value delivered:**
| Metric | Manual Process | multi-agent-pantry |
|---|---|---|
| Time per procurement cycle | ~40 min/day | ~2 min/day |
| Stockout risk | High (human error) | Eliminated for tracked SKUs |
| Email quality | Inconsistent | Enforced by Evaluator agent |
| Duplicate order risk | High | Eliminated via "requested" state |
| Audit trail | None | Full DB log + draft history |
| Email sending | Manual, copy-paste | One-click Gmail SMTP |

One stock update. Zero manual procurement. Production-quality output.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│              React + Vite Frontend  (localhost:5173)                 │
│   Inventory table · Draft review · Edit · Send · Add item modal      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  REST (fetch)
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  FastAPI Backend  (api/main.py)                      │
│     CRUD endpoints · Supplier grouping · "Requested" state logic     │
│     Auto-triggers ADK pipeline on low-stock PUT · Gmail SMTP send    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  SQLAlchemy ORM
                               ▼
                    ┌──────────────────────┐
                    │   SQLite Database     │
                    │  (data/pantry.db)     │
                    │  inventory_items      │
                    │  email_drafts         │
                    │  email_draft_items    │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │    orchestrator.py    │
                    │   (async retry loop)  │
                    └──┬───────────────┬───┘
                       │               │
           ┌───────────▼──┐     ┌──────▼────────────────────────────┐
           │ AuditorAgent │     │         Retry Loop (max 3)         │
           │ (LlmAgent)   │     │                                    │
           │              │     │  ┌──────────────────────────────┐  │
           │  McpToolset  │     │  │  ProcurementAgent (LlmAgent) │  │
           └──────┬───────┘     │  │  (vendor details from DB)    │  │
                  │ stdio MCP   │  └───────────────┬──────────────┘  │
           ┌──────▼───────┐     │                  │ EmailDraft       │
           │  MCP Server  │     │  ┌───────────────▼──────────────┐  │
           │  (FastMCP)   │     │  │  EvaluatorAgent  (LlmAgent)  │  │
           │  + Pydantic  │     │  │  PASS → save & print         │  │
           └──────────────┘     │  │  FAIL → critique → retry     │  │
                                │  └──────────────────────────────┘  │
                                └────────────────────────────────────┘
```

### Agent Breakdown

#### 🔍 Auditor Agent
Calls the `check_inventory` MCP tool, receives the Pydantic-validated inventory JSON from the SQLite database, and identifies all items where `current_stock ≤ minimum_threshold`. Computes `quantity_to_order = reorder_quantity − current_stock` for each deficit item and produces a structured **ShortageReport**. When triggered from the API, the report is scoped to a specific set of items for the target supplier.

#### 📧 Procurement Agent
Receives the ShortageReport and supplier contact details (queried from the DB, not a static file), then drafts a professional restock request email covering **all items in that supplier group**. On retry attempts, it receives the Evaluator's specific critique prepended to its context and rewrites the email addressing every raised issue.

#### ✅ Evaluator Agent
Scores the email draft against three hard criteria: **(1)** every shortage item is mentioned, **(2)** each item has an exact numeric quantity + unit, **(3)** a concrete delivery date or urgency statement is present. Returns `VERDICT: PASS` or `VERDICT: FAIL` with a targeted critique identifying every gap.

### Database Design

```
inventory_items          email_drafts              email_draft_items
──────────────           ────────────────          ─────────────────
id (PK)                  id (PK)                   id (PK)
item_name                supplier_email  ◄──────── draft_id  (FK)
unit                     supplier_name             item_id   (FK) ──► inventory_items.id
current_stock            draft_text
minimum_threshold        subject
reorder_quantity         status
supplier_name            created_at
supplier_email           updated_at
created_at
updated_at
```

**Key design: one `EmailDraft` per supplier**, not per item. The `email_draft_items` join table records which items are "requested" (in-flight), enabling precise exclusion logic on the next procurement cycle.

### API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/inventory` | List all inventory items |
| `POST` | `/api/inventory` | Add a new item (with supplier details) |
| `PUT` | `/api/inventory/{id}` | Update stock count → auto-triggers ADK pipeline if stock < threshold |
| `GET` | `/api/drafts` | Fetch all `pending_review` email drafts |
| `PUT` | `/api/drafts/{id}` | Edit a draft's text or subject |
| `POST` | `/api/drafts/{id}/send` | Send via Gmail SMTP → marks draft as `sent` |
| `DELETE` | `/api/drafts/{id}` | Dismiss a draft without sending |

---

## 🧠 Course Concepts Used

This project meaningfully implements **4 of the 6** course concepts:

### 1. Multi-Agent Systems — Google ADK ✅

All three agents are `LlmAgent` instances from `google-adk`. The orchestrator uses ADK's `Runner` and `InMemorySessionService` to manage each agent's conversation lifecycle with full session isolation — each agent run gets its own `session_id` so conversation history never bleeds between agents or retry attempts.

```python
from google.adk.agents import LlmAgent
from google.adk import Runner
from google.adk.sessions import InMemorySessionService

agent = LlmAgent(name="AuditorAgent", model="gemini-2.0-flash", tools=[mcp_toolset])
runner = Runner(agent=agent, app_name="multi-agent-pantry", session_service=session_service)
```

### 2. MCP Server ✅

The `check_inventory()` tool is served via a **Model Context Protocol server** built with `FastMCP`. The Auditor Agent connects using ADK's `McpToolset` with `StdioConnectionParams`, discovering the tool via MCP's capability handshake at runtime — not through hardcoded function imports.

```
AuditorAgent ──(stdio JSON-RPC)──▶ inventory_server.py (FastMCP)
                                         │
                                    Pydantic validation
                                         │
                                    queries SQLite DB
                                         │
                                    returns inventory JSON
```

This decoupling means swapping the SQLite store for a live Toast/Square POS API requires **zero agent code changes** — only `inventory_server.py` changes.

### 3. Security Features ✅

- `GOOGLE_API_KEY` and `GMAIL_APP_PASSWORD` loaded exclusively via `python-dotenv` from `.env`
- Keys validated at startup with `sys.exit(1)` if missing — clear error, no silent failures
- `.env` in `.gitignore`; `.env.example` committed with blank values only
- MCP server validates every outgoing record with **Pydantic** (`InventoryItem` model with field constraints and cross-field validators)
- Evaluator `parse_evaluation_result()` defaults to `FAIL` on malformed LLM output — safe fallback
- Gmail credentials never logged or exposed to the frontend

### 4. Deployability ✅

- **`Dockerfile`** — multi-stage build, non-root user, secrets injected at runtime only
- **`docker-compose.yml`** — single-service setup with `env_file` directive (never `ENV API_KEY=...`)
- **`Makefile`** — `make run`, `make docker-up`, `make test` for one-command operation

---

## 🗺️ Project Journey

The project started with a simple idea: replace the daily procurement email routine with an agent. The first version used raw `google-generativeai` with a plain Python function for inventory — it worked, but felt like a demo, not a system.

**The first real architectural decision** was pivoting to `google-adk` and separating the inventory tool into a proper MCP server. This forced me to think about tool boundaries: what does the *agent* need to know versus what should be *data infrastructure*? The answer shaped the entire project — the MCP server became a clean data contract, and swapping mock data for a real POS API became a two-line change.

**The retry loop was the hardest part to get right.** The first instinct was to use ADK's `SequentialAgent` + `LoopAgent`, but the conditional retry (PASS exits, FAIL loops) required state that doesn't flow naturally through those primitives. Switching to an explicit `async for attempt in range(1, MAX_ATTEMPTS + 1)` loop with Python's `for...else` clause made the logic self-documenting and testable.

**Supplier grouping required a rethink of the data model.** The original design created one `EmailDraft` per inventory item, leading to duplicated emails for suppliers with multiple low-stock products. Restructuring the draft to be *supplier-scoped* — with a join table tracking which items each draft covers — made the "requested" state logic clean and composable: exclude items already in a sent draft, unless they went low again after the send timestamp.

**Adding the backend and frontend turned the pipeline into a product.** A FastAPI layer handles all the supplier-grouping and "requested" state logic before even touching the agents, and the React dashboard lets restaurant managers interact with the system without touching the terminal. The Gmail SMTP integration closes the loop — from stock drop to supplier email, zero copy-paste required.

The biggest lesson: **multi-agent architecture is as much about data contracts and failure modes as it is about prompts.**

---

## 🚀 Setup & Reproduction

### Prerequisites

- Python 3.11+
- Node.js 18+ (for the frontend)
- A Google AI Studio API key ([get one free](https://aistudio.google.com/app/apikey))
- Docker (optional, for containerised CLI run)

### Option A — Full Web App (Recommended)

The complete experience: live inventory management dashboard + AI-powered draft generation + one-click email sending.

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/multi-agent-pantry
cd multi-agent-pantry

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Open .env and set:
#   GOOGLE_API_KEY=your_key_here
#   GMAIL_SENDER=you@gmail.com          (optional — for one-click sending)
#   GMAIL_APP_PASSWORD=xxxx xxxx xxxx   (optional — Gmail App Password)

# 5. Start the FastAPI backend (Terminal 1)
uvicorn api.main:app --reload
# → Runs on http://localhost:8000
# → Seeds the SQLite database on first run

# 6. Start the React frontend (Terminal 2)
cd frontend
npm install
npm run dev
# → Runs on http://localhost:5173
```

Open **`http://localhost:5173`** — the dashboard shows live inventory, automatically triggers the AI pipeline when you update a stock value below its threshold, and lets you review, edit, and send the grouped supplier emails.

> **Gmail App Password setup:** Google Account → Security → 2-Step Verification → App Passwords → Create one named "Pantry App". Paste the 16-character token into `GMAIL_APP_PASSWORD` in your `.env`. This is completely free — no paid service needed.

### Option B — CLI Pipeline (No UI)

```bash
# Run the full agent pipeline directly against the mock inventory data
python main.py
```

The pipeline logs each step and saves the final email to `output/final_email_<supplier>.txt`.

### Option C — Makefile Shortcuts

```bash
make setup        # Create .venv and install all dependencies
make run          # Run the CLI pipeline locally
make test         # Run the test suite
make clean        # Remove output/ and __pycache__
```

### Option D — Docker (CLI pipeline only)

```bash
# 1. Configure your API key in .env first
cp .env.example .env  # then edit .env

# 2. Build and run with docker-compose
make docker-up

# Or directly:
docker compose up --build
```

> **Note:** The Docker setup runs the CLI pipeline (`main.py`). The web app (FastAPI + React) is intended for local development.

### Expected Output (CLI)

```
11:30:01 [INFO] orchestrator — ═══ multi-agent-pantry pipeline starting ═══
11:30:01 [INFO] orchestrator — Targeting items: ['Roma Tomatoes', 'Garlic']
11:30:01 [INFO] orchestrator — ━━━ STEP 1: Running AuditorAgent ━━━
11:30:05 [INFO] orchestrator — ShortageReport received (487 chars)
11:30:05 [INFO] orchestrator — ━━━ STEP 2: Running ProcurementAgent (attempt 1/3) ━━━
11:30:09 [INFO] orchestrator — EmailDraft received (892 chars)
11:30:09 [INFO] orchestrator — ━━━ STEP 3: Running EvaluatorAgent (attempt 1/3) ━━━
11:30:11 [INFO] orchestrator — EvaluationResult: verdict=PASS | critique=(none)
11:30:11 [INFO] orchestrator — ✅ Email PASSED evaluation on attempt 1
```

---

## 📄 Sample Output

### ShortageReport (from AuditorAgent — Green Valley Produce group)

```
SHORTAGE REPORT — La Bella Cucina
==================================
The following items require immediate restocking:

1. Roma Tomatoes  | Unit: kg | Current: 8.0  | Need to Order: 22.0
2. Garlic         | Unit: kg | Current: 1.0  | Need to Order: 4.0

SUMMARY: 2 item(s) require restocking.
```

### Final Email (combined for Green Valley Produce — PASS on attempt 1)

```
Subject: Restock Request: Roma Tomatoes, Garlic

Dear Green Valley Produce,

I hope this message finds you well. I'm writing on behalf of La Bella Cucina
to place an urgent restock order for several ingredients that have fallen
below our minimum stock thresholds.

Please arrange delivery of the following items to our kitchen by July 8, 2026:

  1. Roma Tomatoes  — 22.0 kg
  2. Garlic         —  4.0 kg

Given our current stock levels, this delivery is time-sensitive and required
by the date above to avoid service disruption. Please confirm receipt of this
order and provide an estimated delivery window at your earliest convenience.

This order falls under our standard Net-30 payment terms.

Thank you for your continued partnership.

Warm regards,
Chef Sofia Marchetti
La Bella Cucina
```

> **Note:** If Roma Tomatoes and Garlic were already covered by a sent email, they will be excluded from the next draft for Green Valley Produce until their stock drops again after the order was sent.

---

## 📁 Project Structure

```
multi-agent-pantry/
│
├── README.md                    ← You are here
├── spec.md                      ← Full architecture specification
├── requirements.txt             ← google-adk, fastapi, uvicorn, sqlalchemy,
│                                   mcp, pydantic, python-dotenv, aiofiles
├── Makefile                     ← make setup | make run | make docker-up | make test
├── Dockerfile                   ← Multi-stage, non-root, no baked secrets
├── docker-compose.yml           ← Single-service deployment (CLI pipeline)
├── .env.example                 ← Safe template (blank values only)
├── .gitignore
│
├── data/
│   ├── database.py              ← SQLAlchemy models & helpers:
│   │                               InventoryItem, EmailDraft, EmailDraftItem
│   │                               init_db(), seed_database(), get_db()
│   ├── inventory.py             ← Mock inventory data (used by CLI main.py)
│   ├── vendors.py               ← Fallback supplier contact details (CLI mode)
│   └── pantry.db                ← SQLite database (git-ignored)
│
├── mcp_server/
│   └── inventory_server.py      ← FastMCP server + Pydantic validation
│                                   Reads from SQLite DB (or falls back to mock)
│
├── agents/
│   ├── auditor.py               ← AuditorAgent (LlmAgent + McpToolset)
│   ├── procurement.py           ← ProcurementAgent + dynamic vendor message builder
│   └── evaluator.py             ← EvaluatorAgent + result parser
│
├── api/
│   ├── main.py                  ← FastAPI backend
│   │                               • GET/POST /api/inventory
│   │                               • PUT /api/inventory/{id} → auto-triggers pipeline
│   │                               • GET/PUT/DELETE /api/drafts
│   │                               • POST /api/drafts/{id}/send
│   └── email_sender.py          ← Gmail SMTP sender (App Password auth)
│
├── frontend/                    ← React 19 + Vite app
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── App.jsx              ← Root component, layout, state management
│       ├── index.css            ← Global styles & design tokens
│       ├── api/
│       │   └── client.js        ← Typed fetch wrappers for all API endpoints
│       └── components/
│           ├── InventoryTable.jsx  ← Live inventory table with inline stock editing
│           ├── DraftPanel.jsx      ← Draft review UI (grouped items per supplier)
│           ├── AddItemModal.jsx    ← Add new inventory item form
│           └── Toast.jsx           ← Notification toasts
│
├── orchestrator.py              ← Async ADK pipeline + retry loop (multi-item aware)
├── main.py                      ← CLI entry point (uses mock data, no web server)
│
└── output/                      ← Git-ignored; stores CLI run artefacts
    └── final_email_<supplier>.txt
```

---

## 🔮 Limitations & Future Work

| Limitation | Future Enhancement |
|---|---|
| SQLite database | Swap to PostgreSQL for multi-user / production deployments |
| Single-restaurant setup | Multi-tenant support with per-restaurant data isolation |
| No scheduling | Cron-triggered audits or webhook integration with POS systems |
| In-memory ADK sessions | Persistent session storage for full audit history & compliance logging |
| Free-tier rate limits | Exponential backoff and model fallback (Flash Lite → Flash → Pro) |
| CLI Docker image only | Dockerise the full web stack (FastAPI + React) with `nginx` reverse proxy |
| No auth on the web UI | Add JWT / OAuth2 authentication for production use |

---


Built with ❤️ for the **Kaggle × Google 5-Day AI Agents Intensive**

*Agents for Business Track*

