# rednote-mcp (Python)

A Python [Model Context Protocol](https://modelcontextprotocol.io/) server for RedNote (小红书 / XiaoHongShu).  
It uses [Playwright](https://playwright.dev/python/) for browser automation and exposes tools to AI assistants such as Claude, Cursor, or any MCP-compatible client.

## Tools

| Tool | Description |
|------|-------------|
| `login` | Open a visible browser and authenticate via QR code scan. Cookies are persisted and reused automatically. Use `force=True` to clear the existing session and start fresh. |
| `set_browser_mode` | Toggle headless (invisible) or headed (visible) browser. Switch to headed when bot detection is triggered — a key symptom is tools returning empty results. |
| `search_notes` | Search notes by keyword. Returns title, author, content, tags, URL, likes, collects, and comments. |
| `get_note_details` | Fetch the full body of a note plus its top-level comments from a URL or share text. |
| `get_user_profile` | Fetch a user's public profile — followers, following, total likes, and recent posts. |
| `get_community_trending` | Fetch trending notes from the XiaoHongShu explore feed. |
| `post_note` | Publish a picture-and-text note via the creator platform. Requires at least one local image file and text content. |

## Requirements

- Python ≥ 3.10
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Installation

```bash
# 1. Clone and enter the directory
git clone <repo-url> rednote-mcp-python
cd rednote-mcp-python

# 2. Create a virtual environment and install dependencies
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"          # or: pip install -e .

# 3. Install Playwright browsers
playwright install chromium
```

## First-time login

Before using any other tool you must authenticate once so that cookies are saved:

```bash
rednote-mcp          # starts the MCP server
# then call the login tool from your AI client
```

The `login` tool opens a real Chrome window. Scan the QR code with the XiaoHongShu app. Cookies are persisted to `~/.mcp/rednote/cookies.json` and reused for all future calls.

## MCP client configuration

### Claude Desktop / Cursor

Add to your `mcp_settings.json` (or equivalent):

```json
{
  "mcpServers": {
    "rednote": {
      "command": "rednote-mcp",
      "args": []
    }
  }
}
```

Or if using `uv run`:

```json
{
  "mcpServers": {
    "rednote": {
      "command": "uv",
      "args": ["--directory", "/path/to/rednote-mcp-python", "run", "rednote-mcp"]
    }
  }
}
```

## Bot detection

XiaoHongShu actively detects automated browsers. This server includes several mitigations:

| Mitigation | Detail |
|------------|--------|
| **Persistent browser session** | The browser stays open between tool calls instead of launching fresh every time — opening a new browser per request is a strong bot signal. |
| **Realistic browser fingerprint** | User agent is set to a real Chrome 131 on macOS string. Viewport (1440×900), locale (`zh-CN`), and timezone (`Asia/Shanghai`) match a typical Chinese user. |
| **Human-like delays** | Random pauses of 1–3 seconds between actions; longer pauses (2–4 seconds) during feed scrolling. |
| **Incremental scrolling** | Feed pages are scrolled in small random steps (400–700 px) with pauses between each, rather than jumping straight to the bottom. |
| **Headed mode fallback** | If tools return empty results (the main symptom of bot detection), call `set_browser_mode(headless=False)` — the visible browser lets you see and dismiss any CAPTCHA challenge before retrying. |

### Recovery flow when bot detection triggers

1. Call `set_browser_mode(headless=False)` — switches to visible browser and resets the session.
2. Call `login(force=True)` — clears the old session and opens a fresh QR code.
3. Scan the QR code.
4. Retry the original tool — results should return normally.
5. Optionally call `set_browser_mode(headless=True)` to go back to background mode.

## Project structure

```
src/rednote_mcp/
├── server.py              # FastMCP server & tool definitions
├── auth/
│   ├── auth_manager.py    # Login flow, persistent session, fingerprint options
│   └── cookie_manager.py  # Cookie persistence (~/.mcp/rednote/cookies.json)
├── tools/
│   ├── rednote_tools.py   # search_notes, get_note_details, post_note
│   ├── note_detail.py     # Low-level page scraping helpers
│   ├── trending.py        # get_community_trending
│   └── user_profile.py    # get_user_profile
└── utils/
    └── logger.py          # Rotating file logger
```

## License

MIT
