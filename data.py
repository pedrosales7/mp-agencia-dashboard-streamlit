"""Camada de dados do dashboard.

Lê o snapshot semanal gerado pelo refresh (data/latest.json): 5 séries cruas
(diárias de 180 dias + semanais de ~13 semanas), sem nenhuma agregação por
período pré-calculada. Todo o resto -- funil por período (7d/30d/90d/mês),
cobertura, detalhamento, progressão e taxas de conversão -- é derivado aqui
por agregação em pandas, filtrando essas séries pela janela de data pedida.
Mesma abordagem que o dashboard HTML atual usa no navegador para período
customizado (agg_daily / build_compact_daily_funnel), só que em Python.

Nenhuma conexão com Metabase/Redshift acontece aqui -- isso é responsabilidade
exclusiva do weekly_refresh.py que roda no GitHub Actions.
"""

import json
import math
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

DATA_PATH = Path(__file__).parent / "data" / "latest.json"

OUTLIER_LOW = 0.5
OUTLIER_HIGH = 2.0

PT_MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def load_snapshot():
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


SNAPSHOT = load_snapshot()
PARTNER_COLORS = SNAPSHOT["partner_colors"]
PARTNERS = list(PARTNER_COLORS.keys())

_daily_snapshot = pd.DataFrame(SNAPSHOT["daily_snapshot"])
_daily_google = pd.DataFrame(SNAPSHOT["daily_funnel_google"])
_daily_meta = pd.DataFrame(SNAPSHOT["daily_funnel_meta"])
PARTNER_WEEKLY = SNAPSHOT["partner_weekly"]
CREDIT_TIMESERIES = SNAPSHOT["credit_timeseries"]

CUTOFF = max(_daily_snapshot["dia"].max(), _daily_google["dia"].max(), _daily_meta["dia"].max())
CUTOFF_DATE = date.fromisoformat(CUTOFF)


# ------------------------------------------------------------------
# Helpers (equivalentes ao dashboard HTML atual)
# ------------------------------------------------------------------
def fmt_brl(v, casas=0):
    if v is None or not math.isfinite(v):
        return "—"
    return "R$ " + f"{v:,.{casas}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def fmt_num(v):
    if v is None:
        return "—"
    return f"{round(v):,}".replace(",", ".")


def fmt_pct(v):
    if v is None or not math.isfinite(v):
        return "—"
    return f"{v * 100:.1f}%"


def safe_div(a, b):
    return a / b if b else None


def median(values):
    vals = sorted(v for v in values if v is not None and math.isfinite(v))
    n = len(vals)
    if n < 2:
        return None
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2


def outlier_status(value, med, mode):
    """mode='rate': baixo=ruim, alto=bom. mode='cost': alto=ruim, baixo=bom."""
    if med is None or med <= 0 or value is None or not math.isfinite(value):
        return None
    ratio = value / med
    if mode == "rate":
        if ratio < OUTLIER_LOW:
            return "bad"
        if ratio > OUTLIER_HIGH:
            return "good"
    elif mode == "cost":
        if ratio > OUTLIER_HIGH:
            return "bad"
        if ratio < OUTLIER_LOW:
            return "good"
    return None


def month_label(mk):
    y, m = mk.split("-")
    return f"{PT_MONTHS[int(m) - 1]}/{y[2:]}"


# ------------------------------------------------------------------
# Janelas de período
# ------------------------------------------------------------------
def period_window(period_key):
    """period_key: '7d' | '30d' | '90d' | 'YYYY-MM' (mês fechado ou corrente)."""
    if period_key in ("7d", "30d", "90d"):
        days = int(period_key[:-1])
        d_ini = (CUTOFF_DATE - timedelta(days=days - 1)).isoformat()
        return d_ini, CUTOFF
    y, m = int(period_key[:4]), int(period_key[5:7])
    d_ini = date(y, m, 1)
    next_m = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
    d_fim = min(next_m - timedelta(days=1), CUTOFF_DATE)
    return d_ini.isoformat(), d_fim.isoformat()


def available_month_keys():
    keys = sorted({d[:7] for d in _daily_snapshot["dia"]}, reverse=True)
    return keys[:6]


def previous_window(d_ini, d_fim):
    """Janela imediatamente anterior, do mesmo tamanho -- pra comparação real
    'vs período anterior', em vez de estimativa."""
    ini, fim = date.fromisoformat(d_ini), date.fromisoformat(d_fim)
    span = (fim - ini).days
    prev_fim = ini - timedelta(days=1)
    prev_ini = prev_fim - timedelta(days=span)
    return prev_ini.isoformat(), prev_fim.isoformat()


