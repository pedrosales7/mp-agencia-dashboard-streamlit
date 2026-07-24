#!/usr/bin/env python3
"""Refresh semanal — versão Streamlit (sem estado).

Adaptado do weekly_refresh.py original (repo mp-agencia-dashboard), que
existe pra fazer o mesmo trabalho, mas escrevendo em docs/index.html em vez
de data/latest.json. Diferença de arquitetura, não de regra de negócio:

O script original precisa de um cache (data/cache/historical_data.json) e de
lógica de merge porque o HTML final carrega TODO o histórico pra sempre
(meses fechados de anos atrás continuam lá). Aqui não: guardamos só as
séries "cruas" que o Metabase já devolve com janela larga o suficiente numa
query só —

  DAILY_SNAPSHOT        últimos 180 dias (investimento + leads/vendas por
                         partner_id_partner, por dia x partner x canal)
  DAILY_FUNNEL_GOOGLE    últimos 180 dias (etapas do funil Google por dia,
                         leads/vendas por campanha/utm)
  DAILY_FUNNEL_META      idem, Meta/WhatsApp
  PARTNER_WEEKLY         últimas ~13 semanas (janela ampliada vs. o original,
                         que usa 70d — aqui dá pra pegar direto numa query só
                         em vez de depender de acúmulo de cache)
  CREDIT_TIMESERIES      últimas 10 semanas (janela fixa na query, 70d)

180 dias cobre folgado os filtros que o app oferece (7d/30d/90d + até 6
meses fechados no dropdown de Mês). Funil por período, cobertura,
detalhamento, progressão e taxas de conversão são todos derivados por
agregação em Python a partir dessas 5 séries — no refresh e no app (mesma
lógica, ver data.py). Isso elimina as janelas FUNNEL_GOOGLE/META por
period_key, PREV_FUNNEL_*, e o cache/merge inteiro do script original.

Armadilha crítica herdada: label_map do FUNNEL_META/DAILY_FUNNEL_META tem
2 linhas por partner -> sempre usar SELECT DISTINCT id_mp_canon (já embutido
nas queries de queries.sql, não precisa repetir aqui).
"""
import json
import os
import re
import sys
from datetime import date, timedelta

import requests

# ── configuração ──────────────────────────────────────────────────────────

METABASE_URL = os.environ["METABASE_URL"].rstrip("/")
METABASE_USERNAME = os.environ["METABASE_USERNAME"]
METABASE_PASSWORD = os.environ["METABASE_PASSWORD"]
STREAMLIT_URL = os.environ.get("STREAMLIT_URL", "")
SLACK_MENTION_ON_ERROR = os.environ.get("SLACK_MENTION_ON_ERROR", "")

TEST_MODE = os.environ.get("TEST_MODE", "").strip().lower() == "true"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL_TEST" if TEST_MODE else "SLACK_WEBHOOK_URL", "")

DATABASE_ID = 69

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
QUERIES_PATH = os.path.join(SCRIPT_DIR, "queries.sql")
DATA_PATH = os.path.join(REPO_ROOT, "data", "latest.json")

VALID_PARTNERS = ["loga-internet", "the fiber internet", "interplus internet", "direct internet",
                   "enove-fibra", "unifique", "ultranet-network", "ativa-telecom"]
PARTNER_LABELS = {
    "loga-internet": "Loga", "the fiber internet": "The Fiber", "interplus internet": "Interplus",
    "direct internet": "Direct", "enove-fibra": "Enove", "unifique": "Unifique",
    "ultranet-network": "Ultranet", "ativa-telecom": "Ativa Telecom",
}
PARTNER_COLORS = {
    "Loga": "#2563eb", "The Fiber": "#16a34a", "Direct": "#f59e0b", "Enove": "#7c3aed",
    "Interplus": "#dc2626", "Unifique": "#0891b2", "Ultranet": "#db2777", "Ativa Telecom": "#64748b",
}

WEEKLY_WINDOW_DAYS = 95  # ~13 semanas — cobre "últimas 12 semanas" da Progressão com folga


