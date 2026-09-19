"""Dashboard independente do benchmark_providers.

Serve (stdlib apenas) um HTML moderno com cards por provider, destaque
positivo/negativo, sparkline SVG da latencia historica e auto-refresh.

Uso:
    python -m benchmark_providers.dashboard [--port 8787] [--host 127.0.0.1]
    python -m benchmark_providers.dashboard --once   # gera data/dashboard.html e sai
    python -m benchmark_providers.dashboard --run-probe --interval 3600  # bot + cron interno
"""
from __future__ import annotations

import html as _html
import json
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .probe_health import read_jsonl, aggregate, _now_iso, run as probe_run

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
    recs = read_jsonl(JSONL, hours=24)
    return {"generated_at": _now_iso(), "window_hours": 24, "providers": aggregate(recs)}


def _history(name: str, hours: int = 24, max_pts: int = 40) -> list[dict]:
    recs = read_jsonl(JSONL, hours=hours)
    mine = [r for r in recs if r.get("provider") == name]
    if len(mine) > max_pts:
        step = len(mine) / max_pts
        mine = [mine[int(i * step)] for i in range(max_pts)]
    return mine


def _sparkline_svg(series: list[dict], w: int = 220, h: int = 46) -> str:
    if not series:
        return ""
    lats = [r.get("latency_ms", 0) or 0 for r in series]
    lo, hi = min(lats), max(lats)
    span = (hi - lo) or 1
    n = len(series)
    pts = []
    dots = []
    for i, r in enumerate(series):
        x = round(i * (w - 4) / max(n - 1, 1) + 2, 1)
        y = round(h - 4 - (r.get("latency_ms", 0) - lo) * (h - 8) / span, 1)
        pts.append(f"{x},{y}")
        if not r.get("ok"):
            dots.append(f'<circle cx="{x}" cy="{y}" r="2.5" fill="#ef4444"/>')
        elif r.get("shed_detected"):
            dots.append(f'<circle cx="{x}" cy="{y}" r="2.5" fill="#f59e0b"/>')
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        f'<polyline fill="none" stroke="#3b82f6" stroke-width="1.6" '
        f'stroke-linejoin="round" stroke-linecap="round" points="{" ".join(pts)}"/>'
        + "".join(dots)
        + "</svg>"
    )


def _fmt(v, unit=""):
    if v is None:
        return '<span class="na">—</span>'
    if isinstance(v, float):
        v = round(v, 1)
    return f"{v}{unit}"


def _status_label(p: dict) -> tuple[str, str]:
    if not p.get("last_ok"):
        if p.get("last_status") in (429, 503) or p.get("shed_hits", 0) > 0:
            return ("bad", "Shed / Indisponível")
        return ("bad", "Falha")
    up = p.get("uptime_pct")
    if isinstance(up, (int, float)) and up >= 99:
        return ("ok", "Saudável")
    if isinstance(up, (int, float)) and up >= 90:
        return ("warn", "Intermitente")
    return ("warn", "Degradado")


def _card(name: str, p: dict, hist: list[dict]) -> str:
    cls, label = _status_label(p)
    icon = {"ok": "🟢", "warn": "🟡", "bad": "🔴"}[cls]
    spark = _sparkline_svg(hist)
    last_err = _html.escape(p.get("last_error") or "")[:120]
    last_ts = p.get("last_ts", "")
    return f"""
<article class="card {cls}">
  <header>
    <h3>{icon} {_html.escape(name)}</h3>
    <span class="pill {cls}">{label}</span>
  </header>
  <div class="kpis">
    <div class="kpi"><span class="k">Uptime 24h</span><span class="v">{_fmt(p.get('uptime_pct'), '%')}</span></div>
    <div class="kpi"><span class="k">P50</span><span class="v">{_fmt(p.get('p50_ms'), ' ms')}</span></div>
    <div class="kpi"><span class="k">P95</span><span class="v">{_fmt(p.get('p95_ms'), ' ms')}</span></div>
    <div class="kpi"><span class="k">P99</span><span class="v">{_fmt(p.get('p99_ms'), ' ms')}</span></div>
    <div class="kpi"><span class="k">TTFT P50</span><span class="v">{_fmt(p.get('ttft_p50_ms'), ' ms')}</span></div>
    <div class="kpi"><span class="k">TTFT P95</span><span class="v">{_fmt(p.get('ttft_p95_ms'), ' ms')}</span></div>
    <div class="kpi"><span class="k">Amostras</span><span class="v">{p.get('samples', 0)}</span></div>
    <div class="kpi"><span class="k">Shed hits</span><span class="v">{p.get('shed_hits', 0)}</span></div>
  </div>
  <div class="spark">{spark}</div>
  <footer>
    <span class="muted">últ. {last_ts} · HTTP {p.get('last_status') or '—'}</span>
    {f'<span class="err">{last_err}</span>' if last_err else ''}
  </footer>
</article>"""


