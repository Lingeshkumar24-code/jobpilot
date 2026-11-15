"""
Job discovery orchestration: fetch â†’ validate â†’ deduplicate â†’ persist â†’ score.

Invariants:
  * A listing is only stored when the source actually returned it. No mock
    listings, no generated jobs, no "example" rows.
  * ``last_verified_at`` is only set after a successful source response.
  * A source error never marks existing jobs inactive; it is reported.
  * Dedupe is deterministic: normalized URL/company/title/location hash,
    plus a cross-source merge on normalized company+title+location.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.core import CandidateProfile, Job, JobMatch, JobSkill, JobSource, UserPreference
from app.schemas.search import StructuredFilters
from app.services.job_sources import CONNECTORS, ConnectorResult, JobListing, source_metadata
from app.services.matching import score_job
from app.services.skills import extract_skills, normalize_skill

logger = logging.getLogger(__name__)

TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gh_src", "lever-source", "ref", "source"}


@dataclass
class DiscoveryOutcome:
    jobs: list[tuple[Job, JobMatch]] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fetched: int = 0
    stored: int = 0
    duplicates: int = 0


async def ensure_sources(db: AsyncSession) -> dict[str, JobSource]:
    existing = {source.connector_key: source for source in (await db.execute(select(JobSource))).scalars()}
    for meta in source_metadata():
        source = existing.get(meta["key"])
        if source is None:
            source = JobSource(
                name=meta["key"],
                connector_key=meta["key"],
                display_name=meta["display_name"],
                base_url=meta["base_url"],
                attribution=meta["attribution"],
                requires_credentials=meta["requires_credentials"],
                is_enabled=meta["configured"],
                notes=meta["notes"],
            )
            db.add(source)
            existing[meta["key"]] = source
        else:
            source.display_name = meta["display_name"]
            source.base_url = meta["base_url"]
            source.attribution = meta["attribution"]
            source.requires_credentials = meta["requires_credentials"]
            source.notes = meta["notes"]
    await db.flush()
    return existing


async def discover(
    db: AsyncSession,
    user,
    filters: StructuredFilters,
    *,
    source_keys: list[str] | None = None,
    limit: int = 25,
) -> DiscoveryOutcome:
    outcome = DiscoveryOutcome()
    sources = await ensure_sources(db)

    prefs_row = (
        await db.execute(select(UserPreference).where(UserPreference.user_id == user.id))
    ).scalar_one_or_none()
    prefs = {
        "greenhouse_boards": (prefs_row.greenhouse_boards if prefs_row else None),
        "lever_sites": (prefs_row.lever_sites if prefs_row else None),
    }

    selected: list[str] = []
    if source_keys:
        for key in source_keys:
            if key not in CONNECTORS:
                outcome.warnings.append(f"Unknown source '{key}' ignored.")
                continue
            selected.append(key)
    else:
        selected = [
            key
            for key, connector in CONNECTORS.items()
            if connector.is_configured()
            and not (
                (key == "remoteok" and not settings.REMOTEOK_ENABLED)
                or (key == "arbeitnow" and not settings.ARBEITNOW_ENABLED)
                or (key == "remotive" and not settings.REMOTIVE_ENABLED)
            )
        ]

    fetch_limit = min(max(limit * 2, 25), settings.JOB_MAX_RESULTS_PER_SOURCE)
    tasks = [
        _fetch_one(CONNECTORS[key], filters.model_dump(), fetch_limit, prefs) for key in selected
    ]
    results: list[ConnectorResult] = await asyncio.gather(*tasks) if tasks else []

    # Sources that were not even attempted are reported, not hidden.
    for key, connector in CONNECTORS.items():
        if key not in selected:
            reason = (
                connector.not_configured_reason()
                or "Disabled in configuration."
            )
            outcome.sources.append(
                {
                    "key": key,
                    "display_name": connector.display_name,
                    "status": "skipped",
                    "count": 0,
                    "message": reason,
                    "attribution": connector.attribution,
                    "requires_credentials": connector.requires_credentials,
                    "duration_ms": 0,
                }
            )
            outcome.warnings.append(f"{connector.display_name}: {reason}")

    source_by_key = sources
    now = datetime.now(timezone.utc)

    for result in results:
        connector = CONNECTORS[result.source_key]
        source_row = source_by_key.get(result.source_key)
        if source_row is not None:
            if result.ok:
                source_row.last_synced_at = now
                source_row.last_sync_error = None
            else:
                source_row.last_sync_error = result.error or result.skipped_reason

        status = "ok"
        if result.skipped_reason:
            status = "skipped"
        elif result.error:
            status = "error"
        elif not result.listings:
            status = "empty"
        outcome.sources.append(
            {
                "key": result.source_key,
                "display_name": result.display_name,
                "status": status,
                "count": len(result.listings),
                "message": result.error or result.skipped_reason or "",
                "attribution": connector.attribution,
                "requires_credentials": connector.requires_credentials,
                "duration_ms": result.duration_ms,
            }
        )
        for warning in result.warnings:
            outcome.warnings.append(warning)
        if result.error:
            outcome.warnings.append(f"{result.display_name}: {result.error}")

        for listing in result.listings:
            outcome.fetched += 1
            if _too_old(listing):
                continue
            job, duplicate = await _persist_listing(db, source_row, listing)
            if job is None:
                continue
            outcome.stored += 1
            if duplicate:
                outcome.duplicates += 1

    await db.flush()

    # Score every active job against the user (bounded to recent jobs).
    profile = (
        await db.execute(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
    ).scalar_one_or_none()
    matches: list[tuple[Job, JobMatch]] = []
    if profile is not None:
        recent = (
            await db.execute(
                select(Job)
                .where(Job.is_active.is_(True), Job.deleted_at.is_(None))
                .order_by(Job.last_seen_at.desc().nullslast())
                .limit(500)
            )
        ).scalars().all()
        skills_by_job = await _skills_map(db, [job.id for job in recent])
        for job in recent:
            score, explanation = score_job(profile, job, skills_by_job.get(job.id, []))
            passed, notes = passes_filters(job, filters, skills_by_job.get(job.id, []))
            if not passed:
                continue
            explanation["filter_notes"] = notes
            match = await _upsert_match(db, user.id, job.id, score, explanation)
            matches.append((job, match))

    matches.sort(key=lambda pair: (pair[1].match_score, pair[0].posted_at or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    outcome.jobs = matches[:limit]
    await db.flush()
    return outcome


async def _fetch_one(connector, filters: dict, limit: int, prefs: dict) -> ConnectorResult:
    started = datetime.now(timezone.utc)
    if not connector.is_configured():
        return ConnectorResult(
            source_key=connector.key,
            display_name=connector.display_name,
            skipped_reason=connector.not_configured_reason(),
        )
    try:
        result = await asyncio.wait_for(
            connector.fetch(filters, limit, prefs),
            timeout=settings.JOB_HTTP_TIMEOUT_SECONDS * 3,
        )
    except asyncio.TimeoutError:
        result = ConnectorResult(
            source_key=connector.key,
            display_name=connector.display_name,
            error="Source timed out.",
        )
    except Exception as exc:  # network errors, bad payloads
        logger.warning("Connector %s failed: %s", connector.key, type(exc).__name__)
        result = ConnectorResult(
            source_key=connector.key,
            display_name=connector.display_name,
            error=f"Source request failed ({type(exc).__name__}).",
        )
    result.duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    return result


async def _persist_listing(
    db: AsyncSession, source: JobSource | None, listing: JobListing
) -> tuple[Job | None, bool]:
    listing = listing.normalize()
    if source is None or not listing.title or not listing.company:
        return None, False
    if not _valid_url(listing.application_url):
        return None, False

    key = dedup_key(listing.company, listing.title, listing.location, listing.application_url)
    now = datetime.now(timezone.utc)

    existing = (await db.execute(select(Job).where(Job.dedup_key == key))).scalar_one_or_none()
    duplicate = existing is not None
    if existing is None:
        existing = await _find_fuzzy_duplicate(db, listing)
        duplicate = existing is not None and (key != existing.dedup_key)

    if existing is not None:
        _update_existing(existing, listing, now, is_duplicate=duplicate)
        return existing, duplicate

    job = Job(
        source_id=source.id,
        external_id=listing.external_id,
        title=listing.title,
        company=listing.company,
        location=listing.location,
        salary_min=listing.salary_min,
        salary_max=listing.salary_max,
        salary_currency=listing.salary_currency,
        work_mode=listing.work_mode,
        experience_requirement=listing.experience_requirement,
        employment_type=listing.employment_type,
        description=listing.description,
        description_html=listing.description_html,
        application_url=listing.application_url,
        source_url=listing.source_url,
        posted_date=listing.posted_at,
        posted_at=listing.posted_at,
        first_seen_at=now,
        last_seen_at=now,
        last_verified_at=now,
        is_active=True,
        dedup_key=key,
        duplicate_sources=[],
        raw_payload=listing.raw,
    )
    db.add(job)
    await db.flush()

    for skill in dict.fromkeys(listing.skills or extract_skills(f"{listing.title} {listing.description or ''}")):
        db.add(JobSkill(job_id=job.id, skill=skill, normalized_skill=normalize_skill(skill)))
    await db.flush()
    return job, False


def _update_existing(job: Job, listing: JobListing, now: datetime, *, is_duplicate: bool) -> None:
    # Never overwrite a known field with a missing one.
    for attribute in (
        "location",
        "salary_min",
        "salary_max",
        "salary_currency",
        "work_mode",
        "experience_requirement",
        "employment_type",
        "description",
    ):
        value = getattr(listing, attribute)
        if value not in (None, "") and not getattr(job, attribute):
            setattr(job, attribute, value)
    job.last_seen_at = now
    job.last_verified_at = now
    job.is_active = True
    if is_duplicate:
        sources = list(job.duplicate_sources or [])
        marker = {"source": listing.source_key, "url": listing.application_url, "external_id": listing.external_id}
        if marker not in sources:
            sources.append(marker)
            job.duplicate_sources = sources


def _too_old(listing: JobListing) -> bool:
    if listing.posted_at is None:
        return False
    posted = listing.posted_at
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    return posted < datetime.now(timezone.utc) - timedelta(days=settings.JOB_MAX_POSTING_AGE_DAYS)


async def _find_fuzzy_duplicate(db: AsyncSession, listing: JobListing) -> Job | None:
    query = select(Job).where(
        func.lower(Job.company) == listing.company.lower(),
        func.lower(Job.title) == listing.title.lower(),
    )
    if listing.location:
        query = query.where(func.lower(func.coalesce(Job.location, "")) == listing.location.lower())
    return (await db.execute(query.limit(1))).scalar_one_or_none()


async def _skills_map(db: AsyncSession, job_ids: list) -> dict:
    if not job_ids:
        return {}
    rows = (
        await db.execute(select(JobSkill).where(JobSkill.job_id.in_(job_ids)))
    ).scalars().all()
    result: dict = {}
    for row in rows:
        result.setdefault(row.job_id, []).append(row.skill)
    return result


async def _upsert_match(db: AsyncSession, user_id, job_id, score: float, explanation: dict) -> JobMatch:
    match = (
        await db.execute(
            select(JobMatch).where(JobMatch.user_id == user_id, JobMatch.job_id == job_id)
        )
    ).scalar_one_or_none()
    if match is None:
        match = JobMatch(user_id=user_id, job_id=job_id, match_score=score, match_explanation=explanation)
        db.add(match)
    else:
        match.match_score = score
        match.match_explanation = explanation
    await db.flush()
    return match


def dedup_key(company: str, title: str, location: str | None, url: str) -> str:
    payload = "|".join(
        [
            _normalize_company(company),
            _normalize(title),
            _normalize(location or ""),
            normalize_url(url),
        ]
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def normalize_url(url: str) -> str:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return url.strip().lower()
    query = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() not in TRACKING_PARAMS]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            urlencode(query),
            "",
        )
    )


def _normalize_company(value: str) -> str:
    text = _normalize(value)
    text = re.sub(
        r"\b(pvt|private|ltd|limited|inc|llc|corp|corporation|technologies|technology|solutions|labs|systems|india)\b",
        "",
        text,
    )
    return re.sub(r"\s+", "", text)


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _valid_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


def passes_filters(job: Job, filters: StructuredFilters, job_skills: list[str]) -> tuple[bool, list[str]]:
    """Post-fetch filtering. Unknown values are kept and annotated, never guessed."""
    notes: list[str] = []
    title = (job.title or "").lower()
    description = (job.description or "").lower()
    haystack = f"{title} {description}"

    if filters.role:
        if not any(_role_matches(role, title) for role in filters.role):
            return False, notes

    if filters.location:
        location_text = (job.location or "").lower()
        if job.work_mode == "remote":
            notes.append("Remote role; location filter treated as compatible.")
        elif not _location_matches(filters.location, location_text, job.work_mode):
            return False, notes

    if filters.work_mode:
        actual = job.work_mode or _infer_work_mode(haystack)
        if actual and actual not in filters.work_mode:
            return False, notes
        if not actual:
            if "remote" in filters.work_mode:
                return False, notes
            notes.append("Work mode not stated by the source; shown for review.")

    if filters.employment_type:
        actual = job.employment_type or _infer_employment_type(haystack)
        if actual and actual not in filters.employment_type:
            return False, notes
        if not actual:
            if "internship" in filters.employment_type:
                return False, notes
            notes.append("Employment type not stated by the source; shown for review.")

    if filters.minimum_salary is not None:
        if job.salary_max is None and job.salary_min is None:
            notes.append("Salary not disclosed by the employer.")
        elif (job.salary_currency or "INR").upper() != "INR":
            notes.append(f"Salary is listed in {job.salary_currency}; not compared to your INR filter.")
        elif (job.salary_max or job.salary_min or 0) < filters.minimum_salary:
            return False, notes

    if filters.maximum_salary is not None and job.salary_min is not None:
        if (job.salary_currency or "INR").upper() == "INR" and job.salary_min > filters.maximum_salary:
            return False, notes

    if filters.posted_within_days:
        if job.posted_at is None:
            notes.append("Posting date not provided; freshness cannot be confirmed.")
        else:
            posted = job.posted_at if job.posted_at.tzinfo else job.posted_at.replace(tzinfo=timezone.utc)
            if posted < datetime.now(timezone.utc) - timedelta(days=filters.posted_within_days):
                return False, notes

    if filters.internship_with_ppo:
        if not re.search(r"\bppo\b|pre[\s-]?placement", haystack):
            return False, notes

    if filters.maximum_experience_years is not None:
        from app.services.matching import _parse_experience

        bounds = _parse_experience(job.experience_requirement or f"{job.title} {job.description or ''}")
        if bounds and bounds[0] > filters.maximum_experience_years:
            return False, notes

    return True, notes


def _role_matches(role: str, title: str) -> bool:
    # Titles and descriptions can both mention the search terms, but only the
    # title establishes the job's actual role. A long description containing
    # every search word (for example, a product role discussing GenAI) must not
    # pass as a GenAI Engineer opening.
    seniority = {
        "entry", "level", "fresher", "freshers", "junior", "jr", "senior",
        "sr", "mid", "graduate", "experienced",
    }
    tokens = [
        token
        for token in re.findall(r"[a-z0-9+#.]+", role.lower())
        if len(token) > 1 and token not in seniority
    ]
    if not tokens:
        return True
    title_tokens = set(re.findall(r"[a-z0-9+#.]+", (title or "").lower().replace("-", " ")))
    aliases = {
        "ai": {"ai", "artificial intelligence"},
        "ml": {"ml", "machine learning"},
        "genai": {"genai", "generative ai"},
    }
    normalized_title = re.sub(r"[^a-z0-9+#.]+", " ", (title or "").lower())
    return all(
        token in title_tokens
        or any(alias in normalized_title for alias in aliases.get(token, set()))
        for token in tokens
    )


def _location_matches(locations: list[str], job_location: str, work_mode: str | None) -> bool:
    if work_mode == "remote":
        return True
    if not job_location:
        return False
    if "remote" in job_location and ("remote" in [loc.lower() for loc in locations] or True):
        # A remote job is compatible with any location filter.
        return True
    for location in locations:
        if location.lower() in job_location:
            return True
    india_aliases = {
        "bengaluru", "bangalore", "mumbai", "delhi", "gurugram", "noida", "hyderabad",
        "pune", "chennai", "kolkata", "ahmedabad", "jaipur", "kochi", "india",
    }
    if any(loc.lower() == "india" for loc in locations):
        if any(alias in job_location for alias in india_aliases):
            return True
    return False


def _infer_work_mode(haystack: str) -> str | None:
    if re.search(r"\bwork from home\b|\bremote\b|\bwfh\b", haystack):
        return "remote"
    if re.search(r"\bhybrid\b", haystack):
        return "hybrid"
    if re.search(r"\bonsite\b|on-site|in[\s-]?office", haystack):
        return "onsite"
    return None


def _infer_employment_type(haystack: str) -> str | None:
    if re.search(r"\bintern(?:ship)?\b", haystack):
        return "internship"
    if re.search(r"\bpart[\s-]?time\b", haystack):
        return "part_time"
    if re.search(r"\bcontract\b", haystack):
        return "contract"
    if re.search(r"\bfull[\s-]?time\b|permanent", haystack):
        return "full_time"
    return None

