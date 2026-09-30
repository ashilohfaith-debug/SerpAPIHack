"""Perception: Windows UI Automation observation + semantic screen model (L1) +
on-demand OCR fallback. All UIA access is confined to the dedicated UIAWorker."""

from .events import WinEventMonitor
from .semantic import Dialog, ScreenSnapshot, UIElement
from .worker import UIAWorker

__all__ = ["Dialog", "ScreenSnapshot", "UIElement", "UIAWorker", "WinEventMonitor"]
