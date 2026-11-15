import hashlib
import hmac
import time
import uuid

import pytest
from fastapi.testclient import TestClient

import mock_site
from app import app
from automation import WorkerError, assert_safe_url

WORKER_SECRET = "test-worker-secret"
APPROVAL_SECRET = "test-approval-secret"
HEADERS = {"X-Worker-Secret": WORKER_SECRET}

LABEL_VALUES = {
    "first name": "Arjun",
    "last name": "Sharma",
    "email": "arjun.sharma@example.com",
    "phone": "+91 98765 43210",
    "country": "India",
    "cover letter": "I have built Python and LLM applications and would like to contribute.",
}


def make_proof(application_id: str, nonce: str | None = None, expires_in: int = 300, secret: str = APPROVAL_SECRET) -> dict:
    nonce = nonce or uuid.uuid4().hex
    expires_at = int(time.time()) + expires_in
    token_hash = hashlib.sha256(b"approval-token").hexdigest()
    message = f"{application_id}:{token_hash}:{nonce}:{expires_at}"
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return {
        "application_id": application_id,
        "token_hash": token_hash,
        "nonce": nonce,
        "expires_at": expires_at,
        "signature": signature,
    }


def values_from(fields: list[dict]) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in fields:
        label = (field.get("label") or field.get("name") or "").lower()
        for key, value in LABEL_VALUES.items():
            if key in label:
                values[field["ref"]] = value
                break
        if "agree" in label or "privacy" in label:
            values[field["ref"]] = "true"
    return values


@pytest.fixture(scope="session")
def site_url():
    server, url = mock_site.start_server()
    yield url
    server.shutdown()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clear_submissions():
    mock_site.SUBMISSIONS.clear()
    yield


