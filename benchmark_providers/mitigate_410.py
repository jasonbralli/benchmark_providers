"""Mitigação automática de HTTP 410 (modelo deprecated) — benchmark_providers.

Regra: sempre que o probe de um provider retorna HTTP 410 (modelo removido do
catálogo do provider), troca o `model` pelo próximo candidato da lista
`fallback_models` do scripts/probe_config.json (rotação cíclica) e re-probeia
apenas os providers trocados — o vermelho do card reverte no mesmo ciclo.

- Sem `fallback_models` no config: apenas loga warning (não inventa modelo).
- Se o candidato também estiver morto (410/404), o próximo ciclo diário
  rotaciona para o seguinte da lista (converge para um vivo, se houver).
- stdlib only (regra do projeto: probe_health nunca ganha dependência).

Integrado ao scripts/curate_daily_light.py (passo 1.5) e via CLI:

    python -m benchmark_providers.mitigate_410 --dry-run   # preview
    python -m benchmark_providers.mitigate_410             # aplica + re-probe
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .probe_health import (
    _now_iso,
    aggregate,
    append_jsonl,
    probe_provider,
    read_jsonl,
)

logger = logging.getLogger("mitigate_410")

ROOT = Path(__file__).parent.parent
CONFIG = ROOT / "scripts" / "probe_config.json"
JSONL = ROOT / "data" / "provider_health.jsonl"
AGGREGATE = ROOT / "data" / "provider_health.json"


def find_410(agg: dict) -> list[str]:
    """Nomes de providers cuja última amostra é HTTP 410 (modelo deprecated)."""
    out = []
    for name, p in (agg or {}).items():
        if p.get("last_status") == 410 or p.get("last_error") == "HTTP 410":
            out.append(name)
    return out


def next_model(fallbacks: list, current: str) -> str | None:
    """Próximo candidato da lista (cíclico). None se lista vazia."""
    if not fallbacks:
        return None
    if current in fallbacks:
        return fallbacks[(fallbacks.index(current) + 1) % len(fallbacks)]
    return fallbacks[0]


def mitigate(config_path: Path, agg: dict, dry_run: bool = False) -> list[tuple[str, str, str]]:
    """Troca o modelo dos providers com 410. Retorna [(provider, old, new), ...]."""
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    swaps: list[tuple[str, str, str]] = []
    for name in find_410(agg):
        p = (cfg.get("providers") or {}).get(name)
        if not p or p.get("disabled"):
            continue
        new = next_model(p.get("fallback_models") or [], p.get("model", ""))
        if not new:
            logger.warning("410 em %s sem fallback_models no config — troca manual necessária", name)
            continue
        if new == p.get("model"):
            continue
        swaps.append((name, p.get("model"), new))
        if not dry_run:
            note = (
                f" · 410 mitigado {datetime.now(timezone.utc).strftime('%d/%m/%Y')}: "
                f"{p['model']} -> {new}"
            )
            p["model"] = new
            p["note"] = (p.get("note") or "") + note
    if swaps and not dry_run:
        config_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        for name, old, new in swaps:
            logger.info("410 mitigado %s: %s -> %s", name, old, new)
    return swaps


def reprobe_swapped(config_path: Path, jsonl_path: Path, aggregate_path: Path,
                    swaps: list[tuple[str, str, str]]) -> dict:
    """Re-probeia apenas os providers trocados e reconstrói o agregado 24h."""
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    probe_cfg = cfg.get("probe", {})
    for name, _old, _new in swaps:
        s = probe_provider(name, cfg["providers"][name], probe_cfg)
        append_jsonl(jsonl_path, s)
        logger.info("re-probe %s: HTTP %s %s", name, s.get("http_status"), s.get("error") or "OK")
    records = read_jsonl(jsonl_path, hours=24)
    payload = {
        "generated_at": _now_iso(),
        "window_hours": 24,
        "providers": aggregate(records),
    }
    aggregate_path.parent.mkdir(parents=True, exist_ok=True)
    aggregate_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CONFIG))
    ap.add_argument("--jsonl", default=str(JSONL))
    ap.add_argument("--aggregate", default=str(AGGREGATE))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    agg = json.loads(Path(a.aggregate).read_text(encoding="utf-8")).get("providers") or {}
    swaps = mitigate(Path(a.config), agg, dry_run=a.dry_run)
    for name, old, new in swaps:
        print(f"{'DRY-RUN ' if a.dry_run else 'CHANGED '}{name}: {old} -> {new}")
    if not swaps:
        print("OK       nenhum 410 a mitigar")
        return 0
    if not a.dry_run:
        payload = reprobe_swapped(Path(a.config), Path(a.jsonl), Path(a.aggregate), swaps)
        for name, _o, _n in swaps:
            p = payload["providers"].get(name, {})
            print(f"REPROBE  {name}: HTTP {p.get('last_status')} last_ok={p.get('last_ok')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
