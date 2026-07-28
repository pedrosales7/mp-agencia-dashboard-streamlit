"""Tema visual 'Sinalização' -- injeta CSS custom em cima do Streamlit.

Streamlit cuida do widget nativo (botões, multiselect, metric); este CSS só
estiliza os componentes que construímos como HTML puro (tabelas com pontos de
status, rail colorido nos KPIs, badges) para ficar consistente com o
protótipo aprovado.
"""

CSS = """
<style>
:root {
  --pg: #f7f8f7; --cd: #ffffff; --ink: #171a1a; --mut: #666e6b; --mut2: #8b918e;
  --bd: #dde2df; --bd-soft: #e9ece9; --acc: #33564c;
  --good: #1a7a4c; --good-bg: #f0fdf4; --good-text: #15803d;
  --warn: #a06400; --warn-bg: #fbf3df;
  --crit: #b5382f; --crit-bg: #fef2f2; --crit-text: #b91c1c;
  --google: #2563eb; --meta: #7c3aed;
}
.dash-h1 { font-size:26px; font-weight:700; margin-bottom:2px; }
.section-title { font-size:18px; margin-bottom:0; }

.snap-badge { display:inline-flex; align-items:center; gap:5px; padding:2px 9px; border-radius:999px;
  font-size:11px; font-weight:700; margin-left:8px; vertical-align:2px; background:var(--good-bg); color:var(--good); }
.snap-badge::before { content:"●"; font-size:8px; }
.snap-badge.warn { background:var(--warn-bg); color:var(--warn); }
.snap-badge.crit { background:var(--crit-bg); color:var(--crit); }

/* Distinção Google/Meta -- ponto colorido reaproveitado em toda parte que
   precisa diferenciar canal: badge (.canal-tag), cabeçalho de grupo de coluna
   (.canal-group, abaixo) e sub-título de bloco (.taxas-channel h4). */
.canal-tag { display:inline-flex; align-items:center; gap:6px; padding:2px 8px; border-radius:4px;
  font-size:10.5px; font-weight:700; }
.canal-tag.google { background: color-mix(in srgb, var(--google) 15%, transparent); color: var(--google); }
.canal-tag.meta { background: color-mix(in srgb, var(--meta) 15%, transparent); color: var(--meta); }
.canal-tag::before { content:""; width:6px; height:6px; border-radius:50%; display:inline-block; background:currentColor; }

table.dk-table { width:100%; border-collapse:collapse; font-size:12.8px; }
table.dk-table th { text-align:right; padding:0 9px 8px; font-weight:700; color:var(--mut);
  font-size:10px; text-transform:uppercase; letter-spacing:0.04em; border-bottom:1px solid var(--bd); white-space:nowrap; }
table.dk-table th:first-child, table.dk-table td:first-child { text-align:left; }
table.dk-table td { padding:7px 9px; border-bottom:1px solid var(--bd-soft); white-space:nowrap;
  font-variant-numeric: tabular-nums; color: var(--ink); font-weight:600; }
table.dk-table .partner-cell { font-weight:600; }
table.dk-table .cell-conv { display:block; font-size:10px; color:var(--mut2); margin-top:1px; font-weight:500; }
table.dk-table .cell-delta { display:block; font-size:10px; margin-top:1px; font-weight:700; }
table.dk-table .cell-delta.up   { color: var(--good-text); }
table.dk-table .cell-delta.down { color: var(--crit-text); }
table.dk-table .cell-delta.flat { color: var(--mut2); font-weight:500; }
table.dk-table tr.tr-total td { background:var(--bd-soft); font-weight:700; }
table.dk-table th.canal-group.google, table.dk-table th.canal-group.meta { text-align:center; }
table.dk-table th.canal-group.google { color:var(--google); border-bottom:2px solid var(--google); }
table.dk-table th.canal-group.meta { color:var(--meta); border-bottom:2px solid var(--meta); }
table.dk-table th.canal-group::before { content:"● "; }
table.dk-table td.taxas-raw { color:var(--mut2); font-style:italic; cursor:help; }

/* Outlier vs. mediana: célula pintada, mesmas cores do dashboard HTML
   (decisão 2026-07-24 — o ponto de 6px do tema "Sinalização" era pequeno
   demais pra ser lido de relance, que é o ponto inteiro do alerta).
   good/crit-bg e good/crit-text vêm do :root -- fonte única com o snap-badge
   e a legenda abaixo (antes eram 2 paletas verde/vermelho divergentes). */
table.dk-table td.bad  { background:var(--crit-bg); }
table.dk-table td.good { background:var(--good-bg); }
table.dk-table td.bad  .cell-conv { color:var(--crit-text); }
table.dk-table td.good .cell-conv { color:var(--good-text); }

.status-dot { display:inline-block; width:6px; height:6px; border-radius:50%; margin-right:5px; vertical-align:1px; }
.status-dot.good { background: var(--good); } .status-dot.bad { background: var(--crit); }

.legend-row { display:flex; gap:14px; align-items:center; font-size:11.5px; color:var(--mut); margin-top:6px; flex-wrap:wrap; }
.legend-row .sw { display:inline-flex; align-items:center; gap:5px; }
.legend-row .sw i { width:7px; height:7px; border-radius:50%; display:inline-block; }
.legend-row .sw i.good { background:var(--good-bg); border:1px solid #bbf7d0; }
.legend-row .sw i.bad  { background:var(--crit-bg); border:1px solid #fecaca; }

.empty-hint { padding:22px 10px; text-align:center; color:var(--mut); font-size:13px;
  border:1px dashed var(--bd); border-radius:10px; }

/* Espaçador entre blocos de partner repetidos (Progressão/Taxas) -- substitui
   st.write("") por uma margem declarativa; casa por prefixo porque a key do
   container embute o id do partner. */
div[class*="st-key-prog_block_"], div[class*="st-key-taxas_block_"] { margin-bottom:16px; }

.taxas-channel h4 { font-size:10.5px; font-weight:700; text-transform:uppercase; letter-spacing:0.05em;
  color:var(--mut); margin:14px 0 6px; display:flex; align-items:center; gap:6px; }
.taxas-channel h4::before { content:""; width:7px; height:7px; border-radius:50%; display:inline-block; }
.taxas-channel.google h4::before { background: var(--google); }
.taxas-channel.meta h4::before { background: var(--meta); }
.taxas-stage .sub { color:var(--mut2); font-weight:400; }
.taxas-spark svg { display:block; margin-left:auto; color:var(--ink); }

/* Rótulos do filtro (PERÍODO/CANAL/PARTNER/COMPARAR) -- mesma receita
   tipográfica dos cabeçalhos de tabela (table.dk-table th acima), pra ler
   como o mesmo sistema em vez de caption nativa do Streamlit. */
.filter-label { font-size:10px; font-weight:700; color:var(--mut); text-transform:uppercase;
  letter-spacing:0.04em; margin-bottom:2px; }

/* Cabeçalho (título + badge + caption) e barra de filtros como um único
   card coeso -- antes o título flutuava sem borda acima do card de filtros. */
.st-key-header_card { background: var(--cd); border-color: var(--bd) !important;
  border-radius: 10px; padding: 18px 20px 16px; }
.header-divider { border: none; border-top: 1px solid var(--bd-soft); margin: 14px 0 16px; }

/* Faixa de KPIs como uma única tira com divisores finos, em vez de 7 caixas
   soltas com borda própria + gutter do st.columns entre elas. */
.st-key-kpi_strip { background: var(--cd); border-color: var(--bd) !important;
  border-radius: 10px; padding: 12px 4px; }
.st-key-kpi_strip div[data-testid="stColumn"] { padding: 0 14px; }
.st-key-kpi_strip div[data-testid="stColumn"]:not(:first-child) { border-left: 1px solid var(--bd-soft); }

/* Streamlit injeta um botão de anchor-link (🔗) em todo h1-h6 renderizado via
   st.markdown -- inclusive nos nossos títulos com HTML puro. Sem uso aqui
   (não linkamos pra seções por âncora), então some com ele. */
[data-testid="stHeaderActionElements"] { display: none !important; }

/* Botão do popover "Mês/custom" no filtro de período -- sem quebra de linha,
   trunca com reticências se o texto (ex.: intervalo de datas) não couber. */
button[data-testid="stPopoverButton"] p {
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%;
}
</style>
"""


