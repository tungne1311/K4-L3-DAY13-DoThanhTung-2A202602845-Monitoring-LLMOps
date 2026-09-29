from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx

from app import logging_config
from app.main import app

CHAT_BODY = {
    "user_id": "student-01",
    "session_id": "session-01",
    "feature": "qa",
    "message": "My email is student@vinuni.edu.vn and phone 0987654321",
}


def _post(headers: dict[str, str] | None = None) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/chat", json=CHAT_BODY, headers=headers or {})

    return asyncio.run(send())


def test_generates_correlation_id_and_response_headers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(logging_config, "LOG_PATH", tmp_path / "logs.jsonl")

    response = _post()

    cid = response.headers["x-request-id"]
    assert re.fullmatch(r"req-[0-9a-f]{8}", cid)
    assert response.json()["correlation_id"] == cid
    assert float(response.headers["x-response-time-ms"]) >= 0


def test_reuses_valid_incoming_id_and_rejects_invalid(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(logging_config, "LOG_PATH", tmp_path / "logs.jsonl")

    assert _post({"x-request-id": "req-0123abcd"}).headers["x-request-id"] == "req-0123abcd"

    replaced = _post({"x-request-id": "evil\nvalue"}).headers["x-request-id"]
    assert replaced != "evil\nvalue"
    assert re.fullmatch(r"req-[0-9a-f]{8}", replaced)


def test_api_logs_are_enriched_and_scrubbed(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    first = _post().headers["x-request-id"]
    second = _post().headers["x-request-id"]
    assert first != second

    api_events = [
        e for e in map(json.loads, log_path.read_text(encoding="utf-8").splitlines())
        if e.get("service") == "api"
    ]
    assert {e["correlation_id"] for e in api_events} == {first, second}
    for event in api_events:
        for field in ("user_id_hash", "session_id", "feature", "model", "env"):
            assert field in event
        assert event["user_id_hash"] != "student-01"

    raw = log_path.read_text(encoding="utf-8")
    assert "student@vinuni.edu.vn" not in raw
    assert "0987654321" not in raw
