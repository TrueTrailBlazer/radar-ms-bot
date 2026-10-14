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
import base64
import pytz
import unicodedata
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

# ================= CONFIGURAÇÕES =================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8958423212:AAGgUvV69TO1jtxlfjrSQ02nq7ZlMMiK_SE")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "1243055118")

DATABASE_FILE = "database.json"

def carregar_configuracao():
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

CONFIG = carregar_configuracao()
KEYWORDS_CONFIG = CONFIG.get("keywords", ["TI"])
URLS_PCI = CONFIG.get("urls_pci", ["https://www.pciconcursos.com.br/concursos/ms/campo-grande"])
ALVOS_UFMS = CONFIG.get("alvos_ufms", [{"nome": "PROPP Editais", "url": "https://propp.ufms.br/", "tipo_extracao": "geral"}])

if not KEYWORDS_CONFIG: KEYWORDS_CONFIG = ["TI"]

def criar_padrao_insensivel(palavras):
    mapa = {
        'a': '[aáàãâä]', 'e': '[eéèêë]', 'i': '[iíìîï]',
        'o': '[oóòõôö]', 'u': '[uúùûü]', 'c': '[cç]'
    }
    padroes = []
    for p in palavras:
        p_clean = ''.join(c for c in unicodedata.normalize('NFD', p.lower()) if unicodedata.category(c) != 'Mn')
        s = ''.join(mapa.get(ch, re.escape(ch)) for ch in p_clean)
        padroes.append(s)
    return re.compile(r'(?i)\b(' + '|'.join(padroes) + r')\b')

def normalizar_texto_pdf(txt):
    if not txt:
        return ""
    # Remover hífens suaves e caracteres invisíveis de diagramação PDF
    txt = txt.replace('\xad', '').replace('\u200b', '').replace('\u200c', '').replace('\u200d', '').replace('\ufeff', '')
    # Reparar quebras de ligaduras comuns em PDFs de concursos (ex: "Computa  o", "informa  o")
    txt = re.sub(r'(?i)computa[\s\ufffd_]+o(?=[^a-z]|$)', 'computacao', txt)
    txt = re.sub(r'(?i)ci[\s\ufffd_]*ncia(?=[^a-z]|$)', 'ciencia', txt)
    txt = re.sub(r'(?i)informa[\s\ufffd_]+o(?=[^a-z]|$)', 'informacao', txt)
    txt = re.sub(r'(?i)avalia[\s\ufffd_]+o(?=[^a-z]|$)', 'avaliacao', txt)
    txt = re.sub(r'(?i)gradua[\s\ufffd_]+o(?=[^a-z]|$)', 'graduacao', txt)
    txt = re.sub(r'(?i)administra[\s\ufffd_]+o(?=[^a-z]|$)', 'administracao', txt)
    txt = re.sub(r'(?i)comunica[\s\ufffd_]+o(?=[^a-z]|$)', 'comunicacao', txt)
    txt = re.sub(r'(?i)programac[\s\ufffd_]+o(?=[^a-z]|$)', 'programacao', txt)
    txt = re.sub(r'(?i)\bt[\s\ufffd_]*nicas?\b', 'tecnicas', txt)
    txt = re.sub(r'(?i)t[\s\ufffd_]*cnic[ao]s?(?=[^a-z]|$)', 'tecnico', txt)
    txt = re.sub(r'(?i)SoMware\b', 'Software', txt)
    return txt

def edital_muito_antigo(prazo_str):
    if not prazo_str:
        return False
    p_lower = prazo_str.lower()
    if any(k in p_lower for k in ["cancelad", "encerrad", "suspenso", "anulado"]):
        return True
    m = re.search(r'(\d{2})/(\d{2})/(\d{4})', prazo_str)
    if m:
        try:
            data_prazo = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            # Se o prazo expirou há mais de 3 dias, tratar como encerrado
            if (datetime.now() - data_prazo).days > 3:
                return True
        except:
            pass
    return False

PADRAO_TI = criar_padrao_insensivel(KEYWORDS_CONFIG)
PADRAO_TI_UFMS = re.compile(r'(?i)\b(ti|computacao|computa[cç][aã]o|ci[êe]ncia da computa[cç][aã]o|sistemas? de informa[cç][aã]o|engenharia de software|an[áa]lise e desenvolvimento de sistemas|tecnologia da informa[cç][aã]o|programador|desenvolvedor|redes de computadores|banco de dados|facom)\b')
PADRAO_LOCAL = re.compile(r'\b(ms|mato grosso do sul|campo grande|dourados|tr[êe]s lagoas|corumb[áa]|ponta por[ãa]|sidrol[âa]ndia|navira[íi]|nova andradina|aquidauana|parana[íi]ba|coxim|ufms|uems|ifms|sad|agesul)\b', re.IGNORECASE)
PADRAO_VAGA = re.compile(r'\b(processo seletivo|concurso|edital|contrata[çc][ãa]o|sele[çc][ãa]o|vaga|especialização|lato sensu)\b', re.IGNORECASE)

