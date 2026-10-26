"""Pure illustration fields for the church bot and the sermon builder.

Scripture is stored as the pastor typed it, plus book and chapter so a search
can ask for a book or a chapter. Fact-check is verified, testimony, or
needs_review. Kind is testimony, historical, science, or bible.
"""

from __future__ import annotations

import re
from datetime import date, datetime

_TRANSLATION_TAIL = re.compile(r"\s*[\(\[]([A-Za-z0-9]{2,15})[\)\]]\s*$")
_KNOWN_TRANSLATION = {
    "kjv", "esv", "niv", "nkjv", "nasb", "nlt", "csb", "asv", "bbe",
    "rsv", "nrsv", "amp", "msg", "web", "ylt", "lsb", "net",
}
_FACT = {
    "verified": "verified",
    "verify": "verified",
    "testimony": "testimony",
    "testimonial": "testimony",
    "needs review": "needs_review",
    "need review": "needs_review",
    "needsreview": "needs_review",
    "review": "needs_review",
    "unverified": "needs_review",
}
_KIND = {
    "testimony": "testimony",
    "historical": "historical",
    "history": "historical",
    "historic": "historical",
    "science": "science",
    "scientific": "science",
    "bible": "bible",
    "biblical": "bible",
}
_TRUTHY = {"1", "true", "yes", "on"}


def truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return str(value or "").strip().lower() in _TRUTHY


