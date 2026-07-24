"""Camada de dados do dashboard.

Lê o snapshot semanal gerado pelo refresh (data/latest.json). Nenhuma conexão
com Metabase/Redshift acontece aqui -- isso é responsabilidade exclusiva do
weekly_refresh.py que roda no GitHub Actions.

Progressão/Taxas ainda não têm histórico diário real disponível no snapshot,
então são derivadas por escala determinística a partir do número atual --
mesmo mecanismo usado no protótipo em HTML. Quando o refresh passar a gravar
séries semanais/mensais de verdade, troca-se só as funções build_progressao_df
e build_taxas_df por leitura direta do snapshot.
"""

import json
import math
from pathlib import Path

import pandas as pd

DATA_PATH = Path(__file__).parent / "data" / "latest.json"

OUTLIER_LOW = 0.5
OUTLIER_HIGH = 2.0

MONTH_LABELS = ["fev/26", "mar/26", "abr/26", "mai/26", "jun/26"]
WEEK_LABELS_12 = ["04/05", "11/05", "18/05", "25/05", "01/06", "08/06",
                  "15/06", "22/06", "29/06", "06/07", "13/07", "20/07"]
WEEK_LABELS_8 = WEEK_LABELS_12[-8:]


def load_snapshot():
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


SNAPSHOT = load_snapshot()
PARTNER_COLORS = SNAPSHOT["partner_colors"]
PARTNERS = list(PARTNER_COLORS.keys())


# ------------------------------------------------------------------
# Helpers (equivalentes ao dashboard HTML atual)
# ------------------------------------------------------------------
def fmt_brl(v, casas=0):
    if v is None:
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


def seed_for(name):
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) % 997
    return h


def scale_series(latest, n, growth, seed):
    out = []
    for i in range(n):
        steps_back = n - 1 - i
        base = latest / ((1 + growth) ** steps_back)
        wiggle = 1 + math.sin(seed + i * 1.7) * 0.045
        out.append(max(0.0, base * wiggle))
    return out


# ------------------------------------------------------------------
# Funis (Google / Meta)
# ------------------------------------------------------------------
def _funnel_df(kind):
    rows = SNAPSHOT["google_funnel"] if kind == "google" else SNAPSHOT["meta_funnel"]
    df = pd.DataFrame(rows)
    df["liquido"] = df["bruto"] - df["cashback"]
    df["cpc"] = df["bruto"] / df["cliques"]
    df["cpl"] = df["liquido"] / df["leads"]
    df["cac"] = df["liquido"] / df["vendas"]
    df["conv_final"] = df["vendas"] / df["cliques"]
    return df


def build_google_df():
    return _funnel_df("google")


def build_meta_df():
    return _funnel_df("meta")


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


def compute_totals(canal_filter):
    g = pd.DataFrame(SNAPSHOT["google_funnel"])
    m = pd.DataFrame(SNAPSHOT["meta_funnel"])
    parts = []
    if not canal_filter or canal_filter == "google":
        parts.append(g)
    if not canal_filter or canal_filter == "meta":
        parts.append(m)
    combined = pd.concat(parts)
    bruto, cashback = combined["bruto"].sum(), combined["cashback"].sum()
    leads, vendas = combined["leads"].sum(), combined["vendas"].sum()
    liquido = bruto - cashback
    return {
        "liquido": liquido, "leads": leads, "vendas": vendas,
        "cpl": safe_div(liquido, leads), "cac": safe_div(liquido, vendas),
        "rate": safe_div(vendas, leads),
    }


