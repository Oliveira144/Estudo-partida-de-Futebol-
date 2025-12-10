"""
app_streamlit_sofascore.py
Streamlit app que:
- Recebe Time e Campeonato
- Abre SofaScore com Playwright
- Busca a partida
- Extrai Over/Under HT e FT e Escanteios HT e FT
- Mostra resultados e envia para análise de IA (ex.: OpenAI)

Instalação de dependências:
pip install streamlit playwright openai python-dotenv
# Inicializar playwright (uma única vez)
playwright install
"""

import streamlit as st
import time
import re
import os
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from dotenv import load_dotenv

# Carrega variáveis de ambiente (opcional)
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # opcional: para análise IA

st.set_page_config(page_title="Agente IA - SofaScore (Over / Escanteios)", layout="wide")

st.title("Agente IA — SofaScore: Over/Under & Escanteios (HT / FT)")
st.write("Digite os times e o campeonato. O agente tentará localizar a partida no SofaScore, coletar os mercados secundários e gerar uma análise.")

with st.form("busca_form"):
    time_casa = st.text_input("Time (Casa) — ex: Flamengo", value="")
    time_visitante = st.text_input("Time (Visitante) — ex: São Paulo", value="")
    campeonato = st.text_input("Campeonato (opcional) — ex: Brasileirão", value="")
    usar_headless = st.checkbox("Rodar headless (sem abrir navegador)", value=True)
    submit = st.form_submit_button("Buscar e Analisar (SofaScore)")

def normalize_name(name: str) -> str:
    # Remove acentos, símbolos e deixa em formato para busca
    name = name.strip()
    name = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE)
    return name

def build_search_query(t1, t2, campeonato=""):
    parts = [t1, "vs", t2]
    if campeonato:
        parts.append(campeonato)
    parts.append("SofaScore")
    return " ".join([p for p in parts if p])

def try_extract_texts(page, xpaths):
    for xp in xpaths:
        try:
            txt = page.locator(f'xpath={xp}').inner_text(timeout=2000)
            if txt and txt.strip():
                return txt.strip()
        except Exception:
            continue
    return None

def parse_numeric_from_string(s: str):
    if not s:
        return None
    # busca números dentro da string (inteiros, floats)
    m = re.findall(r"\d+(?:\.\d+)?", s)
    if not m:
        return None
    # se houver mais de um número, retorna lista; senão, retorna int/float
    nums = [float(x) if "." in x else int(x) for x in m]
    return nums if len(nums) > 1 else nums[0]

