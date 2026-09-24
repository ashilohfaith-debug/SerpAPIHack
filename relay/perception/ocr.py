"""On-demand OCR fallback (RapidOCR, CPU) — a LAST resort, never the default.

UIA is the source of truth. OCR is used only when the accessibility tree yields
nothing (canvas apps, some Electron/Java UIs). Its results are inferences, not
verified facts: every element it produces is tagged ``provenance="ocr"`` and callers
must never claim OCR "identified" a control with certainty. The engine is loaded
lazily and can be unloaded to free RAM.
"""

from __future__ import annotations

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

    def read_screen(self, min_conf: float = 0.5) -> list[UIElement]:
        """OCR the primary screen; return text regions as low-trust UIElements.
        Returns [] if OCR is unavailable or finds nothing."""
        try:
            import mss
            import numpy as np
            from PIL import Image
            with mss.mss() as sct:
                raw = sct.grab(sct.monitors[1])
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
            out.append(UIElement(
                uid=uid, name=str(text).strip(), role="Text",
                bbox=(min(xs), min(ys), max(xs), max(ys)),
                actions=(), states={"ocr_confidence": round(float(conf), 2)},
                provenance="ocr",
            ))
            uid += 1
        return out

    def unload(self) -> None:
        self._engine = None
