import os
import html
import secrets
from flask import Flask, request, redirect, Response
import requests

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")
TEST_PHONE = os.environ.get("TEST_PHONE")
TEST_SECRET = os.environ.get("TEST_SECRET")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY")

ATENDIMENTO_USER = os.environ.get("ATENDIMENTO_USER")
ATENDIMENTO_PASSWORD = os.environ.get("ATENDIMENTO_PASSWORD")


# =========================================================
# FUNÇÕES AUXILIARES
# =========================================================

def supabase_headers():
    return {
        "apikey": SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "Content-Type": "application/json"
    }


def autenticado():
    auth = request.authorization

    if not ATENDIMENTO_USER or not ATENDIMENTO_PASSWORD:
        return False

    if not auth:
        return False

    usuario_ok = secrets.compare_digest(
        auth.username or "",
        ATENDIMENTO_USER
    )

    senha_ok = secrets.compare_digest(
        auth.password or "",
        ATENDIMENTO_PASSWORD
    )

    return usuario_ok and senha_ok


def exigir_login():
    return Response(
        "Acesso restrito à equipe CMK.",
        401,
        {
            "WWW-Authenticate": 'Basic realm="Atendimento CMK"'
        }
    )


def salvar_mensagem(
    telefone,
    nome_contato,
    mensagem,
    direcao,
    whatsapp_message_id
):
    url = f"{SUPABASE_URL}/rest/v1/mensagens"

    headers = supabase_headers()
    headers["Prefer"] = "return=minimal"

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

    print(
        "SUPABASE STATUS:",
        resposta.status_code
    )

    return resposta.status_code


def buscar_mensagens():
    url = f"{SUPABASE_URL}/rest/v1/mensagens"

    parametros = {
        "select": "*",
        "order": "created_at.asc"
    }

    resposta = requests.get(
        url,
        headers=supabase_headers(),
        params=parametros,
        timeout=15
    )

    if not resposta.ok:
        print(
            "ERRO AO LER SUPABASE:",
            resposta.status_code
        )
        return []

    return resposta.json()


def enviar_mensagem(numero, mensagem):
    url = (
        f"https://graph.facebook.com/v26.0/"
        f"{PHONE_NUMBER_ID}/messages"
    )

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

    message_id = None

    if resposta.ok:
        try:
            dados = resposta.json()
            message_id = dados["messages"][0]["id"]
        except (KeyError, IndexError, TypeError):
            pass

    return resposta.status_code, message_id


# =========================================================
# PÁGINA PRINCIPAL
# =========================================================

@app.route("/", methods=["GET"])
def inicio():
    return "Webhook da CMK funcionando!", 200


# =========================================================
# WEBHOOK META
# =========================================================

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

        for msg in mensagens:
            telefone = msg.get("from")
            whatsapp_message_id = msg.get("id")

            nome_contato = ""

            if contatos:
                nome_contato = (
                    contatos[0]
                    .get("profile", {})
                    .get("name", "")
                )

            tipo = msg.get("type")

            if tipo == "text":
                texto = (
                    msg.get("text", {})
                    .get("body", "")
                )
            else:
                texto = f"[{tipo or 'mensagem'}]"

            salvar_mensagem(
                telefone,
                nome_contato,
                texto,
                "entrada",
                whatsapp_message_id
            )

    except (KeyError, IndexError, TypeError) as erro:
        print("WEBHOOK IGNORADO:", erro)

    return "EVENT_RECEIVED", 200


# =========================================================
# TESTE DE ENVIO
# =========================================================

@app.route("/teste-envio", methods=["POST"])
def teste_envio():
    segredo = request.headers.get("X-Test-Secret")

    if not TEST_SECRET or segredo != TEST_SECRET:
        return "Não autorizado", 401

    if not TEST_PHONE:
        return "Número de teste não configurado", 500

    status, _ = enviar_mensagem(
        TEST_PHONE,
        "Teste de envio da API oficial do WhatsApp da CMK."
    )

    if status == 200:
        return "Mensagem enviada", 200

    return "Falha no envio", 500


# =========================================================
# ENVIAR RESPOSTA PELO ATENDIMENTO
# =========================================================

@app.route("/atendimento/enviar", methods=["POST"])
def atendimento_enviar():
    if not autenticado():
        return exigir_login()

    telefone = request.form.get("telefone", "").strip()
    nome = request.form.get("nome", "").strip()
    mensagem = request.form.get("mensagem", "").strip()

    if not telefone or not mensagem:
        return "Telefone e mensagem são obrigatórios.", 400

    status, message_id = enviar_mensagem(
        telefone,
        mensagem
    )

    if status == 200:
        salvar_mensagem(
            telefone,
            nome,
            mensagem,
            "saida",
            message_id
        )

        return redirect(
            f"/atendimento?telefone={telefone}"
        )

    return (
        "Não foi possível enviar a mensagem pelo WhatsApp.",
        500
    )


# =========================================================
# CENTRAL DE ATENDIMENTO
# =========================================================

