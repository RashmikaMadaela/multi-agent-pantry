"""
api/main.py

FastAPI backend for the Multi-Agent Pantry web application.

ENDPOINTS
---------
GET  /api/inventory           → List all inventory items
POST /api/inventory           → Add a new item (with supplier details)
PUT  /api/inventory/{id}      → Update stock count
                                  ↳ Auto-triggers ADK pipeline if stock < threshold
GET  /api/drafts              → Fetch all pending_review email drafts
PUT  /api/drafts/{id}         → Edit a draft's text/subject
POST /api/drafts/{id}/send    → Send via Gmail SMTP → mark as sent
DELETE /api/drafts/{id}       → Dismiss a draft without sending

CORS is enabled for localhost:5173 (Vite dev server).

AUTO-TRIGGER LOGIC
------------------
When PUT /api/inventory/{id} is called and the new stock value is below
the minimum_threshold, a FastAPI BackgroundTask runs the full ADK pipeline
(Auditor → Procurement → Evaluator) and saves the resulting email draft to
the email_drafts table with status='pending_review'.
Only one pending draft per item is kept at a time to avoid duplicates.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# Add project root to path so orchestrator and data modules are importable
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from data.database import (
    EmailDraft,
    InventoryItem,
    get_db,
    init_db,
    seed_database,
)
from api.email_sender import send_restock_email

log = logging.getLogger("api")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)


# ---------------------------------------------------------------------------
# Lifespan: init DB + seed on startup
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = next(get_db())
    seed_database(db)
    db.close()
    log.info("✅ Database initialised and seeded.")
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Multi-Agent Pantry API",
    description="Inventory management with automatic AI-powered restock email drafting.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class InventoryItemCreate(BaseModel):
    item_name: str = Field(..., min_length=1)
    unit: str = Field(..., min_length=1)
    current_stock: float = Field(..., ge=0)
    minimum_threshold: float = Field(..., gt=0)
    reorder_quantity: float = Field(..., gt=0)
    supplier_name: str = Field(..., min_length=1)
    supplier_email: str = Field(..., min_length=5)


class InventoryItemUpdate(BaseModel):
    current_stock: Optional[float] = Field(None, ge=0)
    minimum_threshold: Optional[float] = Field(None, gt=0)
    reorder_quantity: Optional[float] = Field(None, gt=0)
    supplier_name: Optional[str] = None
    supplier_email: Optional[str] = None


class InventoryItemOut(BaseModel):
    id: int
    item_name: str
    unit: str
    current_stock: float
    minimum_threshold: float
    reorder_quantity: float
    supplier_name: str
    supplier_email: str
    is_low_stock: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DraftOut(BaseModel):
    id: int
    item_id: int
    item_name: str
    supplier_name: str
    supplier_email: str
    draft_text: str
    subject: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DraftUpdate(BaseModel):
    draft_text: Optional[str] = None
    subject: Optional[str] = None


# ---------------------------------------------------------------------------
# Background task: run the full ADK pipeline and save the draft
# ---------------------------------------------------------------------------
async def _run_draft_pipeline(item_id: int) -> None:
    """
    Runs the full Auditor → Procurement → Evaluator pipeline and saves
    the resulting email draft to the database for the given item.
    """
    from orchestrator import orchestrate

    db = next(get_db())
    try:
        item = db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
        if not item:
            log.error("Draft pipeline: item_id=%d not found", item_id)
            return

        log.info("🤖 Starting ADK pipeline for low-stock item: %s", item.item_name)

        # Run the full multi-agent pipeline
        email_text = await orchestrate(target_item_name=item.item_name)

        if not email_text:
            log.warning("ADK pipeline returned empty draft for item_id=%d", item_id)
            return

        # Extract subject from the first line of the email if possible
        lines = email_text.strip().splitlines()
        subject = f"Restock Request: {item.item_name}"
        for line in lines:
            if line.lower().startswith("subject:"):
                subject = line.split(":", 1)[1].strip()
                break

        # Save draft
        draft = EmailDraft(
            item_id=item_id,
            draft_text=email_text,
            subject=subject,
            status="pending_review",
        )
        db.add(draft)
        db.commit()
        log.info("✅ Draft saved for item '%s' (draft_id=%d)", item.item_name, draft.id)

    except Exception as exc:
        log.error("Draft pipeline failed for item_id=%d: %s", item_id, exc, exc_info=True)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Routes: Inventory
# ---------------------------------------------------------------------------
@app.get("/api/inventory", response_model=list[InventoryItemOut], tags=["Inventory"])
def list_inventory(db: Session = Depends(get_db)):
    """Return all inventory items sorted by item name."""
    return db.query(InventoryItem).order_by(InventoryItem.item_name).all()


@app.post("/api/inventory", response_model=InventoryItemOut, status_code=201, tags=["Inventory"])
def add_inventory_item(
    payload: InventoryItemCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Add a new inventory item with supplier details."""
    existing = db.query(InventoryItem).filter(
        InventoryItem.item_name == payload.item_name
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Item '{payload.item_name}' already exists.")

    item = InventoryItem(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)

    # If added already below threshold, trigger draft immediately
    if item.is_low_stock:
        background_tasks.add_task(_run_draft_pipeline, item.id)

    return item


@app.put("/api/inventory/{item_id}", response_model=InventoryItemOut, tags=["Inventory"])
def update_inventory_item(
    item_id: int,
    payload: InventoryItemUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Update an inventory item's stock count or other fields.

    AUTO-TRIGGER: If the updated stock falls below minimum_threshold and
    no pending draft exists for this item, the ADK pipeline fires automatically
    in the background.
    """
    item = db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(item, key, value)
    item.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(item)

    # Check if auto-draft should trigger
    if item.is_low_stock:
        existing_draft = (
            db.query(EmailDraft)
            .filter(
                EmailDraft.item_id == item_id,
                EmailDraft.status == "pending_review",
            )
            .first()
        )
        if not existing_draft:
            log.info("⚠️  Low stock detected for '%s'. Triggering draft pipeline...", item.item_name)
            background_tasks.add_task(_run_draft_pipeline, item.id)

    return item


# ---------------------------------------------------------------------------
# Routes: Email Drafts
# ---------------------------------------------------------------------------
@app.get("/api/drafts", response_model=list[DraftOut], tags=["Drafts"])
def list_drafts(db: Session = Depends(get_db)):
    """Return all email drafts with status='pending_review'."""
    drafts = (
        db.query(EmailDraft)
        .filter(EmailDraft.status == "pending_review")
        .order_by(EmailDraft.created_at.desc())
        .all()
    )
    result = []
    for d in drafts:
        result.append(
            DraftOut(
                id=d.id,
                item_id=d.item_id,
                item_name=d.item.item_name,
                supplier_name=d.item.supplier_name,
                supplier_email=d.item.supplier_email,
                draft_text=d.draft_text,
                subject=d.subject,
                status=d.status,
                created_at=d.created_at,
            )
        )
    return result


@app.put("/api/drafts/{draft_id}", response_model=DraftOut, tags=["Drafts"])
def update_draft(
    draft_id: int,
    payload: DraftUpdate,
    db: Session = Depends(get_db),
):
    """Edit the draft text or subject before sending."""
    draft = db.query(EmailDraft).filter(EmailDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    if draft.status != "pending_review":
        raise HTTPException(status_code=400, detail="Only pending drafts can be edited.")

    if payload.draft_text is not None:
        draft.draft_text = payload.draft_text
    if payload.subject is not None:
        draft.subject = payload.subject
    draft.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(draft)

    return DraftOut(
        id=draft.id,
        item_id=draft.item_id,
        item_name=draft.item.item_name,
        supplier_name=draft.item.supplier_name,
        supplier_email=draft.item.supplier_email,
        draft_text=draft.draft_text,
        subject=draft.subject,
        status=draft.status,
        created_at=draft.created_at,
    )


@app.post("/api/drafts/{draft_id}/send", tags=["Drafts"])
def send_draft(draft_id: int, db: Session = Depends(get_db)):
    """
    Send the email draft via Gmail SMTP and mark it as 'sent'.
    Raises 503 if Gmail credentials are not configured in .env.
    """
    draft = db.query(EmailDraft).filter(EmailDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    if draft.status != "pending_review":
        raise HTTPException(status_code=400, detail="Only pending drafts can be sent.")

    supplier_email = draft.item.supplier_email
    if not supplier_email:
        raise HTTPException(status_code=400, detail="Supplier has no email address.")

    try:
        send_restock_email(
            to_address=supplier_email,
            subject=draft.subject,
            body=draft.draft_text,
        )
    except EnvironmentError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        log.error("SMTP send failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Failed to send email: {e}")

    draft.status = "sent"
    draft.updated_at = datetime.utcnow()
    db.commit()

    return {"message": f"Email sent to {supplier_email}", "draft_id": draft_id}


@app.delete("/api/drafts/{draft_id}", tags=["Drafts"])
def dismiss_draft(draft_id: int, db: Session = Depends(get_db)):
    """Dismiss a draft without sending it."""
    draft = db.query(EmailDraft).filter(EmailDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")

    draft.status = "dismissed"
    draft.updated_at = datetime.utcnow()
    db.commit()

    return {"message": "Draft dismissed.", "draft_id": draft_id}


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/api/health", tags=["Health"])
def health():
    return {"status": "ok", "service": "multi-agent-pantry-api"}
