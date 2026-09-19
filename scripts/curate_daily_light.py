"""scripts/curate_daily_light.py
================================

Versão LIGHT do curate_daily.py — apenas health probe + commit/push.

Diferença vs benchmark_geral/scripts/curate_daily.py:
- NÃO roda pipeline de consolidação (extract/normalize/enrich/build)
- NÃO valida quedas de contagem de modelos
- APENAS: probe → grava JSON/JSONL → git add/commit/push → alerta Telegram

Uso:
    python scripts/curate_daily_light.py

Task Scheduler: agendar para rodar a cada N horas, independente do
curate_daily full (que roda em benchmark_geral 1x/dia).
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from benchmark_providers.probe_health import (  # noqa: E402
    run as probe_run,
    send_telegram,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("curate_daily_light")

DATA_DIR = ROOT / "data"
PROVIDER_HEALTH_JSONL = DATA_DIR / "provider_health.jsonl"
PROVIDER_HEALTH_JSON = DATA_DIR / "provider_health.json"
PROBE_CONFIG = ROOT / "scripts" / "probe_config.json"


def _run(cmd: list[str], check=False, timeout=120) -> tuple[int, str, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        logger.error("cmd falhou: %s\n%s", cmd, p.stderr[-300:])
    return p.returncode, p.stdout, p.stderr


def main() -> int:
    logger.info("=== benchmark_providers / curate_daily_light ===")

    # 1. Probe
    logger.info("Passo 1: provider health probe...")
    try:
        res = probe_run(
            config_path=PROBE_CONFIG,
            jsonl_path=PROVIDER_HEALTH_JSONL,
            aggregate_path=PROVIDER_HEALTH_JSON,
            alert=True,
        )
        alerts = res.get("alerts", [])
    except Exception as e:
        logger.exception("Probe falhou")
        send_telegram(f"⚠️ benchmark_providers probe falhou: {e}")
        return 2

    # 2. Commit + push
    logger.info("Passo 2: commit/push...")
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                            capture_output=True, text=True)
    dirty = [l for l in status.stdout.splitlines() if l.strip()]
    if dirty:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        _run(["git", "add", "data/provider_health.json", "data/provider_health.jsonl"])
        rc, _, err = _run(["git", "commit", "-m", f"health probe {ts}"])
        if rc == 0:
            rc, _, err = _run(["git", "push", "origin", "main"])
            if rc != 0:
                alerts.append(f"⚠️ push falhou: {err[-200:]}")
        else:
            if "nothing to commit" not in err.lower():
                alerts.append(f"⚠️ commit falhou: {err[-200:]}")
    else:
        logger.info("Nada a commitar.")

    logger.info("=== Resultado: %d alerta(s) ===", len(alerts))
    if alerts:
        send_telegram("🤖 benchmark_providers/curate_daily_light\n" + "\n".join(alerts))
        print("\n".join(alerts))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
