from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping

from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from scholarly_access_agent.providers.snu.login import (
    PageSnapshot,
    detect_login_required,
)
from scholarly_access_agent.providers.snu.proxy import SnuProxyProvider
from scholarly_access_agent.runtime.browser import (
    DEFAULT_PROFILE_DIR,
    BrowserRuntimeUnavailable,
    _load_sync_playwright,
    capture_page_snapshot,
)


DEFAULT_DOWNLOAD_DIR = Path("downloads")
DEFAULT_TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 50 * 1024 * 1024
USER_AGENT = "scholarly-access-agent/0.1"


@dataclass(frozen=True)
class PdfCandidate:
    href: str
    text: str
    context: str = ""


@dataclass(frozen=True)
class PdfDownloadResult:
    ok: bool
    provider: str
    source_url: str
    status: str
    download_dir: str
    pdf_url: str | None = None
    output_path: str | None = None
    bytes_written: int | None = None
    reason: str | None = None
    message: str | None = None
    candidates: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "ok": self.ok,
            "provider": self.provider,
            "source_url": self.source_url,
            "status": self.status,
            "download_dir": self.download_dir,
        }
        optional: dict[str, object] = {
            "pdf_url": self.pdf_url,
            "output_path": self.output_path,
            "bytes_written": self.bytes_written,
            "reason": self.reason,
            "message": self.message,
        }
        payload.update(
            {key: value for key, value in optional.items() if value is not None}
        )
        if self.candidates:
            payload["candidates"] = self.candidates
        return payload


@dataclass(frozen=True)
class PdfDiscoverResult:
    ok: bool
    provider: str
    source_url: str
    status: str
    candidates: list[dict[str, str]] = field(default_factory=list)
    reason: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "ok": self.ok,
            "provider": self.provider,
            "source_url": self.source_url,
            "status": self.status,
        }
        optional: dict[str, object] = {
            "reason": self.reason,
            "message": self.message,
        }
        payload.update(
            {key: value for key, value in optional.items() if value is not None}
        )
        if self.candidates:
            payload["candidates"] = self.candidates
        return payload


def download_pdf(
    source_url: str,
    *,
    provider: SnuProxyProvider | None = None,
    pdf_url: str | None = None,
    download_dir: Path = DEFAULT_DOWNLOAD_DIR,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    browser_channel: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    headless: bool = True,
) -> PdfDownloadResult:
    provider = provider or SnuProxyProvider()
    resolved_download_dir = (download_dir or DEFAULT_DOWNLOAD_DIR).resolve()
    resolved_profile_dir = (profile_dir or DEFAULT_PROFILE_DIR).resolve()

    if not provider.supports_url(source_url):
        return _failure(
            provider=provider,
            source_url=source_url,
            download_dir=resolved_download_dir,
            status="unsupported",
            reason="unsupported_domain",
            message="The URL host is not in the configured provider domain list.",
        )

    if pdf_url:
        return _download_pdf_direct(
            source_url, pdf_url, provider, resolved_download_dir, timeout_seconds,
        )

    proxy_url = provider.proxied_url(source_url)

    playwright_factory = _try_load_playwright()
    if playwright_factory is None:
        return _download_via_urllib(
            source_url, proxy_url, provider, resolved_download_dir, timeout_seconds,
        )

    return _download_via_playwright(
        source_url, proxy_url, provider, resolved_download_dir,
        resolved_profile_dir, browser_channel, timeout_seconds, headless,
        playwright_factory,
    )


def discover_pdfs(
    source_url: str,
    *,
    provider: SnuProxyProvider | None = None,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    browser_channel: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    headless: bool = True,
) -> PdfDiscoverResult:
    provider = provider or SnuProxyProvider()
    resolved_profile_dir = (profile_dir or DEFAULT_PROFILE_DIR).resolve()

    if not provider.supports_url(source_url):
        return _discover_failure(
            provider=provider,
            source_url=source_url,
            status="unsupported",
            reason="unsupported_domain",
            message="The URL host is not in the configured provider domain list.",
        )

    proxy_url = provider.proxied_url(source_url)

    playwright_factory = _try_load_playwright()
    if playwright_factory is None:
        return _discover_via_urllib(
            source_url, proxy_url, provider, timeout_seconds,
        )

    return _discover_via_playwright(
        source_url, proxy_url, provider, resolved_profile_dir,
        browser_channel, timeout_seconds, headless, playwright_factory,
    )


