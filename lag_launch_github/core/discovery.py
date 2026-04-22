import asyncio
import re
import urllib.parse
from datetime import datetime
from email.utils import parsedate_to_datetime

import httpx
from bs4 import BeautifulSoup
import yt_dlp

OFFICIAL_CHANNELS = ["real madrid", "man city", "champions league", "premier league", "official", "verified"]
PIRACY_TERMS = ["Full Match", "Live Stream", "Watch Online Free", "Highlights 4K", "1080p free", "Download"]

def expand_keywords(topic: str) -> list[str]:
    """Expands a single topic into multiple high-risk search queries."""
    base = topic.strip()
    return [base] + [f"{base} {term}" for term in PIRACY_TERMS]

async def extract_metadata(url: str, platform: str) -> dict:
    """Uses httpx + BeautifulSoup to extract OpenGraph metadata without downloading the video."""
    data = {
        "url": url,
        "platform": platform,
        "uploader": "Unknown",
        "upload_date": "Unknown",
        "thumbnail": None,
        "title": "Unknown",
        "risk_level": "medium",
    }
    
    try:
        # Simulate browser headers
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                
                # Title
                og_title = soup.find("meta", property="og:title")
                if og_title and og_title.get("content"):
                    data["title"] = og_title["content"]
                elif soup.title:
                    data["title"] = soup.title.string
                    
                # Thumbnail
                og_image = soup.find("meta", property="og:image")
                if og_image and og_image.get("content"):
                    data["thumbnail"] = og_image["content"]

                # Youtube/Platform specific sniffing
                if "youtube.com" in url or "youtu.be" in url:
                    author_link = soup.find("link", itemprop="name")
                    if author_link:
                        data["uploader"] = author_link.get("content", "Unknown")
                    
                    date_meta = soup.find("meta", itemprop="uploadDate")
                    if date_meta:
                        data["upload_date"] = date_meta.get("content", "Unknown")
                else:
                    # Generic OG site name
                    og_site = soup.find("meta", property="og:site_name")
                    if og_site:
                        data["uploader"] = og_site.get("content", "Unknown")
                    
                    # Generic Article/Video publish time
                    og_time = soup.find("meta", property="article:published_time") or soup.find("meta", property="video:release_date")
                    if og_time:
                        try:
                            dt = datetime.fromisoformat(og_time.get("content", "").replace("Z", "+00:00"))
                            data["upload_date"] = dt.strftime("%Y-%m-%d")
                        except Exception:
                            pass

    except Exception:
        pass # Silently fallback to basic extraction
        
    data["risk_level"] = _calculate_risk(data)
    return data

def _calculate_risk(metadata: dict) -> str:
    uploader_lower = metadata["uploader"].lower()
    title_lower = metadata["title"].lower()
    url_lower = metadata["url"].lower()
    
    # Check official channels
    for official in OFFICIAL_CHANNELS:
        if official in uploader_lower or "verified" in title_lower:
            return "low"
            
    # Check piracy signals
    for term in PIRACY_TERMS:
        if term.lower() in title_lower:
            return "high"
            
    if "tiktok" in url_lower or "dailymotion" in url_lower or "vk.com" in url_lower or "t.me" in url_lower or "telegram" in url_lower or "rutube" in url_lower:
        return "high"
        
    return "medium"

async def search_youtube(query: str, limit: int = 5) -> list[dict]:
    """Uses yt-dlp strictly for searching to bypass YouTube blocks."""
    ydl_opts = {
        'format': 'best',
        'quiet': True,
        'extract_flat': True,
        'default_search': 'ytsearch',
    }
    results = []
    try:
        # Run yt-dlp blocking call in an executor
        def _search():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
                
        info = await asyncio.to_thread(_search)
        if info and "entries" in info:
            for entry in info["entries"][:limit]:
                risk = "medium"
                uploader = entry.get("uploader", "Unknown")
                for off in OFFICIAL_CHANNELS:
                    if off in uploader.lower():
                        risk = "low"
                        break
                if risk == "medium":
                    for term in PIRACY_TERMS:
                        if term.lower() in entry.get("title", "").lower():
                            risk = "high"
                            break

                results.append({
                    "platform": "YouTube",
                    "url": entry.get("url"),
                    "uploader": uploader,
                    "upload_date": "Unknown",
                    "thumbnail": next((t["url"] for t in entry.get("thumbnails", []) if "url" in t), None),
                    "title": entry.get("title", "Unknown"),
                    "risk_level": risk
                })
    except Exception as e:
        pass
    return results

