"""MP Agência — hub do Funil Ads-to-Sale (Streamlit).

Três abas sobre o MESMO snapshot semanal (data/latest.json). Nenhuma query ao
vivo no Metabase acontece aqui — o refresh (Metabase -> JSON) roda separado, no
GitHub Actions de terça.

  Dashboard         · os números. Puro pandas em cima do snapshot.
  Análise da semana · texto gerado pelo pipeline de IA DENTRO do refresh e lido
                      aqui como arquivo. Zero chamada de LLM em runtime.
  Perguntar         · única aba que chama o Gemini ao vivo. Por isso o controle
                      de acesso do app (lista de e-mails no Community Cloud) é
                      o que de fato protege a cota — ver chat_view.py.
"""

import streamlit as st

from style import CSS

st.set_page_config(page_title="MP Agência — Funil Ads-to-Sale", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

import analysis_view  # noqa: E402  — depois do set_page_config, exigência do Streamlit
import chat_view  # noqa: E402
import dashboard_view  # noqa: E402

tab_dash, tab_analise, tab_chat = st.tabs(
    ["📊 Dashboard", "🤖 Análise da semana", "💬 Perguntar aos dados"])

with tab_dash:
    dashboard_view.render()

with tab_analise:
    analysis_view.render()

with tab_chat:
    chat_view.render()
