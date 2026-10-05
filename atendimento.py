from flask import Blueprint, request, render_template
import html
from datetime import datetime, timezone, timedelta


atendimento_bp = Blueprint(
    "atendimento",
    __name__
)


autenticado = None
exigir_login = None
buscar_mensagens = None


def configurar_atendimento(dependencias):
    global autenticado, exigir_login, buscar_mensagens

    autenticado = dependencias["autenticado"]
    exigir_login = dependencias["exigir_login"]
    buscar_mensagens = dependencias["buscar_mensagens"]


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
