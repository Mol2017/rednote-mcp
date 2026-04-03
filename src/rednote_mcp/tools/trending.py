from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs

from playwright.async_api import BrowserContext, Page

from rednote_mcp.tools.note_detail import _parse_count
from rednote_mcp.utils.logger import get_logger

logger = get_logger(__name__)

XHS_EXPLORE = "https://www.xiaohongshu.com/explore"

_NOTE_ID_RE = re.compile(r"/(?:explore|search_result)/([^/?#]+)")
_XSEC_TOKEN_RE = re.compile(r"[?&]xsec_token=([^&\s]+)")


def _parse_note_id_and_token(url: str) -> tuple[str, str]:
    """Extract (note_id, xsec_token) from a XiaoHongShu URL or href."""
    note_id = ""
    xsec_token = ""
    m = _NOTE_ID_RE.search(url)
    if m:
        note_id = m.group(1)
    m = _XSEC_TOKEN_RE.search(url)
    if m:
        xsec_token = m.group(1)
    return note_id, xsec_token


@dataclass
class TrendingItem:
    title: str = ""
    author: str = ""
    url: str = ""
    cover_img: str = ""
    likes: int = 0
    note_id: str = ""
    xsec_token: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "author": self.author,
            "url": self.url,
            "cover_img": self.cover_img,
            "likes": self.likes,
            "note_id": self.note_id,
            "xsec_token": self.xsec_token,
        }


async def get_community_trending(
    context: BrowserContext,
    limit: int = 18,
) -> list[TrendingItem]:
    page: Page = await context.new_page()
    items: list[TrendingItem] = []
    try:
        await page.goto(XHS_EXPLORE, wait_until="domcontentloaded")
        try:
            await page.wait_for_selector(".feeds-container", timeout=15_000)
        except Exception:
            logger.warning("Trending feed container not found")
            return items

        seen_urls: set[str] = set()
        no_new_rounds = 0

        while len(items) < limit and no_new_rounds < 3:
            note_items = await page.query_selector_all(".feeds-container .note-item")
            new_this_round = 0

            for note_item in note_items:
                if len(items) >= limit:
                    break
                t = TrendingItem()
                try:
                    # URL
                    cover_a = await note_item.query_selector("a.cover.mask.ld, a.cover, a[href*='/explore/']")
                    if cover_a:
                        href = await cover_a.get_attribute("href")
                        if href:
                            t.url = (
                                href if href.startswith("http")
                                else f"https://www.xiaohongshu.com{href}"
                            )

                    if t.url in seen_urls:
                        continue
                    seen_urls.add(t.url)
                    new_this_round += 1

                    # Extract note_id and xsec_token from href
                    t.note_id, t.xsec_token = _parse_note_id_and_token(t.url)

                    # Cover image
                    cover_img = await note_item.query_selector("a.cover img, img[src*='sns-webpic'], .cover img")
                    if cover_img:
                        t.cover_img = await cover_img.get_attribute("src") or ""

                    # Title
                    for sel in (".note-info .title", ".footer .title", "span.title", ".title"):
                        try:
                            el = await note_item.query_selector(sel)
                            if el:
                                t.title = (await el.inner_text()).strip()
                                if t.title:
                                    break
                        except Exception:
                            pass

                    # Author
                    for sel in (".author-wrapper .name", ".author-wrapper span", ".author .name", ".author span"):
                        try:
                            el = await note_item.query_selector(sel)
                            if el:
                                t.author = (await el.inner_text()).strip()
                                if t.author:
                                    break
                        except Exception:
                            pass

                    # Likes
                    for sel in (".note-info .like-wrapper .count", ".like-wrapper .count", ".like-count"):
                        try:
                            el = await note_item.query_selector(sel)
                            if el:
                                likes_txt = (await el.inner_text()).strip()
                                if likes_txt:
                                    t.likes = _parse_count(likes_txt)
                                    break
                        except Exception:
                            pass

                    items.append(t)
                except Exception as e:
                    logger.warning("Error extracting trending item: %s", e)

            logger.info("Round collected %d new items (total %d)", new_this_round, len(items))

            if new_this_round == 0:
                no_new_rounds += 1
            else:
                no_new_rounds = 0

            if len(items) < limit:
                for _ in range(4):
                    await page.evaluate("window.scrollBy(0, Math.floor(Math.random() * 300 + 400))")
                    await asyncio.sleep(random.uniform(0.4, 0.9))
                await asyncio.sleep(random.uniform(2.0, 4.0))

    except Exception as e:
        logger.error("get_community_trending error: %s", e)
    finally:
        await page.close()

    return items
