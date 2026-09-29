"""Dashboard runtime 6 panel, đọc data/logs.jsonl theo contract config/dashboard.yaml.

    python scripts/dashboard.py                 # http://127.0.0.1:8050, tự refresh
    python scripts/dashboard.py --once out.html # ghi một bản HTML tĩnh
    http://127.0.0.1:8050/?minutes=5            # zoom khi điều tra; mặc định theo contract (60)

Mọi số liệu được tính lại từ log mỗi lần tải trang; tiêu đề, đơn vị, time range,
refresh và threshold lấy từ contract để dashboard không lệch khỏi config.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from pathlib import Path
from statistics import mean
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.metrics import percentile

LOG_PATH = REPO_ROOT / "data" / "logs.jsonl"
CONFIG_PATH = REPO_ROOT / "config" / "dashboard.yaml"
SLO_PATH = REPO_ROOT / "config" / "slo.yaml"
COLORS = ["#2563eb", "#d97706", "#dc2626", "#059669"]
OPERATORS = {"lte": ("≤", lambda v, t: v <= t), "gte": ("≥", lambda v, t: v >= t)}
# Aggregations measured per minute, so the threshold can be drawn as a line on the chart.
PER_MINUTE_AGGREGATIONS = {"p95", "rate_per_minute", "error_rate_pct", "mean"}


def load_config(path: Path = CONFIG_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["dashboard"]


def load_slo_latency_ms(path: Path = SLO_PATH) -> float | None:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))["primary_slo"]["sli"]["latency_threshold_ms"]
    except (OSError, KeyError, TypeError):
        return None


def load_records(path: Path, since: datetime) -> list[dict]:
    records: list[dict] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
            ts = datetime.fromisoformat(record["ts"])
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        if ts >= since:
            record["_ts"] = ts
            records.append(record)
    return records


def _minute(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


def _pct(part: int, whole: int) -> float | None:
    return round(part / whole * 100, 2) if whole else None


def compute_panels(records: list[dict], now: datetime, minutes: int) -> dict[str, dict]:
    """Per-minute series and window-level stats for the six contract panels."""
    start = _minute(now - timedelta(minutes=minutes))
    buckets = [start + timedelta(minutes=i) for i in range(minutes + 1)]

    def select(event: str) -> list[dict]:
        return [r for r in records if r.get("event") == event]

    def group(rows: list[dict]) -> dict[datetime, list[dict]]:
        grouped: dict[datetime, list[dict]] = defaultdict(list)
        for row in rows:
            grouped[_minute(row["_ts"])].append(row)
        return grouped

    def series(rows: list[dict], fn, empty: Any = None) -> list:
        grouped = group(rows)
        return [fn(grouped[b]) if grouped.get(b) else empty for b in buckets]

    sent, received, failed = select("response_sent"), select("request_received"), select("request_failed")
    tool_rows = [r for r in records if r.get("tool_success") is not None]

    def lat(rows: list[dict], p: int, field: str = "latency_ms") -> float:
        return percentile([r[field] for r in rows if field in r], p)

    def tool_rate(rows: list[dict]) -> float | None:
        return _pct(sum(1 for r in rows if r["tool_success"] is True), len(rows))

    received_by_minute, failed_by_minute = group(received), group(failed)
    error_series = [
        _pct(len(failed_by_minute.get(b, [])), len(received_by_minute[b]))
        if received_by_minute.get(b)
        else None
        for b in buckets
    ]
    first_request = min((r["_ts"] for r in received), default=None)
    active_minutes = max(1.0, (now - first_request).total_seconds() / 60) if first_request else 1.0

    return {
        "latency": {
            "series": {
                "p50": series(sent, lambda rows: lat(rows, 50)),
                "p95": series(sent, lambda rows: lat(rows, 95)),
                "p99": series(sent, lambda rows: lat(rows, 99)),
                "ttft_p95": series(sent, lambda rows: lat(rows, 95, "ttft_ms")),
            },
            "stats": {
                "p50": lat(sent, 50),
                "p95": lat(sent, 95),
                "p99": lat(sent, 99),
                "ttft_p95": lat(sent, 95, "ttft_ms"),
            },
        },
        "traffic": {
            "series": {"requests/min": series(received, len, empty=0)},
            "stats": {
                "count": len(received),
                "rate_per_minute": round(len(received) / active_minutes, 2),
            },
        },
        "errors": {
            "series": {
                "error_rate_pct": error_series,
                "tool_success_rate_pct": series(tool_rows, tool_rate),
            },
            "stats": {
                "error_rate_pct": _pct(len(failed), len(received)) or 0.0,
                "tool_success_rate_pct": tool_rate(tool_rows) if tool_rows else None,
                "count_by_value": dict(
                    sorted(
                        {
                            k: sum(1 for r in failed if r.get("error_type") == k)
                            for k in {r.get("error_type") for r in failed}
                        }.items()
                    )
                ),
            },
        },
        "cost": {
            "series": {"usd/min": series(sent, lambda rows: round(sum(r["cost_usd"] for r in rows), 6))},
            "stats": {
                "total": round(sum(r["cost_usd"] for r in sent), 6),
                "sum_by_minute": max((v for v in series(sent, lambda rows: sum(r["cost_usd"] for r in rows)) if v), default=0.0),
            },
        },
        "tokens": {
            "series": {
                "tokens_in/min": series(sent, lambda rows: sum(r["tokens_in"] for r in rows)),
                "tokens_out/min": series(sent, lambda rows: sum(r["tokens_out"] for r in rows)),
            },
            "stats": {
                "sum_by_field": {
                    "tokens_in": sum(r["tokens_in"] for r in sent),
                    "tokens_out": sum(r["tokens_out"] for r in sent),
                },
            },
        },
        "quality": {
            "series": {"mean": series(sent, lambda rows: round(mean(r["quality_score"] for r in rows), 3))},
            "stats": {"mean": round(mean(r["quality_score"] for r in sent), 3) if sent else None},
        },
        "_buckets": buckets,
    }


def threshold_status(panel: dict, stats: dict) -> tuple[str, bool | None]:
    threshold = panel["threshold"]
    symbol, check = OPERATORS[threshold["operator"]]
    value = stats.get(threshold["aggregation"])
    label = f"{threshold['aggregation']} {symbol} {threshold['value']} {panel['unit']}"
    if value is None:
        return label, None
    if isinstance(value, dict):
        return label, all(check(v, threshold["value"]) for v in value.values())
    return label, check(value, threshold["value"])


def _fmt(value: Any) -> str:
    if value is None:
        return "–"
    if isinstance(value, float):
        return f"{value:,.6f}".rstrip("0").rstrip(".") if value < 1 else f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, dict):
        return ", ".join(f"{k}={_fmt(v)}" for k, v in value.items()) or "none"
    return f"{value:,}"


def render_chart(
    series: dict[str, list],
    buckets: list[datetime],
    unit: str,
    threshold: float | None,
    slo_line: float | None = None,
) -> str:
    width, height, left, right, top, bottom = 560, 200, 58, 12, 24, 26
    values = [v for vals in series.values() for v in vals if v is not None]
    lines = [v for v in (threshold, slo_line) if v is not None]
    y_max = max(values + lines + [0]) * 1.15 or 1
    inner_w, inner_h = width - left - right, height - top - bottom

    def x(i: int) -> float:
        return left + inner_w * i / max(1, len(buckets) - 1)

    def y(v: float) -> float:
        return top + inner_h * (1 - v / y_max)

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="chart">',
        f'<line x1="{left}" y1="{top + inner_h}" x2="{width - right}" y2="{top + inner_h}" class="axis"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + inner_h}" class="axis"/>',
        f'<text x="{left - 6}" y="{top + 10}" text-anchor="end">{_fmt(round(y_max, 4))}</text>',
        f'<text x="{left - 6}" y="{top + inner_h}" text-anchor="end">0</text>',
        f'<text x="{left}" y="10" class="unit">{html.escape(unit)}</text>',
    ]
    for i in (0, len(buckets) // 2, len(buckets) - 1):
        label = buckets[i].astimezone().strftime("%H:%M")
        parts.append(f'<text x="{x(i)}" y="{height - 6}" text-anchor="middle">{label}</text>')
    if threshold is not None:
        parts.append(
            f'<line x1="{left}" y1="{y(threshold)}" x2="{width - right}" y2="{y(threshold)}" class="threshold"/>'
            f'<text x="{width - right}" y="{y(threshold) - 4}" text-anchor="end" class="threshold-label">threshold {_fmt(threshold)}</text>'
        )
    if slo_line is not None:
        parts.append(
            f'<line x1="{left}" y1="{y(slo_line)}" x2="{width - right}" y2="{y(slo_line)}" class="slo"/>'
            f'<text x="{left + 4}" y="{y(slo_line) - 4}" class="slo-label">SLO {_fmt(slo_line)}</text>'
        )
    for color, (name, vals) in zip(COLORS, series.items()):
        segment: list[str] = []
        segments: list[list[str]] = []
        for i, v in enumerate(vals):
            if v is None:
                if segment:
                    segments.append(segment)
                segment = []
                continue
            segment.append(f"{x(i):.1f},{y(v):.1f}")
            parts.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="2.6" fill="{color}"><title>{name}: {_fmt(v)}</title></circle>')
        if segment:
            segments.append(segment)
        for seg in segments:
            if len(seg) > 1:
                parts.append(f'<polyline points="{" ".join(seg)}" fill="none" stroke="{color}" stroke-width="1.8"/>')
    parts.append("</svg>")
    legend = "".join(
        f'<span><i style="background:{c}"></i>{html.escape(n)}</span>' for c, n in zip(COLORS, series)
    )
    return f'<div class="legend">{legend}</div>' + "".join(parts)


def render_html(
    config: dict,
    computed: dict,
    now: datetime,
    record_count: int,
    slo_latency_ms: float | None = None,
    minutes: int | None = None,
) -> str:
    default_minutes = config["time_range_minutes"]
    minutes = minutes or default_minutes
    zoom_note = "" if minutes == default_minutes else f" · <b>zoom</b> (mặc định {default_minutes} min)"
    local_now = now.astimezone()
    offset = f"{local_now:%z}"
    window = f"{local_now - timedelta(minutes=minutes):%H:%M} → {local_now:%H:%M}, UTC{offset[:3]}:{offset[3:]}"
    cards = []
    for panel in config["panels"]:
        data = computed[panel["id"]]
        label, ok = threshold_status(panel, data["stats"])
        state = "ok" if ok else ("breach" if ok is False else "nodata")
        badge = {"ok": "OK", "breach": "BREACH", "nodata": "NO DATA"}[state]
        agg = panel["threshold"]["aggregation"]
        line = panel["threshold"]["value"] if agg in PER_MINUTE_AGGREGATIONS else None
        stats = "".join(
            f"<div><dt>{html.escape(k)}</dt><dd>{html.escape(_fmt(v))}</dd></div>" for k, v in data["stats"].items()
        )
        slo_line = slo_latency_ms if panel["id"] == "latency" else None
        slo_note = f" · SLO: <b>latency ≤ {_fmt(slo_line)} ms</b>" if slo_line is not None else ""
        cards.append(
            f"""<section class="card">
  <header><h2>{html.escape(panel["title"])}</h2><span class="badge {state}">{badge}</span></header>
  <p class="meta">unit: <b>{html.escape(panel["unit"])}</b> · threshold: <b>{html.escape(label)}</b>{slo_note}</p>
  <dl>{stats}</dl>
  {render_chart(data["series"], computed["_buckets"], panel["unit"], line, slo_line)}
