import streamlit as st
import requests
import pandas as pd

st.title("Análise automática de partidas - SofaScore")

# -----------------------------
# Função para buscar partidas
# -----------------------------
def buscar_partidas(campeonato, time):
    url = f"https://api.sofascore.com/api/v1/search?q={time}"
    r = requests.get(url).json()

    resultados = []
    for item in r.get("results", []):
        if item["entity"]["type"] == "event":
            event = item["entity"]["event"]
            # Filtrar pelo campeonato
            if campeonato.lower() in event["tournament"]["name"].lower():
                resultados.append({
                    "match_id": event["id"],
                    "home": event["homeTeam"]["shortName"],
                    "away": event["awayTeam"]["shortName"],
                    "start": event["startTimestamp"]
                })
    return resultados

# -----------------------------
# Função de análise completa
# -----------------------------
def analisar_partida(match_id):

    # Estatísticas
    stats_url = f"https://api.sofascore.com/api/v1/event/{match_id}/statistics"
    stats = requests.get(stats_url).json()

    # Análise — odds, escanteios, linhas
    analysis_url = f"https://api.sofascore.com/api/v1/event/{match_id}/analysis"
    analysis = requests.get(analysis_url).json()

    return stats, analysis


# ---------------------------------------------
# Interface Streamlit
# ---------------------------------------------
campeonato = st.text_input("Nome do campeonato (ex: Premier League)")
time = st.text_input("Nome do time (ex: Liverpool)")

if st.button("Buscar partidas"):
    partidas = buscar_partidas(campeonato, time)

    if not partidas:
        st.warning("Nenhuma partida encontrada.")
    else:
        st.success(f"{len(partidas)} partidas encontradas:")
        st.write(pd.DataFrame(partidas))

        partida_escolhida = st.selectbox(
            "Escolha o Match ID",
            [p["match_id"] for p in partidas]
        )

        if st.button("Analisar partida"):
            stats, analysis = analisar_partida(partida_escolhida)

            st.subheader("📊 Estatísticas")
            st.json(stats)

            st.subheader("📈 Análises (inclui escanteios, odds, linhas)")
            st.json(analysis)