_CSS = """
:root{--bg:#0b1020;--card:#131a2e;--card-border:#1f2948;--fg:#e6eaf3;--muted:#8a93ab;--accent:#3b82f6;--ok:#10b981;--warn:#f59e0b;--bad:#ef4444;}
*{box-sizing:border-box;}
html,body{margin:0;padding:0;}
body{font:14px/1.55 ui-sans-serif,system-ui,sans-serif;background:radial-gradient(1200px 600px at 20% -10%,rgba(59,130,246,.12),transparent 60%),var(--bg);color:var(--fg);min-height:100vh;padding:20px clamp(12px,4vw,40px);}
.wrap{max-width:1280px;margin:0 auto;}
header.top{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 16px;margin-bottom:18px;}
h1{font-size:22px;margin:0;letter-spacing:-.01em;}
.subtle{color:var(--muted);font-size:13px;}
.refresh{margin-left:auto;font-size:12px;color:var(--muted);}
.refresh b{color:var(--fg);}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:14px;}
.card{background:var(--card);border:1px solid var(--card-border);border-radius:14px;padding:14px 16px;box-shadow:0 2px 10px rgba(0,0,0,.25);transition:transform .15s ease,border-color .2s ease;border-top:3px solid var(--card-border);}
.card:hover{transform:translateY(-2px);}
.card.ok{border-top-color:var(--ok);}
.card.warn{border-top-color:var(--warn);}
.card.bad{border-top-color:var(--bad);}
.card header{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px;}
.card h3{margin:0;font-size:16px;font-weight:600;}
.pill{font-size:11px;font-weight:600;padding:3px 9px;border-radius:999px;letter-spacing:.02em;text-transform:uppercase;}
.pill.ok{background:rgba(16,185,129,.15);color:var(--ok);}
.pill.warn{background:rgba(245,158,11,.15);color:var(--warn);}
.pill.bad{background:rgba(239,68,68,.15);color:var(--bad);}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:8px 10px;margin-bottom:10px;}
.kpi{display:flex;flex-direction:column;min-width:0;}
.kpi .k{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;}
.kpi .v{font-size:14px;font-weight:600;font-variant-numeric:tabular-nums;}
.na{color:var(--muted);font-weight:400;}
.spark{padding:6px 0 2px;}
.spark svg{width:100%;height:46px;display:block;}
.card footer{display:flex;flex-direction:column;gap:4px;font-size:11px;color:var(--muted);border-top:1px dashed var(--card-border);padding-top:8px;margin-top:6px;}
.card footer .err{color:var(--bad);font-family:ui-monospace,monospace;}
footer.site-footer{margin:24px 0 6px;text-align:center;color:var(--muted);font-size:12px;}
footer.site-footer a{color:var(--muted);text-decoration:none;border-bottom:1px dotted var(--muted);}
footer.site-footer a:hover{color:var(--fg);}
@media(max-width:640px){.kpis{grid-template-columns:repeat(2,1fr);}h1{font-size:18px;}}
"""

_JS = """
(function(){
  var T0=Date.now();
  var EL=document.getElementById('elapsed');
  setInterval(function(){
    var s=Math.floor((Date.now()-T0)/1000); if(EL)EL.textContent=s+'s';
  },1000);
  // Pulse / heartbeat: fetch /json cada 30s; se falhar 3x, reload
  var FAILS=0;
  function ping(){
    fetch('/json',{cache:'no-store'})
      .then(function(r){return r.ok?r.json():null;})
      .then(function(p){if(p&&p.generated_at){FAILS=0;}})
      .catch(function(){FAILS+=1;if(FAILS>=3)location.reload();});
    setTimeout(ping,30000);
  }
  setTimeout(ping,30000);
  // Recarga completa a cada 2 min para garantir frescor (simpler que merge DOM)
  setTimeout(function(){location.reload();},120000);
})();
"""


def render_html(payload: dict) -> str:
    provs = payload.get("providers", {}) or {}
    cards = []
    for name in sorted(provs.keys()):
        hist = _history(name, hours=24)
        cards.append(_card(name, provs[name], hist))
    body_cards = "\n".join(cards) or "<p class='subtle'>Sem dados.</p>"
    gen = payload.get("generated_at", "—")
    win = payload.get("window_hours", 24)
    return f"""<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>benchmark_providers — saúde dos providers</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
<header class="top">
  <h1>🩺 benchmark_providers</h1>
  <span class="subtle">Gerado em <b>{_html.escape(str(gen))}</b> · janela de {win}h</span>
  <span class="refresh">auto-refresh 2 min · decorrido <b id="elapsed">0s</b></span>
</header>
<main class="grid">
{body_cards}
</main>
<footer class="site-footer">
  <a href="https://inovatudo.com" target="_blank" rel="noopener">inovatudo.com</a>
</footer>
</div>
<script>{_JS}</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a, **kw):
        return

    def do_GET(self):  # noqa: N802
        if self.path in ("/", "/index.html"):
            body = render_html(_load()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/json":
            body = json.dumps(_load(), ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)


def run_bot(interval_s: int = 3600, alert: bool = True):
    """Bot de verificação: roda probe + gera dashboard.html + dorme."""
    from .probe_health import run as probe_run  # já importado
    DATA.mkdir(parents=True, exist_ok=True)
    while True:
        print(f"[{_now_iso()}] bot: probe...")
        try:
            res = probe_run(
                config_path=ROOT / "scripts" / "probe_config.json",
                jsonl_path=JSONL,
                aggregate_path=AGG,
                alert=alert,
            )
        except Exception as exc:
            print(f"probe erro: {exc}")
        # Regenera HTML
        out = DATA / "dashboard.html"
        out.write_text(render_html(_load()), encoding="utf-8")
        print(f"[{_now_iso()}] bot: html atualizado -> {out}")
        time.sleep(interval_s)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--once", action="store_true", help="gera data/dashboard.html e sai")
    ap.add_argument("--run-probe", action="store_true", help="ativa bot com loop de probe + atualiza HTML")
    ap.add_argument("--interval", type=int, default=3600, help="segundos entre probes no bot (default 3600)")
    a = ap.parse_args(argv)
    if a.run_probe:
        print("Bot iniciado. Probe a cada %ds (Ctrl+C p/ sair)." % a.interval)
        run_bot(interval_s=a.interval, alert=True)
        return 0
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
