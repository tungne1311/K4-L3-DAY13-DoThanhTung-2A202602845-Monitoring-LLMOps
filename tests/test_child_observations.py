from __future__ import annotations

from contextlib import contextmanager

import pytest

from app import agent as agent_module
from app.incidents import STATE


class RecordingObservation:
    def __init__(self, kwargs: dict) -> None:
        self.start = kwargs
        self.updates: dict = {}

    def update(self, **kwargs) -> None:
        self.updates.update(kwargs)


@pytest.fixture
def observations(monkeypatch) -> list[RecordingObservation]:
    recorded: list[RecordingObservation] = []

    @contextmanager
    def fake_start_observation(**kwargs):
        observation = RecordingObservation(kwargs)
        recorded.append(observation)
        yield observation

    monkeypatch.setattr(agent_module, "start_observation", fake_start_observation)
    monkeypatch.setattr(agent_module, "tracing_enabled", lambda: False)
    return recorded


def _run(message: str) -> agent_module.AgentResult:
    agent = agent_module.LabAgent()
    return agent_module.LabAgent.run.__wrapped__(
        agent,
        user_id="student-01",
        feature="qa",
        session_id="session-01",
        message=message,
        correlation_id="req-12345678",
    )


def test_run_creates_retriever_then_generation(observations) -> None:
    result = _run("What is the refund policy? mail me at student@vinuni.edu.vn")

    retriever, prompt_span, generation = observations
    assert (prompt_span.start["name"], prompt_span.start["as_type"]) == ("resolve-prompt", "span")
    assert prompt_span.updates["output"]["prompt_source"] == "local"
    assert (retriever.start["name"], retriever.start["as_type"]) == ("retrieve", "retriever")
    assert retriever.updates["output"]["doc_count"] == 1

    assert (generation.start["name"], generation.start["as_type"]) == ("llm-generate", "generation")
    assert generation.start["model"] == "claude-sonnet-4-5"
    assert generation.start["metadata"]["prompt_version"] == "local-v1"
    assert generation.updates["usage_details"] == {
        "input": result.tokens_in,
        "output": result.tokens_out,
    }
    assert generation.updates["cost_details"]["total"] == result.cost_usd
    assert generation.updates["completion_start_time"] is not None


def test_observations_never_carry_raw_pii(observations) -> None:
    _run("Card 4111 1111 1111 1111, phone 0987654321, email student@vinuni.edu.vn")

    raw = repr([(o.start, o.updates) for o in observations])
    for pii in ("4111 1111 1111 1111", "0987654321", "student@vinuni.edu.vn"):
        assert pii not in raw


def test_retrieval_failure_marks_observation_as_error(observations, monkeypatch) -> None:
    monkeypatch.setitem(STATE, "tool_fail", True)

    with pytest.raises(RuntimeError):
        _run("Explain monitoring")

    (retriever,) = observations
    assert retriever.updates["level"] == "ERROR"
    assert "Vector store timeout" in retriever.updates["status_message"]
