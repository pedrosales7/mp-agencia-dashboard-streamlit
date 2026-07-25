#!/usr/bin/env python3
"""Análise IA semanal — pipeline de 3 estágios.

Roda dentro do weekly_refresh (GitHub Actions, terça), NUNCA em runtime do app:
o app é público e uma chamada de LLM por pageview viraria proxy aberto pra cota
do Gemini. Aqui a análise é gerada uma vez e gravada em data/analysis.json; o
Streamlit só renderiza texto pronto.

  Estágio 0 — triagem      · Python puro. Limiares são numéricos e absolutos;
                             comparar número com limiar é o que LLM faz pior.
  Estágio 1 — diagnóstico  · LLM com responseSchema. Julgamento estruturado.
  Estágio 2 — redação      · LLM com tags XML. Recebe SÓ o JSON do estágio 1,
                             nunca o payload — sem números crus na mão, recitar
                             o dashboard fica impossível.

O JSON do estágio 1 é persistido em data/diagnosticos/AAAA-MM-DD.json: é a
entrada do estágio 2 da semana seguinte (bloco "recomendei X, não mexeu") e o
registro histórico auditável.

Config por env var (secrets do repo):
  LLM_API_KEY  — sem ela a análise é pulada em silêncio, o refresh segue.
  LLM_MODEL    — opcional, default gemini-3.1-pro-preview.
"""
import json
import os
import re
import time
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

import requests

DEFAULT_MODEL = "gemini-3.1-pro-preview"
REQUEST_TIMEOUT = 300
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def enabled():
    return bool(os.environ.get("LLM_API_KEY"))


def _model():
    return (os.environ.get("LLM_MODEL") or "").strip() or DEFAULT_MODEL


# ── payload ───────────────────────────────────────────────────────────────

def _window_bounds(cutoff_dt):
    d = cutoff_dt
    return {
        "7d": ((d - timedelta(days=6)).isoformat(), d.isoformat()),
        "7d_prev": ((d - timedelta(days=13)).isoformat(), (d - timedelta(days=7)).isoformat()),
        "30d": ((d - timedelta(days=29)).isoformat(), d.isoformat()),
        "30d_prev": ((d - timedelta(days=59)).isoformat(), (d - timedelta(days=30)).isoformat()),
        "mes_atual": (d.replace(day=1).isoformat(), d.isoformat()),
    }


def _ratio(num, den):
    return round(num / den, 2) if den else None


def _week_start(dia_iso):
    """Segunda-feira da semana do dia — mesma convenção do DATE_TRUNC('week') do Redshift."""
    d = date.fromisoformat(dia_iso)
    return (d - timedelta(days=d.weekday())).isoformat()


def weekly_series(all_daily, all_dfg, all_dfm, cutoff_dt, valid_partners, n_weeks=8):
    """Série semanal por partner × canal, derivada do dado DIÁRIO.

    Substitui o PARTNER_WEEKLY como fonte da série (fix 2026-07-24). Três motivos:
    - o dict do PARTNER_WEEKLY traz `leads_g`/`leads_m`, não `leads` — o
      _trend_summary lia um campo inexistente e devolvia sem_base/0 pra TODO
      partner desde sempre. A tendência nunca funcionou em produção.
    - só tem verba no nível do partner, então CPL/CAC por canal eram impossíveis;
      e não tem impressões, então CTR por semana também não existia — mas o prompt
      mandava ancorar tendência de CTR e impressões nesse campo. O modelo só podia
      inventar.
    - o resto do payload já sai do DAILY_SNAPSHOT/DAILY_FUNNEL_*; derivar daqui
      elimina divergência de atribuição entre a série e as janelas.

    Semanas incompletas são descartadas: o run é terça com cutoff = segunda, então
    o bucket mais recente teria 1 dia só e puxaria toda tendência para "queda".
    """
    fim_ultima_completa = cutoff_dt - timedelta(days=cutoff_dt.weekday() + 1)  # domingo anterior
    ini = (fim_ultima_completa - timedelta(days=7 * n_weeks - 1)).isoformat()
    fim = fim_ultima_completa.isoformat()
    semanas = sorted({_week_start(d) for d in (
        (fim_ultima_completa - timedelta(days=7 * i)).isoformat() for i in range(n_weeks))})

    agg = defaultdict(lambda: defaultdict(float))  # (partner, canal, ws) -> campos
    for r in all_daily:
        if r["id_mp"] in valid_partners and ini <= r["dia"] <= fim:
            for canal in (r["canal"], "total"):
                k = (r["id_mp"], canal, _week_start(r["dia"]))
                for f in ("liquido", "leads", "vendas"):
                    agg[k][f] += r.get(f) or 0
    for rows, canal in ((all_dfg, "google"), (all_dfm, "meta")):
        for r in rows:
            if r["id_mp"] in valid_partners and ini <= r["dia"] <= fim:
                for c in (canal, "total"):
                    k = (r["id_mp"], c, _week_start(r["dia"]))
                    for f in ("cliques", "impressoes"):
                        agg[k][f] += r.get(f) or 0

    out = {}
    for p in valid_partners:
        for canal in ("total", "google", "meta"):
            serie = []
            for ws in semanas:
                v = agg.get((p, canal, ws), {})
                liq = round(v.get("liquido", 0))
                leads, vendas = int(v.get("leads", 0)), int(v.get("vendas", 0))
                cliques, impr = int(v.get("cliques", 0)), int(v.get("impressoes", 0))
                serie.append({
                    "ws": ws, "liquido": liq, "leads": leads, "vendas": vendas,
                    "cliques": cliques, "impressoes": impr,
                    "cpl": _ratio(liq, leads), "cac": _ratio(liq, vendas),
                    "ctr_pct": round(100 * cliques / impr, 2) if impr else None,
                })
            if any(s["liquido"] or s["leads"] or s["cliques"] for s in serie):
                out.setdefault(p, {})[canal] = serie
    return out


TREND_FIELDS = ("leads", "vendas", "cpl", "cac", "cliques", "ctr_pct")


def _trend_summary(serie, field):
    """Direção da série de 8 semanas + estabilidade recente, com baseline por MEDIANA.

    Mediana e não média (fix 2026-07-24): com contagem baixa de vendas, um pico
    único destrói a média e contamina tudo que se compara contra ela.
    Semanas sem base para a métrica (ex.: CAC numa semana sem venda) entram como
    None e são ignoradas, em vez de virar zero e fabricar uma queda.
    """
    vals = [s.get(field) for s in serie]
    vals = [v for v in vals if v is not None]
    n = len(vals)
    if n < 4:
        return None
    half = n // 2
    m1, m2 = median(vals[:half]), median(vals[half:])
    delta_pct = round(100 * (m2 - m1) / m1, 1) if m1 else None
    if delta_pct is None:
        direcao = "sem_base"
    elif delta_pct >= 15:
        direcao = "alta"
    elif delta_pct <= -15:
        direcao = "queda"
    else:
        direcao = "estavel"
    base = median(vals)
    estaveis = 0
    for v in reversed(vals):
        if base and abs(v - base) / base <= 0.15:
            estaveis += 1
        else:
            break
    fmt, quebra = _formato(serie, field, vals, base, direcao)
    return {
        "direcao_8sem": direcao,
        "variacao_pct_1a_vs_2a_metade": delta_pct,
        "semanas_estaveis_consecutivas": estaveis,
        "mediana_8sem": round(base, 2),
        "semanas_com_base": n,
        "formato": fmt,
        "semana_da_quebra": quebra,
        "desvio_atual_vs_mediana_pct": (round(100 * (vals[-1] - base) / base, 1)
                                        if base else None),
    }


