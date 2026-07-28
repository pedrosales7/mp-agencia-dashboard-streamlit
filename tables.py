"""Monta as tabelas HTML densas (funil, cobertura, detalhamento, progressão,
taxas) -- Streamlit não tem widget nativo pra célula com ponto de status ou
sparkline inline, então isso é HTML puro, renderizado via st.markdown.
"""

import math

from data import fmt_brl, fmt_num, fmt_pct, safe_div, outlier_status, funnel_medians, taxa_value, TAXAS_MIN_DENOM
from style import sparkline_svg


def _ds(v):
    """data-sort com o valor cru. Vazio quando não há número (vira o fim da ordem)."""
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return 'data-sort=""'
    return f'data-sort="{float(v):.6f}"'


def _delta_pct(curr, prev, semantic):
    """Delta de variação percentual do próprio valor (usado por Bruto/Cashback/
    Líquido/CPC/Cliques/CPL/CAC/Cliques->Venda) -- 'neutral' sempre cinza."""
    if curr is None or prev is None or not prev or not math.isfinite(curr) or not math.isfinite(prev):
        return ""
    d = (curr - prev) / abs(prev)
    if abs(d) < 0.005:
        return '<span class="cell-delta flat">· 0%</span>'
    is_up = d > 0
    arrow = "▲" if is_up else "▼"
    cls = "flat" if semantic == "neutral" else ("up" if is_up == (semantic != "down_good") else "down")
    return f'<span class="cell-delta {cls}">{arrow} {abs(d) * 100:.0f}%</span>'


def _delta_pp(curr, prev, semantic):
    """Delta em pontos percentuais -- usado nas colunas de etapa (Sessões,
    Clickoff, Redirect, Leads, Vendas), que comparam a TAXA de conversão deste
    período vs. a do período anterior, não o volume absoluto."""
    if curr is None or prev is None or not math.isfinite(curr) or not math.isfinite(prev):
        return ""
    diff = (curr - prev) * 100
    if abs(diff) < 0.05:
        return '<span class="cell-delta flat">· 0,0pp</span>'
    is_up = diff > 0
    arrow = "▲" if is_up else "▼"
    cls = "up" if is_up == (semantic != "down_good") else "down"
    return f'<span class="cell-delta {cls}">{arrow} {abs(diff):.1f}pp</span>'


