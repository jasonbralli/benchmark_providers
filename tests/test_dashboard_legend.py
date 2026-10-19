"""Regresão das descrições de códigos HTTP no rodapé dos cards (v1.8, 19/10/2026).

Valida que:
1. O wording de _HTTP_SHORT é o aprovado pelo Jason.
2. Rodapé do card: código + descrição na MESMA linha (span .muted = mesma cor/size),
   separados por espaço simples, SEM timestamp no card (info já vive no header).
3. Sem linha vermelha duplicando o código HTTP; erros de rede (não-HTTP) seguem visíveis.
4. A legenda no header foi REMOVIDA (pref: só descrição inline no card).
"""

from benchmark_providers.dashboard import _HTTP_SHORT, _card, render_html

_EXPECTED = {
    401: "credencial ausente ou inválida",
    402: "conta sem créditos/saldo",
    403: "key aceita, mas a conta não tem permissão",
    404: "modelo inexistente, renomeado ou fora do catálogo",
    410: "modelo descontinuado permanentemente",
    429: "quota de requisições excedida",
    503: "serviço sobrecarregado ou em manutenção",
}


def test_wording_dicionario_aprovado():
    assert _HTTP_SHORT == _EXPECTED


def test_rodape_card_codigo_e_descricao_na_mesma_linha():
    for code, desc in _EXPECTED.items():
        p = {"last_ok": False, "last_status": code, "last_error": f"HTTP {code}"}
        html = _card("provider-x", p, [])
        assert f'<span class="muted">HTTP {code} {desc}</span>' in html  # mesma linha, cor e size
        assert '<span class="err">' not in html  # sem duplicar o código em vermelho
    # status de sucesso (200) não ganha descrição
    ok = {"last_ok": True, "last_status": 200, "uptime_pct": 100.0}
    assert '<span class="muted">HTTP 200</span>' in _card("provider-y", ok, [])


def test_rodape_card_sem_timestamp_e_erro_rede_visivel():
    p = {"last_ok": False, "last_status": 401, "last_error": "HTTP 401"}
    html = _card("provider-x", p, [])
    assert "últ." not in html  # timestamp não se repete no card (já está no header)
    # erro de rede (sem status HTTP) continua visível no rodapé
    net = {"last_ok": False, "last_status": None, "last_error": "URLError: timeout"}
    html_net = _card("provider-z", net, [])
    assert "URLError: timeout" in html_net
    assert '<span class="err">' in html_net


def test_legenda_header_removida():
    html = render_html({})
    assert '<details class="legend">' not in html
    assert "Códigos de erro HTTP" not in html
    assert "inovatudo.com" in html  # assinatura do rodapé permanece
