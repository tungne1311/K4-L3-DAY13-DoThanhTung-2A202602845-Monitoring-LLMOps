from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import dashboard  # noqa: E402

NOW = datetime(2026, 9, 29, 9, 0, 30, tzinfo=timezone.utc)


def _write_logs(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


def _ts(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


def _sample(tmp_path: Path) -> dict:
    records = []
    for i, latency in enumerate([100, 200, 300, 4000]):
        records.append({"event": "request_received", "ts": _ts(2)})
        records.append({
            "event": "response_sent", "ts": _ts(2), "latency_ms": latency, "ttft_ms": 50,
            "cost_usd": 0.01, "tokens_in": 10, "tokens_out": 100, "quality_score": 0.8,
            "tool_success": True,
        })
    records.append({"event": "request_received", "ts": _ts(1)})
    records.append({"event": "request_failed", "ts": _ts(1), "error_type": "RuntimeError", "tool_success": False})
    records.append({"event": "response_sent", "ts": _ts(90), "latency_ms": 99999, "cost_usd": 9,
                    "tokens_in": 1, "tokens_out": 1, "quality_score": 0, "ttft_ms": 1})
    log_path = tmp_path / "logs.jsonl"
    _write_logs(log_path, records)
    rows = dashboard.load_records(log_path, NOW - timedelta(minutes=60))
    return dashboard.compute_panels(rows, NOW, 60)


def test_window_excludes_records_older_than_time_range(tmp_path: Path) -> None:
    panels = _sample(tmp_path)
    assert panels["cost"]["stats"]["total"] == 0.04
    assert panels["latency"]["stats"]["p99"] == 4000


def test_error_rate_and_retrieval_success(tmp_path: Path) -> None:
    stats = _sample(tmp_path)["errors"]["stats"]
    assert stats["error_rate_pct"] == 20.0
    assert stats["tool_success_rate_pct"] == 80.0
    assert stats["count_by_value"] == {"RuntimeError": 1}


def test_threshold_status_uses_contract(tmp_path: Path) -> None:
    panels = _sample(tmp_path)
    config = {p["id"]: p for p in dashboard.load_config()["panels"]}
    assert dashboard.threshold_status(config["errors"], panels["errors"]["stats"])[1] is False
    assert dashboard.threshold_status(config["quality"], panels["quality"]["stats"])[1] is True
    assert dashboard.threshold_status(config["tokens"], panels["tokens"]["stats"])[1] is True


def test_page_renders_six_panels_with_refresh(tmp_path: Path) -> None:
    html = dashboard.build_page(tmp_path / "missing.jsonl")
    assert html.count('class="card"') == 6
    assert 'http-equiv="refresh" content="30"' in html
