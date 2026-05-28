from __future__ import annotations

import json
import sys
import traceback
from typing import Any

from scholarly_access_agent.providers.snu.proxy import SnuProxyProvider
from scholarly_access_agent.runtime.pdf import discover_pdfs, download_pdf

# Keep the real stdout for JSON-RPC messages
_REAL_STDOUT = sys.stdout


def _handle_check_url(arguments: dict[str, Any]) -> dict[str, Any]:
    url = arguments.get("url")
    if not url:
        raise ValueError("Missing required argument: 'url'")

    provider = SnuProxyProvider()
    supported = provider.supports_url(url)
    payload: dict[str, Any] = {
        "ok": True,
        "provider": provider.provider_id,
        "source_url": url,
        "supported": supported,
    }
    if supported:
        payload["proxy_url"] = provider.proxied_url(url)
    return payload


def _handle_proxy_url(arguments: dict[str, Any]) -> dict[str, Any]:
    url = arguments.get("url")
    if not url:
        raise ValueError("Missing required argument: 'url'")

    provider = SnuProxyProvider()
    return {
        "ok": True,
        "provider": provider.provider_id,
        "source_url": url,
        "proxy_url": provider.proxied_url(url),
    }


def _handle_download_pdf(arguments: dict[str, Any]) -> dict[str, Any]:
    url = arguments.get("url")
    if not url:
        raise ValueError("Missing required argument: 'url'")
    pdf_url = arguments.get("pdf_url")
    download_dir_str = arguments.get("download_dir")
    timeout_seconds = arguments.get("timeout_seconds", 30)
    profile_dir_str = arguments.get("profile_dir")
    browser_channel = arguments.get("browser_channel")
    headless = arguments.get("headless", True)

    from pathlib import Path
    download_dir = Path(download_dir_str) if download_dir_str else None
    profile_dir = Path(profile_dir_str) if profile_dir_str else None

    kwargs: dict[str, Any] = {
        "provider": SnuProxyProvider(),
        "timeout_seconds": int(timeout_seconds),
        "headless": bool(headless),
    }
    if pdf_url:
        kwargs["pdf_url"] = pdf_url
    if download_dir is not None:
        kwargs["download_dir"] = download_dir
    if profile_dir is not None:
        kwargs["profile_dir"] = profile_dir
    if browser_channel:
        kwargs["browser_channel"] = browser_channel

    result = download_pdf(url, **kwargs)
    return result.to_dict()


def _handle_discover_pdfs(arguments: dict[str, Any]) -> dict[str, Any]:
    url = arguments.get("url")
    if not url:
        raise ValueError("Missing required argument: 'url'")
    timeout_seconds = arguments.get("timeout_seconds", 30)
    profile_dir_str = arguments.get("profile_dir")
    browser_channel = arguments.get("browser_channel")
    headless = arguments.get("headless", True)

    from pathlib import Path
    profile_dir = Path(profile_dir_str) if profile_dir_str else None

    kwargs: dict[str, Any] = {
        "provider": SnuProxyProvider(),
        "timeout_seconds": int(timeout_seconds),
        "headless": bool(headless),
    }
    if profile_dir is not None:
        kwargs["profile_dir"] = profile_dir
    if browser_channel:
        kwargs["browser_channel"] = browser_channel

    result = discover_pdfs(url, **kwargs)
    return result.to_dict()


def _handle_add_domain(arguments: dict[str, Any]) -> dict[str, Any]:
    domain = arguments.get("domain")
    if not domain:
        raise ValueError("Missing required argument: 'domain'")

    from scholarly_access_agent.providers.snu.domains import add_domain
    return add_domain(domain)


def _send_response(response: dict[str, Any]) -> None:
    _REAL_STDOUT.write(json.dumps(response) + "\n")
    _REAL_STDOUT.flush()


def _send_error(req_id: Any, code: int, message: str, data: Any = None) -> None:
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": code,
            "message": message,
        }
    }
    if data is not None:
        payload["error"]["data"] = data
    _send_response(payload)


