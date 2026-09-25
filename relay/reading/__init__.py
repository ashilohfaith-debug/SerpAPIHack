"""Reading: continuous say-all with a cursor, and the text sources it reads from
(the focused document or web page via UI Automation, files, the clipboard, OCR)."""

from .reader import Reader, split_parts

__all__ = ["Reader", "split_parts"]
