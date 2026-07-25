"""Aba 1 — o dashboard.

Corpo movido de app.py em 2026-07-24, quando o app virou hub de 3 abas; o
conteúdo em si não mudou. Lê o snapshot semanal de data/latest.json — nenhuma
query ao vivo acontece aqui.
"""

from datetime import date

import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

import data
import style
import tables


snap = data.SNAPSHOT["snapshot"]



def render():
    def section_title(inner_html, tip_md):
        """Título de seção + popover "i" com a metodologia/fórmula/gotchas,
    equivalente ao .tip-content do dashboard HTML."""
        c1, c2 = st.columns([30, 1])
        with c1:
            st.markdown(f'<h2 style="font-size:18px;margin-bottom:0;">{inner_html}</h2>', unsafe_allow_html=True)
        with c2:
            with st.popover("ℹ️", use_container_width=True):
                st.markdown(tip_md)


    # ------------------------------------------------------------------
    # Header + badge de frescor (dinâmico: verde <24h / amarelo <72h / vermelho >=72h)
    # ------------------------------------------------------------------
    age_h = data.snapshot_age_hours()
    badge_cls = "" if age_h < 24 else ("warn" if age_h < 72 else "crit")
    if age_h < 1:
        human_age = "agora há pouco"
    elif age_h < 24:
        human_age = f"{int(age_h)}h atrás"
    else:
        human_age = f"{int(age_h // 24)}d atrás"

    st.markdown(
        f'<h1 style="font-size:26px;font-weight:700;margin-bottom:2px;">'
    f'MP Agência — Funil Ads-to-Sale'
    f'<span class="snap-badge {badge_cls}">snapshot {human_age} (até {snap["label"]})</span></h1>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Atribuição pelo anunciante. Investimento via `performance_partner_mp_agency`; "
    "eventos via `comparison.*` + `whatsapp_assistant.*`; leads/vendas via `checkout.lead_detail`. "
    "CPL/CAC sobre líquido."
    )

    # ------------------------------------------------------------------
    # Filtros -- estado inicial restaurado da URL (st.query_params), reescrito
    # a cada rerun. Permite bookmark/compartilhar link com filtro aplicado
    # (equivalente ao localStorage do HTML, mas funciona entre pessoas/dispositivos).
    # ------------------------------------------------------------------
    qp = st.query_params
    month_keys = data.available_month_keys()
    month_options = ["—"] + [data.month_label(mk) for mk in month_keys]

    period_qp = qp.get("period", "30d")
    if period_qp not in ("7d", "30d", "90d"):
        period_qp = "30d"
    month_qp = qp.get("month", "—")
    if month_qp not in month_options:
        month_qp = "—"
    canal_qp = qp.get("canal", "Todos")
    if canal_qp not in ("Todos", "Google", "Meta"):
        canal_qp = "Todos"
    compare_qp = qp.get("compare", "0") == "1"
    partner_qp = [p for p in qp.get_all("partner") if p in data.PARTNERS]
    custom_start_qp, custom_end_qp = qp.get("custom_start"), qp.get("custom_end")
    custom_default = ()
    if custom_start_qp and custom_end_qp:
        try:
            custom_default = (date.fromisoformat(custom_start_qp), date.fromisoformat(custom_end_qp))
        except ValueError:
            custom_default = ()

    with st.container(border=True):
        f1, f2, f3, f4 = st.columns([3.2, 1.4, 2.2, 1.4])
        with f1:
            st.caption("PERÍODO")
            p1, p2 = st.columns([1.6, 1], gap="small")
            with p1:
                period = st.segmented_control("Período", ["7d", "30d", "90d"], default=period_qp,
                                               label_visibility="collapsed")
            with p2:
                if custom_default:
                    pop_label = f"📅 {custom_default[0].strftime('%d/%m')}–{custom_default[1].strftime('%d/%m')}"
                elif month_qp != "—":
                    pop_label = f"📅 {month_qp}"
                else:
                    pop_label = "📅 outro"
                with st.popover(pop_label, use_container_width=True, help="Filtrar por mês fechado ou período customizado"):
                    month = st.selectbox("Mês", month_options, index=month_options.index(month_qp))
                    custom_range = st.date_input(
                        "Período customizado", value=custom_default, format="DD/MM/YYYY",
                        min_value=data.MIN_DATE, max_value=data.CUTOFF_DATE,
                        help="Selecione data inicial e final — sobrepõe Período/Mês quando preenchido.",
                    )
        with f2:
            st.caption("CANAL")
            canal_label = st.segmented_control("Canal", ["Todos", "Google", "Meta"], default=canal_qp,
                                                label_visibility="collapsed")
            canal_filter = None if canal_label in (None, "Todos") else canal_label.lower()
        with f3:
            st.caption("PARTNER")
            selected_partners = st.multiselect("Partner", data.PARTNERS, default=partner_qp, label_visibility="collapsed",
                                                placeholder="Todos")
        with f4:
            st.caption("COMPARAR")
            compare = st.toggle("Δ vs período anterior", value=compare_qp)

    custom_invalid = len(custom_range) == 2 and custom_range[0] > custom_range[1]
    if len(custom_range) == 2 and not custom_invalid:
        d_ini, d_fim = custom_range[0].isoformat(), custom_range[1].isoformat()
        janela_label = f"período customizado ({d_ini} a {d_fim})"
    else:
        if custom_invalid:
            st.warning("Data inicial é depois da final — período customizado ignorado, usando Período/Mês.")
        if month != "—":
            period_key = month_keys[month_options.index(month) - 1]
        else:
            period_key = period or "30d"
        d_ini, d_fim = data.period_window(period_key)
        janela_label = f"{d_ini} a {d_fim}"

    # reflete o estado atual na URL -- clear()+update() garante que chaves obsoletas
    # (ex.: custom_start ao voltar pro período preset) somem.
    qp_out = {
        "period": period or "30d",
        "month": month,
        "canal": canal_label or "Todos",
        "compare": "1" if compare else "0",
    }
    if selected_partners:
        qp_out["partner"] = selected_partners
    if len(custom_range) == 2:
        qp_out["custom_start"] = custom_range[0].isoformat()
        qp_out["custom_end"] = custom_range[1].isoformat()
    st.query_params.clear()
    st.query_params.update(qp_out)

    st.caption(f"ℹ️ Snapshot {snap['label']} · janela selecionada: {janela_label}.")

    # ------------------------------------------------------------------
    # KPIs
    # ------------------------------------------------------------------
    totals = data.compute_totals(d_ini, d_fim, canal_filter)
    prev_d_ini, prev_d_fim = data.previous_window(d_ini, d_fim)
    prev = data.compute_totals(prev_d_ini, prev_d_fim, canal_filter)


    def _inline_partners(key_prefix):
        """Seletor de partner local da seção.

    Herda o filtro do topo; mexer aqui vale só pra esta seção — evita rolar até
    o topo só pra trocar de conta. A key embute o filtro do topo de propósito:
    quando ele muda, o widget é recriado e volta a herdar, em vez de ficar
    preso num valor antigo (é o que dispensa a sincronização manual via
    session_state que o handoff apontava como cara demais).
    """
        stamp = "|".join(selected_partners) or "todos"
        return st.multiselect(
            "Partners desta seção", data.PARTNERS, default=selected_partners,
            key=f"{key_prefix}_partners_{stamp}", label_visibility="collapsed",
            placeholder="Partners desta seção — vazio usa o filtro do topo")


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



    TIP_FUNIL_GOOGLE = """
**Etapas:**
- **Cliques**: `ads.google_ads_campaigns_daily_data` (join `name = config.campaign_name`)
- **Sessões**: `comparison.page_load` (distinct session_id)
- **Zip search**: `comparison.zip_search_click`
- **Clickoff**: `comparison.clickoff`
- **Redirect**: `comparison.clickoff_redirect`
- **Leads/Vendas**: `checkout.lead_detail` com `source='google'`, `lead_accepted=true`, atribuído por
  `campaign = config.utm_campaign` — não por `partner_id_partner` (por isso pode divergir levemente do
  KPI "Leads produtivos" no topo em período customizado)

**Atribuição:** via `config.utm_campaign` (`deleted_at IS NULL` — sem filtro de `status`, de propósito).

---
**Alerta visual:** fundo vermelho indica taxa <50% da mediana (ou CAC >200%); fundo verde indica o oposto.
Só conta partners com Cliques ≥ 30 na mediana.

---
**Gotchas:**
- A config NÃO filtra `status='enabled'`, de propósito: The Fiber e Enove tinham config `disabled` mas
  investimento real rodando, e sumiam do funil. Ignorar o status é o comportamento correto.
- Sessões pode ser > Cliques (inclui tráfego não-ads).
- Clickoff pode ocorrer sem passar por Zip search.
"""

    TIP_FUNIL_META = """
**Etapas (todas de `whatsapp_assistant.*`):**
- **Chat start**: `wa_chat_start`
- **Zip search**: `wa_zip_search`
- **Get plans**: `wa_get_plans`
- **Redirect**: `wa_redirect`
- **Leads/Vendas**: `checkout.lead_detail` com `source='whatsapp'`, `lead_accepted=true`, atribuído via chat
  (`wa_chat_start.user_id` ↔ `lead_detail.user_id`, janela 7d) — não por `partner_id_partner` (por isso pode
  divergir levemente do KPI "Leads produtivos" no topo em período customizado)

**Atribuição:** via `referral_agent_label LIKE 'mpa.X@Y'` (lista hardcoded de 10 variações → 8 partners).
Lead conectado ao chat via `user_id` com janela 7d antes.

---
**Alerta visual:** fundo vermelho indica taxa <50% da mediana (ou CAC >200%); fundo verde indica o oposto.
Só conta partners com Cliques ≥ 100 na mediana (Meta tem mais volume bruto de cliques que Google).

---
**Gotchas:**
- Zip search e Get plans têm volume idêntico (disparados juntos pelo bot).
- Desktop excluído (não é cliente MP Agência).
- Unifique vira 100% cashback no histórico — leads vão pra outros provedores.
"""

    if not canal_filter or canal_filter == "google":
        section_title('Funil completo Google <span class="canal-tag google">google</span>', TIP_FUNIL_GOOGLE)
        g_df = data.build_google_df(d_ini, d_fim)
        step_keys, step_labels, min_cliques = data.funnel_step_config("google")
        g_df = g_df.sort_values("cliques", ascending=False, na_position="last")
        components.html(
            tables.sortable_doc(
                tables.render_funnel_table(g_df, step_keys, step_labels, min_cliques, prev_google_df, compare),
                style.CSS),
            height=tables.sortable_table_height(len(g_df), compare=compare), scrolling=True)
        st.markdown(
            '<div class="legend-row"><span class="sw"><i class="bad"></i></span> '
        'pior que a mediana (&lt;50% / CAC &gt;200%) · <span class="sw"><i class="good"></i></span> '
        'melhor que a mediana · só partners com Cliques ≥ 30 entram na comparação. '
        'Clique no cabeçalho pra ordenar.</div>',
            unsafe_allow_html=True,
        )
        st.write("")

    if not canal_filter or canal_filter == "meta":
        section_title('Funil completo Meta WhatsApp <span class="canal-tag meta">meta</span>', TIP_FUNIL_META)
        m_df = data.build_meta_df(d_ini, d_fim)
        step_keys, step_labels, min_cliques = data.funnel_step_config("meta")
        m_df = m_df.sort_values("cliques", ascending=False, na_position="last")
        components.html(
            tables.sortable_doc(
                tables.render_funnel_table(m_df, step_keys, step_labels, min_cliques, prev_meta_df, compare),
                style.CSS),
            height=tables.sortable_table_height(len(m_df), compare=compare), scrolling=True)
        st.markdown(
            '<div class="legend-row"><span class="sw"><i class="bad"></i></span> '
        'pior que a mediana · <span class="sw"><i class="good"></i></span> melhor · '
        'só partners com Cliques ≥ 100 entram (Meta tem mais volume bruto de cliques). '
        'Clique no cabeçalho pra ordenar.</div>',
            unsafe_allow_html=True,
        )
        st.write("")

    st.divider()

    # ------------------------------------------------------------------
    # Cobertura e Assertividade
    # ------------------------------------------------------------------
    TIP_COBERTURA = """
**3 indicadores combinados:**
- **% Cashback** = cashback / bruto. Mede quanto do investimento voltou como cashback (leads/redirects pra
  outros provedores). Alto = muito reaproveitamento fora da cobertura do anunciante.
- **Vol. base** = denominador da assertividade: **Clickoff** pro Google, **Chat start** pro Meta.
- **% Assertividade** = leads produtivos / Vol. base. Mede: dos clickoffs/chats gerados pelo tráfego pago,
  quantos viraram lead no anunciante.

---
**Destaque visual:** verde = melhor que mediana, vermelho = pior. Pra %Cashback alto é tratado como "ruim"
(pouca conversão pro anunciante); pra %Assertividade alto é "bom". Só entram na mediana partners com
Bruto ≥ R$100 (cashback) ou Vol. base ≥ 20 (assertividade).

---
Leads aqui seguem a mesma atribuição por campanha/chat das tabelas de Funil completo em 7d/30d/90d/mês;
em período customizado usa `partner_id_partner` direto — os dois métodos podem divergir levemente.
"""

    section_title("Análise de Cobertura e Assertividade", TIP_COBERTURA)
    cov_df = data.build_coverage_df(d_ini, d_fim, canal_filter)
    st.markdown(tables.render_coverage_table(cov_df), unsafe_allow_html=True)
    st.caption("Uma linha por partner, Google e Meta lado a lado (cada canal tem sua própria base — "
           "Clickoff pro Google, Chat start pro Meta). % Cashback: alto = lead caiu fora da cobertura "
           "do anunciante. % Assertividade = Leads c/ cobertura / Leads totais.")

    st.divider()

    # ------------------------------------------------------------------
    # Progressão por partner
    # ------------------------------------------------------------------
    TIP_PROGRESSAO = """
**Aparece quando você seleciona um partner específico** no filtro.

Linhas = métricas-chave. Colunas = períodos.
Toggle **Mensal** (últimos 5 meses fechados) ou **Semanal** (últimas 12 semanas).

**Métricas mostradas:**
- Investimento bruto / cashback / líquido / %Cashback
- Cliques Google + Meta
- Clickoff (Google) e Chat start (Meta)
- Leads e Vendas
- CPL líq. e CAC líq.
- **%Assertividade Google** = Leads Google / Clickoff Google
- **%Assertividade Meta** = Leads Meta / Chat start Meta
- Lead → Venda

Os dados são extraídos das mesmas fontes das outras seções (consistente com filtros aplicados).
"""

    section_title("Progressão por Partner", TIP_PROGRESSAO)
    pg1, pg2 = st.columns([1, 2.4])
    with pg1:
        prog_gran = st.segmented_control("Granularidade — progressão", ["Mensal", "Semanal"], default="Mensal",
                                          label_visibility="collapsed", key="prog_gran")
    with pg2:
        prog_partners = _inline_partners("prog")
    if not prog_partners:
        st.markdown('<div class="empty-hint">Selecione 1 ou mais <strong>Partners</strong> acima '
                '(ou no filtro do topo) pra ver a progressão deles ao longo do tempo.</div>',
                    unsafe_allow_html=True)
    else:
        for id_mp in prog_partners:
            st.markdown(f"**{id_mp}**")
            prog_df = data.build_progressao_df(id_mp, "weekly" if prog_gran == "Semanal" else "monthly")
            st.markdown(tables.render_progressao_table(prog_df), unsafe_allow_html=True)
            st.write("")
    st.caption("\\* Leads produtivos: `source` em google/whatsapp e `lead_accepted=true`.")

    st.divider()

    # ------------------------------------------------------------------
    # Evolução das taxas de conversão
    # ------------------------------------------------------------------
    TIP_TAXAS = """
**Aparece quando você seleciona um partner específico** no filtro.

Cada linha é uma **etapa do funil**, cada coluna é um período. A última coluna mostra a **trajetória
compacta** (sparkline) e a **variação em pontos percentuais** vs. o período anterior.

**Google:** Clique→Sessão, Sessão→Clickoff, Clickoff→Redirect, Redirect→Lead, Lead→Venda

**Meta:** Clique→Chat start, Chat start→Zip search, Zip search→Redirect, Redirect→Lead, Lead→Venda

Fonte: mesmos eventos do "Funil completo" acima, agregados por semana/mês.

Quando o **denominador é menor que 5**, a célula mostra a contagem bruta ("3/4") em vez da taxa,
pra não induzir a erro com base pequena.
"""

    section_title("Evolução das taxas de conversão", TIP_TAXAS)
    tx1, tx2 = st.columns([1, 2.4])
    with tx1:
        taxas_gran = st.segmented_control("Granularidade — taxas", ["Mensal", "Semanal"], default="Semanal",
                                           label_visibility="collapsed", key="taxas_gran")
    with tx2:
        taxas_partners = _inline_partners("taxas")
    if not taxas_partners:
        st.markdown('<div class="empty-hint">Selecione 1 ou mais <strong>Partners</strong> acima '
                '(ou no filtro do topo) pra ver a evolução das taxas de conversão.</div>',
                    unsafe_allow_html=True)
    else:
        gran_key = "weekly" if taxas_gran == "Semanal" else "monthly"
        gran_label = "sem." if gran_key == "weekly" else "mês"
        for id_mp in taxas_partners:
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
    # Detalhamento investimento x leads x vendas
    # ------------------------------------------------------------------
    TIP_DETALHAMENTO = """
**Consolidado por partner** (soma Google + Meta quando filtro Canal = Todos).

Mesmos filtros das tabelas de funil acima:
- Lead: `source IN ('google','whatsapp')`, `lead_accepted = true`
- Venda: `current_situation IN ('sold','installed','scheduled')`
- Investimento: `raw_investment`, `cashback` e `partnership_net_daily_spend` de `performance_partner_mp_agency`

**Atribuição do lead:** em 7d/30d/90d/mês, por campanha/chat (igual Funil completo); em período
customizado, direto por `partner_id_partner`. Os dois podem divergir levemente pro mesmo partner/período.

CPL e CAC sobre líquido.

---
**Alerta visual** em Lead→Venda, CAC e CPL: fundo vermelho se <50% (ou >200% pro CAC) da mediana;
verde no oposto. Só partners com Leads ≥ 3 entram na comparação.

---
**Linha inteira em destaque:** partner com bruto > 0 mas leads = 0 — dinheiro investido sem gerar nenhum lead.
"""

    section_title("Detalhamento investimento × leads × vendas", TIP_DETALHAMENTO)
    detail_df = data.build_detail_df(d_ini, d_fim, canal_filter)
    detail_meds = data.detail_medians(detail_df)
    detail_df = detail_df.sort_values("liquido", ascending=False, na_position="last")
    prev_detail_df = data.build_detail_df(prev_d_ini, prev_d_fim, canal_filter) if compare else None
    components.html(
        tables.sortable_doc(tables.render_detail_table(detail_df, detail_meds, prev_detail_df, compare), style.CSS),
        height=tables.sortable_table_height(len(detail_df), tables.ROW_H_PLAIN, compare), scrolling=True)
    st.markdown(
        '<div class="legend-row"><span class="sw"><i class="bad"></i></span> '
    'pior que a mediana · <span class="sw"><i class="good"></i></span> melhor que a mediana · '
    '<span class="sw"><i style="background:var(--warn)"></i></span> bruto &gt; 0 e leads = 0.</div>',
        unsafe_allow_html=True,
    )

    st.divider()

    # ------------------------------------------------------------------
    # Crédito Remanescente por Parceiro
    # ------------------------------------------------------------------
    TIP_CREDITO = """
**Fonte:** `credit_remaining` em `performance_partner_mp_agency`, agregado por semana × partnership_id.
Cada ponto no gráfico é a média do saldo diário na semana, não o valor no último dia dela.

Mostra a evolução do crédito disponível pra mídia de cada parceiro ao longo do tempo. Cada salto pra cima
indica recarga (aumento do `total_credit`); a queda gradual reflete o consumo pelo investimento diário.

**Valor negativo**: o partner gastou mais do que tinha de crédito ativo no período — pode ser política de
adiantamento ou ajuste retroativo do MP.

Filtros de canal/período não se aplicam aqui (a métrica é por parceiro, agregada) — o filtro de Partner
continua valendo.
"""

    section_title("Crédito Remanescente por Parceiro", TIP_CREDITO)
    credit_partners = selected_partners if selected_partners else list(data.CREDIT_TIMESERIES.keys())
    all_days = sorted({r["semana"] for p in credit_partners for r in data.CREDIT_TIMESERIES.get(p, [])})
    if not all_days:
        st.markdown('<div class="empty-hint">Sem dados de crédito remanescente pro filtro atual.</div>',
                    unsafe_allow_html=True)
    else:
        fig_credit = go.Figure()
        for p in credit_partners:
            by_day = {r["semana"]: r["credito"] for r in data.CREDIT_TIMESERIES.get(p, [])}
            y = [by_day.get(d) for d in all_days]
            fig_credit.add_trace(go.Scatter(
                x=all_days, y=y, mode="lines", name=p, connectgaps=True,
                line=dict(color=data.PARTNER_COLORS.get(p, "#64748b"), width=2),
                hovertemplate="%{fullData.name} · %{x|%d/%m/%y}: R$ %{y:,.0f}<extra></extra>",
            ))
        fig_credit.update_layout(
            height=320, margin=dict(l=10, r=10, t=10, b=10),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            xaxis=dict(showgrid=False, type="date", tickformat="%d/%m/%y"),
            yaxis=dict(showgrid=True, gridcolor="rgba(128,128,128,0.15)", title="Crédito remanescente (R$)"),
        )
        st.plotly_chart(fig_credit, use_container_width=True)
    st.caption("Clique num item da legenda pra ocultar/exibir a linha do parceiro.")

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
    tc1, tc2, tc3 = st.columns([2, 1, 2.4])
    with tc1:
        metric_label = st.selectbox("Métrica", [m["label"] for m in CHART_METRICS], label_visibility="collapsed")
    with tc2:
        chart_gran = st.segmented_control("Granularidade — gráfico", ["Mensal", "Semanal"], default="Semanal",
                                           label_visibility="collapsed", key="chart_gran")
    with tc3:
        chart_partners = _inline_partners("chart")
    metric = next(m for m in CHART_METRICS if m["label"] == metric_label)
    chart_gran_key = "weekly" if chart_gran == "Semanal" else "monthly"

    if not chart_partners:
        st.markdown('<div class="empty-hint">Selecione 1 ou mais <strong>Partners</strong> acima '
                '(ou no filtro do topo) pra ver a evolução dessa métrica ao longo do tempo.</div>',
                    unsafe_allow_html=True)
    else:
        fig = go.Figure()
        for id_mp in chart_partners:
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

