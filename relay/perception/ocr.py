"""On-demand OCR fallback (RapidOCR, CPU) — a LAST resort, never the default.

UIA is the source of truth. OCR is used only when the accessibility tree yields
nothing (canvas apps, some Electron/Java UIs). Its results are inferences, not
verified facts: every element it produces is tagged ``provenance="ocr"`` and callers
must never claim OCR "identified" a control with certainty. The engine is loaded
lazily and can be unloaded to free RAM.
"""

import ctypes
import time
from ctypes import wintypes

from relay.diagnostics import get_logger
from relay.perception.semantic import UIElement

log = get_logger("perception.ocr")

_user32 = getattr(ctypes, "windll", None) and getattr(ctypes.windll, "user32", None)
_gdi32 = getattr(ctypes, "windll", None) and getattr(ctypes.windll, "gdi32", None)


def attach_thread_to_active_desktop() -> bool:
    """Attach the calling thread to the interactive 'default' desktop on WinSta0.

    Crucial on Windows when threads/subprocesses are spawned in isolated desktop
    contexts (e.g. exebox-* or services) so that GDI and Win32 capture calls succeed.
    """
    if _user32 is None:
        return False
    try:
        hdesk = _user32.OpenDesktopW("default", 0, False, 0x01FF)
        if hdesk:
            return bool(_user32.SetThreadDesktop(hdesk))
    except Exception:
        pass
    return False


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", _BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


def _capture_window_printwindow(hwnd: int):
    """Capture a specific window using PrintWindow PW_RENDERFULLCONTENT."""
    if _user32 is None or _gdi32 is None or not hwnd:
        return None
    try:
        from PIL import Image

        r = wintypes.RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        w = r.right - r.left
        h = r.bottom - r.top
        if w <= 0 or h <= 0:
            return None

        hdc_screen = _user32.GetDC(0)
        hdc_mem = _gdi32.CreateCompatibleDC(hdc_screen)
        hbm = _gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
        old = _gdi32.SelectObject(hdc_mem, hbm)

        # PW_RENDERFULLCONTENT = 2, fallback to 0
        res = _user32.PrintWindow(hwnd, hdc_mem, 2)
        if not res:
            res = _user32.PrintWindow(hwnd, hdc_mem, 0)

        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # top-down DIB
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB

        buf = ctypes.create_string_buffer(w * h * 4)
        lines = _gdi32.GetDIBits(_hdc_mem := hdc_mem, hbm, 0, h, buf, ctypes.byref(bmi), 0)

        _gdi32.SelectObject(hdc_mem, old)
        _gdi32.DeleteObject(hbm)
        _gdi32.DeleteDC(hdc_mem)
        _user32.ReleaseDC(0, hdc_screen)

        if lines != h:
            return None
        return Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    except Exception as e:
        log.debug("PrintWindow capture failed for hwnd %s: %s", hwnd, e)
        return None


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
        self,
        min_conf: float = 0.5,
        region: tuple[int, int, int, int] | None = None,
        hwnd: int | None = None,
    ) -> list[UIElement]:
        """OCR the primary screen (or a (left, top, right, bottom) region, e.g. the
        foreground window); return text regions as low-trust UIElements. Returns []
        if OCR is unavailable or finds nothing. The capture is never stored."""
        attach_thread_to_active_desktop()

        offset_x = 0
        offset_y = 0
        img = None

        # Strategy 1: Targeted window capture via PrintWindow
        if hwnd:
            pil_img = _capture_window_printwindow(hwnd)
            if pil_img is not None:
                import numpy as np

                img = np.array(pil_img)
                if region is not None:
                    offset_x, offset_y = region[0], region[1]
                else:
                    r = wintypes.RECT()
                    if _user32 and _user32.GetWindowRect(hwnd, ctypes.byref(r)):
                        offset_x, offset_y = r.left, r.top

        # Strategy 2: Fast monitor/region grab via mss
        if img is None:
            try:
                import mss
                import numpy as np
                from PIL import Image

                with mss.MSS() as sct:
                    if region is not None:
                        left, top, right, bottom = region
                        mon = {
                            "left": left,
                            "top": top,
                            "width": max(1, right - left),
                            "height": max(1, bottom - top),
                        }
                        offset_x = left
                        offset_y = top
                    else:
                        mon = sct.monitors[1]
                        offset_x = mon.get("left", 0)
                        offset_y = mon.get("top", 0)
                    raw = sct.grab(mon)
                img = np.array(Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX"))
            except Exception as e:
                log.debug("mss screen capture for OCR failed: %s", e)

        # Strategy 3: PIL ImageGrab fallback
        if img is None:
            try:
                import numpy as np
                from PIL import ImageGrab

                bbox = region if region is not None else None
                if bbox is not None:
                    offset_x, offset_y = bbox[0], bbox[1]
                pil_img = ImageGrab.grab(bbox=bbox)
                if pil_img is not None:
                    img = np.array(pil_img.convert("RGB"))
            except Exception as e:
                log.debug("PIL ImageGrab capture failed: %s", e)

        if img is None:
            log.warning("all screen capture strategies for OCR failed")
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

            # Ground coordinates back to global desktop coordinate space
            xs = [int(p[0]) + offset_x for p in box]
            ys = [int(p[1]) + offset_y for p in box]
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

