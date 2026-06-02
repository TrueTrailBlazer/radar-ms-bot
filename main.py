import os
import json
import requests
import time
import re
import feedparser
import hashlib
import io
import urllib3
import PyPDF2
from datetime import datetime
from bs4 import BeautifulSoup

# ================= CONFIGURAÇÕES =================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8958423212:AAGgUvV69TO1jtxlfjrSQ02nq7ZlMMiK_SE")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "1243055118")

DATABASE_FILE = "database.json"

PADRAO_TI = re.compile(r'\b(ti|t\.i\.|tecnologia da informa[çc][ãa]o|suporte|analista de sistemas|tecn[óo]logo em sistemas|desenvolvedor|programador|python|java|php|web|ads|computa[çc][ãa]o|inform[áa]tica|redes|segurança|cibersegurança|cybersecurity)\b', re.IGNORECASE)
PADRAO_LOCAL = re.compile(r'\b(ms|mato grosso do sul|campo grande|sidrol[âa]ndia|ufms|uems|ifms|sad|agesul)\b', re.IGNORECASE)
PADRAO_VAGA = re.compile(r'\b(processo seletivo|concurso|edital|contrata[çc][ãa]o|sele[çc][ãa]o|vaga|especialização|lato sensu)\b', re.IGNORECASE)

URLS_PCI = [
    "https://www.pciconcursos.com.br/concursos/ms/campo-grande",
    "https://www.pciconcursos.com.br/concursos/ms/sidrolandia"
]
URL_SAD_MS = "https://concursos.ms.gov.br/"
LINK_RSS_GOOGLE = "https://www.google.com/alerts/feeds/13337804871994635216/9517030646560371598"

ALVOS_UFMS = [
    {"nome": "PROPP Editais", "url": "https://propp.ufms.br/", "tipo_extracao": "geral"},
    {"nome": "Inscrições Abertas Pós", "url": "https://posgraduacao.ufms.br/portal/cursos/listagem-inscricoes-abertas", "tipo_extracao": "lista_cursos"}
]

urllib3.disable_warnings()
# =================================================

def destacar_termo(mensagem_base, texto_verificado):
    match = PADRAO_TI.search(texto_verificado)
    if match:
        termo = match.group(0).upper()
        return f"🎯 *ALVO ENCONTRADO:* **{termo}**\n\n{mensagem_base}"
    return mensagem_base

def disparar_telegram(mensagem):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram não configurado.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except:
        return False

