"""
Resume → structured candidate data.

Two layers:
  1. A deterministic extractor that only reports tokens literally present in
     the document (regex for contact details, a curated skill vocabulary,
     section/date parsing for education and experience).
  2. An optional LLM refinement that is *validated against the source text*.
     Any value the LLM returns that cannot be found in the resume is dropped
     and reported in ``rejected_llm_fields``. This is what makes "never
     fabricate candidate information" enforceable rather than aspirational.

Unknown values are returned as None/[] and surfaced in ``missing_fields`` so
the UI can ask the user instead of guessing.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from app.services.llm import llm
from app.services.skills import extract_skills

MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
DATE_TOKEN = rf"(?:{MONTHS})[a-z]*\.?\s*\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}}"
DATE_RANGE_RE = re.compile(
    rf"(?P<start>{DATE_TOKEN})\s*(?:-|–|—|to|until)\s*(?P<end>present|current|now|{DATE_TOKEN})",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"(?:19|20)\d{2}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s.\-]?)?(?:\(?\d{2,5}\)?[\s.\-]?){2,4}\d{3,5}")
URL_RE = re.compile(r"https?://[^\s<>()]+|(?:www\.)[^\s<>()]+", re.IGNORECASE)
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/(?:in|pub)/[A-Za-z0-9\-_%./]+", re.IGNORECASE)
GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9\-_%./]+", re.IGNORECASE)
DEGREE_RE = re.compile(
    r"\b(b\.?tech|b\.?e\.?|bachelor(?:'s)?|mca|m\.?c\.?a\.?|m\.?tech|master(?:'s)?|mba|b\.?sc|m\.?sc|ph\.?d|b\.?com|b\.?a\.?|diploma|bca)\b",
    re.IGNORECASE,
)
INSTITUTION_RE = re.compile(
    r"\b(university|college|institute|school|academy|iit|nit|iiit|bits)\b", re.IGNORECASE
)
COMPANY_RE = re.compile(
    r"\b(pvt|private|ltd|limited|inc|llc|technologies|technology|solutions|labs|systems|corp|corporation|company|consulting|services|analytics|software)\b",
    re.IGNORECASE,
)
EMAIL_LABELS = ("email", "e-mail", "mail")

SECTION_ALIASES = {
    "summary": "summary",
    "profile": "summary",
    "objective": "summary",
    "about": "summary",
    "about me": "summary",
    "education": "education",
    "academic": "education",
    "academics": "education",
    "academic background": "education",
    "qualifications": "education",
    "experience": "experience",
    "work experience": "experience",
    "professional experience": "experience",
    "employment": "experience",
    "employment history": "experience",
    "work history": "experience",
    "internship": "experience",
    "internships": "experience",
    "projects": "projects",
    "personal projects": "projects",
    "academic projects": "projects",
    "skills": "skills",
    "technical skills": "skills",
    "core skills": "skills",
    "technologies": "skills",
    "certifications": "certifications",
    "certificates": "certifications",
    "achievements": "achievements",
    "awards": "achievements",
    "honors": "achievements",
    "accomplishments": "achievements",
    "languages": "languages",
    "publications": "publications",
    "positions of responsibility": "achievements",
}

CITY_ALIASES = {
    "bengaluru": "Bengaluru",
    "bangalore": "Bengaluru",
    "bombay": "Mumbai",
    "mumbai": "Mumbai",
    "new delhi": "New Delhi",
    "delhi": "New Delhi",
    "ncr": "Delhi NCR",
    "gurugram": "Gurugram",
    "gurgaon": "Gurugram",
    "noida": "Noida",
    "hyderabad": "Hyderabad",
    "pune": "Pune",
    "chennai": "Chennai",
    "kolkata": "Kolkata",
    "ahmedabad": "Ahmedabad",
    "jaipur": "Jaipur",
    "kochi": "Kochi",
    "cochin": "Kochi",
    "trivandrum": "Thiruvananthapuram",
    "thiruvananthapuram": "Thiruvananthapuram",
    "coimbatore": "Coimbatore",
    "indore": "Indore",
    "chandigarh": "Chandigarh",
    "mysuru": "Mysuru",
    "mysore": "Mysuru",
    "vizag": "Visakhapatnam",
    "visakhapatnam": "Visakhapatnam",
    "remote": "Remote",
    "london": "London",
    "new york": "New York",
    "san francisco": "San Francisco",
    "seattle": "Seattle",
    "berlin": "Berlin",
    "singapore": "Singapore",
    "dubai": "Dubai",
    "toronto": "Toronto",
}

NAME_BLACKLIST = {
    "resume",
    "curriculum vitae",
    "cv",
    "profile",
    "personal details",
    "contact",
    "email",
    "phone",
    "address",
    "linkedin",
    "github",
    "summary",
    "objective",
    "education",
    "experience",
    "skills",
    "projects",
}
ROLE_WORDS = (
    "engineer",
    "developer",
    "scientist",
    "analyst",
    "manager",
    "architect",
    "consultant",
    "intern",
    "designer",
    "administrator",
    "specialist",
)


def extract_profile(text: str) -> dict:
    if not text or not text.strip():
        return empty_profile()

    lines = [line.strip() for line in text.splitlines()]
    sections = split_sections(lines)
    personal, evidence = _extract_personal(lines)
    education = _parse_education(sections.get("education", []))
    experience = _parse_experience(sections.get("experience", []))
    projects = _parse_projects(sections.get("projects", []))
    years = _compute_years(experience)

    profile = {
        "personal": personal,
        "headline": _extract_headline(lines, personal),
        "summary": _join_section(sections.get("summary")),
        "skills": extract_skills(text),
        "education": education,
        "experience": experience,
        "projects": projects,
        "certifications": _list_section(sections.get("certifications")),
        "achievements": _list_section(sections.get("achievements")),
        "languages": _list_section(sections.get("languages")),
        "years_experience": years,
        "evidence": evidence,
        "extraction_method": "heuristic",
        "rejected_llm_fields": [],
    }
    profile["missing_fields"] = missing_fields(profile)
    profile["completeness"] = completeness(profile)
    return profile


def empty_profile() -> dict:
    return {
        "personal": {
            "full_name": None,
            "email": None,
            "phone": None,
            "location": None,
            "linkedin_url": None,
            "github_url": None,
            "portfolio_url": None,
        },
        "headline": None,
        "summary": None,
        "skills": [],
        "education": [],
        "experience": [],
        "projects": [],
        "certifications": [],
        "achievements": [],
        "languages": [],
        "years_experience": None,
        "evidence": {},
        "extraction_method": "heuristic",
        "rejected_llm_fields": [],
        "missing_fields": [],
        "completeness": 0,
    }


def extract_with_llm(text: str, base: dict) -> dict:
    """
    Sync wrapper used by the API's background task. Falls back to the
    deterministic result when no provider is configured or the call fails.
    """
    if not llm.available:
        return base

    import asyncio

    return asyncio.run(_extract_with_llm_async(text, base))


async def _extract_with_llm_async(text: str, base: dict) -> dict:
    prompt = f"""Extract candidate details from the resume below.

