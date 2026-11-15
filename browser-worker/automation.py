"""
Playwright browser automation, isolated from the main API.

Hard rules enforced here, not just documented:
  * Never submit without a valid, unexpired, one-time approval proof.
  * Never solve or bypass a CAPTCHA, login wall or MFA prompt.
  * Never persist browser profile data or passwords.
  * A click is not proof of submission. CONFIRMED requires confirmation text
    or a success URL from the target site; otherwise the result is
    UNKNOWN_SUBMISSION_STATUS.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import logging
import os
import socket
import sqlite3
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

logger = logging.getLogger(__name__)

WORKER_SECRET = os.getenv("WORKER_SECRET", "")
APPROVAL_SIGNING_SECRET = os.getenv("APPROVAL_SIGNING_SECRET", "")
ALLOW_PRIVATE_TARGETS = os.getenv("ALLOW_PRIVATE_TARGETS", "false").lower() == "true"
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "900"))
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "4"))
NAV_TIMEOUT_MS = int(os.getenv("NAV_TIMEOUT_MS", "45000"))
NONCE_DB = os.getenv("NONCE_DB", str(Path(tempfile.gettempdir()) / "jobpilot-worker-nonces.sqlite3"))

SENSITIVE_PATTERNS = (
    "gender",
    "sex",
    "race",
    "ethnic",
    "veteran",
    "disability",
    "religion",
    "caste",
    "marital",
    "social security",
    "ssn",
    "aadhaar",
    "passport",
    "date of birth",
    "dob",
    "nationality",
)

CONFIRMATION_PATTERNS = (
    "thank you for applying",
    "thanks for applying",
    "application has been received",
    "application was received",
    "application received",
    "we have received your application",
    "successfully applied",
    "application submitted",
    "application has been submitted",
    "your application is complete",
    "submission successful",
)

CAPTCHA_PATTERNS = ("captcha", "i'm not a robot", "i am not a robot", "recaptcha", "hcaptcha", "turnstile")

FIELD_JS = """
() => {
  const refs = [];
  const elements = Array.from(document.querySelectorAll('input, textarea, select'));
  let index = 0;
  const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim().slice(0, 300);
  const labelFor = (el) => {
    if (el.labels && el.labels.length) return clean(el.labels[0].innerText);
    if (el.id) {
      const byFor = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (byFor) return clean(byFor.innerText);
    }
    const labelled = el.getAttribute('aria-labelledby');
    if (labelled) {
      const node = document.getElementById(labelled);
      if (node) return clean(node.innerText);
    }
    const aria = el.getAttribute('aria-label');
    if (aria) return clean(aria);
    const placeholder = el.getAttribute('placeholder');
    if (placeholder) return clean(placeholder);
    const parent = el.closest('div, li, fieldset, td, section');
    if (parent) {
      const text = clean(parent.innerText);
      if (text && text.length <= 160) return text;
    }
    return clean(el.name || el.id);
  };
  for (const el of elements) {
    const type = (el.getAttribute('type') || el.tagName || '').toLowerCase();
    if (['hidden', 'submit', 'button', 'reset', 'image'].includes(type)) continue;
    if (el.disabled) continue;
    if (el.offsetParent === null && type !== 'file') continue;
    const ref = 'f' + index++;
    el.setAttribute('data-jobpilot-ref', ref);
    const options = el.tagName.toLowerCase() === 'select'
      ? Array.from(el.options).map(o => ({value: o.value, label: clean(o.text), disabled: o.disabled}))
      : [];
    refs.push({
      ref,
      tag: el.tagName.toLowerCase(),
      type,
      name: clean(el.name || ''),
      id: clean(el.id || ''),
      label: labelFor(el),
      placeholder: clean(el.getAttribute('placeholder') || ''),
      required: !!(el.required || el.getAttribute('aria-required') === 'true'),
      value: type === 'file' ? '' : clean(el.value || ''),
      checked: !!el.checked,
      options,
      multiple: !!el.multiple,
      accept: clean(el.getAttribute('accept') || ''),
    });
  }
  const bodyText = clean(document.body ? document.body.innerText : '').toLowerCase();
  const hasCaptcha = !!document.querySelector('.g-recaptcha, .h-captcha, [data-sitekey], iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"]')
    || /captcha|i'm not a robot|i am not a robot/.test(bodyText);
  const hasPassword = !!document.querySelector('input[type="password"]');
  const buttons = Array.from(document.querySelectorAll('button, input[type="submit"]'))
    .filter(b => b.offsetParent !== null)
    .map(b => clean(b.innerText || b.value || ''));
  return {fields: refs, hasCaptcha, hasPassword, buttons};
}
"""

VALIDATION_JS = """
() => {
  const messages = [];
  const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim().slice(0, 300);
  for (const el of document.querySelectorAll('[aria-invalid="true"], .error, .field-error, .invalid-feedback, [role="alert"]')) {
    const text = clean(el.innerText);
    if (text && text.length > 1) messages.push(text);
  }
  for (const el of document.querySelectorAll('input, textarea, select')) {
    if (el.willValidate && !el.validity.valid) {
      const label = el.getAttribute('aria-label') || el.name || el.id || el.tagName;
      messages.push(`${label}: ${el.validationMessage || 'invalid value'}`);
    }
  }
  return Array.from(new Set(messages)).slice(0, 20);
}
"""


class WorkerError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class Session:
    id: str
    application_id: str
    page: Page
    context: BrowserContext
    fields: list[dict]
    resume_path: str | None
    resume_filename: str | None
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    submitted: bool = False
    url: str = ""
    captcha: bool = False
    login: bool = False


class BrowserAutomation:
    def __init__(self) -> None:
        self._playwright = None
        self.browser: Browser | None = None
        self.sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()
        self._init_nonce_db()

    def _init_nonce_db(self) -> None:
        directory = Path(NONCE_DB).parent
        directory.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(NONCE_DB) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS used_nonces (
                    nonce TEXT PRIMARY KEY,
                    application_id TEXT NOT NULL,
                    used_at TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                )
                """
            )

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
        logger.info("Chromium started")

    async def stop(self) -> None:
        for session in list(self.sessions.values()):
            await self._close_session(session)
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def analyze(
        self,
        url: str,
        application_id: str,
        resume: bytes | None,
        resume_filename: str | None,
    ) -> dict:
        assert_safe_url(url, ALLOW_PRIVATE_TARGETS)
        await self._gc()
        async with self._lock:
            if len(self.sessions) >= MAX_SESSIONS:
                raise WorkerError("Browser worker is at capacity. Try again shortly.", status=429)
            context = await self.browser.new_context(
                viewport={"width": 1280, "height": 900},
                locale="en-IN",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 JobPilotAI/1.0"
                ),
            )
            page = await context.new_page()
            page.set_default_timeout(NAV_TIMEOUT_MS)
            resume_path = None
            if resume:
                suffix = Path(resume_filename or "resume.pdf").suffix or ".pdf"
                handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                handle.write(resume)
                handle.close()
                resume_path = handle.name
            try:
                response = await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(700)
                if response is not None and response.status >= 400:
                    raise WorkerError(f"Application page returned HTTP {response.status}.", status=502)
                detected = await page.evaluate(FIELD_JS)
                session = Session(
                    id=uuid.uuid4().hex,
                    application_id=application_id,
                    page=page,
                    context=context,
                    fields=detected["fields"],
                    resume_path=resume_path,
                    resume_filename=resume_filename,
                    url=url,
                    captcha=bool(detected["hasCaptcha"]),
                    login=bool(detected["hasPassword"]),
                )
                self.sessions[session.id] = session
                screenshot = await self._screenshot(page)
                return {
                    "session_id": session.id,
                    "application_id": application_id,
                    "url": url,
                    "final_url": page.url,
                    "title": await page.title(),
                    "fields": detected["fields"],
                    "buttons": detected["buttons"],
                    "detected": {
                        "has_captcha": session.captcha,
                        "requires_login": session.login,
                        "file_inputs": sum(1 for f in detected["fields"] if f["type"] == "file"),
                        "sensitive_fields": [
                            f["ref"] for f in detected["fields"] if is_sensitive(f)
                        ],
                    },
                    "warnings": [
                        warning
                        for warning in (
                            "CAPTCHA detected. Automation stops; complete it yourself." if session.captcha else None,
                            "A password field was detected. This looks like a login wall." if session.login else None,
                        )
                        if warning
                    ],
                    "screenshot": screenshot,
                }
            except WorkerError:
                await context.close()
                raise
            except Exception as exc:
                await context.close()
                logger.warning("Analyze failed: %s", type(exc).__name__)
                raise WorkerError(f"Could not analyze the application page ({type(exc).__name__}).", status=502) from exc

    async def fill(self, session_id: str, values: dict[str, str], upload_resume: bool = True) -> dict:
        session = self._get(session_id)
        if session.submitted:
            raise WorkerError("This session has already been submitted.", status=409)
        filled: list[dict] = []
        skipped: list[dict] = []

        for field in session.fields:
            ref = field["ref"]
            if field["type"] == "file":
                if upload_resume and session.resume_path:
                    try:
                        await session.page.set_input_files(f'[data-jobpilot-ref="{ref}"]', session.resume_path)
                        filled.append({"ref": ref, "label": field["label"], "value": session.resume_filename})
                    except Exception as exc:
                        skipped.append({"ref": ref, "label": field["label"], "reason": type(exc).__name__})
                else:
                    skipped.append({"ref": ref, "label": field["label"], "reason": "No resume selected"})
                continue

            value = values.get(ref)
            if value is None or value == "":
                skipped.append({"ref": ref, "label": field["label"], "reason": "No value supplied"})
                continue
            if field["tag"] == "select":
                try:
                    await _select_option(session.page, ref, value)
                    filled.append({"ref": ref, "label": field["label"], "value": value})
                except Exception:
                    skipped.append({"ref": ref, "label": field["label"], "reason": "No matching option"})
                continue
            if field["type"] in {"checkbox", "radio"}:
                if str(value).lower() in {"true", "yes", "1", "on"}:
                    try:
                        await session.page.check(f'[data-jobpilot-ref="{ref}"]')
                        filled.append({"ref": ref, "label": field["label"], "value": "checked"})
                    except Exception:
                        skipped.append({"ref": ref, "label": field["label"], "reason": "Could not check"})
                else:
                    skipped.append({"ref": ref, "label": field["label"], "reason": "Unchecked by policy"})
                continue
            try:
                await session.page.fill(f'[data-jobpilot-ref="{ref}"]', str(value))
                filled.append({"ref": ref, "label": field["label"], "value": str(value)})
            except Exception as exc:
                skipped.append({"ref": ref, "label": field["label"], "reason": type(exc).__name__})

        session.last_used = time.time()
        validation = await session.page.evaluate(VALIDATION_JS)
        screenshot = await self._screenshot(session.page)
        return {
            "session_id": session.id,
            "filled": filled,
            "skipped": skipped,
            "validation_errors": validation,
            "screenshot": screenshot,
            "file_inputs": sum(1 for f in session.fields if f["type"] == "file"),
            "resume_attached": bool(session.resume_path),
        }

    async def submit(self, session_id: str, application_id: str, proof: dict) -> dict:
        session = self._get(session_id)
        if session.application_id != application_id:
            raise WorkerError("Approval does not belong to this application.", status=403)
        if session.submitted:
            raise WorkerError("Duplicate submission blocked: this session was already submitted.", status=409)
        if session.captcha:
            raise WorkerError("CAPTCHA detected. Submission is blocked; complete it yourself.", status=409)
        if session.login:
            raise WorkerError("Login required. Submission is blocked; sign in yourself.", status=409)
        verify_approval_proof(application_id, proof)

        validation = await session.page.evaluate(VALIDATION_JS)
        required_file_missing = [
            f["label"] or f["name"] or f["ref"]
            for f in session.fields
            if f.get("required") and f["type"] == "file" and not session.resume_path
        ]
        required_missing = [
            f["label"] or f["name"] or f["ref"]
            for f in session.fields
            if f.get("required") and f["type"] != "file" and not f.get("value")
            and f["type"] not in {"checkbox", "radio"}
        ]
        # Re-inspect the DOM for current values before clicking.
        current = await session.page.evaluate(FIELD_JS)
        current_required_missing = [
            f["label"] or f["name"] or f["ref"]
            for f in current["fields"]
            if f.get("required") and f["type"] != "file" and not f.get("value")
        ]
        if required_file_missing:
            return {
                "outcome": "VALIDATION_FAILED",
                "validation_errors": [],
                "missing_required": required_file_missing[:10],
                "screenshot": await self._screenshot(session.page),
                "final_url": session.page.url,
                "evidence": {"reason": "A required resume attachment is missing."},
            }
        if validation or current_required_missing:
            return {
                "outcome": "VALIDATION_FAILED",
                "validation_errors": validation[:10],
                "missing_required": (current_required_missing or required_missing)[:10],
                "screenshot": await self._screenshot(session.page),
                "final_url": session.page.url,
                "evidence": None,
            }

        consume_nonce(proof["nonce"], application_id, int(proof["expires_at"]))
        session.submitted = True  # set before the click: stops a second click

        button = await _find_submit_button(session.page)
        if button is None:
            return {
                "outcome": "FAILED",
                "validation_errors": [],
                "missing_required": [],
                "screenshot": await self._screenshot(session.page),
                "final_url": session.page.url,
                "evidence": {"reason": "No visible submit button found."},
            }

        started_url = session.page.url
        await button.click()
        try:
            await session.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            await session.page.wait_for_timeout(2000)

        body_text = await session.page.evaluate(
            "() => document.body ? document.body.innerText : ''"
        )
        body_lower = " ".join(body_text.lower().split())
        matched = next((pattern for pattern in CONFIRMATION_PATTERNS if pattern in body_lower), None)
        url_changed = session.page.url != started_url
        # Only unambiguous success path segments count. "no-confirmation"
        # must not be mistaken for "/confirmation".
        path = urlparse(session.page.url).path.lower()
        segments = [segment for segment in path.split("/") if segment]
        success_url = any(
            segment.startswith(("thank-you", "thankyou", "success", "applied", "application-complete"))
            for segment in segments
        )
        validation_after = await session.page.evaluate(VALIDATION_JS)
        screenshot = await self._screenshot(session.page)

        if matched or success_url:
            snippet = _snippet(body_text, matched) if matched else ""
            return {
                "outcome": "CONFIRMED",
                "validation_errors": [],
                "missing_required": [],
                "screenshot": screenshot,
                "final_url": session.page.url,
                "evidence": {
                    "matched_text": snippet or "Success URL detected",
                    "url_changed": url_changed,
                    "final_url": session.page.url,
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                },
            }
        if validation_after:
            return {
                "outcome": "VALIDATION_FAILED",
                "validation_errors": validation_after[:10],
                "missing_required": [],
                "screenshot": screenshot,
                "final_url": session.page.url,
                "evidence": None,
            }
        return {
            "outcome": "UNKNOWN_SUBMISSION_STATUS",
            "validation_errors": [],
            "missing_required": [],
            "screenshot": screenshot,
            "final_url": session.page.url,
            "evidence": {
                "reason": "The button was clicked but no confirmation text or success URL was observed.",
                "url_changed": url_changed,
                "final_url": session.page.url,
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    async def close(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if session:
            await self._close_session(session)

    async def stats(self) -> dict:
        await self._gc()
        return {
            "browser": self.browser is not None,
            "sessions": len(self.sessions),
            "max_sessions": MAX_SESSIONS,
            "allow_private_targets": ALLOW_PRIVATE_TARGETS,
        }

    # -- internals ---------------------------------------------------------

    def _get(self, session_id: str) -> Session:
        session = self.sessions.get(session_id)
        if session is None:
            raise WorkerError("Browser session not found or expired. Re-analyze the form.", status=404)
        if session.last_used < time.time() - SESSION_TTL_SECONDS:
            self.sessions.pop(session_id, None)
            raise WorkerError("Browser session expired. Re-analyze the form.", status=404)
        session.last_used = time.time()
        return session

    async def _close_session(self, session: Session) -> None:
        try:
            await session.context.close()
        except Exception:
            pass
        if session.resume_path:
            try:
                os.unlink(session.resume_path)
            except OSError:
                pass

    async def _gc(self) -> None:
        cutoff = time.time() - SESSION_TTL_SECONDS
        expired = [s.id for s in self.sessions.values() if s.last_used < cutoff]
        for session_id in expired:
            await self.close(session_id)

    async def _screenshot(self, page: Page) -> dict:
        try:
            data = await page.screenshot(full_page=False, type="png")
            return {"mime": "image/png", "base64": base64.b64encode(data).decode()}
        except Exception:
            return {}


async def _select_option(page: Page, ref: str, value: str) -> None:
    selector = f'[data-jobpilot-ref="{ref}"]'
    options = await page.eval_on_selector(
        selector,
        "el => Array.from(el.options).map(o => ({value: o.value, label: o.text.trim()}))",
    )
    value_lower = value.strip().lower()
    match = next((o for o in options if o["value"].strip().lower() == value_lower), None)
    if match is None:
        match = next((o for o in options if o["label"].strip().lower() == value_lower), None)
    if match is None:
        match = next((o for o in options if value_lower in o["label"].strip().lower()), None)
    if match is None:
        raise ValueError("No matching option")
    await page.select_option(selector, match["value"])


async def _find_submit_button(page: Page):
    candidates = page.locator("button[type='submit'], input[type='submit'], button")
    count = await candidates.count()
    for index in range(count):
        candidate = candidates.nth(index)
        try:
            if not await candidate.is_visible():
                continue
            text = ((await candidate.inner_text()) or "").strip().lower()
            if any(
                word in text
                for word in ("submit", "apply", "send application", "finish", "complete")
            ):
                return candidate
        except Exception:
            continue
    return None


def verify_approval_proof(application_id: str, proof: dict) -> None:
    if not APPROVAL_SIGNING_SECRET:
        raise WorkerError("Approval signing secret is not configured on the worker.", status=503)
    try:
        token_hash = str(proof["token_hash"])
        nonce = str(proof["nonce"])
        expires_at = int(proof["expires_at"])
        signature = str(proof["signature"])
        proof_application = str(proof["application_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkerError("Malformed approval proof.", status=403) from exc
    if proof_application != application_id:
        raise WorkerError("Approval does not belong to this application.", status=403)
    if expires_at < int(time.time()):
        raise WorkerError("Approval has expired.", status=403)
    message = f"{application_id}:{token_hash}:{nonce}:{expires_at}"
    expected = hmac.new(APPROVAL_SIGNING_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise WorkerError("Approval signature is invalid.", status=403)
    with sqlite3.connect(NONCE_DB) as conn:
        existing = conn.execute("SELECT 1 FROM used_nonces WHERE nonce = ?", (nonce,)).fetchone()
    if existing:
        raise WorkerError("Approval has already been used.", status=409)


def consume_nonce(nonce: str, application_id: str, expires_at: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    try:
        with sqlite3.connect(NONCE_DB) as conn:
            conn.execute(
                "INSERT INTO used_nonces (nonce, application_id, used_at, expires_at) VALUES (?,?,?,?)",
                (nonce, application_id, now, expires_at),
            )
            # Housekeeping: approval proofs are useless after expiry.
            conn.execute("DELETE FROM used_nonces WHERE expires_at < ?", (int(time.time()) - 86400,))
    except sqlite3.IntegrityError as exc:
        raise WorkerError("Approval has already been used.", status=409) from exc


def is_sensitive(field: dict) -> bool:
    label = f"{field.get('label', '')} {field.get('name', '')} {field.get('id', '')}".lower()
    return any(pattern in label for pattern in SENSITIVE_PATTERNS)


def assert_safe_url(url: str, allow_private: bool) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise WorkerError("Only http(s) application URLs are supported.")
    host = parsed.hostname
    if host in {"localhost", "127.0.0.1", "::1"} and allow_private:
        return
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise WorkerError("Application host could not be resolved.") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        ) and not allow_private:
            raise WorkerError("Application URL resolves to a private or reserved address.")


def _snippet(text: str, needle: str | None) -> str:
    if not text:
        return ""
    lower = text.lower()
    index = lower.find(needle) if needle else -1
    if index == -1:
        return " ".join(text.split())[:300]
    start = max(0, index - 80)
    return " ".join(text[start : start + 400].split())
