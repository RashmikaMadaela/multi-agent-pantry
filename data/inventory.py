"""
data/inventory.py

Mock inventory dataset for La Bella Cucina restaurant.

In a production deployment this module would be replaced by a live query
against a POS system (e.g. Toast, Square) or an ERP API.  By keeping the
data isolated here, the MCP server and agents remain unchanged — only this
file needs to be swapped.

Design note: we intentionally include two items (All-Purpose Flour, Basmati
Rice) that are ABOVE their minimum threshold.  This lets the Auditor Agent
demonstrate that it correctly filters rather than blindly restocking everything.
"""

from typing import TypedDict


class InventoryRecord(TypedDict):
    """Shape of a single inventory record — used for type-checking throughout."""

    item_name: str
    unit: str
    current_stock: float      # Current quantity on hand
    minimum_threshold: float  # Reorder is triggered at or below this level
    reorder_quantity: float   # Target quantity after restocking


# ---------------------------------------------------------------------------
# Mock stock data — 8 SKUs, 6 in shortage, 2 fully stocked
# ---------------------------------------------------------------------------
INVENTORY: list[InventoryRecord] = [
    {
        "item_name": "Chicken Breast",
        "unit": "kg",
        "current_stock": 4.0,
        "minimum_threshold": 10.0,
        "reorder_quantity": 25.0,
    },
    {
        "item_name": "Olive Oil",
        "unit": "liters",
        "current_stock": 1.5,
        "minimum_threshold": 5.0,
        "reorder_quantity": 15.0,
    },
    {
        "item_name": "Roma Tomatoes",
        "unit": "kg",
        "current_stock": 8.0,
        "minimum_threshold": 12.0,
        "reorder_quantity": 30.0,
    },
    {
        # All-Purpose Flour is ABOVE threshold — should NOT appear in ShortageReport
        "item_name": "All-Purpose Flour",
        "unit": "kg",
        "current_stock": 20.0,
        "minimum_threshold": 15.0,
        "reorder_quantity": 50.0,
    },
    {
        "item_name": "Heavy Cream",
        "unit": "liters",
        "current_stock": 2.0,
        "minimum_threshold": 6.0,
        "reorder_quantity": 12.0,
    },
    {
        "item_name": "Parmesan Cheese",
        "unit": "kg",
        "current_stock": 0.5,
        "minimum_threshold": 3.0,
        "reorder_quantity": 8.0,
    },
    {
        "item_name": "Garlic",
        "unit": "kg",
        "current_stock": 1.0,
        "minimum_threshold": 2.0,
        "reorder_quantity": 5.0,
    },
    {
        # Basmati Rice is ABOVE threshold — should NOT appear in ShortageReport
        "item_name": "Basmati Rice",
        "unit": "kg",
        "current_stock": 18.0,
        "minimum_threshold": 10.0,
        "reorder_quantity": 40.0,
    },
]