# Limiares da classificação de formato. Chute educado do desenho, rodado contra o
# histórico real de 8 semanas dos 8 partners (2026-07-24): os valores em si
# aguentaram, o que precisou de conserto foi a regra de gradual_* (ver abaixo).
# Recalibrar aqui se a classificação começar a discordar do que o time vê no
# dashboard — o desenho lista isso como pendência em aberto.
FMT_SALTO = 0.30      # salto entre semanas consecutivas que caracteriza degrau
FMT_PLATO = 0.15      # dispersão máxima depois do salto pra ainda ser platô
FMT_MONOTONIA = 5     # transições (de 7) na mesma direção pra ser gradual
FMT_RUIDO = 0.40      # desvio-padrão relativo acima disso, sem direção, é ruído


def _formato(serie, field, vals, base, direcao):
    """Classifica o FORMATO da curva, não só a direção.

    `direcao_8sem` compara metade com metade, o que torna indistinguíveis dois
    casos de diagnóstico oposto:
    - degrau: caiu de uma vez e ficou parado → algo mudou numa data específica
      (campanha pausada, verba cortada, segmentação alterada, rastreio quebrado).
      A ação é descobrir o que mudou naquela semana.
    - gradual_queda: cai um pouco toda semana → fadiga de criativo ou leilão
      encarecendo. A ação é rotacionar/relançar.
    O formato É o diagnóstico.
    """
    if len(vals) < 5 or not base:
        return "sem_base", None
    # degrau: um salto grande seguido de platô
    for i in range(1, len(vals) - 1):
        ant, cur = vals[i - 1], vals[i]
        if not ant or abs(cur - ant) / abs(ant) < FMT_SALTO:
            continue
        depois = vals[i:]
        pico = max(abs(v) for v in depois) or 1
        if (max(depois) - min(depois)) / pico <= FMT_PLATO:
            # a semana do salto, no índice da série que tem valor pra esta métrica
            ws = [s["ws"] for s in serie if s.get(field) is not None]
            return "degrau", ws[i] if i < len(ws) else None
    # gradual: maioria das transições na mesma direção E deslocamento acumulado
    # que valha a pena. Sem o teste de magnitude, uma curva que oscila ±2% com 5
    # descidas e 2 subidas virava "gradual_queda" — monotonia sem tamanho não é
    # tendência, é ruído com sorte.
    deltas = [b - a for a, b in zip(vals, vals[1:])]
    sobe = sum(1 for d in deltas if d > 0)
    desce = sum(1 for d in deltas if d < 0)
    # gradual_* é um REFINAMENTO da direção, então tem que sair da mesma base que
    # ela (mediana da 1ª metade vs 2ª). Medir o deslocamento por primeiro-vs-último
    # ponto dava contradição dentro do mesmo objeto — "gradual_alta" com
    # "direcao_8sem: queda" — e os dois campos vão juntos pro modelo ler.
    if sobe >= FMT_MONOTONIA and direcao == "alta":
        return "gradual_alta", None
    if desce >= FMT_MONOTONIA and direcao == "queda":
        return "gradual_queda", None
    media = sum(vals) / len(vals)
    if media:
        dp = (sum((v - media) ** 2 for v in vals) / len(vals)) ** 0.5
        if dp / abs(media) > FMT_RUIDO:
            return "ruidoso", None
    return "estavel", None


