"""
Explainable, deterministic job matching.

Every score is the weighted average of components that could actually be
evaluated. A missing salary on the job is *not* treated as a failed salary
match; the component is marked "unknown" and its weight is redistributed.
The response includes per-component scores, reasons, matched skills, missing
skills and the exact weights used, so a user can see why a job ranked where
it did. No opaque model is required for the score.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from app.core.config import settings
from app.services.search_intent import CITY_ALIASES
from app.services.skills import extract_skills, skill_tokens_match

DEFAULT_WEIGHTS = {
    "skills": 0.45,
    "role": 0.20,
    "location": 0.15,
    "experience": 0.10,
    "salary": 0.05,
    "recency": 0.05,
}


def weights() -> dict[str, float]:
    result: dict[str, float] = {}
    for pair in settings.MATCH_WEIGHTS.split(","):
        if "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        try:
            result[key.strip()] = float(value)
        except ValueError:
            continue
    return result or dict(DEFAULT_WEIGHTS)


def score_job(profile, job, job_skills: list[str] | None = None) -> tuple[float, dict]:
    profile_skills = {s for s in (getattr(profile, "skills", None) or []) if isinstance(s, str)}
    job_skill_list = list(dict.fromkeys(job_skills or []))
    if not job_skill_list:
        job_skill_list = extract_skills(f"{job.title} {job.description or ''}")

    components: dict[str, dict] = {}

    # -- skills ------------------------------------------------------------
    matched = [skill for skill in job_skill_list if any(skill_tokens_match(skill, p) for p in profile_skills)]
    missing = [skill for skill in job_skill_list if skill not in matched]
    if job_skill_list and profile_skills:
        skill_score = len(matched) / len(job_skill_list)
        components["skills"] = {
            "score": round(skill_score, 3),
            "reason": f"{len(matched)} of {len(job_skill_list)} listed skills found in your profile.",
            "matched": matched,
            "missing": missing,
        }
    else:
        components["skills"] = {
            "score": None,
            "reason": "No comparable skills listed on the job or profile.",
            "matched": matched,
            "missing": missing,
        }

    # -- role --------------------------------------------------------------
    titles = _profile_titles(profile)
    if titles:
        best_title, best_ratio = max(
            ((title, SequenceMatcher(None, title.lower(), (job.title or "").lower()).ratio()) for title in titles),
            key=lambda pair: pair[1],
        )
        components["role"] = {
            "score": round(min(1.0, best_ratio), 3),
            "reason": f"Closest title: '{best_title}' vs '{job.title}'.",
        }
    else:
        components["role"] = {"score": None, "reason": "No current or past title on the profile yet."}

    # -- location ----------------------------------------------------------
    components["location"] = _location_component(profile, job)

    # -- experience --------------------------------------------------------
    components["experience"] = _experience_component(profile, job)

    # -- salary ------------------------------------------------------------
    components["salary"] = _salary_component(profile, job)

    # -- recency -----------------------------------------------------------
    components["recency"] = _recency_component(job)

    # -- optional semantic embedding similarity ----------------------------
    profile_embedding = getattr(profile, "profile_embedding", None)
    job_embedding = getattr(job, "description_embedding", None)
    if profile_embedding and job_embedding:
        similarity = _cosine(profile_embedding, job_embedding)
        if similarity is not None:
            components["semantic"] = {
                "score": round((similarity + 1) / 2, 3),
                "reason": f"Embedding cosine similarity {similarity:.3f}.",
            }

    configured = weights()
    available = {k: v for k, v in components.items() if v["score"] is not None}
    if not available:
        return 0.0, {
            "score": 0.0,
            "components": components,
            "weights_used": {},
            "matched_skills": matched,
            "missing_skills": missing,
            "strengths": [],
            "gaps": [],
            "summary": "Not enough profile or job data to score this match yet.",
            "engine": "deterministic-v1",
        }

    total_weight = sum(configured.get(k, 0.1) for k in available)
    weighted = sum(available[k]["score"] * configured.get(k, 0.1) for k in available)
    score = round(100 * weighted / total_weight, 1)

    weights_used = {
        k: round(configured.get(k, 0.1) / total_weight, 3) for k in available
    }
    strengths = [
        f"{k}: {int(v['score'] * 100)}% — {v['reason']}"
        for k, v in available.items()
        if v["score"] >= 0.7
    ]
    gaps = [
        f"{k}: {int(v['score'] * 100)}% — {v['reason']}"
        for k, v in available.items()
        if v["score"] < 0.5
    ]
    if missing:
        gaps.append(f"Skills to address: {', '.join(missing[:8])}.")

    explanation = {
        "score": score,
        "components": components,
        "weights_used": weights_used,
        "matched_skills": matched,
        "missing_skills": missing,
        "strengths": strengths,
        "gaps": gaps,
        "summary": _summary(score, components, matched, job_skill_list),
        "engine": "deterministic-v1",
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }
    return score, explanation


def _summary(score: float, components: dict, matched: list[str], job_skills: list[str]) -> str:
    if score >= 80:
        band = "Strong match"
    elif score >= settings.MATCH_THRESHOLD:
        band = "Good match"
    elif score >= 40:
        band = "Partial match"
    else:
        band = "Weak match"
    skill_text = ""
    if job_skills:
        skill_text = f" {len(matched)}/{len(job_skills)} listed skills matched."
    top = max(
        ((k, v["score"]) for k, v in components.items() if v["score"] is not None),
        key=lambda pair: pair[1],
        default=None,
    )
    top_text = f" Strongest signal: {top[0]}." if top else ""
    return f"{band} ({score:.0f}/100).{skill_text}{top_text}"


def _profile_titles(profile) -> list[str]:
    titles: list[str] = []
    for value in (getattr(profile, "current_title", None), getattr(profile, "headline", None)):
        if value:
            titles.append(str(value).strip())
    for entry in (getattr(profile, "experience", None) or [])[:4]:
        if isinstance(entry, dict) and entry.get("title"):
            titles.append(str(entry["title"]).strip())
    return list(dict.fromkeys(t for t in titles if t))


def _location_component(profile, job) -> dict:
    job_location = (job.location or "").strip()
    profile_location = (getattr(profile, "location", None) or "").strip()
    if job.work_mode == "remote":
        return {
            "score": 1.0,
            "reason": "Job is remote." + (f" Your location: {profile_location}." if profile_location else ""),
        }
    if not job_location or not profile_location:
        return {"score": None, "reason": "Location missing on the job or profile."}

    job_norm = _normalize(job_location)
    profile_norm = _normalize(profile_location)
    if profile_norm in job_norm or job_norm in profile_norm:
        return {"score": 1.0, "reason": f"Location matches ({job_location})."}

    job_city = _city(job_location)
    profile_city = _city(profile_location)
    if job_city and profile_city and job_city == profile_city:
        return {"score": 1.0, "reason": f"Same city ({job_city})."}
    if job_city and profile_city and job_city != profile_city:
        return {"score": 0.0, "reason": f"Different city: {job_city} vs {profile_city}."}
    if _normalize(profile_location).split(",")[-1].strip() in job_norm:
        return {"score": 0.7, "reason": "Same country/region."}
    return {"score": 0.2, "reason": f"Location differs ({job_location} vs {profile_location})."}


def _experience_component(profile, job) -> dict:
    years = getattr(profile, "total_experience_years", None)
    requirement = job.experience_requirement or ""
    bounds = _parse_experience(requirement or f"{job.title} {job.description or ''}")
    if years is None:
        return {"score": None, "reason": "Add your total experience to score this."}
    if bounds is None:
        return {"score": None, "reason": "Job does not state an experience range."}
    minimum, maximum = bounds
    if years < minimum:
        score = max(0.0, 1 - (minimum - years) / max(minimum, 1))
        return {
            "score": round(score, 3),
            "reason": f"Job asks for {_range_text(minimum, maximum)}; you have {years:g} years.",
        }
    if maximum is not None and years > maximum + 1:
        return {
            "score": 0.8,
            "reason": f"Job asks for {_range_text(minimum, maximum)}; you have {years:g} years (overqualified).",
        }
    return {
        "score": 1.0,
        "reason": f"Experience fits ({_range_text(minimum, maximum)} vs {years:g} years).",
    }


def _salary_component(profile, job) -> dict:
    expected = getattr(profile, "expected_salary", None)
    job_max = job.salary_max or job.salary_min
    if expected is None:
        return {"score": None, "reason": "No expected salary on your profile."}
    if job_max is None:
        return {"score": None, "reason": "Salary not disclosed by the employer."}
    currency = (job.salary_currency or "").upper()
    if currency and currency != "INR":
        return {"score": None, "reason": f"Salary listed in {currency}; comparison skipped."}
    if job_max >= expected:
        return {"score": 1.0, "reason": f"Listed salary meets your target ({job_max:,.0f})."}
    ratio = job_max / expected if expected else 0
    return {
        "score": round(max(0.0, ratio), 3),
        "reason": f"Listed salary {job_max:,.0f} is below your target {expected:,.0f}.",
    }


def _recency_component(job) -> dict:
    posted = job.posted_at
    if posted is None:
        return {"score": None, "reason": "Posting date not provided by the source."}
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (datetime.now(timezone.utc) - posted).total_seconds() / 86400)
    score = max(0.0, 1 - age_days / 30)
    return {"score": round(score, 3), "reason": f"Posted {age_days:.0f} day(s) ago."}


def _parse_experience(text: str) -> tuple[float, float | None] | None:
    low = (text or "").lower()
    if re.search(r"\bfresher|entry[\s-]?level|graduate|no experience", low):
        return 0.0, 1.0
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*years?", low)
    if match:
        return float(match.group(1)), float(match.group(2))
    match = re.search(r"(\d+(?:\.\d+)?)\s*\+\s*years?", low)
    if match:
        return float(match.group(1)), None
    match = re.search(r"(?:minimum|min|at least|over)\s*(\d+(?:\.\d+)?)\s*years?", low)
    if match:
        return float(match.group(1)), None
    return None


def _range_text(minimum: float, maximum: float | None) -> str:
    return f"{minimum:g}-{maximum:g} years" if maximum is not None else f"{minimum:g}+ years"


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", value.lower()).strip()


def _city(value: str) -> str | None:
    low = value.lower()
    for alias in sorted(CITY_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", low):
            return CITY_ALIASES[alias]
    return None


def _cosine(a: list, b: list) -> float | None:
    if not a or not b or len(a) != len(b):
        return None
    try:
        dot = sum(float(x) * float(y) for x, y in zip(a, b))
        na = math.sqrt(sum(float(x) ** 2 for x in a))
        nb = math.sqrt(sum(float(y) ** 2 for y in b))
        if na == 0 or nb == 0:
            return None
        return dot / (na * nb)
    except (TypeError, ValueError):
        return None
