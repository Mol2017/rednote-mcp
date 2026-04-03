# rednote-mcp (Python)

A Python [Model Context Protocol](https://modelcontextprotocol.io/) server for RedNote (小红书 / XiaoHongShu) — search, browse, and **post notes** via browser automation with [Playwright](https://playwright.dev/python/). Works with Claude, Cursor, or any MCP-compatible client.

## Tools

| Tool | Description |
|------|-------------|
| `login` | Authenticate via QR code scan. Use `force=True` to reset the session. |
| `set_browser_mode` | Toggle headless/headed browser. Use headed if tools return empty results. |
| `search_notes` | Search notes by keyword. Returns title, author, tags, URL, likes, and comments. |
| `get_note_details` | Fetch full note body and top-level comments from a URL or share text. |
| `get_user_profile` | Fetch a user's public profile — followers, following, likes, and recent posts. |
| `get_community_trending` | Fetch trending notes from the explore feed. |
| `post_note` | **Post a picture-and-text note** to the creator platform. Requires 1–18 images, title ≤ 20 chars, content ≤ 1000 chars. |

## Requirements

- Python ≥ 3.10
- `mcp[cli]` ≥ 1.0.0
- `playwright` ≥ 1.42.0
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Installation

### 1. Install the package
```bash
# 1. Clone and enter the directory
git clone https://github.com/Mol2017/rednote-mcp.git
cd rednote-mcp-python

# 2. Create a virtual environment and install dependencies
uv venv && source .venv/bin/activate
uv pip install -e .

# 3. Install Playwright browsers
playwright install chromium
```

### 2. Add to Claude and verify

```bash
# Register the MCP server with Claude
claude mcp add rednote .venv/bin/rednote-mcp

# Verify it is connected
claude mcp list
```

### 3. Debug

```bash
# Activate the virtual environment
source .venv/bin/activate

# Launch the MCP dev inspector
mcp dev src/rednote_mcp/server.py
```

## First-time login

Ask the agent to log in to RedNote. It opens a real Chrome window with a QR code — scan it with the RedNote app. Cookies are persisted to `~/.mcp/rednote/cookies.json` and reused automatically for all future calls.


## Anti-bot detection

Mitigations included: persistent browser session, realistic Chrome 131/macOS fingerprint (viewport 1440×900, locale `zh-CN`, timezone `Asia/Shanghai`), random delays between actions, and incremental scrolling.

If tools return empty results (bot detection triggered): call `set_browser_mode(headless=False)`, then `login(force=True)`, scan the QR code, and retry.

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
