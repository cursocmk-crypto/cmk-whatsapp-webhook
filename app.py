
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

def buscar_contatos_campanha():
    """Consulta apenas campos necessários; não expõe credenciais no navegador."""
    url = f"{SUPABASE_URL}/rest/v1/contatos_cmk"
    try:
        resposta = requests.get(
            url,
            headers=supabase_headers(),
            params={"select": "telefone,nome,autorizado,descadastrado,origem_autorizacao", "limit": "1000"},
            timeout=15,
        )
        if not resposta.ok:
            print("ERRO CONTATOS:", resposta.status_code)
            return None
        return resposta.json()
    except requests.RequestException as erro:
        print("ERRO CONEXAO CONTATOS:", type(erro).__name__)
        return None


@app.route("/campanhas", methods=["GET"])
def campanhas():
    if not autenticado():
        return exigir_login()

    contatos = buscar_contatos_campanha()
    if contatos is None:
        resumo = "Não foi possível consultar os contatos. Verifique as permissões no Supabase."
        linhas = ""
    else:
        unicos = {}
        for contato in contatos:
            telefone = "".join(c for c in (contato.get("telefone") or "") if c.isdigit())
            if telefone:
                unicos[telefone] = contato
        aptos = [c for c in unicos.values() if c.get("autorizado") is True and c.get("descadastrado") is not True]
        resumo = f"{len(unicos)} contatos únicos cadastrados · {len(aptos)} marcados como autorizados e ativos"
        linhas = "".join(
            "<tr><td>" + html.escape(c.get("nome") or "Sem nome") +
            "</td><td>" + html.escape(numero) +
            "</td><td>" + ("Sim" if c.get("autorizado") is True else "Não") +
            "</td><td>" + ("Sim" if c.get("descadastrado") is True else "Não") +
            "</td></tr>"
            for numero, c in list(unicos.items())[:100]
        )

    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CMK · Campanhas</title>
<style>
body{{font-family:Arial,sans-serif;background:#f3f4f6;color:#111827;margin:0}}
header{{background:#111827;color:white;padding:22px}}
main{{max-width:1000px;margin:30px auto;background:white;padding:26px;border-radius:12px}}
a{{color:#124c84}} .aviso{{background:#fff3ce;padding:18px;border-radius:9px;margin:20px 0}}
table{{border-collapse:collapse;width:100%}}td,th{{padding:11px;text-align:left;border-bottom:1px solid #ddd}}
.tabela{{overflow-x:auto}}@media(max-width:600px){{main{{margin:8px;padding:14px}}}}
</style></head><body><header><h2>CMK · Campanhas</h2></header>
<main><a href="/atendimento">← Voltar ao atendimento</a>
<h1>Contatos da campanha</h1><p>{html.escape(resumo)}</p>
<div class="aviso"><strong>Disparos ainda desativados.</strong><br>
Aguardamos a aprovação do modelo de Marketing pela Meta. Antes de enviar, vamos validar
as autorizações, registrar os envios e testar o descadastro.</div>
<h2>Prévia dos contatos (até 100)</h2>
<div class="tabela"><table><thead><tr><th>Nome</th><th>Telefone</th><th>Autorizado</th><th>Descadastrado</th></tr></thead>
<tbody>{linhas}</tbody></table></div>
</main></body></html>""", 200
