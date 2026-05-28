from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scholarly_access_agent.core.urls import (
    any_domain_matches,
    build_proxy_url,
    host_for_url,
)
from scholarly_access_agent.providers.snu.domains import (
    DEFAULT_DOMAINS,
    load_domains,
)


SNU_PROXY_BASE = "https://libproxy.snu.ac.kr/link.n2s?url="


@dataclass(frozen=True)
class SnuProxyProvider:
    domains: tuple[str, ...] = DEFAULT_DOMAINS
    proxy_base: str = SNU_PROXY_BASE
    provider_id: str = "snu"

    @classmethod
    def from_domains_file(cls, path: Path) -> "SnuProxyProvider":
        return cls(domains=load_domains(path))

    def supports_url(self, url: str) -> bool:
        return any_domain_matches(host_for_url(url), self.domains)

    def proxied_url(self, url: str) -> str:
        return build_proxy_url(url, self.proxy_base)
