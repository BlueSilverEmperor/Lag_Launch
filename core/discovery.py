"""
core/discovery.py
-----------------
Optimised Video Discovery & Piracy-Hunt Engine.

Changes vs v1:
- asyncio.Semaphore for proper DDG rate-limiting (no hammering).
- Shared httpx.AsyncClient with connection pooling (single persistent session).
- URL deduplication with a set O(1) lookup.
- Normalised item schema so every result has the same keys.
- Lightweight metadata fallback if yt-dlp fails.
"""

from __future__ import annotations

import asyncio
import urllib.parse
import random
from typing import Callable, Optional

import httpx
from bs4 import BeautifulSoup
import yt_dlp

# ── Signals ───────────────────────────────────────────────────────────────────

OFFICIAL_CHANNELS = [
    "real madrid", "man city", "champions league", "premier league",
    "official", "verified", "nba", "nfl", "fifa", "uefa",
]
PIRACY_TERMS = [
    "Full Match", "Live Stream", "Watch Online Free", "Highlights 4K",
    "1080p free", "Download", "Full Game Free", "pirated",
]

# ── Rate-limit ────────────────────────────────────────────────────────────────
# Max concurrent DDG requests — avoids 429 / CAPTCHA blocks.
_DDG_SEM = asyncio.Semaphore(2)
_YT_SEM = asyncio.Semaphore(3)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/114.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/114.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
]

# ── Helpers ────────────────────────────────────────────────────────────────────

def _blank_item(url: str, platform: str) -> dict:
    return {
        "url":              url,
        "platform":         platform,
        "title":            "Unknown",
        "uploader":         "Unknown",
        "subscriber_count": None,
        "is_verified":      False,
        "view_count":       0,
        "upload_date":      "Unknown",
        "thumbnail":        None,
        "risk_level":       "medium",
    }


def _calculate_risk(item: dict) -> str:
    uploader = (item.get("uploader") or "").lower()
    title    = (item.get("title")    or "").lower()
    url      = (item.get("url")      or "").lower()

    for off in OFFICIAL_CHANNELS:
        if off in uploader:
            return "low"

    for term in PIRACY_TERMS:
        if term.lower() in title:
            return "high"

    HIGH_RISK_DOMAINS = ("t.me", "telegram", "vk.com", "rutube", "dailymotion", "tiktok")
    if any(d in url for d in HIGH_RISK_DOMAINS):
        return "high"

    subs = item.get("subscriber_count") or 0
    if not item.get("is_verified") and subs < 10_000:
        return "high"

    return "medium"


def expand_keywords(topic: str) -> list[str]:
    """Expand a single topic into piracy-targeted search queries."""
    base = topic.strip()
    return [base] + [f"{base} {t}" for t in PIRACY_TERMS[:4]]


# ── Metadata extraction ───────────────────────────────────────────────────────

async def extract_metadata(url: str, platform: str) -> dict:
    """Use yt-dlp to fetch uploader reputation. Falls back gracefully."""
    item = _blank_item(url, platform)
    ydl_opts = {
        "quiet": True, "no_warnings": True,
        "extract_flat": True, "format": "best",
    }
    try:
        def _get():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)
        async with _YT_SEM:
            info = await asyncio.wait_for(asyncio.to_thread(_get), timeout=15.0)

        if info:
            item.update({
                "title":            info.get("title", "Unknown"),
                "uploader":         info.get("uploader", "Unknown"),
                "subscriber_count": info.get("channel_follower_count"),
                "is_verified":      info.get("channel_is_verified", False),
                "view_count":       info.get("view_count", 0),
                "upload_date":      info.get("upload_date", "Unknown"),
                "thumbnail":        next(
                    (t["url"] for t in info.get("thumbnails", []) if "url" in t), None
                ),
            })
    except Exception:
        pass
    item["risk_level"] = _calculate_risk(item)
    return item


# ── Platform searchers ────────────────────────────────────────────────────────

async def search_youtube(query: str, limit: int = 5) -> list[dict]:
    """Search YouTube via yt-dlp (no API key needed)."""
    ydl_opts = {
        "quiet": True, "no_warnings": True,
        "extract_flat": True, "default_search": "ytsearch",
    }
    results: list[dict] = []
    try:
        def _search():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        async with _YT_SEM:
            info = await asyncio.wait_for(asyncio.to_thread(_search), timeout=15.0)

        if info and "entries" in info:
            for entry in (info.get("entries") or [])[:limit]:
                if not entry:
                    continue
                item = _blank_item(entry.get("url", ""), "YouTube")
                item.update({
                    "title":    entry.get("title", "Unknown"),
                    "uploader": entry.get("uploader", "Unknown"),
                    "thumbnail": next(
                        (t["url"] for t in entry.get("thumbnails", []) if "url" in t), None
                    ),
                })
                item["risk_level"] = _calculate_risk(item)
                if item["url"]:
                    results.append(item)
    except Exception:
        pass
    return results


