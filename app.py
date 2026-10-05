import os
import html
import secrets
from datetime import datetime, timezone, timedelta
from flask import Flask, request, redirect, Response, render_template
import requests
import uuid
from atendimento import atendimento_bp, configurar_atendimento

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
    whatsapp_message_id,
    request_id=None
):
    url = f"{SUPABASE_URL}/rest/v1/mensagens"

    headers = supabase_headers()
    headers["Prefer"] = "return=minimal"

    dados = {
        "telefone": telefone,
        "nome_contato": nome_contato,
        "mensagem": mensagem,
        "direcao": direcao,
        "whatsapp_message_id": whatsapp_message_id,
        "request_id": request_id
    }

    try:
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

        return resposta.ok

    except requests.RequestException:
        print("FALHA AO SALVAR MENSAGEM")
        return False


def buscar_mensagens():
    url = f"{SUPABASE_URL}/rest/v1/mensagens"

    parametros = {
       "select": "telefone,nome_contato,mensagem,direcao,whatsapp_message_id,created_at,status,status_at",
        "order": "created_at.desc",
        "limit": "500"
    }

    try:
        resposta = requests.get(
            url,
            headers=supabase_headers(),
            params=parametros,
            timeout=10
        )

        if not resposta.ok:
            print(
                "ERRO AO LER SUPABASE:",
                resposta.status_code
            )
            return []

        mensagens = resposta.json()

        # O Supabase entrega as mais recentes primeiro.
        # Invertemos para a conversa aparecer na ordem correta.
        mensagens.reverse()

        return mensagens

    except requests.RequestException:
        print("FALHA DE CONEXAO AO LER MENSAGENS")
        return []


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
        statuses = value.get("statuses", [])
        contatos = value.get("contacts", [])

        # ==========================================
        # MENSAGENS RECEBIDAS
        # ==========================================

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
                texto = msg.get("text", {}).get("body", "")

            elif tipo == "button":
                texto = msg.get("button", {}).get("text", "")

            elif tipo == "interactive":
                interactive = msg.get("interactive", {})
                interactive_type = interactive.get("type")

                if interactive_type == "button_reply":
                    texto = interactive.get(
                        "button_reply", {}
                    ).get("title", "")

                elif interactive_type == "list_reply":
                    texto = interactive.get(
                        "list_reply", {}
                    ).get("title", "")

                else:
                    texto = "[resposta interativa]"

            else:
                texto = f"[{tipo or 'mensagem'}]"

            salvar_mensagem(
                telefone,
                nome_contato,
                texto,
                "entrada",
                whatsapp_message_id
            )

            # Descadastro
            if (
                tipo == "text"
                and texto.strip().casefold() in (
                    "sair",
                    "parar",
                    "cancelar",
                    "descadastrar"
                )
                and telefone
            ):
                try:
                    numero = "".join(
                        c for c in telefone
                        if c.isdigit()
                    )

                    resposta_saida = requests.patch(
                        f"{SUPABASE_URL}/rest/v1/contatos_cmk",
                        headers={
                            **supabase_headers(),
                            "Prefer": "return=minimal"
                        },
                        params={
                            "telefone": f"eq.{numero}"
                        },
                        json={
                            "descadastrado": True,
                            "data_descadastro":
                                datetime.now(
                                    timezone.utc
                                ).isoformat()
                        },
                        timeout=15
                    )

                    print(
                        "DESCADASTRO STATUS:",
                        resposta_saida.status_code
                    )

                except requests.RequestException:
                    print(
                        "FALHA AO REGISTRAR DESCADASTRO"
                    )

        # ==========================================
        # STATUS: ENVIADO / ENTREGUE / LIDO / FALHA
        # ==========================================

        for item_status in statuses:
            message_id_status = item_status.get("id")
            status_meta = item_status.get("status")
            erros_meta = item_status.get("errors", [])

            if not message_id_status or not status_meta:
                continue

            try:
                # Atualiza campanha
                resposta_status = requests.patch(
                    f"{SUPABASE_URL}/rest/v1/envios_campanha",
                    headers={
                        **supabase_headers(),
                        "Prefer": "return=minimal"
                    },
                    params={
                        "whatsapp_message_id":
                            f"eq.{message_id_status}"
                    },
                    json={
                        "status": status_meta,
                        "status_at":
                            datetime.now(
                                timezone.utc
                            ).isoformat(),
                        "erro":
                            str(erros_meta)
                            if erros_meta
                            else None
                    },
                    timeout=15
                )

                # Atualiza mensagem do atendimento
                resposta_mensagem = requests.patch(
                    f"{SUPABASE_URL}/rest/v1/mensagens",
                    headers={
                        **supabase_headers(),
                        "Prefer": "return=minimal"
                    },
                    params={
                        "whatsapp_message_id":
                            f"eq.{message_id_status}"
                    },
                    json={
                        "status": status_meta,
                        "status_at":
                            datetime.now(
                                timezone.utc
                            ).isoformat()
                    },
                    timeout=15
                )

                print(
                    "STATUS META:",
                    status_meta,
                    "CAMPANHA:",
                    resposta_status.status_code,
                    "ATENDIMENTO:",
                    resposta_mensagem.status_code
                )

            except requests.RequestException:
                print(
                    "FALHA AO ATUALIZAR STATUS DA MENSAGEM"
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
    request_id = request.form.get("request_id", "").strip()

    if not telefone or not mensagem:
        return "Telefone e mensagem são obrigatórios.", 400

    if not request_id:
        request_id = str(uuid.uuid4())

    # Reserva este request_id antes de enviar para o WhatsApp.
    try:
        resposta_trava = requests.post(
            f"{SUPABASE_URL}/rest/v1/travas_envio",
            headers={
                **supabase_headers(),
                "Prefer": "return=minimal"
            },
            json={
                "request_id": request_id
            },
            timeout=10
        )

        # Chave duplicada: este envio já está em processamento
        # ou já foi processado.
        if resposta_trava.status_code == 409:
            return "Mensagem já processada.", 200

        if not resposta_trava.ok:
            print(
                "ERRO AO CRIAR TRAVA:",
                resposta_trava.status_code
            )
            return "Não foi possível iniciar o envio.", 500

    except requests.RequestException:
        return "Falha de conexão ao iniciar o envio.", 500

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
            message_id,
            request_id=request_id
        )

        return "Mensagem enviada.", 200

    # Se a Meta não aceitou o envio, libera a trava
    # para permitir uma nova tentativa.
    try:
        requests.delete(
            f"{SUPABASE_URL}/rest/v1/travas_envio",
            headers=supabase_headers(),
            params={
                "request_id": f"eq.{request_id}"
            },
            timeout=10
        )
    except requests.RequestException:
        print("FALHA AO LIBERAR TRAVA")

    return (
        "Não foi possível enviar a mensagem pelo WhatsApp.",
        500
    )

