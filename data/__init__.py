"""
data/__init__.py

Package marker for the data layer.
Exports INVENTORY and VENDOR so agents and the MCP server
can import them from a single, well-known location.
"""

from data.inventory import INVENTORY
from data.vendors import VENDOR

__all__ = ["INVENTORY", "VENDOR"]