def build_payload(all_daily, all_dfg, all_dfm, cutoff_dt, valid_partners):
    windows = _window_bounds(cutoff_dt)

    # investimento/leads/vendas por partner × canal × janela (do DAILY_SNAPSHOT).
    # "conta" = os dois canais somados. É o nível em que as metas de CAC/CPL estão
    # definidas e em que a triagem julga: com o volume de vendas dessas contas, o
    # mínimo de base quase nunca é atingido POR CANAL, e sem o agregado uma conta
    # com CAC de R$986 caía em "sem_base" e sumia do topo da fila.
    invest = {}
    for wkey, (d_ini, d_fim) in windows.items():
        agg = defaultdict(lambda: defaultdict(float))
        for r in all_daily:
            if r["id_mp"] in valid_partners and d_ini <= r["dia"] <= d_fim:
                for canal in (r["canal"], "conta"):
                    for f in ("bruto", "cashback", "liquido", "leads", "vendas"):
                        agg[(r["id_mp"], canal)][f] += r.get(f) or 0
        for (id_mp, canal), v in agg.items():
            bruto, liq = round(v["bruto"]), round(v["liquido"])
            leads, vendas = int(v["leads"]), int(v["vendas"])
            invest.setdefault(id_mp, {}).setdefault(canal, {})[wkey] = {
                "investimento_bruto": bruto,
                "investimento_liquido": liq,
                "cashback": round(v["cashback"]),
                "pct_cashback": round(100 * v["cashback"] / v["bruto"], 1) if v["bruto"] else None,
                "leads": leads,
                "vendas": vendas,
                "cpl": _ratio(liq, leads),
                "cac": _ratio(liq, vendas),
            }

    # etapas do funil por partner × canal × janela (7d vs prev, 30d)
    def agg_funnel(rows, fields, wkeys):
        out = {}
        for wkey in wkeys:
            d_ini, d_fim = windows[wkey]
            agg = defaultdict(lambda: defaultdict(int))
            for r in rows:
                if r["id_mp"] in valid_partners and d_ini <= r["dia"] <= d_fim:
                    for f in fields:
                        agg[r["id_mp"]][f] += r.get(f) or 0
            for id_mp, v in agg.items():
                out.setdefault(id_mp, {})[wkey] = dict(v)
        return out

    fg_fields = ("impressoes", "cliques", "sessoes", "clickoff", "redirect", "leads", "vendas")
    fm_fields = ("impressoes", "cliques", "chat_start", "zip_search", "redirect", "leads", "vendas")
    wkeys = ("7d", "7d_prev", "30d", "30d_prev")
    funil_google = agg_funnel(all_dfg, fg_fields, wkeys)
    funil_meta = agg_funnel(all_dfm, fm_fields, wkeys)

    # métricas de pré-clique derivadas aqui (LLM não faz aritmética confiável).
    # cpc_estimado usa investimento bruto (financeiro) / cliques (plataforma de ads):
    # bases diferentes do gerenciador — serve pra tendência, não pra auditoria.
    for funil, canal in ((funil_google, "google"), (funil_meta, "meta")):
        for id_mp, per_window in funil.items():
            for wkey, v in per_window.items():
                v["ctr_pct"] = (round(100 * v["cliques"] / v["impressoes"], 2)
                                if v.get("impressoes") else None)
                bruto = (invest.get(id_mp, {}).get(canal, {}).get(wkey, {})
                         .get("investimento_bruto"))
                v["cpc_estimado"] = _ratio(bruto, v["cliques"]) if bruto else None

    # taxas de passagem entre etapas do meio de funil, calculadas AQUI pelo mesmo
    # motivo do ctr/cpc: o LLM ignora "cheque a etapa X" quando só tem contagens
    # brutas — precisa da taxa já pronta pra apontar o gargalo específico
    # (em vez de cair sempre no diagnóstico genérico de cashback/CTR).
    STAGE_DEFS = {
        "google": (("cliques", "sessoes"), ("sessoes", "clickoff"),
                   ("clickoff", "redirect"), ("redirect", "leads")),
        "meta": (("cliques", "chat_start"), ("chat_start", "zip_search"),
                 ("zip_search", "redirect"), ("redirect", "leads")),
    }
    for funil, canal in ((funil_google, "google"), (funil_meta, "meta")):
        for per_window in funil.values():
            for v in per_window.values():
                taxas = {}
                for de, para in STAGE_DEFS[canal]:
                    label = f"{de}>{para}"
                    taxas[label] = (round(100 * v[para] / v[de], 1)
                                     if v.get(de) else None)
                v["taxas_etapa"] = taxas

    # série semanal — 8 últimas semanas COMPLETAS, por partner × canal, derivada do
    # diário. Crédito/runway fica FORA do payload de propósito (decisão do Pedro
    # 2026-07-09): já existem alertas dedicados e, se o dado estiver aqui, o modelo
    # desvia o parecer pra isso.
    series = weekly_series(all_daily, all_dfg, all_dfm, cutoff_dt, valid_partners)

    # série crua enxuta (5 campos) só no nível do partner: rede de segurança pro
    # modelo perceber caso de borda que a classificação de tendência errou. Os
    # derivados por semana (cpl/cac/ctr) ficam só na tendência, pra não inchar.
    semanal = {p: [{k: s[k] for k in ("ws", "liquido", "leads", "vendas", "cliques")}
                   for s in canais["total"]]
               for p, canais in series.items() if "total" in canais}

    # tendência calculada aqui — o LLM não extrai de forma confiável "tendência
    # real vs ruído de 1 semana" de uma lista crua de 8 números.
    tendencia_semanal = {}
    for p, canais in series.items():
        for canal, serie in canais.items():
            t = {f: _trend_summary(serie, f) for f in TREND_FIELDS}
            tendencia_semanal.setdefault(p, {})[canal] = {k: v for k, v in t.items() if v}

    # benchmark de pré-clique 30d — comparação com os pares calculada AQUI.
    # Sem isso o modelo ignora ctr/cpc mesmo com instrução explícita (testado
    # em 2026-07-09): LLM comenta o que está saliente nos dados, não o que a
    # instrução manda procurar.
    benchmark = {}
    for canal, funil in (("google", funil_google), ("meta", funil_meta)):
        stats = {id_mp: pw["30d"] for id_mp, pw in funil.items()
                 if pw.get("30d", {}).get("ctr_pct") is not None}
        for id_mp, w in stats.items():
            peers_ctr = [v["ctr_pct"] for k, v in stats.items() if k != id_mp]
            peers_cpc = [v["cpc_estimado"] for k, v in stats.items()
                         if k != id_mp and v.get("cpc_estimado")]
            entry = {"ctr_pct_30d": w["ctr_pct"], "cpc_estimado_30d": w.get("cpc_estimado")}
            if peers_ctr:
                media = sum(peers_ctr) / len(peers_ctr)
                entry["ctr_media_outros_partners"] = round(media, 2)
                if media:
                    entry["ctr_vs_pares_pct"] = round(100 * (w["ctr_pct"] - media) / media, 1)
            if peers_cpc and w.get("cpc_estimado"):
                media = sum(peers_cpc) / len(peers_cpc)
                entry["cpc_media_outros_partners"] = round(media, 2)
                entry["cpc_vs_pares_pct"] = round(100 * (w["cpc_estimado"] - media) / media, 1)
            benchmark.setdefault(id_mp, {})[canal] = entry

    # gargalo_funil_30d: aponta a ETAPA mais fraca do meio de funil de cada
    # partner×canal (vs a própria janela anterior e vs a média dos pares),
    # já pré-selecionada — mesmo racional do benchmark_pre_clique_30d. Sem
    # isso o modelo só cruza cashback/CTR (os únicos dados já mastigados) e
    # nunca chega no diagnóstico de funil descrito em <como_pensar>.
    gargalo_funil = {}
    for canal, funil in (("google", funil_google), ("meta", funil_meta)):
        stage_labels = [f"{de}>{para}" for de, para in STAGE_DEFS[canal]]
        stats_30d = {id_mp: pw["30d"]["taxas_etapa"] for id_mp, pw in funil.items()
                     if pw.get("30d", {}).get("taxas_etapa")}
        for id_mp, taxas in stats_30d.items():
            taxas_prev = funil[id_mp].get("30d_prev", {}).get("taxas_etapa", {})
            pior_label, pior_desvio, pior_detalhe = None, None, None
            for label in stage_labels:
                taxa = taxas.get(label)
                if taxa is None:
                    continue
                peers = [t[label] for k, t in stats_30d.items()
                         if k != id_mp and t.get(label) is not None]
                desvio_pares = None
                if peers:
                    media_pares = sum(peers) / len(peers)
                    if media_pares:
                        desvio_pares = round(100 * (taxa - media_pares) / media_pares, 1)
                taxa_prev = taxas_prev.get(label)
                delta_hist = (round(100 * (taxa - taxa_prev) / taxa_prev, 1)
                              if taxa_prev else None)
                # pior sinal = menor entre desvio vs pares e delta vs histórico
                candidatos = [d for d in (desvio_pares, delta_hist) if d is not None]
                if not candidatos:
                    continue
                pior_deste = min(candidatos)
                if pior_desvio is None or pior_deste < pior_desvio:
                    pior_desvio = pior_deste
                    pior_label = label
                    pior_detalhe = {
                        "etapa": label, "taxa_30d_pct": taxa,
                        "taxa_media_pares_pct": round(media_pares, 1) if peers else None,
                        "desvio_vs_pares_pct": desvio_pares,
                        "taxa_30d_prev_pct": taxa_prev,
                        "delta_vs_historico_pct": delta_hist,
                    }
            if pior_detalhe:
                gargalo_funil.setdefault(id_mp, {})[canal] = pior_detalhe

    # dias_de_dados: do primeiro dia com investimento BRUTO > 0 até o corte.
    # Satura na poda de 180 dias do all_daily — só importa pro teste de ramp (<14),
    # onde a poda nunca alcança.
    dias_de_dados = {}
    for p in valid_partners:
        dias_ativos = [r["dia"] for r in all_daily
                       if r["id_mp"] == p and (r.get("bruto") or 0) > 0
                       and r["dia"] <= cutoff_dt.isoformat()]
        dias_de_dados[p] = ((cutoff_dt - date.fromisoformat(min(dias_ativos))).days + 1
                            if dias_ativos else 0)

    return {
        "data_corte": cutoff_dt.isoformat(),
        "janelas": {k: {"inicio": v[0], "fim": v[1]} for k, v in windows.items()},
        "partners": valid_partners,
        "dias_de_dados_por_partner": dias_de_dados,
        "kpis_por_partner_canal_janela": invest,
        "funil_google_por_partner": funil_google,
        "funil_meta_por_partner": funil_meta,
        "serie_semanal_por_partner": semanal,
        "tendencia_semanal_por_partner": tendencia_semanal,
        "benchmark_pre_clique_30d": benchmark,
        "gargalo_funil_30d": gargalo_funil,
    }