@app.route("/atendimento", methods=["GET"])
def atendimento():
    if not autenticado():
        return exigir_login()

    mensagens = buscar_mensagens()

    contatos = {}

    for item in mensagens:
        telefone = item.get("telefone") or ""

        if not telefone:
            continue

        nome = item.get("nome_contato") or "Contato"

        if telefone not in contatos:
            contatos[telefone] = {
                "nome": nome,
                "telefone": telefone,
                "mensagens": []
            }

        if (
            contatos[telefone]["nome"] == "Contato"
            and nome != "Contato"
        ):
            contatos[telefone]["nome"] = nome

        contatos[telefone]["mensagens"].append(item)

    telefone_ativo = request.args.get(
        "telefone",
        ""
    )

    if not telefone_ativo and contatos:
        telefone_ativo = list(contatos.keys())[-1]

    lista_contatos = ""

    for telefone, contato in reversed(
        list(contatos.items())
    ):
        nome_seguro = html.escape(
            contato["nome"]
        )

        telefone_seguro = html.escape(
            telefone
        )

        ultima = ""

        if contato["mensagens"]:
            ultima = (
                contato["mensagens"][-1]
                .get("mensagem", "")
            )

        ultima_segura = html.escape(
            ultima[:45]
        )

        classe = "contato"

        if telefone == telefone_ativo:
            classe += " ativo"

        lista_contatos += f"""
        <a class="{classe}"
           href="/atendimento?telefone={telefone_seguro}">
            <div class="avatar">
                {nome_seguro[:1].upper()}
            </div>

            <div class="contato-info">
                <strong>{nome_seguro}</strong>
                <span>{ultima_segura}</span>
            </div>
        </a>
        """

    area_conversa = """
        <div class="sem-conversa">
            Selecione uma conversa para começar.
        </div>
    """

    if telefone_ativo in contatos:
        contato = contatos[telefone_ativo]

        nome = html.escape(
            contato["nome"]
        )

        telefone = html.escape(
            contato["telefone"]
        )

        bolhas = ""

        for item in contato["mensagens"]:
            texto = html.escape(
                item.get("mensagem") or ""
            )

            direcao = item.get("direcao")

            classe = (
                "mensagem-balao saida"
                if direcao == "saida"
                else "mensagem-balao entrada"
            )

            bolhas += f"""
            <div class="{classe}">
                {texto}
            </div>
            """

        area_conversa = f"""
        <div class="cabecalho-conversa">
            <div class="avatar grande">
                {nome[:1].upper()}
            </div>

            <div>
                <strong>{nome}</strong>
                <span>{telefone}</span>
            </div>
        </div>

        <div class="historico">
            {bolhas}
        </div>

        <form
            class="caixa-envio"
            method="POST"
            action="/atendimento/enviar"
        >
            <input
                type="hidden"
                name="telefone"
                value="{telefone}"
            >

            <input
                type="hidden"
                name="nome"
                value="{nome}"
            >

            <textarea
                name="mensagem"
                placeholder="Digite sua mensagem..."
                required
            ></textarea>

            <button type="submit">
                Enviar
            </button>
        </form>
        """

    if not lista_contatos:
        lista_contatos = """
        <div class="vazio">
            Nenhuma conversa ainda.
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="pt-BR">

    <head>
        <meta charset="UTF-8">

        <meta
            name="viewport"
            content="width=device-width, initial-scale=1.0"
        >

        <title>Central CMK</title>

        <style>
            * {{
                box-sizing: border-box;
            }}

            body {{
                margin: 0;
                font-family: Arial, sans-serif;
                background: #eef1f5;
                color: #1f2937;
            }}

            .topo {{
                height: 70px;
                background: #111827;
                color: white;
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 0 25px;
            }}

            .marca {{
                font-size: 22px;
                font-weight: bold;
            }}

            .menu {{
                display: flex;
                gap: 10px;
            }}

            .menu a {{
                color: white;
                text-decoration: none;
                padding: 10px 14px;
                border-radius: 7px;
                background: rgba(255,255,255,0.08);
            }}

            .menu a.ativo {{
                background: white;
                color: #111827;
            }}

            .central {{
                width: calc(100% - 40px);
                max-width: 1300px;
                height: calc(100vh - 100px);
                margin: 15px auto;
                background: white;
                border-radius: 12px;
                overflow: hidden;
                display: grid;
                grid-template-columns: 340px 1fr;
                box-shadow: 0 4px 18px rgba(0,0,0,0.08);
            }}

            .lateral {{
                border-right: 1px solid #e5e7eb;
                overflow-y: auto;
                background: white;
            }}

            .titulo-lateral {{
                padding: 20px;
                font-size: 20px;
                font-weight: bold;
                border-bottom: 1px solid #e5e7eb;
            }}

            .contato {{
                display: flex;
                gap: 12px;
                padding: 15px 18px;
                text-decoration: none;
                color: #111827;
                border-bottom: 1px solid #f1f1f1;
            }}

            .contato:hover {{
                background: #f8fafc;
            }}

            .contato.ativo {{
                background: #eef2ff;
            }}

            .avatar {{
                width: 42px;
                height: 42px;
                border-radius: 50%;
                background: #111827;
                color: white;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: bold;
                flex-shrink: 0;
            }}

            .avatar.grande {{
                width: 45px;
                height: 45px;
            }}

            .contato-info {{
                min-width: 0;
                display: flex;
                flex-direction: column;
                gap: 5px;
            }}

            .contato-info span {{
                color: #6b7280;
                font-size: 13px;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }}

            .painel {{
                display: flex;
                flex-direction: column;
                min-width: 0;
            }}

            .cabecalho-conversa {{
                height: 72px;
                padding: 12px 20px;
                border-bottom: 1px solid #e5e7eb;
                display: flex;
                align-items: center;
                gap: 12px;
            }}

            .cabecalho-conversa div:last-child {{
                display: flex;
                flex-direction: column;
                gap: 4px;
            }}

            .cabecalho-conversa span {{
                color: #6b7280;
                font-size: 13px;
            }}

            .historico {{
                flex: 1;
                overflow-y: auto;
                padding: 25px;
                background: #f8fafc;
                display: flex;
                flex-direction: column;
                gap: 10px;
            }}

            .mensagem-balao {{
                max-width: 70%;
                padding: 11px 14px;
                border-radius: 12px;
                line-height: 1.4;
                word-wrap: break-word;
            }}

            .mensagem-balao.entrada {{
                align-self: flex-start;
                background: white;
                border: 1px solid #e5e7eb;
            }}

            .mensagem-balao.saida {{
                align-self: flex-end;
                background: #dcfce7;
            }}

            .caixa-envio {{
                min-height: 82px;
                border-top: 1px solid #e5e7eb;
                padding: 12px;
                display: flex;
                gap: 10px;
                background: white;
            }}

            .caixa-envio textarea {{
                flex: 1;
                resize: none;
                border: 1px solid #d1d5db;
                border-radius: 9px;
                padding: 12px;
                font-family: Arial, sans-serif;
                font-size: 15px;
                outline: none;
            }}

            .caixa-envio button {{
                border: 0;
                border-radius: 9px;
                padding: 0 24px;
                background: #111827;
                color: white;
                font-weight: bold;
                cursor: pointer;
            }}

            .caixa-envio button:hover {{
                opacity: 0.9;
            }}

            .sem-conversa {{
                height: 100%;
                display: flex;
                align-items: center;
                justify-content: center;
                color: #6b7280;
                background: #f8fafc;
            }}

            .vazio {{
                padding: 25px;
                color: #6b7280;
            }}

            @media (max-width: 760px) {{
                .central {{
                    width: 100%;
                    height: calc(100vh - 70px);
                    margin: 0;
                    border-radius: 0;
                    grid-template-columns: 140px 1fr;
                }}

                .topo {{
                    height: 70px;
                }}

                .marca {{
                    font-size: 17px;
                }}

                .menu {{
                    display: none;
                }}

                .titulo-lateral {{
                    font-size: 15px;
                    padding: 15px 10px;
                }}

                .contato {{
                    padding: 12px 8px;
                }}

                .avatar {{
                    display: none;
                }}

                .mensagem-balao {{
                    max-width: 88%;
                }}
            }}
        </style>
    </head>

    <body>

        <header class="topo">
            <div class="marca">
                CMK • Central de Atendimento
            </div>

            <nav class="menu">
                <a
                    class="ativo"
                    href="/atendimento"
                >
                    Atendimento
                </a>

                <a href="/campanhas">
                    Campanhas
                </a>
            </nav>
        </header>

        <main class="central">

            <aside class="lateral">
                <div class="titulo-lateral">
                    Conversas
                </div>

                {lista_contatos}
            </aside>

            <section class="painel">
                {area_conversa}
            </section>

        </main>

    </body>
    </html>
    """, 200


