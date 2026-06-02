import requests
import hashlib
import json
import os
from bs4 import BeautifulSoup

# ==========================================
# CONFIGURAÇÕES E SEGREDOS
# ==========================================
# Variáveis de ambiente configuradas no GitHub Secrets
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

HISTORICO_ARQUIVO = "historico_ufms.json"

ALVOS = [
    {
        "nome": "PROPP Editais",
        "url": "https://propp.ufms.br/",
        "tipo_extracao": "geral"
    },
    {
        "nome": "Inscrições Abertas Pós",
        "url": "https://posgraduacao.ufms.br/portal/cursos/listagem-inscricoes-abertas",
        "tipo_extracao": "lista_cursos"
    }
]

PALAVRAS_CHAVE = [
    "especialização", "lato sensu", "segurança", "cibersegurança",
    "cybersecurity", "computação", "tecnologia", "informática"
]

# ==========================================
# FUNÇÕES
# ==========================================
def enviar_telegram(mensagem):
    """Envia uma mensagem via Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Aviso: Tokens do Telegram não encontrados no ambiente. Pulando envio de mensagem.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print("Mensagem enviada no Telegram com sucesso!")
    except Exception as e:
        print(f"Erro ao enviar Telegram: {e}")

def carregar_historico():
    """Carrega o histórico de hashes do arquivo JSON."""
    if os.path.exists(HISTORICO_ARQUIVO):
        try:
            with open(HISTORICO_ARQUIVO, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def salvar_historico(historico):
    """Salva o histórico de hashes no arquivo JSON."""
    with open(HISTORICO_ARQUIVO, 'w', encoding='utf-8') as f:
        json.dump(historico, f, indent=4)

def extrair_texto(html, tipo_extracao):
    """Extrai o texto relevante da página com base na estrutura conhecida."""
    soup = BeautifulSoup(html, 'html.parser')
    
    if tipo_extracao == "lista_cursos":
        # Busca apenas a lista de processos de inscrição
        lista = soup.find('ul', id='ListagemProcessos')
        if lista:
            texto = lista.get_text(separator=' ')
        else:
            # Fallback se a lista não for encontrada
            texto = soup.get_text(separator=' ')
    else:
        # Extração geral (PROPP)
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.extract()
        texto = soup.get_text(separator=' ')
        
    # Remove espaços extras e converte para minúsculas
    return ' '.join(texto.split()).lower()

def verificar_alvos():
    """Percorre os alvos e verifica se houve alteração na página."""
    historico = carregar_historico()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    houve_alteracao = False

    for alvo in ALVOS:
        nome = alvo["nome"]
        url = alvo["url"]
        tipo_extracao = alvo["tipo_extracao"]
        print(f"[{nome}] Checando URL: {url}...")
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            # Pega o texto alvo
            texto_limpo = extrair_texto(response.text, tipo_extracao)
            
            # Gera o hash
            hash_atual = hashlib.md5(texto_limpo.encode('utf-8')).hexdigest()
            hash_salvo = historico.get(url, "")
            
            if hash_atual != hash_salvo:
                print(f"[{nome}] -> MUDANÇA DETECTADA!")
                
                # Procura por palavras-chave
                encontradas = [p for p in PALAVRAS_CHAVE if p in texto_limpo]
                
                if encontradas:
                    msg = (f"🚨 <b>Novo Edital / Atualização Detectada!</b> 🚨\n\n"
                           f"<b>Alvo:</b> {nome}\n"
                           f"<b>URL:</b> {url}\n"
                           f"<b>Palavras-chave:</b> {', '.join(encontradas)}")
                    enviar_telegram(msg)
                else:
                    print(f"[{nome}] -> Página mudou, mas sem palavras-chave.")
                
                # Atualiza o hash no histórico
                historico[url] = hash_atual
                houve_alteracao = True
            else:
                print(f"[{nome}] -> Sem mudanças.")
                
        except Exception as e:
            print(f"[{nome}] -> Erro ao checar: {e}")

    if houve_alteracao:
        salvar_historico(historico)
        print("Histórico atualizado com sucesso. O GitHub Action fará o commit deste arquivo.")
    else:
        print("Nenhuma alteração nos arquivos.")

if __name__ == "__main__":
    verificar_alvos()