def render_funnel_table(df, step_keys, step_labels, min_cliques, prev_df=None, compare=False, meds_source_df=None):
    """meds_source_df: df usado só pra calcular a mediana/peer-group (outlier
    bad/good). Por padrão é o próprio df exibido; quando o filtro de Partner
    do topo restringe as linhas mostradas, passamos aqui o df completo (todos
    os partners da conta), pra manter a mediana estável em vez de comparar o
    partner selecionado com ele mesmo."""
    meds = funnel_medians(meds_source_df if meds_source_df is not None else df, step_keys, min_cliques)
    head = ["Partner", "Bruto", "Cashback", "Líquido", "CPC", "Cliques", *step_labels,
            "CPL líq.", "CAC líq.", "Cliques→Venda"]
    # data-sort carrega o valor CRU: a célula mostra "R$ 2.780" e "84,8%", que
    # não ordenam como número. O JS do iframe lê o data-sort, não o texto.
    html = (['<table class="dk-table sortable"><thead><tr>']
            + [f'<th data-type="{"text" if i == 0 else "num"}">{h}</th>' for i, h in enumerate(head)]
            + ["</tr></thead><tbody>"])

    prev_by_id = {r["id_mp"]: r for _, r in prev_df.iterrows()} if compare and prev_df is not None else {}

    totals = {"bruto": 0, "cashback": 0, "cliques": 0, **{k: 0 for k in step_keys}}
    for _, r in df.iterrows():
        pr = prev_by_id.get(r["id_mp"])
        eligible = r["cliques"] >= min_cliques
        cells = [
            f'<td class="partner-cell" data-sort="{r["id_mp"]}">{r["id_mp"]}</td>',
            f'<td {_ds(r["bruto"])}>{fmt_brl(r["bruto"])}{_delta_pct(r["bruto"], pr["bruto"] if pr is not None else None, "neutral")}</td>',
            f'<td {_ds(r["cashback"])}>{fmt_brl(r["cashback"])}{_delta_pct(r["cashback"], pr["cashback"] if pr is not None else None, "neutral")}</td>',
            f'<td {_ds(r["liquido"])}>{fmt_brl(r["liquido"])}{_delta_pct(r["liquido"], pr["liquido"] if pr is not None else None, "neutral")}</td>',
            f'<td {_ds(r["cpc"])}>{fmt_brl(r["cpc"], 2)}{_delta_pct(r["cpc"], pr["cpc"] if pr is not None else None, "down_good")}</td>',
            f'<td {_ds(r["cliques"])}>{fmt_num(r["cliques"])}{_delta_pct(r["cliques"], pr["cliques"] if pr is not None else None, "up_good")}</td>',
        ]
        denom = r["cliques"]
        prev_denom = pr["cliques"] if pr is not None else None
        for k in step_keys:
            val = r[k]
            conv = safe_div(val, denom)
            cls = outlier_status(conv, meds[k], "rate") if eligible else None
            conv_html = f'<span class="cell-conv">{fmt_pct(conv)}</span>' if denom else ""
            if pr is not None and prev_denom:
                prev_conv = safe_div(pr[k], prev_denom)
                delta_html = _delta_pp(conv, prev_conv, "up_good")
            else:
                delta_html = ""
            # ordena pela TAXA de conversão, não pelo volume: é o que a coluna comunica
            cells.append(f'<td class="{cls or ""}" {_ds(conv)}>{fmt_num(val)}{conv_html}{delta_html}</td>')
            denom = val
            prev_denom = pr[k] if pr is not None else None
        cls_cpl = outlier_status(r["cpl"], meds["cpl"], "cost") if eligible and r["leads"] >= 3 else None
        cls_cac = outlier_status(r["cac"], meds["cac"], "cost") if eligible else None
        cls_conv = outlier_status(r["conv_final"], meds["conv_final"], "rate") if eligible else None
        cells.append(f'<td class="{cls_cpl or ""}" {_ds(r["cpl"])}>{fmt_brl(r["cpl"])}'
                     f'{_delta_pct(r["cpl"], pr["cpl"] if pr is not None else None, "down_good")}</td>')
        cells.append(f'<td class="{cls_cac or ""}" {_ds(r["cac"])}>{fmt_brl(r["cac"])}'
                     f'{_delta_pct(r["cac"], pr["cac"] if pr is not None else None, "down_good")}</td>')
        cells.append(f'<td class="{cls_conv or ""}" {_ds(r["conv_final"])}>{fmt_pct(r["conv_final"])}'
                     f'{_delta_pct(r["conv_final"], pr["conv_final"] if pr is not None else None, "up_good")}</td>')
        html.append("<tr>" + "".join(cells) + "</tr>")

        totals["bruto"] += r["bruto"]; totals["cashback"] += r["cashback"]; totals["cliques"] += r["cliques"]
        for k in step_keys:
            totals[k] += r[k]

    tot_liquido = totals["bruto"] - totals["cashback"]
    tot_leads, tot_vendas = totals["leads"], totals["vendas"]
    tot_cells = [f'<td class="partner-cell">TOTAL</td>', f'<td>{fmt_brl(totals["bruto"])}</td>',
                 f'<td>{fmt_brl(totals["cashback"])}</td>', f'<td>{fmt_brl(tot_liquido)}</td>',
                 f'<td>{fmt_brl(safe_div(totals["bruto"], totals["cliques"]), 2)}</td>',
                 f'<td>{fmt_num(totals["cliques"])}</td>']
    for k in step_keys:
        tot_cells.append(f'<td>{fmt_num(totals[k])}</td>')
    tot_cells.append(f'<td>{fmt_brl(safe_div(tot_liquido, tot_leads))}</td>')
    tot_cells.append(f'<td>{fmt_brl(safe_div(tot_liquido, tot_vendas))}</td>')
    tot_cells.append(f'<td>{fmt_pct(safe_div(tot_vendas, totals["cliques"]))}</td>')
    html.append('<tr class="tr-total" data-pin="1">' + "".join(tot_cells) + "</tr>")
    html.append("</tbody></table>")
    return "".join(html)