HEADERS_NAVEGADOR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
}

URL_SAD_MS = "https://www.econcursoms.ms.gov.br/"
LINK_RSS_GOOGLE = "https://www.google.com/alerts/feeds/13337804871994635216/9517030646560371598"

urllib3.disable_warnings()
# =================================================

def registrar_saude(scraper_name, sucesso, msg_erro="", info_adicional="", silencioso=False):
    arquivo = "health.json"
    dados = {}
    try:
        if os.path.exists(arquivo):
            with open(arquivo, "r", encoding="utf-8") as f: dados = json.load(f)
    except: pass

    chave = f"{scraper_name}_falhas"
    falhas = dados.get(chave, 0)
    
    agora = datetime.now(timezone(timedelta(hours=-4))).strftime("%d/%m/%Y %H:%M:%S")
    
    if sucesso:
        dados[chave] = 0
        dados[f"{scraper_name}_ultimo_erro"] = ""
        dados[f"{scraper_name}_info"] = info_adicional if info_adicional else "Operando normalmente."
    else:
        if not silencioso:
            falhas += 1
            if falhas >= 24: # 3 dias
                disparar_telegram(f"⚠️ *Alerta de Manutenção Radar MS:*\nO scraper `{scraper_name}` falhou 24 vezes consecutivas (3 dias).\n\nÚltimo erro: `{msg_erro}`\n\nVerifique se o site mudou de estrutura ou está fora do ar/bloqueando o robô!")
                falhas = 0
            dados[chave] = falhas
        dados[f"{scraper_name}_ultimo_erro"] = msg_erro
        if info_adicional:
            dados[f"{scraper_name}_info"] = info_adicional
    
    dados[f"{scraper_name}_data"] = agora

    try:
        with open(arquivo, "w", encoding="utf-8") as f: json.dump(dados, f, ensure_ascii=False)
    except: pass

def destacar_termo(mensagem_base, texto_verificado, padrao=None):
    if padrao is None:
        padrao = PADRAO_TI
    match = padrao.search(texto_verificado)
    if not match and padrao != PADRAO_TI_UFMS:
        match = PADRAO_TI_UFMS.search(texto_verificado)
    if match:
        termo = match.group(0).upper()
        return f"🎯 *ALVO ENCONTRADO:* *{termo}*\n\n{mensagem_base}", termo
    return mensagem_base, None

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
        if r.status_code == 200:
            return True
        # Se o Telegram rejeitar o parse Markdown (ex: caracteres especiais não escapados), tenta em texto simples
        if r.status_code == 400:
            payload_plain = payload.copy()
            payload_plain.pop("parse_mode", None)
            r_plain = requests.post(url, json=payload_plain, timeout=10)
            return r_plain.status_code == 200
        return False
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

def adicionar_vaga(db, id_vaga, titulo, fonte, detalhes, link, is_silent=False, data_publicacao=None, local=None, data_tipo="Capturado", palavra_chave=None):
    if ja_existe(db, id_vaga): return db
    
    data_captura_str = datetime.now(pytz.timezone('America/Campo_Grande')).strftime('%d/%m/%Y %H:%M')
    
    if data_publicacao:
        data_str = data_publicacao
    else:
        data_str = data_captura_str

    nova_vaga = {
        "id": id_vaga,
        "titulo": titulo,
        "fonte": fonte,
        "detalhes": detalhes,
        "link": link,
        "silent": is_silent,
        "data": data_str,
        "data_captura": data_captura_str,
        "data_publicacao": data_publicacao,
        "data_tipo": data_tipo,
        "palavra_chave": palavra_chave
    }
    if local:
        nova_vaga["local"] = local
    db.insert(0, nova_vaga) # Mais recentes primeiro
    return db[:200] # Limite para não explodir arquivo

