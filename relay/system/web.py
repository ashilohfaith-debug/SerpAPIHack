"""Web by voice: search, YouTube, and opening sites in the user's default browser.

RELAY builds the URL and hands it to the default browser (the one the user already
knows and has signed in to) — it never scrapes or submits anything. Common Indian
and global sites are known by name; spoken domains ("flipkart dot com") work too.
"""

from __future__ import annotations

import os
import re
from urllib.parse import quote_plus

SITES = {
    "youtube": "https://www.youtube.com", "gmail": "https://mail.google.com",
    "google": "https://www.google.com", "google maps": "https://maps.google.com",
    "maps": "https://maps.google.com", "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com", "twitter": "https://x.com",
    "linkedin": "https://www.linkedin.com", "wikipedia": "https://www.wikipedia.org",
    "amazon": "https://www.amazon.in", "flipkart": "https://www.flipkart.com",
    "netflix": "https://www.netflix.com", "whatsapp web": "https://web.whatsapp.com",
    "chatgpt": "https://chatgpt.com", "google news": "https://news.google.com",
    "news": "https://news.google.com", "irctc": "https://www.irctc.co.in",
    "swiggy": "https://www.swiggy.com", "zomato": "https://www.zomato.com",
    "spotify web": "https://open.spotify.com", "github": "https://github.com",
    "outlook web": "https://outlook.live.com",
    "google drive": "https://drive.google.com", "drive": "https://drive.google.com",
    "google docs": "https://docs.google.com", "hotstar": "https://www.hotstar.com",
    "jiohotstar": "https://www.hotstar.com", "paytm": "https://paytm.com",
}
_DOMAIN = re.compile(r"^(?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:/\S*)?$")


def spoken_domain(text: str) -> str:
    """'flipkart dot com' -> 'flipkart.com'."""
    t = re.sub(r"\s+dot\s+", ".", text.lower().strip())
    return t.replace(" ", "") if _DOMAIN.match(t.replace(" ", "")) else t


def site_url(name: str) -> str | None:
    """URL for a known site name or a spoken/typed domain; None otherwise."""
    n = re.sub(r"\b(?:the|website|site|web site|page|dot com page)\b", " ", name.lower())
    n = " ".join(n.split())
    if n in SITES:
        return SITES[n]
    d = spoken_domain(n)
    if _DOMAIN.match(d):
        return d if d.startswith("http") else f"https://{d}"
    return None


def search_url(query: str) -> str:
    return "https://www.google.com/search?q=" + quote_plus(query.strip())


def youtube_url(query: str) -> str:
    return "https://www.youtube.com/results?search_query=" + quote_plus(query.strip())


def site_label(url: str) -> str:
    """A short spoken name for a URL ('www.youtube.com/...' -> 'youtube')."""
    host = re.sub(r"^https?://(?:www\.)?", "", url).split("/")[0]
    return host.split(".")[0] if host.count(".") >= 1 else host


def open_url(url: str) -> None:
    os.startfile(url)  # type: ignore[attr-defined]  # default browser
