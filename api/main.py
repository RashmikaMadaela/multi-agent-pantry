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

AUTO-TRIGGER LOGIC (SUPPLIER-GROUPED)
--------------------------------------
When PUT /api/inventory/{id} is called and the new stock value is below
the minimum_threshold:

1. All low-stock items sharing the SAME supplier_email are collected.
2. Items already covered by a 'sent' draft are excluded UNLESS the item's
   stock was updated after that sent draft was dispatched (meaning it went
   low again — a new order is needed).
3. If the filtered list is non-empty:
   a. Any existing 'pending_review' draft for that supplier is deleted
      (replaced by the new combined draft).
   b. The ADK pipeline runs with the combined shortage report.
   c. The resulting draft is saved and linked to all covered items.
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
    EmailDraftItem,
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


class DraftItemOut(BaseModel):
    """A single item covered by a supplier draft."""
    item_id: int
    item_name: str
    unit: str
    current_stock: float
    reorder_quantity: float


class DraftOut(BaseModel):
    id: int
    supplier_name: str
    supplier_email: str
    items: list[DraftItemOut]   # ALL items covered by this draft
    draft_text: str
    subject: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DraftUpdate(BaseModel):
    draft_text: Optional[str] = None
    subject: Optional[str] = None


# ---------------------------------------------------------------------------
# Helper: build DraftOut from an EmailDraft ORM object
# ---------------------------------------------------------------------------
def _draft_to_out(draft: EmailDraft) -> DraftOut:
    items = [
        DraftItemOut(
            item_id=ci.item.id,
            item_name=ci.item.item_name,
            unit=ci.item.unit,
            current_stock=ci.item.current_stock,
            reorder_quantity=ci.item.reorder_quantity,
        )
        for ci in draft.covered_items
    ]
    return DraftOut(
        id=draft.id,
        supplier_name=draft.supplier_name,
        supplier_email=draft.supplier_email,
        items=items,
        draft_text=draft.draft_text,
        subject=draft.subject,
        status=draft.status,
        created_at=draft.created_at,
    )


# ---------------------------------------------------------------------------
# Helper: determine which low-stock items for a supplier need a new email
# ---------------------------------------------------------------------------
def _get_items_needing_order(db: Session, supplier_email: str) -> list[InventoryItem]:
    """
    Returns low-stock items for a supplier that are NOT already in a
    'requested' state (i.e. covered by a sent draft that was sent AFTER
    the item last went low).

    Rules:
    - Start with all items for this supplier that are currently low-stock.
    - Find the most recent 'sent' draft for this supplier (if any).
    - Exclude items covered by that sent draft UNLESS the item's updated_at
      is AFTER the sent draft's updated_at (meaning stock changed again since
      the order was sent — the item went low a second time).
    """
    # All low-stock items for this supplier
    low_stock_items: list[InventoryItem] = (
        db.query(InventoryItem)
        .filter(
            InventoryItem.supplier_email == supplier_email,
            InventoryItem.current_stock <= InventoryItem.minimum_threshold,
        )
        .all()
    )

    if not low_stock_items:
        return []

    # Find the most recent SENT draft for this supplier
    sent_draft: EmailDraft | None = (
        db.query(EmailDraft)
        .filter(
            EmailDraft.supplier_email == supplier_email,
            EmailDraft.status == "sent",
        )
        .order_by(EmailDraft.updated_at.desc())
        .first()
    )

    if sent_draft is None:
        # No sent draft → all low-stock items need ordering
        return low_stock_items

    # Build set of item_ids that were covered by the sent draft
    sent_item_ids: set[int] = {ci.item_id for ci in sent_draft.covered_items}
    sent_at: datetime = sent_draft.updated_at

    eligible = []
    for item in low_stock_items:
        if item.id not in sent_item_ids:
            # Not previously requested → include
            eligible.append(item)
        elif item.updated_at is not None and item.updated_at > sent_at:
            # Stock was updated AFTER the order was sent → went low again → include
            log.info(
                "Item '%s' went low again after sent draft (item.updated_at=%s > sent_at=%s)",
                item.item_name, item.updated_at, sent_at,
            )
            eligible.append(item)
        else:
            log.info(
                "Item '%s' is already in 'requested' state — skipping for new draft.",
                item.item_name,
            )

    return eligible