# --- SCRAPERS ---
def monitorar_pci(db):
    headers = HEADERS_NAVEGADOR
    novos = 0
    for url in URLS_PCI:
        cidade_slug = url.rstrip("/").split("/")[-1].lower()
        cidade = "Mato Grosso do Sul" if cidade_slug == "ms" else cidade_slug.replace("-", " ").title()
        try:
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code != 200:
                registrar_saude(f"PCI_{cidade_slug}", False, f"HTTP {r.status_code}")
                continue
            registrar_saude(f"PCI_{cidade_slug}", True)
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.find_all("div", class_="ea")
            
            # A página /concursos/ms/ é um índice dos 79 municípios no PCI (sem div.ea direto).
            # As oportunidades ativas do estado ficam listadas na aba regional Centro-Oeste:
            if not cards and cidade_slug == "ms":
                try:
                    r_co = requests.get("https://www.pciconcursos.com.br/concursos/centrooeste/", headers=headers, timeout=30)
                    if r_co.status_code == 200:
                        soup_co = BeautifulSoup(r_co.text, "html.parser")
                        cards = [c for c in soup_co.find_all("div", class_="ea") if PADRAO_LOCAL.search(c.get_text())]
                except Exception as e_co:
                    print(f"Erro ao buscar Centro-Oeste para MS: {e_co}")
            
            inspecoes_varios = 0
            max_inspecoes_varios = 5
            
            for bloco in cards:
                ca = bloco.find("div", class_="ca")
                cd = bloco.find("div", class_="cd")
                ce = bloco.find("div", class_="ce")
                
                link_tag = (ca.find("a") if ca else None) or bloco.find("a")
                if not link_tag:
                    continue
                
                link_direto = bloco.get("data-url") or link_tag.get("href")
                if not link_direto:
                    continue
                if not link_direto.startswith("http"):
                    link_direto = "https://www.pciconcursos.com.br" + link_direto
                
                if ja_existe(db, link_direto):
                    continue
                
                orgao = link_tag.get_text().strip()
                detalhes = cd.get_text(separator=" - ").strip() if cd else ""
                prazo = ce.get_text().strip() if ce else ""
                if not prazo:
                    data_tag = bloco.find("b")
                    prazo = data_tag.get_text().strip() if data_tag else "Ver no edital"
                
                # Ignorar editais encerrados/cancelados ou de anos anteriores
                if edital_muito_antigo(prazo):
                    db = adicionar_vaga(db, link_direto, f"{cidade} - {orgao} (Encerrado)", "PCI Concursos", detalhes, link_direto, is_silent=True, data_publicacao=prazo, local=cidade)
                    continue
                
                match_ti = PADRAO_TI.search(detalhes) or PADRAO_TI.search(orgao)
                cargos_ti_encontrados = ""
                
                # Tratar editais que agrupam múltiplos cargos ("Vários Cargos")
                if not match_ti and re.search(r'v[áa]rios\s+cargos', detalhes, re.IGNORECASE):
                    if inspecoes_varios < max_inspecoes_varios:
                        inspecoes_varios += 1
                        try:
                            r_noticia = requests.get(link_direto, headers=headers, timeout=15)
                            if r_noticia.status_code == 200:
                                soup_noticia = BeautifulSoup(r_noticia.text, "html.parser")
                                art = soup_noticia.find("article") or soup_noticia.find(id="conteudo") or soup_noticia.find(id="materia")
                                txt_noticia = art.get_text() if art else soup_noticia.get_text()
                                match_noticia = PADRAO_TI.search(txt_noticia)
                                if match_noticia:
                                    match_ti = match_noticia
                                    idx = match_noticia.start()
                                    trecho = " ".join(txt_noticia[max(0, idx - 80):min(len(txt_noticia), idx + 80)].split())
                                    cargos_ti_encontrados = f" | TI detectado: ...{trecho}..."
                                else:
                                    db = adicionar_vaga(db, link_direto, f"{cidade} - {orgao} (Sem TI)", "PCI Concursos", detalhes, link_direto, is_silent=True, data_publicacao=prazo, local=cidade)
                                    continue
                        except Exception as err_noticia:
                            print(f"Erro ao inspecionar edital de vários cargos {link_direto}: {err_noticia}")
                            continue
                
                if not match_ti:
                    continue
                
                detalhes_finais = detalhes + cargos_ti_encontrados
                msg = f"🚨 *NOVA VAGA EM {cidade.upper()}!*\n\n🏢 *Órgão:* {orgao}\n📝 *Detalhes:* {detalhes_finais}\n📅 *Inscrições:* {prazo}\n\n🔗 *Link:* {link_direto}"
                msg, keyword = destacar_termo(msg, detalhes_finais)
                if disparar_telegram(msg):
                    time.sleep(2)
                db = adicionar_vaga(db, link_direto, f"{cidade} - {orgao}", "PCI Concursos", detalhes_finais, link_direto, False, prazo, cidade, "Inscrições", keyword)
                novos += 1
        except Exception as e:
            print(f"Erro PCI {cidade}: {e}")
            registrar_saude(f"PCI_{cidade_slug}", False, str(e))
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
            msg, keyword = destacar_termo(msg, texto)
            
            data_pub = entry.published if hasattr(entry, 'published') else None
            cidades_ms = ["Campo Grande", "Dourados", "Três Lagoas", "Corumbá", "Ponta Porã", "Aquidauana", "Naviraí", "Nova Andradina", "Coxim", "Paranaíba", "Chapadão do Sul", "MS"]
            cidades = [c for c in cidades_ms if c.lower() in texto.lower() and c != "MS"]
            if not cidades and "ms" in texto.lower().split(): cidades.append("Mato Grosso do Sul")
            local_str = ", ".join(cidades) if cidades else None
            
            if disparar_telegram(msg):
                db = adicionar_vaga(db, link, titulo[:100], "Google Alerts", resumo_curto, link, False, data_pub, local_str, "Publicado", keyword)
                novos += 1
                time.sleep(2)
    except Exception as e:
        print(f"Erro RSS: {e}")
        registrar_saude("RSS_Google", False, str(e))
    return db, novos

