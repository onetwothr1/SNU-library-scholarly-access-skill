from __future__ import annotations

from urllib.parse import quote, urlparse


def host_for_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Expected an absolute http(s) URL, got: {url}")
    return normalize_host(parsed.hostname or "")


def normalize_host(host: str) -> str:
    host = host.strip().lower().rstrip(".")
    if host.startswith("www."):
        return host[4:]
    return host


def domain_matches(host: str, pattern: str) -> bool:
    normalized_host = normalize_host(host)
    normalized_pattern = normalize_host(pattern)

    if normalized_pattern.startswith("*."):
        bare = normalized_pattern[2:]
        return normalized_host == bare or normalized_host.endswith(f".{bare}")

    return normalized_host == normalized_pattern or normalized_host.endswith(
        f".{normalized_pattern}"
    )


def any_domain_matches(host: str, patterns: list[str] | tuple[str, ...]) -> bool:
    return any(domain_matches(host, pattern) for pattern in patterns)


def build_proxy_url(url: str, proxy_base: str) -> str:
    host_for_url(url)
    return f"{proxy_base}{quote(url, safe='')}"