# ---------------------------------------------------------------------------
# PDF download helpers
# ---------------------------------------------------------------------------


def _download_pdf_direct(
    source_url: str,
    pdf_url: str,
    provider: SnuProxyProvider,
    download_dir: Path,
    timeout_seconds: int,
) -> PdfDownloadResult:
    """Download a specific PDF URL without page discovery."""
    playwright_factory = _try_load_playwright()
    if playwright_factory is not None:
        try:
            return _download_pdf_direct_playwright(
                source_url, pdf_url, provider, download_dir,
                timeout_seconds, playwright_factory,
            )
        except Exception:
            pass

    try:
        pdf = _fetch(pdf_url, timeout_seconds=timeout_seconds)
    except HTTPError as exc:
        return _http_failure(provider, source_url, download_dir, exc)
    except URLError as exc:
        return _failure(
            provider=provider,
            source_url=source_url,
            download_dir=download_dir,
            status="download_failed",
            pdf_url=pdf_url,
            reason="download_failed",
            message=str(exc.reason),
        )

    if not _is_pdf_response(pdf.url, pdf.headers, pdf.body):
        return _failure(
            provider=provider,
            source_url=source_url,
            download_dir=download_dir,
            status="download_failed",
            pdf_url=pdf.url,
            reason="download_failed",
            message="The provided PDF URL did not return PDF content.",
        )

    return _save_pdf(provider, source_url, pdf.url, pdf.body, download_dir)


def _download_pdf_direct_playwright(
    source_url: str,
    pdf_url: str,
    provider: SnuProxyProvider,
    download_dir: Path,
    timeout_seconds: int,
    playwright_factory,
) -> PdfDownloadResult:
    timeout_ms = timeout_seconds * 1000
    with playwright_factory() as p:
        context = p.chromium.launch_persistent_context(headless=True)
        try:
            api = context.request
            pdf_resp = api.get(pdf_url, timeout=timeout_ms)
            pdf_headers = dict(pdf_resp.headers)
            pdf_body = pdf_resp.body()

            if not pdf_resp.ok:
                return _failure(
                    provider=provider,
                    source_url=source_url,
                    download_dir=download_dir,
                    status="download_failed",
                    pdf_url=pdf_resp.url,
                    reason="download_failed",
                    message=f"HTTP {pdf_resp.status}: {pdf_resp.status_text}",
                )

            if not _is_pdf_response(pdf_resp.url, pdf_headers, pdf_body):
                return _failure(
                    provider=provider,
                    source_url=source_url,
                    download_dir=download_dir,
                    status="download_failed",
                    pdf_url=pdf_resp.url,
                    reason="download_failed",
                    message="The provided PDF URL did not return PDF content.",
                )

            return _save_pdf(provider, source_url, pdf_resp.url, pdf_body, download_dir)
        finally:
            context.close()


