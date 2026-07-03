"""
main.py

Entry point for the multi-agent-pantry pipeline.

RESPONSIBILITIES
----------------
1. Load environment variables from .env (never hardcode secrets).
2. Validate that GOOGLE_API_KEY is present before any agent is instantiated.
3. Configure the Google GenAI client used by all ADK LlmAgents.
4. Run the async orchestrator and print the final email to stdout.

SECURITY NOTE
-------------
The API key is loaded exclusively from the environment via python-dotenv.
It is NEVER passed as a function argument, logged, or written to any file.
The google-adk SDK reads GOOGLE_API_KEY from os.environ automatically —
no explicit configure() call is needed or available in this SDK version.

USAGE
-----
    # Local run:
    python main.py

    # Or via Makefile:
    make run

    # Or via Docker:
    make docker-up
"""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 1. Load .env BEFORE importing any google-adk or google-genai modules.
#    This ensures GOOGLE_API_KEY is in os.environ when the SDK initialises.
# ---------------------------------------------------------------------------
load_dotenv()  # Reads .env from the current working directory

# ---------------------------------------------------------------------------
# 2. Validate the API key early — fail fast with a clear message rather than
#    a cryptic authentication error deep inside the ADK stack.
# ---------------------------------------------------------------------------
_API_KEY = os.environ.get("GOOGLE_API_KEY", "").strip()

if not _API_KEY:
    print(
        "\n❌  ERROR: GOOGLE_API_KEY is not set.\n"
        "   Copy .env.example to .env and add your key:\n"
        "     cp .env.example .env\n"
        "     # then edit .env and set GOOGLE_API_KEY=<your key>\n",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# 3. Set up root logger — orchestrator.py configures its own logger;
#    this sets the level for the top-level run output.
#
#    NOTE: google-adk 2.3.0 reads GOOGLE_API_KEY from os.environ directly.
#    No genai.configure() call is needed — the SDK picks up the key we
#    validated above automatically.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

# ---------------------------------------------------------------------------
# 5. Import the orchestrator AFTER env + genai config is complete.
# ---------------------------------------------------------------------------
from orchestrator import orchestrate


# ---------------------------------------------------------------------------
# 6. Async main — runs the full pipeline and prints the result.
# ---------------------------------------------------------------------------
async def main() -> None:
    """
    Top-level async entry point.

    Calls orchestrate(), prints the final email to stdout, and exits cleanly.
    Any unhandled exception is caught here and logged before exit so the
    process always returns a meaningful exit code.
    """
    log.info("multi-agent-pantry starting up")

    try:
        final_email = await orchestrate()
    except Exception as exc:
        log.error("Pipeline failed with an unexpected error: %s", exc, exc_info=True)
        sys.exit(1)

    # Print a clear separator so the email is easy to find in console output
    print("\n" + "═" * 70)
    print("  FINAL RESTOCK EMAIL")
    print("═" * 70 + "\n")
    print(final_email)
    print("\n" + "═" * 70)
    log.info("Done. Check output/final_email.txt for the saved copy.")


# ---------------------------------------------------------------------------
# Entry point guard
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
