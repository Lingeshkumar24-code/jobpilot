"""
Natural language → structured job-search filters.

The deterministic parser is the baseline and covers the phrasing people
actually use ("fresher AI Engineer jobs near Bangalore with minimum 8 LPA",
"GenAI internships with PPO", "remote ML jobs posted in the last 24 hours").
An optional LLM pass may add fields, but only values that are grounded in the
query text survive validation — the model cannot invent a salary the user
never mentioned.
"""
from __future__ import annotations

import re

from app.schemas.search import StructuredFilters
from app.services.llm import llm
from app.services.skills import extract_skills

CITY_ALIASES = {
    "bengaluru": "Bengaluru",
    "bangalore": "Bengaluru",
    "bombay": "Mumbai",
    "mumbai": "Mumbai",
    "new delhi": "New Delhi",
    "delhi": "New Delhi",
    "delhi ncr": "Delhi NCR",
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
    "mysore": "Mysuru",
    "mysuru": "Mysuru",
    "london": "London",
    "new york": "New York",
    "san francisco": "San Francisco",
    "seattle": "Seattle",
    "berlin": "Berlin",
    "singapore": "Singapore",
    "dubai": "Dubai",
    "toronto": "Toronto",
}
COUNTRY_ALIASES = {
    "india": "India",
    "usa": "United States",
    "us": "United States",
    "united states": "United States",
    "uk": "United Kingdom",
    "united kingdom": "United Kingdom",
    "europe": "Europe",
    "canada": "Canada",
    "germany": "Germany",
}

