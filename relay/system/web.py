"""Web by voice: search, YouTube, and opening sites in the user's default browser.

RELAY builds the URL and hands it to the default browser (the one the user already
knows and has signed in to) — it never scrapes or submits anything. Common Indian
and global sites are known by name; spoken domains ("flipkart dot com") work too.
"""

from __future__ import annotations

import html
import os
import re
import tempfile
import threading
from urllib.parse import parse_qsl, quote_plus, urlparse

SITES = {
    "youtube": "https://www.youtube.com",
    "youtube shorts": "https://www.youtube.com/shorts",
    "shorts": "https://www.youtube.com/shorts",
    "yt": "https://www.youtube.com",
    "yt shorts": "https://www.youtube.com/shorts",
    "gmail": "https://mail.google.com",
    "google": "https://www.google.com",
    "google maps": "https://maps.google.com",
    "maps": "https://maps.google.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "twitter": "https://x.com",
    "linkedin": "https://www.linkedin.com",
    "wikipedia": "https://www.wikipedia.org",
    "amazon": "https://www.amazon.in",
    "flipkart": "https://www.flipkart.com",
    "netflix": "https://www.netflix.com",
    "whatsapp web": "https://web.whatsapp.com",
    "chatgpt": "https://chatgpt.com",
    "google news": "https://news.google.com",
    "news": "https://news.google.com",
    "irctc": "https://www.irctc.co.in",
    "swiggy": "https://www.swiggy.com",
    "zomato": "https://www.zomato.com",
    "spotify web": "https://open.spotify.com",
    "github": "https://github.com",
    "outlook web": "https://outlook.live.com",
    "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com",
    "google docs": "https://docs.google.com",
    "hotstar": "https://www.hotstar.com",
    "jiohotstar": "https://www.hotstar.com",
    "paytm": "https://paytm.com",
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


SEARCH_SITES = {
    "gmail": "https://mail.google.com/mail/u/0/#search/{q}",
    "mail": "https://mail.google.com/mail/u/0/#search/{q}",
    "google": "https://www.google.com/search?q={q}",
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "yt": "https://www.youtube.com/results?search_query={q}",
    "twitter": "https://x.com/search?q={q}",
    "x": "https://x.com/search?q={q}",
    "github": "https://github.com/search?q={q}",
    "reddit": "https://www.reddit.com/search/?q={q}",
    "amazon": "https://www.amazon.in/s?k={q}",
    "flipkart": "https://www.flipkart.com/search?q={q}",
    "linkedin": "https://www.linkedin.com/search/results/all/?keywords={q}",
    "instagram": "https://www.instagram.com/explore/tags/{q}",
    "maps": "https://maps.google.com/maps?q={q}",
    "google maps": "https://maps.google.com/maps?q={q}",
    "wikipedia": "https://en.wikipedia.org/wiki/Special:Search?search={q}",
    "news": "https://news.google.com/search?q={q}",
    "google news": "https://news.google.com/search?q={q}",
    "spotify": "https://open.spotify.com/search/{q}",
    "netflix": "https://www.netflix.com/search?q={q}",
}


def search_site_url(site_name: str, query: str) -> str | None:
    s = site_name.lower().strip()
    if s in SEARCH_SITES:
        return SEARCH_SITES[s].format(q=quote_plus(query.strip()))
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


def open_booking_request(url: str, post_data: str = "") -> None:
    """Open a verified SerpApi booking handoff in the default browser.

    Google Flights sometimes returns an opaque POST relay instead of a deeplink.  A
    short-lived local form preserves that payload exactly enough for browser form
    submission.  This only reaches the provider selection page; Relay never fills or
    submits traveller details, credentials, or payment.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("booking handoff URL is not an HTTP(S) address")
    if not post_data:
        open_url(url)
        return
    fields = "\n".join(
        f'<input type="hidden" name="{html.escape(name, quote=True)}" '
        f'value="{html.escape(value, quote=True)}">'
        for name, value in parse_qsl(post_data, keep_blank_values=True)
    )
    document = (
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
        "<title>Relay booking handoff</title><body>"
        "<p>Opening the verified booking provider. No purchase has been submitted.</p>"
        f'<form id="relay-booking" method="post" action="{html.escape(url, quote=True)}">'
        f"{fields}</form><script>document.getElementById('relay-booking').submit()</script>"
        "</body></html>"
    )
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", prefix="relay-booking-", encoding="utf-8", delete=False
    )
    try:
        handle.write(document)
        path = handle.name
    finally:
        handle.close()
    os.startfile(path)  # type: ignore[attr-defined]
    timer = threading.Timer(120.0, lambda: os.path.exists(path) and os.unlink(path))
    timer.daemon = True
    timer.start()