def carregar_database():
    if os.path.exists(DATABASE_FILE):
        with open(DATABASE_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except:
                return []
    return []

def salvar_database(db):
    with open(DATABASE_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=4)

def ja_existe(db, link_ou_hash):
    for item in db:
        if item.get('id') == link_ou_hash:
            return True
    return False

def adicionar_vaga(db, id_vaga, titulo, fonte, detalhes, link, is_silent=False):
    # Se for is_silent = True, significa que não achou vaga, mas queremos
    # registrar o hash no DB para não procurar novamente e poluir a rede.
    hoje = datetime.now().strftime("%d/%m/%Y %H:%M")
    nova_vaga = {
        "id": id_vaga,
        "titulo": titulo,
        "fonte": fonte,
        "detalhes": detalhes,
        "data": hoje,
        "link": link,
        "silent": is_silent
    }
    db.insert(0, nova_vaga) # Mais recentes primeiro
    return db[:200] # Limite para não explodir arquivo

# --- SCRAPERS ---
def monitorar_pci(db):
    headers = {"User-Agent": "Mozilla/5.0"}
    novos = 0
    for url in URLS_PCI:
        cidade = url.split("/")[-1].replace("-", " ").title()
        try:
            r = requests.get(url, headers=headers)
            if r.status_code != 200: continue
            soup = BeautifulSoup(r.text, "html.parser")
            for bloco in soup.find_all("div", class_=["ca", "cd"]):
                lt = bloco.find("a")
                dt = bloco.find("span")
                if not lt or not dt: continue
                orgao = lt.get_text().strip()
                detalhes = dt.get_text(separator=" - ").strip()
                if not PADRAO_TI.search(detalhes): continue
                link_direto = lt.get("href")
                if link_direto and not link_direto.startswith("http"): link_direto = "https://www.pciconcursos.com.br" + link_direto
                
                if ja_existe(db, link_direto): continue
                
                data_tag = bloco.find("b")
                prazo = data_tag.get_text().strip() if data_tag else "Ver no edital"
                msg = f"🚨 *NOVA VAGA EM {cidade.upper()}!*\n\n🏢 *Órgão:* {orgao}\n📝 *Detalhes:* {detalhes}\n📅 *Inscrições:* {prazo}\n\n🔗 *Link:* {link_direto}"
                msg = destacar_termo(msg, detalhes)
                if disparar_telegram(msg):
                    db = adicionar_vaga(db, link_direto, f"{cidade} - {orgao}", "PCI Concursos", detalhes, link_direto)
                    novos += 1
                    time.sleep(2)
        except Exception as e:
            print(f"Erro PCI {cidade}: {e}")
    return db, novos

def monitorar_rss_google(db):
    if "SEU_LINK" in LINK_RSS_GOOGLE: return db, 0
    novos = 0
    try:
        feed = feedparser.parse(LINK_RSS_GOOGLE)
        for entry in feed.entries:
            titulo = BeautifulSoup(entry.title, "html.parser").get_text()
            link = entry.link
            if ja_existe(db, link): continue
            resumo = BeautifulSoup(entry.summary, "html.parser").get_text()
            if not PADRAO_LOCAL.search(titulo): continue
            texto = titulo + " " + resumo
            if not PADRAO_TI.search(texto): continue
            
            resumo_curto = resumo[:147] + "..." if len(resumo)>150 else resumo
            msg = f"🌐 *RADAR GOOGLE ALERTS*\n\n📌 *Título:* {titulo}\n🔎 *Resumo:* {resumo_curto}\n\n🔗 *Acessar:* {link}"
            msg = destacar_termo(msg, texto)
            if disparar_telegram(msg):
                db = adicionar_vaga(db, link, titulo[:100], "Google Alerts", resumo_curto, link)
                novos += 1
                time.sleep(2)
    except Exception as e:
        print(f"Erro RSS: {e}")
    return db, novos

def monitorar_sad(db):
    headers = {"User-Agent": "Mozilla/5.0"}
    novos = 0
    try:
        r = requests.get(URL_SAD_MS, headers=headers, timeout=15, verify=False)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for el in soup.find_all(['tr', 'li', 'div']):
                lt = el.find('a')
                if not lt: continue
                texto = el.get_text(separator=" ").strip()
                if not PADRAO_TI.search(texto): continue
                link = lt.get('href')
                if not link: continue
                if link.startswith('/'): link = "https://concursos.ms.gov.br" + link
                if ja_existe(db, link): continue
                
                detalhes = texto[:200] + "..." if len(texto) > 200 else texto
                msg = f"🚨 *NOVA VAGA NA SAD/MS (GOV MS)!*\n\n📝 *Detalhes:* {detalhes}\n\n🔗 *Link:* {link}"
                msg = destacar_termo(msg, texto)
                if disparar_telegram(msg):
                    db = adicionar_vaga(db, link, "Processo Seletivo (SAD/MS)", "Governo MS", detalhes, link)
                    novos += 1
                    time.sleep(2)
    except Exception as e:
        print(f"Erro SAD: {e}")
    return db, novos

def monitorar_universidades(db):
    urls = [("UFMS", "https://concursos.ufms.br/"), ("IFMS", "https://selecao.ifms.edu.br/")]
    headers = {"User-Agent": "Mozilla/5.0"}
    novos = 0
    for nome, url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=15, verify=False)
            if r.status_code != 200: continue
            soup = BeautifulSoup(r.text, "html.parser")
            for el in soup.find_all(['tr', 'li', 'div', 'a']):
                lt = el if el.name == 'a' else el.find('a')
                if not lt: continue
                texto = el.get_text(separator=" ").strip()
                if not PADRAO_TI.search(texto) or not PADRAO_VAGA.search(texto): continue
                link = lt.get('href')
                if not link: continue
                if link.startswith('/'): link = url.rstrip('/') + link
                if ja_existe(db, link): continue
                
                detalhes = texto[:200] + "..."
                msg = f"🚨 *PROCESSO SELETIVO NA {nome}!*\n\n📝 *Detalhes:* {detalhes}\n\n🔗 *Link:* {link}"
                msg = destacar_termo(msg, texto)
                if disparar_telegram(msg):
                    db = adicionar_vaga(db, link, f"Processo Seletivo {nome}", nome, detalhes, link)
                    novos += 1
                    time.sleep(2)
        except Exception as e:
            print(f"Erro Uni {nome}: {e}")
    return db, novos