def _download_via_urllib(
    source_url: str,
    proxy_url: str,
    provider: SnuProxyProvider,
    download_dir: Path,
    timeout_seconds: int,
) -> PdfDownloadResult:
    try:
        first = _fetch(proxy_url, timeout_seconds=timeout_seconds)
    except HTTPError as exc:
        return _http_failure(provider, source_url, download_dir, exc)
    except URLError as exc:
        return _failure(
            provider=provider,
            source_url=source_url,
            download_dir=download_dir,
            status="download_failed",
            reason="download_failed",
            message=str(exc.reason),
        )

    if _is_pdf_response(first.url, first.headers, first.body):
        return _save_pdf(provider, source_url, first.url, first.body, download_dir)

    page = _parse_html(first.body, first.headers)
    login = detect_login_required(
        PageSnapshot(
            url=first.url,
            title=page.title,
            body_text=page.text,
            has_password_field=page.has_password_field,
        )
    )
    if login.required:
        return _failure(
            provider=provider,
            source_url=source_url,
            download_dir=download_dir,
            status="login_required",
            reason=login.reason or "login_required",
            message=login.message or "Login is required before PDF download.",
        )

    candidates = page.all_pdf_candidates(first.url)
    if not candidates:
        return _failure(
            provider=provider,
            source_url=source_url,
            download_dir=download_dir,
            status="no_pdf_found",
            reason="no_pdf_found",
            message="No downloadable PDF link was found on the page.",
        )

    candidate_url = candidates[0].href

    try:
        pdf = _fetch(candidate_url, timeout_seconds=timeout_seconds)
    except HTTPError as exc:
        return _http_failure(provider, source_url, download_dir, exc)
    except URLError as exc:
        return _failure(
            provider=provider,
            source_url=source_url,
            download_dir=download_dir,
            status="download_failed",
            pdf_url=candidate_url,
            reason="download_failed",
            message=str(exc.reason),
        )

    if not _is_pdf_response(pdf.url, pdf.headers, pdf.body):
        return _failure(
            provider=provider,
            source_url=source_url,
            download_dir=download_dir,
            status="download_failed",
            pdf_url=pdf.url,
            reason="download_failed",
            message="The discovered PDF link did not return PDF content.",
        )

    return _save_pdf(provider, source_url, pdf.url, pdf.body, download_dir)


def _download_via_playwright(
    source_url: str,
    proxy_url: str,
    provider: SnuProxyProvider,
    download_dir: Path,
    profile_dir: Path,
    browser_channel: str | None,
    timeout_seconds: int,
    headless: bool,
    playwright_factory,
) -> PdfDownloadResult:
    timeout_ms = timeout_seconds * 1000
    profile_dir.mkdir(parents=True, exist_ok=True)

    with playwright_factory() as p:
        launch_options: dict[str, object] = {
            "user_data_dir": str(profile_dir),
            "headless": headless,
        }
        if browser_channel:
            launch_options["channel"] = browser_channel

        context = p.chromium.launch_persistent_context(**launch_options)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(timeout_ms)

            try:
                response = page.goto(
                    proxy_url, wait_until="domcontentloaded", timeout=timeout_ms,
                )
                _wait_for_page_ready(page, timeout_ms)
            except Exception as exc:
                return _failure(
                    provider=provider,
                    source_url=source_url,
                    download_dir=download_dir,
                    status="download_failed",
                    reason="navigation_failed",
                    message=str(exc),
                )

            snapshot = capture_page_snapshot(page)
            login = detect_login_required(snapshot)
            if login.required:
                from scholarly_access_agent.providers.snu.login import attempt_auto_login
                if attempt_auto_login(page):
                    try:
                        page.goto(
                            proxy_url, wait_until="domcontentloaded", timeout=timeout_ms,
                        )
                        _wait_for_page_ready(page, timeout_ms)
                    except Exception:
                        pass
                    snapshot = capture_page_snapshot(page)
                    login = detect_login_required(snapshot)
                    if login.required:
                        return _failure(
                            provider=provider,
                            source_url=source_url,
                            download_dir=download_dir,
                            status="login_required",
                            reason="auto_login_incomplete",
                            message="Auto-login was attempted but the page still requires login.",
                        )
                else:
                    return _failure(
                        provider=provider,
                        source_url=source_url,
                        download_dir=download_dir,
                        status="login_required",
                        reason=login.reason or "login_required",
                        message=login.message or "Login is required before PDF download.",
                    )

            content_type = (
                response.headers.get("content-type", "") if response else ""
            ).lower()
            if "application/pdf" in content_type:
                body = response.body() if response else b""
                if _looks_like_pdf_body(body):
                    return _save_pdf(
                        provider,
                        source_url,
                        response.url if response else page.url,
                        body,
                        download_dir,
                    )

            page_obj = _parse_html(
                page.content().encode("utf-8"),
                {"content-type": "text/html; charset=utf-8"},
            )

            candidates = page_obj.all_pdf_candidates(page.url)

            # Also collect Playwright-level link context
            pw_candidates = _discover_pdf_links_playwright(page)
            if pw_candidates:
                candidates = pw_candidates

            if not candidates:
                return _failure(
                    provider=provider,
                    source_url=source_url,
                    download_dir=download_dir,
                    status="no_pdf_found",
                    reason="no_pdf_found",
                    message="No downloadable PDF link was found on the page.",
                )

            candidate_url = candidates[0].href
            api = context.request
            pdf_resp = api.get(candidate_url, timeout=timeout_ms)
            pdf_headers = dict(pdf_resp.headers)
            pdf_body = pdf_resp.body()

            if pdf_resp.status in {401, 403}:
                return _failure(
                    provider=provider,
                    source_url=source_url,
                    download_dir=download_dir,
                    status="login_required",
                    reason="login_required",
                    message=f"HTTP {pdf_resp.status} suggests login or access approval is required.",
                    candidates=_candidates_to_dicts(candidates),
                )

            if not pdf_resp.ok:
                return _failure(
                    provider=provider,
                    source_url=source_url,
                    download_dir=download_dir,
                    status="download_failed",
                    pdf_url=pdf_resp.url,
                    reason="download_failed",
                    message=f"HTTP {pdf_resp.status}: {pdf_resp.status_text}",
                    candidates=_candidates_to_dicts(candidates),
                )

            if not _is_pdf_response(pdf_resp.url, pdf_headers, pdf_body):
                return _failure(
                    provider=provider,
                    source_url=source_url,
                    download_dir=download_dir,
                    status="download_failed",
                    pdf_url=pdf_resp.url,
                    reason="download_failed",
                    message="The discovered PDF link did not return PDF content.",
                    candidates=_candidates_to_dicts(candidates),
                )

            return _save_pdf(
                provider, source_url, pdf_resp.url, pdf_body, download_dir,
            )
        finally:
            context.close()