# ------------------------------------------------------------------
# Funis (Google / Meta) -- agregados por janela de data
# ------------------------------------------------------------------
def _window_mask(df, d_ini, d_fim):
    return (df["dia"] >= d_ini) & (df["dia"] <= d_fim)


def _funnel_df(kind, d_ini, d_fim):
    daily = _daily_google if kind == "google" else _daily_meta
    step_cols = ["cliques", "sessoes", "clickoff", "redirect", "leads", "vendas"] if kind == "google" \
        else ["cliques", "chat_start", "zip_search", "redirect", "leads", "vendas"]
    sub = daily[_window_mask(daily, d_ini, d_fim)]
    agg = sub.groupby("id_mp")[step_cols].sum() if len(sub) else pd.DataFrame(columns=step_cols)
    agg = agg.reindex(PARTNERS, fill_value=0).reset_index().rename(columns={"index": "id_mp"})

    snap = _daily_snapshot[(_daily_snapshot["canal"] == kind) & _window_mask(_daily_snapshot, d_ini, d_fim)]
    inv = snap.groupby("id_mp")[["bruto", "cashback"]].sum() if len(snap) else pd.DataFrame(columns=["bruto", "cashback"])
    inv = inv.reindex(PARTNERS, fill_value=0).reset_index().rename(columns={"index": "id_mp"})

    df = agg.merge(inv, on="id_mp")
    df["liquido"] = df["bruto"] - df["cashback"]
    df["cpc"] = df["bruto"] / df["cliques"]
    df["cpl"] = df["liquido"] / df["leads"]
    df["cac"] = df["liquido"] / df["vendas"]
    df["conv_final"] = df["vendas"] / df["cliques"]
    return df


def build_google_df(d_ini, d_fim):
    return _funnel_df("google", d_ini, d_fim)


def build_meta_df(d_ini, d_fim):
    return _funnel_df("meta", d_ini, d_fim)


def funnel_step_config(kind):
    if kind == "google":
        return ["sessoes", "clickoff", "redirect", "leads", "vendas"], \
               ["Sessões", "Clickoff", "Redirect", "Leads", "Vendas"], 30
    return ["chat_start", "zip_search", "redirect", "leads", "vendas"], \
           ["Chat start", "Zip search", "Redirect", "Leads", "Vendas"], 100


def funnel_medians(df, step_keys, min_cliques):
    peers = df[df["cliques"] >= min_cliques]
    meds = {}
    prev_key = "cliques"
    for k in step_keys:
        valid = peers[peers[prev_key] > 0]
        meds[k] = median((valid[k] / valid[prev_key]).tolist()) if len(valid) else None
        prev_key = k
    meds["conv_final"] = median(peers["conv_final"].tolist())
    vendas_ok = peers[peers["vendas"] > 0]
    meds["cac"] = median((vendas_ok["liquido"] / vendas_ok["vendas"]).tolist()) if len(vendas_ok) else None
    leads_ok = peers[peers["leads"] >= 3]
    meds["cpl"] = median((leads_ok["liquido"] / leads_ok["leads"]).tolist()) if len(leads_ok) else None
    return meds


def compute_totals(d_ini, d_fim, canal_filter):
    parts = []
    if not canal_filter or canal_filter == "google":
        parts.append(_daily_snapshot[(_daily_snapshot["canal"] == "google") & _window_mask(_daily_snapshot, d_ini, d_fim)])
    if not canal_filter or canal_filter == "meta":
        parts.append(_daily_snapshot[(_daily_snapshot["canal"] == "meta") & _window_mask(_daily_snapshot, d_ini, d_fim)])
    combined = pd.concat(parts) if parts else _daily_snapshot.iloc[0:0]
    bruto, cashback = combined["bruto"].sum(), combined["cashback"].sum()
    leads, vendas = combined["leads"].sum(), combined["vendas"].sum()
    liquido = bruto - cashback
    return {
        "bruto": bruto, "cashback": cashback, "liquido": liquido, "leads": leads, "vendas": vendas,
        "cpl": safe_div(liquido, leads), "cac": safe_div(liquido, vendas),
        "rate": safe_div(vendas, leads),
    }


# ------------------------------------------------------------------
# Cobertura e Assertividade -- 1 linha por partner, Google/Meta lado a lado
# (cada canal tem sua própria base -- Clickoff pro Google, Chat start pro
# Meta -- então não faz sentido somar; layout replicado do dashboard atual).
# ------------------------------------------------------------------
def _coverage_channel_metrics(partner, inv, funnel, vol_col):
    bruto = inv["bruto"].get(partner, 0)
    cashback = inv["cashback"].get(partner, 0)
    total_leads = funnel[vol_col].get(partner, 0) if partner in funnel.index else 0
    covered_leads = funnel["leads"].get(partner, 0) if partner in funnel.index else 0
    return {
        "bruto": bruto, "cashback": cashback, "pct_cashback": safe_div(cashback, bruto),
        "total_leads": total_leads, "covered_leads": covered_leads,
        "pct_assert": safe_div(covered_leads, total_leads),
    }


