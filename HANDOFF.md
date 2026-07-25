# Handoff — MP Agência Dashboard (Streamlit)

Documento de continuidade pra próxima sessão. Contexto: migração do dashboard
HTML estático (`mp-agencia-dashboard`, GitHub Pages) pra um app Streamlit,
mantendo refresh só semanal (sem query ao vivo) pra ficar no free tier.

**Última atualização:** 2026-07-24, sessão que levou o projeto do zero até em
produção com paridade quase completa do HTML original.

## Links

- **App ao vivo:** https://mp-agencia-dashboard-app.streamlit.app/
- **Repo deste projeto:** https://github.com/pedrosales7/mp-agencia-dashboard-streamlit (público, conta `pedrosales7`)
- **Dashboard HTML original (referência):** https://github.com/pedrosales7/mp-agencia-dashboard — `docs/index.html`
  é a fonte de verdade pra comparar layout/features. Clone local em
  `/Users/pedro/Claude/Projects/Dashboard-CodeVersion/mp-agencia-dashboard/`.
- **Pasta local deste projeto:** `/Users/pedro/Claude/Projects/mp-agencia-dashboard-streamlit/`

## Status — tudo em produção

| Fase | Status |
|---|---|
| Setup do repo | ✅ |
| Pipeline de dados (`weekly_refresh.py`, sem estado) | ✅ testado contra Metabase real via MCP |
| App Streamlit (10 seções) | ✅ |
| GitHub Actions (refresh terça 8:52 BRT) | ✅ testado com `test_mode=true` |
| Deploy Streamlit Community Cloud | ✅ |
| Paridade com mudanças recentes do HTML | ✅ (ver seção abaixo) |

## Arquitetura (por que é diferente do HTML original)

O HTML original (`weekly_refresh.py` de lá) precisa de cache (`data/cache/historical_data.json`)
porque a página final carrega histórico pra sempre. Aqui não: as queries do
Metabase já trazem janela larga o suficiente numa passada só —

- `DAILY_SNAPSHOT`, `DAILY_FUNNEL_GOOGLE`, `DAILY_FUNNEL_META`: 180 dias
- `PARTNER_WEEKLY`: ~95 dias (ampliado de 70 no original)
- `CREDIT_TIMESERIES`: 70 dias (fixo na query)

`scripts/weekly_refresh.py` roda essas 5 queries **sem cache/merge** e grava tudo
cru em `data/latest.json`. Todo o resto — funil por período (7d/30d/90d/mês/
customizado), cobertura, progressão, taxas — é **agregação em pandas dentro do
app** (`data.py`), filtrando essas séries cruas pela janela pedida. Isso elimina
a necessidade das janelas `FUNNEL_GOOGLE/META` por `period_key`, `PREV_FUNNEL_*`
e o cache inteiro que o script original tem.

Ganho de brinde: "Δ vs período anterior" é cálculo real (janela anterior de
mesmo tamanho via `data.previous_window()`), não estimativa.

## Arquitetura de abas (desde 2026-07-24)

O app virou hub de 3 abas sobre o MESMO snapshot. `app.py` é só o roteador.

| Aba | Arquivo | Chama LLM em runtime? |
|---|---|---|
| Dashboard | `dashboard_view.py` | não |
| Análise da semana | `analysis_view.py` | **não** — lê `data/analysis.json` |
| Perguntar aos dados | `chat_view.py` | **sim** — Gemini a cada mensagem |

**A separação não é estética, é de custo/segurança.** O app é público e o repo
também. A análise é gerada 1x/semana dentro do GitHub Actions e o app só
renderiza texto pronto — zero exposição. O chat é a única porta que gasta cota
em runtime, e por isso o controle de acesso do Community Cloud (lista de
e-mails, em Settings → Sharing) é o que de fato protege; o teto de 15 mensagens
por sessão no `chat_view.py` é segunda linha, não a primeira.

`LLM_API_KEY` precisa estar em DOIS lugares, com escopos diferentes:
- secret do **repositório** → o refresh gera a análise semanal
- secret do **app** (share.streamlit.io) → o chat funciona

Sem o primeiro, o refresh roda e pula a análise. Sem o segundo, a aba de chat
mostra como configurar em vez de quebrar.

### Pipeline da análise (`scripts/ai_analysis.py`)

Estágio 0 (triagem) é Python puro; 1 (diagnóstico, `responseSchema`, thinking
alto) e 2 (redação, tags XML, thinking baixo) são Gemini. O estágio 2 **não
recebe o payload** de propósito: sem números crus na mão, recitar o dashboard
fica impossível, e todo número da prosa é conferido contra
`evidencias_citadas` na validação.

O diagnóstico vai pra `data/diagnosticos/AAAA-MM-DD.json` — entrada do estágio
2 da semana seguinte (bloco "recomendei X, não mexeu") e registro auditável.

