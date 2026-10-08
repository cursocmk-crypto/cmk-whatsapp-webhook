function usarRespostaRapida(botao) {
    const textarea = document.querySelector(
        'textarea[name="mensagem"]'
    );

    if (!textarea) {
        return;
    }

    const mensagem = botao.dataset.mensagem || '';

    textarea.value = mensagem;
    textarea.focus();

    textarea.setSelectionRange(
        textarea.value.length,
        textarea.value.length
    );
}


async function enviarMensagemAjax(event, form) {
    event.preventDefault();

    const botao = form.querySelector('button[type="submit"]');
    const textarea = form.querySelector('textarea[name="mensagem"]');
    const historico = document.querySelector('.historico');
    const requestIdInput = form.querySelector('input[name="request_id"]');

    if (form.dataset.enviando === '1') {
        return false;
    }

    const mensagem = textarea.value.trim();

    if (!mensagem) {
        return false;
    }

    if (!requestIdInput.value) {
        requestIdInput.value = crypto.randomUUID();
    }

    form.dataset.enviando = '1';

    botao.disabled = true;
    botao.innerText = 'Enviando...';

    try {
        const resposta = await fetch(form.action, {
            method: 'POST',
            body: new FormData(form)
        });

        if (!resposta.ok) {
            throw new Error('Falha no envio');
        }

        const balao = document.createElement('div');
        balao.className = 'mensagem-balao saida';
        balao.textContent = mensagem;

        if (historico) {
            historico.appendChild(balao);
            historico.scrollTop = historico.scrollHeight;
        }

        textarea.value = '';
        requestIdInput.value = '';

    } catch (erro) {
        alert('Não foi possível enviar a mensagem. Tente novamente.');

    } finally {
        form.dataset.enviando = '0';
        botao.disabled = false;
        botao.innerText = 'Enviar';
        textarea.focus();
    }

    return false;
}


async function atualizarConversa() {
    const historico = document.querySelector('.historico');

    const telefoneInput = document.querySelector(
        'input[name="telefone"]'
    );

    if (!historico || !telefoneInput) {
        return;
    }

    const telefone = telefoneInput.value;

    try {
        const resposta = await fetch(
            '/atendimento/mensagens?telefone=' +
            encodeURIComponent(telefone)
        );

        if (!resposta.ok) {
            return;
        }

        const htmlNovo = await resposta.text();

        // Primeira leitura: abre nas mensagens mais recentes
        if (!historico.dataset.inicializado) {
            historico.dataset.inicializado = '1';
            historico.dataset.htmlAnterior = htmlNovo;

            historico.innerHTML = htmlNovo;

            requestAnimationFrame(() => {
                historico.scrollTop = historico.scrollHeight;
            });

            return;
        }

        const htmlAnterior =
            historico.dataset.htmlAnterior || historico.innerHTML;

        if (htmlAnterior !== htmlNovo) {
            const tempAnterior = document.createElement('div');
            tempAnterior.innerHTML = htmlAnterior;

            const tempNovo = document.createElement('div');
            tempNovo.innerHTML = htmlNovo;

            const qtdAnterior =
                tempAnterior.querySelectorAll('.mensagem-balao').length;

            const qtdNova =
                tempNovo.querySelectorAll('.mensagem-balao').length;

            const chegouMensagemNova = qtdNova > qtdAnterior;

            historico.innerHTML = htmlNovo;
            historico.dataset.htmlAnterior = htmlNovo;

            if (chegouMensagemNova) {
                const mensagens =
                    historico.querySelectorAll('.mensagem-balao');

                const ultimaMensagem =
                    mensagens[mensagens.length - 1];

                if (
                    ultimaMensagem &&
                    ultimaMensagem.classList.contains('entrada')
                ) {
                    const dadosVisualizacao = new FormData();

                    dadosVisualizacao.append(
                        'telefone',
                        telefone
                    );

                    fetch('/atendimento/visualizar', {
                        method: 'POST',
                        body: dadosVisualizacao
                    }).catch(() => {
                        console.log(
                            'Falha ao marcar conversa como visualizada'
                        );
                    });

                    const aviso = document.createElement('div');

                    aviso.textContent = '● Mensagem nova';

                    aviso.style.cssText = `
                        text-align:center;
                        font-size:12px;
                        font-weight:700;
                        margin:14px 0 8px 0;
                        color:#16a34a;
                        border-bottom:1px solid #d1d5db;
                        line-height:1px;
                    `;

                    ultimaMensagem.parentNode.insertBefore(
                        aviso,
                        ultimaMensagem
                    );

                    try {
                        const audioContext =
                            new (
                                window.AudioContext ||
                                window.webkitAudioContext
                            )();

                        const oscillator =
                            audioContext.createOscillator();

                        const gain =
                            audioContext.createGain();

                        oscillator.connect(gain);
                        gain.connect(audioContext.destination);

                        oscillator.frequency.value = 720;
                        gain.gain.value = 0.08;

                        oscillator.start();

                        setTimeout(() => {
                            oscillator.stop();
                            audioContext.close();
                        }, 130);

                    } catch (erroSom) {
                        console.log(
                            'Som bloqueado pelo navegador'
                        );
                    }

                    historico.scrollTop =
                        historico.scrollHeight;
                }
            }
        }

    } catch (erro) {
        console.log('Falha ao atualizar conversa');
    }
}


