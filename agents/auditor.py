"""
agents/auditor.py

Defines the Auditor Agent for the multi-agent-pantry pipeline.

Role: Inventory auditor — the first agent in the pipeline.

WHY THIS AGENT EXISTS
---------------------
The Auditor is responsible for one thing only: retrieve raw inventory data
via the MCP tool and reason about which items are below threshold. Keeping
this concern separate from procurement (drafting) and evaluation follows the
Single Responsibility Principle and allows each agent to be tested, swapped,
or prompted independently.

HOW IT WORKS (ADK LlmAgent + McpToolset)
-----------------------------------------
1. The orchestrator calls `build_auditor_agent()` which creates an `LlmAgent`
   with a `McpToolset` attached.
2. When the Runner invokes this agent, ADK performs the MCP capability
   handshake with the inventory server subprocess, discovering the
   `check_inventory` tool automatically.
3. The agent calls `check_inventory`, receives the validated JSON list, then
   produces a human-readable ShortageReport as its final text response.
4. The ADK Runner manages the McpToolset subprocess lifecycle internally —
   no explicit context manager call is required from the orchestrator.

SECURITY NOTE
-------------
The agent receives no user-supplied input.  Its only data source is the
MCP tool result, which has already been Pydantic-validated by the server
before reaching the LLM — defence-in-depth against malformed data.
"""

import os
import sys

# Allow overriding the model from the environment — useful when one model's
# free-tier quota is exhausted (e.g. swap to gemini-2.0-flash-lite).
_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset, StdioConnectionParams
from mcp import StdioServerParameters

# ---------------------------------------------------------------------------
# Resolve the absolute path to the MCP server script so this agent can be
# invoked from any working directory (critical for Docker deployments).
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MCP_SERVER_SCRIPT = os.path.join(_PROJECT_ROOT, "mcp_server", "inventory_server.py")
_PYTHON_EXECUTABLE = sys.executable  # Use the same Python that runs this file


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
_AUDITOR_SYSTEM_PROMPT = """
You are a professional restaurant inventory auditor for La Bella Cucina.

Your ONLY task is to call the `check_inventory` tool and produce a shortage report.

Steps:
1. Call `check_inventory` to retrieve all stock data.
2. Identify every item where current_stock <= minimum_threshold.
3. For each shortage item, compute:
      quantity_to_order = reorder_quantity - current_stock
4. Return a shortage report in this EXACT format:

SHORTAGE REPORT — La Bella Cucina
==================================
The following items require immediate restocking:

1. <item_name> | Unit: <unit> | Current: <current_stock> | Need to Order: <quantity_to_order>
2. ...

SUMMARY: <N> item(s) require restocking.

Do NOT include items that are above their minimum threshold.
Do NOT add commentary outside this format.
""".strip()


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------
def build_auditor_agent() -> tuple[LlmAgent, McpToolset]:
    """
    Constructs and returns the Auditor LlmAgent together with its McpToolset.

    The McpToolset is passed to the LlmAgent so the ADK Runner can discover
    and manage the MCP server subprocess automatically — no manual context
    manager is needed by the caller in ADK 0.3+.

    Returns:
        A tuple of (LlmAgent, McpToolset).
    """
    # Connect to the inventory MCP server via stdio subprocess.
    # StdioConnectionParams wraps StdioServerParameters (the MCP SDK type)
    # with an optional timeout for the initial handshake.
    mcp_toolset = McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=_PYTHON_EXECUTABLE,
                args=[_MCP_SERVER_SCRIPT],
            ),
            # Allow up to 10 s for the server process to start and respond
            timeout=10.0,
        )
    )

    agent = LlmAgent(
        name="AuditorAgent",
        # Model is read from GEMINI_MODEL env var (default: gemini-2.0-flash-lite)
        model=_MODEL,
        instruction=_AUDITOR_SYSTEM_PROMPT,
        tools=[mcp_toolset],
        # Store the shortage report text in session state so downstream agents
        # can read it without it being passed through the human turn.
        output_key="shortage_report",
    )

    return agent, mcp_toolset
