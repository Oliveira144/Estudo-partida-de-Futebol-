import streamlit as st
import requests
from bs4 import BeautifulSoup
import json
import re
from openai import OpenAI
from dotenv import load_dotenv
import os

# ================================
# 0) Carregar API KEY da IA
# ================================
load_dotenv()
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_KEY)

# ================================
# 1) Buscar partida no SofaScore
# ================================
def buscar_partida_sofascore(time1, time2, campeonato=""):
    query = f"{time1} {time2} {campeonato}".replace(" ", "%20")
    url_busca = f"https://www.sofascore.com/search/{query}"

    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url_busca, headers=headers)

    if r.status_code != 200:
        return None

    soup = BeautifulSoup(r.text, "lxml")
    a = soup.find("a", href=True)

    if not a:
        return None

    link = a["href"]
    if not link.startswith("http"):
        link = "https://www.sofascore.com" + link

    return link


# ================================
# 2) Extrair dados da partida
# ================================
def coletar_dados_sofascore(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers)

    if r.status_code != 200:
        return None

    # A página do SofaScore contém JSON em texto
    m = re.search(r'"event":({.*}),"categories"', r.text)
    if not m:
        return None

    try:
        json_data = json.loads(m.group(1))
    except:
        return None

    estatisticas = {}

    try:
        esc_a = json_data["homeScore"]["corner"]
        esc_b = json_data["awayScore"]["corner"]
        estatisticas["escanteios_home"] = esc_a
        estatisticas["escanteios_away"] = esc_b
        estatisticas["escanteios_ft"] = esc_a + esc_b
    except:
        estatisticas["escanteios_ft"] = "N/D"

    try:
        estatisticas["ht_home"] = json_data["homeScore"]["period1"]
        estatisticas["ht_away"] = json_data["awayScore"]["period1"]
    except:
        estatisticas["ht_home"] = estatisticas["ht_away"] = "N/D"

    try:
        estatisticas["ft_home"] = json_data["homeScore"]["current"]
        estatisticas["ft_away"] = json_data["awayScore"]["current"]
    except:
        estatisticas["ft_home"] = estatisticas["ft_away"] = "N/D"

    return estatisticas


# ================================
# 3) IA ANALISANDO O JOGO
# ================================
def ia_analisar_dados(dados, time1, time2):
    prompt = f"""
Você é um analista profissional de futebol.
Analise os dados da partida abaixo e gere:

1. Probabilidade Over/Under HT
2. Probabilidade Over/Under FT
3. Probabilidade de escanteios HT e FT
4. Leitura tática e estatística
5. Tendências importantes
6. Riscos e oportunidades
7. Cenário provável para próximos minutos

Times:
{time1} vs {time2}

Dados coletados:
{dados}

Forneça uma análise PROFISSIONAL, clara e objetiva.
"""

    resposta = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return resposta.choices[0].message["content"]


# ================================
# 4) INTERFACE STREAMLIT
# ================================
st.title("⚽ Agente IA – Análise Automática de Jogos (SofaScore)")

time1 = st.text_input("Time da Casa:")
time2 = st.text_input("Time Visitante:")
campeonato = st.text_input("Campeonato (opcional):")

if st.button("Buscar e Analisar"):
    st.info("🔍 Buscando partida no SofaScore...")

    url_partida = buscar_partida_sofascore(time1, time2, campeonato)

    if not url_partida:
        st.error("❌ Partida não encontrada. Tente variar o nome do campeonato.")
        st.stop()

    st.success("✅ Partida encontrada!")
    st.write(url_partida)

    dados = coletar_dados_sofascore(url_partida)

    if not dados:
        st.error("❌ Não foi possível extrair dados da partida.")
        st.stop()

    st.subheader("📊 Dados Coletados")
    st.json(dados)

    st.subheader("🤖 Análise Inteligente da IA")
    analise = ia_analisar_dados(dados, time1, time2)

    st.write(analise)
