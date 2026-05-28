from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Any

from scholarly_access_agent.core.urls import normalize_host

_BUILTIN_DOMAINS_FILE = Path(__file__).parent.parent.parent / "data" / "journal_domains.json"

DOMAIN_LIST_KEYS = frozenset({"domains", "urls", "matches", "patterns"})
DOMAIN_VALUE_KEYS = frozenset({"domain", "host", "url", "pattern", "match", "value"})


def _domain_pattern_from_string(value: str) -> str:
    text = value.strip()
    if not text:
        return ""

    if "://" in text:
        text = text.split("://", 1)[1]

    text = text.split("/", 1)[0]
    text = text.split("?", 1)[0]
    text = text.split("#", 1)[0]
    text = text.strip().rstrip(".")

    if text.startswith("*."):
        return f"*.{normalize_host(text[2:])}"

    if text.startswith("*"):
        text = text.lstrip("*. ")

    if ":" in text:
        text = text.split(":", 1)[0]

    return normalize_host(text)


def _dedupe(values: Iterable[str]) -> Iterable[str]:
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            yield value


def _domain_patterns(data: object) -> Iterable[str]:
    if isinstance(data, str):
        yield _domain_pattern_from_string(data)
        return

    if isinstance(data, list):
        for item in data:
            yield from _domain_patterns(item)
        return

    if isinstance(data, dict):
        for key, value in data.items():
            if key in DOMAIN_LIST_KEYS:
                yield from _domain_patterns(value)
            elif key in DOMAIN_VALUE_KEYS and isinstance(value, str):
                yield _domain_pattern_from_string(value)


def load_domains(path: Path) -> tuple[str, ...]:
    data = json.loads(path.read_text(encoding="utf-8"))
    domains = tuple(_dedupe(_domain_patterns(data)))
    if not domains:
        raise ValueError("Domain file did not contain any supported domain entries.")
    return domains


DEFAULT_DOMAINS: tuple[str, ...] = load_domains(_BUILTIN_DOMAINS_FILE)


def add_domain(domain: str) -> dict[str, Any]:
    normalized = _domain_pattern_from_string(domain)
    if not normalized:
        raise ValueError(f"Could not normalize domain: {domain!r}")

    path = _BUILTIN_DOMAINS_FILE
    data = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, list):
        if normalized in data:
            return {"ok": True, "domain": normalized, "status": "already_exists"}
        data.append(normalized)
    elif isinstance(data, dict):
        for key in DOMAIN_LIST_KEYS:
            if key in data and isinstance(data[key], list):
                if normalized in data[key]:
                    return {"ok": True, "domain": normalized, "status": "already_exists"}
                data[key].append(normalized)
                break
        else:
            raise ValueError("Unsupported domains file format.")
    else:
        raise ValueError("Unsupported domains file format.")

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "domain": normalized, "status": "added"}
