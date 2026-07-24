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
  --good: #1a7a4c; --good-bg: #e4f3ea;
  --warn: #a06400; --warn-bg: #fbf3df;
  --crit: #b5382f; --crit-bg: #fbe9e6;
  --google: #2563eb; --meta: #7c3aed;
}
.snap-badge { display:inline-flex; align-items:center; gap:5px; padding:2px 9px; border-radius:999px;
  font-size:11px; font-weight:700; margin-left:8px; vertical-align:2px; background:var(--good-bg); color:var(--good); }
.snap-badge::before { content:"●"; font-size:8px; }

.canal-tag { display:inline-block; padding:2px 8px; border-radius:4px; font-size:10.5px; font-weight:700; }
.canal-tag.google { background: color-mix(in srgb, var(--google) 15%, transparent); color: var(--google); }
.canal-tag.meta { background: color-mix(in srgb, var(--meta) 15%, transparent); color: var(--meta); }

table.dk-table { width:100%; border-collapse:collapse; font-size:12.8px; }
table.dk-table th { text-align:right; padding:0 9px 8px; font-weight:700; color:var(--mut);
  font-size:10px; text-transform:uppercase; letter-spacing:0.04em; border-bottom:1px solid var(--bd); white-space:nowrap; }
table.dk-table th:first-child, table.dk-table td:first-child { text-align:left; }
table.dk-table td { padding:7px 9px; border-bottom:1px solid var(--bd-soft); white-space:nowrap;
  font-variant-numeric: tabular-nums; color: var(--ink); }
table.dk-table .partner-cell { font-weight:600; }
table.dk-table .cell-conv { display:block; font-size:10px; color:var(--mut2); margin-top:1px; font-weight:500; }
table.dk-table tr.tr-total td { background:var(--bd-soft); font-weight:700; }
table.dk-table tr.tr-warn td:first-child { border-left:3px solid var(--warn); }
table.dk-table th.canal-group.google { color:var(--google); border-bottom:2px solid var(--google); text-align:center; }
table.dk-table th.canal-group.meta { color:var(--meta); border-bottom:2px solid var(--meta); text-align:center; }
table.dk-table td.taxas-raw { color:var(--mut2); font-style:italic; cursor:help; }

.status-dot { display:inline-block; width:6px; height:6px; border-radius:50%; margin-right:5px; vertical-align:1px; }
.status-dot.good { background: var(--good); } .status-dot.bad { background: var(--crit); }

.legend-row { display:flex; gap:14px; align-items:center; font-size:11.5px; color:var(--mut); margin-top:6px; flex-wrap:wrap; }
.legend-row .sw { display:inline-flex; align-items:center; gap:5px; }
.legend-row .sw i { width:7px; height:7px; border-radius:50%; display:inline-block; }

.empty-hint { padding:22px 10px; text-align:center; color:var(--mut); font-size:13px;
  border:1px dashed var(--bd); border-radius:10px; }

.taxas-channel h4 { font-size:10.5px; font-weight:700; text-transform:uppercase; letter-spacing:0.05em;
  color:var(--mut); margin:14px 0 6px; display:flex; align-items:center; gap:6px; }
.taxas-channel h4::before { content:""; width:7px; height:7px; border-radius:50%; display:inline-block; }
.taxas-channel.google h4::before { background: var(--google); }
.taxas-channel.meta h4::before { background: var(--meta); }
.taxas-stage .sub { color:var(--mut2); font-weight:400; }
.taxas-spark svg { display:block; margin-left:auto; color:var(--ink); }

div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] > div[data-testid="stMetric"]) {
  background: var(--cd); border-color: var(--bd) !important; border-radius: 10px; padding: 10px 14px 8px;
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