def monitorar_sad(db):
    headers = HEADERS_NAVEGADOR
    novos = 0
    try:
        r = requests.get(URL_SAD_MS, headers=headers, timeout=30, verify=False)
        if r.status_code == 200:
            is_blazor = "_framework/blazor" in r.text or "blazor.web.js" in r.text or "blazor.server.js" in r.text
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style"]):
                tag.extract()
            
            for el in soup.find_all(['tr', 'li', 'div', 'a']):
                txt = el.get_text(separator=' ').strip()
                if not txt or len(txt) < 10:
                    continue
                if PADRAO_TI.search(txt) and PADRAO_VAGA.search(txt):
                    link_tag = el if el.name == 'a' else el.find('a')
                    link = link_tag.get('href') if link_tag else None
                    if link and link.startswith('/'):
                        link = "https://www.econcursoms.ms.gov.br" + link
                    
                    if not link or ja_existe(db, link):
                        continue
                    
                    txt_limpo = " ".join(txt.split())
                    txt_resumo = txt_limpo[:247] + "..." if len(txt_limpo) > 250 else txt_limpo
                    
                    msg = f"🚨 *NOVIDADE NA SAD MS!*\n\n📝 *Detalhe:* {txt_resumo}\n\n🔗 *Link:* {link}"
                    msg, keyword = destacar_termo(msg, txt_resumo)
                    if disparar_telegram(msg):
                        time.sleep(2)
                    db = adicionar_vaga(db, link, "Atualização SAD MS", "Governo MS", txt_resumo, link, False, None, "MS", "Capturado", keyword)
                    novos += 1
            
            info = "Portal Blazor SPA respondendo 200 OK (renderizado via client-side)." if is_blazor else "Operando normalmente."
            registrar_saude("SAD_MS", True, info_adicional=info)
        else:
            registrar_saude("SAD_MS", False, f"HTTP {r.status_code}")
    except Exception as e:
        print(f"Erro SAD: {e}")
        registrar_saude("SAD_MS", False, str(e))
    return db, novos

