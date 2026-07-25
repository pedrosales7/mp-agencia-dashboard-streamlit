"""Aba "Análise da semana" — só renderiza o que o refresh já gerou.

Nenhuma chamada de LLM acontece aqui. O pipeline roda 1x por semana no
GitHub Actions (scripts/ai_analysis.py) e grava data/analysis.json; esta
aba lê o arquivo. É o que mantém o app público sem virar proxy da cota
do Gemini.
"""

import json
import os
from datetime import date

import streamlit as st

ANALYSIS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "analysis.json")

STATUS_LABEL = {"ok": "OK", "atencao": "Atenção", "alarme": "Alarme",
                "sem_base": "Sem base", "dado_suspeito": "Dado suspeito", "ramp": "Ramp"}


@st.cache_data(show_spinner=False)
def load_analysis(mtime):
    """mtime entra só como chave de cache: muda o arquivo, invalida."""
    if not os.path.exists(ANALYSIS_PATH):
        return None
    with open(ANALYSIS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _analysis():
    if not os.path.exists(ANALYSIS_PATH):
        return None
    return load_analysis(os.path.getmtime(ANALYSIS_PATH))


def render():
    a = _analysis()
    if not a:
        st.info(
            "A análise ainda não foi gerada. Ela é produzida no refresh semanal "
            "(terça de manhã) e depende do secret `LLM_API_KEY` estar configurado "
            "no repositório. Sem ele o refresh roda normalmente e só pula esta parte."
        )
        return

    blocos = a.get("blocos", {})

    c1, c2 = st.columns([4, 1])
    with c1:
        st.markdown(f'<h2 style="font-size:18px;margin-bottom:2px;">Análise da semana '
                    f'<span style="font-size:12px;font-weight:400;color:var(--mut);">'
                    f'corte {a.get("cover", "—")}</span></h2>', unsafe_allow_html=True)
    with c2:
        st.caption(f"modelo: {a.get('modelo', '—')}")

    if a.get("diagnostico_anterior_de"):
        st.caption(f"Compara com o diagnóstico de {a['diagnostico_anterior_de']} — "
                   f"os pareceres dizem se a ação da semana passada foi executada e se respondeu.")
    else:
        st.caption("Primeira semana com diagnóstico persistido — ainda sem bloco de continuidade.")

    st.warning(
        "Relatório gerado por IA a partir dos dados deste dashboard. Todo número citado é "
        "validado contra a lista de evidências do diagnóstico, mas confira no dashboard "
        "antes de mexer em campanha.",
        icon="⚠️",
    )

    if blocos.get("leitura_portfolio"):
        st.markdown("#### Leitura do portfólio")
        st.markdown(blocos["leitura_portfolio"], unsafe_allow_html=True)

    if a.get("triagem_html"):
        with st.expander("Triagem — status por conta (calculada em código, não pela IA)", expanded=True):
            st.markdown(a["triagem_html"], unsafe_allow_html=True)
            # \$ escapado: o Streamlit lê $...$ como LaTeX e a legenda virava fórmula
            st.caption(r"Limiares: CAC até R\$150 ideal · R\$150–200 alerta · acima de R\$200 "
                       r"alarme. CPL até R\$100 na meta. Base mínima de 3 vendas para julgar "
                       r"por CAC, 10 leads para julgar por CPL.")

    if blocos.get("recomendacoes"):
        st.markdown("#### Ações da semana")
        st.markdown(blocos["recomendacoes"], unsafe_allow_html=True)

    if blocos.get("pareceres"):
        st.markdown("#### Parecer por conta")
        st.markdown(blocos["pareceres"], unsafe_allow_html=True)

    if blocos.get("resumo_slack"):
        with st.expander("Resumo enviado no Slack"):
            st.code(blocos["resumo_slack"], language=None)

    if a.get("avisos"):
        with st.expander(f"Avisos da validação automática ({len(a['avisos'])})"):
            for w in a["avisos"]:
                st.caption(f"• {w}")
            st.caption("Avisos não bloqueiam a publicação — erros graves (partner faltando, "
                       "status reclassificado, ação sem confiança) derrubam a análise no refresh.")