</section>"""
        )
    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="{config["refresh_seconds"]}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(config["title"])}</title>
<style>
  :root {{ --bg:#f6f7f9; --card:#fff; --text:#111827; --muted:#6b7280; --line:#e5e7eb; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:20px; background:var(--bg); color:var(--text); font:14px/1.4 system-ui, sans-serif; }}
  h1 {{ margin:0 0 4px; font-size:20px; }}
  .top {{ color:var(--muted); margin-bottom:16px; }}
  .top b {{ color:var(--text); }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(420px, 1fr)); gap:14px; }}
  @media (min-width: 1300px) {{ .grid {{ grid-template-columns:repeat(3, 1fr); }} }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
  .card header {{ display:flex; justify-content:space-between; align-items:center; gap:8px; }}
  h2 {{ margin:0; font-size:15px; }}
  .meta {{ margin:4px 0 8px; color:var(--muted); font-size:12px; }}
  dl {{ display:flex; flex-wrap:wrap; gap:4px 18px; margin:0 0 8px; }}
  dl div {{ min-width:70px; }}
  dt {{ color:var(--muted); font-size:11px; }}
  dd {{ margin:0; font-weight:600; font-variant-numeric:tabular-nums; }}
  .badge {{ font-size:11px; font-weight:700; padding:2px 8px; border-radius:999px; }}
  .badge.ok {{ background:#dcfce7; color:#166534; }}
  .badge.breach {{ background:#fee2e2; color:#991b1b; }}
  .badge.nodata {{ background:#e5e7eb; color:#374151; }}
  svg {{ width:100%; height:auto; font-size:10px; fill:var(--muted); }}
  .axis {{ stroke:#9ca3af; }}
  .threshold {{ stroke:#dc2626; stroke-dasharray:5 4; stroke-width:1.4; }}
  .threshold-label {{ fill:#dc2626; }}
  .slo {{ stroke:#7c3aed; stroke-dasharray:2 3; stroke-width:1.4; }}
  .slo-label {{ fill:#7c3aed; }}
  .legend {{ display:flex; flex-wrap:wrap; gap:4px 12px; font-size:11px; color:var(--muted); }}
  .legend i {{ display:inline-block; width:10px; height:3px; margin-right:4px; vertical-align:middle; }}
</style></head>
<body>
<h1>{html.escape(config["title"])}</h1>
<div class="top">Time range: <b>last {minutes} min</b> ({window}){zoom_note} · auto refresh <b>{config["refresh_seconds"]}s</b>
 · source <b>data/logs.jsonl</b> ({record_count} records) · generated {local_now:%Y-%m-%d %H:%M:%S}</div>
<div class="grid">
{"".join(cards)}
</div>
</body></html>"""


def build_page(log_path: Path = LOG_PATH, minutes: int | None = None) -> str:
    config = load_config()
    minutes = minutes or config["time_range_minutes"]
    now = datetime.now(timezone.utc)
    records = load_records(log_path, now - timedelta(minutes=minutes))
    computed = compute_panels(records, now, minutes)
    return render_html(config, computed, now, len(records), load_slo_latency_ms(), minutes)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        url = urlsplit(self.path)
        if url.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        try:
            minutes = int(parse_qs(url.query).get("minutes", ["0"])[0])
        except ValueError:
            minutes = 0
        body = build_page(minutes=max(1, min(minutes, 1440)) if minutes else None).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        return None


def main() -> None:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--once", type=Path, help="Ghi HTML tĩnh ra file rồi thoát")
    args = parser.parse_args()
    if args.once:
        args.once.write_text(build_page(), encoding="utf-8")
        print(f"Đã ghi {args.once}")
        return
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Dashboard: http://127.0.0.1:{args.port}  (Ctrl+C để dừng)")
    server.serve_forever()


if __name__ == "__main__":
    main()
