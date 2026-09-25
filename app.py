import os
from flask import Flask, request
import requests

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")
TEST_PHONE = os.environ.get("TEST_PHONE")
TEST_SECRET = os.environ.get("TEST_SECRET")


SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY")

@app.route("/", methods=["GET"])
def inicio():
    return "Webhook da CMK funcionando!", 200

@app.route("/webhook", methods=["GET"])
def verificar_webhook():
    modo = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    desafio = request.args.get("hub.challenge")

    if modo == "subscribe" and token == VERIFY_TOKEN:
        return desafio, 200

    return "Falha na verificacao", 403

@app.route("/webhook", methods=["POST"])
def receber_webhook():
    dados = request.get_json(silent=True) or {}

    try:
        value = dados["entry"][0]["changes"][0]["value"]
        mensagens = value.get("messages", [])
        contatos = value.get("contacts", [])

        if mensagens:
            msg = mensagens[0]
            telefone = msg.get("from")
            whatsapp_message_id = msg.get("id")

            nome_contato = ""
            if contatos:
                nome_contato = contatos[0].get("profile", {}).get("name", "")

            if msg.get("type") == "text":
                texto = msg.get("text", {}).get("body", "")
            else:
                texto = f"[{msg.get('type', 'mensagem')}]"

            salvar_mensagem(
                telefone,
                nome_contato,
                texto,
                "entrada",
                whatsapp_message_id
            )

    except (KeyError, IndexError, TypeError):
        pass

    return "EVENT_RECEIVED", 200


def salvar_mensagem(telefone, nome_contato, mensagem, direcao, whatsapp_message_id):
    url = f"{SUPABASE_URL}/rest/v1/mensagens"

    headers = {
        "apikey": SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }

    dados = {
        "telefone": telefone,
        "nome_contato": nome_contato,
        "mensagem": mensagem,
        "direcao": direcao,
        "whatsapp_message_id": whatsapp_message_id
    }

    resposta = requests.post(
        url,
        headers=headers,
        json=dados,
        timeout=15
    )
    print("SUPABASE STATUS:", resposta.status_code, "RESPOSTA:", resposta.text)
    return resposta.status_code


def enviar_mensagem(numero, mensagem):
    url = f"https://graph.facebook.com/v26.0/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "text",
        "text": {
            "body": mensagem
        }
    }

    resposta = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=15
    )

    return resposta.status_code


@app.route("/teste-envio", methods=["POST"])
def teste_envio():
    segredo = request.headers.get("X-Test-Secret")

    if not TEST_SECRET or segredo != TEST_SECRET:
        return "Não autorizado", 401

    if not TEST_PHONE:
        return "Número de teste não configurado", 500

    status = enviar_mensagem(
        TEST_PHONE,
        "Teste de envio da API oficial do WhatsApp da CMK."
    )

    if status == 200:
        return "Mensagem enviada", 200

    return "Falha no envio", 500


@app.route("/atendimento", methods=["GET"])
def atendimento():
    url = f"{SUPABASE_URL}/rest/v1/mensagens?select=*&order=created_at.desc"

    headers = {
        "apikey": SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}"
    }

    resposta = requests.get(
        url,
        headers=headers,
        timeout=15
    )

    if not resposta.ok:
        return "Erro ao carregar as mensagens.", 500

    mensagens = resposta.json()

    linhas = ""

    for item in mensagens:
        nome = item.get("nome_contato") or "Contato"
        telefone = item.get("telefone") or ""
        mensagem = item.get("mensagem") or ""

        linhas += f"""
        <div class="conversa">
            <div class="nome">{nome}</div>
            <div class="telefone">{telefone}</div>
            <div class="mensagem">{mensagem}</div>
        </div>
        """

    if not linhas:
        linhas = "<p>Nenhuma mensagem recebida.</p>"

    return f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Atendimento CMK</title>

        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f3f4f6;
                margin: 0;
            }}

            .topo {{
                background: #111827;
                color: white;
                padding: 20px 30px;
            }}

            .topo h1 {{
                margin: 0;
                font-size: 24px;
            }}

            .conteudo {{
                max-width: 900px;
                margin: 30px auto;
                padding: 0 20px;
            }}

            .conversa {{
                background: white;
                padding: 18px;
                margin-bottom: 12px;
                border-radius: 10px;
                box-shadow: 0 1px 4px rgba(0,0,0,0.08);
            }}

            .nome {{
                font-weight: bold;
                font-size: 17px;
            }}

            .telefone {{
                color: #6b7280;
                font-size: 13px;
                margin-top: 3px;
            }}

            .mensagem {{
                margin-top: 12px;
                font-size: 15px;
            }}
        </style>
    </head>

    <body>
        <div class="topo">
            <h1>Atendimento CMK</h1>
        </div>

        <div class="conteudo">
            <h2>Mensagens recebidas</h2>
            {linhas}
        </div>
    </body>
    </html>
    """, 200