ROLE_CANONICAL = {
    "ai": "AI",
    "ml": "ML",
    "genai": "GenAI",
    "gen ai": "GenAI",
    "llm": "LLM",
    "nlp": "NLP",
    "qa": "QA",
    "devops": "DevOps",
    "mlops": "MLOps",
    "python": "Python",
    "java": "Java",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "react": "React",
    "full stack": "Full Stack",
    "fullstack": "Full Stack",
    "data": "Data",
    "machine learning": "Machine Learning",
    "computer vision": "Computer Vision",
    "cloud": "Cloud",
    "security": "Security",
    "backend": "Backend",
    "frontend": "Frontend",
    "software": "Software",
    "product": "Product",
    "business": "Business",
    "android": "Android",
    "ios": "iOS",
    "web": "Web",
    "mca": "MCA",
    "bca": "BCA",
    "btech": "B.Tech",
    "mtech": "M.Tech",
    "mba": "MBA",
}
ROLE_SUFFIXES = (
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

STOPWORDS = {
    "find",
    "search",
    "show",
    "get",
    "me",
    "for",
    "a",
    "an",
    "the",
    "jobs",
    "job",
    "roles",
    "role",
    "positions",
    "position",
    "openings",
    "opening",
    "internship",
    "internships",
    "in",
    "near",
    "at",
    "with",
    "and",
    "or",
    "remote",
    "hybrid",
    "onsite",
    "fresher",
    "freshers",
    "entry",
    "level",
    "minimum",
    "min",
    "salary",
    "package",
    "ctc",
    "ppo",
    "posted",
    "last",
    "within",
    "days",
    "hours",
    "week",
    "month",
    "product",
    "companies",
    "company",
    "startups",
    "startup",
    "india",
    "jobs.",
    "good",
    "best",
    "new",
    "all",
    "any",
    "based",
    "work",
    "from",
    "home",
    "office",
    "full",
    "time",
    "part",
    "contract",
    "permanent",
    "lpa",
    "lakhs",
    "lakh",
    "years",
    "year",
    "experience",
    "exp",
}


def parse_intent(query: str) -> tuple[StructuredFilters, str]:
    filters = parse_filters(query)
    return filters, "rule_based"


def parse_filters(query: str) -> StructuredFilters:
    text = query.strip()
    low = text.lower()
    filters = StructuredFilters()

    filters.work_mode = _work_modes(low)
    filters.employment_type = _employment_types(low)
    filters.posted_within_days = _freshness(low)
    filters.internship_with_ppo = bool(re.search(r"\bppo\b|pre[\s-]?placement offer", low))
    filters.minimum_salary, filters.maximum_salary = _salary(low, filters.notes)
    filters.experience, filters.minimum_experience_years, filters.maximum_experience_years = _experience(low)
    filters.location = _locations(low)
    filters.role = _roles(text)
    filters.skills = extract_skills(text)

    if filters.employment_type == ["internship"] and not filters.role:
        filters.notes.append("No specific role stated; searching all internship titles.")
    if filters.work_mode and "remote" in filters.work_mode and not filters.location:
        filters.notes.append("Remote-only search; no geographic restriction applied.")
    return filters


async def refine_with_llm(query: str, base: StructuredFilters) -> tuple[StructuredFilters, str]:
    if not llm.available:
        return base, "rule_based"
    prompt = f"""Convert the job-search request into JSON filters.

Schema:
{{
  "role": ["string"], "location": ["string"], "experience": "fresher|0-2 years|2-5 years|null",
  "minimum_salary": number|null, "maximum_salary": number|null,
  "employment_type": ["full_time"|"internship"|"contract"|"part_time"],
  "work_mode": ["onsite"|"hybrid"|"remote"], "skills": ["string"],
  "posted_within_days": integer|null, "internship_with_ppo": boolean
}}

Rules:
- Only include a filter when the user explicitly stated it. Missing means null / [].
- Salary is annual INR. Convert "8 LPA" to 800000.
- Do not invent locations, roles, skills or salary.
- "fresher" means experience = "fresher".

User request: {query}
"""
    response = await llm.generate_json(prompt, system="You turn search requests into strict JSON filters.")
    if response is None:
        return base, "rule_based"
    merged = validate_llm_filters(response.data, query, base)
    return merged, f"{response.provider}+validated"


def validate_llm_filters(data: dict, query: str, base: StructuredFilters) -> StructuredFilters:
    """Accept an LLM filter only when the query contains evidence for it."""
    low = query.lower()
    source = re.sub(r"[^a-z0-9 ]+", " ", low)
    merged = base.model_copy(deep=True)

    roles = []
    for value in data.get("role") or []:
        if isinstance(value, str) and value.strip():
            candidate = value.strip()
            normalized = re.sub(r"[^a-z0-9 ]+", " ", candidate.lower()).strip()
            if normalized and normalized in source:
                roles.append(candidate)
    role_keys = {re.sub(r"[^a-z0-9 ]+", " ", role.lower()).strip() for role in merged.role}
    for role in roles:
        key = re.sub(r"[^a-z0-9 ]+", " ", role.lower()).strip()
        if key and key not in role_keys:
            merged.role.append(role)
            role_keys.add(key)

    locations = []
    for value in data.get("location") or []:
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = re.sub(r"[^a-z0-9 ]+", " ", value.lower()).strip()
        if normalized and normalized in source:
            locations.append(value.strip())
    for location in locations:
        if location not in merged.location:
            merged.location.append(location)

    # Salary can never be accepted without a monetary phrase in the query.
    salary_grounded = bool(
        re.search(r"lpa|lakh|lac|crore|ctc|salary|package|₹|inr|rs\.?\s*\d", low) and re.search(r"\d", low)
    )
    if salary_grounded:
        for field in ("minimum_salary", "maximum_salary"):
            value = data.get(field)
            if isinstance(value, (int, float)) and value >= 0:
                setattr(merged, field, float(value))

    experience_grounded = bool(
        re.search(r"fresher|entry[\s-]?level|graduate|\d+\+?\s*(?:-|to)?\s*\d*\s*years?", low)
    )
    if experience_grounded and isinstance(data.get("experience"), str):
        merged.experience = data["experience"][:60]

    mode_grounded = bool(re.search(r"remote|hybrid|onsite|on-site|work from home|wfh|office", low))
    if mode_grounded:
        for value in data.get("work_mode") or []:
            if isinstance(value, str) and value.lower() in {"remote", "hybrid", "onsite"}:
                if value.lower() not in merged.work_mode:
                    merged.work_mode.append(value.lower())

    type_grounded = bool(re.search(r"intern|full[\s-]?time|part[\s-]?time|contract|permanent", low))
    if type_grounded:
        for value in data.get("employment_type") or []:
            if isinstance(value, str) and value.lower() in {
                "full_time",
                "internship",
                "contract",
                "part_time",
            }:
                if value.lower() not in merged.employment_type:
                    merged.employment_type.append(value.lower())

    freshness_grounded = bool(re.search(r"posted|last|within|past|hours|days|week|month|today", low))
    if freshness_grounded:
        value = data.get("posted_within_days")
        if isinstance(value, int) and 1 <= value <= 365:
            merged.posted_within_days = value

    grounded_skills = set(extract_skills(query))
    for value in data.get("skills") or []:
        if isinstance(value, str) and value in grounded_skills and value not in merged.skills:
            merged.skills.append(value)

    if isinstance(data.get("internship_with_ppo"), bool):
        merged.internship_with_ppo = merged.internship_with_ppo or data["internship_with_ppo"]

    return merged


def merge_refinement(base: StructuredFilters, refinement: StructuredFilters) -> StructuredFilters:
    """Follow-up queries ("only remote ones") update rather than reset."""
    merged = base.model_copy(deep=True)
    if refinement.role:
        merged.role = refinement.role
    if refinement.location:
        merged.location = refinement.location
    if refinement.experience:
        merged.experience = refinement.experience
        merged.minimum_experience_years = refinement.minimum_experience_years
        merged.maximum_experience_years = refinement.maximum_experience_years
    if refinement.minimum_salary is not None:
        merged.minimum_salary = refinement.minimum_salary
    if refinement.maximum_salary is not None:
        merged.maximum_salary = refinement.maximum_salary
    if refinement.employment_type:
        merged.employment_type = refinement.employment_type
    if refinement.work_mode:
        merged.work_mode = refinement.work_mode
    if refinement.skills:
        merged.skills = list(dict.fromkeys(merged.skills + refinement.skills))
    if refinement.posted_within_days is not None:
        merged.posted_within_days = refinement.posted_within_days
    if refinement.internship_with_ppo:
        merged.internship_with_ppo = True
    merged.notes = list(dict.fromkeys(base.notes + refinement.notes))
    return merged


# --------------------------------------------------------------------------
# Field parsers
# --------------------------------------------------------------------------

def _work_modes(low: str) -> list[str]:
    modes: list[str] = []
    if re.search(r"\bremote\b|work from home|\bwfh\b|anywhere", low):
        modes.append("remote")
    if re.search(r"\bhybrid\b", low):
        modes.append("hybrid")
    if re.search(r"\bonsite\b|on-site|in[\s-]?office|in office", low):
        modes.append("onsite")
    return modes


def _employment_types(low: str) -> list[str]:
    types: list[str] = []
    if re.search(r"\bintern(?:ships?)?\b", low):
        types.append("internship")
    if re.search(r"full[\s-]?time|permanent", low):
        types.append("full_time")
    if re.search(r"part[\s-]?time", low):
        types.append("part_time")
    if re.search(r"\bcontract\b", low):
        types.append("contract")
    return types


def _freshness(low: str) -> int | None:
    if re.search(r"last\s+24\s*hours|past\s+24\s*hours|\btoday\b", low):
        return 1
    match = re.search(r"last\s+(\d+)\s*(hour|hours|day|days|week|weeks|month|months)", low)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        if unit.startswith("hour"):
            return max(1, round(value / 24))
        if unit.startswith("week"):
            return value * 7
        if unit.startswith("month"):
            return value * 30
        return value
    if re.search(r"(?:this|last)\s+week", low):
        return 7
    if re.search(r"(?:this|last)\s+month", low):
        return 30
    return None


def _salary(low: str, notes: list[str]) -> tuple[float | None, float | None]:
    unit_multiplier = {"lpa": 100000, "lakh": 100000, "lakhs": 100000, "lac": 100000, "lacs": 100000, "cr": 10000000, "crore": 10000000}
    range_match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*(lpa|lakhs?|lacs?|cr|crore)", low
    )
    if range_match:
        multiplier = unit_multiplier.get(range_match.group(3), 100000)
        return float(range_match.group(1)) * multiplier, float(range_match.group(2)) * multiplier

    single = re.search(r"(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d+)?)\s*(lpa|lakhs?|lacs?|cr|crore)", low)
    if single:
        multiplier = unit_multiplier.get(single.group(2), 100000)
        value = float(single.group(1)) * multiplier
        if not re.search(r"minimum|min\b|at least|above|more than|>=|starting", low):
            notes.append("A single salary figure was treated as the minimum; change it if you meant a maximum.")
        return value, None

    rupees = re.search(r"(?:salary|ctc|package)[^\d]{0,20}(\d{5,9})", low)
    if rupees:
        return float(rupees.group(1)), None

    if re.search(r"\bsalary\b|\bctc\b|package|lpa", low):
        notes.append("Salary keyword found without a number; salary filter not applied.")
    return None, None