def render_coverage_table(df):
    """1 linha por partner, Google e Meta como grupos de coluna lado a lado
    (cabeçalho de 2 níveis) -- cada canal tem sua própria base (Clickoff pro
    Google, Chat start pro Meta), então não faz sentido somar os dois."""
    html = ['<table class="dk-table"><thead><tr>',
            '<th rowspan="2" style="vertical-align:bottom;">Partner</th>',
            '<th colspan="4" class="canal-group google">Google</th>',
            '<th colspan="4" class="canal-group meta">Meta</th>',
            "</tr><tr>",
            "<th>% Cashback</th><th>Leads totais</th><th>Leads c/ cobertura</th><th>% Assertividade</th>",
            "<th>% Cashback</th><th>Leads totais</th><th>Leads c/ cobertura</th><th>% Assertividade</th>",
            "</tr></thead><tbody>"]

    def channel_cells(r, prefix):
        if r[f"{prefix}_bruto"] is None:
            return "<td>—</td><td>—</td><td>—</td><td>—</td>"
        asr_html = fmt_pct(r[f"{prefix}_pct_assert"]) if r[f"{prefix}_elig_asr"] else "—"
        return (
            f'<td class="{r[f"{prefix}_status_cash"] or ""}">{fmt_pct(r[f"{prefix}_pct_cashback"])}</td>'
            f'<td>{fmt_num(r[f"{prefix}_total_leads"])}</td>'
            f'<td>{fmt_num(r[f"{prefix}_covered_leads"])}</td>'
            f'<td class="{r[f"{prefix}_status_asr"] or ""}">{asr_html}</td>'
        )

    for _, r in df.iterrows():
        html.append(f'<tr><td class="partner-cell">{r["id_mp"]}</td>{channel_cells(r, "g")}{channel_cells(r, "m")}</tr>')
    html.append("</tbody></table>")
    return "".join(html)


def render_progressao_table(df):
    metricas = [
        ("Investimento bruto", lambda r: fmt_brl(r["bruto"])),
        ("Cashback", lambda r: fmt_brl(r["cashback"])),
        ("Investimento líq.", lambda r: fmt_brl(r["liquido"])),
        ("% Cashback", lambda r: fmt_pct(r["pct_cashback"])),
        ("Cliques (G + M)", lambda r: fmt_num(r["cliques"])),
        ("Clickoff (Google)", lambda r: fmt_num(r["clickoff_g"])),
        ("Chat start (Meta)", lambda r: fmt_num(r["chat_start_m"])),
        ("Leads*", lambda r: fmt_num(r["leads"])),
        ("Vendas", lambda r: fmt_num(r["vendas"])),
        ("CPL líq.", lambda r: fmt_brl(r["cpl"])),
        ("CAC líq.", lambda r: fmt_brl(r["cac"])),
        ("Lead → Venda", lambda r: fmt_pct(r["lead_venda"])),
        ("% Assert. Google", lambda r: fmt_pct(r["asr_g"]) if r["clickoff_g"] > 0 else "—"),
        ("% Assert. Meta", lambda r: fmt_pct(r["asr_m"]) if r["chat_start_m"] > 0 else "—"),
    ]
    html = ['<table class="dk-table"><thead><tr><th>Métrica</th>']
    for _, r in df.iterrows():
        html.append(f'<th>{r["label"]}</th>')
    html.append("</tr></thead><tbody>")
    for label, f in metricas:
        html.append(f'<tr><td class="partner-cell">{label}</td>')
        for _, r in df.iterrows():
            html.append(f"<td>{f(r)}</td>")
        html.append("</tr>")
    html.append("</tbody></table>")
    return "".join(html)


def _taxas_delta(cur, prev):
    """Mesma convenção visual (seta + 'pp') de _delta_pp, pra não ter um
    terceiro estilo de delta na página."""
    if cur is None or prev is None:
        return '<span class="cell-delta flat">—</span>'
    diff = (cur - prev) * 100
    if abs(diff) < 0.05:
        return '<span class="cell-delta flat">· 0,0pp</span>'
    is_up = diff > 0
    arrow = "▲" if is_up else "▼"
    cls = "up" if is_up else "down"
    return f'<span class="cell-delta {cls}">{arrow} {abs(diff):.1f}pp</span>'


def render_taxas_block(df, stages, gran_label):
    html = ['<table class="dk-table"><thead><tr><th>Etapa</th>']
    for _, r in df.iterrows():
        html.append(f'<th>{r["label"]}</th>')
    html.append(f'<th>Trajetória</th><th>Δ {gran_label}</th></tr></thead><tbody>')
    for from_label, to_label, num_key, den_key in stages:
        rows = list(df.iterrows())
        vals = [taxa_value(r[num_key], r[den_key]) for _, r in rows]
        html.append(f'<tr><td class="taxas-stage">{from_label} <span class="sub">→ {to_label}</span></td>')
        for v, (_, r) in zip(vals, rows):
            if v is not None:
                html.append(f'<td>{v*100:.1f}%</td>')
            elif r[den_key]:
                html.append(f'<td class="taxas-raw" title="Base pequena (menos de {TAXAS_MIN_DENOM}) '
                            f'— taxa não exibida pra não induzir a erro">{r[num_key]}/{r[den_key]}</td>')
            else:
                html.append('<td>—</td>')
        html.append(f'<td class="taxas-spark">{sparkline_svg(vals)}</td>')
        html.append(f'<td>{_taxas_delta(vals[-1], vals[-2] if len(vals) > 1 else None)}</td></tr>')
    html.append("</tbody></table>")
    return "".join(html)


