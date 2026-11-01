"""Regressão da regra de mitigação de HTTP 404 (swap automático de modelo)."""

import json

from benchmark_providers.mitigate_404 import find_404, mitigate_404
from benchmark_providers.mitigate_410 import next_model


def _cfg(tmp_path, with_fallbacks=True, disabled=False):
    prov = {
        "url": "https://x/v1/chat/completions",
        "model": "old/gone:free",
        "key_env": "X_KEY",
    }
    if with_fallbacks:
        prov["fallback_models"] = ["new/alive-free", "new/backup-free"]
    if disabled:
        prov["disabled"] = True
    cfg = {"providers": {"kilocode": prov}, "probe": {"max_tokens": 1, "timeout_s": 10, "retries": 1, "backoff_s": 0}}
    p = tmp_path / "probe_config.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return p, cfg


def test_find_404_por_status_e_por_erro():
    agg = {
        "kilocode": {"last_status": 404, "last_error": "HTTP 404"},
        "groq": {"last_status": 200, "last_error": None},
        "hf": {"last_status": None, "last_error": "HTTP 404"},
        "nvidia": {"last_status": 410, "last_error": "HTTP 410"},  # 410 nao entra no 404
    }
    assert sorted(find_404(agg)) == ["hf", "kilocode"]
    assert find_404(None) == []


def test_mitigate_404_troca_e_anota(tmp_path):
    p, _ = _cfg(tmp_path)
    agg = {"kilocode": {"last_status": 404, "last_error": "HTTP 404"}}
    swaps = mitigate_404(p, agg)
    assert swaps == [("kilocode", "old/gone:free", "new/alive-free")]
    cfg = json.loads(p.read_text(encoding="utf-8"))
    assert cfg["providers"]["kilocode"]["model"] == "new/alive-free"
    assert "404 mitigado" in cfg["providers"]["kilocode"]["note"]
    assert "new/alive-free" in cfg["providers"]["kilocode"]["note"]


def test_mitigate_404_dry_run_nao_escreve(tmp_path):
    p, _ = _cfg(tmp_path)
    agg = {"kilocode": {"last_status": 404, "last_error": "HTTP 404"}}
    assert mitigate_404(p, agg, dry_run=True) == [("kilocode", "old/gone:free", "new/alive-free")]
    assert json.loads(p.read_text(encoding="utf-8"))["providers"]["kilocode"]["model"] == "old/gone:free"


def test_mitigate_404_sem_fallback_nao_troca(tmp_path):
    p, _ = _cfg(tmp_path, with_fallbacks=False)
    agg = {"kilocode": {"last_status": 404, "last_error": "HTTP 404"}}
    assert mitigate_404(p, agg) == []
    assert json.loads(p.read_text(encoding="utf-8"))["providers"]["kilocode"]["model"] == "old/gone:free"


def test_mitigate_404_provider_disabled_ignorado(tmp_path):
    p, _ = _cfg(tmp_path, disabled=True)
    agg = {"kilocode": {"last_status": 404, "last_error": "HTTP 404"}}
    assert mitigate_404(p, agg) == []


def test_mitigate_404_proximo_do_ciclo_quando_atual_ja_foi_trocado(tmp_path):
    # após a 1a troca, se o novo também morrer (404), o ciclo pega o próximo
    p, _ = _cfg(tmp_path)
    prov = json.loads(p.read_text(encoding="utf-8"))["providers"]["kilocode"]
    prov["model"] = "new/alive-free"
    p.write_text(json.dumps({"providers": {"kilocode": prov}}), encoding="utf-8")
    agg = {"kilocode": {"last_status": 404, "last_error": "HTTP 404"}}
    swaps = mitigate_404(p, agg)
    assert swaps == [("kilocode", "new/alive-free", "new/backup-free")]
    assert next_model(["a", "b", "c"], "c") == "a"  # wrap-around herdado do 410
