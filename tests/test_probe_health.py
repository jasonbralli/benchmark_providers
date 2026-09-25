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


def _sample(provider="x", ok=True, lat=100, status=200, shed=False, ts="2026-09-18T12:00:00Z", ttft=None):
    return {
        "ts": ts,
        "provider": provider,
        "model_probe": "m",
        "ok": ok,
        "latency_ms": lat,
        "ttft_ms": ttft,
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
    assert a["p95_ms"] == 500
    assert a["p99_ms"] == 500


def test_aggregate_ttft():
    rows = [_sample(lat=200, ttft=t) for t in (50, 80, 100, 150)]
    rows.append(_sample(lat=200, ttft=None))  # amostra sem TTFT (ex: erro)
    agg = aggregate(rows)
    a = agg["x"]
    assert a["ttft_samples"] == 4
    assert a["ttft_p50_ms"] in (80, 100)  # idx arredondado
    assert a["ttft_p95_ms"] == 150


def test_aggregate_ttft_absent_in_old_probes():
    rows = [_sample(lat=100) for _ in range(3)]
    for r in rows:
        r.pop("ttft_ms")  # probes antigas nao tem o campo
    agg = aggregate(rows)
    a = agg["x"]
    assert a["ttft_samples"] == 0
    assert a["ttft_p50_ms"] is None
    assert a["ttft_p95_ms"] is None


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


def test_probe_once_ok():
    class FakeResp:
        def getcode(self): return 200
        headers = {}
        def read(self, n):
            # primeira chamada devolve chunk SSE; depois EOF
            if not hasattr(self, "_sent"):
                self._sent = True
                return b'data: {"choices":[{"delta":{"content":"h"}}]}\n\n'
            return b""
        def __enter__(self): return self
        def __exit__(self, *a): return False
    with mock.patch("urllib.request.urlopen", return_value=FakeResp()):
        s = probe_once("https://x", "m", "k", 1, 5)
    assert s["ok"] is True
    assert s["shed_detected"] is False
    assert s["ttft_ms"] is not None and s["ttft_ms"] >= 0


def test_probe_once_ttft_none_when_no_sse():
    class FakeResp:
        def getcode(self): return 200
        headers = {}
        def read(self, n): return b""  # sem conteudo
        def __enter__(self): return self
        def __exit__(self, *a): return False
    with mock.patch("urllib.request.urlopen", return_value=FakeResp()):
        s = probe_once("https://x", "m", "k", 1, 5)
    assert s["ok"] is True
    assert s["ttft_ms"] is None


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


def test_probe_once_anthropic_headers():
    """api_style=anthropic: auth via x-api-key + anthropic-version (nao Bearer)."""
    captured = {}

    class FakeResp:
        def getcode(self): return 200
        headers = {}
        def read(self, n): return b""
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        captured["headers"] = {k.lower(): v for k, v in req.headers.items()}
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResp()

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        s = probe_once("https://x", "m", "k", 1, 5, api_style="anthropic")
    assert captured["headers"].get("x-api-key") == "k"
    assert captured["headers"].get("anthropic-version") == "2023-06-01"
    assert "authorization" not in captured["headers"]
    # body /v1/messages e stream SSE ja sao compat com o formato OpenAI do probe
    assert captured["body"]["messages"] == [{"role": "user", "content": "ping"}]
    assert captured["body"]["stream"] is True
    assert s["ok"] is True


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
