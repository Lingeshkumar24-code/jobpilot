"""Authenticated, user-controlled browser sessions for job-board search."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from pydantic import BaseModel, Field

from app.api.v1.deps import get_current_user
from app.core.config import settings
from app.core.rate_limit import limit_search
from app.models.core import User
from app.services.browser_client import BrowserClient, BrowserWorkerError
from app.services.llm import llm

logger = logging.getLogger(__name__)
router = APIRouter()


class OpenBrowserSearchRequest(BaseModel):
    provider: str = Field(pattern="^(google|linkedin|indeed)$")
    query: str = Field(min_length=3, max_length=500)


class DriveBrowserSearchRequest(BaseModel):
    ticket: str = Field(min_length=20, max_length=5000)
    max_actions: int = Field(default=6, ge=1, le=8)
    allow_screenshot_to_openrouter: bool = False


@router.post("/search/open", dependencies=[Depends(limit_search)])
async def open_browser_search(
    payload: OpenBrowserSearchRequest,
    current_user: User = Depends(get_current_user),
):
    client = BrowserClient()
    try:
        opened = await client.open_browser_search(payload.provider, payload.query.strip())
    except BrowserWorkerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    worker_id = str(opened.get("worker_url") or client.base_url).rstrip("/")
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    ticket = jwt.encode(
        {
            "typ": "browser_search_stream",
            "sub": str(current_user.id),
            "session_id": opened["session_id"],
            "worker_id": worker_id,
            "provider": payload.provider,
            "query": payload.query.strip(),
            "exp": expires_at,
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {
        "session_id": opened["session_id"],
        "provider": payload.provider,
        "query": payload.query.strip(),
        "url": opened.get("url"),
        "title": opened.get("title"),
        "ticket": ticket,
        "expires_at": expires_at.isoformat(),
    }


@router.post("/search/drive", dependencies=[Depends(limit_search)])
async def drive_browser_search(
    payload: DriveBrowserSearchRequest,
    current_user: User = Depends(get_current_user),
):
    if not llm.openrouter_key:
        raise HTTPException(status_code=503, detail="Set an OpenRouter vision model to enable mouse-driven browser search.")
    if not payload.allow_screenshot_to_openrouter:
        raise HTTPException(status_code=400, detail="Confirm that the current browser screenshots may be sent to OpenRouter for visual guidance.")
    try:
        claims = jwt.decode(payload.ticket, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        if claims.get("typ") != "browser_search_stream" or claims.get("sub") != str(current_user.id):
            raise JWTError("Ticket does not belong to this user")
        session_id = claims["session_id"]
        worker_id = claims["worker_id"].rstrip("/")
        provider = claims.get("provider", "job site")
    except (JWTError, KeyError, TypeError):
        raise HTTPException(status_code=401, detail="The browser session expired. Open the search again.")

    client = BrowserClient(base_url=worker_id)
    try:
        screenshot = await client.screenshot(session_id)
        steps = []
        outcome = "Reached the action limit; review the visible browser and continue manually."
        for _ in range(payload.max_actions):
            image = (screenshot.get("screenshot") or {}).get("base64")
            if not image:
                raise HTTPException(status_code=502, detail="The browser did not provide a screenshot.")
            prompt = (
                f"Find AI-related jobs for this search: {claims.get('query', '')}. Current site: {provider}. "
                "Use only visible page controls. Click a relevant job result and, if appropriate, its Apply link "
                "to reach the employer application form. Do not sign in, solve a CAPTCHA, enter personal details, "
                "upload a file, submit, or accept terms. If blocked by login/CAPTCHA or if the application form "
                "is visible, return ask_user or done. Return JSON only."
            )
            decision = await llm.generate_browser_action(prompt, image)
            action = (decision.data if decision else {}).get("action", "ask_user")
            target = str((decision.data if decision else {}).get("target") or "")[:160]
            reason = str((decision.data if decision else {}).get("reason") or "")[:240]
            if action in {"done", "ask_user"}:
                outcome = reason or ("The page needs your attention." if action == "ask_user" else "The application page is ready for review.")
                steps.append({"action": action, "target": target, "reason": outcome})
                break
            if re.search(r"submit|send application|accept terms|confirm|finish application", target, re.I):
                outcome = "Stopped before a final application or terms control."
                steps.append({"action": "blocked", "target": target, "reason": outcome})
                break
            try:
                if action == "click":
                    x, y = int(decision.data["x"]), int(decision.data["y"])
                    if not (0 <= x <= 4096 and 0 <= y <= 2160):
                        raise ValueError("coordinate out of range")
                    event = {"type": "input_mouse", "eventType": "mousePressed", "x": x, "y": y, "button": "left"}
                elif action == "scroll":
                    delta_y = int(decision.data.get("delta_y", 500))
                    if not (-1200 <= delta_y <= 1200):
                        raise ValueError("scroll out of range")
                    event = {"type": "input_mouse", "eventType": "mouseWheel", "x": 640, "y": 360, "deltaX": 0, "deltaY": delta_y}
                else:
                    outcome = "The visual agent returned an unsupported action; review the page manually."
                    steps.append({"action": "blocked", "target": target, "reason": outcome})
                    break
            except (KeyError, TypeError, ValueError):
                outcome = "The visual agent returned an invalid mouse action; review the page manually."
                steps.append({"action": "blocked", "target": target, "reason": outcome})
                break
            screenshot = await client.browser_search_action(session_id, event)
            steps.append({"action": action, "target": target, "reason": reason})
            outcome = reason or "Moved the browser to the next page."
        return {
            "provider": provider,
            "query": claims.get("query", ""),
            "steps": steps,
            "outcome": outcome,
            "url": screenshot.get("url"),
            "title": screenshot.get("title"),
            "screenshot": screenshot.get("screenshot"),
        }
    except BrowserWorkerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.websocket("/search/stream")
async def browser_search_stream(websocket: WebSocket):
    raw_ticket = websocket.query_params.get("ticket", "")
    try:
        claims = jwt.decode(raw_ticket, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        if claims.get("typ") != "browser_search_stream" or not claims.get("sub"):
            raise JWTError("Invalid browser search ticket")
        worker_id = claims["worker_id"].rstrip("/")
        parts = urlsplit(worker_id)
        if parts.hostname == "localhost":
            netloc = f"127.0.0.1:{parts.port}" if parts.port else "127.0.0.1"
            worker_id = urlunsplit((parts.scheme, netloc, parts.path, "", ""))
        session_id = claims["session_id"]
    except (JWTError, KeyError, TypeError):
        await websocket.close(code=4401, reason="Invalid or expired browser search ticket")
        return

    await websocket.accept()
    try:
        from websockets.asyncio.client import connect as websocket_connect

        worker_ws = worker_id.replace("http://", "ws://").replace("https://", "wss://")
        async with websocket_connect(
            f"{worker_ws}/v1/sessions/{session_id}/stream",
            additional_headers={"X-Worker-Secret": settings.BROWSER_WORKER_SECRET},
            max_size=8 * 1024 * 1024,
        ) as upstream:
            async def worker_to_user():
                while True:
                    await websocket.send_text(await upstream.recv())

            async def user_to_worker():
                while True:
                    await upstream.send(await websocket.receive_text())

            tasks = [asyncio.create_task(worker_to_user()), asyncio.create_task(user_to_worker())]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if not task.cancelled() and task.exception():
                        raise task.exception()
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Browser search stream failed")
        with contextlib.suppress(Exception):
            await websocket.close(code=1011, reason="Browser stream ended")