# ── Metabase client (idêntico ao script original) ──────────────────────────

class Metabase:
    def __init__(self, base_url, username, password):
        self.base_url = base_url
        resp = requests.post(f"{base_url}/api/session",
                              json={"username": username, "password": password}, timeout=30)
        resp.raise_for_status()
        self.token = resp.json()["id"]

    def query(self, sql):
        resp = requests.post(
            f"{self.base_url}/api/dataset",
            json={"database": DATABASE_ID, "type": "native", "native": {"query": sql}},
            headers={"X-Metabase-Session": self.token},
            timeout=180,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("error"):
            raise RuntimeError(f"Metabase query error: {body['error']}")
        data = body["data"]
        cols = [c["name"] for c in data["cols"]]
        return [dict(zip(cols, row)) for row in data["rows"]]


def load_queries(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    queries = {}
    for m in re.finditer(r"-- \[QUERY:(\w+)\]\n(.*?)-- \[/QUERY:\1\]", text, re.S):
        queries[m.group(1)] = m.group(2).strip()
    return queries


def norm_date(d):
    return str(d)[:10]


# ── transformações (label canônico -> label de exibição) ──────────────────

def to_label(id_mp):
    return PARTNER_LABELS.get(id_mp)


def clean_daily_snapshot(rows):
    out = []
    for r in rows:
        label = to_label(r["id_mp"])
        if not label:
            continue
        out.append({
            "dia": norm_date(r["dia"]), "id_mp": label, "canal": r["canal"],
            "bruto": round(r.get("bruto") or 0), "cashback": round(r.get("cashback") or 0),
            "liquido": round(r.get("liquido") or 0),
            "leads": r.get("leads") or 0, "vendas": r.get("vendas") or 0,
        })
    return out


def clean_daily_funnel_google(rows):
    out = []
    for r in rows:
        label = to_label(r["id_mp"])
        if not label:
            continue
        out.append({
            "dia": norm_date(r["dia"]), "id_mp": label,
            "cliques": r.get("cliques") or 0, "sessoes": r.get("sessoes") or 0,
            "clickoff": r.get("clickoff") or 0, "redirect": r.get("redirect") or 0,
            "leads": r.get("leads") or 0, "vendas": r.get("vendas") or 0,
        })
    return out


def clean_daily_funnel_meta(rows):
    out = []
    for r in rows:
        label = to_label(r["id_mp"])
        if not label:
            continue
        out.append({
            "dia": norm_date(r["dia"]), "id_mp": label,
            "cliques": r.get("cliques") or 0, "chat_start": r.get("chat_start") or 0,
            "zip_search": r.get("zip_search") or 0, "redirect": r.get("redirect") or 0,
            "leads": r.get("leads") or 0, "vendas": r.get("vendas") or 0,
        })
    return out


def clean_partner_weekly(rows):
    by_partner = {}
    for r in rows:
        label = to_label(r["id_mp"])
        if not label:
            continue
        by_partner.setdefault(label, []).append({
            "ws": norm_date(r["semana"]),
            "bruto": round(r.get("bruto") or 0), "cashback": round(r.get("cashback") or 0),
            "liquido": round(r.get("liquido") or 0),
            "cliques_g": r.get("cliques_g") or 0, "cliques_m": r.get("cliques_m") or 0,
            "clickoff_g": r.get("clickoff_g") or 0, "chat_start_m": r.get("chat_start_m") or 0,
            "leads_g": r.get("leads_g") or 0, "vendas_g": r.get("vendas_g") or 0,
            "leads_m": r.get("leads_m") or 0, "vendas_m": r.get("vendas_m") or 0,
        })
    for label, weeks in by_partner.items():
        weeks.sort(key=lambda w: w["ws"])
    return by_partner


def clean_credit_timeseries(rows):
    by_partner = {}
    for r in rows:
        label = to_label(r["id_mp"])
        if not label:
            continue
        by_partner.setdefault(label, []).append({
            "semana": norm_date(r["semana"]),
            "credito": round(r.get("credito") or 0), "total": round(r.get("total") or 0),
        })
    for label, weeks in by_partner.items():
        weeks.sort(key=lambda w: w["semana"])
    return by_partner


# ── Slack ─────────────────────────────────────────────────────────────────

def slack_post(text):
    if not SLACK_WEBHOOK_URL:
        print("SLACK_WEBHOOK_URL não configurado — pulando post no Slack.")
        return
    resp = requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=30)
    resp.raise_for_status()


# ── main ──────────────────────────────────────────────────────────────────

def main():
    today = date.today()
    cutoff_dt = today - timedelta(days=1)  # nunca usar o dia atual — dados parciais
    cutoff = cutoff_dt.isoformat()
    cover = cutoff_dt.strftime("%d/%m/%y")
    weekly_start = (cutoff_dt - timedelta(days=WEEKLY_WINDOW_DAYS)).isoformat()

    queries = load_queries(QUERIES_PATH)
    mb = Metabase(METABASE_URL, METABASE_USERNAME, METABASE_PASSWORD)

    def run(name, sql):
        print(f"Rodando query {name}...")
        rows = mb.query(sql)
        print(f"  {len(rows)} linhas")
        return rows

    daily_snapshot_sql = queries["DAILY_SNAPSHOT"].replace("{{CUTOFF}}", cutoff)
    daily_snapshot = clean_daily_snapshot(run("DAILY_SNAPSHOT", daily_snapshot_sql))

    dfg_sql = queries["DAILY_FUNNEL_GOOGLE"].replace("{{CUTOFF}}", cutoff)
    daily_funnel_google = clean_daily_funnel_google(run("DAILY_FUNNEL_GOOGLE", dfg_sql))

    dfm_sql = queries["DAILY_FUNNEL_META"].replace("{{CUTOFF}}", cutoff)
    daily_funnel_meta = clean_daily_funnel_meta(run("DAILY_FUNNEL_META", dfm_sql))

    weekly_sql = (queries["PARTNER_WEEKLY"]
                  .replace("{{CUTOFF}}", cutoff)
                  .replace("{{WEEKLY_START}}", weekly_start))
    partner_weekly = clean_partner_weekly(run("PARTNER_WEEKLY", weekly_sql))

    credit_sql = queries["CREDIT_TIMESERIES"].replace("{{CUTOFF}}", cutoff)
    credit_timeseries = clean_credit_timeseries(run("CREDIT_TIMESERIES", credit_sql))

    snapshot = {
        "snapshot": {"iso": f"{cutoff}T08:37:00-03:00", "label": cover},
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

    print(f"OK daily_snapshot={len(daily_snapshot)} daily_funnel_google={len(daily_funnel_google)} "
          f"daily_funnel_meta={len(daily_funnel_meta)} partner_weekly_partners={len(partner_weekly)} "
          f"credit_partners={len(credit_timeseries)}")

    dashboard_url = f"{STREAMLIT_URL}" if STREAMLIT_URL else None
    link_line = f"\n{dashboard_url}\n" if dashboard_url else "\n(link do Streamlit ainda não configurado)\n"
    prefix = "🧪 [TESTE — só você vê isso]\n" if TEST_MODE else ""
    channel_mention = "" if TEST_MODE else "\n<!channel>"
    slack_post(
        f"{prefix}📊 Dashboard MP Agência — Funil Ads-to-Sale, versão Streamlit ({cover})\n"
        f"Dados atualizados com snapshot de {cover}. Acesse o dashboard interativo:"
        f"{link_line}{channel_mention}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            prefix = "🧪 [TESTE] " if TEST_MODE else ""
            slack_post(f"{prefix}⚠️ Problema no refresh do dashboard MP Agência (Streamlit): {e} "
                       f"{SLACK_MENTION_ON_ERROR} verifica?")
        except Exception:
            pass
        print(f"ERRO: {e}", file=sys.stderr)
        sys.exit(1)
