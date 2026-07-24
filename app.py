"""MP Agência — Funil Ads-to-Sale (Streamlit).

Lê o snapshot semanal em data/latest.json -- nenhuma query ao vivo acontece
aqui. O refresh (Metabase -> JSON) roda separado, no GitHub Actions.
"""

import plotly.graph_objects as go
import streamlit as st

import data
import tables
from style import CSS

st.set_page_config(page_title="MP Agência — Funil Ads-to-Sale", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

snap = data.SNAPSHOT["snapshot"]

# ------------------------------------------------------------------
# Header
# ------------------------------------------------------------------
st.markdown(
    f'<h1 style="font-size:26px;font-weight:700;margin-bottom:2px;">'
    f'MP Agência — Funil Ads-to-Sale'
    f'<span class="snap-badge">snapshot {snap["label"]}</span></h1>',
    unsafe_allow_html=True,
)
st.caption(
    "Atribuição pelo anunciante. Investimento via `performance_partner_mp_agency`; "
    "eventos via `comparison.*` + `whatsapp_assistant.*`; leads/vendas via `checkout.lead_detail`. "
    "CPL/CAC sobre líquido."
)

# ------------------------------------------------------------------
# Filtros
# ------------------------------------------------------------------
month_keys = data.available_month_keys()
with st.container(border=True):
    f1, f2, f3, f4 = st.columns([2.8, 1.8, 2.4, 1.6])
    with f1:
        st.caption("PERÍODO")
        period = st.segmented_control("Período", ["7d", "30d", "90d"], default="30d", label_visibility="collapsed")
        month = st.selectbox("Mês", ["—"] + [data.month_label(mk) for mk in month_keys],
                              label_visibility="collapsed")
        custom_range = st.date_input(
            "Personalizado", value=(), format="DD/MM/YYYY", label_visibility="collapsed",
            min_value=data.MIN_DATE, max_value=data.CUTOFF_DATE,
            help="Selecione data inicial e final pra um período customizado — sobrepõe Período/Mês quando preenchido.",
        )
    with f2:
        st.caption("CANAL")
        canal_label = st.segmented_control("Canal", ["Todos", "Google", "Meta"], default="Todos",
                                            label_visibility="collapsed")
        canal_filter = None if canal_label in (None, "Todos") else canal_label.lower()
    with f3:
        st.caption("PARTNER")
        selected_partners = st.multiselect("Partner", data.PARTNERS, default=[], label_visibility="collapsed",
                                            placeholder="Todos")
    with f4:
        st.caption("COMPARAR")
        compare = st.toggle("Δ vs período anterior", value=False)

custom_invalid = len(custom_range) == 2 and custom_range[0] > custom_range[1]
if len(custom_range) == 2 and not custom_invalid:
    d_ini, d_fim = custom_range[0].isoformat(), custom_range[1].isoformat()
    janela_label = f"período customizado ({d_ini} a {d_fim})"
else:
    if custom_invalid:
        st.warning("Data inicial é depois da final — período customizado ignorado, usando Período/Mês.")
    if month != "—":
        period_key = month_keys[[data.month_label(mk) for mk in month_keys].index(month)]
    else:
        period_key = period or "30d"
    d_ini, d_fim = data.period_window(period_key)
    janela_label = f"{d_ini} a {d_fim}"

st.caption(f"ℹ️ Snapshot {snap['label']} · janela selecionada: {janela_label}.")

# ------------------------------------------------------------------
# KPIs
# ------------------------------------------------------------------
totals = data.compute_totals(d_ini, d_fim, canal_filter)
prev_d_ini, prev_d_fim = data.previous_window(d_ini, d_fim)
prev = data.compute_totals(prev_d_ini, prev_d_fim, canal_filter)


def _delta(curr, prev_v, invert=False):
    if not compare or curr is None or not prev_v:
        return None, "off"
    pct = (curr - prev_v) / abs(prev_v) * 100
    return f"{pct:+.1f}%", ("inverse" if invert else "normal")


k1, k2, k3, k4, k5, k6, k7 = st.columns(7)

with k1.container(border=True):
    d, c = _delta(totals["liquido"], prev["liquido"])
    st.metric("Investimento líquido", data.fmt_brl(totals["liquido"]), d, delta_color="off",
              help="Bruto − Cashback. Fonte: performance_partner_mp_agency.")

with k2.container(border=True):
    d, c = _delta(totals["cashback"], prev["cashback"])
    st.metric("Cashback", data.fmt_brl(totals["cashback"]), d, delta_color="off",
              help="Parte do investimento bruto que não fica com o anunciante (lead/redirect caiu "
                   "fora da cobertura dele e voltou pra Melhor Plano). Líquido = Bruto − Cashback.")
    st.caption(f"{totals['cashback'] / totals['bruto'] * 100:.0f}% do bruto" if totals["bruto"] else " ")

with k3.container(border=True):
    d, c = _delta(totals["leads"], prev["leads"])
    st.metric("Leads produtivos", data.fmt_num(totals["leads"]), d, delta_color=c,
              help="source em google/whatsapp e lead_accepted=true.")

with k4.container(border=True):
    d, c = _delta(totals["vendas"], prev["vendas"])
    st.metric("Vendas", data.fmt_num(totals["vendas"]), d, delta_color=c,
              help="current_situation IN (sold, installed, scheduled).")

with k5.container(border=True):
    d, c = _delta(totals["cpl"], prev["cpl"], invert=True)
    st.metric("CPL líq.", data.fmt_brl(totals["cpl"], 2), d, delta_color=c,
              help="Investimento líquido / Leads produtivos.")

with k6.container(border=True):
    d, c = _delta(totals["cac"], prev["cac"], invert=True)
    st.metric("CAC líq.", data.fmt_brl(totals["cac"], 2), d, delta_color=c,
              help="Investimento líquido / Vendas.")

with k7.container(border=True):
    d, c = _delta(totals["rate"], prev["rate"])
    st.metric("Lead → Venda", data.fmt_pct(totals["rate"]), d, delta_color=c,
              help="Vendas / Leads produtivos.")

st.divider()

# ------------------------------------------------------------------
# Funil completo Google / Meta
# ------------------------------------------------------------------
prev_google_df, prev_meta_df = None, None
if compare:
    prev_google_df = data.build_google_df(prev_d_ini, prev_d_fim)
    prev_meta_df = data.build_meta_df(prev_d_ini, prev_d_fim)


def _sort_controls(key_prefix, step_labels, step_keys):
    labels = ["Cliques", "Partner", "Bruto", "Cashback", "Líquido", *step_labels, "CPL líq.", "CAC líq.", "Cliques→Venda"]
    keys = ["cliques", "id_mp", "bruto", "cashback", "liquido", *step_keys, "cpl", "cac", "conv_final"]
    c1, c2 = st.columns([2, 1])
    with c1:
        label = st.selectbox("Ordenar por", labels, label_visibility="collapsed", key=f"{key_prefix}_sort_col")
    with c2:
        direction = st.segmented_control("Direção", ["Desc", "Asc"], default="Desc",
                                          label_visibility="collapsed", key=f"{key_prefix}_sort_dir")
    return keys[labels.index(label)], (direction == "Asc")


if not canal_filter or canal_filter == "google":
    st.markdown('<h2 style="font-size:18px;">Funil completo Google '
                '<span class="canal-tag google">google</span></h2>', unsafe_allow_html=True)
    g_df = data.build_google_df(d_ini, d_fim)
    step_keys, step_labels, min_cliques = data.funnel_step_config("google")
    sort_col, ascending = _sort_controls("fg", step_labels, step_keys)
    g_df = g_df.sort_values(sort_col, ascending=ascending, na_position="last")
    st.markdown(tables.render_funnel_table(g_df, step_keys, step_labels, min_cliques, prev_google_df, compare),
                unsafe_allow_html=True)
    st.markdown(
        '<div class="legend-row"><span class="sw"><i style="background:var(--crit)"></i></span> '
        'pior que a mediana (&lt;50% / CAC &gt;200%) · <span class="sw"><i style="background:var(--good)"></i></span> '
        'melhor que a mediana · só partners com Cliques ≥ 30 entram na comparação.</div>',
        unsafe_allow_html=True,
    )
    st.write("")

if not canal_filter or canal_filter == "meta":
    st.markdown('<h2 style="font-size:18px;">Funil completo Meta WhatsApp '
                '<span class="canal-tag meta">meta</span></h2>', unsafe_allow_html=True)
    m_df = data.build_meta_df(d_ini, d_fim)
    step_keys, step_labels, min_cliques = data.funnel_step_config("meta")
    sort_col, ascending = _sort_controls("fm", step_labels, step_keys)
    m_df = m_df.sort_values(sort_col, ascending=ascending, na_position="last")
    st.markdown(tables.render_funnel_table(m_df, step_keys, step_labels, min_cliques, prev_meta_df, compare),
                unsafe_allow_html=True)
    st.markdown(
        '<div class="legend-row"><span class="sw"><i style="background:var(--crit)"></i></span> '
        'pior que a mediana · <span class="sw"><i style="background:var(--good)"></i></span> melhor · '
        'só partners com Cliques ≥ 100 entram (Meta tem mais volume bruto de cliques).</div>',
        unsafe_allow_html=True,
    )
    st.write("")

st.divider()

# ------------------------------------------------------------------
# Cobertura e Assertividade
# ------------------------------------------------------------------
st.markdown('<h2 style="font-size:18px;">Análise de Cobertura e Assertividade</h2>', unsafe_allow_html=True)
cov_df = data.build_coverage_df(d_ini, d_fim, canal_filter)
st.markdown(tables.render_coverage_table(cov_df), unsafe_allow_html=True)
st.caption("Uma linha por partner, Google e Meta lado a lado (cada canal tem sua própria base — "
           "Clickoff pro Google, Chat start pro Meta). % Cashback: alto = lead caiu fora da cobertura "
           "do anunciante. % Assertividade = Leads c/ cobertura / Leads totais.")

st.divider()

# ------------------------------------------------------------------
# Progressão por partner
# ------------------------------------------------------------------
st.markdown('<h2 style="font-size:18px;">Progressão por Partner</h2>', unsafe_allow_html=True)
prog_gran = st.segmented_control("Granularidade — progressão", ["Mensal", "Semanal"], default="Mensal",
                                  label_visibility="collapsed", key="prog_gran")
if not selected_partners:
    st.markdown('<div class="empty-hint">↑ Selecione 1 ou mais <strong>Partners</strong> no filtro do topo '
                'pra ver a progressão deles ao longo do tempo.</div>', unsafe_allow_html=True)
else:
    for id_mp in selected_partners:
        st.markdown(f"**{id_mp}**")
        prog_df = data.build_progressao_df(id_mp, "weekly" if prog_gran == "Semanal" else "monthly")
        st.markdown(tables.render_progressao_table(prog_df), unsafe_allow_html=True)
        st.write("")
st.caption("\\* Leads produtivos: `source` em google/whatsapp e `lead_accepted=true`.")

st.divider()

# ------------------------------------------------------------------
# Evolução das taxas de conversão
# ------------------------------------------------------------------
st.markdown('<h2 style="font-size:18px;">Evolução das taxas de conversão</h2>', unsafe_allow_html=True)
taxas_gran = st.segmented_control("Granularidade — taxas", ["Mensal", "Semanal"], default="Semanal",
                                   label_visibility="collapsed", key="taxas_gran")
if not selected_partners:
    st.markdown('<div class="empty-hint">↑ Selecione 1 ou mais <strong>Partners</strong> no filtro do topo '
                'pra ver a evolução das taxas de conversão.</div>', unsafe_allow_html=True)
else:
    gran_key = "weekly" if taxas_gran == "Semanal" else "monthly"
    gran_label = "sem." if gran_key == "weekly" else "mês"
    for id_mp in selected_partners:
        st.markdown(f"**{id_mp}**")
        taxas_df = data.build_taxas_df(id_mp, gran_key)
        st.markdown('<div class="taxas-channel google"><h4>Google</h4></div>', unsafe_allow_html=True)
        st.markdown(tables.render_taxas_block(taxas_df, data.STAGES_G, gran_label), unsafe_allow_html=True)
        st.markdown('<div class="taxas-channel meta"><h4>Meta</h4></div>', unsafe_allow_html=True)
        st.markdown(tables.render_taxas_block(taxas_df, data.STAGES_M, gran_label), unsafe_allow_html=True)
        st.write("")
st.caption("Cor do delta: verde = taxa subiu, vermelho = caiu. "
           "\"—\" quando o denominador é menor que 5.")

st.divider()

# ------------------------------------------------------------------
# Evolução de métricas ao longo do tempo (teste)
# ------------------------------------------------------------------
CHART_METRICS = [
    {"key": "lead_venda", "label": "Geral — Lead → Venda (combinada G+M)", "source": "prog", "unit": "pct"},
    {"key": "cpl", "label": "Geral — CPL líq. (combinado G+M)", "source": "prog", "unit": "brl"},
    {"key": "cac", "label": "Geral — CAC líq. (combinado G+M)", "source": "prog", "unit": "brl"},
]
for from_l, to_l, num_k, den_k in data.STAGES_G:
    CHART_METRICS.append({"key": f"g_{num_k}", "label": f"Google — {from_l} → {to_l}",
                           "source": "taxas", "unit": "pct", "num_key": num_k, "den_key": den_k})
for from_l, to_l, num_k, den_k in data.STAGES_M:
    CHART_METRICS.append({"key": f"m_{num_k}", "label": f"Meta — {from_l} → {to_l}",
                           "source": "taxas", "unit": "pct", "num_key": num_k, "den_key": den_k})


def _chart_series_for(id_mp, metric, gran_key):
    if metric["source"] == "prog":
        df = data.build_progressao_df(id_mp, gran_key)
        return list(zip(df["label"], df[metric["key"]]))
    df = data.build_taxas_df(id_mp, gran_key)
    return [(r["label"], data.taxa_value(r[metric["num_key"]], r[metric["den_key"]])) for _, r in df.iterrows()]


st.markdown(
    '<h2 style="font-size:18px;">Evolução de métricas ao longo do tempo '
    '<span style="font-size:11px;font-weight:400;color:var(--mut);border:1px solid var(--bd);'
    'border-radius:4px;padding:1px 6px;">teste</span></h2>',
    unsafe_allow_html=True,
)
tc1, tc2 = st.columns([3, 1])
with tc1:
    metric_label = st.selectbox("Métrica", [m["label"] for m in CHART_METRICS], label_visibility="collapsed")
with tc2:
    chart_gran = st.segmented_control("Granularidade — gráfico", ["Mensal", "Semanal"], default="Semanal",
                                       label_visibility="collapsed", key="chart_gran")
metric = next(m for m in CHART_METRICS if m["label"] == metric_label)
chart_gran_key = "weekly" if chart_gran == "Semanal" else "monthly"

if not selected_partners:
    st.markdown('<div class="empty-hint">↑ Selecione 1 ou mais <strong>Partners</strong> no filtro do topo '
                'pra ver a evolução dessa métrica ao longo do tempo.</div>', unsafe_allow_html=True)
else:
    fig = go.Figure()
    for id_mp in selected_partners:
        series = _chart_series_for(id_mp, metric, chart_gran_key)
        labels = [s[0] for s in series]
        values = [s[1] for s in series]
        fig.add_trace(go.Scatter(
            x=labels, y=values, mode="lines+markers", name=id_mp, connectgaps=True,
            line=dict(color=data.PARTNER_COLORS[id_mp], width=2), marker=dict(size=5),
            hovertemplate="%{fullData.name} · %{x}: " + ("%{y:.1%}" if metric["unit"] == "pct" else "R$ %{y:,.0f}") + "<extra></extra>",
        ))
    fig.update_layout(
        height=360, margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="rgba(128,128,128,0.15)",
                   tickformat=".0%" if metric["unit"] == "pct" else None,
                   rangemode="tozero" if metric["unit"] == "pct" else "normal"),
    )
    st.plotly_chart(fig, use_container_width=True)
st.caption("Métricas combinadas (Lead→Venda, CPL, CAC) somam Google + Meta. Etapas do funil usam a mesma "
           "regra de base mínima da Evolução das taxas de conversão (denominador < 5 vira ponto vazio).")
