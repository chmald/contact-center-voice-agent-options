"""Create (or version) the Foundry voice agent from config/agent-profile.json.

Runs as the azd ``postprovision`` hook of examples/foundry-voice-agent and can be
re-run by hand after editing the profile. Every run creates a new agent version;
the app connects to the latest version unless ``VOICE_AGENT_VERSION`` pins one.

The agent owns instructions, function tools (client-executed by the shared bridge,
including the shared ``search_knowledge_base`` RAG tool), voice, the greeting, the
audio pipeline (Azure semantic VAD, deep noise suppression, echo cancellation,
transcription - the same settings the Voice Live example sends per session), and
conversation storage. Agent Service does not accept per-response instruction
overrides, so the greeting must live on the agent.

    python scripts/create-voice-agent.py \
        --project-endpoint https://<foundry>.services.ai.azure.com/api/projects/<project>

Requires ``azure-ai-projects>=2.7.0`` and an Entra identity with the Foundry User
role on the Foundry resource (the Bicep grants it to the deploying user).
Voice agents are in public preview.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / "config" / "agent-profile.json"
NATIVE_TRANSCRIPTION_MODELS = {"gpt-realtime", "gpt-realtime-mini"}
OPENAI_VOICES = {"alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse", "marin", "cedar"}


def voice_config(voice: str) -> dict[str, Any]:
    if voice in OPENAI_VOICES:
        return {"voice": voice, "voice_type": "openai"}
    return {"voice": voice, "voice_type": "azure-standard"}


def build_definition(profile_path: Path, model: str, voice: str, store: bool = True) -> dict[str, Any]:
    """Build the VoiceAgentDefinition payload from the shared agent profile (no Azure calls)."""

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    tools = [
        {
            "type": "function",
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"],
        }
        for tool in profile.get("tools", [])
    ]
    transcription = "gpt-4o-mini-transcribe" if model in NATIVE_TRANSCRIPTION_MODELS else "azure-speech"
    definition: dict[str, Any] = {
        "kind": "voice",
        "model_type": "managed",
        "model": model,
        "instructions": profile["instructions"],
        "audio": {
            "input": {
                "turn_detection": {"type": "azure_semantic_vad"},
                "noise_reduction": {"type": "azure_deep_noise_suppression"},
                "echo_cancellation": {"type": "server_echo_cancellation"},
                "transcription": {"model": transcription},
            },
            "output": voice_config(voice),
        },
        "output_modalities": ["audio"],
        "tools": tools,
        "tool_choice": "auto",
        "store": store,
    }
    greeting = (profile.get("greeting") or "").strip()
    if greeting:
        # Template greetings are Handlebars; escape literal braces so profile text is spoken as-is.
        definition["greeting"] = {"type": "template", "text": greeting.replace("{{", "\\{{")}
    return definition


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-endpoint", default=os.getenv("VOICE_AGENT_PROJECT_ENDPOINT"))
    parser.add_argument("--agent-name", default=os.getenv("VOICE_AGENT_NAME") or "voice-agent-demo")
    parser.add_argument("--model", default=os.getenv("VOICE_AGENT_MODEL") or "gpt-realtime-2.1-mini")
    parser.add_argument("--voice", default=os.getenv("VOICE_AGENT_VOICE") or "en-US-Ava:DragonHDLatestNeural")
    parser.add_argument("--profile", default=os.getenv("AGENT_PROFILE_PATH") or str(DEFAULT_PROFILE))
    parser.add_argument("--no-store", action="store_true", help="Do not persist conversations (transcript/audio) in Foundry")
    parser.add_argument("--dry-run", action="store_true", help="Print the definition and exit")
    args = parser.parse_args()

    definition = build_definition(Path(args.profile), args.model, args.voice, store=not args.no_store)
    if args.dry_run:
        print(json.dumps(definition, indent=2))
        return 0
    if not args.project_endpoint:
        print("VOICE_AGENT_PROJECT_ENDPOINT / --project-endpoint is required", file=sys.stderr)
        return 2

    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import VoiceAgentDefinition
    from azure.identity import DefaultAzureCredential

    with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=args.project_endpoint, credential=credential, allow_preview=True
    ) as client:
        created = client.agents.create_version(
            agent_name=args.agent_name,
            definition=VoiceAgentDefinition(definition),
            description="Voice agent comparison demo (created from config/agent-profile.json)",
        )
    version = getattr(created, "version", None) or (created.get("version") if isinstance(created, dict) else None)
    print(f"Voice agent '{args.agent_name}' version {version} created with model {args.model} and {len(definition['tools'])} tools.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
