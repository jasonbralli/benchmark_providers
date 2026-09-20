"""Scanner de modelos free no HuggingFace Inference Router.

Fonte oficial: https://huggingface.co/inference/models (pagina JS).
Equivalente via API: GET https://router.huggingface.co/v1/models
  - Cada modelo tem lista `providers[]` com `provider`, `is_free`, `pricing.input/output`,
    `first_token_latency_ms`, `throughput`, `context_length`, `status`.

Definicao de "free" (nuance pratica):
  1) `is_free: true` -> gratis de verdade na sua conta (raro; requer plano HF especifico).
  2) `pricing.input == 0 AND pricing.output == 0` -> "$0/$0" — o provider patrocina
     (ex: Novita), mas pode exigir saldo > 0 ou conta ativa. No dashboard chamamos
     de "patrocinado".
  3) Precos muito baixos (< $0.10/M in) — "quase-free" — exibidos p/ referencia.

Uso:
    python -m benchmark_providers.free_scanner                  # imprime
    python -m benchmark_providers.free_scanner --json out.json  # salva JSON
    python -m benchmark_providers.free_scanner --top N          # top N

Saida: lista ordenada por custo (free -> quase-free) agrupada por provider.
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from collections import defaultdict
from pathlib import Path

from .probe_health import _read_env_key

HF_MODELS_URL = "https://router.huggingface.co/v1/models"
NEAR_FREE_THRESHOLD = 0.10  # $/M tokens in — abaixo disso consideramos "quase-free"


def fetch_hf_models() -> list[dict]:
    """Retorna lista crua de modelos do HF router."""
    token = _read_env_key("HF_TOKEN")
    headers = {"User-Agent": "benchmark-providers/scanner"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(HF_MODELS_URL, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return data.get("data", []) or []


def _norm_price(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def classify(p: dict) -> str:
    """free (is_free) | sponsored ($0/$0 mas is_free=false) | cheap | paid."""
    if p.get("is_free"):
        return "free"
    pin = _norm_price((p.get("pricing") or {}).get("input"))
    pout = _norm_price((p.get("pricing") or {}).get("output"))
    if pin == 0 and pout == 0:
        return "sponsored"
    if pin is not None and pin < NEAR_FREE_THRESHOLD:
        return "cheap"
    return "paid"


def scan(models: list[dict]) -> dict:
    """Agrupa candidatos por provider, separando por tier."""
    by_provider: dict[str, dict[str, list]] = defaultdict(
        lambda: {"free": [], "sponsored": [], "cheap": []}
    )
    for m in models:
        mid = m.get("id")
        for p in m.get("providers") or []:
            if p.get("status") != "live":
                continue
            tier = classify(p)
            if tier == "paid":
                continue
            pin = _norm_price((p.get("pricing") or {}).get("input"))
            pout = _norm_price((p.get("pricing") or {}).get("output"))
            entry = {
                "model": mid,
                "provider": p.get("provider"),
                "ctx": p.get("context_length"),
                "in_usd_per_m": pin,
                "out_usd_per_m": pout,
                "ttft_ms": p.get("first_token_latency_ms"),
                "throughput": p.get("throughput"),
            }
            by_provider[p.get("provider")][tier].append(entry)
    # ordena cada bucket por (preco, -ctx)
    for prov, tiers in by_provider.items():
        for t in tiers.values():
            t.sort(key=lambda e: ((e["in_usd_per_m"] or 0), -(e["ctx"] or 0)))
    return dict(by_provider)


def format_report(scan: dict, top: int = 10) -> str:
    lines = ["# Modelos FREE/patrocinados/quase-free no HF Router", ""]
    total_free = sum(len(v["free"]) for v in scan.values())
    total_spons = sum(len(v["sponsored"]) for v in scan.values())
    total_cheap = sum(len(v["cheap"]) for v in scan.values())
    lines.append(f"**Totais:** {total_free} free · {total_spons} sponsored ($0/$0) · {total_cheap} quase-free (<${NEAR_FREE_THRESHOLD}/M)")
    lines.append("")
    for prov in sorted(scan.keys()):
        tiers = scan[prov]
        n = sum(len(v) for v in tiers.values())
        if n == 0:
            continue
        lines.append(f"## {prov}  ({n} candidatos)")
        for tier, label in (("free", "FREE"), ("sponsored", "$0/$0 (patrocinado — pode exigir saldo)"), ("cheap", f"<${NEAR_FREE_THRESHOLD}/M")):
            bucket = tiers[tier]
            if not bucket:
                continue
            lines.append(f"**{label}** ({len(bucket)}):")
            for e in bucket[:top]:
                ctx_k = (e['ctx'] or 0) // 1024
                ttft = e['ttft_ms'] and f"{e['ttft_ms']:.0f}ms" or "?"
                lines.append(
                    f"  - `{e['model']}` — ctx {ctx_k}k · in ${e['in_usd_per_m']}/M · out ${e['out_usd_per_m']}/M · ttft~{ttft}"
                )
            if len(bucket) > top:
                lines.append(f"  ... +{len(bucket) - top} mais")
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_out", help="salva JSON neste caminho")
    ap.add_argument("--top", type=int, default=10, help="top N por provider/tier no report")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    models = fetch_hf_models()
    scan_result = scan(models)
    report = format_report(scan_result, top=a.top)

    if not a.quiet:
        print(report)

    if a.json_out:
        out = Path(a.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "source": HF_MODELS_URL,
            "providers": scan_result,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"json salvo em {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
