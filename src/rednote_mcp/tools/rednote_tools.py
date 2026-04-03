from __future__ import annotations

import os
import asyncio
import re
import random
from dataclasses import dataclass, field
from urllib.parse import quote

from playwright.async_api import Page, BrowserContext

from rednote_mcp.tools.note_detail import (
    NoteWithComments,
    TopLevelComment,
    extract_note_detail,
    extract_top_level_comments,
    _parse_count,
)
from rednote_mcp.utils.logger import get_logger

logger = get_logger(__name__)

XHS_SEARCH_URL = "https://www.xiaohongshu.com/search_result?keyword={keyword}"
XHS_CREATOR_URL = "https://creator.xiaohongshu.com/publish/publish"

FULL_URL_RE = re.compile(
    r"(https?://(?:www\.)?xiaohongshu\.com/[^\s，,。！？]+)", re.IGNORECASE
)
_AUTHOR_ID_RE = re.compile(r"user/profile/([^/?#]+)")


def _extract_url(text: str) -> str | None:
    """
    Extract a XiaoHongShu URL from input.
    - If the input is a bare URL (starts with http/https), return it as-is so
      query params like xsec_token are preserved.
    - Otherwise, scan the share text for an embedded xiaohongshu.com URL.
    """
    text = text.strip()
    if text.startswith("http://") or text.startswith("https://"):
        url = text
    else:
        m = FULL_URL_RE.search(text)
        url = m.group(1) if m else None
    if url:
        url = re.sub(r"xiaohongshu\.com/discovery/item/([^/?#]+)", r"xiaohongshu.com/explore/\1", url)
    return url


async def _random_delay(lo: float = 1.0, hi: float = 3.0) -> None:
    await asyncio.sleep(random.uniform(lo, hi))


async def _scroll_down(page: Page, steps: int = 3) -> None:
    """Scroll down incrementally to mimic human reading."""
    for _ in range(steps):
        await page.evaluate("window.scrollBy(0, Math.floor(Math.random() * 300 + 400))")
        await asyncio.sleep(random.uniform(0.4, 0.9))


# ---------------------------------------------------------------------------
# search_notes
# ---------------------------------------------------------------------------

@dataclass
class NoteSummary:
    title: str = ""
    author: str = ""
    content: str = ""
    tags: list[str] = field(default_factory=list)
    url: str = ""
    likes: int = 0
    collects: int = 0
    comments: int = 0

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "author": self.author,
            "content": self.content,
            "tags": self.tags,
            "url": self.url,
            "likes": self.likes,
            "collects": self.collects,
            "comments": self.comments,
        }


async def search_notes(
    context: BrowserContext, keyword: str, limit: int = 3
) -> list[NoteSummary]:
    page: Page = await context.new_page()
    results: list[NoteSummary] = []

    try:
        url = XHS_SEARCH_URL.format(keyword=quote(keyword))
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_selector(".feeds-container", timeout=15_000)
        await _random_delay()

        # Phase 1: scroll and collect unique URLs — gather extra as buffer for ads
        buffer = limit * 2
        seen_urls: set[str] = set()
        collected_urls: list[str] = []
        no_new_rounds = 0

        while len(collected_urls) < buffer and no_new_rounds < 3:
            items = await page.query_selector_all(".feeds-container .note-item")
            new_this_round = 0
            for item in items:
                if len(collected_urls) >= buffer:
                    break
                try:
                    cover = await item.query_selector("a.cover.mask.ld") or await item.query_selector("a")
                    if cover:
                        href = await cover.get_attribute("href")
                        if href:
                            full_url = href if href.startswith("http") else f"https://www.xiaohongshu.com{href}"
                            if full_url not in seen_urls:
                                seen_urls.add(full_url)
                                collected_urls.append(full_url)
                                new_this_round += 1
                except Exception:
                    pass

            logger.info("URL collection round: %d new, %d total for '%s'", new_this_round, len(collected_urls), keyword)

            if new_this_round == 0:
                no_new_rounds += 1
            else:
                no_new_rounds = 0

            if len(collected_urls) < buffer:
                await _scroll_down(page, steps=4)
                await _random_delay(1.0, 2.0)

        await page.close()
        page = None  # prevent double-close in finally

        # Phase 2: visit each URL directly; skip ads (empty title) and stop when limit reached
        for note_url in collected_urls:
            if len(results) >= limit:
                break
            note_page: Page = await context.new_page()
            note = NoteSummary(url=note_url)
            try:
                await note_page.goto(note_url, wait_until="domcontentloaded")
                await _random_delay()

                try:
                    await note_page.wait_for_selector("#noteContainer", timeout=8_000)
                except Exception:
                    pass

                async def text(sel: str) -> str:
                    try:
                        el = await note_page.query_selector(sel)
                        return (await el.inner_text()).strip() if el else ""
                    except Exception:
                        return ""

                note.title = await text("#detail-title")
                if not note.title:
                    logger.info("Skipping ad/invalid note at %s", note_url)
                    continue
                note.author = await text(".author-wrapper .username")
                note.content = await text("#detail-desc .note-text")
                note.likes = _parse_count(await text(".engage-bar-style .like-wrapper .count"))
                note.collects = _parse_count(await text(".engage-bar-style .collect-wrapper .count"))
                note.comments = _parse_count(await text(".engage-bar-style .chat-wrapper .count"))
                note.tags = re.findall(r"#\S+", note.content)
                results.append(note)
            except Exception as e:
                logger.warning("Error extracting note %s: %s", note_url, e)
            finally:
                await note_page.close()
    except Exception as e:
        logger.error("search_notes error: %s", e)
    finally:
        if page is not None:
            await page.close()

    return results