async function atualizarListaConversas() {
    try {
        const resposta = await fetch(
            '/atendimento/conversas'
        );

        if (!resposta.ok) {
            return;
        }

        const htmlNovo = await resposta.text();

        const lista =
            document.querySelector('.lista-contatos');

        if (!lista) {
            return;
        }

        const listaTemporaria = document.createElement('div');
listaTemporaria.innerHTML = htmlNovo;

const contatosAtuais = [...lista.querySelectorAll('.contato')];
const contatosNovos = [...listaTemporaria.querySelectorAll('.contato')];

const mudou = contatosAtuais.length !== contatosNovos.length ||
    contatosAtuais.some((atual, i) =>
        atual.outerHTML !== contatosNovos[i]?.outerHTML
    );

if (mudou) {
    lista.replaceChildren(...contatosNovos);
}
        aplicarFiltroConversas();
        destacarConversaAtiva();

    } catch (erro) {
        console.log(
            'Falha ao atualizar lista de conversas'
        );
    }
}

let filtroAtual = 'todas';

function aplicarFiltroConversas() {
    const contatos = document.querySelectorAll('.lista-contatos .contato');

    contatos.forEach(contato => {
        const temMensagemNova = !!contato.querySelector('.indicador-novo');
        contato.style.display =
            filtroAtual === 'todas' || temMensagemNova ? '' : 'none';
    });
}

document.querySelectorAll('.filtro').forEach(botao => {
    botao.addEventListener('click', () => {
        filtroAtual = botao.dataset.filtro;

        document.querySelectorAll('.filtro').forEach(item => {
            item.classList.toggle('ativo', item === botao);
        });

        aplicarFiltroConversas();
    });
});

function destacarConversaAtiva() {
    const telefoneAtivo = new URLSearchParams(
        window.location.search
    ).get('telefone');

    document.querySelectorAll('.lista-contatos a.contato')
        .forEach(contato => {
            const telefone = new URL(
                contato.href
            ).searchParams.get('telefone');

            contato.classList.toggle(
                'ativo',
                telefone === telefoneAtivo
            );
        });
}

function irParaUltimaMensagem() {
    const historico = document.querySelector('.historico');

    if (!historico) {
        return;
    }

    requestAnimationFrame(() => {
        historico.scrollTop = historico.scrollHeight;

        setTimeout(() => {
            historico.scrollTop = historico.scrollHeight;
        }, 100);
    });
}

document.addEventListener(
    'DOMContentLoaded',
    irParaUltimaMensagem
);

setInterval(atualizarConversa, 2000);
setInterval(atualizarListaConversas, 2000);


// Troca de conversa sem recarregar a página
document.addEventListener('click', async function(evento) {
    const contato = evento.target.closest('.lista-contatos a.contato');

    if (!contato) return;

    evento.preventDefault();

    const destino = new URL(contato.href);
    const telefone = destino.searchParams.get('telefone');

    if (!telefone) return;
    window.conversaSolicitada = telefone;
    try {
        const resposta = await fetch(
            '/atendimento?telefone=' +
            encodeURIComponent(telefone) +
            '&parcial=1'
        );

        if (!resposta.ok) {
            window.location.href = contato.href;
            return;
        }

        const html = await resposta.text();
        const painel = document.querySelector('.painel');

        if (!painel) return;

       if (window.conversaSolicitada !== telefone) {
    return;
}
        
        painel.innerHTML = html;
        // Registra a visualização sem atrasar a abertura da conversa
        const dadosVisualizacao = new URLSearchParams();
        dadosVisualizacao.append('telefone', telefone);

        fetch('/atendimento/visualizar', {
            method: 'POST',
            body: dadosVisualizacao
        }).catch(erro => {
            console.error('Erro ao registrar visualização:', erro);
        });

        document.querySelectorAll('.lista-contatos a.contato')
            .forEach(item => {
                item.classList.toggle(
                    'ativo',
                    item.href === contato.href
                );
            });

        history.pushState({}, '', contato.href);

        const historico = painel.querySelector('.historico');

        if (historico) {
            historico.scrollTop = historico.scrollHeight;
        }

    } catch (erro) {
        console.error('Erro ao abrir conversa:', erro);
        window.location.href = contato.href;
    }
});

