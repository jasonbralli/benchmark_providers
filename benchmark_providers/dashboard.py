"""Dashboard independente do benchmark_providers.

Serve (stdlib apenas) um HTML com os indicadores 24h lidos de
data/provider_health.json + serie historica do jsonl.

Uso:
    python -m benchmark_providers.dashboard [--port 8787] [--host 127.0.0.1]
    python -m benchmark_providers.dashboard --once   # gera data/dashboard.html e sai
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .probe_health import read_jsonl, aggregate, _now_iso

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
JSONL = DATA / "provider_health.jsonl"
AGG = DATA / "provider_health.json"


def _load() -> dict:
    if AGG.exists():
        try:
            return json.loads(AGG.read_text(encoding="utf-8"))
        except Exception:
            pass
    # fallback: agrega do jsonl
    recs = read_jsonl(JSONL, hours=24)
    return {"generated_at": _now_iso(), "window_hours": 24, "providers": aggregate(recs)}


def render_html(payload: dict) -> str:
    provs = payload.get("providers", {}) or {}
    rows = []
    for name, p in sorted(provs.items()):
        uptime = p.get("uptime_pct")
        ok_badge = "🟢" if p.get("last_ok") else "🔴"
        uptime_str = f"{uptime:.1f}%" if isinstance(uptime, (int, float)) else "—"
        p50 = p.get("p50_ms"); p95 = p.get("p95_ms"); p99 = p.get("p99_ms")
        t50 = p.get("ttft_p50_ms"); t95 = p.get("ttft_p95_ms")
        rows.append(
            "<tr>"
            f"<td>{ok_badge} <b>{name}</b></td>"
            f"<td>{uptime_str}</td>"
            f"<td>{p.get('samples', 0)}</td>"
            f"<td>{p50 if p50 is not None else '—'}</td>"
            f"<td>{p95 if p95 is not None else '—'}</td>"
            f"<td>{p99 if p99 is not None else '—'}</td>"
            f"<td>{t50 if t50 is not None else '—'}</td>"
            f"<td>{t95 if t95 is not None else '—'}</td>"
            f"<td>{p.get('shed_hits', 0)}</td>"
            f"<td><code>{p.get('last_status') or ''}</code> {p.get('last_error') or ''}</td>"
            "</tr>"
        )
    body_rows = "\n".join(rows) or "<tr><td colspan=10><i>sem dados</i></td></tr>"
    gen = payload.get("generated_at", "—")
    win = payload.get("window_hours", 24)
    return f"""<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="300">
<title>benchmark_providers — health</title>
<style>
:root {{ --fg:#e5e7eb; --muted:#9ca3af; --accent:#3b82f6; --border:#374151; --card:#111827; }}
* {{ box-sizing: border-box; }}
body {{ font: 14px/1.5 ui-sans-serif, system-ui, sans-serif; background: transparent; color: var(--fg); margin: 0; padding: 16px; }}
h1 {{ font-size: 18px; margin: 0 0 4px; }}
.sub {{ color: var(--muted); font-size: 12px; margin-bottom: 12px; }}
table {{ border-collapse: collapse; width: 100%; background: var(--card); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
th, td {{ padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--border); }}
th {{ background: #0b1220; color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
tr:last-child td {{ border-bottom: none; }}
code {{ background: rgba(59,130,246,.15); padding: 1px 6px; border-radius: 4px; font-size: 12px; }}
footer.site-footer {{ margin-top: 16px; color: var(--muted); font-size: 12px; }}
footer.site-footer a {{ color: var(--muted); }}
</style></head>
<body>
<h1>🩺 benchmark_providers — saúde dos providers</h1>
<div class="sub">Gerado em {gen} · janela {win}h · auto-refresh 5min</div>
<table>
<thead><tr>
<th>Provider</th><th>Uptime</th><th>Amostras</th>
<th>P50 (ms)</th><th>P95 (ms)</th><th>P99 (ms)</th>
<th>TTFT P50</th><th>TTFT P95</th>
<th>Shed</th><th>Últ. status</th>
</tr></thead>
<tbody>
{body_rows}
</tbody>
</table>
<footer class="site-footer"><a href="https://inovatudo.com" target="_blank" rel="noopener">inovatudo.com</a></footer>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a, **kw):  # silencioso
        return

    def do_GET(self):  # noqa: N802
        if self.path in ("/", "/index.html"):
            body = render_html(_load()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/json":
            body = json.dumps(_load(), ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--once", action="store_true", help="gera data/dashboard.html e sai")
    a = ap.parse_args(argv)

    if a.once:
        out = DATA / "dashboard.html"
        out.write_text(render_html(_load()), encoding="utf-8")
        print(str(out))
        return 0

    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"dashboard em http://{a.host}:{a.port}/  (Ctrl+C p/ sair)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
