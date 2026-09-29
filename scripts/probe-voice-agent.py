"""Diagnostic probe for a Foundry voice agent WebSocket session.

Connects with your Entra sign-in (az login), optionally sends a text turn, streams
a little silence, and prints every server event plus the close code/reason, so
connection problems are visible without the browser or phone path.

    python scripts/probe-voice-agent.py --route project --text "What are your support hours?"
    python scripts/probe-voice-agent.py --route voice-live

Reads VOICE_AGENT_ENDPOINT / VOICE_AGENT_PROJECT / VOICE_AGENT_NAME from the
environment or flags. Routes:
  project    wss://<foundry>/api/projects/<p>/agents/<a>/endpoint/protocols/voice?api-version=2025-11-15-preview
             + Foundry-Features: VoiceAgents=V1Preview   (Foundry portal sample)
  voice-live wss://<foundry>/voice-live/realtime?api-version=2026-07-15&agent-name=<a>&agent-project-name=<p>
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import time
from urllib.parse import quote, urlencode, urlsplit

import websockets
from azure.identity.aio import DefaultAzureCredential

SCOPE = "https://ai.azure.com/.default"


def build_url(route: str, endpoint: str, project: str, agent: str, api_version: str | None) -> str:
    host = urlsplit(endpoint).netloc
    if route == "project":
        version = api_version or "2025-11-15-preview"
        return (
            f"wss://{host}/api/projects/{quote(project, safe='')}/agents/{quote(agent, safe='')}"
            f"/endpoint/protocols/voice?{urlencode({'api-version': version})}"
        )
    version = api_version or "2026-07-15"
    return f"wss://{host}/voice-live/realtime?" + urlencode(
        {"api-version": version, "agent-name": agent, "agent-project-name": project}
    )


def summarize(event: dict) -> str:
    kind = event.get("type", "?")
    if kind in {"response.audio.delta", "response.output_audio.delta"}:
        return f"{kind} ({len(base64.b64decode(event.get('delta') or ''))} bytes)"
    if kind == "error":
        return f"error: {json.dumps(event.get('error'))}"
    text = event.get("transcript") or event.get("delta") if "transcript" in kind else None
    if text:
        return f"{kind}: {text}"
    if kind in {"session.created", "session.updated"}:
        session = event.get("session") or {}
        keys = ", ".join(sorted(session)) if isinstance(session, dict) else ""
        return f"{kind} (session keys: {keys})"
    return kind


async def run(args: argparse.Namespace) -> int:
    url = build_url(args.route, args.endpoint, args.project, args.agent, args.api_version)
    async with DefaultAzureCredential() as credential:
        token = (await credential.get_token(SCOPE)).token
    headers = {"Authorization": f"Bearer {token}"}
    if args.route == "project":
        headers["Foundry-Features"] = "VoiceAgents=V1Preview"
    print(f"Connecting: {url}")
    start = time.monotonic()
    counts: dict[str, int] = {}
    try:
        async with websockets.connect(url, additional_headers=headers, max_size=None) as ws:
            print(f"[{time.monotonic() - start:5.2f}s] connected")

            async def sender() -> None:
                await asyncio.sleep(1.0)
                if args.text:
                    await ws.send(json.dumps({"type": "conversation.item.create", "item": {
                        "type": "message", "role": "user", "content": [{"type": "input_text", "text": args.text}]}}))
                    await ws.send(json.dumps({"type": "response.create"}))
                    print(f"[{time.monotonic() - start:5.2f}s] sent text turn")
                silence = base64.b64encode(bytes(4800)).decode()  # 100 ms PCM16 24 kHz
                for _ in range(int(args.seconds * 10)):
                    await ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": silence}))
                    await asyncio.sleep(0.1)

            send_task = asyncio.create_task(sender())
            try:
                while time.monotonic() - start < args.seconds + 5:
                    raw = await asyncio.wait_for(ws.recv(), timeout=args.seconds + 5)
                    event = json.loads(raw)
                    kind = event.get("type", "?")
                    counts[kind] = counts.get(kind, 0) + 1
                    if "delta" in kind and counts[kind] > 3:
                        continue
                    print(f"[{time.monotonic() - start:5.2f}s] {summarize(event)}")
            except asyncio.TimeoutError:
                print("(no more events)")
            finally:
                send_task.cancel()
    except websockets.ConnectionClosed as closed:
        print(f"[{time.monotonic() - start:5.2f}s] CLOSED by server: code={closed.code} reason={closed.reason!r}")
    except websockets.InvalidStatus as status:
        response = status.response
        print(f"HTTP {response.status_code} on upgrade: {response.body[:500]!r}")
        return 1
    print("Event counts:", json.dumps(counts, indent=1))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--route", choices=["project", "voice-live"], default="project")
    parser.add_argument("--endpoint", default=os.getenv("VOICE_AGENT_ENDPOINT"))
    parser.add_argument("--project", default=os.getenv("VOICE_AGENT_PROJECT") or "voice-agents")
    parser.add_argument("--agent", default=os.getenv("VOICE_AGENT_NAME") or "voice-agent-demo")
    parser.add_argument("--api-version")
    parser.add_argument("--text", default="")
    parser.add_argument("--seconds", type=float, default=6.0)
    args = parser.parse_args()
    if not args.endpoint:
        parser.error("--endpoint or VOICE_AGENT_ENDPOINT is required")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
