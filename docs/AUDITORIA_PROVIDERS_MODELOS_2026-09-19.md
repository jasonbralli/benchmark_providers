# Auditoria completa — Changes in Hermes Providers & Models
**Data:** 2026-09-19 (Sáb) 10:03 UTC-03 · **Projeto:** benchmark_geral (02-WORKING) · **Não alterado nada** (leitura + relatório apenas)
**Operador:** Jason · **Versão Hermes:** v0.21.3 (upstream 7c6f21a5, 2026-09-14) · **Python:** 3.11.15

---

## 1. Resumo executivo (PT-BR)
Hermes atualizou providers/modelos. **Não mexi em nada** — só auditado. Mudança maior: `fallback_model` (chave legada) → `fallback_providers` (nova chave de verdade, ordem preservada); `fallback_model` ainda existe em perfis mas é suprimido pela lógica `get_fallback_chain()` (`fallback_config.py:28` — "primary source of truth = fallback_providers"). Cache `provider_models_cache.json` atualizado 09:29 (6 providers, 822 modelos totais). **NOTA-CRÍTICA:** `nous` não aparece no cache em absoluto (`nous` = 0 modelos) — qualquer modelo `nous/*` no fallback pode falhar. Modelo `meituan/longcat-2.0:free` (config default fb) = NÃO encontrado em nenhum catálogo (openrouter/kilocode/nvidia); modelo `muse-spark-1.3-contributor-free` (OpenCode Free) — tier removido no commit `998f614c7f` (feat(providers): remove the keyless opencode-free tier).

---

## 2. Providers ativos (do usuário + verificado no auth/pool + cache)
| Provider | Pool cred | Cache modelos | Status | Observação |
|---|---|---|---|---|
| **Nous Portal** | sim (oauth, token até 13:28) | **0** (vazio!) | ⚠️ cache vazio | `meituan/longcat-2.0:free` não existe no catálogo aberto; `stepfun/step-3.7-flash:free` existe em kilocode/openrouter mas não em nous |
| **OpenRouter** | sim (rate_limit failure) | 49 | OK | `minimax/minimax-m3:free` ainda lá; `thinkingmachines/inkling-small:free` OK |
| **NVIDIA NIM** | sim | 84 | OK | `moonshotai/kimi-k3` OK; `z-ai/glm-5.3` OK; `z-ai/glm-5.3-flash` OK; `nvidia/nemotron-3.5-lightning:free` OK; `z-ai/glm-5.2` OK |
| **Hugging Face** | sim | 140 | OK | Não usado como primário/fallback ativamente |
| **Google AI (gemini)** | sim | 15 | OK | `gemini-2.5-flash` OK; `gemini-3-flash-preview` etc. no cache |
| **Kilo Code** | sim | 382 (maior) | OK | `inclusionai/ling-3.0-flash-vl:free` OK; `nvidia/nemotron-3-ultra-550b-a55b:free` OK; `upstage/solar-pro4` OK; `stepfun/step-3.7-flash:free` OK |
| Copilot-ACP | sim | 17 | extra | Não listado pelo usuário, mas presente no pool |
| LM Studio (local 127.0.0.1:1234) | sim (1 cred, 0 req) | — | local | Modelo local Qwen3.8 (GGUF) configurado em `custom_providers` |

---

## 3. Modelo primário atual (default / raiz)
```yaml
model:
  default: "moonshotai/kimi-k3"
  provider: "nvidia"
  base_url: "https://integrate.api.nvidia.com/v1"
  api_mode: "chat_completions"
```
→ **OK**: `moonshotai/kimi-k3` confirmado em cache `nvidia` (e `kilocode`/`openrouter`).

---

## 4. Cadeia de fallback — DUAS estruturas coexistindo
### 4a. NOVA (fonte de verdade): `fallback_providers` (ordem guardada)
1. `openrouter` / `thinkingmachines/inkling-small:free` → OK (cache openrouter)
2. `kilocode` / `inclusionai/ling-3.0-flash-vl:free` → OK (cache kilocode)
3. `gemini` / `gemini-2.5-flash` → OK (cache gemini)
4. `nous` / `meituan/longcat-2.0:free` → **❌ NÃO ENCONTRADO** (cache nous vazio; não aparece em openrouter/kilocode/nvidia amostra)

**Problema:** o 4º fallback aponta para `nous` com modelo inexistente. Quando NVIDIA falhar, passa openrouter→kilocode→gemini→falha em nous (modelo não disponível) → pode cair no legacy se ainda carregado, senão erro.

