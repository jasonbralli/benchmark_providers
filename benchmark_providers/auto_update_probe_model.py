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


# Pool de modelos sponsored conhecidos p/ rotacao semanal
MODEL_POOL = [
    "prism-ml/Ternary-Bonsai-27B-AWQ-4bit",
    "inclusionAI/Ling-3.0-flash-Fin",
]
POOL_FILE = Path(__file__).parent.parent / "data" / "model_pool_state.json"


def rotate_weekly(current: str) -> str:
    """Alterna entre modelos do pool a cada semana. Persiste o ultimo usado + dia."""
    from datetime import datetime, timezone
    state = {}
    if POOL_FILE.exists():
        try:
            state = json.loads(POOL_FILE.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    last_model = state.get("model") or current
    last_seen = state.get("last_seen_iso")  # iso string
    now = datetime.now(timezone.utc)
    today_iso = now.strftime("%Y-%m-%d")

    # Se hoje ja rodou e trocou, nao troca de novo
    if last_seen == today_iso:
        return last_model

    # Se eh o mesmo dia da ultima troca, mantem
    # Caso contrario, alterna
    nxt = MODEL_POOL[(MODEL_POOL.index(last_model) + 1) % len(MODEL_POOL)] if last_model in MODEL_POOL else MODEL_POOL[0]
    state = {"model": nxt, "last_seen_iso": today_iso, "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    POOL_FILE.parent.mkdir(parents=True, exist_ok=True)
    POOL_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return nxt


def auto_update(dry_run: bool = False, rotate: bool = True) -> tuple[bool, str]:
    """Aplica troca no config somente para o provider 'huggingface' (router).
    Se rotate=True (default), alterna semanalmente entre pool MODEL_POOL.
    Retorna (changed, message)."""
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    hf_cfg = cfg.get("providers", {}).get("huggingface")
    if not hf_cfg:
        return False, "provider huggingface nao encontrado no config"

    current = hf_cfg.get("model")
    if rotate:
        target = rotate_weekly(current)
        msg = f"rotacao semanal: {current} -> {target}" if target != current else f"rotacao: mantem {current}"
    else:
        scan_result = scan(fetch_hf_models())
        best = pick_best_sponsored(scan_result)
        if not best:
            return False, "nenhum modelo sponsored ($0/$0) disponivel"
        target = best["model"]
        msg = (
            f"huggingface: {current} -> {target} "
            f"(ctx {best['ctx']}, ttft~{best.get('ttft_ms')}ms, via {best['provider']})"
        )

    if target == current:
        return False, msg
    if dry_run:
        return True, "DRY-RUN: " + msg
    hf_cfg["model"] = target
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True, msg


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-rotate", action="store_true", help="usar scanner em vez de rotacao semanal")
    a = ap.parse_args(argv)
    try:
        changed, msg = auto_update(dry_run=a.dry_run, rotate=not a.no_rotate)
        print(("CHANGED " if changed else "OK      ") + msg)
        return 0
    except Exception as e:
        print(f"ERRO: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