def analyze(client, site_url, path="/apply", application_id=None, with_resume=True):
    payload = {
        "url": f"{site_url}{path}",
        "application_id": application_id or str(uuid.uuid4()),
    }
    if with_resume:
        payload["resume"] = {
            "filename": "resume.pdf",
            "content_base64": "JVBERi0xLjQgdGVzdCByZXN1bWU=",
        }
    response = client.post("/v1/sessions/analyze", json=payload, headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def test_health_and_auth(client):
    assert client.get("/health").json()["status"] == "ok"
    response = client.post(
        "/v1/sessions/analyze",
        json={"url": "https://example.com", "application_id": "app-12345678"},
    )
    assert response.status_code == 401
    response = client.post(
        "/v1/sessions/analyze",
        json={"url": "https://example.com", "application_id": "app-12345678"},
        headers={"X-Worker-Secret": "wrong"},
    )
    assert response.status_code == 401


def test_analyze_detects_form_fields(client, site_url):
    data = analyze(client, site_url)
    labels = " ".join(field["label"].lower() for field in data["fields"])
    assert "first name" in labels
    assert "email" in labels
    assert "resume" in labels
    assert data["detected"]["file_inputs"] == 1
    assert data["detected"]["has_captcha"] is False
    assert data["detected"]["requires_login"] is False
    assert data["screenshot"]["base64"]
    assert any("submit" in button.lower() for button in data["buttons"])
    assert data["fields"][0]["ref"].startswith("f")


def test_fill_fields_and_resume(client, site_url):
    data = analyze(client, site_url)
    values = values_from(data["fields"])
    response = client.post(
        f"/v1/sessions/{data['session_id']}/fill",
        json={"values": values, "upload_resume": True},
        headers=HEADERS,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["resume_attached"] is True
    assert any("resume" in (item["label"] or "").lower() for item in body["filled"])
    assert not body["validation_errors"]


def test_submission_requires_valid_one_time_approval(client, site_url):
    application_id = str(uuid.uuid4())
    data = analyze(client, site_url, application_id=application_id)
    values = values_from(data["fields"])
    client.post(
        f"/v1/sessions/{data['session_id']}/fill",
        json={"values": values},
        headers=HEADERS,
    )

    # No approval at all.
    response = client.post(
        f"/v1/sessions/{data['session_id']}/submit",
        json={"application_id": application_id, "approval": make_proof(application_id)},
        headers={"X-Worker-Secret": "wrong"},
    )
    assert response.status_code == 401
    assert mock_site.SUBMISSIONS == []

    # Forged signature.
    forged = make_proof(application_id, secret="attacker-secret")
    response = client.post(
        f"/v1/sessions/{data['session_id']}/submit",
        json={"application_id": application_id, "approval": forged},
        headers=HEADERS,
    )
    assert response.status_code == 403
    assert mock_site.SUBMISSIONS == []

    # Expired approval.
    expired = make_proof(application_id, expires_in=-10)
    response = client.post(
        f"/v1/sessions/{data['session_id']}/submit",
        json={"application_id": application_id, "approval": expired},
        headers=HEADERS,
    )
    assert response.status_code == 403
    assert mock_site.SUBMISSIONS == []

    # Approval for a different application.
    other = make_proof(str(uuid.uuid4()))
    response = client.post(
        f"/v1/sessions/{data['session_id']}/submit",
        json={"application_id": application_id, "approval": other},
        headers=HEADERS,
    )
    assert response.status_code == 403
    assert mock_site.SUBMISSIONS == []

    # Valid, application-specific approval.
    proof = make_proof(application_id)
    response = client.post(
        f"/v1/sessions/{data['session_id']}/submit",
        json={"application_id": application_id, "approval": proof},
        headers=HEADERS,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "CONFIRMED"
    assert "thank you" in (body["evidence"]["matched_text"] or "").lower()
    assert len(mock_site.SUBMISSIONS) == 1

    # A second click is blocked, even with the same proof.
    response = client.post(
        f"/v1/sessions/{data['session_id']}/submit",
        json={"application_id": application_id, "approval": proof},
        headers=HEADERS,
    )
    assert response.status_code == 409
    assert len(mock_site.SUBMISSIONS) == 1


def test_nonce_is_single_use_across_sessions(client, site_url):
    application_id = str(uuid.uuid4())
    nonce = uuid.uuid4().hex
    first = analyze(client, site_url, application_id=application_id)
    client.post(f"/v1/sessions/{first['session_id']}/fill", json={"values": values_from(first["fields"])}, headers=HEADERS)
    proof = make_proof(application_id, nonce=nonce)
    response = client.post(
        f"/v1/sessions/{first['session_id']}/submit",
        json={"application_id": application_id, "approval": proof},
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert len(mock_site.SUBMISSIONS) == 1

    second = analyze(client, site_url, application_id=application_id)
    client.post(f"/v1/sessions/{second['session_id']}/fill", json={"values": values_from(second["fields"])}, headers=HEADERS)
    response = client.post(
        f"/v1/sessions/{second['session_id']}/submit",
        json={"application_id": application_id, "approval": proof},
        headers=HEADERS,
    )
    assert response.status_code == 409
    assert len(mock_site.SUBMISSIONS) == 1


def test_captcha_is_detected_and_blocks_submission(client, site_url):
    data = analyze(client, site_url, path="/captcha")
    assert data["detected"]["has_captcha"] is True
    assert data["warnings"]
    application_id = str(uuid.uuid4())
    # Session application id is set by analyze, so build the proof for it.
    session_id = data["session_id"]
    proof = make_proof(application_id)
    response = client.post(
        f"/v1/sessions/{session_id}/submit",
        json={"application_id": application_id, "approval": proof},
        headers=HEADERS,
    )
    assert response.status_code in {403, 409}


def test_login_wall_is_detected(client, site_url):
    data = analyze(client, site_url, path="/login")
    assert data["detected"]["requires_login"] is True
    assert any("login" in warning.lower() for warning in data["warnings"])


def test_validation_errors_block_submission(client, site_url):
    application_id = str(uuid.uuid4())
    data = analyze(client, site_url, application_id=application_id)
    # Only one field filled: the rest are required.
    first_ref = next(f["ref"] for f in data["fields"] if "first name" in f["label"].lower())
    client.post(
        f"/v1/sessions/{data['session_id']}/fill",
        json={"values": {first_ref: "Arjun"}},
        headers=HEADERS,
    )
    response = client.post(
        f"/v1/sessions/{data['session_id']}/submit",
        json={"application_id": application_id, "approval": make_proof(application_id)},
        headers=HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "VALIDATION_FAILED"
    assert body["missing_required"]
    assert mock_site.SUBMISSIONS == []


def test_unknown_submission_status_is_not_reported_as_confirmed(client, site_url):
    application_id = str(uuid.uuid4())
    data = analyze(client, site_url, path="/no-confirmation", application_id=application_id)
    client.post(
        f"/v1/sessions/{data['session_id']}/fill",
        json={"values": values_from(data["fields"])},
        headers=HEADERS,
    )
    response = client.post(
        f"/v1/sessions/{data['session_id']}/submit",
        json={"application_id": application_id, "approval": make_proof(application_id)},
        headers=HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "UNKNOWN_SUBMISSION_STATUS"
    assert body["evidence"]["reason"]
    assert len(mock_site.SUBMISSIONS) == 1


def test_required_unknown_field_is_flagged(client, site_url):
    data = analyze(client, site_url, path="/apply-unknown")
    labels = " ".join(field["label"].lower() for field in data["fields"])
    assert "portfolio passcode" in labels
    field = next(f for f in data["fields"] if "portfolio passcode" in f["label"].lower())
    assert field["required"] is True


def test_ssrf_guard_blocks_private_addresses():
    with pytest.raises(WorkerError):
        assert_safe_url("http://169.254.169.254/latest/meta-data/", allow_private=False)
    with pytest.raises(WorkerError):
        assert_safe_url("http://localhost:8000/", allow_private=False)
    with pytest.raises(WorkerError):
        assert_safe_url("file:///etc/passwd", allow_private=True)
