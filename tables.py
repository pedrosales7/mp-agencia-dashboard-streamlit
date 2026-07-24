"""Monta as tabelas HTML densas (funil, cobertura, detalhamento, progressão,
taxas) -- Streamlit não tem widget nativo pra célula com ponto de status ou
sparkline inline, então isso é HTML puro, renderizado via st.markdown.
"""

import math

from data import fmt_brl, fmt_num, fmt_pct, safe_div, outlier_status, funnel_medians, taxa_value, TAXAS_MIN_DENOM
from style import status_dot, sparkline_svg


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


def render_funnel_table(df, step_keys, step_labels, min_cliques, prev_df=None, compare=False):
    meds = funnel_medians(df, step_keys, min_cliques)
    head = ["Partner", "Bruto", "Cashback", "Líquido", "CPC", "Cliques", *step_labels,
            "CPL líq.", "CAC líq.", "Cliques→Venda"]
    html = ['<table class="dk-table"><thead><tr>'] + [f"<th>{h}</th>" for h in head] + ["</tr></thead><tbody>"]

    prev_by_id = {r["id_mp"]: r for _, r in prev_df.iterrows()} if compare and prev_df is not None else {}

    totals = {"bruto": 0, "cashback": 0, "cliques": 0, **{k: 0 for k in step_keys}}
    for _, r in df.iterrows():
        pr = prev_by_id.get(r["id_mp"])
        eligible = r["cliques"] >= min_cliques
        cells = [
            f'<td class="partner-cell">{r["id_mp"]}</td>',
            f'<td>{fmt_brl(r["bruto"])}{_delta_pct(r["bruto"], pr["bruto"] if pr is not None else None, "neutral")}</td>',
            f'<td>{fmt_brl(r["cashback"])}{_delta_pct(r["cashback"], pr["cashback"] if pr is not None else None, "neutral")}</td>',
            f'<td>{fmt_brl(r["liquido"])}{_delta_pct(r["liquido"], pr["liquido"] if pr is not None else None, "neutral")}</td>',
            f'<td>{fmt_brl(r["cpc"], 2)}{_delta_pct(r["cpc"], pr["cpc"] if pr is not None else None, "down_good")}</td>',
            f'<td>{fmt_num(r["cliques"])}{_delta_pct(r["cliques"], pr["cliques"] if pr is not None else None, "up_good")}</td>',
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
            cells.append(f'<td>{status_dot(cls)}{fmt_num(val)}{conv_html}{delta_html}</td>')
            denom = val
            prev_denom = pr[k] if pr is not None else None
        cls_cpl = outlier_status(r["cpl"], meds["cpl"], "cost") if eligible and r["leads"] >= 3 else None
        cls_cac = outlier_status(r["cac"], meds["cac"], "cost") if eligible else None
        cls_conv = outlier_status(r["conv_final"], meds["conv_final"], "rate") if eligible else None
        cells.append(f'<td>{status_dot(cls_cpl)}{fmt_brl(r["cpl"])}'
                     f'{_delta_pct(r["cpl"], pr["cpl"] if pr is not None else None, "down_good")}</td>')
        cells.append(f'<td>{status_dot(cls_cac)}{fmt_brl(r["cac"])}'
                     f'{_delta_pct(r["cac"], pr["cac"] if pr is not None else None, "down_good")}</td>')
        cells.append(f'<td>{status_dot(cls_conv)}{fmt_pct(r["conv_final"])}'
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
    html.append('<tr class="tr-total">' + "".join(tot_cells) + "</tr>")
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
            f'<td>{status_dot(r[f"{prefix}_status_cash"])}{fmt_pct(r[f"{prefix}_pct_cashback"])}</td>'
            f'<td>{fmt_num(r[f"{prefix}_total_leads"])}</td>'
            f'<td>{fmt_num(r[f"{prefix}_covered_leads"])}</td>'
            f'<td>{status_dot(r[f"{prefix}_status_asr"])}{asr_html}</td>'
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
    if cur is None or prev is None:
        return '<span class="cell-delta flat">—</span>'
    diff = (cur - prev) * 100
    if abs(diff) < 0.05:
        return '<span class="cell-delta flat">0,0 pp</span>'
    cls = "up" if diff > 0 else "down"
    sign = "+" if diff > 0 else "−"
    return f'<span class="cell-delta {cls}">{sign}{abs(diff):.1f} pp</span>'


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
