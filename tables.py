"""Monta as tabelas HTML densas (funil, cobertura, detalhamento, progressão,
taxas) -- Streamlit não tem widget nativo pra célula com ponto de status ou
sparkline inline, então isso é HTML puro, renderizado via st.markdown.
"""

from data import fmt_brl, fmt_num, fmt_pct, safe_div, outlier_status, funnel_medians, taxa_value
from style import status_dot, sparkline_svg


def render_funnel_table(df, step_keys, step_labels, min_cliques):
    meds = funnel_medians(df, step_keys, min_cliques)
    head = ["Partner", "Bruto", "Cashback", "Líquido", "CPC", "Cliques", *step_labels,
            "CPL líq.", "CAC líq.", "Cliques→Venda"]
    html = ['<table class="dk-table"><thead><tr>'] + [f"<th>{h}</th>" for h in head] + ["</tr></thead><tbody>"]

    totals = {"bruto": 0, "cashback": 0, "cliques": 0, **{k: 0 for k in step_keys}}
    for _, r in df.iterrows():
        eligible = r["cliques"] >= min_cliques
        cells = [f'<td class="partner-cell">{r["id_mp"]}</td>',
                 f'<td>{fmt_brl(r["bruto"])}</td>', f'<td>{fmt_brl(r["cashback"])}</td>',
                 f'<td>{fmt_brl(r["liquido"])}</td>', f'<td>{fmt_brl(r["cpc"], 2)}</td>',
                 f'<td>{fmt_num(r["cliques"])}</td>']
        denom = r["cliques"]
        for k in step_keys:
            val = r[k]
            conv = safe_div(val, denom)
            cls = outlier_status(conv, meds[k], "rate") if eligible else None
            conv_html = f'<span class="cell-conv">{fmt_pct(conv)}</span>' if denom else ""
            cells.append(f'<td>{status_dot(cls)}{fmt_num(val)}{conv_html}</td>')
            denom = val
        cls_cpl = outlier_status(r["cpl"], meds["cpl"], "cost") if eligible and r["leads"] >= 3 else None
        cls_cac = outlier_status(r["cac"], meds["cac"], "cost") if eligible else None
        cls_conv = outlier_status(r["conv_final"], meds["conv_final"], "rate") if eligible else None
        cells.append(f'<td>{status_dot(cls_cpl)}{fmt_brl(r["cpl"])}</td>')
        cells.append(f'<td>{status_dot(cls_cac)}{fmt_brl(r["cac"])}</td>')
        cells.append(f'<td>{status_dot(cls_conv)}{fmt_pct(r["conv_final"])}</td>')
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
    html = ['<table class="dk-table"><thead><tr>',
            "<th>Partner</th><th>Canal</th><th>Bruto</th><th>Cashback</th>",
            "<th>% Cashback</th><th>Vol. base</th><th>Leads</th><th>% Assertividade</th>",
            "</tr></thead><tbody>"]
    for _, r in df.iterrows():
        asr_html = fmt_pct(r["pct_assert"]) if r["elig_asr"] else "—"
        html.append(
            f'<tr><td class="partner-cell">{r["id_mp"]}</td>'
            f'<td><span class="canal-tag {r["canal"]}">{r["canal"]}</span></td>'
            f'<td>{fmt_brl(r["bruto"])}</td><td>{fmt_brl(r["cashback"])}</td>'
            f'<td>{status_dot(r["status_cash"])}{fmt_pct(r["pct_cashback"])}</td>'
            f'<td>{fmt_num(r["vol_base"])}<span class="cell-conv">{r["base_label"]}</span></td>'
            f'<td>{fmt_num(r["leads"])}</td>'
            f'<td>{status_dot(r["status_asr"])}{asr_html}</td></tr>'
        )
    html.append("</tbody></table>")
    return "".join(html)


def render_detail_table(df):
    html = ['<table class="dk-table"><thead><tr>',
            "<th>Partner</th><th>Bruto</th><th>Cashback</th><th>Líquido</th>",
            "<th>Leads</th><th>Vendas</th><th>CPL líq.</th><th>CAC líq.</th><th>Lead→Venda</th>",
            "</tr></thead><tbody>"]
    totals = {"bruto": 0, "cashback": 0, "liquido": 0, "leads": 0, "vendas": 0}
    for _, r in df.iterrows():
        row_cls = "tr-warn" if r["warn"] else ""
        html.append(
            f'<tr class="{row_cls}"><td class="partner-cell">{r["id_mp"]}</td>'
            f'<td>{fmt_brl(r["bruto"])}</td><td>{fmt_brl(r["cashback"])}</td><td>{fmt_brl(r["liquido"])}</td>'
            f'<td>{fmt_num(r["leads"])}</td><td>{fmt_num(r["vendas"])}</td>'
            f'<td>{status_dot(r["status_cpl"])}{fmt_brl(r["cpl"])}</td>'
            f'<td>{status_dot(r["status_cac"])}{fmt_brl(r["cac"])}</td>'
            f'<td>{status_dot(r["status_rate"])}{fmt_pct(r["rate"])}</td></tr>'
        )
        for k in totals:
            totals[k] += r[k]
    html.append(
        f'<tr class="tr-total"><td class="partner-cell">TOTAL</td>'
        f'<td>{fmt_brl(totals["bruto"])}</td><td>{fmt_brl(totals["cashback"])}</td><td>{fmt_brl(totals["liquido"])}</td>'
        f'<td>{fmt_num(totals["leads"])}</td><td>{fmt_num(totals["vendas"])}</td>'
        f'<td>{fmt_brl(safe_div(totals["liquido"], totals["leads"]))}</td>'
        f'<td>{fmt_brl(safe_div(totals["liquido"], totals["vendas"]))}</td>'
        f'<td>{fmt_pct(safe_div(totals["vendas"], totals["leads"]))}</td></tr>'
    )
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
        vals = [taxa_value(r[num_key], r[den_key]) for _, r in df.iterrows()]
        html.append(f'<tr><td class="taxas-stage">{from_label} <span class="sub">→ {to_label}</span></td>')
        for v in vals:
            html.append(f'<td>{"—" if v is None else f"{v*100:.1f}%"}</td>')
        html.append(f'<td class="taxas-spark">{sparkline_svg(vals)}</td>')
        html.append(f'<td>{_taxas_delta(vals[-1], vals[-2] if len(vals) > 1 else None)}</td></tr>')
    html.append("</tbody></table>")
    return "".join(html)
