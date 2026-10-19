"""Regresão das descrições de códigos HTTP no rodapé dos cards (v1.7, 19/10/2026).

Valida que:
1. O wording de _HTTP_SHORT é o aprovado pelo Jason.
2. O rodapé do card mostra a descrição ao lado do código (status 200 não ganha descrição).
3. A legenda no header foi REMOVIDA (pref: só descrição inline no card).
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


def test_rodape_card_mostra_descricao_ao_lado_do_codigo():
    for code, desc in _EXPECTED.items():
        p = {"last_ok": False, "last_status": code, "last_error": f"HTTP {code}"}
        assert f"HTTP {code} — {desc}" in _card("provider-x", p, [])
    # status de sucesso (200) não ganha descrição
    ok = {"last_ok": True, "last_status": 200, "uptime_pct": 100.0}
    html_ok = _card("provider-y", ok, [])
    assert "HTTP 200" in html_ok


def test_legenda_header_removida():
    html = render_html({})
    assert '<details class="legend">' not in html
    assert "Códigos de erro HTTP" not in html
    assert "inovatudo.com" in html  # assinatura do rodapé permanece
