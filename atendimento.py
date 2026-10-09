from flask import Blueprint, request, render_template
import html
import requests
import uuid
import time
from datetime import datetime, timezone, timedelta


atendimento_bp = Blueprint(
    "atendimento",
    __name__
)


autenticado = None
exigir_login = None
buscar_mensagens = None
supabase_headers = None
SUPABASE_URL = None
enviar_mensagem = None
salvar_mensagem = None

cache_respostas_rapidas = {
    "dados": [],
    "atualizado_em": 0
}


def configurar_atendimento(dependencias):
    global autenticado, exigir_login, buscar_mensagens
    global supabase_headers, SUPABASE_URL
    global enviar_mensagem, salvar_mensagem

    autenticado = dependencias["autenticado"]
    exigir_login = dependencias["exigir_login"]
    buscar_mensagens = dependencias["buscar_mensagens"]
    supabase_headers = dependencias["supabase_headers"]
    SUPABASE_URL = dependencias["SUPABASE_URL"]
    enviar_mensagem = dependencias["enviar_mensagem"]
    salvar_mensagem = dependencias["salvar_mensagem"]

@atendimento_bp.route("/atendimento/mensagens", methods=["GET"])
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
        status_classe = ""

        if direcao == "saida":
            if status == "read":
                status_texto = "✓✓ Lida"
                status_classe = "status-lida"
            elif status == "delivered":
                status_texto = "✓✓ Entregue"
            elif status == "sent":
                status_texto = "✓ Enviada"
            elif status == "failed":
                status_texto = "⚠ Falhou"
                status_classe = "status-falha"
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
            <div class="mensagem-info {status_classe}">{detalhes}</div>
        </div>
        """

    return bolhas, 200

@atendimento_bp.route("/atendimento/conversas", methods=["GET"])
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

    status_conversas = {}

    try:
        resposta_status = requests.get(
            f"{SUPABASE_URL}/rest/v1/status_conversas",
            headers=supabase_headers(),
            params={"select": "telefone,status"},
            timeout=5
        )

        if resposta_status.ok:
            for item in resposta_status.json():
                telefone_status = item.get("telefone")
                status = item.get("status", "novo")

                if telefone_status:
                    status_conversas[telefone_status] = status

    except requests.RequestException:
        pass



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
                <span class="indicador-novo" style="
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

        horario_ultima = ""

        criado_ultima = ultima.get("created_at") or ""

        if criado_ultima:
            try:
                data_ultima = datetime.fromisoformat(
                    criado_ultima.replace("Z", "+00:00")
                )
                horario_ultima = data_ultima.astimezone(
                    timezone(timedelta(hours=-3))
                ).strftime("%H:%M")
            except (ValueError, TypeError):
                pass


        status_atual = status_conversas.get(
            telefone, "aguardando"
        )

        nomes_status = {
            "aguardando": "🟠 Aguardando",
            "em_atendimento": "🔵 Em atendimento",
            "finalizado": "🟢 Finalizado"
        }

        status_texto = nomes_status.get(
            status_atual, "🟠 Aguardando"
        )

        
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
                        <span style="margin-left:auto; font-size:11px; color:#667781; white-space:nowrap;">
                            {horario_ultima}
                        </span>
                    </div>

                    <small class="status-atendimento">
                        {status_texto}
                    </small>

                    <span style="font-weight:{peso};">
                        {ultima_texto}
                    </span>
                </div>
            </a>
        """

    return lista, 200
    
@atendimento_bp.route("/atendimento/visualizar", methods=["POST"])
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

@atendimento_bp.route("/atendimento/enviar", methods=["POST"])
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

@atendimento_bp.route("/atendimento", methods=["GET"])
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
        contato_mais_recente = max(
            contatos.values(),
            key=lambda c: (
                c["mensagens"][-1].get("created_at") or ""
                if c["mensagens"]
                else ""
            )
        )

        telefone_ativo = contato_mais_recente["telefone"]
            # Marca a conversa aberta como visualizada


    lista_contatos = ""
    status_validos = {
    "aguardando",
    "em_atendimento",
    "finalizado"
}


    status_conversas = {}

    try:
        resposta_status = requests.get(
            f"{SUPABASE_URL}/rest/v1/status_conversas",
            headers=supabase_headers(),
            params={"select": "telefone,status"},
            timeout=5
        )

        if resposta_status.ok:
            for item in resposta_status.json():
                telefone_status = item.get("telefone")
                status = item.get("status", "novo")

                if telefone_status:
                    status_conversas[telefone_status] = status

    except requests.RequestException:
        pass


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

        
        status_atual = status_conversas.get(
            telefone, "aguardando"
        )

        if status_atual not in status_validos:
            status_atual = "aguardando"

        nomes_status = {
            "aguardando": "🟠 Aguardando",
            "em_atendimento": "🔵 Em atendimento",
            "finalizado": "🟢 Finalizado"
        }

        status_texto = nomes_status[status_atual]

        lista_contatos += f"""
        <a class="{classe}"
           href="/atendimento?telefone={telefone_seguro}">
            <div class="avatar">
                {nome_seguro[:1].upper()}
            </div>

            <div class="contato-info">
                <strong>{nome_seguro}</strong>
                <small class="status-atendimento">{status_texto}</small>
                <span>{ultima_segura}</span>
            </div>
        </a>
        """
    respostas_rapidas_html = ""
    
    agora = time.monotonic()

    if agora - cache_respostas_rapidas["atualizado_em"] < 60:
        respostas_ativas = cache_respostas_rapidas["dados"]
    else:
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

            if resposta_rapidas.ok:
                respostas_ativas = resposta_rapidas.json()
                cache_respostas_rapidas["dados"] = respostas_ativas
                cache_respostas_rapidas["atualizado_em"] = agora
            else:
                respostas_ativas = cache_respostas_rapidas["dados"]

        except requests.RequestException:
            respostas_ativas = cache_respostas_rapidas["dados"]
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
            status_classe = ""

            if direcao == "saida":
                if status == "read":
                    status_texto = "✓✓ Lida"
                    status_classe = "status-lida"
                elif status == "delivered":
                    status_texto = "✓✓ Entregue"
                elif status == "sent":
                    status_texto = "✓ Enviada"
                elif status == "failed":
                    status_texto = "⚠ Falhou"
                    status_classe = "status-falha"
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
                <div class="mensagem-info {status_classe}">{detalhes}</div>
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
    if request.args.get("parcial") == "1":
        return area_conversa, 200
    return render_template(
        "atendimento.html",
        lista_contatos=lista_contatos,
        area_conversa=area_conversa
    ), 200
