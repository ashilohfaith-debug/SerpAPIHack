"""Knowledge and instant research engine — Wikipedia & instant search synthesis.

Provides instant factual answers, research summaries, and entity lookups without
requiring paid API keys or cloud tokens. Essential for a standalone voice computer
answering general questions aloud for a blind user.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Optional

from relay.diagnostics import get_logger

log = get_logger("system.knowledge")

import unicodedata

_STOPWORDS = {
    "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "of", "with",
    "is", "was", "are", "were", "what", "who", "where", "when", "why", "how",
    "tell", "me", "about", "please", "can", "you", "does", "do", "did", "define",
    "explain", "search", "google", "look", "up", "find", "out"
}


def _clean_for_speech(text: str) -> str:
    """Normalize accents and foreign glyphs so TTS engines speak naturally."""
    text = (
        text.replace("\u0142", "l")
        .replace("\u0141", "L")
        .replace("\u00f8", "o")
        .replace("\u00d8", "O")
        .replace("\u00df", "ss")
        .replace("\u00e6", "ae")
        .replace("\u00c6", "AE")
    )
    norm = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in norm if not unicodedata.combining(c))
    return stripped.encode("ascii", "ignore").decode("ascii")


def _clean_query(raw_query: str) -> str:
    """Strip question phrasing and fillers to get clean search keywords."""
    q = raw_query.strip().rstrip("?.! ")
    # Strip common leading question patterns
    q = re.sub(
        r"^(?:ask|question|ask relay|tell me about|tell me|who is|who was|who were|who are|"
        r"what is|what was|what are|what were|what does|what mean|what's|"
        r"where is|where are|why is|why does|why do|why did|"
        r"how does|how do|how is|how can i|how to|"
        r"explain|define|research|look up|search for|google)\s+",
        "",
        q,
        flags=re.I,
    ).strip("?.! ")
    # If stripping left nothing or almost nothing, fall back to original
    return q if len(q) >= 2 else raw_query.strip().rstrip("?.! ")


def _format_spoken_sentences(text: str, max_sentences: int = 2) -> str:
    """Clean Wikipedia / web text for natural speech synthesis."""
    if not text:
        return ""
    # Normalize unicode to avoid Windows console / TTS charset errors
    text = _clean_for_speech(text)
    # Strip citations like [1], [2], [citation needed]
    clean = re.sub(r"\[(?:\d+|citation needed)\]", "", text)
    # Strip parenthetical pronunciation / coordinates / IPA (e.g. (/ˈpærɪs/ PA-riss) or (listen))
    clean = re.sub(r"\([^\)]*?(?:IPA|listen|pronounced|\/)[^\)]*?\)", "", clean)
    # Strip non-standard dashes / special unicode spacing
    clean = re.sub(r"[\u200b\u200e\u200f]", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip()

    sentences = re.split(r"(?<=[.!?])\s+", clean)
    selected = []
    for s in sentences:
        s_clean = s.strip()
        if len(s_clean) > 10 and not s_clean.startswith("Coordinates:"):
            selected.append(s_clean)
        if len(selected) >= max_sentences:
            break
    result = " ".join(selected) if selected else clean
    return result[:400].rstrip(". ") + "."


class KnowledgeEngine:
    """Instant factual search and summarization engine."""

    def __init__(self, user_agent: str = "RelayVoiceComputer/1.0 (Windows; Accessibility)") -> None:
        self.user_agent = user_agent

    def answer(self, query: str) -> Optional[str]:
        """Fetch a concise, spoken factual answer for a question or topic."""
        clean = _clean_query(query)
        if not clean:
            return None

        # 1. Try Wikipedia Search & Summary
        wiki_ans = self._query_wikipedia(clean)
        if wiki_ans:
            return wiki_ans

        # 2. Try DuckDuckGo Instant Answer
        ddg_ans = self._query_duckduckgo(clean)
        if ddg_ans:
            return ddg_ans

        return None

    def _query_wikipedia(self, topic: str) -> Optional[str]:
        """Search Wikipedia API and retrieve lead summary."""
        try:
            # First search for the best matching article title
            search_url = (
                "https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch="
                + urllib.parse.quote(topic)
                + "&utf8=&format=json"
            )
            req = urllib.request.Request(
                search_url,
                headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                results = data.get("query", {}).get("search", [])
                if not results:
                    return None
                best_title = results[0].get("title", "")
                snippet = results[0].get("snippet", "")

            if not best_title:
                return None

            # Retrieve clean lead extract from REST summary endpoint
            summary_url = (
                "https://en.wikipedia.org/api/rest_v1/page/summary/"
                + urllib.parse.quote(best_title.replace(" ", "_"))
            )
            sum_req = urllib.request.Request(
                summary_url,
                headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            )
            with urllib.request.urlopen(sum_req, timeout=3.5) as resp:
                s_data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                extract = s_data.get("extract", "")
                if extract:
                    return _format_spoken_sentences(extract, max_sentences=2)

            # Fallback to stripped search snippet if summary was empty
            if snippet:
                clean_snippet = re.sub(r"<[^>]+>", "", snippet).strip()
                if len(clean_snippet) > 20:
                    return f"{best_title}: {clean_snippet}."
        except Exception as e:
            log.debug("Wikipedia query failed for '%s': %s", topic, e)
        return None

    def _query_duckduckgo(self, topic: str) -> Optional[str]:
        """Retrieve instant answers / abstracts from DuckDuckGo."""
        try:
            url = (
                f"https://api.duckduckgo.com/?q={urllib.parse.quote(topic)}"
                "&format=json&no_html=1&skip_disambig=1"
            )
            req = urllib.request.Request(
                url,
                headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                ans = data.get("Answer") or data.get("AbstractText")
                if ans:
                    return _format_spoken_sentences(ans, max_sentences=2)
        except Exception as e:
            log.debug("DuckDuckGo query failed for '%s': %s", topic, e)
        return None

    def summarize_text(self, text: str, max_sentences: int = 3) -> str:
        """Lightweight extractive summarization of raw screen or page text."""
        if not text or not text.strip():
            return "There is no text to summarize."

        lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 20]
        if not lines:
            sentences = re.split(r"(?<=[.!?])\s+", text)
            lines = [s.strip() for s in sentences if len(s.strip()) > 15]

        if not lines:
            return text[:250].strip()

        # Score sentences by word frequency
        words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
        content_words = [w for w in words if w not in _STOPWORDS]
        freq: dict[str, int] = {}
        for w in content_words:
            freq[w] = freq.get(w, 0) + 1

        def score_line(line: str) -> float:
            line_words = re.findall(r"\b[a-zA-Z]{3,}\b", line.lower())
            if not line_words:
                return 0.0
            score = sum(freq.get(w, 0) for w in line_words)
            return score / (len(line_words) ** 0.5)

        scored = sorted(lines, key=score_line, reverse=True)
        top = scored[:max_sentences]
        # Preserve original relative order
        ordered_top = [ln for ln in lines if ln in top][:max_sentences]
        return " ".join(ordered_top)