# =========================================================
# CENTRAL DE ATENDIMENTO
# =========================================================

@app.route("/atendimento/conversas", methods=["GET"])
def atendimento_conversas():
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

        if nome and nome != "Contato":
            contatos[telefone]["nome"] = nome

        contatos[telefone]["mensagens"].append(item)

    # Busca quando cada conversa foi visualizada
    visualizacoes = {}

    try:
        resposta = requests.get(
            f"{SUPABASE_URL}/rest/v1/conversas_visualizadas",
            headers=supabase_headers(),
            params={
                "select": "telefone,ultima_visualizacao"
            },
            timeout=15
        )

        if resposta.ok:
            for item in resposta.json():
                visualizacoes[item["telefone"]] = (
                    item.get("ultima_visualizacao")
                )

    except requests.RequestException:
        pass

    lista = ""

    # Mais recentes primeiro
    contatos_ordenados = sorted(
        contatos.values(),
        key=lambda c: (
            c["mensagens"][-1].get("created_at") or ""
            if c["mensagens"]
            else ""
        ),
        reverse=True
    )

    for contato in contatos_ordenados:
        telefone = contato["telefone"]
        nome = html.escape(contato["nome"])
        telefone_seguro = html.escape(telefone)

        ultima = contato["mensagens"][-1]

        ultima_texto = html.escape(
            (ultima.get("mensagem") or "")[:45]
        )

        ultima_visualizacao = visualizacoes.get(telefone)
        quantidade_novas = 0

        for mensagem_item in contato["mensagens"]:
            if mensagem_item.get("direcao") != "entrada":
                continue

            data_mensagem = (
                mensagem_item.get("created_at") or ""
            )

            if (
                not ultima_visualizacao
                or data_mensagem > ultima_visualizacao
            ):
                quantidade_novas += 1

        indicador = ""

        if quantidade_novas > 0:
            texto_contador = (
                "99+"
                if quantidade_novas > 99
                else str(quantidade_novas)
            )

            indicador = f"""
                <span style="
                    min-width:20px;
                    height:20px;
                    padding:0 6px;
                    border-radius:10px;
                    background:#16a34a;
                    color:white;
                    font-size:11px;
                    font-weight:700;
                    display:inline-flex;
                    align-items:center;
                    justify-content:center;
                ">
                    {texto_contador}
                </span>
            """

        peso = "700" if quantidade_novas > 0 else "600"

        lista += f"""
            <a class="contato"
               href="/atendimento?telefone={telefone_seguro}"
               style="position:relative;">
                <div class="avatar">
                    {nome[:1].upper()}
                </div>

                <div class="contato-info"
                     style="flex:1;">
                    <div style="
                        display:flex;
                        align-items:center;
                        gap:8px;
                    ">
                        <strong style="font-weight:{peso};">
                            {nome}
                        </strong>
                        {indicador}
                    </div>

                    <span style="font-weight:{peso};">
                        {ultima_texto}
                    </span>
                </div>
            </a>
        """

    return lista, 200

