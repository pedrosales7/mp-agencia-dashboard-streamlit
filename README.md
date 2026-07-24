# MP Agência — Funil Ads-to-Sale (Streamlit)

Segundo projeto, separado do dashboard HTML atual (`Dashboard-CodeVersion` /
repo `mp-agencia-dashboard`). Réplica das mesmas 10 seções, mesma lógica de
negócio, com Streamlit + Plotly no lugar de HTML/JS estático.

## Rodar localmente

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Estrutura

- `app.py` — layout e filtros (widgets nativos do Streamlit)
- `data.py` — carrega `data/latest.json` e deriva todas as tabelas/métricas
- `tables.py` — monta as tabelas HTML densas (status dot, sparkline)
- `style.py` — CSS do tema "Sinalização"
- `data/latest.json` — snapshot semanal. **Hoje é ilustrativo** (dados fictícios,
  mesmos números do protótipo aprovado). Quando o pipeline real existir, este
  arquivo passa a ser gerado pelo `weekly_refresh.py` adaptado — sem nenhuma
  mudança em `app.py`/`tables.py`.

## Ainda não implementado

- Geração real de `data/latest.json` a partir do Metabase (hoje é estático)
- Histórico semanal/mensal real para Progressão/Taxas (hoje é derivado por
  escala determinística a partir do número atual — ver `data.py`)
- Página "Análise IA"
- Deploy no Streamlit Community Cloud + Slack
