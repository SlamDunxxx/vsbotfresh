from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def ensure_site(site_dir: Path) -> Path:
    site_dir.mkdir(parents=True, exist_ok=True)
    index_path = site_dir / "index.html"
    if index_path.exists():
        return index_path
    index_path.write_text(
        """<!doctype html>
<html lang=\"en\"> 
<head>
<meta charset=\"utf-8\" />
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
<title>VSBotFresh Observer</title>
<style>
:root { --bg:#0b1320; --panel:#111a2e; --line:#28405f; --text:#dbeafe; --muted:#93a4bf; --good:#10b981; --warn:#f59e0b; --bad:#ef4444; }
body { margin:0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; background:radial-gradient(circle at top, #16233f, #081021 60%); color:var(--text); }
main { max-width:1080px; margin:24px auto; padding:0 16px; }
section { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px; margin-bottom:14px; }
h1 { margin:0 0 14px; font-size:24px; }
.grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap:12px; }
.k { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:0.08em; }
.v { font-size:18px; margin-top:4px; }
.ok { color: var(--good); }
.warn { color: var(--warn); }
.bad { color: var(--bad); }
pre { white-space: pre-wrap; word-break: break-word; margin:0; }
</style>
</head>
<body>
<main>
  <h1>VSBotFresh Observer</h1>
  <section>
    <div class=\"grid\" id=\"stats\"></div>
  </section>
  <section>
    <div class=\"k\">Health Payload</div>
    <pre id=\"health\">loading...</pre>
  </section>
  <section>
    <div class=\"k\">Latest Summary</div>
    <pre id=\"summary\">loading...</pre>
  </section>
</main>
<script>
async function load() {
  const [h, s] = await Promise.all([
    fetch('/data/health.json').then(r => r.json()).catch(() => ({})),
    fetch('/data/latest_summary.json').then(r => r.json()).catch(() => ({})),
  ]);

  document.getElementById('health').textContent = JSON.stringify(h, null, 2);
  document.getElementById('summary').textContent = JSON.stringify(s, null, 2);

  const stats = [
    ['Mode', h.mode || 'unknown'],
    ['State', h.state || 'unknown'],
    ['Generation', String(h.generation ?? 0)],
    ['Active Policy', h.active_policy_id || 'none'],
    ['Sim Backend', h.sim_backend || 'python'],
    ['Autotune Mode', (h.autotune && h.autotune.mode) || 'off'],
    ['Autotune Action', (h.autotune && h.autotune.last_action) || 'none'],
    ['Autotune CPU', h.autotune && h.autotune.cpu_snapshot ? Number(h.autotune.cpu_snapshot.normalized_usage || 0).toFixed(3) : '0.000'],
    ['Workers', h.autotune && h.autotune.current_knobs ? String(h.autotune.current_knobs.max_parallel_workers ?? '-') : '-'],
    ['Safe Pause', String(Boolean(h.safe_pause))],
    ['Recoveries(30m)', String(h.recoveries_30m ?? 0)],
    ['Last Error', h.last_error || 'none'],
  ];
  const node = document.getElementById('stats');
  node.innerHTML = stats.map(([k,v]) => `<div><div class=\"k\">${k}</div><div class=\"v\">${v}</div></div>`).join('');
}
load();
setInterval(load, 2000);
</script>
</body>
</html>
""",
        encoding="utf-8",
    )
    return index_path


def write_daily_summary(summary_dir: Path, payload: dict[str, Any], *, date_override: str | None = None) -> Path:
    summary_dir.mkdir(parents=True, exist_ok=True)
    day = date_override or datetime.now().strftime("%Y-%m-%d")
    path = summary_dir / f"{day}.json"
    write_json(path, payload)
    return path