# ---------------------------------------------------------------------------
# PDF discovery helpers
# ---------------------------------------------------------------------------


def _discover_via_urllib(
    source_url: str,
    proxy_url: str,
    provider: SnuProxyProvider,
    timeout_seconds: int,
) -> PdfDiscoverResult:
    try:
        first = _fetch(proxy_url, timeout_seconds=timeout_seconds)
    except HTTPError as exc:
        return _discover_failure(
            provider=provider,
            source_url=source_url,
            status="download_failed",
            reason="download_failed",
            message=f"HTTP {exc.code}: {exc.reason}",
        )
    except URLError as exc:
        return _discover_failure(
            provider=provider,
            source_url=source_url,
            status="download_failed",
            reason="download_failed",
            message=str(exc.reason),
        )

    if _is_pdf_response(first.url, first.headers, first.body):
        candidates = [
            {"href": first.url, "text": "(direct PDF)", "context": ""}
        ]
        return PdfDiscoverResult(
            ok=True,
            provider=provider.provider_id,
            source_url=source_url,
            status="discovered",
            candidates=candidates,
        )

    page = _parse_html(first.body, first.headers)
    login = detect_login_required(
        PageSnapshot(
            url=first.url,
            title=page.title,
            body_text=page.text,
            has_password_field=page.has_password_field,
        )
    )
    if login.required:
        return _discover_failure(
            provider=provider,
            source_url=source_url,
            status="login_required",
            reason="login_required",
            message=login.message or "Login is required before PDF discovery.",
        )

    html_candidates = page.all_pdf_candidates(first.url)
    candidates = _candidates_to_dicts(html_candidates)

    if not candidates:
        return _discover_failure(
            provider=provider,
            source_url=source_url,
            status="no_pdf_found",
            reason="no_pdf_found",
            message="No downloadable PDF link was found on the page.",
        )

    return PdfDiscoverResult(
        ok=True,
        provider=provider.provider_id,
        source_url=source_url,
        status="discovered",
        candidates=candidates,
    )


