"""Probe de saude por provider — latencia real + load shedding.

Uso:  python -m benchmark_providers.probe_health [--config scripts/probe_config.json]
                                            [--out data/provider_health.jsonl]
                                            [--aggregate data/provider_health.json]

Nao usa requests/httpx — stdlib urllib apenas.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

SHED_PAT = re.compile(r"overloaded|capacity|rate.?limit|try again later|shed", re.I)
SHED_STATUS = {429, 503}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_env_key(name: str) -> str:
    """Le do ambiente; fallback para .env do Hermes."""
    v = os.environ.get(name, "").strip()
    if v:
        return v
    for p in (
        Path.home() / "AppData/Local/hermes/.env",
        Path.cwd() / ".env",
    ):
        if p.exists():
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith(f"{name}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def probe_once(url: str, model: str, api_key: str, max_tokens: int, timeout: int, api_style: str = "openai") -> dict:
    """Uma tentativa. Retorna amostra para jsonl."""
    ts = _now_iso()
    if api_style == "gemini":
        # Gemini API usa formato diferente: contents + generationConfig
        body = json.dumps({
            "contents": [{"parts": [{"text": "ping"}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0}
        }).encode("utf-8")
    else:
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": max_tokens,
            "temperature": 0,
            "stream": False,
        }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "benchmark-geral-probe/1.0",
    }
    if api_key:
        if api_style == "gemini":
            headers["x-goog-api-key"] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    t0 = time.perf_counter()
    status = 0
    err = ""
    shed = False
    retry_after = None
    body_snippet = ""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            retry_after = resp.headers.get("Retry-After")
            raw = resp.read(2048)
            body_snippet = raw.decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        status = e.code
        retry_after = e.headers.get("Retry-After") if e.headers else None
        try:
            body_snippet = e.read(2048).decode("utf-8", errors="ignore")
        except Exception:
            pass
        err = f"HTTP {status}"
    except Exception as e:  # timeout, DNS, TLS
        err = f"{type(e).__name__}: {e}"
    dt_ms = round((time.perf_counter() - t0) * 1000, 1)

    if status in SHED_STATUS or retry_after or SHED_PAT.search(body_snippet or ""):
        shed = True

    ok = 200 <= status < 300 and not shed
    return {
        "ts": ts,
        "model_probe": model,
        "ok": ok,
        "latency_ms": dt_ms,
        "http_status": status,
        "shed_detected": shed,
        "retry_after": retry_after,
        "error": err or None,
    }


def probe_provider(name: str, cfg: dict, probe_cfg: dict) -> dict:
    """Roda probe com retries; retorna a melhor amostra (primeiro ok, senao a ultima)."""
    api_key = _read_env_key(cfg.get("key_env", ""))
    retries = int(probe_cfg.get("retries", 3))
    backoff = float(probe_cfg.get("backoff_s", 1.5))
    samples = []
    for i in range(retries):
        s = probe_once(
            url=cfg["url"],
            model=cfg["model"],
            api_key=api_key,
            max_tokens=int(probe_cfg.get("max_tokens", 1)),
            timeout=int(probe_cfg.get("timeout_s", 10)),
            api_style=cfg.get("api_style", "openai"),
        )
        s["provider"] = name
        s["attempt"] = i + 1
        samples.append(s)
        if s["ok"]:
            break
        time.sleep(backoff * (i + 1))
    best = next((s for s in samples if s["ok"]), samples[-1])
    return best


def aggregate(records: list[dict]) -> dict:
    """Agrega lista de amostras -> uptime/P50/P99 por provider."""
    by = {}
    for r in records:
        by.setdefault(r["provider"], []).append(r)
    out = {}
    for prov, rows in by.items():
        lats = sorted(r["latency_ms"] for r in rows)
        n = len(lats)
        ok_n = sum(1 for r in rows if r["ok"])
        shed_n = sum(1 for r in rows if r.get("shed_detected"))

        def pct(p: float) -> float | None:
            if not lats:
                return None
            idx = max(0, min(n - 1, int(round(p * (n - 1)))))
            return lats[idx]

        out[prov] = {
            "samples": n,
            "ok": ok_n,
            "uptime_pct": round(100.0 * ok_n / n, 2) if n else None,
            "shed_hits": shed_n,
            "p50_ms": pct(0.50),
            "p99_ms": pct(0.99),
            "last_status": rows[-1].get("http_status"),
            "last_error": rows[-1].get("error"),
            "last_ok": rows[-1]["ok"],
            "last_ts": rows[-1]["ts"],
        }
    return out


def detect_alert(records: list[dict], consecutive: int, latency_ms: float) -> list[str]:
    """Providers com ultimas N probes consecutivas falhando OU acima do limiar."""
    by = {}
    for r in records:
        by.setdefault(r["provider"], []).append(r)
    alerts = []
    for prov, rows in by.items():
        tail = rows[-consecutive:]
        if len(tail) < consecutive:
            continue
        all_bad = all((not r["ok"]) or r["latency_ms"] > latency_ms for r in tail)
        if all_bad:
            alerts.append(prov)
    return alerts


def send_telegram(text: str) -> bool:
    """Envia alerta via Telegram Bot API. Retorna True se entregue."""
    token = _read_env_key("TELEGRAM_BOT_TOKEN")
    chat_id = _read_env_key("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return 200 <= r.getcode() < 300
    except Exception:
        return False


def read_jsonl(path: Path, hours: int = 24) -> list[dict]:
    if not path.exists():
        return []
    cutoff = time.time() - hours * 3600
    out = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        try:
            ts = datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            continue
        if ts >= cutoff:
            out.append(r)
    return out


def append_jsonl(path: Path, sample: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(sample, ensure_ascii=False) + "\n")


def run(config_path: Path, jsonl_path: Path, aggregate_path: Path, alert: bool = True) -> dict:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    probe_cfg = cfg.get("probe", {})
    alert_cfg = cfg.get("alert", {})
    new_samples = []
    for name, pcfg in cfg.get("providers", {}).items():
        if pcfg.get("disabled"):
            continue
        s = probe_provider(name, pcfg, probe_cfg)
        append_jsonl(jsonl_path, s)
        new_samples.append(s)

    records = read_jsonl(jsonl_path, hours=24)
    agg = aggregate(records)
    payload = {
        "generated_at": _now_iso(),
        "window_hours": 24,
        "providers": agg,
    }
    aggregate_path.parent.mkdir(parents=True, exist_ok=True)
    aggregate_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    alerts = detect_alert(
        records,
        consecutive=int(alert_cfg.get("consecutive_threshold", 3)),
        latency_ms=float(alert_cfg.get("latency_threshold_ms", 5000)),
    )
    if alerts and alert:
        msg = (
            "⚠️ <b>benchmark_providers health</b>\n"
            + "\n".join(f"• {p}: {agg[p]['samples']} amostras 24h, uptime {agg[p]['uptime_pct']}%, P50 {agg[p]['p50_ms']}ms" for p in alerts)
        )
        send_telegram(msg)

    return {"samples": new_samples, "aggregate": agg, "alerts": alerts}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="scripts/probe_config.json")
    ap.add_argument("--out", default="data/provider_health.jsonl")
    ap.add_argument("--aggregate", default="data/provider_health.json")
    ap.add_argument("--no-alert", action="store_true")
    a = ap.parse_args(argv)
    res = run(Path(a.config), Path(a.out), Path(a.aggregate), alert=not a.no_alert)
    print(json.dumps({"alerts": res["alerts"], "providers": list(res["aggregate"].keys())}, indent=2))


if __name__ == "__main__":
    main()
