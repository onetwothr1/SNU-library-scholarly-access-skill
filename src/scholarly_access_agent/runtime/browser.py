from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO

from scholarly_access_agent.providers.snu.login import (
    PageSnapshot,
    detect_login_required,
)
from scholarly_access_agent.providers.snu.proxy import SnuProxyProvider


DEFAULT_PROFILE_DIR = Path(".profiles") / "snu"
DEFAULT_TIMEOUT_MS = 15_000


class BrowserRuntimeUnavailable(RuntimeError):
    """Raised when optional browser dependencies are not installed."""


@dataclass(frozen=True)
class BrowserOpenResult:
    ok: bool
    provider: str
    source_url: str
    profile_dir: str
    status: str
    proxy_url: str | None = None
    current_url: str | None = None
    title: str | None = None
    reason: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "ok": self.ok,
            "provider": self.provider,
            "source_url": self.source_url,
            "profile_dir": self.profile_dir,
            "status": self.status,
        }
        optional = {
            "proxy_url": self.proxy_url,
            "current_url": self.current_url,
            "title": self.title,
            "reason": self.reason,
            "message": self.message,
        }
        payload.update({key: value for key, value in optional.items() if value})
        return payload


def open_proxied_url(
    source_url: str,
    *,
    provider: SnuProxyProvider | None = None,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    browser_channel: str | None = None,
    headless: bool = False,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    wait_for_login: bool = False,
    input_func: Callable[[str], str] = input,
    stderr: TextIO | None = None,
    playwright_factory: Callable[[], Any] | None = None,
) -> BrowserOpenResult:
    provider = provider or SnuProxyProvider()
    resolved_profile_dir = profile_dir.resolve()

    if not provider.supports_url(source_url):
        return BrowserOpenResult(
            ok=False,
            provider=provider.provider_id,
            source_url=source_url,
            profile_dir=str(resolved_profile_dir),
            status="unsupported",
            reason="unsupported_domain",
            message="The URL host is not in the configured provider domain list.",
        )

    proxy_url = provider.proxied_url(source_url)
    factory = playwright_factory or _load_sync_playwright()
    resolved_profile_dir.mkdir(parents=True, exist_ok=True)

    with factory() as playwright:
        launch_options: dict[str, object] = {
            "user_data_dir": str(resolved_profile_dir),
            "headless": headless,
        }
        if browser_channel:
            launch_options["channel"] = browser_channel

        context = playwright.chromium.launch_persistent_context(
            **launch_options,
        )
        try:
            page = _first_page(context)
            page.set_default_timeout(timeout_ms)
            page.goto(proxy_url, wait_until="domcontentloaded", timeout=timeout_ms)
            snapshot = capture_page_snapshot(page)
            login = detect_login_required(snapshot)

            if login.required:
                from scholarly_access_agent.providers.snu.login import attempt_auto_login
                auto_login_ok = attempt_auto_login(page)
                if auto_login_ok:
                    snapshot = capture_page_snapshot(page)
                    login = detect_login_required(snapshot)
                elif wait_for_login:
                    _write_login_prompt(login.message or "", stderr or sys.stderr)
                    input_func("")
                    _reload_after_user_login(page, timeout_ms)
                    snapshot = capture_page_snapshot(page)
                    login = detect_login_required(snapshot)

            if login.required:
                return BrowserOpenResult(
                    ok=False,
                    provider=provider.provider_id,
                    source_url=source_url,
                    proxy_url=proxy_url,
                    profile_dir=str(resolved_profile_dir),
                    current_url=snapshot.url,
                    title=snapshot.title,
                    status="login_required",
                    reason=login.reason,
                    message=login.message,
                )

            return BrowserOpenResult(
                ok=True,
                provider=provider.provider_id,
                source_url=source_url,
                proxy_url=proxy_url,
                profile_dir=str(resolved_profile_dir),
                current_url=snapshot.url,
                title=snapshot.title,
                status="opened",
            )
        finally:
            context.close()


def capture_page_snapshot(page: Any) -> PageSnapshot:
    return PageSnapshot(
        url=str(getattr(page, "url", "")),
        title=_safe_page_title(page),
        body_text=_safe_body_text(page),
        has_password_field=_has_password_field(page),
    )


def _load_sync_playwright() -> Callable[[], Any]:
    try:
        module = importlib.import_module("playwright.sync_api")
    except ModuleNotFoundError as exc:
        raise BrowserRuntimeUnavailable(
            "Playwright is not installed. Install the optional browser runtime "
            "with `python -m pip install -e .[browser]`, then run "
            "`python -m playwright install chromium`."
        ) from exc
    return module.sync_playwright


def _first_page(context: Any) -> Any:
    pages = getattr(context, "pages", None)
    if pages:
        return pages[0]
    return context.new_page()


def _safe_page_title(page: Any) -> str:
    try:
        return str(page.title())
    except Exception:
        return ""


def _safe_body_text(page: Any) -> str:
    try:
        return str(page.text_content("body", timeout=1_000) or "")
    except Exception:
        return ""


def _has_password_field(page: Any) -> bool:
    try:
        return page.locator("input[type='password']").count() > 0
    except Exception:
        return False


def _reload_after_user_login(page: Any, timeout_ms: int) -> None:
    try:
        page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception:
        page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)


def _write_login_prompt(message: str, stderr: TextIO) -> None:
    print(message, file=stderr)
    print("Press Enter here after completing login in the browser.", file=stderr)