async def _ddg_search(
    client: httpx.AsyncClient,
    query: str,
    limit: int,
    platform: str,
    force_high_risk: bool = False,
    exclude_youtube: bool = False,
) -> list[dict]:
    """Shared DDG HTML scraper — uses the shared semaphore for rate limiting."""
    results: list[dict] = []
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    
    for attempt in range(2):  # Simple retry loop
        async with _DDG_SEM:
            try:
                # Rotate user agent per request to avoid blocking
                headers = {"User-Agent": random.choice(USER_AGENTS)}
                resp = await client.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for a in soup.find_all("a", class_="result__url", limit=limit * 2):
                        href = a.get("href", "")
                        if "uddg=" not in href:
                            continue
                        extracted = urllib.parse.unquote(href.split("uddg=")[1].split("&")[0])
                        if exclude_youtube and "youtube.com" in extracted:
                            continue
                        item = _blank_item(extracted, platform)
                        # Grab title from sibling element if possible
                        parent = a.find_parent("div", class_="result")
                        if parent:
                            title_el = parent.find("a", class_="result__a")
                            if title_el:
                                item["title"] = title_el.get_text(strip=True)
                        if force_high_risk:
                            item["risk_level"] = "high"
                        results.append(item)
                        if len(results) >= limit:
                            break
                    return results  # Success, exit retry loop
            except httpx.TimeoutException:
                pass
            except Exception:
                pass
        await asyncio.sleep(1.0) # Backoff before retry
    return results


# ── Main discovery pipeline ──────────────────────────────────────────────────

async def discover_videos(topic: str, emit: Optional[Callable] = None) -> list[dict]:
    """
    Multi-platform piracy discovery pipeline.

    Searches YouTube, DuckDuckGo (web), Twitter/X, Telegram, VK,
    Instagram, and Dailymotion for potential pirated copies.

    Parameters
    ----------
    topic : Search topic / video title.
    emit  : Optional callback(event_dict) for live streaming to the UI.
    """
    all_results:  list[dict] = []
    seen_urls:    set[str]   = set()
    expanded     = expand_keywords(topic)

    def _add(item: dict):
        url = (item.get("url") or "").strip()
        if url and url not in seen_urls:
            seen_urls.add(url)
            all_results.append(item)
            if emit:
                emit({"type": "discovered", "item": item,
                      "message": f"Found: {item['title']} — {item['risk_level'].upper()} Risk"})

    if emit:
        emit({"type": "info",
              "message": f"Searching queries across 14 video platforms & domains for '{topic}'…"})

    limits  = httpx.Limits(max_connections=8, max_keepalive_connections=5)
    timeout = httpx.Timeout(15.0, connect=5.0)

    async with httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=True) as client:
        # Only scan top-2 expanded queries to stay under DDG rate limits
        for query in expanded[:2]:
            if emit:
                emit({"type": "info", "message": f"  ↳ Query: '{query}'"})

            tasks = [
                search_youtube(query, limit=4),
                _ddg_search(client, query,                     limit=3, platform="Web",            exclude_youtube=True),
                _ddg_search(client, f"site:twitter.com {query}", limit=2, platform="X (Twitter)"),
                _ddg_search(client, f"site:t.me {query}",       limit=2, platform="Telegram",      force_high_risk=True),
                _ddg_search(client, f"site:vk.com {query}",     limit=2, platform="VKontakte",     force_high_risk=True),
                _ddg_search(client, f"site:instagram.com {query}", limit=2, platform="Instagram"),
                _ddg_search(client, f"site:dailymotion.com {query}", limit=1, platform="Dailymotion", force_high_risk=True),
                _ddg_search(client, f"site:vimeo.com {query}", limit=2, platform="Vimeo"),
                _ddg_search(client, f"site:rumble.com {query}", limit=2, platform="Rumble", force_high_risk=True),
                _ddg_search(client, f"site:bilibili.com {query}", limit=2, platform="Bilibili", force_high_risk=True),
                _ddg_search(client, f"site:facebook.com/watch {query}", limit=2, platform="Facebook Watch"),
                _ddg_search(client, f"site:tiktok.com {query}", limit=2, platform="TikTok", force_high_risk=True),
                _ddg_search(client, f"site:twitch.tv {query}", limit=2, platform="Twitch"),
                _ddg_search(client, f"site:reddit.com/r/ {query} video", limit=2, platform="Reddit"),
            ]

            task_results = await asyncio.gather(*tasks, return_exceptions=True)
            for batch in task_results:
                if isinstance(batch, list):
                    for item in batch:
                        _add(item)

            await asyncio.sleep(1.2)  # Back-off between query cycles

    if emit:
        emit({"type": "info",
              "message": f"Discovery complete — {len(all_results)} unique candidates found."})

    return all_results
