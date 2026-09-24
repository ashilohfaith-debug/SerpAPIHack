"""Performance measurement helpers.

Real numbers only — RELAY must never claim a memory target it hasn't measured. These
wrap psutil for resident/peak/process-tree memory and provide a timing context, plus
a Windows Job Object hard memory cap so Essential mode can be exercised under a
constrained commit limit (the closest honest proxy for a 4 GB machine on a dev box
with more RAM).
"""

from __future__ import annotations

import os
import time

_MB = 1_000_000


def rss_mb(pid: int | None = None) -> float:
    import psutil
    return psutil.Process(pid or os.getpid()).memory_info().rss / _MB


def peak_working_set_mb() -> float | None:
    """Windows peak working set for this process, if available."""
    import psutil
    mi = psutil.Process().memory_info()
    peak = getattr(mi, "peak_wset", None)
    return peak / _MB if peak else None


def process_tree_rss_mb() -> float:
    """Resident memory of this process plus all children (worker subprocesses etc.)."""
    import psutil
    p = psutil.Process()
    total = p.memory_info().rss
    for c in p.children(recursive=True):
        try:
            total += c.memory_info().rss
        except psutil.Error:
            pass
    return total / _MB


class Measure:
    """Context manager timing a block and recording its RSS delta."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.seconds = 0.0
        self.rss_delta_mb = 0.0
        self.rss_after_mb = 0.0

    def __enter__(self) -> "Measure":
        self._t0 = time.perf_counter()
        self._r0 = rss_mb()
        return self

    def __exit__(self, *exc) -> None:
        self.seconds = time.perf_counter() - self._t0
        self.rss_after_mb = rss_mb()
        self.rss_delta_mb = self.rss_after_mb - self._r0


def set_process_memory_limit_mb(limit_mb: int) -> bool:
    """Apply a HARD commit limit to the current process via a Windows Job Object.
    Allocations beyond the limit fail (Python raises MemoryError). Returns True on
    success. No-op (False) off Windows. Use in a child process — capping the current
    process is irreversible for its lifetime."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    JobObjectExtendedLimitInformation = 9

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong)]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.POINTER(wintypes.ULONG)),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return False
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY
    info.ProcessMemoryLimit = ctypes.c_size_t(limit_mb * _MB)
    ok = k32.SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                     ctypes.byref(info), ctypes.sizeof(info))
    if not ok:
        return False
    return bool(k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()))