def run_mcp_server() -> int:
    sys.stdout = sys.stderr

    for line in sys.stdin:
        line_str = line.strip()
        if not line_str:
            continue

        try:
            req = json.loads(line_str)
        except json.JSONDecodeError as exc:
            _send_error(None, -32700, f"Parse error: {exc}")
            continue

        if not isinstance(req, dict):
            _send_error(None, -32600, "Invalid Request: expected a JSON object")
            continue

        if "method" not in req:
            _send_error(req.get("id"), -32600, "Invalid Request: missing method")
            continue

        req_id = req.get("id")
        method = req["method"]
        params = req.get("params", {})

        if req_id is None:
            sys.stderr.write(f"Received notification: {method}\n")
            sys.stderr.flush()
            continue

        try:
            if method == "initialize":
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {}
                        },
                        "serverInfo": {
                            "name": "scholarly-access-agent",
                            "version": "0.1.0"
                        }
                    }
                }
                _send_response(res)

            elif method == "ping":
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {}
                }
                _send_response(res)

            elif method == "tools/list":
                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": [
                            {
                                "name": "check_url",
                                "description": (
                                    "Check if a URL host is supported by the SNU proxy. "
                                    "Returns structured JSON containing provider information and compatibility details."
                                ),
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "url": {
                                            "type": "string",
                                            "description": "The publisher or article URL to check."
                                        }
                                    },
                                    "required": ["url"]
                                }
                            },
                            {
                                "name": "proxy_url",
                                "description": (
                                    "Generate a proxied URL for the given scholarly article/publisher URL."
                                ),
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "url": {
                                            "type": "string",
                                            "description": "The scholarly URL to proxy."
                                        }
                                    },
                                    "required": ["url"]
                                }
                            },
                            {
                                "name": "download_pdf",
                                "description": (
                                    "Discover and download an accessible PDF from a given article page or direct PDF URL. "
                                    "Reuses persistent browser profile and handles user-assisted login state."
                                ),
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "url": {
                                            "type": "string",
                                            "description": "The original (non-proxied) article page URL."
                                        },
                                        "pdf_url": {
                                            "type": "string",
                                            "description": "Optional direct PDF URL to download, skipping page discovery."
                                        },
                                        "download_dir": {
                                            "type": "string",
                                            "description": "Optional absolute path to save the PDF. Defaults to a 'downloads/' directory relative to the MCP server's working directory."
                                        },
                                        "profile_dir": {
                                            "type": "string",
                                            "description": "Optional persistent browser profile directory for sharing login state."
                                        },
                                        "browser_channel": {
                                            "type": "string",
                                            "description": "Optional browser channel (e.g. chrome, msedge) to use system browser."
                                        },
                                        "headless": {
                                            "type": "boolean",
                                            "description": "Run browser headless (default: true)."
                                        },
                                        "timeout_seconds": {
                                            "type": "integer",
                                            "description": "Optional network timeout in seconds (default: 30)."
                                        }
                                    },
                                    "required": ["url"]
                                }
                            },
                            {
                                "name": "discover_pdfs",
                                "description": (
                                    "Discover all PDF candidate links on an article page. "
                                    "Returns every matching PDF link with text and context so "
                                    "the caller can pick the correct one (e.g. full-text vs supplementary). "
                                    "Follow up with download_pdf and pdf_url to download the chosen file."
                                ),
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "url": {
                                            "type": "string",
                                            "description": "The original (non-proxied) article page URL."
                                        },
                                        "profile_dir": {
                                            "type": "string",
                                            "description": "Optional persistent browser profile directory for sharing login state."
                                        },
                                        "browser_channel": {
                                            "type": "string",
                                            "description": "Optional browser channel (e.g. chrome, msedge) to use system browser."
                                        },
                                        "headless": {
                                            "type": "boolean",
                                            "description": "Run browser headless (default: true)."
                                        },
                                        "timeout_seconds": {
                                            "type": "integer",
                                            "description": "Optional network timeout in seconds (default: 30)."
                                        }
                                    },
                                    "required": ["url"]
                                }
                            },
                            {
                                "name": "add_domain",
                                "description": (
                                    "Add a new domain to the built-in SNU proxy domain list. "
                                    "Use when a publisher is known to be accessible via SNU proxy "
                                    "but check_url returns supported: false. "
                                    "The domain is normalized and appended to journal_domains.json."
                                ),
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "domain": {
                                            "type": "string",
                                            "description": "Domain to add (e.g. 'publisher.com' or 'https://www.publisher.com/article/123'). URLs are automatically stripped to their host."
                                        }
                                    },
                                    "required": ["domain"]
                                }
                            }
                        ]
                    }
                }
                _send_response(res)

            elif method == "tools/call":
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})

                if tool_name == "check_url":
                    tool_result = _handle_check_url(tool_args)
                elif tool_name == "proxy_url":
                    tool_result = _handle_proxy_url(tool_args)
                elif tool_name == "download_pdf":
                    tool_result = _handle_download_pdf(tool_args)
                elif tool_name == "discover_pdfs":
                    tool_result = _handle_discover_pdfs(tool_args)
                elif tool_name == "add_domain":
                    tool_result = _handle_add_domain(tool_args)
                else:
                    _send_error(req_id, -32601, f"Method not found: tool '{tool_name}'")
                    continue

                res = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(tool_result, indent=2, sort_keys=True)
                            }
                        ],
                        "isError": not tool_result.get("ok", True)
                    }
                }
                _send_response(res)

            else:
                _send_error(req_id, -32601, f"Method not found: '{method}'")

        except Exception as exc:
            tb = traceback.format_exc()
            res = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({
                                "ok": False,
                                "error": type(exc).__name__,
                                "message": str(exc),
                                "traceback": tb
                            }, indent=2)
                        }
                    ],
                    "isError": True
                }
            }
            _send_response(res)

    return 0