def _discover_via_playwright(
    source_url: str,
    proxy_url: str,
    provider: SnuProxyProvider,
    profile_dir: Path,
    browser_channel: str | None,
    timeout_seconds: int,
    headless: bool,
    playwright_factory,
) -> PdfDiscoverResult:
    timeout_ms = timeout_seconds * 1000
    profile_dir.mkdir(parents=True, exist_ok=True)

    with playwright_factory() as p:
        _trace("[discover] playwright loaded")

        launch_options: dict[str, object] = {
            "user_data_dir": str(profile_dir),
            "headless": headless,
        }
        if browser_channel:
            launch_options["channel"] = browser_channel

        _trace("[discover] launching persistent context ...")
        context = p.chromium.launch_persistent_context(**launch_options)
        _trace("[discover] context launched")
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(timeout_ms)
            _trace(f"[discover] navigating to proxy URL (timeout={timeout_ms}ms) ...")

            try:
                page.goto(
                    proxy_url, wait_until="domcontentloaded", timeout=timeout_ms,
                )
                _trace("[discover] domcontentloaded fired, waiting for page ready ...")
                _wait_for_page_ready(page, timeout_ms)
                _trace("[discover] page ready")
            except Exception as exc:
                _trace(f"[discover] navigation failed: {exc}")
                return _discover_failure(
                    provider=provider,
                    source_url=source_url,
                    status="download_failed",
                    reason="navigation_failed",
                    message=str(exc),
                )

            _trace("[discover] capturing page snapshot ...")
            snapshot = capture_page_snapshot(page)
            login = detect_login_required(snapshot)
            _trace(f"[discover] login_required={login.required}")
            if login.required:
                from scholarly_access_agent.providers.snu.login import attempt_auto_login
                _trace("[discover] attempting auto-login ...")
                if attempt_auto_login(page):
                    _trace("[discover] auto-login ok, re-navigating ...")
                    try:
                        page.goto(
                            proxy_url, wait_until="domcontentloaded", timeout=timeout_ms,
                        )
                        _wait_for_page_ready(page, timeout_ms)
                    except Exception:
                        pass
                    snapshot = capture_page_snapshot(page)
                    login = detect_login_required(snapshot)
                    if login.required:
                        _trace("[discover] still login_required after auto-login")
                        return _discover_failure(
                            provider=provider,
                            source_url=source_url,
                            status="login_required",
                            reason="auto_login_incomplete",
                            message="Auto-login was attempted but the page still requires login.",
                        )
                else:
                    _trace("[discover] auto-login skipped or failed")
                    return _discover_failure(
                        provider=provider,
                        source_url=source_url,
                        status="login_required",
                        reason=login.reason or "login_required",
                        message=login.message or "Login is required before PDF discovery.",
                    )

            _trace("[discover] running JS pdf link discovery ...")
            candidates = _discover_pdf_links_playwright(page)
            _trace(f"[discover] JS discovery found {len(candidates)} candidates")

            # Fall back to HTML-parsed candidates
            if not candidates:
                _trace("[discover] falling back to HTML content parse ...")
                page_obj = _parse_html(
                    page.content().encode("utf-8"),
                    {"content-type": "text/html; charset=utf-8"},
                )
                candidates = page_obj.all_pdf_candidates(page.url)
                _trace(f"[discover] HTML parse found {len(candidates)} candidates")

            candidate_dicts = _candidates_to_dicts(candidates)

            if not candidate_dicts:
                return _discover_failure(
                    provider=provider,
                    source_url=source_url,
                    status="no_pdf_found",
                    reason="no_pdf_found",
                    message="No downloadable PDF link was found on the page.",
                )

            return PdfDiscoverResult(
                ok=True,
                provider=provider.provider_id,
                source_url=source_url,
                status="discovered",
                candidates=candidate_dicts,
            )
        finally:
            context.close()


def _trace(msg: str) -> None:
    """Write a timestamped trace message to stderr (never stdout, to keep MCP clean)."""
    ts = time.monotonic()
    sys.stderr.write(f"[{ts:07.2f}] {msg}\n")
    sys.stderr.flush()