# ---------------------------------------------------------------------------
# get_note_details  (body + top-level comments, fast path)
# ---------------------------------------------------------------------------

async def get_note_details(
    context: BrowserContext,
    url_or_text: str,
    top_comments_limit: int = 10,
) -> NoteWithComments:
    url = _extract_url(url_or_text) or url_or_text
    page: Page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded")

        base = await extract_note_detail(page, page.url)

        # Try to extract author_id from the author profile link
        author_id = ""
        try:
            for sel in (".author-container a", ".author-wrapper a"):
                el = await page.query_selector(sel)
                if el:
                    href = await el.get_attribute("href")
                    m = _AUTHOR_ID_RE.search(href or "")
                    if m:
                        author_id = m.group(1)
                        break
        except Exception:
            pass

        top_comments = await extract_top_level_comments(page, limit=top_comments_limit)

        return NoteWithComments(
            title=base.title,
            content=base.content,
            tags=base.tags,
            imgs=base.imgs,
            videos=base.videos,
            url=base.url,
            author=base.author,
            author_id=author_id,
            likes=base.likes,
            collects=base.collects,
            comments_count=base.comments,
            top_level_comments=top_comments,
        )
    finally:
        await page.close()


# ---------------------------------------------------------------------------
# submit_post  (publish a new note on creator platform)
# ---------------------------------------------------------------------------

