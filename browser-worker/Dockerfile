FROM node:24-bookworm-slim AS agent-browser-deps
WORKDIR /opt/agent-browser
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts

FROM mcr.microsoft.com/playwright/python:v1.63.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY --from=agent-browser-deps /usr/local/bin/node /usr/local/bin/node
COPY --from=agent-browser-deps /opt/agent-browser/node_modules ./node_modules
ENV NODE_BINARY=/usr/local/bin/node \
    AGENT_BROWSER_SCRIPT=/app/node_modules/agent-browser/bin/agent-browser.js

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --shell /bin/bash worker && chown -R worker:worker /app
USER worker

# Isolated from the main API — this worker is the ONLY service that drives a
# real browser, and it never submits a form without a signed, one-time proof
# bound to that specific application.
EXPOSE 8100
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]
