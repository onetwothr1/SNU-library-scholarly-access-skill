from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SNU_USERNAME_ENV = "SAA_SNU_USERNAME"
SNU_PASSWORD_ENV = "SAA_SNU_PASSWORD"
_ENV_FILE_LOADED = False


def _try_load_env_file() -> None:
    global _ENV_FILE_LOADED
    if _ENV_FILE_LOADED:
        return
    _ENV_FILE_LOADED = True
    
    project_root = Path(__file__).resolve().parents[4]
    env_path = project_root / ".env"

    if not env_path.is_file():
        print(f"Error: .env file not found at {env_path}")
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip()

_USERNAME_SELECTORS = (
    "input[name='uid']",
    "input[id='login-id']",
    "input[name='userId']",
    "input[name='username']",
    "input[name='userid']",
    "input[name='id']",
    "input[name='logonId']",
    "input[name='logonid']",
    "input[id='userId']",
    "input[id='username']",
    "input[id='userid']",
    "input[id='id']",
    "input[id='loginId']",
)
_PASSWORD_SELECTORS = (
    "input[type='password']",
)
_SUBMIT_SELECTORS = (
    "button[type='submit']:has-text('로그인')",
    "button[type='submit']:has-text('Login')",
    "button[type='submit']:has-text('Sign In')",
    "input[type='submit'][value*='로그인']",
    "input[type='submit'][value*='Login']",
    "button[type='submit']",
    "input[type='submit']",
    "button.btn-login",
    "button.login-btn",
    "button[id*='login']",
    "input[id*='login']",
    "button[id*='btnLogin']",
    "a[id*='login']",
)


@dataclass(frozen=True)
class PageSnapshot:
    url: str
    title: str = ""
    body_text: str = ""
    has_password_field: bool = False


@dataclass(frozen=True)
class LoginDetection:
    required: bool
    reason: str | None = None
    message: str | None = None


SNU_LOGIN_URL_MARKERS = ("login", "signin", "signon", "sso", "auth")
SNU_TEXT_MARKERS = (
    "snu",
    "seoul national university",
    "\uc11c\uc6b8\ub300\ud559\uad50",
)
LOGIN_TEXT_MARKERS = ("login", "log in", "sign in", "\ub85c\uadf8\uc778")
PASSWORD_TEXT_MARKERS = ("password", "passwd", "\ube44\ubc00\ubc88\ud638")


def detect_login_required(snapshot: PageSnapshot) -> LoginDetection:
    url = snapshot.url.lower()
    text = f"{snapshot.title}\n{snapshot.body_text}".lower()
    combined = f"{url}\n{text}"

    if "snu.ac.kr" in url and _contains_any(url, SNU_LOGIN_URL_MARKERS):
        return _login_required()

    if snapshot.has_password_field and _contains_any(combined, SNU_TEXT_MARKERS):
        return _login_required()

    if (
        _contains_any(text, SNU_TEXT_MARKERS)
        and _contains_any(text, LOGIN_TEXT_MARKERS)
        and (snapshot.has_password_field or _contains_any(text, PASSWORD_TEXT_MARKERS))
    ):
        return _login_required()

    return LoginDetection(required=False)


def _login_required() -> LoginDetection:
    return LoginDetection(
        required=True,
        reason="login_required",
        message=(
            "SNU proxy appears to require user login. Complete login in the "
            "persistent browser profile, then retry."
        ),
    )


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def attempt_auto_login(page: Any) -> bool:
    _try_load_env_file()
    username = os.environ.get(SNU_USERNAME_ENV, "").strip()
    password = os.environ.get(SNU_PASSWORD_ENV, "").strip()
    if not username or not password:
        return False

    try:
        username_field = _find_first_visible(page, _USERNAME_SELECTORS)
        if username_field is None:
            return False
        username_field.fill(username)

        password_field = _find_first_visible(page, _PASSWORD_SELECTORS)
        if password_field is None:
            return False
        password_field.fill(password)

        submit_button = _find_first_visible(page, _SUBMIT_SELECTORS)
        if submit_button is None:
            return False

        submit_button.click()

        try:
            page.wait_for_url(
                lambda url: not _contains_any(url.lower(), SNU_LOGIN_URL_MARKERS),
                timeout=15_000,
            )
        except Exception:
            page.wait_for_timeout(5_000)

        try:
            page.wait_for_load_state("load", timeout=10_000)
        except Exception:
            pass
        page.wait_for_timeout(5_000)

        current_url = str(getattr(page, "url", "")).lower()
        if _contains_any(current_url, SNU_LOGIN_URL_MARKERS):
            return False

        return True
    except Exception:
        return False


def _find_first_visible(page: Any, selectors: tuple[str, ...]) -> Any | None:
    for selector in selectors:
        try:
            locator = page.locator(selector)
            if locator.count() > 0 and locator.first.is_visible():
                return locator.first
        except Exception:
            continue
    return None