@app.route("/atendimento/visualizar", methods=["POST"])
def atendimento_visualizar():
    if not autenticado():
        return exigir_login()

    telefone = request.form.get("telefone", "").strip()

    if not telefone:
        return "Telefone obrigatório.", 400

    try:
        resposta = requests.post(
            f"{SUPABASE_URL}/rest/v1/conversas_visualizadas",
            headers={
                **supabase_headers(),
                "Prefer": "resolution=merge-duplicates,return=minimal"
            },
            json={
                "telefone": telefone,
                "ultima_visualizacao": datetime.now(
                    timezone.utc
                ).isoformat()
            },
            timeout=10
        )

        if not resposta.ok:
            return "Falha ao registrar visualização.", 500

    except requests.RequestException:
        return "Falha ao registrar visualização.", 500

    return "", 204

@app.route("/atendimento/mensagens", methods=["GET"])
def atendimento_mensagens():
    if not autenticado():
        return exigir_login()

    telefone = request.args.get("telefone", "").strip()

    if not telefone:
        return "", 400

    mensagens = buscar_mensagens()
    bolhas = ""

    for item in mensagens:
        if (item.get("telefone") or "") != telefone:
            continue

        texto = html.escape(
            item.get("mensagem") or ""
        )

        direcao = item.get("direcao")
        status = (item.get("status") or "").lower()
        criado_em = item.get("created_at") or ""

        horario = ""

        if criado_em:
            try:
                data_msg = datetime.fromisoformat(
                    criado_em.replace("Z", "+00:00")
                )

                horario = data_msg.astimezone(
                    timezone(timedelta(hours=-3))
                ).strftime("%H:%M")

            except (ValueError, TypeError):
                horario = ""

        classe = (
            "mensagem-balao saida"
            if direcao == "saida"
            else "mensagem-balao entrada"
        )

        status_texto = ""

        if direcao == "saida":
            if status == "read":
                status_texto = "✓✓ Lida"
            elif status == "delivered":
                status_texto = "✓✓ Entregue"
            elif status == "sent":
                status_texto = "✓ Enviada"
            elif status == "failed":
                status_texto = "⚠ Falhou"
            else:
                status_texto = "✓ Enviada"

        detalhes = horario

        if status_texto:
            detalhes = (
                f"{horario} · {status_texto}"
                if horario
                else status_texto
            )

        bolhas += f"""
        <div class="{classe}">
            <div>{texto}</div>
            <div class="mensagem-info">{detalhes}</div>
        </div>
        """

    return bolhas, 200      