# ── estágio 0: triagem ────────────────────────────────────────────────────
#
# Regra, não julgamento. Os limiares são numéricos e absolutos — comparar número
# com limiar é o que LLM faz pior e código faz perfeito. Com a triagem aqui, ela
# para de variar de uma semana pra outra e nenhuma conta em alarme é esquecida
# porque o modelo economizou atenção.

META = {
    "CAC_IDEAL": 150,     # <= ideal · 150-200 alerta · > 200 alarme
    "CAC_ALARME": 200,
    "CPL_META": 100,      # <= meta · 100-200 alerta · > 200 alarme
    "CPL_ALARME": 200,    # 2x a meta — suposição, o Pedro definiu só o alerta em 100
    "MIN_VENDAS": 3,      # base mínima pro CAC ter significado (decisão 2026-07-24)
    "MIN_LEADS": 10,      # base mínima pro CPL
    "RAMP_DIAS": 14,
}

SEV = {"alarme": 0, "atencao": 1, "dado_suspeito": 2, "sem_base": 3, "ramp": 4, "ok": 5}


def _gargalo_relevante(g):
    """False quando os dois desvios estão dentro de ±15%.

    Sem isso o campo SEMPRE existe e até a conta mais saudável do portfólio "tem
    um gargalo" — um mínimo relativo não é um problema, e o modelo patologiza a
    melhor conta da carteira.
    """
    if not g:
        return False
    return any(d is not None and d <= -15
               for d in (g.get("desvio_vs_pares_pct"), g.get("delta_vs_historico_pct")))


def _escada(liq, leads, vendas, cac, cpl, leads_7d, dias):
    """A escada de julgamento: para no primeiro degrau que o dado sustenta."""
    if not liq and not leads:
        return "sem_base", "sem investimento nem lead em 30d", "nenhuma"
    if dias < META["RAMP_DIAS"]:
        return "ramp", f"conta com {dias} dias de dados (ramp de {META['RAMP_DIAS']})", "ramp"
    if liq > 0 and not leads and not leads_7d:
        return "dado_suspeito", "investimento em 30d sem nenhum lead em 7d e 30d", "nenhuma"
    if vendas >= META["MIN_VENDAS"] and cac is not None:
        if cac <= META["CAC_IDEAL"]:
            return "ok", f"CAC 30d R${cac:.0f} dentro do ideal", "cac"
        if cac <= META["CAC_ALARME"]:
            return "atencao", f"CAC 30d R${cac:.0f} na zona de alerta (150-200)", "cac"
        return "alarme", f"CAC 30d R${cac:.0f} acima do teto de R$200", "cac"
    if leads >= META["MIN_LEADS"] and cpl is not None:
        suf = f" (só {vendas} venda(s) em 30d, CAC sem base)"
        if cpl <= META["CPL_META"]:
            return "ok", f"CPL 30d R${cpl:.0f} na meta{suf}", "cpl"
        if cpl <= META["CPL_ALARME"]:
            return "atencao", f"CPL 30d R${cpl:.0f} acima da meta de R$100{suf}", "cpl"
        return "alarme", f"CPL 30d R${cpl:.0f} acima do dobro da meta{suf}", "cpl"
    return ("sem_base",
            f"{leads} lead(s) e {vendas} venda(s) em 30d — abaixo da base mínima", "nenhuma")


def _distancia_meta_pct(base, cac, cpl):
    if base == "cac" and cac is not None:
        return round(100 * (cac - META["CAC_ALARME"]) / META["CAC_ALARME"])
    if base == "cpl" and cpl is not None:
        return round(100 * (cpl - META["CPL_META"]) / META["CPL_META"])
    return None


def triar(payload):
    """Status por partner (nível conta) + localização por canal.

    O status vem do agregado da CONTA, não do pior canal: as metas de CAC/CPL do
    Pedro são definidas nesse nível, e com esse volume de vendas o mínimo de base
    quase nunca é atingido canal a canal — julgar por canal jogava conta com CAC
    de R$986 em "sem_base". O canal serve pra localizar onde está o problema, que
    é exatamente o papel dele na escada (degrau 3 explica, não decide).
    """
    kpis = payload.get("kpis_por_partner_canal_janela", {})
    tend = payload.get("tendencia_semanal_por_partner", {})
    garg = payload.get("gargalo_funil_30d", {})
    dias_map = payload.get("dias_de_dados_por_partner", {})
    partners = payload.get("partners") or list(kpis)
    out = {}

    for p in partners:
        dias = dias_map.get(p, 0)
        niveis = {}
        for nivel in ("conta", "google", "meta"):
            w = kpis.get(p, {}).get(nivel, {})
            j30, j30p, j7 = w.get("30d", {}), w.get("30d_prev", {}), w.get("7d", {})
            liq = j30.get("investimento_liquido") or 0
            leads, vendas = j30.get("leads") or 0, j30.get("vendas") or 0
            cac, cpl = j30.get("cac"), j30.get("cpl")
            status, motivo, base = _escada(liq, leads, vendas, cac, cpl,
                                           j7.get("leads") or 0, dias)
            niveis[nivel] = {
                "status": status, "motivo": motivo, "base_de_julgamento": base,
                "cac_30d": cac, "cpl_30d": cpl,
                "cac_30d_prev": j30p.get("cac"), "cpl_30d_prev": j30p.get("cpl"),
                "leads_30d": leads, "vendas_30d": vendas,
                "investimento_liquido_30d": round(liq),
                "distancia_meta_pct": _distancia_meta_pct(base, cac, cpl),
                "pct_cashback_30d": j30.get("pct_cashback"),
                "pct_cashback_30d_prev": j30p.get("pct_cashback"),
                "cashback_subiu": (j30.get("pct_cashback") > j30p.get("pct_cashback")
                                   if j30.get("pct_cashback") is not None
                                   and j30p.get("pct_cashback") is not None else None),
                # gargalo só conta onde há base: conta sem lead marca -100% em toda
                # etapa e viraria "gargalo grave" sendo que o problema é não ter dado
                "gargalo_relevante": (_gargalo_relevante(garg.get(p, {}).get(nivel))
                                      if base not in ("nenhuma", "ramp") else False),
            }

        conta = niveis.pop("conta")
        # canal crítico = o pior canal; empate ou nenhum problema → nenhum
        piores = sorted(niveis.items(), key=lambda kv: (SEV[kv[1]["status"]],
                                                        -(kv[1]["distancia_meta_pct"] or 0)))
        canal_critico = piores[0][0] if SEV[piores[0][1]["status"]] <= SEV["atencao"] else "nenhum"

        # risco de churn: proxy operacional pra "CAC acima de R$200 por 3 semanas
        # seguidas". CAC semanal com esse volume de vendas é ruído puro, então a
        # persistência sai da comparação entre as duas janelas de 30d.
        cac, cac_prev = conta["cac_30d"], conta["cac_30d_prev"]
        dir_leads = (tend.get(p, {}).get("total", {}).get("leads") or {}).get("direcao_8sem")
        risco_churn = bool(cac and cac_prev and cac > META["CAC_ALARME"]
                           and cac_prev > META["CAC_ALARME"]
                           and dir_leads in ("queda", "estavel"))

        out[p] = {
            "status_geral": conta["status"],
            "motivo": conta["motivo"],
            "base_de_julgamento": conta["base_de_julgamento"],
            "distancia_meta_pct": conta["distancia_meta_pct"],
            "dias_de_dados": dias,
            "conta": conta,
            "canal_critico": canal_critico,
            "canais": niveis,
            "tendencia_leads_8sem": dir_leads,
            "risco_churn": risco_churn,
            "motivo_risco_churn": ("CAC acima de R$200 em 30d e em 30d_prev, com leads em "
                                   "queda ou estáveis no piso") if risco_churn else None,
        }

    ordem = sorted(out, key=lambda p: (SEV[out[p]["status_geral"]],
                                       -(out[p]["distancia_meta_pct"] or 0)))
    return {"metas": META, "ordem_de_prioridade": ordem, "por_partner": out}


