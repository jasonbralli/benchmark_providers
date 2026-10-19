"""Regressão da regra de mitigação de HTTP 410 (swap automático de modelo)."""

import json

from benchmark_providers.mitigate_410 import find_410, mitigate, next_model


def _cfg(tmp_path, with_fallbacks=True, disabled=False):
    prov = {
        "url": "https://x/v1/chat/completions",
        "model": "old/dead",
        "key_env": "X_KEY",
    }
    if with_fallbacks:
        prov["fallback_models"] = ["new/alive", "new/backup"]
    if disabled:
        prov["disabled"] = True
    cfg = {"providers": {"nvidia": prov}, "probe": {"max_tokens": 1, "timeout_s": 10, "retries": 1, "backoff_s": 0}}
    p = tmp_path / "probe_config.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return p, cfg


def test_find_410_por_status_e_por_erro():
    agg = {
        "nvidia": {"last_status": 410, "last_error": "HTTP 410"},
        "groq": {"last_status": 200, "last_error": None},
        "hf": {"last_status": None, "last_error": "HTTP 410"},
        "outro": {"last_status": 404, "last_error": "HTTP 404"},
    }
    assert sorted(find_410(agg)) == ["hf", "nvidia"]
    assert find_410(None) == []


def test_next_model_ciclo():
    fb = ["a/1", "b/2", "c/3"]
    assert next_model(fb, "a/1") == "b/2"
    assert next_model(fb, "c/3") == "a/1"  # wrap-around
    assert next_model(fb, "z/9") == "a/1"  # fora da lista -> primeiro
    assert next_model([], "a/1") is None


def test_mitigate_troca_e_anota(tmp_path):
    p, _ = _cfg(tmp_path)
    agg = {"nvidia": {"last_status": 410, "last_error": "HTTP 410"}}
    swaps = mitigate(p, agg)
    assert swaps == [("nvidia", "old/dead", "new/alive")]
    cfg = json.loads(p.read_text(encoding="utf-8"))
    assert cfg["providers"]["nvidia"]["model"] == "new/alive"
    assert "new/alive" in cfg["providers"]["nvidia"]["note"]
    assert "410 mitigado" in cfg["providers"]["nvidia"]["note"]


def test_mitigate_dry_run_nao_escreve(tmp_path):
    p, _ = _cfg(tmp_path)
    agg = {"nvidia": {"last_status": 410, "last_error": "HTTP 410"}}
    assert mitigate(p, agg, dry_run=True) == [("nvidia", "old/dead", "new/alive")]
    assert json.loads(p.read_text(encoding="utf-8"))["providers"]["nvidia"]["model"] == "old/dead"


def test_mitigate_sem_fallback_nao_troca(tmp_path):
    p, _ = _cfg(tmp_path, with_fallbacks=False)
    agg = {"nvidia": {"last_status": 410, "last_error": "HTTP 410"}}
    assert mitigate(p, agg) == []
    assert json.loads(p.read_text(encoding="utf-8"))["providers"]["nvidia"]["model"] == "old/dead"


def test_mitigate_provider_disabled_ignorado(tmp_path):
    p, _ = _cfg(tmp_path, disabled=True)
    agg = {"nvidia": {"last_status": 410, "last_error": "HTTP 410"}}
    assert mitigate(p, agg) == []