Return ONLY JSON with this shape:
{{
  "personal": {{"full_name":null,"email":null,"phone":null,"location":null,"linkedin_url":null,"github_url":null,"portfolio_url":null}},
  "headline": null,
  "summary": null,
  "education": [{{"degree":null,"institution":null,"specialization":null,"graduation_year":null,"details":null}}],
  "experience": [{{"title":null,"company":null,"start_date":null,"end_date":null,"location":null,"description":null,"type":null}}],
  "projects": [{{"name":null,"description":null,"technologies":[]}}],
  "certifications": [],
  "achievements": [],
  "languages": []
}}

Rules:
- Copy values exactly from the resume. Do not infer, translate, expand or invent anything.
- Use null / [] when the resume does not state a value.
- `headline` must be a phrase literally present in the resume.
- Keep dates exactly as written.
- Do not include emails, phone numbers or links that are not in the text.

RESUME:
\"\"\"
{text[:20000]}
\"\"\"
"""
    response = await llm.generate_json(prompt, system="You extract structured data without inventing facts.")
    if response is None:
        return base

    merged = _merge_validated(base, response.data, text)
    merged["extraction_method"] = f"{response.provider}+validated"
    merged["missing_fields"] = missing_fields(merged)
    merged["completeness"] = completeness(merged)
    return merged


# --------------------------------------------------------------------------
# Validation of LLM output against the source text
# --------------------------------------------------------------------------

def _normalize_for_match(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _appears(value: str | None, normalized_source: str) -> bool:
    if not value or not isinstance(value, str):
        return False
    normalized = _normalize_for_match(value)
    if not normalized:
        return False
    if len(normalized) <= 2:
        return normalized in normalized_source.split()
    return normalized in normalized_source


def _merge_validated(base: dict, llm_data: dict, text: str) -> dict:
    source = _normalize_for_match(text)
    rejected: list[str] = []
    personal = dict(base["personal"])

    llm_personal = llm_data.get("personal") or {}
    for field in ("full_name", "email", "phone", "linkedin_url", "github_url", "portfolio_url"):
        if personal.get(field):
            continue
        candidate = llm_personal.get(field)
        if candidate and _appears(str(candidate), source):
            personal[field] = candidate
        elif candidate:
            rejected.append(f"personal.{field}")

    location = personal.get("location")
    if not location:
        candidate = llm_personal.get("location")
        if candidate and _location_in_text(str(candidate), text):
            personal["location"] = candidate
        elif candidate:
            rejected.append("personal.location")

    for field in ("headline", "summary"):
        if not base.get(field):
            candidate = llm_data.get(field)
            if candidate and _appears(str(candidate), source):
                base[field] = candidate
            elif candidate:
                rejected.append(field)

    # Lists: accept an LLM entry only when one of its identifying strings is
    # literally in the resume, and it isn't already present.
    def merge_list(target_key: str, keys: tuple[str, ...]) -> None:
        existing = {_normalize_for_match(str(e.get(k) or "")) for e in base.get(target_key, []) for k in keys}
        seen = set(existing)
        for item in llm_data.get(target_key) or []:
            if not isinstance(item, dict):
                continue
            identifying = [str(item.get(k) or "") for k in keys]
            if not any(_appears(v, source) for v in identifying if v):
                rejected.append(f"{target_key}[{identifying[0][:40]}]")
                continue
            fingerprint = _normalize_for_match(" ".join(identifying))
            if not fingerprint or fingerprint in seen:
                continue
            seen.add(fingerprint)
            base.setdefault(target_key, []).append(item)
        base.setdefault(target_key, base.get(target_key) or [])

    merge_list("education", ("degree", "institution"))
    merge_list("experience", ("title", "company"))
    merge_list("projects", ("name",))

    for key in ("certifications", "achievements", "languages"):
        existing = {_normalize_for_match(str(v)) for v in (base.get(key) or [])}
        for item in llm_data.get(key) or []:
            if isinstance(item, str) and _appears(item, source):
                if _normalize_for_match(item) not in existing:
                    base.setdefault(key, []).append(item)
                    existing.add(_normalize_for_match(item))
            elif item:
                rejected.append(f"{key}[{str(item)[:40]}]")

    # Skills are always deterministic; an LLM cannot "add" a skill.
    base["personal"] = personal
    base["rejected_llm_fields"] = rejected
    return base


def _location_in_text(candidate: str, text: str) -> bool:
    normalized = _normalize_for_match(candidate)
    source = _normalize_for_match(text)
    if normalized and normalized in source:
        return True
    first = normalized.split(",")[0].strip()
    return bool(first and first in source)


# --------------------------------------------------------------------------
# Deterministic extraction helpers
# --------------------------------------------------------------------------

def split_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for line in lines:
        key = _section_key(line)
        if key:
            current = key
            sections.setdefault(current, [])
            continue
        # Blank lines are preserved: they are what separates education and
        # experience entries during parsing.
        sections.setdefault(current, []).append(line)
    return sections


def _section_key(line: str) -> str | None:
    cleaned = line.strip().strip(":•-–— ").lower()
    if not cleaned or len(cleaned) > 45:
        return None
    cleaned = re.sub(r"\s+", " ", cleaned)
    if cleaned in SECTION_ALIASES:
        return SECTION_ALIASES[cleaned]
    # "Education: ..." style headings
    if ":" in line and len(cleaned.split(":")[0]) <= 30:
        prefix = cleaned.split(":")[0].strip()
        if prefix in SECTION_ALIASES:
            return SECTION_ALIASES[prefix]
    return None


def _extract_personal(lines: list[str]) -> tuple[dict, dict]:
    text = "\n".join(lines)
    evidence: dict[str, str] = {}

    email = None
    for line in lines:
        if any(label in line.lower() for label in EMAIL_LABELS) and EMAIL_RE.search(line):
            email = EMAIL_RE.search(line).group(0).rstrip(".,;")
            evidence["email"] = line
            break
    if not email:
        match = EMAIL_RE.search(text)
        if match:
            email = match.group(0).rstrip(".,;")
            evidence["email"] = _line_containing(lines, email)

    phone = _find_phone(lines)
    if phone:
        evidence["phone"] = _line_containing(lines, phone)

    linkedin = None
    match = LINKEDIN_RE.search(text)
    if match:
        linkedin = _clean_url(match.group(0))
        evidence["linkedin_url"] = _line_containing(lines, "linkedin")

    github = None
    match = GITHUB_RE.search(text)
    if match:
        github = _clean_url(match.group(0))
        evidence["github_url"] = _line_containing(lines, "github")

    portfolio = None
    for match in URL_RE.finditer(text):
        url = _clean_url(match.group(0))
        low = url.lower()
        if "linkedin.com" in low or "github.com" in low:
            continue
        if any(domain in low for domain in ("gmail.com", "outlook.com", "yahoo.com")):
            continue
        portfolio = url
        evidence["portfolio_url"] = _line_containing(lines, url)
        break

    full_name = _find_name(lines)
    if full_name:
        evidence["full_name"] = _line_containing(lines, full_name)

    location = _find_location(lines)
    if location:
        evidence["location"] = _line_containing(lines, location)

    return (
        {
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "location": location,
            "linkedin_url": linkedin,
            "github_url": github,
            "portfolio_url": portfolio,
        },
        evidence,
    )


def _find_name(lines: list[str]) -> str | None:
    for raw in lines[:10]:
        line = raw.strip().lstrip("•-–— ").strip()
        if not line:
            continue
        if ":" in line:
            label, _, rest = line.partition(":")
            if label.strip().lower() in {"name", "full name", "candidate name"}:
                line = rest.strip()
            else:
                continue
        if any(ch.isdigit() for ch in line) or "@" in line or "http" in line.lower():
            continue
        if line.lower() in NAME_BLACKLIST:
            continue
        if len(line) > 60 or len(line) < 2:
            continue
        tokens = line.split()
        if not 2 <= len(tokens) <= 5:
            continue
        if any(word in line.lower() for word in ("engineer", "developer", "resume", "curriculum")):
            continue
        if not re.fullmatch(r"[A-Za-z][A-Za-z.'\- ]+", line):
            continue
        return " ".join(word.capitalize() if word.isupper() else word for word in tokens)
    return None


def _find_phone(lines: list[str]) -> str | None:
    preferred: list[str] = []
    fallback: list[str] = []
    for line in lines[:30]:
        low = line.lower()
        if any(label in low for label in ("phone", "mobile", "contact", "tel")):
            preferred.append(line)
        else:
            fallback.append(line)
    for line in preferred + fallback:
        for match in PHONE_RE.finditer(line):
            candidate = match.group(0).strip(" .-")
            digits = re.sub(r"\D", "", candidate)
            if 10 <= len(digits) <= 13 and not DATE_RANGE_RE.search(candidate):
                if digits.startswith(("19", "20")) and len(digits) <= 8:
                    continue
                return candidate
    return None


def _find_location(lines: list[str]) -> str | None:
    for line in lines[:25]:
        low = line.lower()
        if any(label in low for label in ("location", "address", "based in", "city")):
            value = re.split(r"[:–—-]", line, maxsplit=1)
            if len(value) == 2 and 2 <= len(value[1].strip()) <= 80:
                return value[1].strip().strip(",|")
    for line in lines[:20]:
        low = line.lower()
        for alias in sorted(CITY_ALIASES, key=len, reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b", low):
                return CITY_ALIASES[alias]
    return None


def _extract_headline(lines: list[str], personal: dict) -> str | None:
    for line in lines[:15]:
        low = line.lower()
        if any(low.startswith(f"{label}:") for label in ("headline", "title", "role", "designation")):
            value = line.split(":", 1)[1].strip()
            if 2 <= len(value) <= 200:
                return value
    name = personal.get("full_name")
    for index, line in enumerate(lines[:15]):
        if name and name.lower() in line.lower():
            for follow in lines[index + 1 : index + 3]:
                candidate = follow.strip("•-–— |")
                if (
                    3 <= len(candidate) <= 120
                    and any(word in candidate.lower() for word in ROLE_WORDS)
                    and not EMAIL_RE.search(candidate)
                    and not URL_RE.search(candidate)
                ):
                    # "AI Engineer | Bengaluru, India" → "AI Engineer"
                    parts = [p.strip() for p in candidate.split("|") if p.strip()]
                    for part in parts:
                        if any(word in part.lower() for word in ROLE_WORDS):
                            return part[:200]
                    return candidate[:200]
            break
    return None


def _parse_education(lines: list[str]) -> list[dict]:
    if not lines:
        return []
    entries: list[dict] = []
    for block in _blocks(lines):
        text_block = [line for line in block if line.strip()]
        if not text_block:
            continue
        joined = " ".join(text_block)
        degree_line = next((b for b in text_block if DEGREE_RE.search(b)), None)
        degree_match = DEGREE_RE.search(degree_line) if degree_line else None
        institution_line = next((b for b in text_block if INSTITUTION_RE.search(b)), None)
        if not degree_match and not institution_line:
            continue
        years = YEAR_RE.findall(joined)
        graduation = years[-1] if years else None
        specialization = None
        if degree_match:
            tail = degree_line[degree_match.end() :]
            cut_points = [len(tail)]
            if institution_line:
                pos = tail.find(institution_line)
                if pos > 0:
                    cut_points.append(pos)
            for marker in ("|", " CGPA", " GPA", " - ", " – ", "—"):
                pos = tail.find(marker)
                if pos > 0:
                    cut_points.append(pos)
            year_pos = YEAR_RE.search(tail)
            if year_pos:
                cut_points.append(year_pos.start())
            tail = tail[: min(cut_points)]
            spec = re.sub(r"^[\s,:.\-–—]*|[\s,:.\-–—]*$", "", tail)
            spec = re.sub(r"^(?:in|of|major(?:ing)?\s+in)\s+", "", spec, flags=re.IGNORECASE)
            if 2 <= len(spec) <= 80:
                specialization = spec
        cgpa = re.search(r"(?:CGPA|GPA)\s*[:\-]?\s*([0-9]{1,2}(?:\.[0-9]{1,2})?)", joined, re.IGNORECASE)
        percentage = re.search(r"([0-9]{2,3}(?:\.[0-9]{1,2})?)\s*%", joined)
        academic = None
        if cgpa:
            academic = f"CGPA {cgpa.group(1)}"
        elif percentage:
            academic = f"{percentage.group(1)}%"
        entries.append(
            {
                "degree": _clean_degree(degree_match.group(0)) if degree_match else None,
                "institution": institution_line.strip(" ,|") if institution_line else None,
                "specialization": specialization,
                "graduation_year": graduation,
                "academic_details": academic,
                "details": joined[:500],
            }
        )
    return _dedupe_entries(entries)[:10]


def _clean_degree(value: str) -> str:
    cleaned = value.strip().rstrip(".")
    fixes = {
        "btech": "B.Tech",
        "b.tech": "B.Tech",
        "be": "B.E.",
        "b.e": "B.E.",
        "mca": "MCA",
        "m.tech": "M.Tech",
        "mtech": "M.Tech",
        "mba": "MBA",
        "bca": "BCA",
        "b.sc": "B.Sc",
        "msc": "M.Sc",
    }
    return fixes.get(cleaned.lower(), cleaned.title() if cleaned.islower() else cleaned)


def _parse_experience(lines: list[str]) -> list[dict]:
    if not lines:
        return []
    entries: list[dict] = []
    for block in _blocks(lines):
        joined = " ".join(block)
        dates = DATE_RANGE_RE.search(joined)
        is_internship = bool(re.search(r"\bintern(?:ship)?\b", joined, re.IGNORECASE))
        if not dates and not (is_internship and any(COMPANY_RE.search(b) for b in block)):
            continue
        title, company = _title_company(block, dates)
        if not title and not company:
            continue
        entries.append(
            {
                "title": title,
                "company": company,
                "start_date": dates.group("start") if dates else None,
                "end_date": dates.group("end") if dates else None,
                "location": _block_location(joined),
                "description": " ".join(block)[:1500] or None,
                "type": "internship" if is_internship else "full_time",
            }
        )
    return _dedupe_entries(entries)[:15]


def _title_company(block: list[str], dates: re.Match | None) -> tuple[str | None, str | None]:
    title = None
    company = None
    for line in block:
        cleaned = line.strip("•-–— |")
        if not cleaned or not cleaned.strip() or DATE_RANGE_RE.fullmatch(cleaned):
            continue
        if len(cleaned) > 140:
            continue
        if re.search(r"\s+at\s+", cleaned, re.IGNORECASE):
            left, right = re.split(r"\s+at\s+", cleaned, maxsplit=1, flags=re.IGNORECASE)
            title = title or left.strip(" ,|")
            company = company or right.split("|")[0].strip(" ,|")
            break
        if "|" in cleaned:
            parts = [p.strip() for p in cleaned.split("|") if p.strip()]
            if len(parts) >= 2 and any(w in parts[0].lower() for w in ROLE_WORDS):
                title = title or parts[0]
                company = company or parts[1]
                break
        separator = next((sep for sep in (" - ", " – ", " — ") if sep in cleaned), None)
        if separator:
            parts = [p.strip() for p in cleaned.split(separator, 1)]
            if len(parts) == 2 and any(w in parts[0].lower() for w in ROLE_WORDS):
                title = title or parts[0]
                company = company or parts[1]
                break
    if not title:
        for line in block:
            cleaned = line.strip("•-–— |")
            if any(word in cleaned.lower() for word in ROLE_WORDS) and len(cleaned) <= 120:
                title = cleaned
                break
    if not company:
        for line in block:
            cleaned = line.strip("•-–— |")
            if COMPANY_RE.search(cleaned) and len(cleaned) <= 120 and cleaned != title:
                company = cleaned
                break
    if title and DATE_RANGE_RE.search(title):
        title = DATE_RANGE_RE.sub("", title).strip(" ,-–—|")
    if company:
        if DATE_RANGE_RE.search(company):
            company = DATE_RANGE_RE.sub("", company).strip(" ,-–—|")
        company = company.split("|")[0].strip(" ,-–—")
    if company and title and company.lower() == title.lower():
        company = None
    return title or None, company or None


def _parse_projects(lines: list[str]) -> list[dict]:
    if not lines:
        return []
    projects: list[dict] = []
    for block in _blocks(lines):
        if not block:
            continue
        name = block[0].strip("•-–— ")
        if len(name) > 160:
            name = name[:160]
        description = " ".join(block[1:])[:1500] if len(block) > 1 else None
        projects.append(
            {
                "name": name,
                "description": description,
                "technologies": extract_skills(" ".join(block)),
            }
        )
    return projects[:10]


def _list_section(lines: list[str] | None) -> list[str]:
    if not lines:
        return []
    result: list[str] = []
    for line in lines:
        cleaned = re.sub(r"^[•\-–—*]\s*", "", line).strip()
        if 2 <= len(cleaned) <= 300:
            result.append(cleaned)
    return result[:20]


def _join_section(lines: list[str] | None) -> str | None:
    if not lines:
        return None
    text = " ".join(lines).strip()
    return text[:2000] or None


def _blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        is_bullet = bool(re.match(r"^[•\-–—*]\s+", line))
        if is_bullet and current:
            current.append(line)
            continue
        # No blank line between entries: start a new block when the current
        # block already has a date range and this line looks like a new title.
        if current and any(DATE_RANGE_RE.search(item) for item in current):
            if any(word in line.lower() for word in ROLE_WORDS) and len(line) <= 140:
                blocks.append(current)
                current = []
        current.append(line)
    if current:
        blocks.append(current)
    if len(blocks) == 1 and len(blocks[0]) > 3:
        # Education sections often have no blank lines; split at degree or
        # institution lines instead.
        chunked: list[list[str]] = []
        chunk: list[str] = []
        for line in blocks[0]:
            starts_entry = bool(DEGREE_RE.search(line) or INSTITUTION_RE.search(line))
            if starts_entry and chunk:
                chunked.append(chunk)
                chunk = []
            chunk.append(line)
        if chunk:
            chunked.append(chunk)
        return chunked
    return blocks


def _block_location(text: str) -> str | None:
    for alias, canonical in CITY_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE):
            return canonical
    return None


def _compute_years(experience: list[dict]) -> float | None:
    if not experience:
        return None
    now = datetime.now(timezone.utc)
    months: set[tuple[int, int]] = set()
    for entry in experience:
        start_year = _year(entry.get("start_date"))
        end_token = (entry.get("end_date") or "").strip().lower()
        is_present = end_token in {"present", "current", "now"}
        end_year = now.year if is_present else _year(entry.get("end_date"))
        if not start_year or not end_year or end_year < start_year:
            continue
        if end_year > now.year:
            end_year = now.year
        for year in range(start_year, end_year + 1):
            if year == end_year:
                max_month = now.month if is_present else _month(entry.get("end_date"), 12)
            else:
                max_month = 12
            min_month = _month(entry.get("start_date"), 1) if year == start_year else 1
            for month in range(min_month, max_month + 1):
                months.add((year, month))
    if not months:
        return None
    return round(len(months) / 12, 1)


def _year(value: str | None, default: int | None = None) -> int | None:
    if not value:
        return default
    match = YEAR_RE.search(value)
    return int(match.group(0)) if match else default


def _month(value: str | None, default: int = 1) -> int:
    if not value:
        return default
    match = re.match(rf"({MONTHS})", value.strip(), re.IGNORECASE)
    if not match:
        return default
    return ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(
        match.group(1).lower()[:3]
    ) + 1


def _dedupe_entries(entries: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for entry in entries:
        key = _normalize_for_match(" ".join(str(v) for v in entry.values() if isinstance(v, str)))
        if key and key not in seen:
            seen.add(key)
            result.append(entry)
    return result


def _line_containing(lines: list[str], needle: str) -> str:
    for line in lines:
        if needle.lower() in line.lower():
            return line[:300]
    return ""


def _clean_url(url: str) -> str:
    url = url.strip().rstrip(".,;)")
    if not url.lower().startswith("http"):
        url = "https://" + url
    return url


def missing_fields(profile: dict) -> list[str]:
    personal = profile.get("personal") or {}
    missing: list[str] = []
    for field in ("full_name", "email", "phone", "location"):
        if not personal.get(field):
            missing.append(field)
    for field in ("skills", "education", "experience"):
        if not profile.get(field):
            missing.append(field)
    return missing


def completeness(profile: dict) -> int:
    personal = profile.get("personal") or {}
    score = 0
    score += 10 if personal.get("full_name") else 0
    score += 10 if personal.get("email") else 0
    score += 5 if personal.get("phone") else 0
    score += 5 if personal.get("location") else 0
    score += 5 if any(personal.get(k) for k in ("linkedin_url", "github_url", "portfolio_url")) else 0
    score += 20 if profile.get("skills") else 0
    score += 15 if profile.get("education") else 0
    score += 15 if profile.get("experience") else 0
    score += 10 if profile.get("projects") else 0
    score += 5 if profile.get("summary") else 0
    return min(100, score)
