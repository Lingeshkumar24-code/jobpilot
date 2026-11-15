"""
Browser automation worker — Phase 1 placeholder.

Real implementation (Phase 10) will:
  - navigate to a job's application_url
  - detect and fill supported form fields
  - never submit without a per-application approval token
  - never attempt to bypass CAPTCHA, login walls, or MFA
  - capture a screenshot for the Approval Agent's preview

This file intentionally does nothing but expose a health check today —
no fabricated automation logic ships before the real agent does.
"""
from fastapi import FastAPI

app = FastAPI(title="JobPilot AI — Browser Worker")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "browser-worker", "phase": "1 — not yet implemented"}