def _wait_for_page_ready(page: Any, timeout_ms: int) -> None:
    """Wait for page to settle after navigation.

    Uses ``load`` state (not ``networkidle``) because publisher pages often have
    persistent connections (analytics, websockets, polling) that prevent the
    page from ever reaching network-idle.
    """
    _trace("[wait] waiting for 'load' state ...")
    try:
        page.wait_for_load_state("load", timeout=min(timeout_ms, 15_000))
        _trace("[wait] 'load' state reached")
    except Exception:
        _trace("[wait] 'load' state timed out, continuing")
    # Extra settle time for JS-rendered content (React/Vue shadow DOM, etc.)
    _trace("[wait] settle delay 4s ...")
    page.wait_for_timeout(4_000)
    _trace("[wait] settle done")


def _discover_pdf_links_playwright(page: Any) -> list[PdfCandidate]:
    """Extract all PDF candidate links with context via a single JS evaluation."""
    _trace("[js-discover] running page.evaluate() ...")
    try:
        raw = page.evaluate(
            """() => {
                const results = [];
                const links = document.querySelectorAll('a[href]');
                for (const link of links) {
                    const href = link.href || '';
                    if (!href || href.startsWith('javascript:') || href.startsWith('mailto:') || href.startsWith('#'))
                        continue;
                    const text = (link.textContent || '').trim();
                    const isPdf = href.endsWith('.pdf')
                        || (text.toLowerCase().includes('pdf') && href.toLowerCase().includes('pdf'));
                    if (!isPdf) continue;
                    const parent = link.closest('li, div, p, section, article');
                    const context = (parent?.textContent || text).trim().slice(0, 300);
                    results.push({ href, text, context });
                }
                return results;
            }"""
        )
    except Exception as exc:
        _trace(f"[js-discover] evaluate failed: {exc}")
        return []

    candidates: list[PdfCandidate] = []
    for item in raw:
        candidates.append(
            PdfCandidate(
                href=str(item.get("href", "")),
                text=str(item.get("text", "")),
                context=str(item.get("context", "")),
            )
        )
    _trace(f"[js-discover] evaluate returned {len(candidates)} raw candidates")
    return candidates


def _candidates_to_dicts(candidates: list[PdfCandidate]) -> list[dict[str, str]]:
    return [{"href": c.href, "text": c.text, "context": c.context} for c in candidates]


# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------


def _try_load_playwright():
    try:
        return _load_sync_playwright()
    except BrowserRuntimeUnavailable:
        return None


@dataclass(frozen=True)
class _FetchResult:
    url: str
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class _Link:
    href: str
    text: str


class _HtmlPage:
    def __init__(
        self,
        *,
        title: str,
        text: str,
        links: list[_Link],
        has_password_field: bool,
    ) -> None:
        self.title = title
        self.text = text
        self.links = links
        self.has_password_field = has_password_field

    def all_pdf_candidates(self, base_url: str) -> list[PdfCandidate]:
        results: list[PdfCandidate] = []
        for link in self.links:
            href = link.href.strip()
            if not href or href.startswith(("#", "javascript:", "mailto:")):
                continue
            absolute = urljoin(base_url, href)
            if _looks_like_pdf_url(absolute):
                results.append(PdfCandidate(href=absolute, text=link.text))
            elif "pdf" in link.text.lower() and "pdf" in urlparse(absolute).path.lower():
                results.append(PdfCandidate(href=absolute, text=link.text))
        return results


class _PdfLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[_Link] = []
        self.has_password_field = False
        self._in_title = False
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attr_map = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "title":
            self._in_title = True
        elif tag.lower() == "a" and attr_map.get("href"):
            self._current_href = attr_map["href"]
            self._current_text = []
        elif tag.lower() == "input":
            input_type = attr_map.get("type", "").lower()
            if input_type == "password":
                self.has_password_field = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
        elif tag.lower() == "a" and self._current_href is not None:
            self.links.append(
                _Link(self._current_href, " ".join(self._current_text).strip())
            )
            self._current_href = None
            self._current_text = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        self.text_parts.append(text)
        if self._in_title:
            self.title_parts.append(text)
        if self._current_href is not None:
            self._current_text.append(text)

    def page(self) -> _HtmlPage:
        return _HtmlPage(
            title=" ".join(self.title_parts).strip(),
            text=" ".join(self.text_parts).strip(),
            links=self.links,
            has_password_field=self.has_password_field,
        )


