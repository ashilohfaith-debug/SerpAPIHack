"""Files and folders by voice: open Downloads, find "my resume", read a PDF aloud.

Known folders are resolved through Windows (SHGetKnownFolderPath), so a Documents or
Desktop folder redirected into OneDrive is still found. File search is bounded
(folders, depth, entries and time) so it can never hang the assistant, and skips
system/hidden/dependency directories. Reading extracts plain text from .txt/.md/.csv,
Word .docx (stdlib zip/XML, no Office needed) and PDF (pypdf). Nothing is modified.
"""

from __future__ import annotations

import ctypes
import os
import re
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from relay.diagnostics import get_logger

log = get_logger("system.files")

_KNOWN = {
    "desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
    "videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
}
FOLDER_WORDS = {
    "desktop": "desktop",
    "documents": "documents",
    "document folder": "documents",
    "my documents": "documents",
    "downloads": "downloads",
    "download folder": "downloads",
    "downloads folder": "downloads",
    "pictures": "pictures",
    "photos folder": "pictures",
    "music folder": "music",
    "my music": "music",
    "videos": "videos",
    "video folder": "videos",
    "home folder": "home",
    "user folder": "home",
}
_SKIP_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    "appdata",
    "$recycle.bin",
    ".venv",
    "venv",
    "site-packages",
    ".cache",
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
}
READABLE = {".txt", ".md", ".csv", ".log", ".json", ".docx", ".pdf", ".rtf", ".html", ".htm"}


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __init__(self, s: str) -> None:
        u = uuid.UUID(s)
        super().__init__()
        self.Data1, self.Data2, self.Data3 = u.fields[0], u.fields[1], u.fields[2]
        for i, b in enumerate(u.bytes[8:]):
            self.Data4[i] = b


def known_folder(name: str) -> Path | None:
    name = name.lower()
    if name == "home":
        return Path.home()
    guid = _KNOWN.get(name)
    if guid is None:
        return None
    try:
        ptr = ctypes.c_wchar_p()
        hr = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(_GUID(guid)), 0, None, ctypes.byref(ptr)
        )
        if hr == 0 and ptr.value:
            p = Path(ptr.value)
            ctypes.windll.ole32.CoTaskMemFree(ptr)
            return p
    except Exception:
        pass
    fallback = Path.home() / name.capitalize()
    return fallback if fallback.exists() else None


def folder_for_phrase(phrase: str) -> tuple[str, Path] | None:
    """'my downloads' / 'the documents folder' -> ('downloads', Path)."""
    p = re.sub(r"\b(?:the|my|folder)\b", " ", phrase.lower())
    p = " ".join(p.split())
    for key in (phrase.lower().strip(), p):
        word = FOLDER_WORDS.get(key) or (key if key in _KNOWN or key == "home" else None)
        if word:
            path = known_folder(word)
            if path is not None:
                return word, path
    return None


@dataclass(frozen=True)
class FileHit:
    path: Path
    score: float

    @property
    def spoken(self) -> str:
        parent = self.path.parent.name or str(self.path.parent)
        return f"{self.path.name}, in {parent}"


def _score(query_tokens: list[str], name: str) -> float:
    stem = name.lower()
    base = re.sub(r"[_\-.]+", " ", stem)
    if not query_tokens:
        return 0.0
    hits = sum(1 for t in query_tokens if t in base)
    if hits == 0:
        return 0.0
    score = hits / len(query_tokens)
    if " ".join(query_tokens) in base:
        score += 0.5
    return score


def search_roots() -> list[Path]:
    roots = []
    for n in ("desktop", "documents", "downloads", "pictures", "music", "videos"):
        p = known_folder(n)
        if p is not None and p.exists() and p not in roots:
            roots.append(p)
    return roots


def find_files(
    query: str,
    roots: list[Path] | None = None,
    limit: int = 5,
    max_depth: int = 5,
    max_entries: int = 40000,
    time_budget: float = 4.0,
) -> list[FileHit]:
    """Bounded name search across the user's folders. Newest first among equals."""
    q = re.sub(r"\b(?:the|my|a|file|document|called|named|folder)\b", " ", query.lower())
    q = q.replace(" dot ", ".")
    tokens = [t for t in re.split(r"[\s_\-]+", q) if t]
    if not tokens:
        return []
    roots = roots if roots is not None else search_roots()
    start = time.monotonic()
    seen = 0
    hits: list[FileHit] = []
    for root in roots:
        stack = [(root, 0)]
        while stack:
            d, depth = stack.pop()
            if time.monotonic() - start > time_budget or seen > max_entries:
                break
            try:
                with os.scandir(d) as it:
                    for entry in it:
                        seen += 1
                        name = entry.name
                        if name.startswith((".", "~$")):
                            continue
                        try:
                            is_dir = entry.is_dir(follow_symlinks=False)
                        except OSError:
                            continue
                        s = _score(tokens, name)
                        if s >= 1.0:  # every spoken word is in the name
                            hits.append(FileHit(Path(entry.path), s))
                        if is_dir and depth < max_depth and name.lower() not in _SKIP_DIRS:
                            stack.append((Path(entry.path), depth + 1))
            except (PermissionError, FileNotFoundError, NotADirectoryError, OSError):
                continue

    def sort_key(h: FileHit):
        try:
            mtime = h.path.stat().st_mtime
        except OSError:
            mtime = 0
        return (-h.score, -mtime)

    hits.sort(key=sort_key)
    return hits[:limit]


def read_file_text(path: Path, max_chars: int = 60000) -> str | None:
    """Plain text of a readable document, or None if it has no extractable text."""
    ext = path.suffix.lower()
    try:
        if ext in (".txt", ".md", ".csv", ".log", ".json"):
            return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
        if ext in (".html", ".htm"):
            raw = path.read_text(encoding="utf-8", errors="replace")
            raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
            return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)).strip()[:max_chars]
        if ext == ".docx":
            return _docx_text(path)[:max_chars]
        if ext == ".rtf":
            raw = path.read_text(encoding="utf-8", errors="replace")
            return re.sub(r"\\[a-z]+-?\d* ?|[{}]", "", raw)[:max_chars]
        if ext == ".pdf":
            return _pdf_text(path, max_chars)
    except Exception as e:
        log.warning("could not read %s: %s", path.name, e)
        return None
    return None


def _docx_text(path: Path) -> str:
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    paras = []
    for p in root.iter(f"{ns}p"):
        text = "".join(t.text or "" for t in p.iter(f"{ns}t"))
        if text.strip():
            paras.append(text)
    return "\n\n".join(paras)


def _pdf_text(path: Path, max_chars: int) -> str | None:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            return None
    parts, total = [], 0
    for page in reader.pages:
        t = (page.extract_text() or "").strip()
        if t:
            parts.append(t)
            total += len(t)
        if total >= max_chars:
            break
    text = "\n\n".join(parts)
    return text[:max_chars] if text.strip() else None


def open_path(path: Path) -> None:
    os.startfile(str(path))  # type: ignore[attr-defined]