async def post_note(
    context: BrowserContext,
    title: str,
    content: str,
    image_paths: list[str],
    tags: list[str] | None = None,
) -> dict:
    errors = []
    if len(title) > 20:
        errors.append(f"Title exceeds 20 characters (got {len(title)})")
    if len(content) > 1000:
        errors.append(f"Content exceeds 1000 characters (got {len(content)})")
    if len(image_paths) == 0:
        errors.append("At least one image is required")
    elif len(image_paths) > 18:
        errors.append(f"Too many images: maximum is 18 (got {len(image_paths)})")
    if errors:
        return {"success": False, "errors": errors}

    image_paths = [os.path.expanduser(p) for p in image_paths]

    # Step 1: open main site and click 发布 to open creator platform in a new tab
    page: Page = await context.new_page()
    creator_page: Page | None = None
    try:
        await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded")
        await _random_delay(1.5, 2.5)

        new_page_future: asyncio.Future = asyncio.get_event_loop().create_future()
        context.once("page", lambda p: new_page_future.set_result(p) if not new_page_future.done() else None)

        publish_link = await page.query_selector("a[href*='publish'].link-wrapper")
        if not publish_link:
            return {"success": False, "error": "Could not find 发布 button on main site"}
        await publish_link.click()

        try:
            creator_page = await asyncio.wait_for(new_page_future, timeout=10)
        except asyncio.TimeoutError:
            return {"success": False, "error": "Creator platform tab did not open"}

        await creator_page.wait_for_load_state("domcontentloaded")
        await creator_page.set_viewport_size({"width": 1440, "height": 900})
        await _random_delay(2, 3)

        # Step 2: click 上传图文 tab (the image+text tab, not the default video tab)
        # There are multiple elements with this text; use JS to click the first visible one
        try:
            await creator_page.wait_for_selector('.creator-tab', timeout=10_000)
        except Exception:
            return {"success": False, "error": "Creator platform did not load"}
        clicked = await creator_page.evaluate('''() => {
            const tabs = document.querySelectorAll(".creator-tab");
            for (const tab of tabs) {
                if (tab.innerText.includes("上传图文") || tab.innerText.includes("Upload")) {
                    const rect = tab.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        tab.click();
                        return true;
                    }
                }
            }
            return false;
        }''')
        if not clicked:
            return {"success": False, "error": "Could not find 上传图文 tab"}
        await _random_delay(1, 2)

        # Step 3: upload images via file input
        try:
            file_input = await creator_page.wait_for_selector('input[type="file"]', timeout=8_000, state="attached")
        except Exception:
            return {"success": False, "error": "File upload input not found"}
        try:
            await file_input.set_input_files(image_paths)
        except Exception as e:
            return {"success": False, "error": f"Could not attach files — check that all paths exist and are readable. Paths: {image_paths}. Error: {e}"}
        # Wait for upload to complete — title input appears once image is processed
        try:
            await creator_page.wait_for_selector(
                'input[placeholder*="填写标题"], input[placeholder*="title"]',
                timeout=30_000,
            )
        except Exception as e:
            return {"success": False, "error": f"Image upload did not complete within 30s — the format may be unsupported (accepted: jpg, jpeg, png, webp). Paths: {image_paths}. Error: {e}"}
        await _random_delay(2, 3)

        # Step 4: fill title
        try:
            title_input = await creator_page.wait_for_selector(
                'input[placeholder*="填写标题"], input[placeholder*="title"]',
                timeout=8_000,
            )
            await title_input.click()
            await title_input.fill(title)
        except Exception as e:
            return {"success": False, "error": f"Could not fill title field — title provided: {repr(title)}. Error: {e}"}

        await _random_delay()

        # Step 5: fill content + tags (TipTap ProseMirror contenteditable div)
        try:
            content_area = await creator_page.wait_for_selector(
                'div.ProseMirror, div.tiptap',
                timeout=8_000,
            )
            await content_area.click()
            full_content = content
            if tags:
                full_content += "\n" + " ".join(
                    t if t.startswith("#") else f"#{t}" for t in tags
                )
            if not full_content.strip():
                return {"success": False, "error": "Content is empty — provide non-empty content text"}
            await content_area.fill(full_content)
        except Exception as e:
            return {"success": False, "error": f"Could not fill content field — content provided: {repr(content[:80])}. Error: {e}"}

        await _random_delay(1, 2)

        # Step 6: click publish (standalone "发布" button, not "发布笔记")
        # Try up to 3 times; after each click, verify the button is gone
        for _ in range(3):
            # Try CSS selector first, then JS fallback
            btn_clicked = False
            try:
                submit_btn = await creator_page.wait_for_selector(
                    'button.publishBtn, button[class*="publish"]:not([class*="note"])',
                    timeout=5_000,
                )
                await submit_btn.click()
                btn_clicked = True
            except Exception:
                pass
            if not btn_clicked:
                try:
                    btn_clicked = await creator_page.evaluate('''() => {
                        const btns = Array.from(document.querySelectorAll("button"));
                        const btn = btns.find(b => b.innerText.trim() === "发布" || b.innerText.trim() === "Publish");
                        if (btn) { btn.click(); return true; }
                        return false;
                    }''')
                except Exception as e:
                    return {"success": False, "error": f"Publish button click failed: {e}"}

            if not btn_clicked:
                return {"success": False, "error": "Could not find publish button"}

            await _random_delay(2, 3)

            # Check if the publish button is still visible — if gone, we succeeded
            still_visible = await creator_page.evaluate('''() => {
                const btns = Array.from(document.querySelectorAll("button"));
                const btn = btns.find(b => b.innerText.trim() === "发布" || b.innerText.trim() === "Publish");
                if (!btn) return false;
                const rect = btn.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            }''')
            if not still_visible:
                return {"success": True}

        return {"success": False, "error": "Publish button still visible after 3 attempts — post may not have been submitted"}

    except Exception as e:
        logger.error("post_note error: %s", e)
        return {"success": False, "error": str(e)}
    finally:
        await page.close()
        if creator_page:
            await creator_page.close()
