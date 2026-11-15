"""
Skill recognition. A skill is only "found" when its literal token occurs in
the supplied text — this module recognises, it never infers.
"""
import re

from app.core.constants import SKILL_ALIASES

# Longest aliases first so "spring boot" wins over "spring", "node.js" over
# "node", etc. Escaping keeps C++ / C# / Next.js safe as regular expressions.
_ALIAS_PATTERN = re.compile(
    r"(?<![A-Za-z0-9+#.])("
    + "|".join(re.escape(alias) for alias in sorted(SKILL_ALIASES, key=len, reverse=True))
    + r")(?![A-Za-z0-9+#])",
    re.IGNORECASE,
)


def extract_skills(text: str | None) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for match in _ALIAS_PATTERN.finditer(text):
        canonical = SKILL_ALIASES[match.group(1).lower()]
        if canonical not in seen:
            seen.add(canonical)
            found.append(canonical)
    return found


def normalize_skill(skill: str) -> str:
    return re.sub(r"[^a-z0-9+#.]", "", skill.lower())


def skill_tokens_match(a: str, b: str) -> bool:
    """Alias-aware comparison used when diffing resume vs job skills."""
    na, nb = normalize_skill(a), normalize_skill(b)
    if na == nb:
        return True
    aliases = {
        "postgres": "postgresql",
        "nodejs": "node",
        "nextjs": "next",
        "ml": "machinelearning",
        "genai": "generativeai",
        "nlp": "naturallanguageprocessing",
    }
    return aliases.get(na, na) == aliases.get(nb, nb)
