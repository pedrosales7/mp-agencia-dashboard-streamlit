"""Aba "Perguntar aos dados" — chat sobre o snapshot da semana.

Diferente das outras duas abas, esta chama o Gemini em runtime. Duas
consequências que moldaram o desenho:

1. Cada mensagem gasta cota da conta do Pedro. O controle de acesso real é a
   lista de e-mails autorizados do Streamlit Community Cloud (configurada fora
   do código); o teto por sessão aqui é segunda linha de defesa, não a primeira.
2. O modelo responde SÓ com o que está no contexto do refresh — o mesmo payload
   que alimenta a análise semanal. Não há query ao vivo, então ele não pode
   inventar recorte que o snapshot não tem, e é instruído a dizer isso em vez
   de estimar.
"""

import json
import os

import requests
import streamlit as st

BASE = os.path.dirname(os.path.abspath(__file__))
CONTEXT_PATH = os.path.join(BASE, "data", "ai_context.json")
ANALYSIS_PATH = os.path.join(BASE, "data", "analysis.json")

MAX_MSGS = 15          # por sessão — trava de custo, não de segurança
MAX_OUTPUT_TOKENS = 1400
DEFAULT_MODEL = "gemini-3.1-pro-preview"

SYSTEM = """Você é especialista sênior de mídia paga do MP Agência (Melhor Plano) e está \
respondendo perguntas do time sobre o snapshot semanal do dashboard.

<negocio>
8 provedores regionais de internet ("partners"), cada um com um pacote mensal de mídia
100% investido em campanhas. Dois canais por partner:
- google — pesquisa. Funil: impressoes > cliques > sessoes > clickoff > redirect > leads > vendas
- meta — click-to-WhatsApp com bot. Funil: impressoes > cliques > chat_start > zip_search > redirect > leads > vendas

Cashback: quando o lead gerado pela campanha de um partner fecha com OUTRO provedor (CEP
fora da cobertura do anunciante), o anunciante recebe cashback de reinvestimento.
investimento_liquido = bruto − cashback; CPL e CAC já vêm sobre o líquido.
Cashback alto NÃO é problema por si só — ele mede COBERTURA, não desperdício: diz que há
demanda em CEPs onde o parceiro não atende. Com CPL na meta e volume razoável de leads, a
campanha está saudável e a recomendação é revisar a área de cobertura, não apertar o raio.
Vira problema só quando vem junto de CPL ruim ou volume baixo.

Cada partner é uma conta isolada. Verba só se move entre os canais DELE — nunca entre partners.

Metas (absolutas, iguais para todos): CAC até R$150 ideal, R$150–200 alerta, acima de R$200
alarme. CPL até R$100 na meta.
</negocio>

<regras>
- Responda SÓ com o que está nos dados abaixo. Se a pergunta pede um recorte que o snapshot
  não tem (um dia específico, uma campanha, um criativo, um CEP), diga que o dado não está
  neste snapshot e ofereça o recorte mais próximo que existe. Nunca estime.
- Não recalcule: taxas, CTR, CPC, tendências, formatos de curva e as variações semana vs
  semana já vêm prontos em `comparativo_semana_vs_semana` — inclusive a contribuição de
  cada provedor para o CAC do portfólio e o driver que explica cada movimento.
- Quando `cac_base_suficiente` for false, NÃO diga que o CAC daquela conta subiu ou caiu na
  semana: o volume não sustenta. Use a janela de 30d e explique por quê.
- Avalie CAC e CPL sempre em 30d, nunca em 7d — venda tem lag de fechamento e o CAC de 7d
  vem sistematicamente inflado. Use 7d só para topo e meio de funil.
- Não atribua variação a sazonalidade, feriado ou ciclo de faturamento: não está mapeado
  neste negócio e a atribuição fecha a investigação antes da hora.
- O status da triagem foi calculado em código. Não reclassifique.
- Seja direto e curto. Responda a pergunta feita, sem preâmbulo e sem repetir a pergunta.
  Valores em R$ sem centavos. Português do Brasil.
- Se a resposta depende de algo fora do escopo de mídia (operação comercial do provedor,
  crédito/saldo do pacote), diga isso em vez de especular.
</regras>

DADOS — snapshot de {cover}:
{context}

DIAGNÓSTICO DA SEMANA (produzido pela análise automática, pode ser citado):
{diagnostico}
"""

SUGESTOES = [
    "Qual conta está pior essa semana e por quê?",
    "Por que o CAC da Ultranet está tão alto?",
    "Onde o cashback está mais alto e o que isso indica?",
    "Que conta está saudável e subaproveitada?",
]


