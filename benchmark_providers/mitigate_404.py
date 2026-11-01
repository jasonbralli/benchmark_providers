"""Mitigação automática de HTTP 404 (modelo inexistente/renomeado/fora do catálogo).

Mesma rotação cíclica do mitigate_410: probe retorna 404 -> troca o `model` pelo
próximo candidato de `fallback_models` do scripts/probe_config.json e re-probeia
apenas os providers trocados — o vermelho do card reverte no mesmo ciclo.

Casos reais de 404:
- sufixo :free removido pelo provider (ex: thinkingmachines/inkling-small:free no
  Kilo Code, nov/2026 — catálogo ao vivo lista só a versão paga)
- modelo renomeado ou fora do catálogo do provider

- Sem `fallback_models` no config: apenas loga warning (não inventa modelo).
- Se o candidato também estiver morto (404/410), o próximo ciclo rotaciona de
  novo (converge para um vivo, se houver).
- stdlib only (regra do projeto: probe_health nunca ganha dependência).

Integrado ao scripts/curate_daily_light.py (passo 1.5) e via CLI:

    python -m benchmark_providers.mitigate_404 --dry-run   # preview
    python -m benchmark_providers.mitigate_404             # aplica + re-probe
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .mitigate_410 import next_model, reprobe_swapped

logger = logging.getLogger("mitigate_404")

ROOT = Path(__file__).parent.parent
CONFIG = ROOT / "scripts" / "probe_config.json"
JSONL = ROOT / "data" / "provider_health.jsonl"
AGGREGATE = ROOT / "data" / "provider_health.json"


def find_404(agg: dict) -> list[str]:
    """Nomes de providers cuja última amostra é HTTP 404 (modelo fora do catálogo)."""
    out = []
    for name, p in (agg or {}).items():
        if p.get("last_status") == 404 or p.get("last_error") == "HTTP 404":
            out.append(name)
    return out


def mitigate_404(config_path: Path, agg: dict, dry_run: bool = False) -> list[tuple[str, str, str]]:
    """Troca o modelo dos providers com 404. Retorna [(provider, old, new), ...]."""
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    swaps: list[tuple[str, str, str]] = []
    for name in find_404(agg):
        p = (cfg.get("providers") or {}).get(name)
        if not p or p.get("disabled"):
            continue
        new = next_model(p.get("fallback_models") or [], p.get("model", ""))
        if not new:
            logger.warning("404 em %s sem fallback_models no config — troca manual necessária", name)
            continue
        if new == p.get("model"):
            continue
        swaps.append((name, p.get("model"), new))
        if not dry_run:
            note = (
                f" · 404 mitigado {datetime.now(timezone.utc).strftime('%d/%m/%Y')}: "
                f"{p['model']} -> {new}"
            )
            p["model"] = new
            p["note"] = (p.get("note") or "") + note
    if swaps and not dry_run:
        config_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        for name, old, new in swaps:
            logger.info("404 mitigado %s: %s -> %s", name, old, new)
    return swaps


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CONFIG))
    ap.add_argument("--jsonl", default=str(JSONL))
    ap.add_argument("--aggregate", default=str(AGGREGATE))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    agg = json.loads(Path(a.aggregate).read_text(encoding="utf-8")).get("providers") or {}
    swaps = mitigate_404(Path(a.config), agg, dry_run=a.dry_run)
    for name, old, new in swaps:
        print(f"{'DRY-RUN ' if a.dry_run else 'CHANGED '}{name}: {old} -> {new}")
    if not swaps:
        print("OK       nenhum 404 a mitigar")
        return 0
    if not a.dry_run:
        payload = reprobe_swapped(Path(a.config), Path(a.jsonl), Path(a.aggregate), swaps)
        for name, _o, _n in swaps:
            p = payload["providers"].get(name, {})
            print(f"REPROBE  {name}: HTTP {p.get('last_status')} last_ok={p.get('last_ok')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