def coletar_dados_sofascore(t1, t2, campeonato="", headless=True, max_wait=15):
    """
    1) Abre sofascore.com
    2) Usa busca do site para localizar partida (query: t1 vs t2 campeonato)
    3) Clica no primeiro resultado relevante
    4) Extrai textos para Over/Under HT/FT e Escanteios HT/FT
    """
    resultado = {"found": False, "url": None, "raw": {}, "parsed": {}}
    query = build_search_query(t1, t2, campeonato)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            page.goto("https://www.sofascore.com", timeout=12000)
        except PlaywrightTimeoutError:
            browser.close()
            st.warning("Tempo esgotado ao abrir SofaScore. Tente novamente.")
            return resultado

        # Fecha popups se existirem
        try:
            # exemplo de tentativa de fechar cookie banner
            page.locator("button:has-text('Accept'), button:has-text('ACEITAR'), button[aria-label='close']").first.click(timeout=2000)
        except Exception:
            pass

        # Busca pelo termo na caixa de pesquisa do SofaScore (caso exista)
        try:
            # abrir search input
            # existe um botão de search; tentamos várias estratégias
            try:
                page.click("button[aria-label='Search']", timeout=2000)
            except Exception:
                try:
                    page.click("button[title='Search']", timeout=2000)
                except Exception:
                    # tentar focar no input direto
                    pass

            # digitar na pesquisa global (se houver)
            # tentamos vários seletores onde a caixa de busca pode existir
            typed = False
            for sel in [
                "input[placeholder*='Search']",
                "input[placeholder*='search']",
                "input[type='search']",
                "input[aria-label='Search']"
            ]:
                try:
                    inp = page.locator(sel)
                    inp.click(timeout=1500)
                    inp.fill(query, timeout=1500)
                    typed = True
                    break
                except Exception:
                    continue

            # fallback: usar busca do Google via site search
            if not typed:
                # usar campo de pesquisa do próprio site via URL search
                pass

            # aguardar resultados carregarem
            time.sleep(1.0)
        except Exception:
            pass

        # Caso a busca do site não funcione, usamos a função de pesquisa via URL de site (busca do sofascore)
        # SofaScore suporta uma rota de busca via /search?query=
        try:
            search_url = f"https://www.sofascore.com/search/{query.replace(' ', '%20')}"
            page.goto(search_url, timeout=8000)
            time.sleep(1.0)
        except Exception:
            pass

        # Tentar clicar no primeiro resultado de partida encontrado
        # Resultados de partidas tendem a ter "/{time1}-vs-{time2}/" ou "/event/{id}"
        match_url = None
        try:
            # tentativa 1: localizar links que contenham "match" ou "/team/" ou "/event/"
            anchors = page.locator("a").all()
            for a in anchors[:200]:
                try:
                    href = a.get_attribute("href")
                    txt = a.inner_text()
                    if not href:
                        continue
                    low = href.lower()
                    if "/match/" in low or "/event/" in low or re.search(r"/[a-z0-9-]+-vs-[a-z0-9-]+/", low):
                        if "sofascore.com" not in href:
                            href = "https://www.sofascore.com" + href if href.startswith("/") else href
                        match_url = href
                        break
                except Exception:
                    continue
        except Exception:
            match_url = None

        # Se não encontrou link, tentar encontrar elementos de resultado com texto dos times
        if not match_url:
            try:
                elements = page.locator("a:has-text('{}')".format(t1)).all()
                if elements:
                    for el in elements[:50]:
                        try:
                            href = el.get_attribute("href")
                            if href and "/match/" in href:
                                match_url = href if href.startswith("http") else "https://www.sofascore.com" + href
                                break
                        except Exception:
                            continue
            except Exception:
                pass

        # Se ainda não achou, tentar construir URL básica (forma comum no sofascore):
        if not match_url:
            t1_norm = normalize_name(t1).replace(" ", "-").lower()
            t2_norm = normalize_name(t2).replace(" ", "-").lower()
            candidate = f"https://www.sofascore.com/{t1_norm}-v-{t2_norm}/"
            # abrir e ver se é válido
            try:
                page.goto(candidate, timeout=6000)
                if page.title() and "SofaScore" in page.title():
                    match_url = candidate
            except Exception:
                match_url = None

        if not match_url:
            browser.close()
            return resultado

        # Abrir a página da partida
        try:
            page.goto(match_url, timeout=12000)
            time.sleep(1.5)
        except Exception:
            pass

        resultado["found"] = True
        resultado["url"] = match_url

        # Agora precisamos extrair os valores. Sofascore estrutura é dinâmica; tentamos diversos caminhos.
        raw = {}

        # 1) Procurar por "Corners" (Escanteios)
        corners_text = None
        corners_xpaths = [
            "//div[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'corner')]" ,
            "//div[contains(., 'Corners') or contains(., 'Corner')]" ,
            "//div[contains(@class,'stat') and contains(., 'Corners')]" ,
            "//span[contains(., 'Corners')]" ,
        ]
        corners_text = try_extract_texts(page, corners_xpaths)
        raw["corners_text"] = corners_text

        # 2) Procurar Over/Under HT / FT — frequentemente em markets / bets / statistics
        ou_text = None
        ou_xpaths = [
            "//div[contains(translate(. , 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'over') and contains(translate(. , 'abcdefghijklmnopqrstuvwxyz','abcdefghijklmnopqrstuvwxyz'), 'under')]" ,
            "//div[contains(., 'Over/Under')]" ,
            "//div[contains(text(),'Over') and contains(text(),'Under')]" ,
            "//div[contains(., 'Total Goals')]" ,
        ]
        ou_text = try_extract_texts(page, ou_xpaths)
        raw["ou_text"] = ou_text

        # 3) Procurar áreas de "statistics" (HT/FT podem estar dentro de boxes de estatísticas)
        stats_html = None
        try:
            stats_html = page.locator("div").filter(has_text="Stats").first.inner_text(timeout=2500)
        except Exception:
            stats_html = None
        raw["stats_ht_ft"] = stats_html

        # 4) Outra abordagem: extrair todo o HTML text da página e buscar por padrões
        page_content = ""
        try:
            page_content = page.content()
        except Exception:
            try:
                page_content = page.inner_text("body")
            except Exception:
                page_content = ""

        raw["page_text_snippet"] = page_content[:20000]  # amostra para debug

        # Tentar extrair números de corners HT e FT a partir de texto
        # Procuramos por padrões como "Corners 1 - 2" ou "Corners HT 1 - 0" ou "Corners: HT 1 FT 3"
        corners_parsed = {"ht": None, "ft": None}
        # Tentativas com regex
        try:
            # Pattern típico: "Corners 1 - 2"
            m = re.search(r"Corners[^0-9\n\r]*?(\d{1,2})\s*[-:]\s*(\d{1,2})", page_content, re.IGNORECASE)
            if m:
                a, b = int(m.group(1)), int(m.group(2))
                corners_parsed["ft"] = a + b  # total FT
                # HT tentativa: procurar por "HT" perto
                m2 = re.search(r"HT[^0-9\n\r]*?Corners[^0-9\n\r]*?(\d{1,2})\s*[-:]\s*(\d{1,2})", page_content, re.IGNORECASE)
                if m2:
                    ht_a, ht_b = int(m2.group(1)), int(m2.group(2))
                    corners_parsed["ht"] = ht_a + ht_b
        except Exception:
            pass

        # Tentar captura via seletores mais específicos (se houver seção "Statistics" com rows)
        try:
            # Localiza linhas de estatística
            stat_rows = page.locator("div[class*='statistics'] div").all()[:150]
            for r in stat_rows:
                try:
                    txt = r.inner_text()
                    if "Corner" in txt or "Corners" in txt:
                        # exemplo de txt: "Corners 1 - 2"
                        m = re.search(r"(\d{1,2})\s*[-:]\s*(\d{1,2})", txt)
                        if m:
                            a, b = int(m.group(1)), int(m.group(2))
                            corners_parsed["ft"] = a + b
                            # não há indicação HT aqui normalmente
                except Exception:
                    continue
        except Exception:
            pass

        # Over/Under linhas: procurar por "Over 0.5 HT", "Over 1.5 FT", ou odds
        ou_parsed = {"ht": None, "ft": None, "details": None}
        try:
            # procurar expressões comuns
            m_ht = re.search(r"(Over\s*[\d\.]+)\s*HT", page_content, re.IGNORECASE)
            m_ft = re.search(r"(Over\s*[\d\.]+)\s*(Full Time|FT|Full-time)", page_content, re.IGNORECASE)
            if m_ht:
                ou_parsed["ht"] = m_ht.group(1)
            if m_ft:
                ou_parsed["ft"] = m_ft.group(1)

            # procurar por "Over/Under" bloco com séries de linhas
            m_ou_block = re.search(r"Over/?Under[\s\S]{0,180}", page_content, re.IGNORECASE)
            if m_ou_block:
                ou_parsed["details"] = m_ou_block.group(0)
        except Exception:
            pass

        # Salvar coletado
        resultado["raw"] = raw
        resultado["parsed"]["corners"] = corners_parsed
        resultado["parsed"]["over_under"] = ou_parsed

        browser.close()
        return resultado