`build_context()` é separado do `run()`: o payload+triagem é puro cálculo, vai
pra `data/ai_context.json` sempre, e é também o contexto do chat. Assim o chat
sobrevive a uma falha da análise.

**Nunca rodou ponta a ponta.** Encanamento, validação e render foram testados
com dado real; o texto que os estágios 1 e 2 produzem ainda não foi visto por
ninguém. Rodar `-f test_mode=true` manda o resumo pro DM em vez do canal.

## Estrutura de arquivos

- **`app.py`** — roteador das 3 abas, só isso.
- **`dashboard_view.py`** — layout, filtros, todas as seções do dashboard. Widgets nativos do Streamlit
  (segmented_control, multiselect, date_input em modo intervalo, toggle, metric).
- **`data.py`** — carrega `data/latest.json`, todas as funções `build_*_df` e
  helpers de formatação/outlier/delta. **Fonte de verdade dos dados.**
- **`tables.py`** — monta as tabelas HTML densas (funil, cobertura, progressão,
  taxas) com ponto de status e sparkline inline — Streamlit não tem widget
  nativo pra isso, então é HTML puro via `st.markdown(unsafe_allow_html=True)`.
- **`style.py`** — CSS do tema "Sinalização" (rail colorido, pontos de status
  em vez de célula pintada inteira). **Light-only por decisão** (ver Gotchas).
- **`scripts/weekly_refresh.py`** — roda no GitHub Actions, Metabase → `data/latest.json`.
- **`scripts/queries.sql`** — cópia do original, mas só 5 das 9 queries são usadas.
- **`scripts/generate_mock_data.py`** — gera dado fake no schema real, pra testar
  sem credencial do Metabase (`python scripts/generate_mock_data.py`).
- **`.github/workflows/weekly-refresh.yml`** — cron terça 8:52 BRT (15min depois
  do refresh do HTML original, pra não bater os dois no Metabase junto).

## Rodar localmente

```bash
cd /Users/pedro/Claude/Projects/mp-agencia-dashboard-streamlit
source .venv/bin/activate   # venv já existe com streamlit/pandas/plotly/requests
streamlit run app.py
```

## Secrets do GitHub Actions (já configurados, nomes só)

`METABASE_URL`, `METABASE_USERNAME`, `METABASE_PASSWORD`, `SLACK_WEBHOOK_URL`,
`SLACK_WEBHOOK_URL_TEST` — configurados pelo Pedro diretamente (Claude não tem
acesso a credencial, nunca vai ter). Variável de repo `STREAMLIT_URL` já
aponta pro app live.

## Paridade com o dashboard HTML — o que foi trazido nesta sessão

O HTML original recebeu ~12 commits de feature nova que a versão Streamlit não
tinha (foi construída a partir de uma cópia mais antiga). Já sincronizado:

- KPI de Cashback no cabeçalho (com % do bruto)
- Removida seção "Detalhamento investimento × leads × vendas" (redundante,
  mesma decisão tomada no HTML)
- Removida seção "Crédito Remanescente por Parceiro" (idem, foi removida lá)
- Cobertura e Assertividade redesenhada: 1 linha por partner, Google/Meta como
  grupos de coluna lado a lado (cabeçalho 2 níveis), sem Bruto/Cashback
- Evolução das taxas: mostra contagem bruta ("3/4") em vez de "—" quando
  0 < denominador < 5
- "Comparar" agora afeta as tabelas de Funil completo também, não só os KPIs
  (deltas em pp nas colunas de etapa, % nas outras — mesma semântica do HTML)
- Ordenação nas tabelas de Funil completo (seletor "Ordenar por" + Asc/Desc —
  adaptação Streamlit-idiomática, já que não dá pra ter clique-no-cabeçalho
  numa tabela HTML estática sem JS)
- Nova seção "Evolução de métricas ao longo do tempo" (marcada "teste", igual
  no HTML): escolhe métrica (Lead→Venda/CPL/CAC combinados ou qualquer etapa
  do funil) + granularidade, plota 1 linha por partner selecionado
- Filtro de período customizado (`st.date_input` em modo intervalo — um único
  componente pra início+fim, diferente do HTML que usa 2 campos separados)

### Feito em 2026-07-24 (Pedro apontou os 5 buracos numa passada)

- **Ordenação por clique no cabeçalho** — as 3 tabelas densas (Funil Google,
  Funil Meta, Detalhamento) passaram de `st.markdown` para
  `st.components.v1.html`, que permite `<script>`. Os selectbox "Ordenar por"
  + Desc/Asc foram removidos (o Pedro não entendia o que eram — apareciam como
  dropdown solto sem label). Cada `<td>` carrega `data-sort` com o valor cru,
  porque "R$ 2.780" e "84,8%" não ordenam como número; a linha TOTAL tem
  `data-pin="1"` e fica fixa no fim; célula sem base ordena por último nos dois
  sentidos. Nas colunas de etapa o `data-sort` é a TAXA, não o volume — é o que
  a coluna comunica.
  Custo do iframe: não herda o CSS da página (vai injetado junto em
  `sortable_doc`) e não cresce com o conteúdo, então a altura é calculada em
  `sortable_table_height()` — as constantes `ROW_H_FUNNEL=42` / `ROW_H_PLAIN=30`
  foram medidas no browser. Mexeu no layout da célula, remede.
