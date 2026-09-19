# Decisão Recomendada — Uptime Kuma × NVIDIA AIPerf vs benchmark_providers

**Data:** 19/09/2026
**Status:** aprovado para implementação futura (não urgente)
**Contexto completo:** skill `benchmark-geral-automation` → seção "Ferramentas externas avaliadas 19/09/2026"

---

## Estratégia

| Ação | Uptime Kuma | NVIDIA AIPerf |
|---|---|---|
| **Absorver no código** | ❌ Não — escopo divergente (uptime genérico de sites, não métricas LLM) | ⚠️ Só 2 ideias: TTFT via streaming + percentil P95 no agregado |
| **Instalar em paralelo** | ✅ Só se precisarmos monitorar **sites** (peruibe455.com, inovatudo.com, Hospedin) — serviço Docker à parte | ✅ Só quando benchmarkarmos o **llama-server local sob carga real** (complementa `llama-bench`, que é single-stream) |

## Checklist de absorção (quando houver tempo)

### Probe (`benchmark_providers/probe_health.py`)

- [ ] Adicionar flag `stream: true` na request da probe e medir **TTFT** (tempo até o primeiro chunk)
  - Salvar em `provider_health.jsonl` como campo novo `ttft_ms`
  - Não quebra nada: campo opcional, ausente em probes antigas
- [ ] Agregador: adicionar **P95** na lista de percentis (hoje P50/P99)
  - `provider_health.json` agregado expõe `p50_ms / p95_ms / p99_ms`
- [ ] Atualizar `tests/test_probe_health.py` com casos novos
- [ ] Atualizar template do `benchmark_geral` para renderizar P95 e TTFT quando disponíveis

### Quando instalar em paralelo

| Ferramenta | Trigger | Como |
|---|---|---|
| **Uptime Kuma** | Quando assumirmos monitoramento de site em produção (pousada ou InovaTudo) | `docker run -d -p 3001:3001 louislam/uptime-kuma` em VPS ou PC local; configurar Telegram apontando para o mesmo bot do Hermes |
| **AIPerf** | Quando formos benchmarkar `llama-server` do Ornith/Qwen sob carga concorrente (não apenas 1 stream) | `uv tool install aiperf` + `aiperf profile --model ... --endpoint-type chat --streaming --arrival-pattern poisson --request-rate N`; comparar com `llama-bench` |

## O que NÃO absorver

- Padrões Poisson/gamma/ramp do AIPerf → probe é 1x/dia, não stress test
- GPU telemetry DCGM → fora do escopo (probe mede providers REMOTOS)
- 95+ canais do Uptime Kuma → nosso Telegram já resolve
- Status pages públicas do Kuma → não precisamos (não temos SLA público)

## Achados adicionais — artigo GenAI-Perf (NVIDIA, mai/2025, antecessor do AIPerf)

Mesmo tema do AIPerf, mas com nuggets operacionais ausentes no artigo novo:

| Técnica | Onde aplicar |
|---|---|
| `ignore_eos:true` + `min_tokens:N` | Força o servidor a emitir N tokens reais — sem isso OSL vira "desejo" e throughput sai inflado. Aplicar em benchmarks locais. |
| `--measurement-interval 30000` | Só conta requests que FINALIZAM na janela — evita contaminar média com timeouts cortados. |
| Warm-up antes de medir | Primeiro run aquece CUDA/JIT; descartar. Confirmado pelo doc oficial NIM. |
| Sweep baseline por use case | Translation 200/200, Classification 200/5, Summary 1000/200, Code 200/1000 × concurrency {1,2,5,10,50,100,250}. Usar esses ISL/OSL para resultados comparáveis ao NIM oficial. |
| Curva TTFT × RPS | Plot X=TTFT, Y=RPS, 1 ponto por concurrency. Identifica o "knee" onde latência explode sem ganho de throughput. Candidata a visualização futura no `benchmark_local`. |
| Artefatos organizados | `artifacts/<modelo>-openai-chat-concurrency<N>/<ISL>_<OSL>.{json,csv}` + `inputs.json` — padrão limpo a emular. |
| `--tokenizer <repo HF>` | Necessário para contar tokens corretamente; repos gated (Llama) precisam de `huggingface-cli login` antes. |

## Decisão final

**Nenhum dos dois substitui o probe atual.** Mantemos `benchmark_providers` como está, absorvemos apenas TTFT-streaming + P95, e instalamos AIPerf e/ou Kuma **à parte** apenas se/quando os triggers acima dispararem.
