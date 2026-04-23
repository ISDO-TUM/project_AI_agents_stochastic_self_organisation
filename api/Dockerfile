# ---- uv binary ----
FROM ghcr.io/astral-sh/uv:0.11.7 AS uv

# ---- builder: install deps into an isolated venv ----
FROM python:3.12-slim AS builder

COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app

# Install production dependencies into /opt/venv (cached layer)
COPY requirements.txt .
RUN uv venv /opt/venv && \
    uv pip install --python /opt/venv --no-cache -r requirements.txt

# ---- runtime: minimal image, no build tools ----
FROM python:3.12-slim AS runtime

# Copy only the pre-built venv — no uv, no pip, no build tools in the final image
COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    VIRTUAL_ENV="/opt/venv" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Non-root user
RUN useradd --system --uid 1001 --no-create-home appuser

WORKDIR /app
COPY . .

USER appuser
EXPOSE 8000

CMD ["uvicorn", "index:app", "--host", "0.0.0.0", "--port", "8000"]
