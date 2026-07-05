"""
data/database.py

SQLAlchemy database layer for multi-agent-pantry.

Replaces the static INVENTORY list in inventory.py with a persistent SQLite
database. The MCP server, API, and orchestrator all share this single source
of truth.

Tables:
    inventory_items    — Ingredient stock levels + supplier contact details
    email_drafts       — AI-generated restock emails awaiting review / send.
                         Now SUPPLIER-SCOPED: one draft covers all low-stock
                         items from the same supplier.
    email_draft_items  — Join table: which items are covered by each draft.
                         Used to track the "requested" state per item.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

# ---------------------------------------------------------------------------
# Database location — stored alongside the data module, never in /tmp
# ---------------------------------------------------------------------------
_DB_DIR = Path(__file__).parent
DATABASE_URL = f"sqlite:///{_DB_DIR / 'pantry.db'}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # Required for SQLite + FastAPI
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# ORM Base
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    __allow_unmapped__ = True


# ---------------------------------------------------------------------------
# Model: InventoryItem
# ---------------------------------------------------------------------------
class InventoryItem(Base):
    """
    Represents a single ingredient tracked in the pantry.

    supplier_email is used by the email sender to address the restock order.
    """

    __tablename__ = "inventory_items"

    id: int = Column(Integer, primary_key=True, index=True)
    item_name: str = Column(String, nullable=False, unique=True, index=True)
    unit: str = Column(String, nullable=False)
    current_stock: float = Column(Float, nullable=False)
    minimum_threshold: float = Column(Float, nullable=False)
    reorder_quantity: float = Column(Float, nullable=False)
    supplier_name: str = Column(String, nullable=False, default="Unknown Supplier")
    supplier_email: str = Column(String, nullable=False, default="")
    created_at: datetime = Column(DateTime, default=datetime.utcnow)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # An item can appear in many draft coverage records over time
    draft_coverages: list["EmailDraftItem"] = relationship(
        "EmailDraftItem", back_populates="item", cascade="all, delete-orphan"
    )

    @property
    def is_low_stock(self) -> bool:
        return self.current_stock <= self.minimum_threshold


# ---------------------------------------------------------------------------
# Model: EmailDraft  (SUPPLIER-SCOPED)
# ---------------------------------------------------------------------------
class EmailDraft(Base):
    """
    An AI-drafted restock email generated when one or more items from the
    same supplier fall below their minimum threshold.

    Key design decisions
    --------------------
    - Supplier-scoped: one draft per supplier covers ALL their low-stock items.
    - The covered items are tracked in the `email_draft_items` join table.
    - When a draft is 'sent', the covered items enter a "requested" state —
      they are excluded from the NEXT draft for that supplier, unless their
      stock drops again after the sent timestamp.

    status:
        'pending_review' — Draft ready, waiting for user to send or dismiss.
        'sent'           — User clicked send; email dispatched via Gmail SMTP.
        'dismissed'      — User dismissed without sending.
    """

    __tablename__ = "email_drafts"

    id: int = Column(Integer, primary_key=True, index=True)

    # Supplier identity — no FK, denormalised for easy querying
    supplier_email: str = Column(String, nullable=False, index=True)
    supplier_name: str = Column(String, nullable=False, default="")

    draft_text: str = Column(Text, nullable=False)
    subject: str = Column(String, nullable=False, default="Restock Request")
    status: str = Column(String, nullable=False, default="pending_review")
    # pending_review | sent | dismissed

    created_at: datetime = Column(DateTime, default=datetime.utcnow)
    updated_at: datetime = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Items covered by this draft
    covered_items: list["EmailDraftItem"] = relationship(
        "EmailDraftItem", back_populates="draft", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Model: EmailDraftItem  (join table)
# ---------------------------------------------------------------------------
class EmailDraftItem(Base):
    """
    Records which inventory item is covered by which email draft.

    This is the source of truth for the "requested" state:
      - If the newest 'sent' draft for a supplier contains item_id X,
        then item X is considered "requested" (in flight to the supplier).
      - It is re-included in a new draft if its stock was updated AFTER
        that sent draft's updated_at timestamp.
    """

    __tablename__ = "email_draft_items"

    id: int = Column(Integer, primary_key=True, index=True)
    draft_id: int = Column(Integer, ForeignKey("email_drafts.id"), nullable=False, index=True)
    item_id: int = Column(Integer, ForeignKey("inventory_items.id"), nullable=False, index=True)

    draft: "EmailDraft" = relationship("EmailDraft", back_populates="covered_items")
    item: "InventoryItem" = relationship("InventoryItem", back_populates="draft_coverages")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_db():
    """FastAPI dependency that yields a database session and closes it after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables if they don't already exist."""
    Base.metadata.create_all(bind=engine)


def seed_database(db: Session) -> None:
    """
    Pre-populate the inventory table with the original 8 mock items if the
    table is empty. Idempotent — safe to call on every startup.
    """
    if db.query(InventoryItem).count() > 0:
        return  # Already seeded

    seed_data = [
        {
            "item_name": "Chicken Breast",
            "unit": "kg",
            "current_stock": 4.0,
            "minimum_threshold": 10.0,
            "reorder_quantity": 25.0,
            "supplier_name": "Farm Fresh Meats",
            "supplier_email": "orders@farmfreshmeats.com",
        },
        {
            "item_name": "Olive Oil",
            "unit": "liters",
            "current_stock": 1.5,
            "minimum_threshold": 5.0,
            "reorder_quantity": 15.0,
            "supplier_name": "Mediterranean Imports",
            "supplier_email": "supply@medimports.com",
        },
        {
            "item_name": "Roma Tomatoes",
            "unit": "kg",
            "current_stock": 8.0,
            "minimum_threshold": 12.0,
            "reorder_quantity": 30.0,
            "supplier_name": "Green Valley Produce",
            "supplier_email": "orders@greenvalley.com",
        },
        {
            "item_name": "All-Purpose Flour",
            "unit": "kg",
            "current_stock": 20.0,
            "minimum_threshold": 15.0,
            "reorder_quantity": 50.0,
            "supplier_name": "Sunrise Mills",
            "supplier_email": "bulk@sunrisemills.com",
        },
        {
            "item_name": "Heavy Cream",
            "unit": "liters",
            "current_stock": 2.0,
            "minimum_threshold": 6.0,
            "reorder_quantity": 12.0,
            "supplier_name": "Dairy Direct",
            "supplier_email": "orders@dairydirect.com",
        },
        {
            "item_name": "Parmesan Cheese",
            "unit": "kg",
            "current_stock": 0.5,
            "minimum_threshold": 3.0,
            "reorder_quantity": 8.0,
            "supplier_name": "Artisan Cheese Co",
            "supplier_email": "wholesale@artisancheese.com",
        },
        {
            "item_name": "Garlic",
            "unit": "kg",
            "current_stock": 1.0,
            "minimum_threshold": 2.0,
            "reorder_quantity": 5.0,
            "supplier_name": "Green Valley Produce",
            "supplier_email": "orders@greenvalley.com",
        },
        {
            "item_name": "Basmati Rice",
            "unit": "kg",
            "current_stock": 18.0,
            "minimum_threshold": 10.0,
            "reorder_quantity": 40.0,
            "supplier_name": "Sunrise Mills",
            "supplier_email": "bulk@sunrisemills.com",
        },
    ]

    for record in seed_data:
        db.add(InventoryItem(**record))

    db.commit()
