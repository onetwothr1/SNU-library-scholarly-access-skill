# SNU Library Scholarly Access — CLI Skill

CLI tool that uses a Seoul National University library account to access paywalled scholarly journals and download PDFs.

- Headless automatic SNU library login (using Playwright)
- Proxy URL generation for affiliated publisher sites
- PDF link discovery on article pages (distinguishes full-text from supplementary files)
- PDF download

## Supported Publishers

Nature, Science, and other publishers affiliated with the SNU library. See [journal_domain.json](src/scholarly_access_agent/data/journal_domains.json) for the full domain list.

---

## Setup

### Requirements

- Python 3.10 or later
- A Seoul National University library account

### 1. Install

Run the following commands in your terminal:

```bash
git clone https://github.com/onetwothr1/SNU-library-scholarly-access-skill.git $HOME/.claude/skills/SNU-library-scholarly-access
cd ~/.claude/skills/SNU-library-scholarly-access

python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows (PowerShell)
# source .venv/bin/activate       # macOS/Linux

pip install -e .
playwright install chromium

scholarly-access-agent setup
```

### 2. Set credentials

Create a `.env` file in the skill directory:

```
SAA_SNU_USERNAME=your_snu_library_id
SAA_SNU_PASSWORD=your_snu_library_password
```

---

## CLI Usage

```bash
# Check if a URL is supported
scholarly-access-agent check-url https://www.nature.com/articles/s41586-026-10669-3

# Generate a proxy URL
scholarly-access-agent proxy-url https://www.nature.com/articles/s41586-026-10669-3

# Discover PDF links on an article page
scholarly-access-agent discover-pdfs https://www.nature.com/articles/s41586-026-10669-3

# Download a PDF (auto-discover)
scholarly-access-agent download-pdf https://www.nature.com/articles/s41586-026-10669-3 --download-dir C:/path/to/download

# Download a PDF with explicit PDF URL (skip discovery)
scholarly-access-agent download-pdf https://www.nature.com/articles/s41586-026-10669-3 --pdf-url "https://www.nature.com/.../article.pdf" --download-dir C:/path/to/download

# Open a proxied URL in a browser (for manual login or inspection)
scholarly-access-agent open-url https://www.nature.com/articles/s41586-026-10669-3

# Add a domain to the proxy list
scholarly-access-agent add-domain publisher.com
```

### Common Options

| Flag | Description |
|------|-------------|
| `--headless false` | Show browser window (for manual login intervention) |
| `--browser-channel chrome` | Use system Chrome instead of bundled Chromium |
| `--profile-dir <path>` | Persistent browser profile (preserves login state) |
| `--timeout-seconds <N>` | Network timeout in seconds (default: 30) |
| `--download-dir <path>` | Where to save downloaded PDFs |

### Output

All commands print JSON to stdout:
```json
{"ok": true, "output_path": "C:/Users/kimde/Desktop/article.pdf"}
```

Parse in scripts with `python -c "import sys,json; ..."` or `jq`.

---

## MCP Server (Optional)

An MCP server mode is available but not required for use with Claude Code. The skill works fully via CLI commands.

To use the MCP server, register it in `~/.claude.json` or `.mcp.json` (see [Claude Code MCP installation docs](https://code.claude.com/docs/en/mcp#mcp-installation-scopes)):

```json
{
  "mcpServers": {
    "snu-library-scholarly-access": {
      "command": "C:/path/to/SNU-library-scholarly-access-skill/.venv/Scripts/scholarly-access-agent.exe",
      "args": ["mcp-server"],
      "env": {
        "SAA_SNU_USERNAME": "your_snu_library_id",
        "SAA_SNU_PASSWORD": "your_snu_library_password"
      }
    }
  }
}
```

MCP tools: `check_url`, `proxy_url`, `discover_pdfs`, `download_pdf`, `add_domain`
(These mirror the CLI commands — same functionality, different interface.)

---


## Contributing

If the agent malfunctions on an affiliated publisher please open an Issue or PR.


## License

MIT License