# Função simples de análise com OpenAI (apenas exemplo)
def analisar_com_openai(dados):
    # Implementação pontual: apenas monta prompt e devolve texto dummy se não houver chave
    if not OPENAI_API_KEY:
        return "Chave OPENAI_API_KEY não configurada — habilite a variável de ambiente para análise automática com IA."
    try:
        import openai
        openai.api_key = OPENAI_API_KEY
        prompt = (
            "Você é um analista de partidas. Analise os dados abaixo e gere probabilidades e sugestões de mercado (Over/Under HT, Over/Under FT, Escanteios HT e FT).\n\n"
            f"Dados:\n{dados}\n\nForneça:\n- Probabilidades estimadas (em %)\n- Racional curto (2-3 linhas)\n- Risco / motivo de alerta\n"
        )
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",  # ajuste conforme sua conta
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400
        )
        return resp.choices[0].message["content"]
    except Exception as e:
        return f"Erro ao chamar OpenAI: {e}"

# --- Fluxo da aplicação ---
if submit:
    if not time_casa or not time_visitante:
        st.error("Preencha Time (Casa) e Time (Visitante).")
    else:
        placeholder = st.empty()
        with placeholder.container():
            st.info("🔎 Procurando partida no SofaScore e coletando dados...")
        # Executa scraping
        with st.spinner("Abrindo SofaScore e buscando a partida..."):
            dados_coletados = coletar_dados_sofascore(time_casa, time_visitante, campeonato, headless=usar_headless)

        if not dados_coletados["found"]:
            st.error("Não foi possível localizar a partida automaticamente no SofaScore.")
            st.write("URL pesquisada / pistas:", build_search_query(time_casa, time_visitante, campeonato))
        else:
            st.success(f"Partida encontrada: {dados_coletados['url']}")
            st.subheader("Dados brutos coletados (trecho):")
            st.code(dados_coletados["raw"].get("page_text_snippet","")[:2000])

            st.subheader("Dados parseados (tentativa):")
            st.write(dados_coletados["parsed"])

            st.subheader("Extração específica (se disponível):")
            cols = st.columns(2)
            with cols[0]:
                st.markdown("**Escanteios**")
                corners = dados_coletados["parsed"]["corners"]
                st.write(corners)
            with cols[1]:
                st.markdown("**Over / Under (HT/FT)**")
                st.write(dados_coletados["parsed"]["over_under"])

            st.markdown("---")
            st.subheader("Análise IA (opcional)")
            with st.spinner("Enviando dados para análise..."):
                ai_result = analisar_com_openai(dados_coletados)
                st.markdown(ai_result)

            st.markdown("---")
            st.info("Observações técnicas:")
            st.write("""
            - O SofaScore é bastante dinâmico; os seletores podem variar conforme a versão da página.
            - Se os valores não forem extraídos corretamente, cole aqui o link da partida e podemos ajustar os XPaths.
            - Evite rodar buscas muito frequentes (rate-limit / bloqueios).
            """)
