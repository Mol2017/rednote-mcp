import asyncio
import random
import re
from dataclasses import dataclass, field

from playwright.async_api import Page

from rednote_mcp.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_count(text: str) -> int:
    """Convert display counts like '1.2万' to integers."""
    if not text:
        return 0
    text = text.strip()
    try:
        if "万" in text:
            return int(float(text.replace("万", "")) * 10_000)
        return int(text)
    except ValueError:
        return 0


async def _random_delay(lo: float = 0.5, hi: float = 1.5) -> None:
    await asyncio.sleep(random.uniform(lo, hi))


async def _el_text(el, selector: str) -> str:
    """Query selector within an element handle and return inner text."""
    try:
        child = await el.query_selector(selector)
        return (await child.inner_text()).strip() if child else ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class NoteDetail:
    title: str = ""
    content: str = ""
    tags: list[str] = field(default_factory=list)
    imgs: list[str] = field(default_factory=list)
    videos: list[str] = field(default_factory=list)
    url: str = ""
    author: str = ""
    likes: int = 0
    collects: int = 0
    comments: int = 0

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "content": self.content,
            "tags": self.tags,
            "imgs": self.imgs,
            "videos": self.videos,
            "url": self.url,
            "author": self.author,
            "likes": self.likes,
            "collects": self.collects,
            "comments": self.comments,
        }


@dataclass
class TopLevelComment:
    author: str = ""
    content: str = ""
    likes: int = 0

    def to_dict(self) -> dict:
        return {
            "author": self.author,
            "content": self.content,
            "likes": self.likes,
        }


@dataclass
class NoteWithComments:
    """Combined result for get_note_details (fast path)."""
    title: str = ""
    content: str = ""
    tags: list[str] = field(default_factory=list)
    imgs: list[str] = field(default_factory=list)
    videos: list[str] = field(default_factory=list)
    url: str = ""
    author: str = ""
    author_id: str = ""
    likes: int = 0
    collects: int = 0
    comments_count: int = 0
    top_level_comments: list[TopLevelComment] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "content": self.content,
            "tags": self.tags,
            "imgs": self.imgs,
            "videos": self.videos,
            "url": self.url,
            "author": self.author,
            "author_id": self.author_id,
            "likes": self.likes,
            "collects": self.collects,
            "comments_count": self.comments_count,
            "top_level_comments": [c.to_dict() for c in self.top_level_comments],
        }


# ---------------------------------------------------------------------------
# Note body extraction (unchanged from original)
# ---------------------------------------------------------------------------

async def extract_note_detail(page: Page, url: str) -> NoteDetail:
    detail = NoteDetail(url=url)

    try:
        await page.wait_for_selector(".note-container", timeout=10_000)
    except Exception:
        logger.warning("Timed out waiting for note container at %s", url)

    # Media container differs between image notes and video notes
    for media_sel in (".media-container", ".video-container", "xg-player", ".note-video", "video"):
        try:
            await page.wait_for_selector(media_sel, timeout=3_000)
            break
        except Exception:
            pass

    async def text(selector: str, fallback: str = "") -> str:
        try:
            el = await page.query_selector(selector)
            return (await el.inner_text()).strip() if el else fallback
        except Exception:
            return fallback

    detail.title = await text("#detail-title") or await text(".title")

    content_parts = []
    for el in await page.query_selector_all(
        ".note-scroller .note-content .note-text span"
    ):
        try:
            content_parts.append((await el.inner_text()).strip())
        except Exception:
            pass
    detail.content = "\n".join(p for p in content_parts if p)

    for a in await page.query_selector_all(
        ".note-scroller .note-content .note-text a"
    ):
        try:
            tag = (await a.inner_text()).strip()
            if tag.startswith("#"):
                detail.tags.append(tag)
        except Exception:
            pass

    detail.author = await text(".author-container .info .username")

    detail.likes = _parse_count(await text(".interact-container .like-wrapper .count"))
    detail.collects = _parse_count(await text(".interact-container .collect-wrapper .count"))
    detail.comments = _parse_count(await text(".interact-container .chat-wrapper .count"))

    # Images — include both media-container and note-slider (image carousels)
    for img in await page.query_selector_all(
        ".media-container img, .note-slider img, .swiper-slide img"
    ):
        try:
            src = await img.get_attribute("src")
            if src and not src.startswith("data:"):
                detail.imgs.append(src)
        except Exception:
            pass

    # Videos — XiaoHongShu uses a JS player that sets blob: URLs at runtime.
    # The real stream URL lives in window.__INITIAL_STATE__ and og:video meta.
    # Priority order:
    #   1. window.__INITIAL_STATE__ h264 masterUrl (most reliable, highest quality)
    #   2. <meta name="og:video"> content attribute
    #   3. <video> element src/data-src/<source> (fallback, usually blob:)
    # Poster thumbnail is always captured as a fallback image.
    seen_video_urls: set[str] = set()

    # Extract from window.__INITIAL_STATE__ JS object
    try:
        js_video_url = await page.evaluate("""
            () => {
                try {
                    const state = window.__INITIAL_STATE__;
                    if (!state) return null;
                    const map = state.noteDetailMap || state.note?.noteDetailMap;
                    if (!map) return null;
                    for (const key of Object.keys(map)) {
                        const note = map[key];
                        const streams = note?.note?.video?.media?.stream;
                        if (streams) {
                            const h264 = streams.h264 || streams.H264;
                            if (h264 && h264.length > 0 && h264[0].masterUrl) {
                                return h264[0].masterUrl;
                            }
                            // try h265 as fallback
                            const h265 = streams.h265 || streams.H265;
                            if (h265 && h265.length > 0 && h265[0].masterUrl) {
                                return h265[0].masterUrl;
                            }
                        }
                    }
                } catch(e) {}
                return null;
            }
        """)
        if js_video_url and js_video_url not in seen_video_urls:
            detail.videos.append(js_video_url)
            seen_video_urls.add(js_video_url)
    except Exception:
        pass

    return detail


# ---------------------------------------------------------------------------
# Comment extraction — fast path (no reply expansion)
# ---------------------------------------------------------------------------

_COMMENT_CONTAINER = ".comments-container, .comment-list, [class*='comment-list']"
_COMMENT_ITEM = ".comment-item, [class*='comment-item']"


async def extract_top_level_comments(page: Page, limit: int = 20) -> list[TopLevelComment]:
    """
    Fast path: extract top-level comments without clicking reply-expand buttons.
    `reply_count` is populated from the button label; `replies` arrays are empty.
    """
    comments: list[TopLevelComment] = []
    try:
        await page.wait_for_selector(_COMMENT_CONTAINER, timeout=8_000)
    except Exception:
        logger.warning("Comment container not found")
        return comments

    items = await page.query_selector_all(_COMMENT_ITEM)
    for item in items[:limit]:
        c = TopLevelComment()
        try:
            c.author = (
                await _el_text(item, ".author-name")
                or await _el_text(item, ".user-info .name")
                or await _el_text(item, ".name")
            )
            c.content = (
                await _el_text(item, ".content span")
                or await _el_text(item, ".comment-content")
                or await _el_text(item, "p")
            )
            c.likes = _parse_count(
                await _el_text(item, ".like-wrapper .count")
                or await _el_text(item, ".like-count")
            )
            comments.append(c)
        except Exception as e:
            logger.warning("Error extracting comment: %s", e)

    return comments


