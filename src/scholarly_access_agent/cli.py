from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from scholarly_access_agent.providers.snu.proxy import SnuProxyProvider
from scholarly_access_agent.runtime.browser import (
    DEFAULT_PROFILE_DIR,
    DEFAULT_TIMEOUT_MS,
    BrowserRuntimeUnavailable,
    open_proxied_url,
)
from scholarly_access_agent.runtime.pdf import (
    DEFAULT_DOWNLOAD_DIR,
    DEFAULT_TIMEOUT_SECONDS,
    discover_pdfs,
    download_pdf,
)

def str2bool(v: str | bool) -> bool:
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    if v.lower() in ("no", "false", "f", "n", "0"):
        return False
    raise argparse.ArgumentTypeError("Boolean value expected.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scholarly-access-agent",
        description="Local CLI for scholarly access provider workflows.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    proxy_url = subcommands.add_parser("proxy-url", help="Build a provider proxy URL.")
    proxy_url.add_argument("url", help="Article or publisher URL to proxy.")

    check_url = subcommands.add_parser("check-url", help="Check provider domain support.")
    check_url.add_argument("url", help="Article or publisher URL to check.")
    open_url = subcommands.add_parser(
        "open-url",
        help="Open a provider-proxied URL in a persistent browser profile.",
    )
    open_url.add_argument("url", help="Article or publisher URL to open.")
    open_url.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help="Persistent browser profile directory.",
    )
    open_url.add_argument(
        "--browser-channel",
        help="Optional installed browser channel, such as chrome or msedge.",
    )
    open_url.add_argument(
        "--headless",
        type=str2bool,
        nargs="?",
        const=True,
        default=False,
        help="Run the browser headlessly. User-assisted login usually needs a window.",
    )
    open_url.add_argument(
        "--timeout-ms",
        type=int,
        default=DEFAULT_TIMEOUT_MS,
        help="Navigation timeout in milliseconds.",
    )
    open_url.add_argument(
        "--wait-for-login",
        action="store_true",
        help="Keep the browser open and wait for the user to finish SNU login.",
    )

    download_pdf_command = subcommands.add_parser(
        "download-pdf",
        help="Discover and download an accessible PDF from a URL.",
    )
    download_pdf_command.add_argument("url", help="Article page or direct PDF URL.")
    download_pdf_command.add_argument(
        "--pdf-url",
        help="Optional direct PDF URL to download, skipping page discovery.",
    )
    download_pdf_command.add_argument(
        "--download-dir",
        type=Path,
        default=DEFAULT_DOWNLOAD_DIR,
        help="Directory for downloaded PDFs.",
    )
    download_pdf_command.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Network timeout in seconds.",
    )
    download_pdf_command.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help="Persistent browser profile directory for sharing login state.",
    )
    download_pdf_command.add_argument(
        "--browser-channel",
        help="Optional browser channel (e.g. chrome, msedge) to use system browser.",
    )
    download_pdf_command.add_argument(
        "--headless",
        type=str2bool,
        nargs="?",
        const=True,
        default=True,
        help="Run browser headlessly (default: true).",
    )

    discover_pdfs_command = subcommands.add_parser(
        "discover-pdfs",
        help="Discover all PDF candidate links on an article page.",
    )
    discover_pdfs_command.add_argument("url", help="Article page URL to scan for PDF links.")
    discover_pdfs_command.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Network timeout in seconds.",
    )
    discover_pdfs_command.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help="Persistent browser profile directory for sharing login state.",
    )
    discover_pdfs_command.add_argument(
        "--browser-channel",
        help="Optional browser channel (e.g. chrome, msedge) to use system browser.",
    )
    discover_pdfs_command.add_argument(
        "--headless",
        type=str2bool,
        nargs="?",
        const=True,
        default=True,
        help="Run browser headlessly (default: true).",
    )

    subcommands.add_parser(
        "mcp-server",
        help="Start the MCP tool process over standard I/O.",
    )
    subcommands.add_parser(
        "setup",
        help="Set up and personalize path settings in skill.md for this system.",
    )
    add_domain = subcommands.add_parser(
        "add-domain",
        help="Add a domain to the built-in SNU proxy domain list.",
    )
    add_domain.add_argument("domain", help="Domain to add (e.g. publisher.com).")

    return parser