def build_coverage_df(d_ini, d_fim, canal_filter):
    g_funnel = _daily_google[_window_mask(_daily_google, d_ini, d_fim)].groupby("id_mp")[["clickoff", "leads"]].sum()
    m_funnel = _daily_meta[_window_mask(_daily_meta, d_ini, d_fim)].groupby("id_mp")[["chat_start", "leads"]].sum()
    snap = _daily_snapshot[_window_mask(_daily_snapshot, d_ini, d_fim)]
    g_inv = snap[snap["canal"] == "google"].groupby("id_mp")[["bruto", "cashback"]].sum()
    m_inv = snap[snap["canal"] == "meta"].groupby("id_mp")[["bruto", "cashback"]].sum()

    rows = []
    for p in PARTNERS:
        row = {"id_mp": p}
        for prefix, metrics in (("g", _coverage_channel_metrics(p, g_inv, g_funnel, "clickoff")),
                                 ("m", _coverage_channel_metrics(p, m_inv, m_funnel, "chat_start"))):
            for k, v in metrics.items():
                row[f"{prefix}_{k}"] = v
        rows.append(row)
    df = pd.DataFrame(rows)

    def channel_medians(bruto_col, cash_col, leads_col, assert_col):
        elig = df[df[bruto_col] >= 100]
        med_cash = median(elig[cash_col].tolist())
        elig2 = elig[elig[leads_col] >= 20]
        med_asr = median(elig2[assert_col].tolist())
        return med_cash, med_asr

    med_cash_g, med_asr_g = channel_medians("g_bruto", "g_pct_cashback", "g_total_leads", "g_pct_assert")
    med_cash_m, med_asr_m = channel_medians("m_bruto", "m_pct_cashback", "m_total_leads", "m_pct_assert")

    def status_row(row):
        elig_cash_g, elig_asr_g = row["g_bruto"] >= 100, row["g_bruto"] >= 100 and row["g_total_leads"] >= 20
        elig_cash_m, elig_asr_m = row["m_bruto"] >= 100, row["m_bruto"] >= 100 and row["m_total_leads"] >= 20
        return pd.Series({
            "g_status_cash": outlier_status(row["g_pct_cashback"], med_cash_g, "cost") if elig_cash_g else None,
            "g_status_asr": outlier_status(row["g_pct_assert"], med_asr_g, "rate") if elig_asr_g else None,
            "g_elig_asr": elig_asr_g,
            "m_status_cash": outlier_status(row["m_pct_cashback"], med_cash_m, "cost") if elig_cash_m else None,
            "m_status_asr": outlier_status(row["m_pct_assert"], med_asr_m, "rate") if elig_asr_m else None,
            "m_elig_asr": elig_asr_m,
        })

    df = df.join(df.apply(status_row, axis=1))

    if canal_filter == "google":
        for c in [c for c in df.columns if c.startswith("m_")]:
            df[c] = None
    elif canal_filter == "meta":
        for c in [c for c in df.columns if c.startswith("g_")]:
            df[c] = None

    df["_sort"] = df["g_bruto"].fillna(0) + df["m_bruto"].fillna(0)
    return df.sort_values("_sort", ascending=False).drop(columns="_sort")


# ------------------------------------------------------------------
# Progressão por partner
# ------------------------------------------------------------------
def _week_start(dstr):
    d = date.fromisoformat(dstr)
    return (d - timedelta(days=d.weekday())).isoformat()


