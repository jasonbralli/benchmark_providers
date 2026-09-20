"""Auto-update do modelo probeado nos providers, baseado no free_scanner.

Logica:
- Para provider "huggingface": acessa via HF router, entao qualquer modelo $0/$0
  patrocinado pode ser o alvo. Escolhe o sponsored com maior context_length
  (criterio: mais ctx = melhor probe, mesmo modelo ja ok se for o melhor).
- Outros providers acoplados a HF (deepinfra/together via HF router) - futuro.

Uso:
    python -m benchmark_providers.auto_update_probe_model
    python -m benchmark_providers.auto_update_probe_model --dry-run

Retorna 0 se trocou (ou nada muda), 2 em erro.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .free_scanner import fetch_hf_models, scan

ROOT = Path(__file__).parent.parent
CONFIG = ROOT / "scripts" / "probe_config.json"


def pick_best_sponsored(scan_result: dict) -> dict | None:
    """Do scan, pega o melhor modelo sponsored agregado ($0/$0) em qualquer provider HF-router."""
    candidates = []
    for prov, tiers in scan_result.items():
        for e in tiers.get("sponsored", []):
            candidates.append(e)
    if not candidates:
        return None
    # Maior ctx primeiro; desempate: menor ttft
    candidates.sort(key=lambda e: (-(e.get("ctx") or 0), e.get("ttft_ms") or 9e9))
    return candidates[0]


def auto_update(dry_run: bool = False) -> tuple[bool, str]:
    """Aplica troca no config somente para o provider 'huggingface' (router).
    Retorna (changed, message)."""
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    hf_cfg = cfg.get("providers", {}).get("huggingface")
    if not hf_cfg:
        return False, "provider huggingface nao encontrado no config"

    scan_result = scan(fetch_hf_models())
    best = pick_best_sponsored(scan_result)
    if not best:
        return False, "nenhum modelo sponsored ($0/$0) disponivel"

    current = hf_cfg.get("model")
    target = best["model"]
    if current == target:
        return False, f"modelo atual ({current}) ja e o melhor sponsored"

    msg = (
        f"huggingface: {current} -> {target} "
        f"(ctx {best['ctx']}, ttft~{best.get('ttft_ms')}ms, via {best['provider']})"
    )
    if dry_run:
        return True, "DRY-RUN: " + msg
    hf_cfg["model"] = target
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True, msg


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        changed, msg = auto_update(dry_run=a.dry_run)
        print(("CHANGED " if changed else "OK      ") + msg)
        return 0
    except Exception as e:
        print(f"ERRO: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
