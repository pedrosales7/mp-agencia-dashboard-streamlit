#!/usr/bin/env python3
"""Gera data/latest.json com dado ILUSTRATIVO no schema real (o mesmo que
weekly_refresh.py produziria a partir do Metabase) -- pra testar app.py/data.py
sem precisar de credencial do Metabase.

Roda com: .venv/bin/python scripts/generate_mock_data.py
"""
import json
import math
import os
from datetime import date, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
DATA_PATH = os.path.join(REPO_ROOT, "data", "latest.json")

PARTNER_COLORS = {
    "Loga": "#2563eb", "The Fiber": "#16a34a", "Direct": "#f59e0b", "Enove": "#7c3aed",
    "Interplus": "#dc2626", "Unifique": "#0891b2", "Ultranet": "#db2777", "Ativa Telecom": "#64748b",
}
PARTNERS = list(PARTNER_COLORS.keys())

# Totais de referência numa janela de 30 dias (mesmos números do protótipo aprovado)
GOOGLE_30D = {
    "Loga":          dict(bruto=46200, cashback=3700, cliques=8200, sessoes=7100, clickoff=1140, redirect=890, leads=312, vendas=89),
    "The Fiber":     dict(bruto=33800, cashback=2600, cliques=6100, sessoes=5300, clickoff=780,  redirect=610, leads=245, vendas=71),
    "Interplus":     dict(bruto=30100, cashback=2300, cliques=5400, sessoes=4600, clickoff=690,  redirect=520, leads=198, vendas=58),
    "Direct":        dict(bruto=24000, cashback=1900, cliques=4300, sessoes=3700, clickoff=540,  redirect=410, leads=167, vendas=42),
    "Enove":         dict(bruto=21000, cashback=1600, cliques=3900, sessoes=3300, clickoff=410,  redirect=290, leads=143, vendas=31),
    "Unifique":      dict(bruto=19200, cashback=2400, cliques=3400, sessoes=2900, clickoff=340,  redirect=240, leads=108, vendas=24),
    "Ultranet":      dict(bruto=16500, cashback=1300, cliques=2800, sessoes=2300, clickoff=210,  redirect=140, leads=76,  vendas=14),
    "Ativa Telecom": dict(bruto=13400, cashback=1000, cliques=2100, sessoes=1750, clickoff=98,   redirect=61,  leads=35,  vendas=13),
}
META_30D = {
    "Loga":          dict(bruto=28900, cashback=2100, cliques=15200, chat_start=2380, zip_search=2380, redirect=1810, leads=268, vendas=74),
    "The Fiber":     dict(bruto=21100, cashback=1500, cliques=11400, chat_start=1710, zip_search=1690, redirect=1240, leads=201, vendas=55),
    "Interplus":     dict(bruto=18800, cashback=1300, cliques=10100, chat_start=1414, zip_search=1390, redirect=990,  leads=165, vendas=44),
    "Direct":        dict(bruto=15000, cashback=1050, cliques=8200,  chat_start=1066, zip_search=1050, redirect=760,  leads=132, vendas=31),
    "Enove":         dict(bruto=13100, cashback=900,  cliques=7300,  chat_start=803,  zip_search=790,  redirect=560,  leads=104, vendas=21),
    "Unifique":      dict(bruto=12000, cashback=1400, cliques=6400,  chat_start=640,  zip_search=630,  redirect=440,  leads=74,  vendas=15),
    "Ultranet":      dict(bruto=10300, cashback=720,  cliques=5200,  chat_start=364,  zip_search=355,  redirect=230,  leads=48,  vendas=8),
    "Ativa Telecom": dict(bruto=8400,  cashback=560,  cliques=3900,  chat_start=195,  zip_search=188,  redirect=118,  leads=21,  vendas=7),
}


def seed_for(name):
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) % 997
    return h


def daily_factor(day_index, seed, weekday):
    weekday_mult = [1.05, 1.08, 1.06, 1.04, 0.95, 0.62, 0.55][weekday]  # seg..dom
    trend = 1 + (day_index / 180) * 0.18  # leve crescimento ao longo da janela
    wiggle = 1 + math.sin(seed + day_index * 0.35) * 0.10
    return weekday_mult * trend * wiggle


def spread_over_days(monthly_total, n_days, seed):
    """Distribui um total mensal em n_days dias com variação de dia da semana,
    preservando a soma exata (ajuste no último dia)."""
    daily_avg = monthly_total / 30
    values = []
    for i in range(n_days):
        d = date.today() - timedelta(days=1) - timedelta(days=n_days - 1 - i)
        f = daily_factor(i, seed, d.weekday())
        values.append(daily_avg * f)
    return values


