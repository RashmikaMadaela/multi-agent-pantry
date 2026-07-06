# multi-agent-pantry — Project Specification
### Kaggle × Google · 5-Day AI Agents Intensive · "Agents for Business" Track

> **Rubric target: 100 / 100**
> This document drives every implementation decision. All code, comments, and documentation must stay aligned with the grading criteria annotated below.

---

## Rubric Alignment Map

| Rubric Area | Points | How We Earn Them |
|---|---|---|
| Core Concept — meaningful business use | 10 | Autonomous restaurant procurement saves labour hours & prevents stockouts |
| Writeup — Problem / Solution / Architecture / Journey | 20 | World-class README.md (outline in §9) |
| Technical — Multi-agent systems **(ADK)** | ✅ 50 | All agents built with `google-adk` SequentialAgent + LlmAgent |
| Technical — **MCP Server** | ✅ 50 | Inventory tool exposed as a local MCP server |
| Technical — **Security features** | ✅ 50 | `.env`, secrets audit, input sanitisation |
| Technical — **Deployability** | ✅ 50 | Docker + docker-compose; one-command run |
| Code Quality | included | Mandatory docstrings + inline comments standard (see §8) |
| Security rule | hard gate | Zero plaintext secrets anywhere in the repo |
| Documentation | 20 | README covers problem → setup → architecture → journey |

> The rubric awards the 50 technical points for **at least 3** course concepts. We implement **4** (ADK, MCP, Security, Deployability) for maximum headroom.

---

## 1. Project Overview

**Problem:** Restaurant kitchens lose ~8–12 % of revenue through manual inventory errors — over-ordering perishables, running out of key ingredients mid-service, or spending 30–45 minutes per shift on procurement emails.

**Solution:** `multi-agent-pantry` is a fully autonomous, three-agent AI pipeline that:
1. **Audits** live stock levels against minimum thresholds (no human involvement).
2. **Drafts** a professional supplier restock email with exact quantities and delivery urgency.
3. **Self-critiques** the draft and automatically revises it until it passes quality gates (max 3 attempts).

**Business value delivered:**
- Procurement time: ~40 min/day → ~2 min/day (automated trigger + review).
- Stockout risk: eliminated for tracked SKUs.
- Audit trail: every run logs the shortage report, draft history, and final email.

---

## 2. Course Concepts Used (≥ 3 Required)

### 2.1 Multi-Agent Systems — Google ADK ✅

We use the **`google-adk`** (Agent Development Kit) library, not raw `google-generativeai`. ADK provides:

- `LlmAgent` — a single agent with a system prompt and optional tools.
- `SequentialAgent` — chains sub-agents so output of one feeds the next.
- Built-in state passing between agents via `InvocationContext`.

All three agents (Auditor, Procurement, Evaluator) are `LlmAgent` instances wired into a custom orchestrator that implements the retry loop.

### 2.2 MCP Server ✅

The `check_inventory()` tool is **not** a plain Python function — it is served via a **Model Context Protocol (MCP) server** (`mcp` Python package). The Auditor Agent connects to this server as an MCP client and discovers the tool dynamically.

This demonstrates real-world tool decoupling: the inventory data source could be swapped for a real ERP/POS system without touching agent code.

```
┌──────────────────────┐        MCP (stdio / SSE)       ┌─────────────────────┐
│   Auditor LlmAgent   │ ──────────────────────────────▶ │  MCP Inventory      │
│   (ADK)              │ ◀────────────────────────────── │  Server             │
└──────────────────────┘    tool result: inventory JSON  └─────────────────────┘
```

### 2.3 Security Features ✅

- `GOOGLE_API_KEY` loaded exclusively from `.env` via `python-dotenv`. Never referenced as a literal in code.
- `.env` in `.gitignore`; `.env.example` committed with blank values.
- Pre-commit hook (documented in README) using `detect-secrets` to block accidental key commits.
- MCP server validates inventory payloads with `pydantic` before returning to agent.
- No user-supplied input reaches the model without sanitisation.

### 2.4 Deployability ✅