@app.route("/respostas-rapidas", methods=["GET", "POST"])
def respostas_rapidas():
    if not autenticado():
        return exigir_login()

    if request.method == "POST":
        titulo = request.form.get("titulo", "").strip()
        mensagem = request.form.get("mensagem", "").strip()

        if not titulo or not mensagem:
            return "Título e mensagem são obrigatórios.", 400

        try:
            resposta = requests.post(
                f"{SUPABASE_URL}/rest/v1/respostas_rapidas",
                headers={
                    **supabase_headers(),
                    "Prefer": "return=minimal"
                },
                json={
                    "titulo": titulo,
                    "mensagem": mensagem,
                    "ativo": True
                },
                timeout=15
            )

            if not resposta.ok:
                return "Erro ao salvar resposta rápida.", 500

        except requests.RequestException:
            return "Erro ao salvar resposta rápida.", 500

        return redirect("/respostas-rapidas")

    try:
        resposta = requests.get(
            f"{SUPABASE_URL}/rest/v1/respostas_rapidas",
            headers=supabase_headers(),
            params={
                "select": "id,titulo,mensagem,ativo",
                "order": "titulo.asc"
            },
            timeout=15
        )

        respostas = resposta.json() if resposta.ok else []

    except requests.RequestException:
        respostas = []

    itens = ""

    for item in respostas:
        id_resposta = item.get("id")
        titulo = html.escape(item.get("titulo") or "")
        mensagem = html.escape(item.get("mensagem") or "")
        ativo = item.get("ativo") is True

        status = "Ativa" if ativo else "Desativada"

        itens += f"""
        <div style="
            background:white;
            padding:16px;
            margin-bottom:12px;
            border-radius:10px;
            border:1px solid #ddd;
        ">
            <strong>{titulo}</strong>
            <span style="
                font-size:12px;
                margin-left:8px;
                color:#666;
            ">
                {status}
            </span>

            <div style="
                margin-top:8px;
                white-space:pre-wrap;
            ">{mensagem}</div>

            <div style="
                margin-top:12px;
                display:flex;
                gap:8px;
            ">
                <a href="/respostas-rapidas/editar/{id_resposta}">
                    Editar
                </a>
                <form
    method="POST"
    action="/respostas-rapidas/status/{id_resposta}"
>
    <input
        type="hidden"
        name="ativo"
        value="{'false' if ativo else 'true'}"
    >

    <button type="submit">
        {'Desativar' if ativo else 'Ativar'}
    </button>
</form>

                <form
                    method="POST"
                    action="/respostas-rapidas/excluir/{id_resposta}"
                    onsubmit="return confirm('Excluir esta resposta?');"
                >
                    <button type="submit">
                        Excluir
                    </button>
                </form>
            </div>
        </div>
        """

    if not itens:
        itens = "<p>Nenhuma resposta rápida cadastrada.</p>"

    return render_template(
        "respostas_rapidas.html",
        itens=itens
    ), 200
    
@app.route(
    "/respostas-rapidas/excluir/<int:id_resposta>",
    methods=["POST"]
)
def excluir_resposta_rapida(id_resposta):
    if not autenticado():
        return exigir_login()

    try:
        resposta = requests.delete(
            f"{SUPABASE_URL}/rest/v1/respostas_rapidas",
            headers={
                **supabase_headers(),
                "Prefer": "return=minimal"
            },
            params={
                "id": f"eq.{id_resposta}"
            },
            timeout=15
        )

        if not resposta.ok:
            return "Erro ao excluir resposta.", 500

    except requests.RequestException:
        return "Erro ao excluir resposta.", 500

    return redirect("/respostas-rapidas")