def _fetch(url: str, *, timeout_seconds: int) -> _FetchResult:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout_seconds) as response:
        body = _read_limited(response, MAX_RESPONSE_BYTES)
        return _FetchResult(
            url=response.geturl(),
            headers=dict(response.headers.items()),
            body=body,
        )


def _read_limited(response: object, max_bytes: int) -> bytes:
    body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise URLError(f"response exceeded {max_bytes} bytes")
    return body


def _parse_html(body: bytes, headers: Mapping[str, str]) -> _HtmlPage:
    parser = _PdfLinkParser()
    parser.feed(body.decode(_charset(headers), errors="replace"))
    return parser.page()


def _charset(headers: Mapping[str, str]) -> str:
    content_type = _header(headers, "content-type")
    match = re.search(r"charset=([^;\s]+)", content_type, flags=re.IGNORECASE)
    return match.group(1) if match else "utf-8"


def _is_pdf_response(
    url: str, headers: Mapping[str, str], body: bytes
) -> bool:
    content_type = _header(headers, "content-type").lower()
    if "application/pdf" in content_type:
        return True
    return _looks_like_pdf_url(url) and _looks_like_pdf_body(body)


def _looks_like_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def _looks_like_pdf_body(body: bytes) -> bool:
    return body.lstrip().startswith(b"%PDF")


def _save_pdf(
    provider: SnuProxyProvider,
    source_url: str,
    pdf_url: str,
    body: bytes,
    download_dir: Path,
) -> PdfDownloadResult:
    if not _looks_like_pdf_body(body):
        return _failure(
            provider=provider,
            source_url=source_url,
            download_dir=download_dir,
            status="download_failed",
            pdf_url=pdf_url,
            reason="download_failed",
            message="The response was labelled as PDF but did not contain PDF bytes.",
        )

    download_dir.mkdir(parents=True, exist_ok=True)
    output_path = _available_path(download_dir / _filename_for_pdf_url(pdf_url))
    output_path.write_bytes(body)
    return PdfDownloadResult(
        ok=True,
        provider=provider.provider_id,
        source_url=source_url,
        status="downloaded",
        pdf_url=pdf_url,
        download_dir=str(download_dir),
        output_path=str(output_path),
        bytes_written=len(body),
    )


def _filename_for_pdf_url(pdf_url: str) -> str:
    parsed = urlparse(pdf_url)
    name = unquote(Path(parsed.path).name) or "article.pdf"
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return _safe_filename(name)


def _safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "article.pdf"


def _available_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find an available filename for {path}")


def _http_failure(
    provider: SnuProxyProvider,
    source_url: str,
    download_dir: Path,
    exc: HTTPError,
) -> PdfDownloadResult:
    if exc.code in {401, 403}:
        return _failure(
            provider=provider,
            source_url=source_url,
            download_dir=download_dir,
            status="login_required",
            reason="login_required",
            message=f"HTTP {exc.code} suggests login or access approval is required.",
        )
    return _failure(
        provider=provider,
        source_url=source_url,
        download_dir=download_dir,
        status="download_failed",
        reason="download_failed",
        message=f"HTTP {exc.code}: {exc.reason}",
    )


def _failure(
    *,
    provider: SnuProxyProvider,
    source_url: str,
    download_dir: Path,
    status: str,
    reason: str,
    message: str,
    pdf_url: str | None = None,
    candidates: list[dict[str, str]] | None = None,
) -> PdfDownloadResult:
    return PdfDownloadResult(
        ok=False,
        provider=provider.provider_id,
        source_url=source_url,
        status=status,
        download_dir=str(download_dir),
        pdf_url=pdf_url,
        reason=reason,
        message=message,
        candidates=candidates or [],
    )


def _discover_failure(
    *,
    provider: SnuProxyProvider,
    source_url: str,
    status: str,
    reason: str,
    message: str,
) -> PdfDiscoverResult:
    return PdfDiscoverResult(
        ok=False,
        provider=provider.provider_id,
        source_url=source_url,
        status=status,
        reason=reason,
        message=message,
    )


def _header(headers: Mapping[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return ""
