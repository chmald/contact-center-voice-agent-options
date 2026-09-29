"""Simulate an Asterisk chan_websocket call against a deployed app's /telephony/asterisk/media.

Connects the way Asterisk does (HTTP Basic auth with ASTERISK_WEBSOCKET_SECRET, subprotocol
"media"), sends a JSON MEDIA_START for slin24, streams silence, and prints the control commands
and audio the agent sends back (the agent's greeting arrives as audio). Use it to verify the
endpoint before pointing a real Asterisk at it.

    python scripts/probe-asterisk.py --url wss://<app-fqdn>/telephony/asterisk/media --secret <ASTERISK_WEBSOCKET_SECRET>

Without --secret it reads ASTERISK_WEBSOCKET_SECRET from the environment
(e.g. `$env:ASTERISK_WEBSOCKET_SECRET = azd env get-value ASTERISK_WEBSOCKET_SECRET`).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import time

import websockets


async def run(url: str, secret: str, seconds: float, fmt: str) -> int:
    auth = base64.b64encode(f"asterisk:{secret}".encode()).decode()
    frame = bytes(960 if fmt == "slin24" else 160 if fmt == "ulaw" else 320)
    start = time.monotonic()
    audio_bytes = 0
    commands: list[str] = []
    try:
        async with websockets.connect(
            url, additional_headers={"Authorization": f"Basic {auth}"}, subprotocols=["media"], max_size=None
        ) as ws:
            print(f"[{time.monotonic() - start:5.2f}s] connected (subprotocol={ws.subprotocol})")
            await ws.send(json.dumps({
                "event": "MEDIA_START", "connection_id": "probe", "channel": "WebSocket/probe",
                "channel_id": "probe-1.1", "format": fmt, "optimal_frame_size": len(frame), "ptime": 20,
            }))

            async def stream_silence() -> None:
                for _ in range(int(seconds * 50)):
                    await ws.send(frame)  # 20 ms of silence, like a quiet caller
                    await asyncio.sleep(0.02)

            sender = asyncio.create_task(stream_silence())
            try:
                while time.monotonic() - start < seconds + 2:
                    message = await asyncio.wait_for(ws.recv(), timeout=seconds + 2)
                    if isinstance(message, bytes):
                        if audio_bytes == 0:
                            print(f"[{time.monotonic() - start:5.2f}s] first agent audio received")
                        audio_bytes += len(message)
                    else:
                        commands.append(message)
                        print(f"[{time.monotonic() - start:5.2f}s] command: {message}")
            except asyncio.TimeoutError:
                pass
            finally:
                sender.cancel()
    except websockets.InvalidStatus as status:
        print(f"Rejected: HTTP {status.response.status_code} (check the secret and TELEPHONY_PROVIDERS)")
        return 1
    except websockets.ConnectionClosed as closed:
        print(f"Closed by app: code={closed.code} reason={closed.reason!r}")
    bytes_per_second = 48000 if fmt == "slin24" else 8000 if fmt == "ulaw" else 16000
    print(f"Agent audio: {audio_bytes} bytes (~{audio_bytes / bytes_per_second:.1f} s); commands: {len(commands)}")
    return 0 if audio_bytes else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True, help="wss://<app-fqdn>/telephony/asterisk/media")
    parser.add_argument("--secret", default=os.getenv("ASTERISK_WEBSOCKET_SECRET"))
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--format", choices=["slin24", "ulaw", "slin"], default="slin24")
    args = parser.parse_args()
    if not args.secret:
        parser.error("--secret or ASTERISK_WEBSOCKET_SECRET is required")
    return asyncio.run(run(args.url, args.secret, args.seconds, args.format))


if __name__ == "__main__":
    sys.exit(main())