- **`Dockerfile`** — multi-stage build; non-root user; no secrets baked in.
- **`docker-compose.yml`** — spins up MCP server + orchestrator as linked services.
- **`Makefile`** — `make run`, `make docker-up`, `make test` convenience targets.
- Environment variables injected at runtime via `docker-compose` `env_file` directive.

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          main.py (entry point)                      │
│                      loads .env · configures ADK                    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │     Orchestrator      │
                    │   orchestrator.py     │
                    │  (custom retry loop)  │
                    └──┬───────────────┬───┘
                       │               │
           ┌───────────▼──┐     ┌──────▼──────────────────────────┐
           │ Auditor Agent│     │        Retry Loop (max 3)        │
           │  (LlmAgent)  │     │                                  │
           │              │     │  ┌─────────────────────────┐     │
           │  MCP Client  │     │  │  Procurement Agent      │     │
           └──────┬───────┘     │  │  (LlmAgent)             │     │
                  │ MCP call    │  └────────────┬────────────┘     │
           ┌──────▼───────┐     │               │ EmailDraft       │
           │  MCP Inventory│     │  ┌────────────▼────────────┐     │
           │  Server       │     │  │  Evaluator Agent        │     │
           │  (stdio/SSE)  │     │  │  (LlmAgent)             │     │
           └──────┬───────┘     │  │  PASS → final output    │     │
                  │ inventory   │  │  FAIL → critique → retry│     │
                  │ JSON        │  └─────────────────────────┘     │
           ┌──────▼───────┐     └─────────────────────────────────┘
           │ ShortageReport│
           └──────────────┘
```

### Data Flow Summary

1. `main.py` initialises ADK, loads env, calls `orchestrate()`.
2. **Auditor** calls `check_inventory` via MCP → receives inventory JSON → returns `ShortageReport`.
3. **Procurement** receives `ShortageReport` + `VendorDetails` → returns `EmailDraft`.
4. **Evaluator** scores the draft → returns `EvaluationResult {verdict, critique}`.
5. If `FAIL` and `attempt < 3` → critique passed back to Procurement for revision.
6. Final email written to `output/final_email.txt` and printed to stdout.

---

## 4. Agent Definitions

### 4.1 Auditor Agent

```python
LlmAgent(
    name="AuditorAgent",
    model="gemini-2.0-flash",
    tools=[mcp_toolset],   # connected to MCP Inventory Server
    system_prompt="""
        You are a restaurant inventory auditor.
        Call the check_inventory tool to retrieve current stock levels.
        Identify all items where current_stock <= minimum_threshold.
        Return a structured shortage report: item name, current stock, unit, quantity to order.
        quantity_to_order = reorder_quantity - current_stock.
    """
)
```

**Behaviour:** Exactly one tool call. Returns plain-text `ShortageReport`.

---

### 4.2 Procurement Agent

```python
LlmAgent(
    name="ProcurementAgent",
    model="gemini-2.0-flash",
    tools=[],
    system_prompt="""
        You are a procurement officer at a busy restaurant.
        Draft a professional restock request email using the shortage report and vendor details.
        The email MUST include:
          - Restaurant name and sender name
          - Vendor contact name
          - Each shortage item with EXACT quantity and unit
          - A concrete delivery date or explicit urgency statement
          - Account number for reference
        If a critique is provided, address every point raised before rewriting.
    """
)
```

**Behaviour:** On first call — drafts from scratch. On retry — prepends critique to context.

---

### 4.3 Evaluator Agent

```python
LlmAgent(
    name="EvaluatorAgent",
    model="gemini-2.0-flash",
    tools=[],
    system_prompt="""
        You are a strict procurement quality evaluator.
        Given a restock email and the original shortage report, check ALL three criteria:
          1. Every item in the shortage report appears in the email.
          2. Each item has an exact numeric quantity and unit.
          3. A specific delivery date OR explicit urgency level is stated.
        Respond in this exact format:
          VERDICT: PASS   (or FAIL)
          CRITIQUE: <empty if PASS, specific gaps if FAIL>
    """
)
```

**Behaviour:** Returns `PASS` (all 3 criteria met) or `FAIL` + targeted critique.

---

## 5. MCP Server Specification

**File:** `mcp_server/inventory_server.py`
**Transport:** `stdio` (default) or `SSE` (for Docker networking)

```python
# Tool exposed via MCP
@mcp.tool()
def check_inventory() -> list[InventoryItem]:
    """
    Returns current stock levels for all tracked ingredients.
    Validated by Pydantic before returning to the calling agent.
    """
```

**Pydantic model:**

```python
class InventoryItem(BaseModel):
    item_name: str
    unit: str
    current_stock: float
    minimum_threshold: float
    reorder_quantity: float
