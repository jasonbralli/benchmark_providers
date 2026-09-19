# benchmark_providers

Monitoramento de saúde (health probe) dos providers de LLM usados pelo Hermes.

## Escopo
Este projeto contém APENAS o **health probe** — ping real em cada provider, agregação
de resultados, alertas por Telegram e histórico em JSONL.

O pipeline de consolidação de modelos vive em
[`benchmark_geral`](../benchmark_geral/) — este projeto é **autônomo** e fornece
`data/provider_health.json` (agregado) + `data/provider_health.jsonl` (histórico),
consumidos por `benchmark_geral` via subprocess.

## Estrutura

```
benchmark_providers/
├── benchmark_providers/
│   ├── __init__.py
│   └── probe_health.py        # probe atômico por provider
├── scripts/
│   ├── probe_health.bat       # wrapper scheduler → chama python -m benchmark_providers.probe_health
│   ├── probe_config.json      # providers/modelos a testar
│   └── curate_daily_light.py  # versão light do curate_daily: só probe + commit/push
├── tests/
│   └── test_probe_health.py
├── data/
│   ├── provider_health.json   # agregado (últimas 24h)
│   └── provider_health.jsonl  # histórico raw
└── docs/
    └── AUDITORIA_PROVIDERS_MODELOS_2026-09-19.md
```

## Setup

```bash
cd benchmark_providers
# stdlib only — nenhuma dependência de produção
pip install pytest  # apenas para testes
```

As chaves de API são lidas via `_read_env_key()` na ordem:

1. Variável de ambiente (`NVIDIA_API_KEY`, `OPENROUTER_API_KEY`, etc.)
2. `~/AppData/Local/hermes/.env`
3. `<cwd>/.env`

## Uso

```bash
# probe one-shot (padrão: scripts/probe_config.json → data/provider_health.json)
python -m benchmark_providers.probe_health

# ou via .bat (usado pelo Task Scheduler)
scripts\probe_health.bat

# custom paths
python -m benchmark_providers.probe_health --config scripts/probe_config.json \
    --out data/provider_health.jsonl --aggregate data/provider_health.json

# sem enviar alertas Telegram
python -m benchmark_providers.probe_health --no-alert
```

## Testes

```bash
pytest tests/ -v
```

## Versionamento

Repositório GitHub privado: `jasonbralli/benchmark_providers`.

## Relação com benchmark_geral

- **Este projeto** escreve `provider_health.json` e `provider_health.jsonl`.
- **`benchmark_geral`** consome via path absoluto configurável em
  `benchmark_pipe/build.py` (`HEALTH_FILE`) ou via subprocess de `probe_health`.
- `curate_daily.py` **full** vive em `benchmark_geral` e chama este probe via subprocess.
- `curate_daily_light.py` (aqui) é a versão enxuta para agendamento independente —
  faz probe + commit + push, sem pipeline de consolidação.