# ---------------------------------------------------------------------------
# Background task: run the full ADK pipeline for a supplier group
# ---------------------------------------------------------------------------
async def _run_draft_pipeline_for_supplier(supplier_email: str) -> None:
    """
    Runs the full Auditor → Procurement → Evaluator pipeline for all
    eligible low-stock items belonging to a single supplier, then saves
    the resulting combined draft to the database.

    Steps:
    1. Collect all low-stock items for supplier_email, excluding those
       already 'requested' (covered by a sent draft and not re-lowered).
    2. If nothing to order → exit early.
    3. Delete any existing 'pending_review' draft for this supplier
       (it will be replaced with the new combined draft).
    4. Run the ADK pipeline with the combined shortage report.
    5. Save the draft and link it to all covered items via EmailDraftItem.
    """
    from orchestrator import orchestrate

    db = next(get_db())
    try:
        # ── 1. Determine which items need ordering ───────────────────────────
        items_to_order = _get_items_needing_order(db, supplier_email)

        if not items_to_order:
            log.info(
                "No eligible items for supplier '%s' — all already requested or stocked.",
                supplier_email,
            )
            return

        item_names = [i.item_name for i in items_to_order]
        supplier_name = items_to_order[0].supplier_name
        log.info(
            "🤖 Starting ADK pipeline for supplier '%s' covering items: %s",
            supplier_email, item_names,
        )

        # ── 2. Remove stale pending_review draft for this supplier ───────────
        stale_draft: EmailDraft | None = (
            db.query(EmailDraft)
            .filter(
                EmailDraft.supplier_email == supplier_email,
                EmailDraft.status == "pending_review",
            )
            .first()
        )
        if stale_draft:
            log.info(
                "Replacing stale pending_review draft (id=%d) for supplier '%s'.",
                stale_draft.id, supplier_email,
            )
            db.delete(stale_draft)
            db.commit()

        # ── 3. Build vendor_details from the first item's supplier info ──────
        # All items in the group share the same supplier_email/supplier_name.
        # For other fields we use sensible defaults (the restaurant always
        # uses Net-30 / 48-hour urgency; contact info is DB-stored per item).
        from datetime import timedelta
        delivery_date = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")

        vendor_details = {
            "vendor_name": supplier_name,
            "contact_name": supplier_name,   # best available; supplier can be updated in a real system
            "email": supplier_email,
            "account_number": "N/A",         # could be stored per-supplier in a future enhancement
            "restaurant_name": "La Bella Cucina",
            "restaurant_contact": "Chef Sofia Marchetti",
            "required_delivery_date": delivery_date,
            "payment_terms": "Net-30",
        }

        # ── 4. Run the ADK pipeline ─────────────────────────────────────────
        email_text = await orchestrate(
            target_item_names=item_names,
            vendor_details=vendor_details,
        )

        if not email_text:
            log.warning("ADK pipeline returned empty draft for supplier '%s'", supplier_email)
            return

        # ── 5. Extract subject ──────────────────────────────────────────────
        lines = email_text.strip().splitlines()
        if len(item_names) == 1:
            subject = f"Restock Request: {item_names[0]}"
        else:
            subject = f"Restock Request: {', '.join(item_names[:2])}" + (
                f" +{len(item_names)-2} more" if len(item_names) > 2 else ""
            )
        for line in lines:
            if line.lower().startswith("subject:"):
                subject = line.split(":", 1)[1].strip()
                break

        # ── 6. Save the supplier-scoped draft ──────────────────────────────
        draft = EmailDraft(
            supplier_email=supplier_email,
            supplier_name=supplier_name,
            draft_text=email_text,
            subject=subject,
            status="pending_review",
        )
        db.add(draft)
        db.flush()  # get draft.id before adding children

        for item in items_to_order:
            db.add(EmailDraftItem(draft_id=draft.id, item_id=item.id))

        db.commit()
        log.info(
            "✅ Combined draft saved (draft_id=%d) for supplier '%s' covering %d item(s): %s",
            draft.id, supplier_email, len(items_to_order), item_names,
        )

    except Exception as exc:
        log.error(
            "Draft pipeline failed for supplier '%s': %s", supplier_email, exc, exc_info=True
        )
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

    # If added already below threshold, trigger grouped draft for this supplier
    if item.is_low_stock:
        background_tasks.add_task(_run_draft_pipeline_for_supplier, item.supplier_email)

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

    AUTO-TRIGGER: If the updated stock falls below minimum_threshold, the
    ADK pipeline fires in the background for the ENTIRE supplier group.
    Items already in a 'requested' state (sent draft) are excluded unless
    they went low again. Any stale pending_review draft is replaced.
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
        supplier_email = item.supplier_email

        # Check if there are eligible items to order for this supplier
        eligible = _get_items_needing_order(db, supplier_email)
        if eligible:
            log.info(
                "⚠️  Low stock detected. Triggering grouped draft for supplier '%s' "
                "with %d eligible item(s).",
                supplier_email, len(eligible),
            )
            background_tasks.add_task(_run_draft_pipeline_for_supplier, supplier_email)
        else:
            log.info(
                "Low stock for '%s' but all items already requested — no new draft triggered.",
                item.item_name,
            )

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
    return [_draft_to_out(d) for d in drafts]


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

    return _draft_to_out(draft)


@app.post("/api/drafts/{draft_id}/send", tags=["Drafts"])
def send_draft(draft_id: int, db: Session = Depends(get_db)):
    """
    Send the email draft via Gmail SMTP and mark it as 'sent'.
    All items covered by this draft enter the 'requested' state automatically.
    Raises 503 if Gmail credentials are not configured in .env.
    """
    draft = db.query(EmailDraft).filter(EmailDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    if draft.status != "pending_review":
        raise HTTPException(status_code=400, detail="Only pending drafts can be sent.")

    supplier_email = draft.supplier_email
    if not supplier_email:
        raise HTTPException(status_code=400, detail="Draft has no supplier email address.")

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

    item_names = [ci.item.item_name for ci in draft.covered_items]
    log.info(
        "✅ Email sent to %s covering items: %s — marked as 'requested'.",
        supplier_email, item_names,
    )

    return {
        "message": f"Email sent to {supplier_email}",
        "draft_id": draft_id,
        "items_requested": item_names,
    }


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