```

The Auditor Agent connects using ADK's `MCPToolset` with the server command:

```python
MCPToolset(
    connection_params=StdioServerParameters(
        command="python",
        args=["mcp_server/inventory_server.py"],
    )
)
```

---

## 6. Mock Data Structures

### 6.1 Inventory (`data/inventory.py`)

```python
INVENTORY: list[dict] = [
    {"item_name": "Chicken Breast",   "unit": "kg",     "current_stock": 4.0,  "minimum_threshold": 10.0, "reorder_quantity": 25.0},
    {"item_name": "Olive Oil",        "unit": "liters",  "current_stock": 1.5,  "minimum_threshold": 5.0,  "reorder_quantity": 15.0},
    {"item_name": "Roma Tomatoes",    "unit": "kg",     "current_stock": 8.0,  "minimum_threshold": 12.0, "reorder_quantity": 30.0},
    {"item_name": "All-Purpose Flour","unit": "kg",     "current_stock": 20.0, "minimum_threshold": 15.0, "reorder_quantity": 50.0},  # OK
    {"item_name": "Heavy Cream",      "unit": "liters",  "current_stock": 2.0,  "minimum_threshold": 6.0,  "reorder_quantity": 12.0},
    {"item_name": "Parmesan Cheese",  "unit": "kg",     "current_stock": 0.5,  "minimum_threshold": 3.0,  "reorder_quantity": 8.0},
    {"item_name": "Garlic",           "unit": "kg",     "current_stock": 1.0,  "minimum_threshold": 2.0,  "reorder_quantity": 5.0},
    {"item_name": "Basmati Rice",     "unit": "kg",     "current_stock": 18.0, "minimum_threshold": 10.0, "reorder_quantity": 40.0},  # OK
]
```

**Expected shortages (6 of 8 items):**

| Item | Current | Min | To Order |
|---|---|---|---|
| Chicken Breast | 4.0 kg | 10.0 kg | 21.0 kg |
| Olive Oil | 1.5 L | 5.0 L | 13.5 L |
| Roma Tomatoes | 8.0 kg | 12.0 kg | 22.0 kg |
| Heavy Cream | 2.0 L | 6.0 L | 10.0 L |
| Parmesan Cheese | 0.5 kg | 3.0 kg | 7.5 kg |
| Garlic | 1.0 kg | 2.0 kg | 4.0 kg |

### 6.2 Vendor (`data/vendors.py`)

```python
VENDOR: dict = {
    "vendor_name": "FreshFields Wholesale Distributors",
    "contact_name": "Marcus Thorne",
    "email": "marcus.thorne@freshfields-wholesale.com",
    "phone": "+1-800-555-0192",
    "account_number": "FF-78432",
    "restaurant_name": "La Bella Cucina",
    "restaurant_contact": "Chef Sofia Marchetti",
    "required_delivery_date": "2026-07-05",
    "payment_terms": "Net-30",
}
```

---

## 7. Python Dependencies

**`requirements.txt`**

```
google-adk>=0.3.0          # ADK: LlmAgent, SequentialAgent, MCPToolset
mcp>=1.0.0                  # MCP server + client protocol
pydantic>=2.0.0             # Inventory payload validation in MCP server
python-dotenv>=1.0.0        # Secure API key loading from .env
```

**Python version:** 3.11+ (required by `google-adk`)

---

## 8. Code Quality Standards

Every file MUST follow these standards (judges will read the code):

### Comment Requirements

```python
# ── Module-level docstring: what this file does, why it exists ──────────────
"""
agents/auditor.py
Defines the AuditorAgent using Google ADK's LlmAgent.
Connects to the MCP Inventory Server via MCPToolset to retrieve live
stock data and produce a ShortageReport for the Procurement pipeline.
"""

# ── Class/function docstrings ────────────────────────────────────────────────
def build_auditor_agent(mcp_toolset: MCPToolset) -> LlmAgent:
    """
    Constructs and returns the Auditor LlmAgent.

    Args:
        mcp_toolset: Pre-configured MCPToolset connected to the inventory server.

    Returns:
        LlmAgent ready to be invoked by the orchestrator.
    """

