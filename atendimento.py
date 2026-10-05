from flask import Blueprint, request, render_template
import html
import requests
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


def configurar_atendimento(dependencias):
    global autenticado, exigir_login, buscar_mensagens
    global supabase_headers, SUPABASE_URL

    autenticado = dependencias["autenticado"]
    exigir_login = dependencias["exigir_login"]
    buscar_mensagens = dependencias["buscar_mensagens"]
    supabase_headers = dependencias["supabase_headers"]
    SUPABASE_URL = dependencias["SUPABASE_URL"]


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