def build_progressao_df(id_mp, granularity):
    if granularity == "weekly":
        rows = PARTNER_WEEKLY.get(id_mp, [])[-12:]
        out = []
        for r in rows:
            leads = r["leads_g"] + r["leads_m"]
            vendas = r["vendas_g"] + r["vendas_m"]
            liquido = r["liquido"]
            out.append({
                "label": f'{r["ws"][8:10]}/{r["ws"][5:7]}',
                "bruto": r["bruto"], "cashback": r["cashback"], "liquido": liquido,
                "pct_cashback": safe_div(r["cashback"], r["bruto"]),
                "cliques": r["cliques_g"] + r["cliques_m"],
                "clickoff_g": r["clickoff_g"], "chat_start_m": r["chat_start_m"],
                "leads": leads, "vendas": vendas,
                "cpl": safe_div(liquido, leads), "cac": safe_div(liquido, vendas),
                "lead_venda": safe_div(vendas, leads),
                "asr_g": safe_div(r["leads_g"], r["clickoff_g"]),
                "asr_m": safe_div(r["leads_m"], r["chat_start_m"]),
            })
        return pd.DataFrame(out)

    # mensal -- agrega as séries diárias por mês, últimos 5 meses fechados
    snap = _daily_snapshot[_daily_snapshot["id_mp"] == id_mp].copy()
    fg = _daily_google[_daily_google["id_mp"] == id_mp].copy()
    fm = _daily_meta[_daily_meta["id_mp"] == id_mp].copy()
    for df_ in (snap, fg, fm):
        df_["mes"] = df_["dia"].str.slice(0, 7)
    current_month = CUTOFF[:7]
    months = sorted({m for m in snap["mes"] if m != current_month})[-5:]

    out = []
    for mk in months:
        s = snap[snap["mes"] == mk]
        g = fg[fg["mes"] == mk]
        m = fm[fm["mes"] == mk]
        bruto, cashback = s["bruto"].sum(), s["cashback"].sum()
        liquido = bruto - cashback
        leads_g, vendas_g, clickoff_g = g["leads"].sum(), g["vendas"].sum(), g["clickoff"].sum()
        leads_m, vendas_m, chat_start_m = m["leads"].sum(), m["vendas"].sum(), m["chat_start"].sum()
        leads, vendas = leads_g + leads_m, vendas_g + vendas_m
        out.append({
            "label": month_label(mk), "bruto": bruto, "cashback": cashback, "liquido": liquido,
            "pct_cashback": safe_div(cashback, bruto),
            "cliques": g["cliques"].sum() + m["cliques"].sum(),
            "clickoff_g": clickoff_g, "chat_start_m": chat_start_m,
            "leads": leads, "vendas": vendas,
            "cpl": safe_div(liquido, leads), "cac": safe_div(liquido, vendas),
            "lead_venda": safe_div(vendas, leads),
            "asr_g": safe_div(leads_g, clickoff_g), "asr_m": safe_div(leads_m, chat_start_m),
        })
    return pd.DataFrame(out)


# ------------------------------------------------------------------
# Evolução das taxas de conversão
# ------------------------------------------------------------------
TAXAS_MIN_DENOM = 5
STAGES_G = [("Clique", "Sessão", "sessoes_g", "cliques_g"),
            ("Sessão", "Clickoff", "clickoff_g", "sessoes_g"),
            ("Clickoff", "Redirect", "redirect_g", "clickoff_g"),
            ("Redirect", "Lead", "leads_g", "redirect_g"),
            ("Lead", "Venda", "vendas_g", "leads_g")]
STAGES_M = [("Clique", "Chat start", "chat_start_m", "cliques_m"),
            ("Chat start", "Zip search", "zip_search_m", "chat_start_m"),
            ("Zip search", "Redirect", "redirect_m", "zip_search_m"),
            ("Redirect", "Lead", "leads_m", "redirect_m"),
            ("Lead", "Venda", "vendas_m", "leads_m")]


def taxa_value(num, den):
    if not den or den < TAXAS_MIN_DENOM:
        return None
    return num / den


def build_taxas_df(id_mp, granularity):
    fg = _daily_google[_daily_google["id_mp"] == id_mp].copy()
    fm = _daily_meta[_daily_meta["id_mp"] == id_mp].copy()

    if granularity == "weekly":
        for df_ in (fg, fm):
            df_["bucket"] = df_["dia"].apply(_week_start)
        buckets = sorted({b for b in fg["bucket"]} | {b for b in fm["bucket"]})
        buckets = [b for b in buckets if (date.fromisoformat(b) + timedelta(days=6)) <= CUTOFF_DATE][-8:]
        label = lambda b: f"{b[8:10]}/{b[5:7]}"
    else:
        for df_ in (fg, fm):
            df_["bucket"] = df_["dia"].str.slice(0, 7)
        current_month = CUTOFF[:7]
        buckets = sorted({b for b in fg["bucket"] if b != current_month} | {b for b in fm["bucket"] if b != current_month})[-5:]
        label = month_label

    rows = []
    for b in buckets:
        g = fg[fg["bucket"] == b]
        m = fm[fm["bucket"] == b]
        rows.append({
            "label": label(b),
            "cliques_g": g["cliques"].sum(), "sessoes_g": g["sessoes"].sum(),
            "clickoff_g": g["clickoff"].sum(), "redirect_g": g["redirect"].sum(),
            "leads_g": g["leads"].sum(), "vendas_g": g["vendas"].sum(),
            "cliques_m": m["cliques"].sum(), "chat_start_m": m["chat_start"].sum(),
            "zip_search_m": m["zip_search"].sum(), "redirect_m": m["redirect"].sum(),
            "leads_m": m["leads"].sum(), "vendas_m": m["vendas"].sum(),
        })
    return pd.DataFrame(rows)
