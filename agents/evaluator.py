"""
agents/evaluator.py

Defines the Evaluator Agent for the multi-agent-pantry pipeline.

Role: Email quality critic — the third agent in the pipeline.

WHY THIS AGENT EXISTS
---------------------
Having the Procurement Agent draft an email and then immediately send it
introduces the risk of missing items or vague quantities (e.g. "some olive
oil" instead of "13.5 liters").  A dedicated Evaluator enforces a strict
quality gate, making the system self-correcting.

This pattern — a "critic" agent that checks another agent's output — is a
key multi-agent design technique taught in the course.  It demonstrates that
agents don't have to be interchangeable; specialisation improves overall
output quality more than a single general-purpose agent would.

HOW IT WORKS
------------
1. The orchestrator calls `build_evaluator_agent()` once.
2. For each draft, it passes the email text + original shortage report as
   the user message.
3. The agent responds in a strict VERDICT / CRITIQUE format.
4. `parse_evaluation_result()` extracts the verdict and critique text.
5. The orchestrator decides whether to loop or accept based on the verdict.

EVALUATION CRITERIA (all three must pass)
------------------------------------------
  1. Item completeness — every shortage item appears in the email.
  2. Quantity specificity — each item has an exact number + unit.
  3. Delivery urgency — a specific date OR explicit urgency phrasing.

WHY STRUCTURED OUTPUT FORMAT?
------------------------------
We enforce a rigid "VERDICT: PASS/FAIL" prefix rather than free-form text
so the orchestrator can parse the result with simple string operations —
no JSON parsing, no regex fragility.  The format is defined in both the
system prompt and validated in `parse_evaluation_result()`.
"""

from __future__ import annotations

import dataclasses

import os

from google.adk.agents import LlmAgent

# Allow overriding the model from the environment — useful when one model's
# free-tier quota is exhausted (e.g. swap to gemini-2.0-flash-lite).
_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")


# ---------------------------------------------------------------------------
# Result dataclass — typed container for the Evaluator's decision
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class EvaluationResult:
    """
    Typed result returned by the Evaluator Agent after reviewing a draft.

    Attributes:
        passed:  True if the email meets all quality criteria.
        verdict: Raw verdict string ("PASS" or "FAIL").
        critique: Specific feedback on missing elements (empty string if PASS).
        raw_response: The full unprocessed agent response for logging/debugging.
    """

    passed: bool
    verdict: str
    critique: str
    raw_response: str


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
_EVALUATOR_SYSTEM_PROMPT = """
You are a strict procurement quality evaluator at La Bella Cucina restaurant.

You will be given:
  - A restock request email draft.
  - The original shortage report that the email should address.

Your job is to evaluate the email against THREE criteria:

  CRITERION 1 — Item Completeness:
    Every item listed in the shortage report MUST appear in the email body.

  CRITERION 2 — Quantity Specificity:
    Each item MUST have an exact numeric quantity with its unit
    (e.g. "21 kg", "13.5 liters"). Vague language like "some" or "a few" fails.

  CRITERION 3 — Delivery Urgency:
    The email MUST state either a specific delivery date (e.g. "by July 5th")
    OR an explicit urgency level (e.g. "within 48 hours", "urgent delivery required").

RESPONSE FORMAT — you must respond in exactly this format, nothing else:
  VERDICT: PASS
  CRITIQUE:

  OR

  VERDICT: FAIL
  CRITIQUE: <specific description of every missing element>

Rules:
  - PASS only if ALL three criteria are fully satisfied.
  - FAIL if even one criterion is partially or fully missing.
  - The CRITIQUE must name the specific items or phrases that are missing.
  - Do not add any text before "VERDICT:" or after the CRITIQUE line.
""".strip()


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------
def build_evaluator_agent() -> LlmAgent:
    """
    Constructs and returns the Evaluator LlmAgent.

    The agent uses no tools — its entire task is structured text analysis.
    The strict output format (VERDICT / CRITIQUE) allows the orchestrator
    to parse results reliably with plain string operations.

    Returns:
        A configured LlmAgent ready to be invoked by the orchestrator.
    """
    agent = LlmAgent(
        name="EvaluatorAgent",
        model=_MODEL,
        instruction=_EVALUATOR_SYSTEM_PROMPT,
        tools=[],
        # Store the evaluation result in session state for logging
        output_key="evaluation_result",
    )
    return agent


# ---------------------------------------------------------------------------
# Message builder
# ---------------------------------------------------------------------------
def build_evaluator_message(email_draft: str, shortage_report: str) -> str:
    """
    Builds the user-turn message sent to the Evaluator Agent.

    Args:
        email_draft: The email produced by the Procurement Agent.
        shortage_report: The original ShortageReport from the Auditor Agent.
                         Used as the ground-truth list of items to check against.

    Returns:
        A formatted string containing both documents for the evaluator to compare.
    """
    return (
        "=== SHORTAGE REPORT (ground truth) ===\n"
        f"{shortage_report}\n\n"
        "=== EMAIL DRAFT (to evaluate) ===\n"
        f"{email_draft}"
    )


# ---------------------------------------------------------------------------
# Result parser
# ---------------------------------------------------------------------------
def parse_evaluation_result(raw_response: str) -> EvaluationResult:
    """
    Parses the Evaluator Agent's raw text response into an EvaluationResult.

    Expected format:
        VERDICT: PASS
        CRITIQUE:

        or

        VERDICT: FAIL
        CRITIQUE: <specific feedback text>

    Design decision: we use simple string parsing rather than JSON or regex
    because the format is deliberately minimal — one prefix per field.
    If the agent fails to follow the format, we default to FAIL with the
    full response as the critique, which triggers a retry and surfaces the
    issue in logs.

    Args:
        raw_response: The raw text response from the Evaluator LlmAgent.

    Returns:
        An EvaluationResult with parsed verdict and critique.
    """
    lines = raw_response.strip().splitlines()

    verdict = "FAIL"  # Default to FAIL if parsing fails — safe fallback
    critique_lines: list[str] = []
    reading_critique = False

    for line in lines:
        stripped = line.strip()

        if stripped.upper().startswith("VERDICT:"):
            # Extract "PASS" or "FAIL" from "VERDICT: PASS"
            verdict_value = stripped.split(":", 1)[1].strip().upper()
            if verdict_value in ("PASS", "FAIL"):
                verdict = verdict_value

        elif stripped.upper().startswith("CRITIQUE:"):
            reading_critique = True
            # Capture inline critique text if present: "CRITIQUE: Missing item X"
            inline = stripped.split(":", 1)[1].strip()
            if inline:
                critique_lines.append(inline)

        elif reading_critique and stripped:
            # Capture multi-line critique content
            critique_lines.append(stripped)

    critique = " ".join(critique_lines).strip()

    return EvaluationResult(
        passed=(verdict == "PASS"),
        verdict=verdict,
        critique=critique,
        raw_response=raw_response,
    )
