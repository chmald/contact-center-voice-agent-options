from __future__ import annotations

from voiceagent_core.metrics import SessionMetrics


def test_turn_and_session_metrics_tolerate_missing_and_nested_usage():
    metrics = SessionMetrics("session-1")
    metrics.mark_turn_start()
    assert metrics.turn_started_at is not None
    metrics.turn_started_at -= 0.2
    metrics.mark_first_audio()

    turn = metrics.finish_turn(
        {
            "type": "response.done",
            "response": {
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 6,
                    "total_tokens": 16,
                    "input_token_details": {
                        "cached_tokens": 4,
                        "text_tokens": 7,
                        "audio_tokens": 3,
                    },
                    "output_token_details": {
                        "text_tokens": 2,
                        "audio_tokens": 4,
                    },
                }
            },
        }
    )

    assert turn["ttfa_ms"] is not None
    assert turn["input_tokens"] == 10
    assert turn["output_tokens"] == 6
    assert turn["cached_tokens"] == 4

    session = metrics.session_summary()
    assert session["turns"] == 1
    assert session["total_tokens"] == 16
    assert session["tokens_per_minute"] > 0
    assert session["ttfa_p50_ms"] == turn["ttfa_ms"]


def test_metrics_missing_usage_defaults_to_zero():
    metrics = SessionMetrics("session-2")
    metrics.mark_turn_start()
    turn = metrics.finish_turn({"type": "response.done", "response": {}})
    assert turn["total_tokens"] == 0
    assert metrics.session_summary()["turns"] == 1