def monitorar_universidades(db):
    headers = HEADERS_NAVEGADOR
    novos = 0

    # 1. UFMS Concursos (concursos.ufms.br)
    try:
        url_ufms = "https://www.concursos.ufms.br/"
        r_ufms = requests.get(url_ufms, headers=headers, timeout=30, verify=False)
        if r_ufms.status_code != 200:
            registrar_saude("Uni_UFMS", False, f"HTTP {r_ufms.status_code}")
        else:
            registrar_saude("Uni_UFMS", True, info_adicional="Operando normalmente (eventos abertos inspecionados).")
            soup = BeautifulSoup(r_ufms.text, "html.parser")
            
            eventos = []
            for sec_id in ["open", "current"]:
                sec = soup.find(id=sec_id)
                if sec:
                    for a in sec.find_all("a", href=True):
                        h = a.get("href")
                        if "/front/setup/" in h:
                            if h.startswith("/"): h = "https://www.concursos.ufms.br" + h
                            titulo_ev = a.get_text().strip() or "Concurso UFMS"
                            if not any(e["url"] == h for e in eventos):
                                eventos.append({"url": h, "titulo": titulo_ev})
            
            for ev in eventos:
                ev_url = ev["url"]
                ev_titulo = ev["titulo"]
                try:
                    r_ev = requests.get(ev_url, headers=headers, timeout=30, verify=False)
                    if r_ev.status_code != 200: continue
                    soup_ev = BeautifulSoup(r_ev.text, "html.parser")
                    
                    news_items = []
                    for a in soup_ev.find_all("a", href=True):
                        nh = a.get("href")
                        if "/front/news/view/" in nh:
                            if nh.startswith("/"): nh = "https://www.concursos.ufms.br" + nh
                            n_title = a.get_text().strip()
                            if not any(item["url"] == nh for item in news_items):
                                news_items.append({"url": nh, "titulo": n_title})
                    
                    novos_items = [item for item in news_items if not ja_existe(db, item["url"])]
                    for item in novos_items[:5]:
                        n_url = item["url"]
                        n_titulo = item["titulo"]
                        
                        r_noticia = requests.get(n_url, headers=headers, timeout=30, verify=False)
                        if r_noticia.status_code != 200: continue
                        soup_noticia = BeautifulSoup(r_noticia.text, "html.parser")
                        txt_noticia = soup_noticia.get_text()
                        
                        docs = []
                        for a_doc in soup_noticia.find_all("a", href=True):
                            dh = a_doc.get("href")
                            if "/front/documents/download/" in dh:
                                if dh.startswith("/"): dh = "https://www.concursos.ufms.br" + dh
                                docs.append(dh)
                        
                        ti_encontrado = False
                        trecho_encontrado = ""
                        termo_encontrado = ""
                        
                        match_txt = PADRAO_TI_UFMS.search(txt_noticia)
                        if match_txt and ("vaga" in txt_noticia.lower() or "cargo" in txt_noticia.lower() or "edital" in txt_noticia.lower()):
                            ti_encontrado = True
                            termo_encontrado = match_txt.group(0)
                            idx = match_txt.start()
                            trecho_encontrado = " ".join(txt_noticia[max(0, idx - 80):min(len(txt_noticia), idx + 80)].split())
                        
                        if not ti_encontrado and docs:
                            for doc_url in docs[:2]:
                                try:
                                    r_pdf = requests.get(doc_url, headers=headers, timeout=45, verify=False)
                                    if r_pdf.status_code == 200:
                                        reader = PyPDF2.PdfReader(io.BytesIO(r_pdf.content))
                                        for page in reader.pages:
                                            raw_p = page.extract_text() or ""
                                            clean_p = normalizar_texto_pdf(raw_p)
                                            m_pdf = PADRAO_TI_UFMS.search(clean_p)
                                            if m_pdf and ("vaga" in clean_p.lower() or "facom" in clean_p.lower() or "docente" in clean_p.lower() or "concurso" in clean_p.lower()):
                                                ti_encontrado = True
                                                termo_encontrado = m_pdf.group(0)
                                                idx = m_pdf.start()
                                                trecho_encontrado = " ".join(clean_p[max(0, idx - 80):min(len(clean_p), idx + 80)].split())
                                                break
                                    if ti_encontrado:
                                        break
                                except Exception as pdf_err:
                                    print(f"Erro lendo PDF UFMS {doc_url}: {pdf_err}")
                        
                        if ti_encontrado:
                            msg = f"🚨 *NOVIDADE NA UFMS (CONCURSOS)!*\n\n🏢 *Evento:* {ev_titulo}\n📝 *Edital:* {n_titulo}\n🎯 *Trecho:* ...{trecho_encontrado}...\n\n🔗 *Acessar:* {n_url}"
                            msg, keyword = destacar_termo(msg, trecho_encontrado or termo_encontrado, padrao=PADRAO_TI_UFMS)
                            if disparar_telegram(msg):
                                time.sleep(2)
                            db = adicionar_vaga(db, n_url, f"UFMS - {ev_titulo}", "Universidades MS", f"{n_titulo} | {trecho_encontrado}", n_url, False, None, "Mato Grosso do Sul", "Capturado", keyword)
                            novos += 1
                        else:
                            db = adicionar_vaga(db, n_url, f"UFMS - {n_titulo} (Sem TI)", "Universidades MS", "Sem menção a vagas de TI.", n_url, is_silent=True)
                except Exception as ev_err:
                    print(f"Erro inspecionando evento UFMS {ev_url}: {ev_err}")
    except Exception as e:
        print(f"Erro Uni UFMS: {e}")
        registrar_saude("Uni_UFMS", False, str(e))

    # 2. IFMS (selecao.ifms.edu.br)
    try:
        url_ifms = "https://selecao.ifms.edu.br/"
        r_ifms = requests.get(url_ifms, headers=headers, timeout=30, verify=False)
        if r_ifms.status_code == 403:
            print("[IFMS] HTTP 403 Forbidden detectado (Datacenter WAF). Silenciando graciosamente...")
            registrar_saude("Uni_IFMS", False, msg_erro="HTTP 403 (Bloqueio Datacenter)", info_adicional="Bloqueado por WAF na nuvem. Aguardando execução local.", silencioso=True)
        elif r_ifms.status_code != 200:
            registrar_saude("Uni_IFMS", False, f"HTTP {r_ifms.status_code}", silencioso=True)
        else:
            registrar_saude("Uni_IFMS", True, info_adicional="Operando normalmente.")
            soup_ifms = BeautifulSoup(r_ifms.text, "html.parser")
            for el in soup_ifms.find_all(['tr', 'li', 'div', 'a']):
                txt = el.get_text(separator=' ').strip()
                if not txt or len(txt) < 10: continue
                if PADRAO_TI.search(txt) and PADRAO_VAGA.search(txt):
                    link_tag = el if el.name == 'a' else el.find('a')
                    link = link_tag.get('href') if link_tag else None
                    if link and link.startswith('//'): link = "https:" + link
                    elif link and link.startswith('/'): link = "https://selecao.ifms.edu.br" + link
                    
                    if not link or ja_existe(db, link): continue
                    
                    txt_limpo = " ".join(txt.split())
                    txt_resumo = txt_limpo[:247] + "..." if len(txt_limpo) > 250 else txt_limpo
                    
                    msg = f"🚨 *NOVIDADE NO IFMS!*\n\n📝 *Detalhe:* {txt_resumo}\n\n🔗 *Acessar:* {link}"
                    msg, keyword = destacar_termo(msg, txt_resumo)
                    if disparar_telegram(msg):
                        time.sleep(2)
                    db = adicionar_vaga(db, link, "Atualização IFMS", "Universidades MS", txt_resumo, link, False, None, "Mato Grosso do Sul", "Capturado", keyword)
                    novos += 1
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as ifms_net_e:
        print(f"[IFMS] Timeout/Conexão: {ifms_net_e}. Silenciando graciosamente...")
        registrar_saude("Uni_IFMS", False, msg_erro="Timeout/ConnectionError", info_adicional="Indisponível temporariamente na nuvem.", silencioso=True)
    except Exception as e:
        print(f"Erro Uni IFMS: {e}")
        registrar_saude("Uni_IFMS", False, str(e), silencioso=True)

    return db, novos

