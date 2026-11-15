"""
Central application settings, loaded from environment variables / .env.

Nothing secret has a usable default: JWT_SECRET and APPROVAL_SIGNING_SECRET
are blank, and the app refuses to start in production unless they are set.
All booleans that could weaken safety default to the safe value.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    APP_NAME: str = "JobPilot AI"
    ENVIRONMENT: str = "development"  # development | staging | production
    APP_BASE_URL: str = "http://localhost:8000"
    FRONTEND_BASE_URL: str = "http://localhost:3000"

    # Comma-separated list. Credentials are allowed only for these origins.
    CORS_ORIGINS: str = "http://localhost:3000"

    # Database (PostgreSQL in every real environment; tests may use SQLite)
    DATABASE_URL: str = "postgresql+asyncpg://jobpilot:jobpilot@localhost:5432/jobpilot"
    DATABASE_POOL_SIZE: int = 5
    REDIS_URL: str | None = None

    # Auth
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
    SESSION_COOKIE_NAME: str = "jobpilot_session"
    COOKIE_SECURE: bool = False  # must be True behind HTTPS

    # Storage
    STORAGE_BACKEND: str = "auto"  # auto | s3 | local
    LOCAL_STORAGE_DIR: str = str(BASE_DIR / "var" / "storage")
    AWS_REGION: str = "ap-south-1"
    S3_BUCKET_RESUMES: str = "jobpilot-ai-resumes-dev"
    S3_ENDPOINT_URL: str | None = None  # set for LocalStack/MinIO
    S3_PRESIGN_EXPIRE_SECONDS: int = 300
    MAX_RESUME_BYTES: int = 5 * 1024 * 1024
    MAX_RESUME_PAGES: int = 20

    # AI providers. When neither is configured the deterministic
    # (rule-based) implementations are used and clearly labelled as such.
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-2.0-flash"
    GEMINI_EMBED_MODEL: str = "text-embedding-004"
    OPENROUTER_API_KEY: str | None = None
    OPENROUTER_MODEL: str = "nvidia/nemotron-3.5-super-vl:free"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OLLAMA_BASE_URL: str | None = None
    OLLAMA_MODEL: str = "llama3.1"
    LLM_TIMEOUT_SECONDS: int = 45
    EMBEDDINGS_ENABLED: bool = True
    PGVECTOR_ENABLED: bool = False

    # Job discovery
    JOB_HTTP_TIMEOUT_SECONDS: int = 15
    JOB_MAX_RESULTS_PER_SOURCE: int = 50
    JOB_USER_AGENT: str = "JobPilotAI/1.0 (+contact: set JOB_USER_AGENT)"
    JOB_MAX_POSTING_AGE_DAYS: int = 60
    GREENHOUSE_BOARDS: str = ""  # comma-separated board tokens
    LEVER_SITES: str = ""  # comma-separated Lever site tokens
    REMOTEOK_ENABLED: bool = True
    ARBEITNOW_ENABLED: bool = True
    REMOTIVE_ENABLED: bool = True
    FIRECRAWL_API_KEY: str | None = None
    FIRECRAWL_BASE_URL: str = "https://api.firecrawl.dev/v2"
    FIRECRAWL_MAX_RESULTS: int = 10

    # Credentialed sources: only used when you are authorized to use them.
    LINKEDIN_API_TOKEN: str | None = None
    LINKEDIN_API_URL: str | None = None
    INDEED_API_KEY: str | None = None
    INDEED_API_URL: str | None = None
    NAUKRI_API_KEY: str | None = None
    NAUKRI_API_URL: str | None = None

    # Matching
    MATCH_THRESHOLD: float = 55.0
    MATCH_WEIGHTS: str = "skills=0.45,role=0.20,location=0.15,experience=0.10,salary=0.05,recency=0.05"

    # Browser automation
    BROWSER_WORKER_URL: str = "http://localhost:8100"
    BROWSER_WORKER_SECRET: str = ""
    APPROVAL_SIGNING_SECRET: str = ""
    APPROVAL_TOKEN_TTL_MINUTES: int = 60
    BROWSER_ALLOW_PRIVATE_TARGETS: bool = False  # true only for the local mock-site tests

    # n8n
    N8N_WEBHOOK_BASE_URL: str | None = None
    N8N_WEBHOOK_SECRET: str = ""

    # Rate limiting (in-process; API Gateway/Redis handles this at scale)
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_AUTH_PER_MINUTE: int = 20
    RATE_LIMIT_SEARCH_PER_MINUTE: int = 30
    RATE_LIMIT_WRITE_PER_MINUTE: int = 120

    # Safety flag: must stay False. Approval is always required.
    ALLOW_AUTO_SUBMIT: bool = False

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def greenhouse_boards(self) -> list[str]:
        return [b.strip() for b in self.GREENHOUSE_BOARDS.split(",") if b.strip()]

    @property
    def lever_sites(self) -> list[str]:
        return [s.strip() for s in self.LEVER_SITES.split(",") if s.strip()]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # A missing signing secret is a development convenience, never a
        # production one: refuse to run insecure in a real deployment.
        if self.ENVIRONMENT == "production":
            missing = [
                name
                for name in ("JWT_SECRET", "APPROVAL_SIGNING_SECRET", "BROWSER_WORKER_SECRET")
                if not getattr(self, name)
            ]
            if missing:
                raise RuntimeError(
                    f"Refusing to start in production without: {', '.join(missing)}"
                )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