TRIAGEM_LABEL = {"ok": "OK", "atencao": "Atenção", "alarme": "Alarme",
                 "sem_base": "Sem base", "dado_suspeito": "Dado suspeito", "ramp": "Ramp"}


def render_triagem_html(triagem):
    """Tabela de triagem do topo do relatório — dado puro, renderizado aqui.

    Fora do LLM de propósito: assim o bloco sai do relatório com uma linha quando
    o Pedro decidir que não vale a pena, e nunca diverge do que a triagem decidiu.
    """
    linhas = []
    for p in triagem["ordem_de_prioridade"]:
        v = triagem["por_partner"][p]
        c = v["conta"]
        cac = f"R${c['cac_30d']:.0f}" if c["cac_30d"] is not None else "—"
        cpl = f"R${c['cpl_30d']:.0f}" if c["cpl_30d"] is not None else "—"
        churn = " ⚠️ risco de churn" if v["risco_churn"] else ""
        canal = v["canal_critico"] if v["canal_critico"] != "nenhum" else "—"
        linhas.append(
            f"<tr><td><strong>{p}</strong></td><td>{TRIAGEM_LABEL[v['status_geral']]}{churn}</td>"
            f"<td>{cac}</td><td>{cpl}</td><td>{c['vendas_30d']}</td><td>{canal}</td>"
            f"<td>{v['motivo']}</td></tr>")
    return ("<h2>Triagem</h2>\n<table><thead><tr><th>Partner</th><th>Status</th>"
            "<th>CAC 30d</th><th>CPL 30d</th><th>Vendas 30d</th><th>Canal crítico</th>"
            "<th>Motivo</th></tr></thead>\n<tbody>\n" + "\n".join(linhas) +
            "\n</tbody></table>\n")

# ── estágio 1: diagnóstico ────────────────────────────────────────────────

PROMPT_E1 = """Você é especialista sênior de mídia paga e cuida das contas do MP Agência (Melhor
Plano) — provedores regionais de internet que compram um pacote mensal de mídia
100% investido em campanhas.

Sua tarefa nesta etapa é DIAGNOSTICAR, não escrever. A redação do relatório
acontece em outra etapa. Aqui você produz julgamento estruturado: o que explica o
número, qual a causa provável, como validar, o que fazer.

<negocio>
Dois canais por partner:
- google — pesquisa no Google Ads.
  Funil: impressoes > cliques > sessoes > clickoff > redirect > leads > vendas
- meta — click-to-WhatsApp com bot.
  Funil: impressoes > cliques > chat_start > zip_search > redirect > leads > vendas

Cashback: quando o lead gerado pela campanha de um partner fecha com OUTRO
provedor (CEP fora da cobertura do anunciante), o anunciante recebe cashback de
reinvestimento.
- investimento_liquido = bruto - cashback. CPL e CAC já vêm sobre o líquido.
- Cashback subindo NÃO é dinheiro de volta: é a campanha comprando demanda fora
  da área atendida. É sinal de segmentação geográfica desalinhada.
- Atribuição de lead e venda é SEMPRE ao partner anunciante, nunca ao provedor
  que recebeu o lead.

Cada partner é uma conta isolada. A verba de um partner só pode ser realocada
entre os canais e campanhas DELE. Nunca recomende mover verba entre partners.
</negocio>

<metas>
- CAC: até R$150 é o ideal · R$150-200 é zona de alerta · acima de R$200 é alarme
- CPL: até R$100 é a meta · acima disso é alerta

Metas absolutas, iguais para todos os partners. Tamanho da conta não altera
prioridade.
</metas>

<escada_de_julgamento>
Julgue cada partner descendo esta escada e pare no primeiro degrau que o dado
sustenta:

1. CAC (30d) — indicador principal.
2. CPL (30d) — use quando o CAC não tem base.
3. Etapas do funil + CPC — sempre, para EXPLICAR o CAC ou o CPL do degrau acima.

O degrau 3 nunca substitui os degraus 1 e 2 como veredito: ele é a explicação de
por que o número de cima está onde está. Parecer que fica só no degrau 3, sem
amarrar em CAC ou CPL, está incompleto.

Toda avaliação de CAC e CPL usa 30d, nunca 7d: venda tem lag de fechamento e o
CAC de 7d vem sistematicamente inflado. Use 7d apenas para topo e meio de funil
(impressões, cliques, sessões/conversas, redirects, leads).
</escada_de_julgamento>

<como_diagnosticar>
Ordem de investigação, por partner:

1. Leia "status" e "motivo" em triagem. Os limiares já foram aplicados em código
   — não recalcule nem discuta o status.

2. Se "gargalo_relevante" for true, comece por gargalo_funil_30d: é a etapa mais
   fraca do meio de funil e a de ação mais rápida. Se for false, o funil está
   dentro do normal e o problema está em outro lugar — não invente gargalo.

3. Leia o formato da série semanal antes de concluir. Formato é diagnóstico:
   - degrau -> algo mudou numa data específica: campanha pausada, verba cortada,
     segmentação alterada, rastreamento quebrado. A ação é descobrir o que mudou
     na semana indicada.
   - gradual_queda -> desgaste contínuo: fadiga de criativo ou leilão encarecendo.
   - estavel -> o número atual não é notícia desta semana, é o patamar da conta.
   - ruidoso -> volume baixo demais para ler tendência.

4. Pré-clique (ctr_pct, cpc_estimado vs pares) quando o gargalo não for de meio
   de funil. Desvio de 30% ou mais vs pares precisa aparecer no diagnóstico.

5. Cashback quando pct_cashback subiu vs a janela anterior. Antes de recomendar
   aperto geográfico, verifique se zip_search>redirect (meta) ou
   clickoff>redirect (google) também piorou. Se o cashback subiu e essas taxas
   estão estáveis, a causa provável é mudança no mix de demanda, não segmentação
   — apertar o raio corta volume sem ganho.

6. Taxa redirect>leads fraca ou taxa lead>venda fraca tem DUAS causas possíveis,
   e você precisa escolher com evidência:
   - captação desqualificada (é alavanca de mídia): volume alto + CPL abaixo da
     meta + cashback subindo -> segmentação aberta demais puxando tráfego que não
     fecha.
   - funil comercial do provedor (fora da mídia): volume normal + CPL na meta +
     cobertura ok -> atendimento ou agenda de instalação do provedor.
   Não atribua ao provedor por default.

Padrões de leitura pré-clique:
- impressões caindo + CTR estável = perda de entrega (orçamento/lance/leilão)
- CTR caindo + impressões estáveis = fadiga de criativo ou concorrente novo
- impressões subindo + CTR caindo sem ganho de cliques = segmentação aberta demais
- CPC subindo + CTR estável = leilão mais caro

Padrões por etapa:
- google: cliques ok + sessões baixas = landing ou rastreamento ·
  sessoes>clickoff fraca = oferta pouco competitiva · clickoff>redirect fraca =
  cobertura/viabilidade · redirect>leads fraca = fricção de formulário
- meta: cliques>chat_start fraca = criativo/CTA ou fricção do click-to-WhatsApp ·
  chat_start>zip_search fraca = abandono no início do bot · zip_search>redirect
  fraca = CEPs fora da cobertura · redirect>leads fraca = fricção final do fluxo
</como_diagnosticar>

<regras_de_evidencia>
- Todo número que você citar em qualquer campo tem que estar também em
  evidencias_citadas, com metrica, valor e janela exatamente como aparecem no
  payload. Número fora dessa lista é rejeitado na validação automática.
- Não calcule nada. Taxas, variações, CTR, CPC e tendências já vêm prontas. Se um
  número que você quer citar não existe no payload, ele não existe — reformule o
  diagnóstico no nível que os dados permitem.
- Não cite nome de campanha, criativo, adset ou posição média: não estão no
  payload.
- Não atribua variação a sazonalidade, feriado ou ciclo de faturamento.
  Sazonalidade não está mapeada neste negócio; essa atribuição é sempre
  especulação e fecha a investigação antes da hora.
- confianca "baixa" é resposta válida e melhor que hipótese inventada. Mas se a
  confiança é baixa, a ação da semana é de observação ou coleta de dado, não
  mexida em campanha.
- Quando 7d e 30d apontarem em direções opostas na MESMA métrica, com base
  suficiente nas duas janelas, o resultado não fechou direção: diga isso e
  proponha acompanhar. Divergência entre métricas diferentes não autoriza essa
  saída.
- status "dado_suspeito" -> não diagnostique performance. A ação é verificar
  rastreamento.
- status "ramp" -> diga só que a conta está em ramp e o que observar quando
  fechar 14 dias de dados.
- risco_churn true na triagem -> o diagnóstico tem que endereçar isso
  explicitamente, não apenas repetir o CAC.
- Limites de tamanho: diagnostico até 400 caracteres, cadeia_causal até 300,
  hipotese até 250, como_validar até 200, acao_semana até 250.
</regras_de_evidencia>

<comparacao_com_semana_anterior>
Você recebe diagnostico_semana_anterior. Para cada partner que aparecer lá,
preencha mudou_vs_semana_anterior com uma destas leituras:
- a ação recomendada foi executada e o indicador respondeu
- a ação foi executada e o indicador NÃO respondeu — nesse caso a hipótese
  anterior provavelmente estava errada e você precisa de uma nova
- a ação não parece ter sido executada (indicador e padrão seguem idênticos)
- o diagnóstico mudou de eixo (o problema anterior saiu, apareceu outro)

Partner ausente na semana anterior, ou lista vazia -> deixe o campo fora. Não
invente continuidade.
</comparacao_com_semana_anterior>

<acoes_priorizadas>
Além dos diagnósticos, produza a lista de ações da semana ordenada por impacto.
Sem número mínimo nem máximo: quantas o dado sustentar.

Impacto = gravidade (distância da meta, conforme o status da triagem) x confiança
no diagnóstico. Ordene por gravidade primeiro; em caso de empate, confiança alta
antes de média.

Não inclua ação com confiança baixa nesta lista — ela vive no parecer do partner
como observação, não como ação priorizada.
Nunca proponha mover verba entre partners.
</acoes_priorizadas>

DADOS — data de corte {cover}:
{payload}

DIAGNÓSTICO DA SEMANA ANTERIOR:
{diagnostico_anterior}

Responda apenas com o JSON do schema. Sem markdown em volta, sem comentários."""


