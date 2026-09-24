"""P11: performance-measurement helpers. (The full benchmark with real models is
scripts/bench_perf.py; these test the measurement plumbing.)"""

import time

from relay.diagnostics.perf import (
    Measure,
    process_tree_rss_mb,
    rss_mb,
    set_process_memory_limit_mb,
)


def test_rss_is_positive():
    assert rss_mb() > 0


def test_process_tree_rss_covers_self():
    # tree includes this process, so it's at least our own RSS (minus sampling jitter)
    assert process_tree_rss_mb() >= rss_mb() - 5


def test_measure_times_and_records_rss():
    with Measure("sleep") as m:
        time.sleep(0.05)
        _ = [0] * 10000
    assert m.seconds >= 0.04
    assert isinstance(m.rss_after_mb, float) and m.rss_after_mb > 0


def test_memory_limit_api_returns_bool_without_capping():
    # Apply an effectively-infinite cap so the test process is never constrained;
    # this just proves the Windows Job Object call path works and returns a bool.
    result = set_process_memory_limit_mb(10_000_000)  # ~10 TB, never hit
    assert isinstance(result, bool)