def main():
    cutoff_dt = date.today() - timedelta(days=1)
    n_days = 180

    daily_snapshot = []
    daily_funnel_google = []
    daily_funnel_meta = []
    partner_weekly = {}
    credit_timeseries = {}

    for partner in PARTNERS:
        seed = seed_for(partner)
        g, m = GOOGLE_30D[partner], META_30D[partner]

        days = [(cutoff_dt - timedelta(days=n_days - 1 - i)).isoformat() for i in range(n_days)]

        g_bruto = spread_over_days(g["bruto"], n_days, seed + 1)
        g_cashback = spread_over_days(g["cashback"], n_days, seed + 2)
        g_leads = spread_over_days(g["leads"], n_days, seed + 3)
        g_vendas = spread_over_days(g["vendas"], n_days, seed + 4)
        m_bruto = spread_over_days(m["bruto"], n_days, seed + 11)
        m_cashback = spread_over_days(m["cashback"], n_days, seed + 12)
        m_leads = spread_over_days(m["leads"], n_days, seed + 13)
        m_vendas = spread_over_days(m["vendas"], n_days, seed + 14)

        g_cliques = spread_over_days(g["cliques"], n_days, seed + 21)
        g_sessoes = spread_over_days(g["sessoes"], n_days, seed + 22)
        g_clickoff = spread_over_days(g["clickoff"], n_days, seed + 23)
        g_redirect = spread_over_days(g["redirect"], n_days, seed + 24)
        m_cliques = spread_over_days(m["cliques"], n_days, seed + 31)
        m_chat = spread_over_days(m["chat_start"], n_days, seed + 32)
        m_zip = spread_over_days(m["zip_search"], n_days, seed + 33)
        m_redirect = spread_over_days(m["redirect"], n_days, seed + 34)

        for i, dia in enumerate(days):
            daily_snapshot.append({"dia": dia, "id_mp": partner, "canal": "google",
                                    "bruto": round(g_bruto[i]), "cashback": round(g_cashback[i]),
                                    "liquido": round(g_bruto[i] - g_cashback[i]),
                                    "leads": round(g_leads[i]), "vendas": round(g_vendas[i])})
            daily_snapshot.append({"dia": dia, "id_mp": partner, "canal": "meta",
                                    "bruto": round(m_bruto[i]), "cashback": round(m_cashback[i]),
                                    "liquido": round(m_bruto[i] - m_cashback[i]),
                                    "leads": round(m_leads[i]), "vendas": round(m_vendas[i])})
            daily_funnel_google.append({"dia": dia, "id_mp": partner,
                                         "cliques": round(g_cliques[i]), "sessoes": round(g_sessoes[i]),
                                         "clickoff": round(g_clickoff[i]), "redirect": round(g_redirect[i]),
                                         "leads": round(g_leads[i]), "vendas": round(g_vendas[i])})
            daily_funnel_meta.append({"dia": dia, "id_mp": partner,
                                       "cliques": round(m_cliques[i]), "chat_start": round(m_chat[i]),
                                       "zip_search": round(m_zip[i]), "redirect": round(m_redirect[i]),
                                       "leads": round(m_leads[i]), "vendas": round(m_vendas[i])})

        # partner_weekly (13 semanas) — soma diária por semana ISO (seg-dom)
        weeks = {}
        for i, dia in enumerate(days):
            d = date.fromisoformat(dia)
            ws = (d - timedelta(days=d.weekday())).isoformat()
            w = weeks.setdefault(ws, dict(bruto=0, cashback=0, liquido=0, cliques_g=0, cliques_m=0,
                                           clickoff_g=0, chat_start_m=0, leads_g=0, vendas_g=0, leads_m=0, vendas_m=0))
            w["bruto"] += g_bruto[i] + m_bruto[i]
            w["cashback"] += g_cashback[i] + m_cashback[i]
            w["liquido"] += (g_bruto[i] - g_cashback[i]) + (m_bruto[i] - m_cashback[i])
            w["cliques_g"] += g_cliques[i]; w["cliques_m"] += m_cliques[i]
            w["clickoff_g"] += g_clickoff[i]; w["chat_start_m"] += m_chat[i]
            w["leads_g"] += g_leads[i]; w["vendas_g"] += g_vendas[i]
            w["leads_m"] += m_leads[i]; w["vendas_m"] += m_vendas[i]
        full_weeks = sorted(ws for ws in weeks if (date.fromisoformat(ws) + timedelta(days=6)) <= cutoff_dt)
        partner_weekly[partner] = [
            {"ws": ws, **{k: round(v) for k, v in weeks[ws].items()}} for ws in full_weeks[-13:]
        ]

        # credit_timeseries (10 semanas) — saldo com padrão dente-de-serra
        base_credit = (g["bruto"] + m["bruto"]) * 2.6
        pattern = [1.00, 0.84, 0.68, 0.50, 1.15, 0.95, 0.76, 0.58, 0.38, 1.05]
        credit_weeks = full_weeks[-10:]
        credit_timeseries[partner] = [
            {"semana": ws, "credito": round(base_credit * pattern[i]), "total": round(base_credit * 1.3)}
            for i, ws in enumerate(credit_weeks)
        ]

    snapshot = {
        "snapshot": {"iso": f"{cutoff_dt.isoformat()}T08:37:00-03:00", "label": cutoff_dt.strftime("%d/%m/%y")},
        "partner_colors": PARTNER_COLORS,
        "daily_snapshot": daily_snapshot,
        "daily_funnel_google": daily_funnel_google,
        "daily_funnel_meta": daily_funnel_meta,
        "partner_weekly": partner_weekly,
        "credit_timeseries": credit_timeseries,
    }

    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, separators=(",", ":"))
    print(f"OK -> {DATA_PATH} ({os.path.getsize(DATA_PATH)//1024}KB) "
          f"daily_snapshot={len(daily_snapshot)} daily_funnel_google={len(daily_funnel_google)} "
          f"daily_funnel_meta={len(daily_funnel_meta)}")


if __name__ == "__main__":
    main()