# =========================================================
# CAMPANHAS
# =========================================================

@app.route("/campanhas", methods=["GET"])
def campanhas():
    if not autenticado():
        return exigir_login()

    return """
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta
            name="viewport"
            content="width=device-width, initial-scale=1.0"
        >
        <title>Campanhas CMK</title>

        <style>
            body {
                margin: 0;
                font-family: Arial, sans-serif;
                background: #f3f4f6;
                color: #111827;
            }

            .topo {
                background: #111827;
                color: white;
                padding: 20px 30px;
            }

            .conteudo {
                max-width: 900px;
                margin: 35px auto;
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 4px 18px rgba(0,0,0,0.08);
            }

            .aviso {
                background: #fef3c7;
                padding: 16px;
                border-radius: 8px;
                margin-top: 20px;
            }

            a {
                color: #111827;
                font-weight: bold;
            }
        </style>
    </head>

    <body>
        <div class="topo">
            <h2>CMK • Campanhas</h2>
        </div>

        <div class="conteudo">
            <p>
                <a href="/atendimento">
                    ← Voltar para Atendimento
                </a>
            </p>

            <h1>Campanhas e Disparos</h1>

            <p>
                Esta área será usada para campanhas oficiais
                do WhatsApp da CMK.
            </p>

            <div class="aviso">
                Os disparos serão ativados após configurarmos
                contatos com consentimento e os templates
                aprovados pela Meta.
            </div>
        </div>
    </body>
    </html>
    """, 200