async def search_web(query: str, limit: int = 5) -> list[dict]:
    """Uses DuckDuckGo HTML version to extract alternative links (simulating Google/X)"""
    results = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}", headers=headers)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.find_all("a", class_="result__url", limit=limit):
                    url = a.get("href")
                    if url and url.startswith("//duckduckgo.com/l/?uddg="):
                        extracted_url = urllib.parse.unquote(url.split("uddg=")[1].split("&")[0])
                        # Filter out basic noise
                        if "youtube.com" not in extracted_url: # handled by ytsearch
                            platform = "X (Twitter)" if "twitter.com" in extracted_url or "x.com" in extracted_url else "Web"
                            meta = await extract_metadata(extracted_url, platform)
                            results.append(meta)
    except Exception as e:
        pass
    return results

async def search_dork(query: str, site: str, platform: str, limit: int = 3, force_high_risk: bool = True) -> list[dict]:
    """Targeted dorking for specific sites using DuckDuckGo."""
    results = []
    dork_query = f"site:{site} {query}"
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(dork_query)}", headers=headers)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.find_all("a", class_="result__url", limit=limit):
                    url = a.get("href")
                    if url and url.startswith("//duckduckgo.com/l/?uddg="):
                        extracted_url = urllib.parse.unquote(url.split("uddg=")[1].split("&")[0])
                        meta = await extract_metadata(extracted_url, platform)
                        if force_high_risk:
                            meta["risk_level"] = "high"
                        results.append(meta)
    except Exception as e:
        pass
    return results

async def discover_videos(topic: str, emit=None) -> list[dict]:
    """Main pipeline for automated discovery across all platforms"""
    all_results = []
    
    # 1. Expand
    expanded = expand_keywords(topic)
    
    if emit: emit({"type": "info", "message": f"Expanded '{topic}' to {len(expanded)} queries"})
        
    for idx, query in enumerate(expanded[:2]): # Search top 2 queries to avoid rate limits with all these dorks
        if emit: emit({"type": "info", "message": f"Crawling YouTube, Web, Telegram, VK, Instagram & X for: '{query}'..."})
        
        # Parallelizing safely
        tasks = [
            search_youtube(query, limit=3),
            search_web(query, limit=3),
            search_dork(query, "twitter.com", "X (Twitter)", limit=2, force_high_risk=False),
            search_dork(query, "instagram.com", "Instagram", limit=2, force_high_risk=False),
            search_dork(query, "t.me", "Telegram", limit=2, force_high_risk=True),
            search_dork(query, "vk.com", "VKontakte", limit=2, force_high_risk=True),
            search_dork(query, "dailymotion.com", "Dailymotion", limit=1, force_high_risk=True),
        ]
        
        task_results = await asyncio.gather(*tasks)
        combined = [item for sublist in task_results for item in sublist]
        
        for item in combined:
            if not any(r["url"] == item["url"] for r in all_results):
                all_results.append(item)
                if emit: emit({
                    "type": "discovered",
                    "item": item,
                    "message": f"Found URL: {item['url']} ({item['risk_level'].upper()} Risk)"
                })
                
        await asyncio.sleep(1) # Backoff for DDG proxy limits
                
    if emit: emit({"type": "info", "message": f"Discovery complete. Found {len(all_results)} total candidates."})
    return all_results
