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
    "CPL/CAC sobre líquido. *Protótipo — dados ilustrativos, sem conexão com Metabase/Redshift.*"
)

# ------------------------------------------------------------------
# Filtros
# ------------------------------------------------------------------
with st.container(border=True):
    f1, f2, f3, f4 = st.columns([2.4, 1.8, 2.4, 1.6])
    with f1:
        st.caption("PERÍODO")
        period = st.segmented_control("Período", ["7d", "30d", "90d"], default="30d", label_visibility="collapsed")
        month = st.selectbox("Mês", ["—", "jul/26", "jun/26", "mai/26", "abr/26", "mar/26", "fev/26"],
                              label_visibility="collapsed")
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

st.caption(f"ℹ️ Snapshot {snap['label']} · período/mês ainda não reprocessam o snapshot ilustrativo neste protótipo.")

# ------------------------------------------------------------------
# KPIs
# ------------------------------------------------------------------
totals = data.compute_totals(canal_filter)
prev = {
    "liquido": totals["liquido"] * 0.958, "leads": totals["leads"] / 1.071, "vendas": totals["vendas"] / 1.035,
    "cpl": totals["cpl"] * 1.024 if totals["cpl"] else None,
    "cac": totals["cac"] / 1.018 if totals["cac"] else None,
    "rate": totals["rate"] / 0.996 if totals["rate"] else None,
}


def _delta(curr, prev_v, invert=False):
    if not compare or curr is None or not prev_v:
        return None, "off"
    pct = (curr - prev_v) / abs(prev_v) * 100
    return f"{pct:+.1f}%", ("inverse" if invert else "normal")


k1, k2, k3, k4, k5, k6 = st.columns(6)
d, c = _delta(totals["liquido"], prev["liquido"])
k1.metric("Investimento líquido", data.fmt_brl(totals["liquido"]), d, delta_color="off",
          help="Bruto − Cashback. Fonte: performance_partner_mp_agency.")
d, c = _delta(totals["leads"], prev["leads"])
k2.metric("Leads produtivos", data.fmt_num(totals["leads"]), d, delta_color=c,
          help="source em google/whatsapp e lead_accepted=true.")
d, c = _delta(totals["vendas"], prev["vendas"])
k3.metric("Vendas", data.fmt_num(totals["vendas"]), d, delta_color=c,
          help="current_situation IN (sold, installed, scheduled).")
d, c = _delta(totals["cpl"], prev["cpl"], invert=True)
k4.metric("CPL líq.", data.fmt_brl(totals["cpl"], 2), d, delta_color=c,
          help="Investimento líquido / Leads produtivos.")
d, c = _delta(totals["cac"], prev["cac"], invert=True)
k5.metric("CAC líq.", data.fmt_brl(totals["cac"], 2), d, delta_color=c,
          help="Investimento líquido / Vendas.")
d, c = _delta(totals["rate"], prev["rate"])
k6.metric("Lead → Venda", data.fmt_pct(totals["rate"]), d, delta_color=c,
          help="Vendas / Leads produtivos.")

st.divider()

# ------------------------------------------------------------------
# Funil completo Google / Meta
# ------------------------------------------------------------------
if not canal_filter or canal_filter == "google":
    st.markdown('<h2 style="font-size:18px;">Funil completo Google '
                '<span class="canal-tag google">google</span></h2>', unsafe_allow_html=True)
    g_df = data.build_google_df()
    step_keys, step_labels, min_cliques = data.funnel_step_config("google")
    st.markdown(tables.render_funnel_table(g_df, step_keys, step_labels, min_cliques), unsafe_allow_html=True)
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
    m_df = data.build_meta_df()
    step_keys, step_labels, min_cliques = data.funnel_step_config("meta")
    st.markdown(tables.render_funnel_table(m_df, step_keys, step_labels, min_cliques), unsafe_allow_html=True)
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
cov_df = data.build_coverage_df(canal_filter)
st.markdown(tables.render_coverage_table(cov_df), unsafe_allow_html=True)
st.caption("% Cashback: alto = lead caiu fora da cobertura do anunciante. "
           "% Assertividade = leads produtivos / Vol. base (Clickoff no Google, Chat start no Meta).")

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
# Detalhamento consolidado
# ------------------------------------------------------------------
st.markdown('<h2 style="font-size:18px;">Detalhamento investimento × leads × vendas</h2>', unsafe_allow_html=True)
detail_df = data.build_detail_df(canal_filter)
st.markdown(tables.render_detail_table(detail_df), unsafe_allow_html=True)
st.markdown(
    '<div class="legend-row"><span class="sw"><i style="background:var(--crit)"></i></span> pior que a mediana · '
    '<span class="sw"><i style="background:var(--good)"></i></span> melhor · '
    'linha com rail âmbar: bruto &gt; 0 e leads = 0.</div>',
    unsafe_allow_html=True,
)

st.divider()

# ------------------------------------------------------------------
# Crédito remanescente por parceiro
# ------------------------------------------------------------------
st.markdown('<h2 style="font-size:18px;">Crédito Remanescente por Parceiro</h2>', unsafe_allow_html=True)
credit_df = data.build_credit_df(selected_partners or None)

fig = go.Figure()
for id_mp in (selected_partners or data.PARTNERS):
    sub = credit_df[credit_df["id_mp"] == id_mp]
    fig.add_trace(go.Scatter(
        x=sub["semana"], y=sub["credito"], mode="lines+markers", name=id_mp,
        line=dict(color=data.PARTNER_COLORS[id_mp], width=2),
        marker=dict(size=5),
        hovertemplate="%{fullData.name} · sem. %{x}: R$ %{y:,.0f}<extra></extra>",
    ))
fig.update_layout(
    height=380, margin=dict(l=10, r=10, t=10, b=10),
    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    xaxis=dict(title="Semana", showgrid=False),
    yaxis=dict(title="Crédito remanescente (R$)", showgrid=True, gridcolor="rgba(128,128,128,0.15)"),
)
st.plotly_chart(fig, use_container_width=True)
st.caption("Cada ponto = média do saldo diário na semana. "
           "Clique num item da legenda pra ocultar/exibir a linha (nativo do Plotly).")
