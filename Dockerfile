# =============================================================================
# Dockerfile — multi-agent-pantry
#
# SECURITY DESIGN
# ---------------
# - API keys are NEVER baked into the image (no ENV GOOGLE_API_KEY=... here).
# - Secrets are injected at runtime via docker-compose's `env_file` directive.
# - The container runs as a non-root user (appuser) to limit blast radius if
#   the container is ever compromised.
#
# MULTI-STAGE BUILD
# -----------------
# Stage 1 (builder): installs Python dependencies into an isolated layer.
# Stage 2 (runtime): copies only the installed packages and source code.
# This keeps the final image lean — no pip, no build tools in production.
#
# BUILD:  docker build -t multi-agent-pantry .
# RUN:    docker run --env-file .env multi-agent-pantry
# =============================================================================

# ── Stage 1: dependency builder ──────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Copy only the requirements file first so Docker can cache this layer.
# The layer is only invalidated when requirements.txt changes — not on
# every source code edit, which keeps iterative builds fast.
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime image ───────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Create a non-root user and group.
# Running as root inside a container is a security anti-pattern.
RUN groupadd --gid 1001 appgroup \
 && useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy installed packages from the builder stage
COPY --from=builder /install /usr/local

# Copy application source code
# .dockerignore excludes .env, .venv, __pycache__, and output/
COPY --chown=appuser:appgroup . .

# Ensure the output directory exists and is writable by the app user
RUN mkdir -p /app/output && chown appuser:appgroup /app/output

# Switch to non-root user before running the application
USER appuser

# GOOGLE_API_KEY must be provided at runtime via --env-file or -e flag.
# It is intentionally NOT set here.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "main.py"]
