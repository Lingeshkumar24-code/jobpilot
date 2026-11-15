import os
import sys
import tempfile
from pathlib import Path

# Configure the worker before importing app/automation.
NONCE_DB = str(Path(tempfile.gettempdir()) / f"jobpilot-test-nonces-{os.getpid()}.sqlite3")
os.environ.setdefault("WORKER_SECRET", "test-worker-secret")
os.environ.setdefault("APPROVAL_SIGNING_SECRET", "test-approval-secret")
os.environ.setdefault("ALLOW_PRIVATE_TARGETS", "true")
os.environ.setdefault("NONCE_DB", NONCE_DB)
os.environ.setdefault("MAX_SESSIONS", "50")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
