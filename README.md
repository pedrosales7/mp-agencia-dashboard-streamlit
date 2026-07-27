# MP Agência — Funil Ads-to-Sale (Streamlit)

App Streamlit com a mesma lógica de negócio do dashboard HTML original (`mp-agencia-dashboard`), reescrito para visualização mais rica (Plotly) e filtros que de fato reprocessam os dados, mantendo refresh só semanal (sem query ao vivo) para ficar no free tier do Streamlit Community Cloud.

**App ao vivo:** https://mp-agencia-dashboard-app.streamlit.app/
**Repo:** [`pedrosales7/mp-agencia-dashboard-streamlit`](https://github.com/pedrosales7/mp-agencia-dashboard-streamlit) (público, conta pessoal `pedrosales7`)
**Projeto irmão:** [`mp-agencia-dashboard`](https://github.com/pedrosales7/mp-agencia-dashboard) — dashboard HTML original, ainda ativo em paralelo (fonte de verdade para comparar layout/features quando ele ganha commits novos)

Handoff técnico detalhado de sessão para sessão vive em [`HANDOFF.md`](HANDOFF.md) — ler antes de continuar qualquer trabalho neste projeto.

---

## 1. Contexto de negócio

**MP Agência** é a linha de receita da Melhor Plano que opera como agência de performance de mídia paga vertical para **provedores regionais de internet (ISPs)** — os "partners". Modelo: pacote fixo mensal, 100% investido em mídia, sem fee, com **cashback de reinvestimento** quando um lead de um partner fecha com outro provedor (fora da área de cobertura do anunciante).

**8 partners:** `loga-internet`, `the fiber internet`, `interplus internet`, `direct internet`, `enove-fibra`, `unifique`, `ultranet-network`, `ativa-telecom`.

**2 canais:**
- **Google Ads** — funil `impressões → cliques → sessões → clickoff → redirect → leads → vendas`
- **Meta Ads** (click-to-WhatsApp) — funil `impressões → cliques → chat_start → zip_search → redirect → leads → vendas`

Owner do produto/coordenação: **Pedro Ribeiro Sales**.

## 2. Regras de negócio (idênticas ao dashboard HTML — não revisitar sem motivo)

| Regra | Definição |
|---|---|
| **Atribuição** | Lead e venda sempre atribuídos ao **anunciante**, nunca ao recebedor |
| **Venda** | `current_situation IN ('sold','installed','scheduled')` |
| **Lead produtivo** | `source IN ('google','whatsapp') AND lead_accepted = true` |
| **Excluídos** | `whatsapp:paid` e Desktop — não são MP Agência |
| **CPL / CAC** | Sempre sobre **investimento líquido** (bruto − cashback) |
| **Cutoff** | `date.today() - 1` sempre (nunca o dia corrente — dados parciais); calculado tanto no refresh (`weekly_refresh.py`) quanto derivado dos próprios dados em `data.py` |

**Armadilha crítica:** `label_map`/`id_mp_canon` pode ter 2 linhas por partner — `scripts/queries.sql` já usa `SELECT DISTINCT`. Não remover se mexer nessas queries.

## 3. Arquitetura

### Por que não tem cache/merge como o dashboard HTML

O HTML original precisa de `data/cache/historical_data.json` porque a página carrega histórico "para sempre" incrementalmente. Aqui não: as 5 queries do Metabase já trazem janela larga o suficiente numa passada só —

| Query | Janela |
|---|---|
| `DAILY_SNAPSHOT`, `DAILY_FUNNEL_GOOGLE`, `DAILY_FUNNEL_META` | 180 dias |
| `PARTNER_WEEKLY` | ~95 dias |
| `CREDIT_TIMESERIES` | 70 dias (fixo) |

`scripts/weekly_refresh.py` roda essas 5 queries **sem cache/merge** e grava tudo cru em `data/latest.json`. Toda agregação (funil por período — 7d/30d/90d/mês/custom, cobertura, progressão, taxas) é feita **em pandas dentro do app** (`data.py`), filtrando as séries cruas pela janela pedida. Isso elimina a necessidade de janelas pré-computadas por `period_key`, `PREV_FUNNEL_*` e todo o cache. Ganho extra: "Δ vs período anterior" é cálculo real sobre janela anterior de mesmo tamanho (`data.previous_window()`), não estimativa.

### 3 abas sobre o mesmo snapshot

`app.py` é só o roteador. Nenhuma query ao vivo ao Metabase acontece dentro do app — só o refresh semanal no GitHub Actions.

| Aba | Arquivo | Chama LLM em runtime? |
|---|---|---|
| 📊 Dashboard | `dashboard_view.py` | não — puro pandas sobre `data/latest.json` |
| 🤖 Análise da semana | `analysis_view.py` | **não** — lê texto já pronto de `data/analysis.json` |
| 💬 Perguntar aos dados | `chat_view.py` | **sim** — Gemini a cada mensagem |

**A separação é de custo/segurança, não estética.** O app e o repo são públicos. A análise é gerada 1×/semana dentro do GitHub Actions e o app só renderiza texto pronto (zero exposição de custo). O chat é a única porta que gasta cota em runtime — por isso a proteção real é o controle de acesso do Streamlit Community Cloud (lista de e-mails autorizados, em Settings → Sharing); o teto de 15 mensagens por sessão em `chat_view.py` é segunda linha de defesa, não a primeira.

## 4. Dados (`scripts/queries.sql`, `scripts/weekly_refresh.py`)

Mesmo Metabase/Redshift do dashboard HTML (`database_id=69`), mas só 5 das 9 queries do arquivo original são usadas (as que trazem janela larga o suficiente — ver tabela acima). `weekly_refresh.py` grava direto em `data/latest.json`, sem transformação de merge.

## 5. Análise IA — pipeline em 3 estágios (`scripts/ai_analysis.py`)

Diferente do dashboard HTML (que usa um único prompt/chamada), aqui a análise é dividida em estágios para controlar custo e evitar alucinação:

| Estágio | O que faz | LLM? |
|---|---|---|
| **0 — Triagem** | Calcula anomalias, gargalos de funil, tendências — puro Python | não |
| **1 — Diagnóstico** | Gera diagnóstico estruturado (`responseSchema` do Gemini), thinking alto | sim |
| **2 — Redação** | Escreve a prosa final em tags XML, thinking baixo | sim |

O estágio 2 **não recebe o payload de números cru** de propósito — sem os dados na mão, recitar o dashboard fica impossível, e todo número que aparece na prosa final é conferido contra `evidencias_citadas` na validação (anti-alucinação).

O diagnóstico do estágio 1 é salvo em `data/diagnosticos/AAAA-MM-DD.json` — vira entrada do estágio 2 da semana seguinte (permite o modelo dizer "recomendei X na semana passada, não foi implementado ainda") e serve como registro auditável.

`build_context()` é separado de `run()`: o payload + triagem (estágio 0) é puro cálculo, sempre grava `data/ai_context.json`, e esse mesmo arquivo é o contexto usado pela aba de chat. Assim o chat sobrevive a uma falha da análise (estágios 1/2).

**Modelo:** Gemini via Google AI Studio, `gemini-3.1-pro-preview` como default (`chat_view.py`); `LLM_MODEL` (variable do repo) sobrescreve.

**`LLM_API_KEY` precisa estar configurada em DOIS lugares, com escopos diferentes:**
- **secret do repositório** (GitHub Actions) → o refresh gera a análise semanal
- **secret do app** (share.streamlit.io → Settings → Secrets) → a aba de chat funciona em runtime

Sem o primeiro, o refresh roda e pula a análise (sem erro). Sem o segundo, a aba de chat mostra instrução de configuração em vez de quebrar.

## 6. Stack e conectores

| Camada | Tecnologia |
|---|---|
| App | Streamlit ≥1.36, tema fixo `base="light"` (ver Gotchas) |
| Visualização | Plotly ≥5.20, tabelas HTML densas via `st.components.v1.html` (sort por clique no cabeçalho) |
| Dados | pandas ≥2.0, `data/latest.json` como única fonte de verdade |
| Análise IA / Chat | Gemini (Google AI Studio), `requests` |
| Automação | GitHub Actions (`weekly-refresh.yml`, cron terça 8:52 BRT — 15min depois do refresh do HTML original, para não bater os dois no Metabase junto) |
| Deploy | Streamlit Community Cloud |
| Notificação | Slack Incoming Webhook (mesmo app "Bot MP Agência") |

**Secrets do GitHub Actions:** `METABASE_URL`, `METABASE_USERNAME`, `METABASE_PASSWORD`, `SLACK_WEBHOOK_URL`, `SLACK_WEBHOOK_URL_TEST`, `LLM_API_KEY`
**Variables do repo:** `STREAMLIT_URL`, `LLM_MODEL`

## 7. Estrutura de arquivos

```
app.py                    # roteador das 3 abas — só isso
dashboard_view.py         # layout, filtros, todas as seções do dashboard
analysis_view.py          # renderiza data/analysis.json (sem chamar LLM)
chat_view.py              # aba de chat — única que chama Gemini em runtime
data.py                   # carrega data/latest.json, build_*_df, formatação/delta/outlier — fonte de verdade dos dados
tables.py                 # monta tabelas HTML densas (status dot, sparkline inline, sort por header)
style.py                  # CSS do tema "Sinalização" (light-only, ver Gotchas)
scripts/weekly_refresh.py # GitHub Actions: Metabase → data/latest.json (+ dispara ai_analysis)
scripts/ai_analysis.py    # pipeline de 3 estágios (triagem, diagnóstico, redação)
scripts/queries.sql       # cópia do original; só 5 das 9 queries usadas
scripts/generate_mock_data.py  # gera dado fake no schema real, sem precisar de credencial Metabase
data/latest.json          # snapshot semanal cru (5 queries, sem merge)
data/ai_context.json       # payload + triagem — contexto do chat e insumo da análise
data/analysis.json        # texto final da análise semanal
data/diagnosticos/AAAA-MM-DD.json  # diagnóstico estruturado por semana (auditoria + memória do prompt)
.github/workflows/weekly-refresh.yml
.streamlit/config.toml    # tema fixo light
```

## 8. Rodar localmente

```bash
cd /Users/pedro/Claude/Projects/mp-agencia-dashboard-streamlit
source .venv/bin/activate   # ou: python3 -m venv .venv && pip install -r requirements.txt
streamlit run app.py
```

Sem credencial do Metabase, gerar dado fake no schema real:
```bash
python scripts/generate_mock_data.py
```

Disparar refresh manual em modo teste (Slack vai só pro DM, sem `@channel`):
```bash
gh workflow run "Weekly Dashboard Refresh (Streamlit)" --repo pedrosales7/mp-agencia-dashboard-streamlit -f test_mode=true
```

## 9. Gotchas / decisões que não devem ser revisitadas sem motivo

1. **Tema é light-only, de propósito.** `.streamlit/config.toml` está fixado em `base="light"`; uma versão anterior tinha CSS reativo a dark mode que quebrava os KPIs (texto escuro em fundo escuro) por mismatch com o tema fixo do Streamlit. Dark mode real exigiria mexer em `config.toml` **e** `style.py` juntos.
2. **`fmt_brl` trata NaN/Infinity como "—"** — sem isso aparece "R$ nan"/"R$ inf" quando cliques ou vendas = 0 na janela (divisão por zero vetorizada do pandas não gera erro, gera NaN/Inf silencioso).
3. **Streamlit Cloud às vezes fica com cache velho depois de um push.** Código 100% correto no GitHub mas o app ao vivo dá erro (`AttributeError`/`TypeError`) até um **reboot manual** (share.streamlit.io → app → "⋮" → Reboot app). Testar isso antes de assumir bug de código, principalmente após pushes em sequência rápida.
4. **Widgets custom do Streamlit** (`st.multiselect`, `st.segmented_control`) não respondem a cliques sintéticos simples em automação de browser — precisa de sequência completa de eventos de mouse (pointerdown/mousedown/pointerup/mouseup/click) ou, no multiselect, `ArrowDown` antes do `Enter`.
5. **Sort por clique no header** usa `st.components.v1.html` (iframe) em vez de `st.markdown` nas 3 tabelas densas — não herda CSS da página (injetado junto no doc do iframe) e não cresce com o conteúdo (altura calculada manualmente em `sortable_table_height()`, constantes `ROW_H_FUNNEL=42`/`ROW_H_PLAIN=30` medidas no browser — remedir se mexer no layout da célula).
6. **Análise IA nunca rodou ponta a ponta com validação humana** do texto gerado pelos estágios 1/2 — encanamento, validação e render foram testados com dado real, mas o conteúdo textual em si ainda não foi revisado por ninguém.

## 10. Próximos passos / pendências conhecidas

- Seletor de partner inline sincronizado entre seções (parcialmente portado — ver HANDOFF.md)
- Validação humana do texto gerado pela análise IA (nunca revisado, item 6 acima)
- Ajustes de usabilidade/estética sob demanda — não presumir escopo, perguntar antes de mexer

## 11. Contexto adicional / memória entre sessões

- Handoff técnico completo (arquitetura, decisões, histórico de sessão): [`HANDOFF.md`](HANDOFF.md) — ler sempre antes de continuar trabalho aqui
- Schema/definições de negócio do Data Warehouse: `outputs/mp-data-context/SKILL.md` na pasta `Dashboard-CodeVersion` (projeto irmão)
- Nota de projeto no Obsidian: `~/Claude/Projects/Obsidian/01-Projects/Dashboard-CodeVersion/Dashboard-CodeVersion.md`
