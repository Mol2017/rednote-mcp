# rednote-mcp (Python)

A Python [Model Context Protocol](https://modelcontextprotocol.io/) server for RedNote (小红书 / XiaoHongShu) — search, browse, and **post notes** via browser automation with [Playwright](https://playwright.dev/python/). Works with Claude, Cursor, or any MCP-compatible client.

## Tools

| Tool | Description |
|------|-------------|
| `login` | Authenticate via QR code scan. Use `force=True` to reset the session. |
| `set_browser_mode` | Toggle headless/headed browser. Use headed if tools return empty results. |
| `search_notes` | Search notes by keyword. Returns title, author, tags, URL, likes, comments, `note_id`, and `xsec_token`. |
| `get_note_details` | Fetch full note body and top-level comments using `note_id` + `xsec_token`. Returns `author_id` and `author_xsec_token` for chaining into `get_user_profile`. |
| `get_user_profile` | Fetch a user's public profile — followers, following, likes, and recent posts. Pass `author_xsec_token` from `get_note_details` for an authenticated request. |
| `get_community_trending` | Fetch trending notes from the explore feed. Returns `note_id` and `xsec_token` per item. |
| `post_note` | **Post a picture-and-text note** to the creator platform. Requires 1–18 images, title ≤ 20 chars, content ≤ 1000 chars. |

## Token flow

Tools chain together using `note_id` + `xsec_token` — XiaoHongShu's request signing system. Providing the token builds a properly authenticated URL (`xsec_source=pc_feed` / `pc_note`) that avoids access errors.

```
search_notes / get_community_trending
  → note_id, xsec_token per result
      ↓
get_note_details(note_id, xsec_token)
  → author_id, author_xsec_token
      ↓
get_user_profile(author_id, author_xsec_token)
```

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

The following mitigations are built in:

- **`playwright-stealth`** — patches `navigator.webdriver` and other JS fingerprint leaks
- **Realistic browser fingerprint** — Chrome 145 user-agent, viewport 1440×900, locale `zh-CN`, timezone `Asia/Shanghai`
- **Persistent browser session** — one browser instance reused across all tool calls (opening a fresh browser per call is a bot signal)
- **Human mouse behaviour** — cursor moves to element with random ±5px jitter before each click
- **Human typing** — characters typed one by one with 30–90ms random delays and occasional thinking pauses
- **Random delays** — randomised sleep between every major action
- **Incremental scrolling** — page scrolled by random amounts (300–700px) with pauses between steps

If tools return empty results (bot detection triggered): call `set_browser_mode(headless=False)`, then `login(force=True)`, scan the QR code, and retry.

## Project structure

```
src/rednote_mcp/
├── server.py              # FastMCP server & tool definitions
├── auth/
│   ├── auth_manager.py    # Login flow, persistent session, fingerprint & stealth config
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