def _secret(nome, default=None):
    """st.secrets.get() LEVANTA StreamlitSecretNotFoundError quando não existe
    nenhum secrets.toml — o .get() não protege contra arquivo ausente, só
    contra chave ausente. Sem este try o app quebra em vez de mostrar o aviso."""
    try:
        return st.secrets.get(nome, default)
    except Exception:
        return os.environ.get(nome, default)


def _api_key():
    return _secret("LLM_API_KEY") or os.environ.get("LLM_API_KEY")


@st.cache_data(show_spinner=False)
def _load(path, mtime):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read(path):
    if not os.path.exists(path):
        return None
    return _load(path, os.path.getmtime(path))


@st.cache_data(show_spinner=False)
def _system_prompt(cover, ctx_json, diag_json):
    return SYSTEM.replace("{cover}", cover).replace("{context}", ctx_json).replace("{diagnostico}", diag_json)


def _ask(system, historico, pergunta, key, model):
    """Uma chamada por pergunta, com o histórico como turnos anteriores.

    O contexto vai em systemInstruction: assim o Gemini pode fazer cache do
    prefixo entre turnos, em vez de reprocessar 17k tokens toda mensagem.
    """
    contents = []
    for m in historico:
        contents.append({"role": "user" if m["role"] == "user" else "model",
                         "parts": [{"text": m["content"]}]})
    contents.append({"role": "user", "parts": [{"text": pergunta}]})

    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key},
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": MAX_OUTPUT_TOKENS,
                                 "thinkingConfig": {"thinkingBudget": 2048}},
        },
        timeout=120,
    )
    r.raise_for_status()
    cand = r.json()["candidates"][0]
    return "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))


def render():
    ctx = _read(CONTEXT_PATH)
    if not ctx:
        st.info("O contexto de dados ainda não foi gerado. Ele é gravado no refresh semanal "
                "(`data/ai_context.json`) — rode o refresh uma vez e esta aba passa a funcionar.")
        return

    key = _api_key()
    if not key:
        st.warning("`LLM_API_KEY` não está configurado nos secrets do app. "
                   "Em share.streamlit.io → app → Settings → Secrets, adicione "
                   "`LLM_API_KEY = \"...\"` para habilitar o chat.", icon="🔑")
        return

    analysis = _read(ANALYSIS_PATH) or {}
    cover = analysis.get("cover") or ctx.get("data_corte", "—")
    diag = analysis.get("diagnostico")

    st.markdown('<h2 style="font-size:18px;margin-bottom:2px;">Perguntar aos dados</h2>',
                unsafe_allow_html=True)
    st.caption(f"Responde sobre o snapshot de {cover} — as mesmas janelas e séries do dashboard. "
               "Não consulta o banco ao vivo, então não responde recorte por dia, campanha ou CEP.")

    if "chat" not in st.session_state:
        st.session_state.chat = []

    restantes = MAX_MSGS - len(st.session_state.chat)

    if not st.session_state.chat:
        cols = st.columns(len(SUGESTOES))
        for c, s in zip(cols, SUGESTOES):
            if c.button(s, use_container_width=True, key=f"sug_{s[:18]}"):
                st.session_state.pending = s
                st.rerun()

    for m in st.session_state.chat:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    pergunta = st.session_state.pop("pending", None)
    entrada = st.chat_input(
        f"Pergunte sobre os dados ({restantes} de {MAX_MSGS} restantes nesta sessão)"
        if restantes > 0 else "Limite da sessão atingido — recarregue a página para reiniciar",
        disabled=restantes <= 0,
    )
    pergunta = pergunta or entrada
    if not pergunta:
        return

    if restantes <= 0:
        return

    system = _system_prompt(
        str(cover),
        json.dumps(ctx, ensure_ascii=False, separators=(",", ":")),
        json.dumps(diag, ensure_ascii=False, separators=(",", ":")) if diag
        else "(a análise da semana ainda não foi gerada)",
    )

    st.session_state.chat.append({"role": "user", "content": pergunta})
    with st.chat_message("user"):
        st.markdown(pergunta)

    with st.chat_message("assistant"):
        with st.spinner("Consultando os dados da semana…"):
            try:
                resposta = _ask(system, st.session_state.chat[:-1], pergunta, key,
                                _secret("LLM_MODEL", DEFAULT_MODEL))
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else "?"
                resposta = (f"Não consegui responder agora (o Gemini devolveu {code}). "
                            "Se for 429, a cota da conta esgotou — tente mais tarde.")
            except Exception as e:
                resposta = f"Não consegui responder agora ({type(e).__name__})."
        st.markdown(resposta)
    st.session_state.chat.append({"role": "assistant", "content": resposta})
    st.rerun()
