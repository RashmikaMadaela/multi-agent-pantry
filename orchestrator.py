"""
orchestrator.py

The central coordinator for the multi-agent-pantry pipeline.

WHAT THIS MODULE DOES
---------------------
It wires together the three ADK LlmAgents in the correct sequence and
implements the Evaluator → Procurement retry loop:

  1. AuditorAgent    → produces ShortageReport
  2. ProcurementAgent → drafts restock email
  3. EvaluatorAgent  → critiques the draft
     - PASS → pipeline complete
     - FAIL → sends critique back to ProcurementAgent (up to MAX_ATTEMPTS)

WHY AN ASYNC ORCHESTRATOR?
--------------------------
Google ADK's Runner.run_async() is a native async generator.  Using asyncio
throughout avoids blocking the event loop and is required for the McpToolset
to manage its subprocess connection correctly (it uses asyncio under the hood).

WHY NOT USE ADK'S BUILT-IN SequentialAgent?
--------------------------------------------
SequentialAgent is ideal for fixed linear pipelines.  Our pipeline has a
*conditional loop* (the Evaluator retry).  Implementing that with a
SequentialAgent would require a LoopAgent or custom callbacks, which is more
complex than a clean explicit async loop.  The approach here is more readable,
more testable, and makes the retry logic self-documenting.

SESSION DESIGN
--------------
Each agent run gets its own Runner + Session so their state is isolated.
We use a shared `InMemorySessionService` (in-process, no I/O) which is
appropriate for a single-run CLI tool.  The output_key mechanism on each
LlmAgent writes the agent's final text to session.state, which we read back
after each run to pass data downstream.

SECURITY
--------
- API key is consumed by the Runner/genai client via the GOOGLE_API_KEY
  environment variable — it is never passed as a function argument here.
- No user-controlled text reaches any agent without going through the
  message-builder functions defined in the agent modules.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path

from google.adk import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agents.auditor import build_auditor_agent
from agents.procurement import build_procurement_agent, build_procurement_message
from agents.evaluator import (
    build_evaluator_agent,
    build_evaluator_message,
    parse_evaluation_result,
    EvaluationResult,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum number of Procurement drafts before we accept the best available
MAX_PROCUREMENT_ATTEMPTS: int = 3

# Application name used by the ADK session service
APP_NAME: str = "multi-agent-pantry"

# Directory where the final email is saved
OUTPUT_DIR: Path = Path(__file__).parent / "output"

# ---------------------------------------------------------------------------
# Logging — structured log lines make it easy to trace each agent turn
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("orchestrator")


# ---------------------------------------------------------------------------
# Helper: run a single agent turn and return its final text response
# ---------------------------------------------------------------------------
async def _run_agent_turn(
    runner: Runner,
    session_service: InMemorySessionService,
    session_id: str,
    user_id: str,
    user_message: str,
    output_key: str,
) -> str:
    """
    Sends a single user message to an agent via its Runner and returns the
    agent's final text response.

    We iterate over all streamed events from run_async() and pick the last
    event where is_final_response() is True.  Intermediate events (tool calls,
    tool responses, partial tokens) are logged at DEBUG level so they don't
    clutter the console but remain inspectable when needed.

    Args:
        runner:          The ADK Runner bound to the agent.
        session_service: Shared InMemorySessionService instance.
        session_id:      Unique session ID for this agent's conversation.
        user_id:         Consistent user ID across all sessions.
        user_message:    The text to send as the user turn.
        output_key:      The session state key where the agent stores its output.

    Returns:
        The agent's final response text, or an empty string if none was found.
    """
    # Wrap the plain string in the ADK Content/Part structure
    new_message = types.Content(
        role="user",
        parts=[types.Part(text=user_message)],
    )

    final_text = ""

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=new_message,
    ):
        if event.is_final_response():
            # Extract text from the Content parts
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        final_text += part.text
            log.debug("Final event from agent '%s': %s", event.author, final_text[:80])
        else:
            log.debug("Intermediate event: author=%s, partial=%s", event.author, event.partial)

    # Fall back to reading the output_key from session state if the event
    # didn't carry a content payload (some ADK versions store output there)
    if not final_text:
        session = await session_service.get_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )
        if session and output_key in session.state:
            final_text = str(session.state[output_key])

    return final_text.strip()


# ---------------------------------------------------------------------------
# Step 1: Run the Auditor Agent
# ---------------------------------------------------------------------------
async def _run_auditor(session_service: InMemorySessionService, user_id: str) -> str:
    """
    Runs the Auditor Agent to retrieve inventory and produce a ShortageReport.

    The McpToolset is used as an async context manager to ensure the MCP
    inventory server subprocess is properly started before the agent runs
    and cleanly terminated afterwards — preventing zombie processes.

    Args:
        session_service: Shared session service instance.
        user_id:         Consistent user ID for this pipeline run.

    Returns:
        The ShortageReport as a plain-text string.
    """
    log.info("━━━ STEP 1: Running AuditorAgent ━━━")

    auditor_agent, mcp_toolset = build_auditor_agent()
    session_id = f"auditor-{uuid.uuid4().hex[:8]}"

    # Create a dedicated session for the Auditor so its conversation
    # history is isolated from the other agents.
    await session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )

    runner = Runner(
        agent=auditor_agent,
        app_name=APP_NAME,
        session_service=session_service,
    )

    # In ADK 2.3, the Runner manages the McpToolset subprocess lifecycle
    # internally — no explicit context manager is needed. The toolset is
    # passed to the LlmAgent and the Runner handles spawning/teardown.
    shortage_report = await _run_agent_turn(
        runner=runner,
        session_service=session_service,
        session_id=session_id,
        user_id=user_id,
        # The Auditor's system prompt instructs it to call the tool and
        # return a formatted report — this trigger message is minimal.
        user_message="Please audit the current inventory and produce the shortage report.",
        output_key="shortage_report",
    )

    log.info("ShortageReport received (%d chars)", len(shortage_report))
    log.debug("ShortageReport:\n%s", shortage_report)
    return shortage_report


# ---------------------------------------------------------------------------
# Step 2: Run the Procurement Agent (with optional retry critique)
# ---------------------------------------------------------------------------
async def _run_procurement(
    session_service: InMemorySessionService,
    user_id: str,
    shortage_report: str,
    critique: str | None,
    attempt: int,
) -> str:
    """
    Runs the Procurement Agent to draft a restock email.

    On the first attempt (attempt=1), critique is None and the agent drafts
    from scratch.  On retries, the critique from the Evaluator is prepended
    to the message so the agent knows exactly what to fix.

    Args:
        session_service: Shared session service instance.
        user_id:         Consistent user ID for this pipeline run.
        shortage_report: Output from the AuditorAgent.
        critique:        Evaluator critique from the previous attempt (or None).
        attempt:         Current attempt number (1-indexed), used for logging.

    Returns:
        The drafted email as a plain-text string.
    """
    log.info("━━━ STEP 2: Running ProcurementAgent (attempt %d/%d) ━━━",
             attempt, MAX_PROCUREMENT_ATTEMPTS)

    if critique:
        log.info("Critique to address: %s", critique)

    procurement_agent = build_procurement_agent()
    # Use a unique session per attempt so the agent has a clean conversation
    # history — we don't want earlier failed drafts polluting the context.
    session_id = f"procurement-attempt{attempt}-{uuid.uuid4().hex[:8]}"

    await session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )

    runner = Runner(
        agent=procurement_agent,
        app_name=APP_NAME,
        session_service=session_service,
    )

    user_message = build_procurement_message(
        shortage_report=shortage_report,
        critique=critique,
    )

    email_draft = await _run_agent_turn(
        runner=runner,
        session_service=session_service,
        session_id=session_id,
        user_id=user_id,
        user_message=user_message,
        output_key="email_draft",
    )

    log.info("EmailDraft received (%d chars)", len(email_draft))
    log.debug("EmailDraft:\n%s", email_draft)
    return email_draft


# ---------------------------------------------------------------------------
# Step 3: Run the Evaluator Agent
# ---------------------------------------------------------------------------
async def _run_evaluator(
    session_service: InMemorySessionService,
    user_id: str,
    email_draft: str,
    shortage_report: str,
    attempt: int,
) -> EvaluationResult:
    """
    Runs the Evaluator Agent to score the current email draft.

    Args:
        session_service: Shared session service instance.
        user_id:         Consistent user ID for this pipeline run.
        email_draft:     The email produced by the ProcurementAgent.
        shortage_report: The original ShortageReport for ground-truth comparison.
        attempt:         Current attempt number (1-indexed), used for logging.

    Returns:
        An EvaluationResult with verdict (PASS/FAIL) and critique text.
    """
    log.info("━━━ STEP 3: Running EvaluatorAgent (attempt %d/%d) ━━━",
             attempt, MAX_PROCUREMENT_ATTEMPTS)

    evaluator_agent = build_evaluator_agent()
    session_id = f"evaluator-attempt{attempt}-{uuid.uuid4().hex[:8]}"

    await session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )

    runner = Runner(
        agent=evaluator_agent,
        app_name=APP_NAME,
        session_service=session_service,
    )

    user_message = build_evaluator_message(
        email_draft=email_draft,
        shortage_report=shortage_report,
    )

    raw_response = await _run_agent_turn(
        runner=runner,
        session_service=session_service,
        session_id=session_id,
        user_id=user_id,
        user_message=user_message,
        output_key="evaluation_result",
    )

    result = parse_evaluation_result(raw_response)
    log.info(
        "EvaluationResult: verdict=%s | critique=%s",
        result.verdict,
        result.critique or "(none)",
    )
    return result


# ---------------------------------------------------------------------------
# Save the final email to disk
# ---------------------------------------------------------------------------
def _save_output(email_draft: str, verdict: str, attempts: int) -> Path:
    """
    Saves the final email draft to output/final_email.txt with a run header.

    Args:
        email_draft: The accepted email text.
        verdict:     Final verdict ("PASS" or best-effort "FAIL").
        attempts:    Number of procurement attempts made.

    Returns:
        The Path where the file was saved.
    """
    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / "final_email.txt"

    header = (
        f"# multi-agent-pantry — Final Restock Email\n"
        f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"# Evaluator verdict: {verdict} (after {attempts} attempt(s))\n"
        f"# {'=' * 60}\n\n"
    )

    output_path.write_text(header + email_draft, encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# Main orchestration entry point
# ---------------------------------------------------------------------------
async def orchestrate() -> str:
    """
    Runs the full multi-agent pipeline and returns the final email draft.

    Pipeline:
      1. AuditorAgent    → ShortageReport
      2. ProcurementAgent → EmailDraft  (up to MAX_PROCUREMENT_ATTEMPTS)
      3. EvaluatorAgent  → EvaluationResult
         - PASS: save and return email
         - FAIL: send critique back to step 2, increment attempt counter
      4. If max attempts exhausted: log warning, save and return best draft

    Returns:
        The final email draft text (PASS quality or best-effort after 3 tries).

    Raises:
        RuntimeError: If the AuditorAgent returns an empty shortage report,
                      indicating a data or MCP connection problem.
    """
    log.info("═══ multi-agent-pantry pipeline starting ═══")

    # A single session service is shared across all agent runs in this pipeline.
    # InMemorySessionService is in-process and requires no external dependencies.
    session_service = InMemorySessionService()

    # Stable user ID for this pipeline run — links all agent sessions together
    # in logs without requiring a real user identity.
    user_id = f"system-run-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # ── Step 1: Audit ────────────────────────────────────────────────────────
    shortage_report = await _run_auditor(session_service, user_id)

    if not shortage_report:
        raise RuntimeError(
            "AuditorAgent returned an empty shortage report. "
            "Check the MCP server connection and inventory data."
        )

    # ── Step 2–3: Procurement + Evaluation loop ──────────────────────────────
    email_draft = ""
    last_result: EvaluationResult | None = None
    critique: str | None = None
    attempt: int = 0  # Guards against unbound variable if MAX_PROCUREMENT_ATTEMPTS == 0

    for attempt in range(1, MAX_PROCUREMENT_ATTEMPTS + 1):
        # Draft (or re-draft with critique)
        email_draft = await _run_procurement(
            session_service=session_service,
            user_id=user_id,
            shortage_report=shortage_report,
            critique=critique,
            attempt=attempt,
        )

        # Evaluate the draft
        last_result = await _run_evaluator(
            session_service=session_service,
            user_id=user_id,
            email_draft=email_draft,
            shortage_report=shortage_report,
            attempt=attempt,
        )

        if last_result.passed:
            log.info("✅ Email PASSED evaluation on attempt %d", attempt)
            break

        # Prepare critique for the next procurement attempt
        critique = last_result.critique
        log.warning(
            "⚠️  Email FAILED evaluation (attempt %d/%d). Retrying...",
            attempt,
            MAX_PROCUREMENT_ATTEMPTS,
        )

    else:
        # Loop exhausted without a PASS — accept the best available draft
        log.warning(
            "⚠️  Max attempts (%d) reached without PASS. "
            "Saving best-effort draft.",
            MAX_PROCUREMENT_ATTEMPTS,
        )

    # ── Save output ──────────────────────────────────────────────────────────
    final_verdict = last_result.verdict if last_result else "UNKNOWN"
    output_path = _save_output(email_draft, final_verdict, attempt)

    log.info("═══ Pipeline complete — output saved to %s ═══", output_path)
    return email_draft
