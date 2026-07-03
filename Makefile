# =============================================================================
# Makefile — multi-agent-pantry
#
# Convenience targets for local development and Docker deployment.
# All Python commands use the project's virtual environment (.venv).
#
# Prerequisites:
#   - Python 3.11+  (for local targets)
#   - Docker        (for docker-* targets)
#   - .env file     (with GOOGLE_API_KEY set)
#
# Quick start:
#   make setup      # Create .venv and install dependencies
#   make run        # Run the full agent pipeline
# =============================================================================

VENV        := .venv
PYTHON      := $(VENV)/bin/python
PIP         := $(VENV)/bin/pip
PYTEST      := $(VENV)/bin/pytest

.PHONY: help setup run test lint clean docker-build docker-up docker-down

# ── Default target: show help ────────────────────────────────────────────────
help:
	@echo ""
	@echo "  multi-agent-pantry — available targets"
	@echo "  ───────────────────────────────────────"
	@echo "  make setup        Create .venv and install dependencies"
	@echo "  make run          Run the full 3-agent pipeline locally"
	@echo "  make test         Run the test suite"
	@echo "  make lint         Check for secrets with detect-secrets"
	@echo "  make clean        Remove output/, __pycache__, .pyc files"
	@echo "  make docker-build Build the Docker image"
	@echo "  make docker-up    Build and run the pipeline in Docker"
	@echo "  make docker-down  Stop and remove Docker containers"
	@echo ""

# ── Local setup ──────────────────────────────────────────────────────────────
setup: $(VENV)/bin/activate

$(VENV)/bin/activate: requirements.txt
	@echo "→ Creating virtual environment..."
	python3 -m venv $(VENV)
	@echo "→ Installing dependencies..."
	$(PIP) install --upgrade pip -q
	$(PIP) install -r requirements.txt -q
	@echo "✅ Setup complete. Activate with: source $(VENV)/bin/activate"

# ── Run pipeline locally ─────────────────────────────────────────────────────
run: $(VENV)/bin/activate
	@echo "→ Starting multi-agent-pantry pipeline..."
	$(PYTHON) main.py

# ── Tests ────────────────────────────────────────────────────────────────────
test: $(VENV)/bin/activate
	@echo "→ Running test suite..."
	$(PYTEST) tests/ -v

# ── Security lint (detect-secrets) ───────────────────────────────────────────
lint: $(VENV)/bin/activate
	@echo "→ Running detect-secrets scan..."
	$(VENV)/bin/detect-secrets scan --baseline .secrets.baseline 2>/dev/null || \
	$(VENV)/bin/pip install detect-secrets -q && \
	$(VENV)/bin/detect-secrets scan
	@echo "→ Running security check for hardcoded keys..."
	@grep -rn "AIza" --include="*.py" . && echo "⚠️  Possible API key found!" || echo "✅ No hardcoded keys detected."

# ── Clean ────────────────────────────────────────────────────────────────────
clean:
	@echo "→ Cleaning up..."
	rm -rf output/ __pycache__ .pytest_cache
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Clean complete."

# ── Docker targets ───────────────────────────────────────────────────────────
docker-build:
	@echo "→ Building Docker image..."
	docker build -t multi-agent-pantry .
	@echo "✅ Image built: multi-agent-pantry"

docker-up:
	@test -f .env || (echo "❌ .env file not found. Run: cp .env.example .env" && exit 1)
	@echo "→ Building and running pipeline in Docker..."
	docker compose up --build

docker-down:
	@echo "→ Stopping Docker containers..."
	docker compose down
	@echo "✅ Containers stopped."