# ------------------------------------------------------------------
# Cobertura e Assertividade
# ------------------------------------------------------------------
def build_coverage_df(canal_filter):
    rows = []
    for r in SNAPSHOT["google_funnel"]:
        rows.append({"id_mp": r["id_mp"], "canal": "google", "bruto": r["bruto"],
                      "cashback": r["cashback"], "vol_base": r["clickoff"], "leads": r["leads"],
                      "base_label": "Clickoff"})
    for r in SNAPSHOT["meta_funnel"]:
        rows.append({"id_mp": r["id_mp"], "canal": "meta", "bruto": r["bruto"],
                      "cashback": r["cashback"], "vol_base": r["chat_start"], "leads": r["leads"],
                      "base_label": "Chat start"})
    df = pd.DataFrame(rows)
    if canal_filter:
        df = df[df["canal"] == canal_filter]
    df["pct_cashback"] = df["cashback"] / df["bruto"]
    df["pct_assert"] = df["leads"] / df["vol_base"]

    meds = {}
    for canal in ("google", "meta"):
        sub = df[(df["canal"] == canal) & (df["bruto"] >= 100)]
        meds[(canal, "cash")] = median(sub["pct_cashback"].tolist())
        sub2 = sub[sub["vol_base"] >= 20]
        meds[(canal, "asr")] = median(sub2["pct_assert"].tolist())

    def row_status(row):
        elig_cash = row["bruto"] >= 100
        elig_asr = row["bruto"] >= 100 and row["vol_base"] >= 20
        cls_cash = outlier_status(row["pct_cashback"], meds[(row["canal"], "cash")], "cost") if elig_cash else None
        cls_asr = outlier_status(row["pct_assert"], meds[(row["canal"], "asr")], "rate") if elig_asr else None
        return pd.Series({"status_cash": cls_cash, "status_asr": cls_asr, "elig_asr": elig_asr})

    df = df.join(df.apply(row_status, axis=1))
    return df.sort_values("bruto", ascending=False)


# ------------------------------------------------------------------
# Detalhamento consolidado
# ------------------------------------------------------------------
def build_detail_df(canal_filter):
    g = pd.DataFrame(SNAPSHOT["google_funnel"])[["id_mp", "bruto", "cashback", "leads", "vendas"]]
    m = pd.DataFrame(SNAPSHOT["meta_funnel"])[["id_mp", "bruto", "cashback", "leads", "vendas"]]
    if canal_filter == "google":
        combined = g
    elif canal_filter == "meta":
        combined = m
    else:
        combined = pd.concat([g, m]).groupby("id_mp", as_index=False).sum()
        combined["id_mp"] = pd.Categorical(combined["id_mp"], categories=PARTNERS, ordered=True)
        combined = combined.sort_values("id_mp").reset_index(drop=True)
        combined["id_mp"] = combined["id_mp"].astype(str)

    df = combined.copy()
    df["liquido"] = df["bruto"] - df["cashback"]
    df["cpl"] = df["liquido"] / df["leads"]
    df["cac"] = df.apply(lambda r: safe_div(r["liquido"], r["vendas"]), axis=1)
    df["rate"] = df["leads"].apply(lambda x: None) if False else df["vendas"] / df["leads"]
    df["warn"] = (df["bruto"] > 0) & (df["leads"] == 0)

    peers = df[df["leads"] >= 3]
    med_rate = median(peers["rate"].tolist())
    med_cac = median(peers[peers["vendas"] > 0]["cac"].tolist())
    med_cpl = median(peers["cpl"].tolist())

    def status(row):
        elig = row["leads"] >= 3
        return pd.Series({
            "status_rate": outlier_status(row["rate"], med_rate, "rate") if elig else None,
            "status_cac": outlier_status(row["cac"], med_cac, "cost") if elig else None,
            "status_cpl": outlier_status(row["cpl"], med_cpl, "cost") if elig else None,
        })

    df = df.join(df.apply(status, axis=1))
    return df.sort_values("liquido", ascending=False)


# ------------------------------------------------------------------
# Progressão por partner
# ------------------------------------------------------------------
def _partner_latest(id_mp):
    g = next(r for r in SNAPSHOT["google_funnel"] if r["id_mp"] == id_mp)
    m = next(r for r in SNAPSHOT["meta_funnel"] if r["id_mp"] == id_mp)
    return g, m


