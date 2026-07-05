"""
agents/procurement.py

Defines the Procurement Agent for the multi-agent-pantry pipeline.

Role: Supplier email drafter — the second agent in the pipeline.

WHY THIS AGENT EXISTS
---------------------
Drafting a restock email is templated but non-trivial: it must correctly
reference every shortage item with exact quantities, address the supplier
by name, use the right account number, and communicate urgency clearly.
An LLM handles this far better than a hand-crafted template because it
can vary phrasing naturally while still hitting all required data points.

HOW IT WORKS
------------
1. The orchestrator calls `build_procurement_agent()` once.
2. On the first invocation the agent receives the shortage report and vendor
   details injected into the user message.
3. On retry invocations (after an Evaluator FAIL) the orchestrator prepends
   the Evaluator's critique to the message so the agent can address gaps.
4. The final email draft is stored in session state under `email_draft`.

RETRY DESIGN
------------
We intentionally do NOT implement retries inside this agent — that is the
Evaluator's job.  This separation keeps each agent's prompt focused and
makes the retry count easy to control from the orchestrator.

DYNAMIC VENDOR DETAILS
-----------------------
Vendor details are now passed per-invocation (from the DB record for the
specific supplier) rather than being read from the static VENDOR dict.
This allows the pipeline to handle multiple suppliers correctly.

SECURITY NOTE
-------------
Vendor details (name, account number, email) are passed as structured text
from our own data module — never from external/user input — so there is no
prompt-injection risk here.
"""

import os

from google.adk.agents import LlmAgent

# Allow overriding the model from the environment — useful when one model's
# free-tier quota is exhausted (e.g. swap to gemini-2.0-flash-lite).
_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")


# ---------------------------------------------------------------------------
# System prompt — static instructions baked into the agent
# ---------------------------------------------------------------------------
_PROCUREMENT_SYSTEM_PROMPT = """
You are the procurement officer at La Bella Cucina restaurant.

Your task is to draft a professional restock request email to the supplier.

The email MUST contain ALL of the following elements — missing any will cause rejection:
  1. A greeting addressing the supplier contact by their first name.
  2. The restaurant name and your name (the sender).
  3. The account/reference number.
  4. A numbered list of EVERY shortage item with:
       - The EXACT quantity to order (numeric value + unit, e.g. "21 kg", "13.5 liters")
  5. A specific delivery date OR an explicit urgency statement (e.g. "within 48 hours").
  6. Payment terms.
  7. A professional closing.

If a CRITIQUE is provided, read it carefully and fix EVERY issue raised before rewriting.
Do not acknowledge the critique in the email itself — just produce the corrected email.

Output ONLY the email text. No preamble, no commentary outside the email.
""".strip()


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------
def build_procurement_agent() -> LlmAgent:
    """
    Constructs and returns the Procurement LlmAgent.

    The agent has no tools — its entire task is text generation based on
    the shortage report and vendor details provided in the user message.
    This keeps the agent fast and deterministic in structure.

    Returns:
        A configured LlmAgent ready to be invoked by the orchestrator.
    """
    agent = LlmAgent(
        name="ProcurementAgent",
        model=_MODEL,
        instruction=_PROCUREMENT_SYSTEM_PROMPT,
        # No tools needed — this agent only generates text
        tools=[],
        # Store the latest draft in session state for the Evaluator to read
        output_key="email_draft",
    )
    return agent


# ---------------------------------------------------------------------------
# Message builder — constructs the user turn content for each invocation
# ---------------------------------------------------------------------------
def build_procurement_message(
    shortage_report: str,
    vendor_details: dict,
    critique: str | None = None,
) -> str:
    """
    Builds the user-turn message sent to the Procurement Agent.

    On first attempt `critique` is None.
    On retries `critique` contains the Evaluator's specific feedback.

    Args:
        shortage_report: Plain-text output from the Auditor Agent.
        vendor_details:  Dict with keys: vendor_name, contact_name, email,
                         account_number, restaurant_name, restaurant_contact,
                         required_delivery_date, payment_terms.
        critique:        Optional feedback from the Evaluator Agent on a failed draft.

    Returns:
        A formatted string that becomes the user message for this invocation.
    """
    # Vendor context injected here (not in the system prompt) so it reads
    # naturally as "data provided to you for this specific task".
    vendor_context = (
        f"Supplier Name: {vendor_details.get('vendor_name', 'N/A')}\n"
        f"Supplier Contact: {vendor_details.get('contact_name', 'N/A')}\n"
        f"Supplier Email: {vendor_details.get('email', 'N/A')}\n"
        f"Our Account Number: {vendor_details.get('account_number', 'N/A')}\n"
        f"Restaurant: {vendor_details.get('restaurant_name', 'La Bella Cucina')}\n"
        f"Sender Name: {vendor_details.get('restaurant_contact', 'Procurement Team')}\n"
        f"Required Delivery Date: {vendor_details.get('required_delivery_date', 'As soon as possible')}\n"
        f"Payment Terms: {vendor_details.get('payment_terms', 'Net-30')}\n"
    )

    parts = [
        "=== VENDOR DETAILS ===",
        vendor_context,
        "=== SHORTAGE REPORT ===",
        shortage_report,
    ]

    if critique:
        # Prepend critique prominently so the agent addresses it first
        parts = [
            "=== EVALUATOR CRITIQUE (MUST BE FIXED) ===",
            critique,
            "",
        ] + parts

    return "\n".join(parts)