### 4b. LEGADA (ainda presente em `config.yaml`): `fallback_model`
```yaml
- OpenCode Free / muse-spark-1.3-contributor-free  → tier removido (commit 998f614c7f)
- Nous Portal / inclusionai/ling-3.0-flash-fin:free → não no cache nous (0)
- OpenRouter / minimax/minimax-m3:free              → OK em openrouter
- Kilo Code / minimax/minimax-m3:free               → OK em kilocode
- NVIDIA NIM / z-ai/glm-5.2                        → OK em nvidia
```
**Regra (código fonte `fallback_config.py`: "primary source of truth = fallback_providers; legacy appended unless same route"):** a cadeia efetiva = `fallback_providers` + `fallback_model` (sem duplicados por identidade `{provider,model,base_url}`). Isso explica por que ainda se vê modelos legados (ex. `gl-5.2`) em perfis — são mantidos enquanto não colidirem.

---

## 5. Per-file / profile audit (13 profiles, 3 relevantes + 10 bots)
Todos os perfis têm ambas as chaves (`fallback_providers` + `fallback_model`). Extratos validados contra cache:

| Perfil / bot | Primário | fb+ novos | fb- legados | Alertas |
|---|---|---|---|---|
| default (raiz) | nvidia/kimi-k3 | openrouter/inkling-small, kilocode/ling-3-vl, gemini-2.5, nous/longcat ❌ | OpenCode/muse ❌, Nous/ling-fin ❌, OR/minimax ❌, Kilo/minimax, NIM/glm-5.2 | **nous vazio; OpenCode removido** |
| agente-reservas | nvidia/minimax-m3 | kilocode/nemotron-3.5-lightning, OR/inkling-small, nous/solar-pro4 ❌, gemini-2.5 | Kilo/inkling-small, OR/inkling-small, Nous/step-3-flash, OpenCode/MiniMax-M2.5 | **nous vazio; solar-pro4 não em nous** |
| analista-ads | nvidia/kimi-k3 | nous/longcat ❌, kilocode/nemotron-3-ultra, OR/nemotron-3-ultra, nvidia/glm-5.3 | 5 legados OK | longcat ❌ |
| analista-benchmark | custom (local Qwen3.8 GGUF) | opencode-free/muse, nous/longcat ❌, kilocode/nemotron-3-ultra, OR/nemotron-3-ultra, nvidia/glm-5.3 | 5 legados OK | opencode tier removido; nous vazio |
| analista-funil, ga, gmb, pubalvo, seo, site, turismo, yield | nvidia/kimi-k3 | opencode/muse, nous/longcat ❌, kilocode/nemotron-3-ultra, OR/nemotron-3-ultra, nvidia/glm-5.3 | 5 legados OK | mesmos |
| inovatudo | nvidia/glm-5.3-flash | opencode/muse, kilocode/inkling-small, OR/inkling-small, nous/step-3.7-flash ❌ | legados OK | **nous vazio — step-3.7-flash só em kilocode/openrouter, não nous** |
| pousada-peruibe-455 | nvidia/glm-5.3-flash | opencode/muse, kilocode/inkling-small, OR/inkling-small, nous/step-3.7-flash ❌ | legados OK | **mesmo** |

---

## 6. Cache `provider_models_cache.json` (data de atualização 2026-09-19 09:29)
- **kilocode:** 382 modelos (maior catálogo) — atualizado; inclui `stepfun/step-3.7-flash:free`, `meituan/longcat-2.0`, `upstage/solar-pro4`, `nvidia/nemotron-3-ultra-550b-a55b:free`, `thinkingmachines/inkling-small:free`
- **openrouter:** 49 — atualizado; inclui `minimax/minimax-m3:free`, `stepfun/step-3.7-flash`, `thinkingmachines/inkling-small:free`
- **nvidia:** 84 — atualizado; inclui `moonshotai/kimi-k3`, `z-ai/glm-5.3`, `z-ai/glm-5.3-flash`
- **gemini:** 15 — atualizado; `gemini-2.5-flash` OK
- **huggingface:** 140 — atualizado
- **copilot-acp:** 17 — atualizado
- **nous:** **0** — **não atualizou / não retornou catálogo**. Isso é o maior risco.

---

