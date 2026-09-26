import os
import html
import secrets
from datetime import datetime, timezone
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
