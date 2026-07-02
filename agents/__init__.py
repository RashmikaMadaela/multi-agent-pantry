"""
agents/__init__.py

Package marker for the agents layer.

Each agent module exposes a single factory function that returns a configured
ADK LlmAgent.  Using factory functions (rather than module-level singletons)
means each orchestrator run gets a fresh agent instance — important when the
MCP toolset connection must be re-established between runs.
"""

from agents.auditor import build_auditor_agent
from agents.procurement import build_procurement_agent
from agents.evaluator import build_evaluator_agent

__all__ = [
    "build_auditor_agent",
    "build_procurement_agent",
    "build_evaluator_agent",
]