STAGE1_SCHEMA = {
    "type": "object",
    "required": ["partners", "acoes_priorizadas"],
    "properties": {
        "partners": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["partner", "status_geral", "eixo_principal", "canal_critico",
                             "diagnostico", "cadeia_causal", "acao_semana", "confianca",
                             "evidencias_citadas", "risco_churn"],
                "properties": {
                    "partner": {"type": "string"},
                    "status_geral": {"type": "string",
                                     "enum": ["ok", "atencao", "alarme", "sem_base",
                                              "dado_suspeito", "ramp"]},
                    "eixo_principal": {"type": "string",
                                       "enum": ["cac", "cpl", "funil", "pre_clique", "cobertura",
                                                "rastreamento", "ramp", "saudavel"]},
                    "canal_critico": {"type": "string",
                                      "enum": ["google", "meta", "ambos", "nenhum"]},
                    "diagnostico": {"type": "string", "description": "até 400 caracteres"},
                    "cadeia_causal": {"type": "string", "description": "até 300 caracteres"},
                    "hipotese": {"type": "string", "description": "até 250 caracteres"},
                    "como_validar": {"type": "string", "description": "até 200 caracteres"},
                    "acao_semana": {"type": "string", "description": "até 250 caracteres"},
                    "confianca": {"type": "string", "enum": ["alta", "media", "baixa"]},
                    "risco_churn": {"type": "boolean"},
                    "mudou_vs_semana_anterior": {"type": "string", "description": "até 200 caracteres"},
                    "evidencias_citadas": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["metrica", "valor", "janela"],
                            "properties": {
                                "metrica": {"type": "string"},
                                "valor": {"type": "string"},
                                "janela": {"type": "string"},
                                "canal": {"type": "string", "enum": ["google", "meta", "ambos"]},
                            },
                        },
                    },
                },
            },
        },
        "acoes_priorizadas": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["ordem", "partner", "canal", "acao", "justificativa",
                             "impacto_esperado", "confianca"],
                "properties": {
                    "ordem": {"type": "integer"},
                    "partner": {"type": "string"},
                    "canal": {"type": "string", "enum": ["google", "meta", "ambos"]},
                    "acao": {"type": "string"},
                    "justificativa": {"type": "string"},
                    "impacto_esperado": {"type": "string"},
                    "confianca": {"type": "string", "enum": ["alta", "media"]},
                },
            },
        },
    },
}


# ── estágio 2: redação ────────────────────────────────────────────────────
#
# Tags XML e não JSON: não existe escape pra quebrar, truncamento devolve as
# seções que fecharam em vez de perder o run inteiro, e prosa longa dentro de
# string JSON é onde o Gemini erra escape com mais frequência.