def monitorar_diogrande(db, modo_local=False):
    headers_api = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://diogrande.campogrande.ms.gov.br/"
    }
    novos = 0
    url_api = "https://diogrande.campogrande.ms.gov.br/wp-admin/admin-ajax.php?action=edicao2_dia_json"
    
    try:
        r = requests.get(url_api, headers=headers_api, timeout=30, verify=False)
        if r.status_code in [403, 503]:
            print(f"[Diogrande] HTTP {r.status_code} (Bloqueio Geo/WAF na nuvem). Silenciando graciosamente...")
            registrar_saude("Diogrande", False, msg_erro=f"HTTP {r.status_code}", info_adicional="Bloqueado na nuvem (Geo-blocking). Aguardando execução local.", silencioso=True)
            return db, 0
        elif r.status_code != 200:
            print(f"[Diogrande] HTTP {r.status_code} inesperado.")
            registrar_saude("Diogrande", False, msg_erro=f"HTTP {r.status_code}", info_adicional="Resposta inesperada", silencioso=not modo_local)
            return db, 0

        links = []
        try:
            dados = r.json()
            if 'atual' in dados and 'arquivos' in dados['atual']:
                for a in dados['atual']['arquivos']:
                    cod = a.get('codigodia')
                    nome = a.get('nomearquivo', 'Edição')
                    if cod:
                        b64 = base64.b64encode(f'{{"codigodia":"{cod}"}}'.encode()).decode()
                        links.append({"url": f"https://diogrande.campogrande.ms.gov.br/download_edicao/{b64}.pdf", "nome": f"Diário Oficial - {nome}"})
            
            if 'ultimasedicoes' in dados:
                for ed in dados['ultimasedicoes']:
                    if 'arquivos' in ed:
                        for a in ed['arquivos']:
                            cod = a.get('codigodia')
                            nome = a.get('nomearquivo', 'Edição')
                            data_form = f"{ed.get('dia_dia', '')}/{ed.get('dia_mes', '')}"
                            if cod:
                                b64 = base64.b64encode(f'{{"codigodia":"{cod}"}}'.encode()).decode()
                                links.append({"url": f"https://diogrande.campogrande.ms.gov.br/download_edicao/{b64}.pdf", "nome": f"Diário Oficial ({data_form}) - {nome}"})
        except Exception as json_e:
            print(f"[Diogrande] Erro ao decodificar JSON: {json_e}")
            registrar_saude("Diogrande", False, f"JSON Error: {json_e}", silencioso=True)
            return db, 0
        
        if not links:
            registrar_saude("Diogrande", False, "API não retornou links", silencioso=True)
            return db, 0
        
        pdf_headers = HEADERS_NAVEGADOR
        
        for l_obj in links:
            link = l_obj["url"]
            titulo_padrao = l_obj["nome"]
            
            if ja_existe(db, link):
                continue
            
            try:
                pdf_r = requests.get(link, headers=pdf_headers, timeout=45, verify=False)
                if pdf_r.status_code in [403, 503]:
                    print(f"[Diogrande] Bloqueio ao baixar PDF {link} (HTTP {pdf_r.status_code}). Silenciando...")
                    registrar_saude("Diogrande", False, f"Download PDF HTTP {pdf_r.status_code}", info_adicional="Bloqueado na nuvem", silencioso=True)
                    return db, novos
                elif pdf_r.status_code != 200:
                    print(f"[Diogrande] Erro HTTP {pdf_r.status_code} no PDF {link}")
                    registrar_saude("Diogrande", False, f"Download PDF HTTP {pdf_r.status_code}", silencioso=True)
                    return db, novos
                
                reader = PyPDF2.PdfReader(io.BytesIO(pdf_r.content))
                encontrou = False
                trecho = ""
                for page in reader.pages:
                    raw_txt = page.extract_text() or ""
                    txt = normalizar_texto_pdf(raw_txt)
                    if txt and PADRAO_TI.search(txt) and PADRAO_VAGA.search(txt):
                        encontrou = True
                        idx = PADRAO_TI.search(txt).start()
                        trecho = txt[max(0, idx - 150):min(len(txt), idx + 150)].replace('\n', ' ')
                        break
                
                if encontrou:
                    msg = f"🚨 *ALERTA NO DIOGRANDE!*\n\n📌 *Arquivo:* {titulo_padrao}\n📝 *Trecho:* ...{trecho}...\n\n🔗 *Baixar:* {link}"
                    msg, keyword = destacar_termo(msg, trecho)
                    if disparar_telegram(msg):
                        time.sleep(2)
                    db = adicionar_vaga(db, link, titulo_padrao, "Diogrande", trecho, link, False, None, "Campo Grande - MS", "Capturado", keyword)
                    novos += 1
                else:
                    db = adicionar_vaga(db, link, titulo_padrao + " (Sem TI)", "Diogrande", "Sem vagas detectadas.", link, is_silent=True, local="Campo Grande - MS")
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as pdf_net_e:
                print(f"[Diogrande] Timeout/Conexão ao baixar PDF: {pdf_net_e}")
                registrar_saude("Diogrande", False, "Timeout ao baixar PDF", info_adicional="Timeout na nuvem", silencioso=True)
                return db, novos
            except Exception as pdf_e:
                print(f"[Diogrande] Erro ao processar PDF: {pdf_e}")
                
        registrar_saude("Diogrande", True, info_adicional=f"Lidos {len(links)} PDFs das últimas edições.")
        
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as net_e:
        print(f"[Diogrande] Timeout/Conexão com API Diogrande: {net_e}. Silenciando graciosamente...")
        registrar_saude("Diogrande", False, msg_erro="Timeout/ConnectionError", info_adicional="Timeout na nuvem", silencioso=True)
    except Exception as e:
        print(f"[Diogrande] Exceção geral: {e}")
        registrar_saude("Diogrande", False, str(e), silencioso=not modo_local)
        
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
            r = requests.get(url, headers=headers, timeout=45)
            if r.status_code != 200:
                registrar_saude(f"UFMS_Lato_Sensu_{nome}", False, f"HTTP {r.status_code}")
                continue
            registrar_saude(f"UFMS_Lato_Sensu_{nome}", True)
            
            soup = BeautifulSoup(r.text, 'html.parser')
            
            if tipo == "lista_cursos":
                lista = soup.find('ul', id='ListagemProcessos')
                if not lista: lista = soup
                for li in lista.find_all(['li', 'a', 'div']):
                    link_tag = li if li.name == 'a' else li.find('a')
                    if not link_tag: continue
                    texto = li.get_text(separator=" ").strip().lower()
                    link_curso = link_tag.get('href', '')
                    if not link_curso: continue
                    if link_curso.startswith('/'): link_curso = "https://posgraduacao.ufms.br" + link_curso
                    if not link_curso.startswith('http'): continue
                    
                    if ja_existe(db, link_curso): continue
                    
                    encontradas = [p for p in KEYWORDS_CONFIG + ["especialização", "lato sensu"] if p.lower() in texto]
                    if not encontradas: continue
                    
                    titulo_curso = link_tag.get_text(separator=" ").strip()
                    if len(titulo_curso) < 5: titulo_curso = texto[:100]
                    titulo_curso = titulo_curso[:120]
                    
                    msg = f"\U0001f6a8 *Pós-Graduação UFMS - Inscrição Aberta!*\n\n\U0001f3eb *Curso:* {titulo_curso}\n\U0001f4dd *Palavras:* {', '.join(encontradas[:5])}\n\n\U0001f517 *Inscreva-se:* {link_curso}"
                    
                    cidades_ms = ["Campo Grande", "Dourados", "Três Lagoas", "Corumbá", "Ponta Porã", "Aquidauana", "Naviraí", "Nova Andradina", "Coxim", "Paranaíba", "Chapadão do Sul"]
                    cidades = [c for c in cidades_ms if c.lower() in texto.lower()]
                    local_str = ", ".join(cidades) if cidades else "Mato Grosso do Sul"
                    
                    if disparar_telegram(msg):
                        db = adicionar_vaga(db, link_curso, titulo_curso, "UFMS Pós", f"Inscrições abertas. Palavras: {', '.join(encontradas[:5])}", link_curso, False, None, local_str, "Capturado", encontradas[0])
                        novos += 1
                        time.sleep(2)
            else:
                # General page monitoring (PROPP)
                for tag in soup(["script", "style", "nav", "footer", "header"]): tag.extract()
                texto = ' '.join(soup.get_text(separator=' ').split()).lower()
                hash_atual = hashlib.md5(texto.encode('utf-8')).hexdigest()
                id_hash = f"{url}_{hash_atual}"
                
                if ja_existe(db, id_hash): continue
                
                encontradas = [p for p in KEYWORDS_CONFIG + ["especialização", "lato sensu"] if p.lower() in texto]
                if encontradas:
                    # Try to find a specific link on the page
                    best_link = url
                    for a in soup.find_all('a', href=True):
                        a_text = a.get_text().lower()
                        if any(k.lower() in a_text for k in encontradas[:3]):
                            href = a.get('href', '')
                            if href.startswith('/'): href = 'https://propp.ufms.br' + href
                            if href.startswith('http'): best_link = href; break
                    
                    msg = f"\U0001f6a8 *Nova Atualização na UFMS Pós-Graduação!*\n\n\U0001f3eb *Alvo:* {nome}\n\U0001f4dd *Palavras encontradas:* {', '.join(encontradas[:5])}\n\n\U0001f517 *Acesse:* {best_link}"
                    
                    cidades_ms = ["Campo Grande", "Dourados", "Três Lagoas", "Corumbá", "Ponta Porã", "Aquidauana", "Naviraí", "Nova Andradina", "Coxim", "Paranaíba", "Chapadão do Sul"]
                    cidades = [c for c in cidades_ms if c.lower() in texto.lower()]
                    local_str = ", ".join(cidades) if cidades else "Mato Grosso do Sul"
                    
                    if disparar_telegram(msg):
                        db = adicionar_vaga(db, id_hash, f"Pós-Graduação: {nome}", "UFMS Pós", f"Atualização contendo: {', '.join(encontradas[:5])}", best_link, False, None, local_str, "Capturado", encontradas[0])
                        novos += 1
                else:
                    db = adicionar_vaga(db, id_hash, f"Atualização Pós: {nome}", "UFMS Pós", "Página alterada (Sem palavras TI detectadas)", url, is_silent=True)
        except Exception as e:
            print(f"Erro UFMS Pós {nome}: {e}")
    return db, novos


def verificar_inatividade_diogrande():
    """Função desativada para eliminar mensagens de spam no Telegram.
    O scraper do Diogrande agora roda no fluxo unificado (nuvem e local)."""
    pass

def main():
    import sys
    print("Iniciando varredura unificada Radar MS...")
    db = carregar_database()
    total_novos = 0
    
    if "--diogrande-only" in sys.argv:
        print("Modo Local: Rodando apenas Diogrande...")
        db, n = monitorar_diogrande(db, modo_local=True); total_novos += n
    else:
        print("Modo Nuvem: Rodando scrapers unificados...")
        db, n = monitorar_diogrande(db, modo_local=False); total_novos += n
        db, n = monitorar_pci(db); total_novos += n
        db, n = monitorar_rss_google(db); total_novos += n
        db, n = monitorar_sad(db); total_novos += n
        db, n = monitorar_universidades(db); total_novos += n
        db, n = monitorar_ufms_lato_sensu(db); total_novos += n
    
    salvar_database(db)
    print(f"Varredura concluída. {total_novos} novos alertas disparados e salvos no banco de dados.")

if __name__ == "__main__":
    main()