def provider_from_args(args: argparse.Namespace) -> SnuProxyProvider:
    return SnuProxyProvider()


def write_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def run(args: argparse.Namespace) -> int:
    provider = provider_from_args(args)

    if args.command == "proxy-url":
        write_json(
            {
                "ok": True,
                "provider": provider.provider_id,
                "source_url": args.url,
                "proxy_url": provider.proxied_url(args.url),
            }
        )
        return 0

    if args.command == "check-url":
        supported = provider.supports_url(args.url)
        payload: dict[str, object] = {
            "ok": True,
            "provider": provider.provider_id,
            "source_url": args.url,
            "supported": supported,
        }
        if supported:
            payload["proxy_url"] = provider.proxied_url(args.url)
        write_json(payload)
        return 0

    if args.command == "open-url":
        try:
            result = open_proxied_url(
                args.url,
                provider=provider,
                profile_dir=args.profile_dir,
                browser_channel=args.browser_channel,
                headless=args.headless,
                timeout_ms=args.timeout_ms,
                wait_for_login=args.wait_for_login,
            )
        except BrowserRuntimeUnavailable as exc:
            write_json(
                {
                    "ok": False,
                    "provider": provider.provider_id,
                    "source_url": args.url,
                    "profile_dir": str(args.profile_dir.resolve()),
                    "status": "unavailable",
                    "reason": "missing_playwright",
                    "message": str(exc),
                }
            )
            return 2

        write_json(result.to_dict())
        return 0 if result.ok else 1

    if args.command == "download-pdf":
        pdf_url = getattr(args, "pdf_url", None) or None
        result = download_pdf(
            args.url,
            provider=provider,
            pdf_url=pdf_url,
            download_dir=args.download_dir,
            profile_dir=args.profile_dir,
            browser_channel=args.browser_channel,
            timeout_seconds=args.timeout_seconds,
            headless=args.headless,
        )
        write_json(result.to_dict())
        return 0 if result.ok else 1

    if args.command == "discover-pdfs":
        from scholarly_access_agent.runtime.pdf import discover_pdfs
        result = discover_pdfs(
            args.url,
            provider=provider,
            profile_dir=args.profile_dir,
            browser_channel=args.browser_channel,
            timeout_seconds=args.timeout_seconds,
            headless=args.headless,
        )
        write_json(result.to_dict())
        return 0 if result.ok else 1

    if args.command == "mcp-server":
        from scholarly_access_agent.mcp.server import run_mcp_server
        return run_mcp_server()

    if args.command == "setup":
        executable_name = "scholarly-access-agent.exe" if sys.platform == "win32" else "scholarly-access-agent"
        exec_path = Path(sys.executable).parent / executable_name
        
        # Resolve skill.md path relative to package source
        root_dir = Path(__file__).resolve().parents[2]
        skill_path = root_dir / "skill.md"
        
        if not skill_path.exists():
            write_json({
                "ok": False,
                "message": f"Could not find skill.md at {skill_path}. Make sure you run this from the cloned repository."
            })
            return 1
            
        content = skill_path.read_text(encoding="utf-8")
        
        # Replace the line below "## CLI Executable" with the actual path
        lines = content.splitlines()
        updated_lines = []
        skip_next = False
        replaced = False
        
        for line in lines:
            if skip_next:
                skip_next = False
                continue
            updated_lines.append(line)
            if line.strip() == "## CLI Executable":
                formatted_path = str(exec_path.resolve()).replace("\\", "/")
                updated_lines.append(f"`{formatted_path}`")
                skip_next = True
                replaced = True
                
        if not replaced:
            write_json({
                "ok": False,
                "message": "Could not find '## CLI Executable' section in skill.md"
            })
            return 1
            
        skill_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
        
        write_json({
            "ok": True,
            "message": "Successfully personalized skill.md",
            "cli_path": str(exec_path.resolve()).replace("\\", "/")
        })
        return 0

    if args.command == "add-domain":
        from scholarly_access_agent.providers.snu.domains import add_domain
        result = add_domain(args.domain)
        write_json(result)
        return 0

    raise ValueError(f"Unsupported command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except Exception as exc:
        write_json({"ok": False, "error": type(exc).__name__, "message": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
