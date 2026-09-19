"""Testes para probe_health — stdlib mock."""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from benchmark_providers.probe_health import (
    aggregate,
    append_jsonl,
    detect_alert,
    probe_once,
    read_jsonl,
)


def _sample(provider="x", ok=True, lat=100, status=200, shed=False, ts="2026-09-18T12:00:00Z"):
    return {
        "ts": ts,
        "provider": provider,
        "model_probe": "m",
        "ok": ok,
        "latency_ms": lat,
        "http_status": status,
        "shed_detected": shed,
        "error": None if ok else "err",
    }


def test_aggregate_empty():
    assert aggregate([]) == {}


def test_aggregate_computes_percentiles():
    rows = [_sample(lat=v) for v in (100, 200, 300, 400, 500)]
    agg = aggregate(rows)
    a = agg["x"]
    assert a["samples"] == 5
    assert a["uptime_pct"] == 100.0
    assert a["p50_ms"] == 300
    assert a["p99_ms"] == 500


def test_aggregate_uptime():
    rows = [_sample(ok=True), _sample(ok=False), _sample(ok=True), _sample(ok=True)]
    agg = aggregate(rows)
    assert agg["x"]["uptime_pct"] == 75.0


def test_detect_alert_requires_consecutive():
    rows = [_sample(ok=False, lat=9000) for _ in range(2)]
    assert detect_alert(rows, consecutive=3, latency_ms=5000) == []
    rows.append(_sample(ok=False, lat=9000))
    assert detect_alert(rows, consecutive=3, latency_ms=5000) == ["x"]


def test_detect_alert_recovers():
    rows = [_sample(ok=False, lat=9000) for _ in range(3)] + [_sample(ok=True, lat=100)]
    assert detect_alert(rows, consecutive=3, latency_ms=5000) == []


def test_probe_once_shed_on_503():
    class FakeResp:
        def getcode(self): return 503
        headers = {"Retry-After": "5"}
        def read(self, n): return b'{"error":"overloaded"}'
        def __enter__(self): return self
        def __exit__(self, *a): return False
    with mock.patch("urllib.request.urlopen", return_value=FakeResp()):
        s = probe_once("https://x", "m", "k", 1, 5)
    assert s["http_status"] == 503
    assert s["shed_detected"] is True
    assert s["ok"] is False


def test_probe_once_ok():
    class FakeResp:
        def getcode(self): return 200
        headers = {}
        def read(self, n): return b'{"choices":[{"message":{"content":"hi"}}]}'
        def __enter__(self): return self
        def __exit__(self, *a): return False
    with mock.patch("urllib.request.urlopen", return_value=FakeResp()):
        s = probe_once("https://x", "m", "k", 1, 5)
    assert s["ok"] is True
    assert s["shed_detected"] is False


def test_jsonl_roundtrip(tmp_path: Path):
    p = tmp_path / "h.jsonl"
    append_jsonl(p, _sample())
    append_jsonl(p, _sample(ok=False, lat=9000))
    rows = read_jsonl(p, hours=24)
    assert len(rows) == 2
    # filtro de tempo: ts velho é excluido
    append_jsonl(p, _sample(ts="2020-01-01T00:00:00Z"))
    rows2 = read_jsonl(p, hours=24)
    assert len(rows2) == 2


def test_probe_once_network_exception():
    with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("boom")):
        s = probe_once("https://x", "m", "k", 1, 5)
    assert s["ok"] is False
    assert "TimeoutError" in s["error"]