PROMPT_E2 = """Você é especialista sênior de mídia paga do MP Agência e está escrevendo o
relatório semanal das contas. Os diagnósticos já estão fechados — seu trabalho
aqui é redigir, não reanalisar.

<leitores>
Três públicos no mesmo documento:
- Time de mídia — executa as ações. Precisa da alavanca específica: qual canal,
  qual etapa, o que mexer.
- PM do projeto — precisa da leitura de conjunto e do que mudou desde a semana
  passada.
- CEO — lê o topo e para. Precisa saber onde está o dinheiro em risco e qual é a
  decisão da semana, sem vocabulário de operação.

Voz de especialista de mídia falando sobre contas que acompanha toda semana:
direto, opinativo, específico. Não é consultoria externa avaliando de fora, nem
laudo formal. O topo do relatório precisa funcionar para o CEO; o detalhe é do
time de mídia.
</leitores>

<materia_prima>
Você recebe o JSON de diagnóstico desta semana e o da semana anterior. Não recebe
os dados brutos — de propósito. Os leitores já têm um dashboard interativo com
todos os números, funis e comparações. Relatório que repete o dashboard tem valor
zero; seu valor é o raciocínio.
</materia_prima>

<regra_dos_numeros>
Você só pode citar números que aparecem em evidencias_citadas do partner
correspondente. Nada além disso — não estime, não arredonde para um valor que não
está lá, não some, não calcule variação.

Critério de uso, não de quantidade: todo número citado tem que estar na mesma
frase que a conclusão que ele sustenta. Número solto, sem inferência amarrada, é
recitação de dashboard — corte.

Quando o volume for baixo, prefira absolutos a percentuais: "de 20 leads, só 3
viraram venda" comunica o tamanho real do problema melhor que "taxa de 15%".

Valores em R$ sem centavos.
</regra_dos_numeros>

<ordem_de_escrita>
Escreva nesta ordem, porque cada bloco depende do anterior:
1. pareceres por partner
2. recomendações
3. leitura de portfólio (derivada dos pareceres que você acabou de escrever)
4. resumo Slack (derivado da leitura de portfólio)

Não escreva o resumo antes dos pareceres.
</ordem_de_escrita>

<pareceres>
Um parecer por partner, na ordem de prioridade que vier no JSON. Nunca omita um
partner.

3 a 5 frases. Todo parecer cobre: situação, o que explica, e o que fazer esta
semana. Hipótese e forma de validar entram quando existirem no diagnóstico.

Os campos cobertos são fixos — a ênfase e a ordem são livres. Abra pela parte
mais forte da história daquela conta, não por um template. Uma conta com degrau na
série abre pelo degrau; uma conta com gargalo de bot abre pelo bot; uma conta
saudável e subaproveitada abre pela oportunidade.

Quando mudou_vs_semana_anterior estiver preenchido, isso entra no parecer —
inclusive quando a leitura é que a ação anterior não foi executada, ou foi e não
funcionou. Essa é a parte do relatório que nenhum dashboard faz.

Partner em ramp, sem_base ou dado_suspeito: uma frase dizendo o que é e o que
verificar. Não force análise.
</pareceres>

<leitura_portfolio>
Um parágrafo curto. Onde o MP Agência ganha e perde dinheiro hoje, qual conta
exige ação urgente e por quê, e a decisão mais importante da semana.

Escrito para o CEO: sem jargão de etapa de funil, sem nome de métrica de
plataforma. Se houver padrão de portfólio — várias contas com o mesmo problema ao
mesmo tempo — a manchete é o padrão, não a conta individual.

Verba nunca se move entre partners. Cada conta é isolada e os resultados são dela.
</leitura_portfolio>

<nao_faca>
- Não escreva frase que não contenha diagnóstico, hipótese, risco, oportunidade
  ou decisão. Teste: se a frase não muda nenhuma decisão do leitor, corte.
- Não subdivida o parecer em "Google:" / "Meta:" com lista de métricas. Canal
  entra na narrativa quando for relevante para o diagnóstico.
- Não use preâmbulo ("vale destacar que", "é importante notar", "conforme os
  dados") nem adjetivo que não carrega informação.
- Não repita entre seções. O resumo Slack não é a leitura de portfólio
  abreviada, é a conclusão dela.
- Não hedge quando o diagnóstico tem confiança alta. Posicione-se: faça X porque
  Y. Quando o diagnóstico disser que o resultado não fechou direção, dizer
  "vamos acompanhar mais uma semana" é a posição correta, não uma fuga.
- Não comente crédito, saldo ou runway do pacote — há alertas dedicados a isso.
- Não mencione responsáveis, pessoas ou times na ação. Descreva o problema, a
  hipótese e o que fazer.
- Não invente número, data ou nome de campanha.
</nao_faca>

<formato>
Responda com os quatro blocos abaixo, nesta ordem, sem markdown em volta e sem
texto fora das tags:

<pareceres>
HTML. Um h3 com o nome do partner por parecer, seguido de p.
Tags permitidas: h3, p, strong, ul, li.
</pareceres>

<recomendacoes>
HTML. Uma table com thead/tbody e as colunas: Prioridade, Partner, Canal, Ação,
Justificativa, Impacto esperado, Confiança.
Uma linha por item de acoes_priorizadas, na ordem do JSON.
Esta tabela é o recorte executável dos pareceres — repetição aqui é intencional.
Não introduza ação que não esteja no JSON.
</recomendacoes>

<leitura_portfolio>
HTML. Um único p.
</leitura_portfolio>

<resumo_slack>
Texto puro em mrkdwn do Slack (*negrito*, bullets com •). Até 700 caracteres.
1 bullet com a leitura da semana — a conclusão, não os números.
2 a 3 bullets com os diagnósticos mais importantes.
1 bullet com a ação nº 1.
</resumo_slack>
</formato>

DIAGNÓSTICO DESTA SEMANA (corte {cover}):
{diagnostico_json}

DIAGNÓSTICO DA SEMANA ANTERIOR:
{diagnostico_anterior}"""


# ── chamadas ao Gemini ────────────────────────────────────────────────────

RETRYABLE = {429, 500, 502, 503, 529}


def _post(body, tries=3):
    """POST no Gemini com retry só em erro transiente. 4xx de auth/payload
    estoura na hora — retentar um payload inválido só queima tempo."""
    url = GEMINI_URL.format(model=_model())
    last = None
    for i in range(tries):
        if i:
            time.sleep(20 * i)
        r = requests.post(url, headers={"x-goog-api-key": os.environ["LLM_API_KEY"]},
                          json=body, timeout=REQUEST_TIMEOUT)
        if r.status_code in RETRYABLE:
            last = requests.HTTPError(f"{r.status_code} do Gemini", response=r)
            print(f"Aviso: Gemini devolveu {r.status_code} (tentativa {i + 1}/{tries}).")
            continue
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    raise last


def call_stage1(payload, cover, diag_anterior):
    """Thinking alto: é a etapa de julgamento e se beneficia."""
    prompt = (PROMPT_E1
              .replace("{cover}", cover)
              .replace("{payload}", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
              .replace("{diagnostico_anterior}",
                       json.dumps(diag_anterior, ensure_ascii=False, separators=(",", ":"))
                       if diag_anterior else "(primeira semana — não existe diagnóstico anterior)"))
    txt = _post({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 65536,
            "responseMimeType": "application/json",
            "responseSchema": STAGE1_SCHEMA,
            "thinkingConfig": {"thinkingBudget": 24576},
        },
    })
    return json.loads(txt)


def call_stage2(diag, cover, diag_anterior):
    """Thinking baixo: aqui é executar uma especificação; thinking alto só
    aumenta a variância da redação."""
    prompt = (PROMPT_E2
              .replace("{cover}", cover)
              .replace("{diagnostico_json}", json.dumps(diag, ensure_ascii=False, separators=(",", ":")))
              .replace("{diagnostico_anterior}",
                       json.dumps(diag_anterior, ensure_ascii=False, separators=(",", ":"))
                       if diag_anterior else "(primeira semana — sem bloco de continuidade)"))
    return _post({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.5, "maxOutputTokens": 32768,
                             "thinkingConfig": {"thinkingBudget": 2048}},
    })