# ── Inline comments explain WHY, not WHAT ───────────────────────────────────
# We pass the full inventory JSON back rather than pre-filtering in the server
# so the LLM can verify its own reasoning — this is an intentional design choice
# that lets the Auditor agent demonstrate tool-augmented reasoning.
```

### Naming Conventions

- Agents: `AuditorAgent`, `ProcurementAgent`, `EvaluatorAgent`
- Data models: `InventoryItem`, `ShortageReport`, `EmailDraft`, `EvaluationResult`
- Constants: `INVENTORY`, `VENDOR`, `MAX_PROCUREMENT_ATTEMPTS = 3`

---

## 9. Project File Structure

```
multi-agent-pantry/
│
├── README.md                    # World-class writeup (see §10 outline)
├── spec.md                      # ← This file
├── requirements.txt
├── Makefile                     # make run | make docker-up | make test
├── Dockerfile                   # Multi-stage, non-root, no baked secrets
├── docker-compose.yml           # MCP server + orchestrator services
├── .env.example                 # Blank template — safe to commit
├── .gitignore                   # .env, __pycache__, output/
│
├── data/
│   ├── inventory.py             # INVENTORY list (mock data)
│   └── vendors.py               # VENDOR dict (mock data)
│
├── mcp_server/
│   └── inventory_server.py      # MCP server exposing check_inventory()
│
├── agents/
│   ├── auditor.py               # AuditorAgent (LlmAgent + MCPToolset)
│   ├── procurement.py           # ProcurementAgent (LlmAgent)
│   └── evaluator.py             # EvaluatorAgent (LlmAgent)
│
├── orchestrator.py              # Retry loop; wires agents together
├── main.py                      # Entry point: load env → orchestrate()
│
├── output/                      # Git-ignored; stores run artefacts
│   └── final_email.txt
│
└── tests/
    ├── test_mcp_server.py       # Unit tests for MCP tool response + validation
    ├── test_evaluator.py        # Unit tests for pass/fail logic
    └── test_orchestrator.py     # Integration test: mock agents, verify retry loop
```

---

## 10. README.md Outline (Writeup — 20 pts)

The README must cover all four required sections to score full writeup points:

### Sections

1. **Header** — Project name, track badge, one-line description, demo GIF/screenshot.

2. **The Problem** (~150 words)
   - Manual inventory is error-prone and time-consuming.
   - Stockouts cost restaurants revenue mid-service.
   - Procurement emails are repetitive, low-value work.

3. **The Solution** (~150 words)
   - Three-agent pipeline: Audit → Draft → Evaluate/Revise.
   - Fully autonomous: one command, zero human input required.
   - Self-healing: Evaluator enforces quality; Procurement agent retries.

4. **Architecture** — embed the ASCII diagram from §3 + one paragraph per agent.

5. **Course Concepts Used**
   - ADK (`LlmAgent`, `MCPToolset`)
   - MCP Server (`inventory_server.py`)
   - Security (`.env`, `detect-secrets`, Pydantic validation)
   - Deployability (Docker, docker-compose, Makefile)

6. **Project Journey** (~200 words) — what we built first, what broke, what we learned, how the Evaluator retry loop design evolved.

7. **Setup & Reproduction** (step-by-step)
   ```bash
   git clone https://github.com/<you>/multi-agent-pantry
   cd multi-agent-pantry
   cp .env.example .env          # add your GOOGLE_API_KEY
   pip install -r requirements.txt
   python main.py
   # OR with Docker:
   make docker-up
   ```

8. **Sample Output** — paste a real run's shortage report + final email.

9. **Limitations & Future Work** — real POS integration, Slack notifications, multi-vendor routing.

---

## 11. Security Checklist (Hard Gate)

All items below MUST be true before submission:

- [ ] `GOOGLE_API_KEY` only referenced via `os.environ["GOOGLE_API_KEY"]`
- [ ] `.env` listed in `.gitignore`
- [ ] `git log --all -S "AIza"` returns nothing (no key ever committed)
- [ ] `.env.example` contains only blank values
- [ ] MCP server validates all outgoing data with Pydantic
- [ ] `detect-secrets scan` reports zero findings
- [ ] Docker image built with `--secret` or runtime env injection (no `ENV API_KEY=...` in Dockerfile)

---

## 12. Evaluator Pass/Fail Criteria (Reference)

| # | Criterion | Failure Example |
|---|---|---|
| 1 | All shortage items present in email | "Garlic not mentioned" |
| 2 | Exact quantity + unit per item | "Says 'some olive oil' instead of 13.5 L" |
| 3 | Delivery date OR urgency stated | "No date, no urgency language" |

Critique format returned on `FAIL`:
> `"Missing items: Garlic. No quantity specified for Olive Oil. No delivery date or urgency found."`

---

*End of specification — last updated 2026-07-02*
