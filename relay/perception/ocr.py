"""On-demand OCR fallback (RapidOCR, CPU) — a LAST resort, never the default.

UIA is the source of truth. OCR is used only when the accessibility tree yields
nothing (canvas apps, some Electron/Java UIs). Its results are inferences, not
verified facts: every element it produces is tagged ``provenance="ocr"`` and callers
must never claim OCR "identified" a control with certainty. The engine is loaded
lazily and can be unloaded to free RAM.
"""

from __future__ import annotations

import time

from relay.diagnostics import get_logger
from relay.perception.semantic import UIElement

log = get_logger("perception.ocr")


class OCR:
    def __init__(self) -> None:
        self._engine = None

    def _ensure(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            log.info("loading RapidOCR (CPU)")
            self._engine = RapidOCR()
        return self._engine

    def read_screen(
        self, min_conf: float = 0.5, region: tuple[int, int, int, int] | None = None
    ) -> list[UIElement]:
        """OCR the primary screen (or a (left, top, right, bottom) region, e.g. the
        foreground window); return text regions as low-trust UIElements. Returns []
        if OCR is unavailable or finds nothing. The capture is never stored."""
        try:
            import mss
            import numpy as np
            from PIL import Image

            with mss.mss() as sct:
                if region is not None:
                    left, top, right, bottom = region
                    mon = {
                        "left": left,
                        "top": top,
                        "width": max(1, right - left),
                        "height": max(1, bottom - top),
                    }
                else:
                    mon = sct.monitors[1]
                raw = sct.grab(mon)
            img = np.array(Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX"))
        except Exception as e:
            log.warning("screen capture for OCR failed: %s", e)
            return []
        try:
            result, _ = self._ensure()(img)
        except Exception as e:
            log.warning("OCR failed: %s", e)
            return []
        if not result:
            return []
        out: list[UIElement] = []
        uid = 1
        for det in result:
            try:
                box, text, conf = det
            except Exception:
                continue
            if float(conf) < min_conf or not str(text).strip():
                continue
            xs = [int(p[0]) for p in box]
            ys = [int(p[1]) for p in box]
            out.append(
                UIElement(
                    uid=uid,
                    name=str(text).strip(),
                    role="Text",
                    bbox=(min(xs), min(ys), max(xs), max(ys)),
                    actions=("click",),
                    states={"ocr_confidence": round(float(conf), 2)},
                    provenance="ocr",
                    confidence=round(float(conf), 2),
                    timestamp=time.time(),
                    stable_id=f"ocr_{min(xs)}_{min(ys)}",
                )
            )
            uid += 1
        return out

    def unload(self) -> None:
        self._engine = None


def to_text(regions: list[UIElement]) -> str:
    """OCR regions -> reading-order text: rows top-to-bottom, words left-to-right."""
    if not regions:
        return ""
    rows: list[list[UIElement]] = []
    for r in sorted(regions, key=lambda e: (e.bbox[1], e.bbox[0])):
        h = max(1, r.bbox[3] - r.bbox[1])
        if rows and abs(rows[-1][0].bbox[1] - r.bbox[1]) < h * 0.6:
            rows[-1].append(r)
        else:
            rows.append([r])
    return "\n".join(" ".join(e.name for e in sorted(row, key=lambda e: e.bbox[0])) for row in rows)