BLOCOS = ("pareceres", "recomendacoes", "leitura_portfolio", "resumo_slack")
TAGS_OK = {"h3", "p", "strong", "ul", "li", "table", "thead", "tbody", "tr", "th", "td"}


def parse_blocos(txt):
    out = {}
    for b in BLOCOS:
        m = re.search(rf"<{b}>(.*?)</{b}>", txt, re.S)
        if m:
            out[b] = m.group(1).strip()
    return out


def sanitize(html):
    """O texto vai pra dentro de st.markdown(unsafe_allow_html=True) — nunca
    deixar o LLM injetar script/style/iframe na página."""
    return re.sub(r"<\s*/?\s*(script|style|iframe|link|meta|object|embed)\b[^>]*>", "", html, flags=re.I)


# ── validação ─────────────────────────────────────────────────────────────

def _numeros(txt):
    limpo = re.sub(r"<[^>]+>", " ", txt)
    achados = set()
    for m in re.finditer(r"(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:[.,]\d+)?)", limpo):
        try:
            v = float(m.group(1).replace(".", "").replace(",", "."))
        except ValueError:
            continue
        if v >= 2:      # ignora 0 e 1, que aparecem em prosa ("1 lead", "0%")
            achados.add(round(v, 2))
    return achados


def _permitidos(diag):
    ok = set()
    for p in diag.get("partners", []):
        for e in p.get("evidencias_citadas", []):
            for m in re.finditer(r"(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:[.,]\d+)?)", str(e.get("valor", ""))):
                try:
                    v = float(m.group(1).replace(".", "").replace(",", "."))
                except ValueError:
                    continue
                ok.add(round(v, 2))
                ok.add(float(round(v)))
    return ok


def validar(triagem, diag, blocos):
    """Checks que o desenho pediu. Devolve (avisos, erros_fatais).

    O check de números é o que mata a classe de erro do prompt antigo, em que o
    modelo citava "estável há 6 semanas" — número que não existia no payload.
    """
    avisos, fatais = [], []

    esperados = set(triagem["por_partner"])
    vistos = {p.get("partner") for p in diag.get("partners", [])}
    faltando = esperados - vistos
    if faltando:
        fatais.append(f"partner ausente no diagnóstico: {', '.join(sorted(faltando))}")

    for p in diag.get("partners", []):
        t = triagem["por_partner"].get(p.get("partner"))
        if t and t["status_geral"] != p.get("status_geral"):
            fatais.append(f"{p['partner']}: modelo reclassificou status "
                          f"({p.get('status_geral')} vs {t['status_geral']} da triagem)")

    for a in diag.get("acoes_priorizadas", []):
        if a.get("confianca") == "baixa":
            fatais.append(f"ação priorizada com confiança baixa: {a.get('partner')}")

    churn_tri = {k for k, v in triagem["por_partner"].items() if v["risco_churn"]}
    churn_diag = {p["partner"] for p in diag.get("partners", []) if p.get("risco_churn")}
    if churn_tri - churn_diag:
        avisos.append(f"risco de churn não endereçado: {', '.join(sorted(churn_tri - churn_diag))}")

    if blocos is not None:
        for b in BLOCOS:
            if not blocos.get(b):
                fatais.append(f"bloco <{b}> ausente ou não fechou")
        n_h3 = len(re.findall(r"<h3", blocos.get("pareceres", ""), re.I))
        if n_h3 != len(vistos):
            avisos.append(f"{n_h3} pareceres para {len(vistos)} partners")
        if len(blocos.get("resumo_slack", "")) > 700:
            avisos.append(f"resumo Slack com {len(blocos['resumo_slack'])} caracteres (limite 700)")
        prosa = " ".join(blocos.get(b, "") for b in ("pareceres", "leitura_portfolio", "resumo_slack"))
        usadas = {t.lower() for t in re.findall(r"<\s*/?\s*([a-zA-Z0-9]+)", prosa)}
        if usadas - TAGS_OK:
            avisos.append(f"tag fora da whitelist: {', '.join(sorted(usadas - TAGS_OK))}")
        permitidos = _permitidos(diag)
        inventados = {v for v in _numeros(prosa)
                      if v not in permitidos and float(round(v)) not in permitidos}
        if inventados:
            amostra = ", ".join(str(v) for v in sorted(inventados)[:12])
            avisos.append(f"número na prosa fora de evidencias_citadas: {amostra}")

    return avisos, fatais


# ── orquestração ──────────────────────────────────────────────────────────

DIAG_DIR = "data/diagnosticos"


def _diag_anterior(repo_root):
    """Diagnóstico mais recente já persistido. Na 1ª semana não existe e o
    bloco de continuidade simplesmente não sai."""
    d = os.path.join(repo_root, DIAG_DIR)
    if not os.path.isdir(d):
        return None, None
    arquivos = sorted(f for f in os.listdir(d) if f.endswith(".json"))
    if not arquivos:
        return None, None
    with open(os.path.join(d, arquivos[-1]), encoding="utf-8") as f:
        return json.load(f), arquivos[-1][:-5]


def build_context(all_daily, all_dfg, all_dfm, cutoff_dt, partners):
    """Payload + triagem. Puro cálculo, sem LLM.

    Separado do run() de propósito: é também o contexto da aba de chat, que
    precisa existir mesmo quando a análise semanal falha ou está desligada.
    """
    payload = build_payload(all_daily, all_dfg, all_dfm, cutoff_dt, partners)
    payload["triagem"] = triar(payload)
    return payload


def run(context, cutoff_dt, repo_root):
    """Estágios 1 e 2 sobre um contexto já montado por build_context().

    Levanta exceção em falha — quem chama (o refresh) engole e segue sem a
    análise. Análise nunca derruba o refresh.
    """
    cover = cutoff_dt.strftime("%d/%m/%y")
    payload = context
    triagem = payload["triagem"]

    anterior, anterior_data = _diag_anterior(repo_root)

    diag = call_stage1(payload, cover, anterior)
    avisos, fatais = validar(triagem, diag, None)
    if fatais:
        raise RuntimeError("estágio 1 reprovou na validação: " + " · ".join(fatais))

    texto = call_stage2(diag, cover, anterior)
    blocos = parse_blocos(texto)
    a2, f2 = validar(triagem, diag, blocos)
    avisos += a2
    if f2:
        raise RuntimeError("estágio 2 reprovou na validação: " + " · ".join(f2))

    for b in ("pareceres", "recomendacoes", "leitura_portfolio"):
        blocos[b] = sanitize(blocos[b])

    os.makedirs(os.path.join(repo_root, DIAG_DIR), exist_ok=True)
    with open(os.path.join(repo_root, DIAG_DIR, f"{cutoff_dt.isoformat()}.json"), "w",
              encoding="utf-8") as f:
        json.dump(diag, f, ensure_ascii=False, indent=1)

    return {
        "gerado_em": cutoff_dt.isoformat(),
        "cover": cover,
        "modelo": _model(),
        "triagem": triagem,
        "triagem_html": render_triagem_html(triagem),
        "diagnostico": diag,
        "diagnostico_anterior_de": anterior_data,
        "blocos": blocos,
        "avisos": avisos,
    }