@app.route(
    "/respostas-rapidas/editar/<int:id_resposta>",
    methods=["GET", "POST"]
)
def editar_resposta_rapida(id_resposta):
    if not autenticado():
        return exigir_login()

    if request.method == "POST":
        titulo = request.form.get("titulo", "").strip()
        mensagem = request.form.get("mensagem", "").strip()

        if not titulo or not mensagem:
            return "Título e mensagem são obrigatórios.", 400

        try:
            resposta = requests.patch(
                f"{SUPABASE_URL}/rest/v1/respostas_rapidas",
                headers={
                    **supabase_headers(),
                    "Prefer": "return=minimal"
                },
                params={
                    "id": f"eq.{id_resposta}"
                },
                json={
                    "titulo": titulo,
                    "mensagem": mensagem
                },
                timeout=15
            )

            if not resposta.ok:
                return "Erro ao atualizar resposta.", 500

        except requests.RequestException:
            return "Erro ao atualizar resposta.", 500

        return redirect("/respostas-rapidas")

    try:
        resposta = requests.get(
            f"{SUPABASE_URL}/rest/v1/respostas_rapidas",
            headers=supabase_headers(),
            params={
                "select": "id,titulo,mensagem",
                "id": f"eq.{id_resposta}",
                "limit": "1"
            },
            timeout=15
        )

        dados = resposta.json() if resposta.ok else []

    except requests.RequestException:
        dados = []

    if not dados:
        return "Resposta rápida não encontrada.", 404

    item = dados[0]

    titulo = html.escape(
        item.get("titulo") or "",
        quote=True
    )

    mensagem = html.escape(
        item.get("mensagem") or ""
    )

    return f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta
            name="viewport"
            content="width=device-width, initial-scale=1.0"
        >
        <title>Editar resposta - CMK</title>
    </head>

    <body style="
        font-family:Arial,sans-serif;
        background:#f3f4f6;
        padding:30px;
    ">
        <div style="
            max-width:700px;
            margin:auto;
            background:white;
            padding:25px;
            border-radius:10px;
        ">
            <h1>Editar resposta rápida</h1>

            <form method="POST">
                <label><strong>Nome da resposta</strong></label>

                <input
                    type="text"
                    name="titulo"
                    value="{titulo}"
                    required
                    style="
                        width:100%;
                        box-sizing:border-box;
                        padding:10px;
                        margin:8px 0 15px;
                    "
                >

                <label><strong>Mensagem</strong></label>

                <textarea
                    name="mensagem"
                    required
                    rows="8"
                    style="
                        width:100%;
                        box-sizing:border-box;
                        padding:10px;
                        margin:8px 0 15px;
                    "
                >{mensagem}</textarea>

                <button type="submit">
                    Salvar alterações
                </button>

                <a
                    href="/respostas-rapidas"
                    style="margin-left:12px;"
                >
                    Cancelar
                </a>
            </form>
        </div>
    </body>
    </html>
    """


@app.route(
    "/respostas-rapidas/status/<int:id_resposta>",
    methods=["POST"]
)
def status_resposta_rapida(id_resposta):
    if not autenticado():
        return exigir_login()

    novo_status = (
        request.form.get("ativo", "").lower() == "true"
    )

    try:
        resposta = requests.patch(
            f"{SUPABASE_URL}/rest/v1/respostas_rapidas",
            headers={
                **supabase_headers(),
                "Prefer": "return=minimal"
            },
            params={
                "id": f"eq.{id_resposta}"
            },
            json={
                "ativo": novo_status
            },
            timeout=15
        )

        if not resposta.ok:
            return "Erro ao alterar status.", 500

    except requests.RequestException:
        return "Erro ao alterar status.", 500

    return redirect("/respostas-rapidas")

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

            # Marca a conversa aberta como visualizada
    if telefone_ativo:
        try:
            requests.post(
                f"{SUPABASE_URL}/rest/v1/conversas_visualizadas",
                headers={
                    **supabase_headers(),
                    "Prefer": "resolution=merge-duplicates,return=minimal"
                },
                json={
                    "telefone": telefone_ativo,
                    "ultima_visualizacao": datetime.now(
                        timezone.utc
                    ).isoformat()
                },
                timeout=10
            )
        except requests.RequestException:
            print(
                "FALHA AO REGISTRAR VISUALIZACAO:",
                telefone_ativo
            )

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
        respostas_rapidas_html = ""

    try:
        resposta_rapidas = requests.get(
            f"{SUPABASE_URL}/rest/v1/respostas_rapidas",
            headers=supabase_headers(),
            params={
                "select": "id,titulo,mensagem",
                "ativo": "eq.true",
                "order": "titulo.asc"
            },
            timeout=15
        )

        respostas_ativas = (
            resposta_rapidas.json()
            if resposta_rapidas.ok
            else []
        )

    except requests.RequestException:
        respostas_ativas = []
    for resposta_item in respostas_ativas:
        titulo_rapido = html.escape(
            resposta_item.get("titulo") or ""
        )

        mensagem_rapida = html.escape(
            resposta_item.get("mensagem") or "",
            quote=True
        )

        respostas_rapidas_html += f"""
        <button
            type="button"
            class="botao-resposta-rapida"
            data-mensagem="{mensagem_rapida}"
            onclick="usarRespostaRapida(this)"
        >
            ⚡ {titulo_rapido}
        </button>
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
            status = (item.get("status") or "").lower()
            criado_em = item.get("created_at") or ""

            horario = ""

            if criado_em:
                try:
                    data_msg = datetime.fromisoformat(
                        criado_em.replace("Z", "+00:00")
                    )

                    horario = data_msg.astimezone(
                        timezone(timedelta(hours=-3))
                    ).strftime("%H:%M")

                except (ValueError, TypeError):
                    horario = ""

            classe = (
                "mensagem-balao saida"
                if direcao == "saida"
                else "mensagem-balao entrada"
            )

            status_texto = ""

            if direcao == "saida":
                if status == "read":
                    status_texto = "✓✓ Lida"
                elif status == "delivered":
                    status_texto = "✓✓ Entregue"
                elif status == "sent":
                    status_texto = "✓ Enviada"
                elif status == "failed":
                    status_texto = "⚠ Falhou"
                else:
                    status_texto = "✓ Enviada"

            detalhes = horario

            if status_texto:
                detalhes = (
                    f"{horario} · {status_texto}"
                    if horario
                    else status_texto
                )

            bolhas += f"""
            <div class="{classe}">
                <div>{texto}</div>
                <div class="mensagem-info">{detalhes}</div>
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
           onsubmit="enviarMensagemAjax(event, this); return false;"
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
            <input
                type="hidden"
                name="request_id"
                value=""
            >
           
                       <div class="respostas-rapidas">
                {respostas_rapidas_html}
            </div>
            
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

    return render_template(
        "atendimento.html",
        lista_contatos=lista_contatos,
        area_conversa=area_conversa
    ), 200

# =========================================================
# CAMPANHAS
# =========================================================

TEMPLATE_MARKETING = "cmk_curso_auxiliar_veterinaria"


def buscar_contatos_campanha():
    url = f"{SUPABASE_URL}/rest/v1/contatos_cmk"

    try:
        resposta = requests.get(
            url,
            headers=supabase_headers(),
            params={
                "select": "telefone,nome,autorizado,descadastrado,origem_autorizacao",
                "limit": "1000"
            },
            timeout=15
        )

        if not resposta.ok:
            print("ERRO CONTATOS:", resposta.status_code)
            return None

        return resposta.json()

    except requests.RequestException:
        print("ERRO CONEXAO CONTATOS")
        return None


def buscar_envios_campanha():
    url = f"{SUPABASE_URL}/rest/v1/envios_campanha"

    try:
        resposta = requests.get(
            url,
            headers=supabase_headers(),
            params={
                "select": "telefone,nome,template,status,status_at,erro",
                "order": "created_at.desc",
                "limit": "100"
            },
            timeout=15
        )

        if not resposta.ok:
            print("ERRO HISTORICO:", resposta.status_code)
            return []

        return resposta.json()

    except requests.RequestException:
        print("ERRO CONEXAO HISTORICO")
        return []


def enviar_template_marketing(numero):
    numero = "".join(c for c in numero if c.isdigit())

    if not numero:
        return 400, None

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
        "type": "template",
        "template": {
            "name": TEMPLATE_MARKETING,
            "language": {
                "code": "pt_BR"
            }
        }
    }

    try:
        resposta = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=15
        )

    except requests.RequestException:
        return 500, None

    message_id = None

    if resposta.ok:
        try:
            message_id = resposta.json()["messages"][0]["id"]
        except (KeyError, IndexError, TypeError):
            pass
    else:
        print(
            "ERRO TEMPLATE:",
            resposta.status_code,
            resposta.text[:500]
        )

    return resposta.status_code, message_id


def registrar_envio_campanha(
    telefone,
    nome,
    template,
    whatsapp_message_id,
    status="enviado"
):
    url = f"{SUPABASE_URL}/rest/v1/envios_campanha"

    dados = {
        "telefone": telefone,
        "nome": nome,
        "template": template,
        "whatsapp_message_id": whatsapp_message_id,
        "status": status,
        "status_at": datetime.now(timezone.utc).isoformat()
    }

    try:
        resposta = requests.post(
            url,
            headers={
                **supabase_headers(),
                "Prefer": "return=minimal"
            },
            json=dados,
            timeout=15
        )

        if not resposta.ok:
            print(
                "ERRO REGISTRO CAMPANHA:",
                resposta.status_code
            )

        return resposta.ok

    except requests.RequestException:
        print("FALHA AO REGISTRAR ENVIO DA CAMPANHA")
        return False


# =========================================================
# PAINEL DE CAMPANHAS
# =========================================================

@app.route("/campanhas", methods=["GET"])
def campanhas():
    if not autenticado():
        return exigir_login()

    contatos = buscar_contatos_campanha()
    envios = buscar_envios_campanha()

    if contatos is None:
        return "Não foi possível consultar os contatos.", 500

    unicos = {}

    for contato in contatos:
        numero = "".join(
            c for c in (contato.get("telefone") or "")
            if c.isdigit()
        )

        if numero:
            unicos[numero] = contato

    aptos = [
        (numero, contato)
        for numero, contato in unicos.items()
        if contato.get("autorizado") is True
        and contato.get("descadastrado") is not True
    ]

    ultimo_status = {}

    for envio in envios:
        numero = "".join(
            c for c in (envio.get("telefone") or "")
            if c.isdigit()
        )

        if numero and numero not in ultimo_status:
            ultimo_status[numero] = envio

    linhas = ""

    for numero, contato in list(unicos.items())[:100]:
        nome = html.escape(
            contato.get("nome") or "Sem nome"
        )

        numero_seguro = html.escape(numero)

        autorizado = (
            "Sim"
            if contato.get("autorizado") is True
            else "Não"
        )

        descadastrado = (
            "Sim"
            if contato.get("descadastrado") is True
            else "Não"
        )

        envio = ultimo_status.get(numero)

        if envio:
            status = html.escape(
                envio.get("status") or "-"
            )
        else:
            status = "Nunca enviado"

        if (
            contato.get("autorizado") is True
            and contato.get("descadastrado") is not True
        ):
            acao = (
                '<form method="POST" '
                'action="/campanhas/enviar-individual">'
                '<input type="hidden" name="telefone" value="'
                + numero_seguro +
                '">'
                '<button type="submit">Enviar</button>'
                '</form>'
            )
        else:
            acao = "Bloqueado"

        linhas += (
            "<tr>"
            f"<td>{nome}</td>"
            f"<td>{numero_seguro}</td>"
            f"<td>{autorizado}</td>"
            f"<td>{descadastrado}</td>"
            f"<td><strong>{status}</strong></td>"
            f"<td>{acao}</td>"
            "</tr>"
        )

        total_contatos = len(unicos)
        total_aptos = len(aptos)

        status_contagem = {
            "read": 0,
            "delivered": 0,
            "sent": 0,
            "failed": 0
        }

        processados = 0

        for numero in unicos:
            envio = ultimo_status.get(numero)

            if not envio:
                continue

            processados += 1
            status = (envio.get("status") or "").lower()

            if status in status_contagem:
                status_contagem[status] += 1

        restantes = max(total_aptos - processados, 0)

        resumo = (
            f"Total: {total_contatos} · "
            f"Processados: {processados} · "
            f"Lidos: {status_contagem['read']} · "
            f"Entregues: {status_contagem['delivered']} · "
            f"Enviados: {status_contagem['sent']} · "
            f"Falharam: {status_contagem['failed']} · "
            f"Restantes: {restantes}"
        )
    
    return render_template(
        "campanhas.html",
        resumo=resumo,
        linhas=linhas
    ), 200

# =========================================================
# ENVIO INDIVIDUAL
# =========================================================

@app.route("/campanhas/enviar-individual", methods=["POST"])
def campanha_enviar_individual():
    if not autenticado():
        return exigir_login()

    telefone = request.form.get("telefone", "").strip()

    telefone = "".join(
        c for c in telefone
        if c.isdigit()
    )

    if not telefone:
        return "Telefone inválido.", 400

    try:
        resposta_contato = requests.get(
            f"{SUPABASE_URL}/rest/v1/contatos_cmk",
            headers=supabase_headers(),
            params={
                "select": "telefone,nome,autorizado,descadastrado",
                "telefone": f"eq.{telefone}",
                "limit": "1"
            },
            timeout=15
        )

        if not resposta_contato.ok:
            return "Não foi possível validar o contato.", 500

        contatos = resposta_contato.json()

    except requests.RequestException:
        return "Não foi possível validar o contato.", 500

    if not contatos:
        return "Contato não encontrado.", 404

    contato = contatos[0]

    if contato.get("autorizado") is not True:
        return "Envio bloqueado: contato não autorizado.", 403

    if contato.get("descadastrado") is True:
        return "Envio bloqueado: contato descadastrado.", 403

    status, message_id = enviar_template_marketing(
        telefone
    )

    if 200 <= status < 300:
        registrar_envio_campanha(
            telefone=telefone,
            nome=contato.get("nome") or "",
            template=TEMPLATE_MARKETING,
            whatsapp_message_id=message_id,
            status="enviado"
        )

        return redirect("/campanhas")

    return "Não foi possível enviar o template.", 500


# =========================================================
# TESTE EM LOTE - MÁXIMO 5 CONTATOS
# =========================================================

@app.route("/campanhas/enviar-lote-teste", methods=["POST"])
def campanha_enviar_lote_teste():
    if not autenticado():
        return exigir_login()

    contatos = buscar_contatos_campanha()

    if contatos is None:
        return "Não foi possível consultar os contatos.", 500

    unicos = {}

    for contato in contatos:
        telefone = "".join(
            c for c in (contato.get("telefone") or "")
            if c.isdigit()
        )

        if telefone:
            unicos[telefone] = contato

    envios_anteriores = buscar_envios_campanha()

    telefones_ja_processados = set()

    for envio in envios_anteriores:
        telefone_envio = "".join(
            c for c in (envio.get("telefone") or "")
            if c.isdigit()
        )

        if telefone_envio:
            telefones_ja_processados.add(telefone_envio)

    aptos = [
        (telefone, contato)
        for telefone, contato in unicos.items()
        if contato.get("autorizado") is True
        and contato.get("descadastrado") is not True
        and telefone not in telefones_ja_processados
    ]

    enviados = 0
    falhas = 0

    for telefone, contato in aptos[:5]:
        status, message_id = enviar_template_marketing(
            telefone
        )

        if 200 <= status < 300:
            registrar_envio_campanha(
                telefone=telefone,
                nome=contato.get("nome") or "",
                template=TEMPLATE_MARKETING,
                whatsapp_message_id=message_id,
                status="enviado"
            )

            enviados += 1

        else:
            falhas += 1

    return (
        f"""
        <h2>Teste concluído</h2>
        <p>Envios aceitos pela API: {enviados}</p>
        <p>Falhas imediatas: {falhas}</p>
        <p><a href="/campanhas">Voltar para Campanhas</a></p>
        """,
        200
    )


# =========================================================
# TESTE INTERNO DO TEMPLATE
# =========================================================

@app.route("/teste-template", methods=["POST"])
def teste_template():
    if not autenticado():
        return exigir_login()

    if not TEST_PHONE:
        return "Número de teste não configurado.", 500

    status, _ = enviar_template_marketing(
        TEST_PHONE
    )

    if 200 <= status < 300:
        return "Template de teste enviado com sucesso!", 200

    return "Não foi possível enviar o template.", 500