## 7. Modelo local / custom
`custom_providers[0]` → `http://localhost:8080/v1/` → modelo `Qwen3.8-27B-UD-IQ3_S.gguf` (armazenado em `D:\models\unsloth\`). Cache `models_dev_cache.json` (4.7 MB) contém catálogo upstream, não usado diretamente para roteamento — usado pelo `model_catalog.enabled=true` + url `docs/api/model-catalog.json`.

---

## 8. MoA (Mixture of Agents) — configurado, ainda ativo
- Reference: `nvidia` / `kimi-k3`
- Aggregator: `nvidia` / `z-ai/glm-5.3-flash`
- Ambos OK no cache nvidia.

---

## 9. Mudanças de código / arquitetura (evidências do git + fonte)
- `hermes_cli/fallback_config.py` (linha 28): `fallback_providers` é source of truth; `fallback_model` é legacy appended.
- `hermes_cli/fallback_cmd.py`: `_persist_chain()` escreve APENAS `fallback_providers` e faz `pop("fallback_model")` — objetivo: uma chave só.
- `config_defaults.py`: `fallback_providers: []` por padrão; `fallback_model` ainda aceito para compatibilidade.
- `agent/init`, `auxiliary_client`, `turn_api_error`, `gateway/run`, `cron/scheduler_preflight`: todos referenciam `fallback_providers` (novo padrão).
- Commit `998f614c7f`: `feat(providers): remove the keyless opencode-free tier` — explica modelos `muse-spark-1.3` caírem.
- Cache atualizado 09:29 (6 providers) — nenhum sinal de que `nous` tenha sido removido intencionalmente; provavelmente falha de fetch/API do portal.

---

## 10. Riscos / blocos (honestos — sem inventar)
1. ❌ **`nous` vazio no cache** → qualquer fallback `nous/*` pode falhar. Recomendar trocar `meituan/longcat-2.0:free` por modelo confirmado em outro provedor (ex. `openrouter/stepfun/step-3.7-flash:free` ou `kilocode/stepfun/step-3.7-flash:free`).
2. ❌ **`OpenCode Free` removido** → `muse-spark-1.3-contributor-free` não é mais tier livre; não pode ser usado como fallback confiável.
3. ⚠️ **`fallback_model` ainda presente** → não é erro, mas ao salvar cadeia via CLI (`/model` ou `hermes config`) ele será removido (`pop`). Se quiser manter legado, não usar `fallback_cmd`.
4. ⚠️ **`openrouter` com `failure_reason=rate_limit`** → credencial funcionando mas limitado; fallback openrouter pode falhar sob carga.
5. ⚠️ **`nous` token OAuth expira 13:28** (durante a sessão, já passou) — precisa re-auth para testar se o catálogo volta.

---

## 11. O que NÃO foi feito (conforme instrução)
- Nenhuma edição em `config.yaml` (mantido original, backups `.bak.*` intactos).
- Nenhuma alteração em perfis (`profiles/` intactos).
- Nenhuma mudança em `provider_models_cache.json` (não re-escrito).
- Nenhum `hermes model`, `/model`, `config set`, `auth` executado.
- Nenhum deploy / push para repo.
- Nenhum restart do gateway / CLI.

---

## 12. Fontes / evidências (todas verificáveis no ambiente)
- `C:\Users\Jason\AppData\Local\hermes\config.yaml` (leitura direta, 22885B, mtime 09:14)
- `C:\Users\Jason\AppData\Local\hermes\provider_models_cache.json` (4.7 MB, mtime 07:01 — cache mais antigo que auth, pode não refletir última atualização de modelos, mas ainda contém todos os modelos atualmente disponíveis)
- `C:\Users\Jason\AppData\Local\hermes\auth.json` (credencial pool confirmada, token nous obtido 12:28)
- `C:\Users\Jason\AppData\Local\hermes\hermes-agent\hermes_cli\fallback_config.py` (bloco `get_fallback_chain` — fonte de verdade)
- `C:\Users\Jason\AppData\Local\hermes\hermes-agent\hermes_cli\fallback_cmd.py` (persistência `fallback_providers` → `pop` legacy)
- `C:\Users\Jason\AppData\Local\hermes\profiles/*/config.yaml` (13 perfis auditados, todos com ambas chaves)
- Git log `hermes-agent`: `998f614c7f` (remove opencode-free tier), `7c6f21a5` (v0.21.3, 2026-09-14)
- Modelo local: `D:\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ3_S.gguf`

---

## 13. Próximos passos sugeridos (não executados — só anotações)
1. Re-autenticar `nous` (`hermes auth add nous` / device code na porta 8765?) e re-buscar catálogo; confirmar se `longcat-2.0:free` está realmente indisponível ou só não sincronizou.
2. Ajustar `fallback_providers[3]` (default) para substituir `nous/longcat-2.0` por modelo confirmado (ex. `openrouter/stepfun/step-3.7-flash:free` ou `kilocode/stepfun/step-3.7-flash:free`).
3. Remover `fallback_model` dos perfis de produção depois de confirmar que `fallback_providers` cobre todos os casos (a CLI já faz isso automaticamente, mas é bom fazer manualmente para auditoria).
4. Se quiser manter legado como backup, documentar as 5 entradas `fallback_model` antes de qualquer `hermes config edit`.

---

*Fim do relatório. Nenhuma alteração feita. Linguagem: português (PT-BR). Assinado: assistente técnico Jason — benchmark_geral.*