- **Outlier vs. mediana virou célula pintada** (`td.bad` / `td.good`, cores
  `#fef2f2` / `#f0fdf4` — as mesmas do HTML). A lógica sempre existiu e estava
  certa; o que não dava era enxergar, porque o tema "Sinalização" renderizava
  como um ponto de 6px. Isso reverte parcialmente aquela decisão de design,
  de propósito: alerta que não é lido de relance não é alerta.
- **Seletor de partner inline** em Progressão, Evolução das taxas e Evolução de
  métricas (`_inline_partners`). Sem os truques de `session_state` que a versão
  anterior deste handoff previa: a key do widget embute o filtro do topo
  (`f"{prefixo}_partners_{stamp}"`), então mudar o topo recria o widget e ele
  volta a herdar, em vez de ficar preso num valor velho. Mexer no seletor da
  seção vale só pra ela.

## Gotchas / decisões que não devem ser revisitadas sem motivo

1. **Tema é light-only, de propósito.** Uma primeira versão tinha CSS reativo
   a `prefers-color-scheme: dark`, mas o Streamlit estava fixado em
   `base="light"` no `.streamlit/config.toml` — o mismatch fazia os KPIs
   renderizarem como caixa preta (texto escuro em fundo escuro). Removido o
   dark-mode do CSS custom pra ficar 100% consistente com o tema fixo do
   Streamlit. Se quiser dark mode de verdade, precisa mexer nos dois lados
   junto (config.toml + style.py), não só um.
2. **`fmt_brl` trata NaN/Infinity como "—".** Sem isso aparecia "R$ nan"/
   "R$ inf" quando cliques ou vendas = 0 na janela (divisão por zero vetorizada
   do pandas, não gera erro, gera NaN/Inf silenciosamente).
3. **Streamlit Cloud às vezes fica com cache velho depois de um push.**
   Aconteceu 2x nesta sessão: código 100% correto no GitHub (conferido byte a
   byte), mas o app ao vivo dava erro (`AttributeError`/`TypeError`) até um
   **reboot manual** (share.streamlit.io → app → "⋮" → Reboot app). Se o app
   der erro logo depois de um push, tenta reboot antes de assumir que é bug de
   código — principalmente depois de pushes em sequência rápida.
4. **Automação de browser (Claude) tem dificuldade com alguns widgets custom
   do Streamlit** (`st.multiselect`, `st.segmented_control`) — cliques
   sintéticos simples não disparam o handler; funciona com sequência completa
   de eventos de mouse via JS (pointerdown/mousedown/pointerup/mouseup/click)
   ou, pro multiselect, precisa de ArrowDown antes do Enter pra de fato
   selecionar a opção destacada (só digitar + Enter não comita). Não é bug do
   app — só relevante se uma sessão futura for testar via browser automatizado.
5. **`label_map` / `id_mp_canon` tem 2 linhas por partner** (armadilha
   documentada no CLAUDE.md do projeto principal) — as queries em
   `scripts/queries.sql` já usam `SELECT DISTINCT`, não precisa repetir, só não
   remover esse DISTINCT se algum dia mexer nessas queries.
6. **Cutoff de dados é `date.today() - 1 dia`**, nunca o dia corrente (dados
   parciais). Isso é calculado tanto no refresh real (`weekly_refresh.py`)
   quanto derivado dos próprios dados em `data.py` (`CUTOFF = max(...)`).

## Próximos passos (o motivo desta sessão ter pedido handoff)

Pedro quer fazer **várias pequenas atualizações de usabilidade e estética**
daqui pra frente. Nenhuma definida ainda nesta sessão — começar perguntando
o que especificamente ele quer ajustar. Candidatos óbvios que já surgiram:

- Seletor de partner inline sincronizado (ver "ainda não portado" acima)
- Qualquer ajuste visual/cores/espaçamento que ele apontar
- Eventualmente: página de Análise IA (existe no HTML via `ai_analysis.py`,
  nunca entrou no escopo do Streamlit)

## Comandos úteis

```bash
# ver o que rodou no último GitHub Actions
gh run list --repo pedrosales7/mp-agencia-dashboard-streamlit --limit 5

# disparar refresh manual em modo teste (não manda @channel no Slack)
gh workflow run "Weekly Dashboard Refresh (Streamlit)" --repo pedrosales7/mp-agencia-dashboard-streamlit -f test_mode=true

# comparar com o HTML original pra ver se ele recebeu commits novos
cd /Users/pedro/Claude/Projects/Dashboard-CodeVersion/mp-agencia-dashboard
git fetch origin -q && git log HEAD..origin/main --oneline -- docs/index.html scripts/
```
