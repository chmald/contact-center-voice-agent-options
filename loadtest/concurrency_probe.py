"""Text-turn concurrency probe for deployed browser voice agents."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path
from typing import Any

import websockets

DEFAULT_TURNS_FILE = Path(__file__).with_name("prompts.example.json")
GREETING_QUIET_SECONDS = 1.5


async def wait_for_greeting(ws: Any, timeout: float, quiet_seconds: float = GREETING_QUIET_SECONDS) -> dict[str, Any] | None:
    """Let the agent finish its greeting so turn 1 isn't measured against it.

    Returns when the greeting's ``metrics`` message arrives, or when the socket
    stays quiet for ``quiet_seconds`` (no greeting configured). A ``busy`` or
    ``error`` message is returned to the caller.
    """

    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=quiet_seconds)
        except TimeoutError:
            return None
        message = json.loads(raw)
        if message.get("type") == "metrics":
            return None
        if message.get("type") in {"busy", "error"}:
            return message
    return None


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * quantile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize_results(records: list[dict[str, Any]], sessions: int) -> dict[str, Any]:
    ok_records = [record for record in records if record["status"] == "ok"]
    busy = sum(1 for record in records if record["status"] == "busy")
    errors = sum(1 for record in records if record["status"] == "error")
    turn_rows = [turn for record in ok_records for turn in record.get("turns", [])]
    ttfas = [turn["ttfa_ms"] for turn in turn_rows if turn.get("ttfa_ms") is not None]
    responses = [turn["response_ms"] for turn in turn_rows if turn.get("response_ms") is not None]
    token_values = [turn.get("total_tokens", 0) for turn in turn_rows]
    session_tpms = [
        record.get("session", {}).get("tokens_per_minute", 0)
        for record in ok_records
        if record.get("session")
    ]
    return {
        "sessions": sessions,
        "ok": len(ok_records),
        "busy": busy,
        "errors": errors,
        "p50_ttfa_ms": round(percentile(ttfas, 0.5), 2) if ttfas else None,
        "p90_ttfa_ms": round(percentile(ttfas, 0.9), 2) if ttfas else None,
        "p50_response_ms": round(percentile(responses, 0.5), 2) if responses else None,
        "p90_response_ms": round(percentile(responses, 0.9), 2) if responses else None,
        "avg_tokens_per_turn": round(statistics.mean(token_values), 2) if token_values else 0,
        "est_tpm_per_session": round(statistics.mean(session_tpms), 2) if session_tpms else 0,
        "aggregate_tpm": round(sum(session_tpms), 2),
    }


async def run_session(
    session_index: int,
    url: str,
    turns: list[str],
    timeout: float,
    start_delay: float,
) -> dict[str, Any]:
    await asyncio.sleep(start_delay)
    result: dict[str, Any] = {"session_index": session_index, "status": "ok", "turns": []}
    try:
        async with websockets.connect(url, max_size=None) as ws:
            first = await asyncio.wait_for(ws.recv(), timeout=timeout)
            first_message = json.loads(first)
            if first_message.get("type") == "busy":
                result["status"] = "busy"
                result["message"] = first_message.get("message", "")
                return result
            if first_message.get("type") != "ready":
                result["status"] = "error"
                result["message"] = f"Expected ready, got {first_message.get('type')}"
                return result

            interrupted = await wait_for_greeting(ws, timeout)
            if interrupted is not None:
                result["status"] = interrupted["type"]
                result["message"] = interrupted.get("message", "")
                return result

            latest_session = None
            for text in turns:
                sent_at = time.perf_counter()
                await ws.send(json.dumps({"type": "text", "text": text}))
                first_audio_ms = None
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    message = json.loads(raw)
                    elapsed_ms = (time.perf_counter() - sent_at) * 1000
                    if message.get("type") == "audio" and first_audio_ms is None:
                        first_audio_ms = elapsed_ms
                    elif message.get("type") == "metrics":
                        turn = dict(message.get("turn", {}))
                        turn["probe_ttfa_ms"] = round(first_audio_ms, 2) if first_audio_ms else None
                        turn["probe_response_ms"] = round(elapsed_ms, 2)
                        result["turns"].append(turn)
                        latest_session = message.get("session", {})
                        break
                    elif message.get("type") == "busy":
                        result["status"] = "busy"
                        result["message"] = message.get("message", "")
                        return result
                    elif message.get("type") == "error":
                        result["status"] = "error"
                        result["message"] = message.get("message", "")
                        return result
            result["session"] = latest_session or {}
            return result
    except Exception as exc:
        return {
            "session_index": session_index,
            "status": "error",
            "message": f"{type(exc).__name__}: {exc}",
            "turns": result.get("turns", []),
        }


async def run_level(
    url: str,
    sessions: int,
    turns: list[str],
    ramp_seconds: float,
    timeout: float,
) -> dict[str, Any]:
    delay_step = ramp_seconds / max(sessions, 1)
    tasks = [
        asyncio.create_task(run_session(i, url, turns, timeout, i * delay_step))
        for i in range(sessions)
    ]
    records = await asyncio.gather(*tasks)
    return {"summary": summarize_results(records, sessions), "records": records}


def load_turns(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(item, str) and item for item in data):
        raise ValueError("Turns file must be a JSON list of non-empty strings")
    return data


def print_table(results: list[dict[str, Any]]) -> None:
    headers = [
        "sessions",
        "ok",
        "busy",
        "errors",
        "p50_ttfa_ms",
        "p90_ttfa_ms",
        "p50_response_ms",
        "p90_response_ms",
        "avg_tokens_per_turn",
        "est_tpm_per_session",
        "aggregate_tpm",
    ]
    print(" | ".join(headers))
    print(" | ".join("---" for _ in headers))
    for row in results:
        summary = row["summary"]
        print(" | ".join(str(summary.get(header, "")) for header in headers))


async def main_async(args: argparse.Namespace) -> None:
    turns = load_turns(args.turns_file)
    levels = [int(part.strip()) for part in args.sessions.split(",") if part.strip()]
    results = []
    for sessions in levels:
        results.append(
            await run_level(
                url=args.url,
                sessions=sessions,
                turns=turns,
                ramp_seconds=args.ramp_seconds,
                timeout=args.timeout,
            )
        )
    print_table(results)
    payload = {"url": args.url, "turns_file": str(args.turns_file), "results": results}
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run concurrent text-turn probes against a voice-agent WebSocket.")
    parser.add_argument("--url", required=True, help="WebSocket URL ending in /ws")
    parser.add_argument("--sessions", default="1,4,10,20", help="Comma-separated concurrency levels")
    parser.add_argument("--turns-file", type=Path, default=DEFAULT_TURNS_FILE, help="JSON list of scripted text turns")
    parser.add_argument("--ramp-seconds", type=float, default=0.0, help="Seconds over which to stagger session starts")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-message timeout in seconds")
    parser.add_argument("--out", type=Path, default=Path("results.json"), help="Output JSON path")
    return parser.parse_args()


def main() -> None:
    asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    main()
