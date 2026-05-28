---
name: SNU Library Scholarly Access
description: Access paywalled scholarly journals and download full-text PDF.
---

# SNU Library Scholarly Access
Skill for accessing paywalled scholarly journals via Seoul National University library proxy. Provides SNU portal auto-login, proxy URL generation, PDF link discovery on article pages (distinguishing full-text from supplementary files), and PDF download.

NEVER read or open the .env file.

## CLI Executable
PLACEHOLDER_PATH_TO_EXECUTABLE

All commands are run via Bash/PowerShell using this executable.

## Commands

| Command | Description |
|---------|-------------|
| `check-url <URL>` | Check if a URL's domain is supported by the SNU proxy |
| `proxy-url <URL>` | Generate a proxied URL for a given scholarly article URL |
| `discover-pdfs <URL>` | Discover all PDF candidate links on an article page |
| `download-pdf <URL>` | Download a PDF from a given article page URL |
| `open-url <URL>` | Open a proxied URL in a browser |
| `add-domain <DOMAIN>` | Add a domain to the built-in SNU proxy domain list |

Use `--help` on any command for full option details. Common flags across commands:
- `--headless false` — show browser window (useful for manual login)
- `--browser-channel chrome` — use system Chrome instead of bundled Chromium
- `--profile-dir <path>` — reuse persistent browser profile (preserves login state)
- `--timeout-seconds <N>` — network timeout (default: 30)

## JSON Output

All commands print JSON to stdout. Example:

```json
{"ok": true, "provider": "snu-proxy", "source_url": "...", "supported": true, "proxy_url": "..."}
```

Parse with Bash: `scholarly-access-agent check-url <URL> | python -c "import sys,json; print(json.load(sys.stdin)['supported'])"`

## Workflow

### 1. Check domain support
```bash
scholarly-access-agent check-url "<ARTICLE_URL>"
```
- Returns `{"supported": true/false, "proxy_url": "..."}`.
- If `supported: false` → stop, inform user publisher is not in SNU proxy list.
- If `supported: true` → the `proxy_url` field is already provided; no separate call needed.

### 2. Discover PDF candidates
```bash
scholarly-access-agent discover-pdfs "<ARTICLE_URL>"
```
- Pass the **original** article URL, not the proxied one.
- Returns `{"candidates": [{href, text, context}, ...]}`.

### 3. Select the full-text PDF
Apply selection rules below to pick the correct candidate from the results.

### 4. Download
```bash
scholarly-access-agent download-pdf "<ARTICLE_URL>" --pdf-url "<SELECTED_HREF>" --download-dir "<SAVE_PATH>"
```
- `--pdf-url`: direct PDF href from step 3 — skips re-discovery.
- `--download-dir`: absolute path for saving. Example: `C:/Users/<Username>/Desktop` on Windows or `/Users/<Username>/Desktop` on macOS/Linux.
- Returns `{"ok": true, "output_path": "<DOWNLOAD_DIR>/article.pdf"}`.
- Report `output_path` to user.

## Full-Text Selection Rules

**Exclude** candidates whose `text` or `context` contains:
- `supplementary materials`, `SM`, `supporting information`, `SI`, `ESI`, `appendix`
- Pattern `S\d+` (e.g. `S1`, `S2`), `Table S`, `Figure S`

**Prefer** candidates whose `text` contains:
- `PDF`, `Full Text`, `Article PDF`, `Download PDF`

If ambiguous, pick the first candidate or ask the user.

## Domain Management

The built-in domain list (`src/scholarly_access_agent/data/journal_domains.json`) covers publishers affiliated with the SNU library. If `check-url` returns `supported: false` for a publisher you believe is affiliated:

1. Verify SNU library access for that publisher (ask user).
2. If confirmed, run: `scholarly-access-agent add-domain "<domain>"`
3. Retry `check-url` after adding.

## Error Handling

- Any response with `"ok": false` → report `message` field to user, do not retry blindly.
- `"status": "login_required"` → Playwright auto-login was attempted but failed. Retry with `--headless false` for user's manual login.
- Unsupported domain: inform user and suggest verifying SNU library access for that publisher.