def monitorar_diogrande(db):
    import base64
    headers = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}
    novos = 0
    try:
        url_api = "https://diogrande.campogrande.ms.gov.br/wp-admin/admin-ajax.php?action=edicao2_dia_json"
        r = requests.get(url_api, headers=headers, timeout=15, verify=False)
        if r.status_code != 200: return db, 0
        dados = r.json()
        if 'atual' not in dados or 'arquivos' not in dados['atual']: return db, 0
        
        links = []
        for a in dados['atual']['arquivos']:
            cod = a.get('codigodia')
            if cod:
                b64 = base64.b64encode(f'{{"codigodia":"{cod}"}}'.encode()).decode()
                links.append(f"https://diogrande.campogrande.ms.gov.br/download_edicao/{b64}.pdf")
        
        if not links: return db, 0
        link = links[0]
        if ja_existe(db, link): return db, 0
        
        pdf_r = requests.get(link, headers=headers, timeout=30, verify=False)
        if pdf_r.status_code == 200:
            reader = PyPDF2.PdfReader(io.BytesIO(pdf_r.content))
            encontrou = False
            trecho = ""
            for page in reader.pages:
                txt = page.extract_text()
                if txt and PADRAO_TI.search(txt) and PADRAO_VAGA.search(txt):
                    encontrou = True
                    idx = PADRAO_TI.search(txt).start()
                    trecho = txt[max(0, idx-150):min(len(txt), idx+150)].replace('\n', ' ')
                    break
            
            if encontrou:
                msg = f"🚨 *ALERTA NO DIOGRANDE (DIÁRIO OFICIAL)!*\n\n📝 *Trecho:* ...{trecho}...\n\n🔗 *Baixar:* {link}"
                msg = destacar_termo(msg, trecho)
                if disparar_telegram(msg):
                    db = adicionar_vaga(db, link, "Diário Oficial Campo Grande", "Diogrande", trecho, link)
                    novos += 1
            else:
                db = adicionar_vaga(db, link, "Edição sem TI", "Diogrande", "Sem vagas detectadas.", link, is_silent=True)
    except Exception as e:
        print(f"Erro Diogrande: {e}")
    return db, novos

def extrair_texto_ufms(html, tipo):
    soup = BeautifulSoup(html, 'html.parser')
    if tipo == "lista_cursos":
        lista = soup.find('ul', id='ListagemProcessos')
        texto = lista.get_text(separator=' ') if lista else soup.get_text(separator=' ')
    else:
        for tag in soup(["script", "style", "nav", "footer", "header"]): tag.extract()
        texto = soup.get_text(separator=' ')
    return ' '.join(texto.split()).lower()

def monitorar_ufms_lato_sensu(db):
    headers = {"User-Agent": "Mozilla/5.0"}
    novos = 0
    for alvo in ALVOS_UFMS:
        nome = alvo["nome"]
        url = alvo["url"]
        tipo = alvo["tipo_extracao"]
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200: continue
            
            texto = extrair_texto_ufms(r.text, tipo)
            hash_atual = hashlib.md5(texto.encode('utf-8')).hexdigest()
            id_hash = f"{url}_{hash_atual}"
            
            if ja_existe(db, id_hash): continue
            
            encontradas = [p for p in ["especialização", "lato sensu", "segurança", "cibersegurança", "cybersecurity", "tecnologia"] if p in texto]
            if encontradas:
                msg = f"🚨 *Nova Atualização na UFMS Pós-Graduação!*\n\n🏢 *Alvo:* {nome}\n📝 *Palavras encontradas:* {', '.join(encontradas)}\n\n🔗 *Acesse:* {url}"
                if disparar_telegram(msg):
                    db = adicionar_vaga(db, id_hash, f"Pós-Graduação: {nome}", "UFMS Pós", f"Atualização de edital contendo: {', '.join(encontradas)}", url)
                    novos += 1
            else:
                db = adicionar_vaga(db, id_hash, f"Atualização Pós: {nome}", "UFMS Pós", "Página alterada (Sem palavras TI detectadas)", url, is_silent=True)
        except Exception as e:
            print(f"Erro UFMS Pós {nome}: {e}")
    return db, novos


def main():
    print("Iniciando varredura unificada Radar MS...")
    db = carregar_database()
    total_novos = 0
    
    db, n = monitorar_pci(db); total_novos += n
    db, n = monitorar_rss_google(db); total_novos += n
    db, n = monitorar_sad(db); total_novos += n
    db, n = monitorar_universidades(db); total_novos += n
    db, n = monitorar_diogrande(db); total_novos += n
    db, n = monitorar_ufms_lato_sensu(db); total_novos += n
    
    salvar_database(db)
    print(f"Varredura concluída. {total_novos} novos alertas disparados e salvos no banco de dados.")

if __name__ == "__main__":
    main()
