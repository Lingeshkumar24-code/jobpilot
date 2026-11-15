"""
Deliberately simple local mock application site used by the browser-worker
tests. It never leaves 127.0.0.1 and exists so automation can be tested
without touching a real employer's application form.

Endpoints:
  /apply                 full form, confirms on POST
  /apply-unknown         required field the worker cannot know
  /no-confirmation       POST succeeds but shows no confirmation text
  /captcha               reCAPTCHA widget
  /login                 password field (login wall)
"""
from __future__ import annotations

import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SUBMISSIONS: list[dict] = []
LOCK = threading.Lock()

FORM = """
<form method="post" action="{action}">
  <div><label for="first_name">First name *</label><input id="first_name" name="first_name" required></div>
  <div><label for="last_name">Last name *</label><input id="last_name" name="last_name" required></div>
  <div><label for="email">Email *</label><input id="email" name="email" type="email" required></div>
  <div><label for="phone">Phone</label><input id="phone" name="phone" type="tel"></div>
  <div><label for="country">Country *</label>
    <select id="country" name="country" required>
      <option value="">Select...</option>
      <option value="IN">India</option>
      <option value="US">United States</option>
      <option value="GB">United Kingdom</option>
    </select>
  </div>
  <div><label for="cover_letter">Cover letter *</label><textarea id="cover_letter" name="cover_letter" required></textarea></div>
  <div><label for="resume">Resume *</label><input id="resume" name="resume" type="file" accept=".pdf,.docx" required></div>
  <div><label><input type="checkbox" name="agree" required> I agree to the privacy policy *</label></div>
  {extra}
  <button type="submit">Submit application</button>
</form>
"""

PAGE = """<!doctype html>
<html><head><title>{title}</title></head>
<body><h1>{heading}</h1>{body}</body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "JobPilotMock/1.0"

    def log_message(self, format, *args):  # noqa: A002 - silence test server
        return

    def do_GET(self):  # noqa: N802
        if self.path == "/apply":
            body = PAGE.format(
                title="Apply - Mock Company",
                heading="Apply for AI Engineer",
                body=FORM.format(action="/apply", extra=""),
            )
            self._send(body)
        elif self.path == "/apply-unknown":
            extra = (
                '<div><label for="portfolio_passcode">Portfolio passcode *</label>'
                '<input id="portfolio_passcode" name="portfolio_passcode" required></div>'
            )
            body = PAGE.format(
                title="Apply - Mock Company",
                heading="Apply for AI Engineer",
                body=FORM.format(action="/apply-unknown", extra=extra),
            )
            self._send(body)
        elif self.path == "/no-confirmation":
            body = PAGE.format(
                title="Apply - Mock Company",
                heading="Apply for AI Engineer",
                body=FORM.format(action="/no-confirmation", extra=""),
            )
            self._send(body)
        elif self.path == "/thank-you":
            reference = uuid.uuid4().hex[:8].upper()
            body = PAGE.format(
                title="Thank you",
                heading="Thank you for applying!",
                body=f"<p>Your application has been received. Reference: {reference}</p>",
            )
            self._send(body)
        elif self.path == "/captcha":
            body = PAGE.format(
                title="Apply",
                heading="Apply for AI Engineer",
                body='<div class="g-recaptcha" data-sitekey="mock"></div>'
                + FORM.format(action="/apply", extra=""),
            )
            self._send(body)
        elif self.path == "/login":
            body = PAGE.format(
                title="Sign in",
                heading="Sign in to continue",
                body='<form><label for="email">Email</label><input id="email" name="email">'
                '<label for="password">Password</label><input id="password" name="password" type="password">'
                '<button type="submit">Sign in</button></form>',
            )
            self._send(body)
        else:
            self.send_error(404)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length", "0") or 0)
        raw = self.rfile.read(length) if length else b""
        with LOCK:
            SUBMISSIONS.append({"path": self.path, "body": raw.decode("utf-8", "ignore")})

        if self.path == "/apply":
            self.send_response(303)
            self.send_header("Location", "/thank-you")
            self.end_headers()
            return
        if self.path == "/apply-unknown":
            if b"portfolio_passcode" not in raw:
                self._send(
                    PAGE.format(
                        title="Error",
                        heading="Please fix the errors",
                        body="<p>Portfolio passcode is required.</p>",
                    )
                )
                return
            self.send_response(303)
            self.send_header("Location", "/thank-you")
            self.end_headers()
            return
        if self.path == "/no-confirmation":
            self._send(
                PAGE.format(
                    title="Application",
                    heading="Application",
                    body="<p>Your form was processed.</p>",
                )
            )
            return
        self.send_error(404)

    def _send(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_server(port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


if __name__ == "__main__":
    server, url = start_server(8765)
    print(f"Mock application site: {url}/apply")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()