def status_dot(status):
    return f'<span class="status-dot {status}"></span>' if status else ""


def sparkline_svg(values):
    w, h, pad = 62, 22, 3
    valid = [v for v in values if v is not None]
    if len(valid) < 2:
        return f'<svg width="{w}" height="{h}"></svg>'
    lo, hi = min(valid), max(valid)
    rng = (hi - lo) or 1
    step_x = (w - 2 * pad) / (len(values) - 1)
    pts = []
    for i, v in enumerate(values):
        if v is None:
            pts.append(None)
            continue
        x = pad + i * step_x
        y = h - pad - ((v - lo) / rng) * (h - 2 * pad)
        pts.append((x, y))
    path, started = "", False
    for p in pts:
        if p is None:
            started = False
            continue
        path += (" L" if started else "M") + f"{p[0]:.1f},{p[1]:.1f}"
        started = True
    last = next((p for p in reversed(pts) if p is not None), None)
    prev = None
    for p in reversed(pts[:-1]):
        if p is not None:
            prev = p
            break
    dot_color = "currentColor"
    if last and prev:
        if last[1] < prev[1] - 0.5:
            dot_color = "var(--good)"
        elif last[1] > prev[1] + 0.5:
            dot_color = "var(--crit)"
    dot = f'<circle cx="{last[0]:.1f}" cy="{last[1]:.1f}" r="2.2" fill="{dot_color}"/>' if last else ""
    return (f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" fill="none">'
            f'<path d="{path}" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>'
            f'{dot}</svg>')
