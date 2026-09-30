"""Pick the fastest models a router offers — "perfect routing" for voice.

FreeLLMAPI offers hundreds of models; for a spoken answer what matters is the time to
the first word AND that the model follows RELAY's rules. ``tune()``:

1. lists the router's models and keeps plausible fast ones (flash / lite / mini / small
   families; no embedding, vision, reasoning or role-play models);
2. times each one IN PARALLEL with a real RELAY request ("open notepad") and checks the
   reply is exactly RELAY's command format ("DO: open notepad") — a fast model that
   rambles or ignores the rules is dropped;
3. ranks the ones that pass by time to first token and caches the ranking (per router
   URL) in the user data folder, so start-up doesn't re-test every time.

``best_models()`` reads that cache; ``routes_from_config`` races the top three and keeps
the router's own ``auto:fast`` as the last fallback. A model that later rate-limits or
fails is cooled down by the router and the next one answers — nothing is ever pinned.
"""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from relay.diagnostics import get_logger
from relay.llm.client import LLMClient, Route, RouteError

log = get_logger("llm.tune")

_EXCLUDE = re.compile(
    r"embed|whisper|tts|image|vision|vl-|-vl|thinking|reasoning|guard|audio|ocr|robotics|"
    r"coder|code|uncensored|\brp\b|-rp-|lora|heretic|stheno|lunaris|magnum|eclipse|nova|"
    r"distill|\br1\b|-r1|moondream|voxtral|diffusion|phone|sea-lion|allam|apertus|preview",
    re.I,
)
_FAST = [
    re.compile(p, re.I)
    for p in (
        r"flash-lite|-lite\b",
        r"flash|instant|turbo",
        r"haiku|mini|small|nano|air|scout",
        r"(?:^|-)(?:3|4|7|8|9|12|14)b\b|e4b",
    )
]
CACHE_TTL = 3 * 24 * 3600  # re-test every few days (free providers change)
_PROBE = [{"role": "user", "content": "open notepad"}]


def candidates(model_ids: list[str], limit: int = 20) -> list[str]:
    """Plausibly fast chat models, likeliest first."""
    scored = []
    for mid in model_ids:
        if _EXCLUDE.search(mid) or mid.startswith(("auto", "fusion", "free-router", "kilo")):
            continue
        rank = next((k for k, rx in enumerate(_FAST) if rx.search(mid)), None)
        if rank is not None:
            scored.append((rank, len(mid), mid))
    return [m for _r, _n, m in sorted(scored)][:limit]


def list_models(url: str, key: str, timeout: float = 10.0) -> list[str]:
    import urllib.request

    req = urllib.request.Request(
        url.rstrip("/") + "/models", headers={"Authorization": f"Bearer {key}"} if key else {}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    items = data.get("data", data) if isinstance(data, dict) else data
    return [m["id"] if isinstance(m, dict) else str(m) for m in items]


def probe(url: str, key: str, model: str, timeout: float = 8.0) -> dict:
    """One real RELAY request: time to first token, and whether the reply follows the
    command format exactly."""
    from relay.llm.assistant import SYSTEM

    route = Route(name=model, base_url=url, api_key=key, model=model, timeout=timeout)
    client = LLMClient()
    t0 = time.monotonic()
    first, text = None, ""
    try:
        for delta in client.stream_chat(
            route, [{"role": "system", "content": SYSTEM}] + _PROBE, max_tokens=16, temperature=0.0
        ):
            if first is None:
                first = time.monotonic() - t0
            text += delta
            if time.monotonic() - t0 > timeout:
                break
    except RouteError as e:
        return {"model": model, "ok": False, "error": f"HTTP {e.status}"}
    except Exception as e:  # timeouts, broken streams
        return {"model": model, "ok": False, "error": type(e).__name__}
    reply = " ".join(text.split())
    ok = bool(re.match(r"^DO\s*:\s*open notepad\.?$", reply, re.I))
    return {
        "model": model,
        "ok": ok and first is not None,
        "ttft": round(first or 99, 3),
        "total": round(time.monotonic() - t0, 3),
        "reply": reply[:60],
    }


def tune(
    url: str, key: str, limit: int = 20, workers: int = 8, rounds: int = 3, keep: int = 5
) -> list[dict]:
    """1. screen the candidates in parallel (which ones work AND follow the rules);
    2. re-time the passing ones ONE AT A TIME, ``rounds`` times each, and rank by the
    median — parallel requests queue up behind each other and hit rate limits, so their
    timings aren't trustworthy. Returns all results, usable ones first; saves them."""
    import statistics

    ids = list_models(url, key)
    picks = candidates(ids, limit)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        screened = list(pool.map(lambda m: probe(url, key, m), picks))
    passing = sorted((r for r in screened if r["ok"]), key=lambda r: r["ttft"])[:keep]
    for r in passing:
        times = [r["ttft"]]
        for _ in range(rounds - 1):
            again = probe(url, key, r["model"])
            times.append(again["ttft"] if again["ok"] else 99.0)
        r["ttft"] = round(statistics.median(times), 3)
        r["times"] = times
        r["ok"] = r["ttft"] < 99.0
    results = sorted(screened, key=lambda r: (not r["ok"], r.get("ttft", 99)))
    save_cache(url, results)
    return results


# ---- cache (per router URL, in the user data folder) ----
def _cache_path():
    from relay.config import user_data_dir

    return user_data_dir() / "llm_routes.json"


def save_cache(url: str, results: list[dict]) -> None:
    try:
        path = _cache_path()
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        data[url] = {"ts": time.time(), "results": results}
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except (OSError, ValueError) as e:
        log.debug("could not save the model ranking: %s", e)


def load_cache(url: str) -> dict | None:
    try:
        return json.loads(_cache_path().read_text(encoding="utf-8")).get(url)
    except (OSError, ValueError):
        return None


def best_models(url: str, n: int = 3) -> list[tuple[str, float]]:
    """(model, measured first-token seconds) for the fastest usable models, if a fresh
    ranking exists."""
    entry = load_cache(url)
    if not entry or time.time() - entry.get("ts", 0) > CACHE_TTL:
        return []
    return [(r["model"], r["ttft"]) for r in entry["results"] if r.get("ok")][:n]


def needs_tuning(url: str) -> bool:
    entry = load_cache(url)
    return not entry or time.time() - entry.get("ts", 0) > CACHE_TTL


def tune_in_background(url: str, key: str, on_done=None) -> threading.Thread:
    def run():
        try:
            results = tune(url, key)
            log.info(
                "model ranking: %s",
                ", ".join(f"{r['model']} {r['ttft']}s" for r in results if r.get("ok"))[:300],
            )
            if on_done is not None:
                on_done(results)
        except Exception as e:
            log.info("model tuning skipped: %s", e)

    t = threading.Thread(target=run, name="llm-tune", daemon=True)
    t.start()
    return t
