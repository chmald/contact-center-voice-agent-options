from __future__ import annotations

import asyncio

import pytest
import uvicorn

from loadtest.concurrency_probe import run_level, summarize_results
from tests.fake_upstream import FakeRealtimeServer
from voiceagent_core.server import create_app
from voiceagent_core.settings import CommonSettings


@pytest.mark.asyncio
async def test_probe_end_to_end_with_greeting_and_admission_control(repo_root, profile_path, dummy_bridge_class):
    """Real uvicorn app + fake upstream: greeting is drained, turns are measured,
    and the session over MAX_CONCURRENT_SESSIONS is reported as busy."""

    fake = FakeRealtimeServer(dialect="ga", script_function_call=True, response_delay=0.05)
    await fake.start()
    dummy_bridge_class.upstream_url = fake.url
    settings = CommonSettings(
        agent_profile_path=profile_path,
        max_concurrent_sessions=2,
        static_dir=repo_root / "shared" / "static",
    )
    app = create_app(lambda *args: dummy_bridge_class(*args), settings)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    serve_task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.02)
        port = server.servers[0].sockets[0].getsockname()[1]
        level = await run_level(
            url=f"ws://127.0.0.1:{port}/ws",
            sessions=3,
            turns=["What's the status of request SR-1001?", "And SR-1004?"],
            ramp_seconds=0.0,
            timeout=10.0,
        )
        summary = level["summary"]
        assert summary["ok"] == 2, level["records"]
        assert summary["busy"] == 1
        assert summary["errors"] == 0
        assert summary["p50_ttfa_ms"] is not None
        ok_records = [r for r in level["records"] if r["status"] == "ok"]
        assert all(len(r["turns"]) == 2 for r in ok_records)
        assert fake.rejected_response_creates == 0
    finally:
        server.should_exit = True
        await serve_task
        await fake.stop()


def test_probe_summary_math_on_synthetic_data():
    records = [
        {
            "status": "ok",
            "turns": [
                {"ttfa_ms": 100, "response_ms": 500, "total_tokens": 10},
                {"ttfa_ms": 200, "response_ms": 700, "total_tokens": 20},
            ],
            "session": {"tokens_per_minute": 60},
        },
        {
            "status": "ok",
            "turns": [{"ttfa_ms": 300, "response_ms": 900, "total_tokens": 30}],
            "session": {"tokens_per_minute": 90},
        },
        {"status": "busy", "turns": []},
        {"status": "error", "turns": []},
    ]

    summary = summarize_results(records, sessions=4)
    assert summary["sessions"] == 4
    assert summary["ok"] == 2
    assert summary["busy"] == 1
    assert summary["errors"] == 1
    assert summary["p50_ttfa_ms"] == 200
    assert summary["p90_ttfa_ms"] == 280
    assert summary["avg_tokens_per_turn"] == 20
    assert summary["est_tpm_per_session"] == 75
    assert summary["aggregate_tpm"] == 150