def _experience(low: str) -> tuple[str | None, float | None, float | None]:
    if re.search(r"\bfresher|entry[\s-]?level|no experience|new grad|graduate", low):
        return "fresher", 0.0, 1.0
    between = re.search(r"(\d+)\s*(?:-|–|to)\s*(\d+)\s*years?", low)
    if between:
        min_years, max_years = float(between.group(1)), float(between.group(2))
        return f"{int(min_years)}-{int(max_years)} years", min_years, max_years
    at_least = re.search(r"(?:minimum|min|at least|over|more than|above)\s*(\d+)\s*\+?\s*years?", low)
    if at_least:
        value = float(at_least.group(1))
        return f"{int(value)}+ years", value, None
    plus = re.search(r"(\d+)\s*\+\s*years?", low)
    if plus:
        value = float(plus.group(1))
        return f"{int(value)}+ years", value, None
    return None, None, None


def _locations(low: str) -> list[str]:
    locations: list[str] = []
    for alias in sorted(CITY_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", low):
            canonical = CITY_ALIASES[alias]
            if canonical not in locations:
                locations.append(canonical)
    for alias in sorted(COUNTRY_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", low):
            canonical = COUNTRY_ALIASES[alias]
            if canonical not in locations:
                locations.append(canonical)
    return locations


def _roles(text: str) -> list[str]:
    low = text.lower()
    found: list[str] = []

    patterns = (
        r"(?:find|search|show|get|looking for)\s+(?:me\s+)?(.{2,70}?)\s+(?:jobs?|roles?|positions?|openings?|internships?)",
        r"(.{2,70}?)\s+(?:jobs?|roles?|positions?|openings?|internships?)\s+(?:in|near|at|with|for|posted)",
        r"(.{2,70}?)\s+(?:jobs?|roles?|positions?|openings?|internships?)\s*$",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, low):
            candidate = _clean_role(match.group(1))
            if candidate:
                found.append(candidate)

    # Direct mentions of a role with no "jobs" keyword.
    for match in re.finditer(
        r"\b((?:[a-z0-9+#.]+\s+){0,3}(?:engineer|developer|scientist|analyst|architect|consultant|manager|designer|specialist))\b",
        low,
    ):
        candidate = _clean_role(match.group(1))
        if candidate:
            found.append(candidate)

    # Genes like "GenAI" are skills, but "GenAI internships" should still
    # yield a usable role phrase.
    if not found:
        skill_match = re.search(r"\b(genai|gen ai|llm|nlp|ml|ai)\b", low)
        if skill_match and re.search(r"intern|job|role", low):
            found.append(ROLE_CANONICAL.get(skill_match.group(1), skill_match.group(1).upper()))

    result: list[str] = []
    for role in found:
        normalized = _title_role(role)
        if normalized and normalized not in result:
            result.append(normalized)
    return result[:4]


def _clean_role(value: str) -> str | None:
    value = value.strip(" ,.;/|")
    # Remove leading search verbs and adjectives that are not part of a title.
    value = re.sub(
        r"\b(?:find|search|show|get|me|for|a|an|the|jobs?|roles?|positions?|openings?|internships?)\b",
        " ",
        value,
    )
    # Cut at prepositions that introduce filters, never at a work-mode word
    # (e.g. "remote machine learning jobs" must keep "machine learning").
    value = re.sub(r"\b(?:in|near|with|posted|minimum|salary|package|ctc|last|within)\b.*$", "", value)
    tokens = [t for t in value.split() if t and t not in STOPWORDS]
    if not tokens:
        return None
    phrase = " ".join(tokens[:5])
    if len(phrase) < 2:
        return None
    has_title_suffix = any(suffix in phrase for suffix in ROLE_SUFFIXES)
    looks_like_skill = bool(extract_skills(phrase)) or any(
        token.lower() in ROLE_CANONICAL for token in tokens
    )
    if not has_title_suffix and not looks_like_skill and not re.fullmatch(r"[a-z0-9+#. ]{2,20}", phrase):
        return None
    return phrase


def _title_role(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9+#.]+", value)
    if not words:
        return ""
    output: list[str] = []
    for word in words[:6]:
        low = word.lower()
        if low in ROLE_CANONICAL:
            output.append(ROLE_CANONICAL[low])
        elif word.isupper() and len(word) <= 4:
            output.append(word)
        else:
            output.append(word.capitalize())
    role = " ".join(output).strip()
    role = re.sub(r"\s+", " ", role)
    return role[:80]