def blank_date(value):
    """Empty, missing, and MySQL zero dates become no date."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        if value.year < 1:
            return None
        return value.isoformat()
    text = str(value).strip()
    if not text or text.startswith("0000-00-00"):
        return None
    return text[:10]


def title_key(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def tag_name(value) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "").strip()).strip(" ,")
    if not text:
        return None
    return text[:80]


def passage_from(body) -> tuple[object, bool]:
    """primary_passage wins when it has words. passage is the same field."""
    if not isinstance(body, dict):
        return None, False
    has_primary = "primary_passage" in body
    has_passage = "passage" in body
    if has_primary:
        primary = body.get("primary_passage")
        if str(primary or "").strip() or not has_passage:
            return primary, True
    if has_passage:
        return body.get("passage"), True
    return None, False


def wants_explicit_insert(body) -> bool:
    if not isinstance(body, dict):
        return False
    return truthy(body.get("insert")) or truthy(body.get("add_section"))


def link_without_section(body) -> str | None:
    """A link with no section id must not insert a section."""
    if not isinstance(body, dict):
        return None
    if body.get("section_id") not in (None, "", 0, "0"):
        return None
    if wants_explicit_insert(body):
        return None
    raw = body.get("illustration_id")
    if raw in (None, "", 0, "0"):
        return None
    return (
        "Linking an illustration needs a section_id. "
        "Use POST /api/bot/sermons/<id>/sections/link. "
        "This call does not add a section."
    )


def normalize_fact(value) -> str | None:
    key = re.sub(r"[\s_-]+", " ", str(value or "").strip().lower())
    return _FACT.get(key)


def normalize_kind(value) -> str | None:
    key = re.sub(r"[\s_-]+", " ", str(value or "").strip().lower())
    return _KIND.get(key)


def _canon_names() -> list[str]:
    from app.models.pastoral.bible import BIBLE_BOOKS
    names = [name for name, *_rest in BIBLE_BOOKS]
    names.sort(key=len, reverse=True)
    return names


def _canon_set() -> set[str]:
    from app.models.pastoral.bible import BIBLE_BOOKS
    return {name for name, *_rest in BIBLE_BOOKS}


def _split_translation(text: str) -> tuple[str, str | None]:
    match = _TRANSLATION_TAIL.search(text)
    if match:
        return text[: match.start()].strip(), match.group(1).upper()[:40]
    parts = text.split()
    if len(parts) >= 2 and parts[-1].lower() in _KNOWN_TRANSLATION:
        return " ".join(parts[:-1]).strip(), parts[-1].upper()[:40]
    return text, None


def _match_book(text: str) -> tuple[str | None, str]:
    lowered = text.lower()
    for name in _canon_names():
        key = name.lower()
        if lowered == key or lowered.startswith(key + " ") or lowered.startswith(key + ":"):
            return name, text[len(name):].strip(" :")
    from app.models.pastoral.bible import normalize_book_name
    known = _canon_set()
    parts = text.split()
    for count in range(min(4, len(parts)), 0, -1):
        candidate = " ".join(parts[:count])
        canon = normalize_book_name(candidate)
        if canon in known:
            return canon, " ".join(parts[count:]).strip(" :")
    return None, text


def parse_scripture(value) -> dict:
    """Book and chapter from a reference. Verse is optional. Translation may sit at the end."""
    raw = str(value or "").strip()
    if not raw:
        return {"reference": None, "book": None, "chapter": None, "translation": None}
    body, translation = _split_translation(raw)
    book, rest = _match_book(body)
    chapter = None
    if rest:
        match = re.match(r"(\d+)", rest)
        if match:
            chapter = int(match.group(1))
    return {
        "reference": raw[:500],
        "book": book,
        "chapter": chapter,
        "translation": translation,
    }


def meta_columns(body) -> tuple[dict | None, str | None]:
    """Column updates for an illustration. Missing keys are left alone."""
    if not isinstance(body, dict):
        return {}, None
    out: dict = {}
    if "scripture_reference" in body or "scripture" in body:
        raw = body.get("scripture_reference")
        if (raw is None or str(raw).strip() == "") and "scripture" in body:
            raw = body.get("scripture")
        parsed = parse_scripture(raw)
        out["scripture_reference"] = parsed["reference"]
        out["scripture_book"] = parsed["book"]
        out["scripture_chapter"] = parsed["chapter"]
        if parsed["translation"] and "translation" not in body and "scripture_translation" not in body:
            out["scripture_translation"] = parsed["translation"]
    if "translation" in body or "scripture_translation" in body:
        raw = body.get("translation") if "translation" in body else body.get("scripture_translation")
        text = str(raw or "").strip()[:40]
        out["scripture_translation"] = text or None
    if "fact_check" in body or "fact" in body:
        raw = body.get("fact_check") if "fact_check" in body else body.get("fact")
        if raw in (None, ""):
            out["fact_check"] = None
        else:
            fact = normalize_fact(raw)
            if not fact:
                return None, "fact_check must be verified, testimony, or needs_review."
            out["fact_check"] = fact
    if "kind" in body:
        raw = body.get("kind")
        if raw in (None, ""):
            out["kind"] = None
        else:
            kind = normalize_kind(raw)
            if not kind:
                return None, "kind must be testimony, historical, science, or bible."
            out["kind"] = kind
    return out, None


def rewrite_tags(tags: list[str], sources: list[str], destination: str) -> tuple[list[str], bool]:
    """Replace source tag names with destination. Returns the new list and whether it changed."""
    source_keys = {item.lower() for item in sources if item}
    dest = tag_name(destination) or ""
    changed = False
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        name = tag_name(raw)
        if not name:
            continue
        if name.lower() in source_keys:
            changed = True
            name = dest
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out, changed


def tag_rename_request(body) -> tuple[list[str], str, str | None]:
    """Sources and one destination. merge and from name the tags to replace."""
    if not isinstance(body, dict):
        return [], "", "Send from and to, or merge and to."
    dest = tag_name(body.get("to") if body.get("to") not in (None, "") else body.get("into") or body.get("name"))
    raw_sources = []
    merge = body.get("merge")
    if isinstance(merge, list):
        raw_sources.extend(merge)
    elif isinstance(merge, str) and merge.strip():
        raw_sources.extend(part.strip() for part in merge.split(","))
    for key in ("from", "rename", "old", "tag"):
        if body.get(key) not in (None, ""):
            raw_sources.append(body.get(key))
    sources: list[str] = []
    seen: set[str] = set()
    for raw in raw_sources:
        name = tag_name(raw)
        if not name:
            continue
        if dest and name.lower() == dest.lower():
            continue
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        sources.append(name)
    if not dest:
        return [], "", "Send the new tag name as to."
    if not sources:
        return [], "", "Send the tag to rename as from, or a merge list."
    return sources, dest, None
