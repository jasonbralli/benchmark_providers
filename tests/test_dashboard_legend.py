"""Regresão da legenda de códigos HTTP do dashboard (v1.6, 19/10/2026).

Valida que:
1. render_html embute a legenda com todos os códigos de _HTTP_LONG.
2. O rodapé do card mostra a descrição curta ao lado do código (ex.: HTTP 401 — credencial ausente/inválida).
"""

from benchmark_providers.dashboard import _HTTP_LONG, _HTTP_SHORT, _card, render_html


def test_legenda_contem_todos_os_codigos():
    html = render_html({})
    assert '<details class="legend">' in html
    for code, desc in _HTTP_LONG.items():
        assert f"<b>HTTP {code}</b>" in html
        assert desc in html


def test_rodape_card_mostra_descricao_curta():
    p = {"last_ok": False, "last_status": 401, "last_error": "HTTP 401"}
    html = _card("provider-x", p, [])
    assert f"HTTP 401 — {_HTTP_SHORT[401]}" in html
    # status desconhecido (200) não ganha descrição
    ok = {"last_ok": True, "last_status": 200, "uptime_pct": 100.0}
    html_ok = _card("provider-y", ok, [])
    assert "HTTP 200" in html_ok and " — " not in html_ok.split("HTTP 200")[1].split("<")[0]
