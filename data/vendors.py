"""
data/vendors.py

Mock vendor / supplier contact details for La Bella Cucina's primary supplier.

In production this would be fetched from a supplier management database.
The `required_delivery_date` field is set statically here for reproducibility
during demos; the orchestrator can override it with today + N days at runtime.
"""

from typing import TypedDict


class VendorRecord(TypedDict):
    """Shape of a vendor contact record."""

    vendor_name: str
    contact_name: str
    email: str
    phone: str
    account_number: str        # Our account reference with the supplier
    restaurant_name: str
    restaurant_contact: str    # Name to sign the email with
    required_delivery_date: str  # ISO 8601 format: YYYY-MM-DD
    payment_terms: str


# ---------------------------------------------------------------------------
# Primary supplier for La Bella Cucina
# ---------------------------------------------------------------------------
VENDOR: VendorRecord = {
    "vendor_name": "FreshFields Wholesale Distributors",
    "contact_name": "Marcus Thorne",
    "email": "marcus.thorne@freshfields-wholesale.com",
    "phone": "+1-800-555-0192",
    "account_number": "FF-78432",
    "restaurant_name": "La Bella Cucina",
    "restaurant_contact": "Chef Sofia Marchetti",
    # Delivery expected within 3 days of order — set statically for demo runs
    "required_delivery_date": "2026-07-05",
    "payment_terms": "Net-30",
}