def build_progressao_df(id_mp, granularity):
    g, m = _partner_latest(id_mp)
    n = 12 if granularity == "weekly" else 5
    labels = WEEK_LABELS_12 if granularity == "weekly" else MONTH_LABELS
    div = 4.3 if granularity == "weekly" else 1
    seed = seed_for(id_mp)

    def mk(val, growth, offset):
        return scale_series(val / div, n, growth, seed + offset)

    bruto = mk(g["bruto"] + m["bruto"], 0.02, 0)
    cashback = mk(g["cashback"] + m["cashback"], 0.015, 1)
    cliques_g = mk(g["cliques"], 0.025, 2)
    cliques_m = mk(m["cliques"], 0.02, 3)
    clickoff_g = mk(g["clickoff"], 0.03, 4)
    chat_start_m = mk(m["chat_start"], 0.022, 5)
    leads_g = mk(g["leads"], 0.018, 6)
    leads_m = mk(m["leads"], 0.018, 7)
    vendas_g = mk(g["vendas"], 0.02, 8)
    vendas_m = mk(m["vendas"], 0.02, 9)

    rows = []
    for i, label in enumerate(labels):
        bruto_i, cashback_i = bruto[i], cashback[i]
        leads_i = leads_g[i] + leads_m[i]
        vendas_i = vendas_g[i] + vendas_m[i]
        liquido_i = bruto_i - cashback_i
        rows.append({
            "label": label, "bruto": bruto_i, "cashback": cashback_i, "liquido": liquido_i,
            "pct_cashback": safe_div(cashback_i, bruto_i),
            "cliques": cliques_g[i] + cliques_m[i],
            "clickoff_g": clickoff_g[i], "chat_start_m": chat_start_m[i],
            "leads": leads_i, "vendas": vendas_i,
            "cpl": safe_div(liquido_i, leads_i), "cac": safe_div(liquido_i, vendas_i),
            "lead_venda": safe_div(vendas_i, leads_i),
            "asr_g": safe_div(leads_g[i], clickoff_g[i]),
            "asr_m": safe_div(leads_m[i], chat_start_m[i]),
        })
    return pd.DataFrame(rows)


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
    g, m = _partner_latest(id_mp)
    n = 8 if granularity == "weekly" else 5
    labels = WEEK_LABELS_8 if granularity == "weekly" else MONTH_LABELS
    div = 4.3 if granularity == "weekly" else 1
    seed = seed_for(id_mp) + 40

    def mk(val, growth, offset):
        return scale_series(val / div, n, growth, seed + offset)

    series = {
        "cliques_g": mk(g["cliques"], 0.02, 0), "sessoes_g": mk(g["sessoes"], 0.018, 1),
        "clickoff_g": mk(g["clickoff"], 0.03, 2), "redirect_g": mk(g["redirect"], 0.025, 3),
        "leads_g": mk(g["leads"], 0.015, 4), "vendas_g": mk(g["vendas"], 0.02, 5),
        "cliques_m": mk(m["cliques"], 0.02, 6), "chat_start_m": mk(m["chat_start"], 0.02, 7),
        "zip_search_m": mk(m["zip_search"], 0.02, 8), "redirect_m": mk(m["redirect"], 0.022, 9),
        "leads_m": mk(m["leads"], 0.015, 10), "vendas_m": mk(m["vendas"], 0.02, 11),
    }
    rows = []
    for i, label in enumerate(labels):
        rows.append({"label": label, **{k: v[i] for k, v in series.items()}})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------
# Crédito remanescente por parceiro
# ------------------------------------------------------------------
def build_credit_df(partner_filter=None):
    weeks = list(range(1, 15))
    pattern = [1.00, 0.84, 0.68, 0.50, 1.15, 0.95, 0.76, 0.58, 0.38, 1.05, 0.88, 0.66, 0.44]
    records = []
    for id_mp in PARTNERS:
        if partner_filter and id_mp not in partner_filter:
            continue
        g, m = _partner_latest(id_mp)
        base_credit = (g["bruto"] + m["bruto"]) * 2.6
        last = -0.06 if id_mp == "Ativa Telecom" else 0.22
        vals = [base_credit * p for p in pattern] + [base_credit * last]
        for w, v in zip(weeks, vals):
            records.append({"id_mp": id_mp, "semana": w, "credito": v})
    return pd.DataFrame(records)
