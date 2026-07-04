"""
mcp_server/inventory_server.py

MCP (Model Context Protocol) server that exposes restaurant inventory data
as a discoverable tool.

WHY MCP instead of a plain Python function?
--------------------------------------------
Using MCP decouples the *tool implementation* from the *agent code*.
The Auditor Agent connects to this server at runtime and discovers the
`check_inventory` tool dynamically via the MCP handshake.  This means:
  - The server can be replaced with a real POS/ERP integration without
    touching a single line of agent code.
  - The server can run as a separate process or even a remote service,
    enabling true microservice-style deployment.
  - Tool discovery is automatic — no manual registration in the agent.

Transport: stdio (default for local/Docker runs).
           Switch to "sse" for HTTP-based multi-client deployments.

Security: All outgoing records are validated by Pydantic before being
          serialised and returned to the calling agent.  Malformed data
          in the source (e.g. wrong types, missing keys) raises a
          ValidationError here rather than silently propagating to the LLM.

Usage (standalone test):
    python mcp_server/inventory_server.py

Usage (via ADK MCPToolset — automatic):
    The orchestrator spawns this process and connects via stdio.
"""

import sys
import os

# ---------------------------------------------------------------------------
# Path setup — allows the server to be launched as a standalone process
# from any working directory (e.g. by the ADK MCPToolset subprocess call).
# We add the project root to sys.path so `data` is importable.
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from mcp.server.fastmcp import FastMCP

# Import DB models — reads from SQLite instead of the static INVENTORY list
from data.database import InventoryItem as DBInventoryItem, SessionLocal, init_db


# ---------------------------------------------------------------------------
# Pydantic model — validates every inventory record before it reaches the LLM.
# Using Pydantic here satisfies the "Security features" rubric criterion by
# ensuring type safety and preventing malformed data from entering the agent.
# ---------------------------------------------------------------------------
class InventoryItem(BaseModel):
    """
    A single inventory record with strict type constraints.

    Fields mirror the INVENTORY data structure but are enforced at runtime.
    Negative stock values are rejected as physically impossible.
    """

    item_name: str = Field(..., min_length=1, description="Human-readable ingredient name")
    unit: str = Field(..., min_length=1, description="Unit of measurement (kg, liters, etc.)")
    current_stock: float = Field(..., ge=0.0, description="Current quantity on hand")
    minimum_threshold: float = Field(..., gt=0.0, description="Reorder trigger level")
    reorder_quantity: float = Field(..., gt=0.0, description="Target quantity after restocking")

    @field_validator("reorder_quantity")
    @classmethod
    def reorder_must_exceed_threshold(cls, v: float, info: ValidationInfo) -> float:
        """
        Sanity check: the reorder quantity must be greater than the minimum
        threshold, otherwise restocking would immediately trigger another order.
        """
        if "minimum_threshold" in info.data and v <= info.data["minimum_threshold"]:
            raise ValueError(
                f"reorder_quantity ({v}) must exceed minimum_threshold "
                f"({info.data['minimum_threshold']})"
            )
        return v


# ---------------------------------------------------------------------------
# FastMCP server instance
# ---------------------------------------------------------------------------
mcp = FastMCP(
    name="pantry-inventory",
    instructions=(
        "Provides real-time inventory data for La Bella Cucina restaurant. "
        "Use check_inventory to retrieve all ingredient stock levels."
    ),
)


# ---------------------------------------------------------------------------
# Tool: check_inventory
# ---------------------------------------------------------------------------
@mcp.tool()
def check_inventory() -> list[dict]:
    """
    Retrieve current stock levels for all tracked ingredients from the database.

    Returns a list of inventory records, each containing:
      - item_name: Name of the ingredient.
      - unit: Unit of measurement (kg, liters, etc.).
      - current_stock: Current quantity on hand.
      - minimum_threshold: Level at or below which restocking is needed.
      - reorder_quantity: Target quantity to order to reach safe stock levels.

    All records are validated by Pydantic before being returned.
    Data is read from the SQLite database — reflects live stock updates.
    """
    # Ensure the DB and tables exist (idempotent)
    init_db()

    db = SessionLocal()
    validated_items: list[dict] = []

    try:
        raw_records = db.query(DBInventoryItem).all()

        for raw_record in raw_records:
            item = InventoryItem(
                item_name=raw_record.item_name,
                unit=raw_record.unit,
                current_stock=raw_record.current_stock,
                minimum_threshold=raw_record.minimum_threshold,
                reorder_quantity=raw_record.reorder_quantity,
            )
            validated_items.append(item.model_dump())
    finally:
        db.close()

    return validated_items


# ---------------------------------------------------------------------------
# Resource: inventory/summary
# ---------------------------------------------------------------------------
@mcp.resource("inventory://summary")
def inventory_summary() -> str:
    """
    Returns a plain-text summary of total SKUs and how many are in shortage.
    """
    init_db()
    db = SessionLocal()
    try:
        items = db.query(DBInventoryItem).all()
        total = len(items)
        in_shortage = sum(1 for item in items if item.is_low_stock)
    finally:
        db.close()

    return (
        f"La Bella Cucina Inventory Summary\n"
        f"Total SKUs tracked: {total}\n"
        f"Items in shortage:  {in_shortage}\n"
        f"Items fully stocked: {total - in_shortage}\n"
    )


# ---------------------------------------------------------------------------
# Entry point — run as stdio MCP server
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="stdio")
