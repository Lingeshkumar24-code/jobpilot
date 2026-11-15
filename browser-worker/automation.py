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
import json
import logging
import os
import re
import socket
import sqlite3
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from websockets.asyncio.client import connect as websocket_connect

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
  const allElements = Array.from(document.querySelectorAll('input, textarea, select'));
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
  const applicationCue = /\\b(first name|last name|full name|email|phone|resume|curriculum vitae|cv|cover letter|linkedin|portfolio|salary expectation|salary requirement|work authorization|notice period|experience|website|github|candidate)\\b/i;
  const visible = (el) => el.offsetParent !== null || (el.getAttribute('type') || '').toLowerCase() === 'file';
  const forms = Array.from(document.querySelectorAll('form')).filter(visible).map(form => {
    const controls = Array.from(form.querySelectorAll('input, textarea, select')).filter(visible);
    const cues = controls.filter(el => applicationCue.test(labelFor(el))).length;
    const hasFile = controls.some(el => (el.getAttribute('type') || '').toLowerCase() === 'file');
    const context = clean(form.innerText).toLowerCase();
    const applicationContext = /\\b(apply|application|candidate|job application)\\b/.test(context);
    return {controls, cues, isApplication: cues >= 2 || (hasFile && controls.length >= 2) || (applicationContext && cues >= 1 && controls.length >= 2)};
  }).filter(item => item.isApplication).sort((a, b) => b.cues - a.cues);
  let elements = forms.length ? forms[0].controls : [];
  if (!elements.length && !document.querySelector('form')) {
    const controls = allElements.filter(visible);
    const cues = controls.filter(el => applicationCue.test(labelFor(el)));
    if (cues.length >= 2 || (controls.some(el => (el.getAttribute('type') || '').toLowerCase() === 'file') && controls.length >= 2)) elements = controls;
  }
  const hasApplicationForm = elements.length > 0;
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
  return {fields: refs, hasCaptcha, hasPassword, hasApplicationForm, buttons};
}
"""

APPLY_LINK_JS = """
() => {
  const clean = value => (value || '').replace(/\\s+/g, ' ').trim().slice(0, 160);
  return Array.from(document.querySelectorAll('a[href]'))
    .filter(a => a.offsetParent !== null)
    .map(a => ({text: clean(a.innerText || a.getAttribute('aria-label') || a.title), href: a.href}))
    .filter(a => /^https?:/i.test(a.href) && /\\bapply\\b|application/i.test(a.text))
    .sort((a, b) => {
      const rank = item => /\\bapply now\\b/i.test(item.text) ? 0 : /\\bapply for this job\\b/i.test(item.text) ? 1 : /\\bapply\\b/i.test(item.text) ? 2 : 3;
      return rank(a) - rank(b);
    })
    .slice(0, 8);
}
"""

VALIDATION_JS = """
() => {
  const messages = [];
  const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim().slice(0, 300);
  const form = Array.from(document.forms).find(candidate => candidate.querySelector('[data-jobpilot-ref]'));
  const fields = Array.from(document.querySelectorAll('[data-jobpilot-ref]'));
  if (!fields.length) return messages;
  const root = form || document;
  for (const el of root.querySelectorAll('[aria-invalid="true"], .error, .field-error, .invalid-feedback')) {
    const text = clean(el.innerText);
    if (text && text.length > 1) messages.push(text);
  }
  for (const el of fields) {
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
    browser: Browser
    agent_session: str
    stream_port: int
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
        self.chrome_executable_path: str | None = None
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
        self.chrome_executable_path = self._playwright.chromium.executable_path
        logger.info("Playwright CDP client started")

    async def search_google(self, query: str, limit: int = 20) -> dict:
        """Search Google in an isolated agent-browser Chrome session."""
        session_name = f"jp-search-{uuid.uuid4().hex}"
        try:
            await self._agent_browser(
                session_name,
                "open",
                f"https://www.google.com/search?q={quote_plus(query)}&num={max(1, min(limit, 50))}",
            )
            observed = await self._agent_browser(
                session_name,
                "eval",
                "({url:location.href,title:document.title,text:(document.body?.innerText||'').slice(0,4000)})",
            )
            page_info = observed.get("result") or {}
            page_text = str(page_info.get("text") or "").lower()
            if "google.com/sorry" in str(page_info.get("url") or "") or "unusual traffic" in page_text or "captcha" in page_text:
                raise WorkerError("Google requires a CAPTCHA. Search stopped for manual review.", status=503)
            extracted = await self._agent_browser(
                session_name,
                "eval",
                """(() => {
                  const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                  const out = [];
                  const seen = new Set();
                  for (const heading of document.querySelectorAll('a h3')) {
                    const link = heading.closest('a');
                    const url = link?.href;
                    if (!url || !/^https?:/.test(url) || seen.has(url)) continue;
                    const root = heading.closest('div.MjjYud') || heading.parentElement?.parentElement;
                    const text = clean(root?.innerText || '');
                    seen.add(url);
                    out.push({title: clean(heading.innerText), url, snippet: text.slice(0, 900)});
                    if (out.length >= 50) break;
                  }
                  return out;
                })()""",
            )
            return {
                "query": query,
                "results": extracted.get("result") or [],
                "url": page_info.get("url"),
            }
        except WorkerError:
            raise
        except Exception as exc:
            logger.warning("agent-browser search failed: %s", type(exc).__name__)
            raise WorkerError("Google browser search failed.", status=502) from exc
        finally:
            try:
                await self._agent_browser(session_name, "close")
            except Exception:
                pass

    async def open_job_search(self, provider: str, query: str) -> dict:
        """Open a private, user-controlled browser tab at a job search page."""
        provider = provider.lower().strip()
        encoded = quote_plus(query.strip())
        search_urls = {
            "google": f"https://www.google.com/search?q={encoded}",
            "linkedin": f"https://www.linkedin.com/jobs/search/?keywords={encoded}",
            "indeed": f"https://www.indeed.com/jobs?q={encoded}",
        }
        if provider not in search_urls:
            raise WorkerError("Choose Google, LinkedIn, or Indeed.")
        await self._gc()
        if len(self.sessions) >= MAX_SESSIONS:
            raise WorkerError("Browser worker is at capacity. Try again shortly.", status=429)
        session_key = uuid.uuid4().hex
        agent_session = f"jp-user-search-{session_key}"
        try:
            opened = await self._agent_browser(agent_session, "open", search_urls[provider])
            cdp = await self._agent_browser(agent_session, "get", "cdp-url")
            browser = await self._playwright.chromium.connect_over_cdp(cdp["cdpUrl"])
            if not browser.contexts or not browser.contexts[0].pages:
                raise WorkerError("Search browser did not open a page.", status=502)
            context = browser.contexts[0]
            page = context.pages[0]
            page.set_default_timeout(NAV_TIMEOUT_MS)
            await page.wait_for_timeout(700)
            stream = await self._agent_browser(agent_session, "stream", "status")
            stream_port = stream.get("port")
            if not isinstance(stream_port, int) or not 1 <= stream_port <= 65535:
                raise WorkerError("agent-browser did not expose a live browser stream.", status=502)
            session_id = uuid.uuid4().hex
            self.sessions[session_id] = Session(
                id=session_id,
                application_id=session_key,
                page=page,
                context=context,
                browser=browser,
                agent_session=agent_session,
                stream_port=stream_port,
                fields=[],
                resume_path=None,
                resume_filename=None,
                url=search_urls[provider],
            )
            return {
                "session_id": session_id,
                "session_key": session_key,
                "provider": provider,
                "query": query,
                "url": page.url or opened.get("url") or search_urls[provider],
                "title": await page.title(),
                "stream_port": stream_port,
                "screenshot": await self._screenshot(page),
            }
        except WorkerError:
            await self._agent_browser(agent_session, "close")
            raise
        except Exception as exc:
            try:
                await self._agent_browser(agent_session, "close")
            except Exception:
                pass
            logger.warning("Browser job search failed: %s", type(exc).__name__)
            raise WorkerError("Could not open the job search browser.", status=502) from exc

    async def _agent_browser(self, session_name: str, *args: str) -> dict:
        script = Path(os.getenv(
            "AGENT_BROWSER_SCRIPT",
            str(Path(__file__).resolve().parent / "node_modules" / "agent-browser" / "bin" / "agent-browser.js"),
        ))
        if not script.is_file():
            raise WorkerError("agent-browser is not installed in the browser worker.", status=503)
        command = [os.getenv("NODE_BINARY", "node"), str(script), "--session", session_name]
        if self.chrome_executable_path:
            command.extend(["--executable-path", self.chrome_executable_path])
        if os.name != "nt":
            command.extend(["--args", "--no-sandbox,--disable-dev-shm-usage"])
        command.extend(["--json", *args])
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise WorkerError("agent-browser command timed out.", status=504) from exc
        try:
            payload = json.loads(stdout.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("agent-browser returned invalid JSON: %s", stderr.decode("utf-8", errors="replace")[:300])
            raise WorkerError("agent-browser returned an invalid response.", status=502) from exc
        if process.returncode or not payload.get("success"):
            detail = payload.get("error") or stderr.decode("utf-8", errors="replace")[:300]
            raise WorkerError(str(detail or "agent-browser command failed."), status=502)
        return payload.get("data") or {}

    async def stop(self) -> None:
        for session in list(self.sessions.values()):
            await self._close_session(session)
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
            resume_path = None
            if resume:
                suffix = Path(resume_filename or "resume.pdf").suffix or ".pdf"
                handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                handle.write(resume)
                handle.close()
                resume_path = handle.name
            agent_session = "jp-application-" + re.sub(r"[^a-zA-Z0-9_-]", "", application_id)
            try:
                opened = await self._agent_browser(agent_session, "open", url)
                cdp = await self._agent_browser(agent_session, "get", "cdp-url")
                browser = await self._playwright.chromium.connect_over_cdp(cdp["cdpUrl"])
                if not browser.contexts:
                    raise WorkerError("agent-browser did not create a Chrome context.", status=502)
                context = browser.contexts[0]
                target_url = opened.get("url") or url
                page = next((candidate for candidate in context.pages if candidate.url == target_url), None)
                if page is None:
                    raise WorkerError("Could not attach to the active agent-browser tab.", status=502)
                page.set_default_timeout(NAV_TIMEOUT_MS)
                await page.wait_for_timeout(700)
                await self._navigate_to_application_target(page, url)
                detected = await page.evaluate(FIELD_JS)
                stream = await self._agent_browser(agent_session, "stream", "status")
                stream_port = stream.get("port")
                if not isinstance(stream_port, int) or not 1 <= stream_port <= 65535:
                    raise WorkerError("agent-browser did not expose a live browser stream.", status=502)
                session = Session(
                    id=uuid.uuid4().hex,
                    application_id=application_id,
                    page=page,
                    context=context,
                    browser=browser,
                    agent_session=agent_session,
                    stream_port=stream_port,
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
                    "stream_port": stream_port,
                    "fields": detected["fields"],
                    "buttons": detected["buttons"],
                    "detected": {
                        "has_captcha": session.captcha,
                        "requires_login": session.login,
                        "has_application_form": bool(detected.get("hasApplicationForm")),
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
                            "No employer application form was found at this job listing. Use the visible Apply link or choose another listing." if not detected.get("hasApplicationForm") else None,
                        )
                        if warning
                    ],
                    "screenshot": screenshot,
                }
            except WorkerError:
                await self._agent_browser(agent_session, "close")
                raise
            except Exception as exc:
                await self._agent_browser(agent_session, "close")
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

    async def screenshot(self, session_id: str) -> dict:
        session = self._get(session_id)
        return await self._screenshot(session.page)

    async def browser_action(self, session_id: str, event: dict) -> dict:
        """Apply one bounded mouse/keyboard action to a user-controlled page."""
        session = self._get(session_id)
        self._validate_stream_event(event)
        kind = event["type"]
        if kind == "input_mouse":
            action = event["eventType"]
            x, y = float(event.get("x", 0)), float(event.get("y", 0))
            if action == "mouseMoved":
                await session.page.mouse.move(x, y)
            elif action == "mousePressed":
                target = await session.page.evaluate(
                    """([x, y]) => {
                      const node = document.elementFromPoint(x, y);
                      const control = node?.closest('button,a,[role=button],input[type=submit],input[type=button]') || node;
                      return {
                        text: (control?.innerText || control?.getAttribute('aria-label') || control?.value || '').trim(),
                        type: control?.getAttribute('type') || '',
                        tag: control?.tagName || ''
                      };
                    }""",
                    [x, y],
                )
                if str(target.get("type", "")).lower() == "submit" or re.search(
                    r"submit|send application|accept terms|confirm application|finish application|complete application",
                    str(target.get("text", "")),
                    re.I,
                ):
                    raise WorkerError("Stopped before a final application or terms control.", status=409)
                await session.page.mouse.click(x, y, button=event.get("button", "left"))
            elif action == "mouseWheel":
                await session.page.mouse.wheel(float(event.get("deltaX", 0)), float(event.get("deltaY", 0)))
        elif kind == "input_keyboard":
            if event["eventType"] == "char":
                await session.page.keyboard.insert_text(str(event.get("text", "")))
            elif event["eventType"] == "keyDown":
                await session.page.keyboard.down(str(event["key"]))
            else:
                await session.page.keyboard.up(str(event["key"]))
        else:
            raise WorkerError("This browser action is not supported.")
        await session.page.wait_for_timeout(350)
        session.last_used = time.time()
        return {
            "url": session.page.url,
            "title": await session.page.title(),
            "screenshot": await self._screenshot(session.page),
        }

    async def _navigate_to_application_target(self, page: Page, original_url: str) -> None:
        """Follow one visible Apply link when a source listing points to an employer form."""
        try:
            existing = await page.evaluate(FIELD_JS)
            if existing.get("hasApplicationForm"):
                return
            links = await page.evaluate(APPLY_LINK_JS)
            target = next((item for item in links if item.get("href") and item["href"].rstrip("/") != page.url.rstrip("/")), None)
            if target:
                assert_safe_url(target["href"], ALLOW_PRIVATE_TARGETS)
                await page.goto(target["href"], wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                logger.info("Followed application link from %s to %s", original_url, page.url)
            await self._activate_application_form_tab(page)
        except WorkerError:
            raise
        except Exception as exc:
            logger.info("Could not follow application link from %s: %s", original_url, type(exc).__name__)

    async def _activate_application_form_tab(self, page: Page) -> None:
        """Dismiss only necessary-cookie notices and reveal a clearly labelled Apply tab."""
        necessary = page.get_by_role("button", name=re.compile(r"^agree to necessary$", re.I))
        if await necessary.count() and await necessary.first.is_visible():
            await necessary.first.click()
            await page.wait_for_timeout(250)

        tabs = page.locator('button[aria-selected="false"]')
        for index in range(await tabs.count()):
            tab = tabs.nth(index)
            try:
                text = (await tab.inner_text()).strip().lower()
                if text == "apply" and await tab.is_visible():
                    await tab.click()
                    await page.wait_for_timeout(350)
                    break
            except Exception:
                continue

    async def browser_stream(self, session_id: str, websocket) -> None:
        """Proxy agent-browser's live viewport and mouse/keyboard input."""
        session = self._get(session_id)
        try:
            async with websocket_connect(
                f"ws://127.0.0.1:{session.stream_port}/?pacing=ack&maxFps=12"
            ) as upstream:
                async def frames() -> None:
                    while True:
                        await websocket.send_text(await upstream.recv())
                        session.last_used = time.time()

                async def inputs() -> None:
                    while True:
                        message = await websocket.receive_text()
                        try:
                            event = json.loads(message)
                        except json.JSONDecodeError as exc:
                            raise WorkerError("Invalid browser input message.") from exc
                        self._validate_stream_event(event)
                        kind = event["type"]
                        if kind == "input_mouse":
                            action = event["eventType"]
                            x, y = float(event.get("x", 0)), float(event.get("y", 0))
                            if action == "mouseMoved":
                                await session.page.mouse.move(x, y)
                            elif action == "mousePressed":
                                await session.page.mouse.move(x, y)
                                await session.page.mouse.down(button=event.get("button", "left"))
                            elif action == "mouseReleased":
                                # click() already releases the button; preserve explicit release for drags.
                                await session.page.mouse.up(button=event.get("button", "left"))
                            elif action == "mouseWheel":
                                await session.page.mouse.wheel(
                                    float(event.get("deltaX", 0)), float(event.get("deltaY", 0))
                                )
                        elif kind == "input_keyboard":
                            if event["eventType"] == "char":
                                await session.page.keyboard.insert_text(str(event.get("text", "")))
                            elif event["eventType"] == "keyDown":
                                await session.page.keyboard.down(str(event["key"]))
                            else:
                                await session.page.keyboard.up(str(event["key"]))
                        else:
                            await upstream.send(json.dumps(event))

                tasks = [asyncio.create_task(frames()), asyncio.create_task(inputs())]
                try:
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        exception = task.exception()
                        if exception:
                            raise exception
                finally:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as exc:
            if isinstance(exc, WorkerError):
                raise
            logger.info("Browser viewport websocket closed: %s", type(exc).__name__)

    @staticmethod
    def _validate_stream_event(event: dict) -> None:
        if not isinstance(event, dict):
            raise WorkerError("Invalid browser input message.")
        if event.get("type") == "ack":
            if not isinstance(event.get("seq"), int):
                raise WorkerError("Invalid browser frame acknowledgement.")
            return
        if event.get("type") == "config":
            if event.get("pacing") not in {None, "ack", "push"}:
                raise WorkerError("Invalid browser stream configuration.")
            return
        if event.get("type") == "input_mouse":
            if event.get("eventType") not in {"mousePressed", "mouseReleased", "mouseMoved", "mouseWheel"}:
                raise WorkerError("Unsupported mouse event.")
            for key in ("x", "y", "deltaX", "deltaY"):
                if key in event and (not isinstance(event[key], (int, float)) or abs(event[key]) > 10000):
                    raise WorkerError("Mouse coordinates are invalid.")
            return
        if event.get("type") == "input_keyboard":
            if event.get("eventType") not in {"keyDown", "keyUp", "char"}:
                raise WorkerError("Unsupported keyboard event.")
            if "text" in event and len(str(event["text"])) > 2000:
                raise WorkerError("Keyboard input is too long.")
            return
        raise WorkerError("Unsupported browser input.")

    async def stats(self) -> dict:
        await self._gc()
        return {
            "browser": self._playwright is not None,
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
            await self._agent_browser(session.agent_session, "close")
        except Exception:
            pass
        try:
            await session.browser.close()
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