# ── tabela ordenável por clique no cabeçalho ─────────────────────────────
#
# A tabela é HTML puro (o Streamlit não tem widget com % de conversão embaixo
# do número, delta e linha TOTAL numa célula só). O st.markdown remove <script>,
# então a ordenação por clique só é possível dentro de um components.v1.html,
# que roda num iframe com JS liberado. Custo: o iframe não herda o CSS da
# página, por isso o CSS vai injetado junto; e a altura tem que ser calculada,
# porque iframe não cresce sozinho com o conteúdo.

SORT_JS = """
<script>
(function () {
  var table = document.querySelector('table.sortable');
  if (!table) return;
  var ths = table.tHead.rows[0].cells;

  function val(row, i) {
    var td = row.cells[i];
    var raw = td.getAttribute('data-sort');
    if (raw === null) return td.innerText.trim();
    if (raw === '') return null;               // sem base: sempre no fim
    var n = parseFloat(raw);
    return isNaN(n) ? raw : n;
  }

  function sortBy(i, asc) {
    var body = table.tBodies[0];
    var rows = [].slice.call(body.rows);
    var pinned = rows.filter(function (r) { return r.dataset.pin; });
    var data = rows.filter(function (r) { return !r.dataset.pin; });
    data.sort(function (a, b) {
      var x = val(a, i), y = val(b, i);
      if (x === null && y === null) return 0;
      if (x === null) return 1;                // nulo vai pro fim nos dois sentidos
      if (y === null) return -1;
      var c = (typeof x === 'number' && typeof y === 'number')
              ? x - y : String(x).localeCompare(String(y), 'pt-BR');
      return asc ? c : -c;
    });
    data.concat(pinned).forEach(function (r) { body.appendChild(r); });
    for (var k = 0; k < ths.length; k++) ths[k].removeAttribute('data-dir');
    ths[i].setAttribute('data-dir', asc ? 'asc' : 'desc');
  }

  for (var i = 0; i < ths.length; i++) {
    (function (idx) {
      ths[idx].addEventListener('click', function () {
        var asc = ths[idx].getAttribute('data-dir') !== 'asc';
        sortBy(idx, asc);
      });
    })(i);
  }
})();
</script>
"""

SORT_CSS = """
<style>
  body { margin:0; background:transparent; }
  table.sortable th { cursor:pointer; user-select:none; position:relative; padding-right:14px !important; }
  table.sortable th:hover { color:var(--ink); }
  table.sortable th::after { content:"⇅"; position:absolute; right:4px; opacity:.25; font-size:9px; }
  table.sortable th[data-dir="asc"]::after  { content:"▲"; opacity:.85; }
  table.sortable th[data-dir="desc"]::after { content:"▼"; opacity:.85; }
</style>
"""


# Altura de linha medida no browser: o funil tem a taxa de conversão numa
# segunda linha dentro da célula, o detalhamento não. Com "Comparar" ligado
# entra mais um span de delta, que empurra um pouco.
ROW_H_FUNNEL = 42
ROW_H_COMPARE_EXTRA = 10


def sortable_table_height(n_rows, row_h=ROW_H_FUNNEL, compare=False):
    """Altura do iframe: cabeçalho + linhas + TOTAL + folga.

    Iframe não cresce com o conteúdo, então a altura é calculada. Errar pra
    baixo corta a tabela; errar pra cima deixa buraco branco — por isso a
    folga é pequena e o scrolling fica ligado como rede de segurança.
    """
    return 24 + (n_rows + 1) * (row_h + (ROW_H_COMPARE_EXTRA if compare else 0)) + 10


def sortable_doc(table_html, base_css):
    """Documento completo do iframe: CSS da página + CSS/JS de ordenação."""
    return f"{base_css}{SORT_CSS}<div class='dk-wrap'>{table_html}</div>{SORT_JS}"
