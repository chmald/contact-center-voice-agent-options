"""Generate docs/assets/voice-live-vs-realtime-api-architecture.drawio (4 pages).

Re-run after architecture changes, then export PNGs:

    python scripts/build-diagrams.py
    pwsh scripts/export-diagrams.ps1

Pages: 1 solution architecture, 2 three ways to connect, 3 phone call flow,
4 deployment and regions. Styles follow the Microsoft Fluent palette with the
Azure 2 icons bundled in draw.io (image=img/lib/azure2/...svg).
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "voice-live-vs-realtime-api-architecture.drawio"

BLUE, AI, USER, TEAL, GREY = "#0078D4", "#5C2D91", "#A4262C", "#036C70", "#605E5C"
WARN, WARN_FILL = "#B7791F", "#FFF4CE"
OK, OK_FILL = "#107C10", "#DFF6DD"
BAD_FILL = "#FDE7E9"

ICONS = {
    "aca": "other/Container_App_Environments.svg",
    "acs": "other/Azure_Communication_Services.svg",
    "eg": "integration/Event_Grid_Subscriptions.svg",
    "speech": "ai_machine_learning/Speech_Services.svg",
    "openai": "ai_machine_learning/Azure_OpenAI.svg",
    "foundry": "ai_machine_learning/AI_Foundry.svg",
    "search": "app_services/Search_Services.svg",
    "acr": "containers/Container_Registries.svg",
    "log": "analytics/Log_Analytics_Workspaces.svg",
    "mi": "identity/Managed_Identities.svg",
    "rg": "general/Resource_Groups.svg",
    "sub": "general/Subscriptions.svg",
}


def a(text: str) -> str:
    """Escape a label for an XML attribute (newlines become &#10;)."""
    return escape(text, {'"': "&quot;"}).replace("\n", "&#10;")


class Page:
    def __init__(self, page_id: str, name: str, width: int, height: int):
        self.page_id, self.name, self.width, self.height = page_id, name, width, height
        self.cells: list[str] = []
        self._n = 0

    def _id(self, prefix: str) -> str:
        self._n += 1
        return f"{self.page_id}-{prefix}{self._n}"

    def raw(self, cid: str, value: str, style: str, x: int, y: int, w: int, h: int, parent: str = "1") -> str:
        self.cells.append(
            f'<mxCell id="{cid}" value="{a(escape(value))}" style="{style}" vertex="1" parent="{parent}">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" /></mxCell>'
        )
        return cid

    def title(self, text: str, subtitle: str) -> None:
        self.raw(self._id("t"), text, "text;html=1;fontSize=20;fontStyle=1;fontColor=#323130;align=left;verticalAlign=middle;", 40, 20, self.width - 80, 40)
        self.raw(self._id("s"), subtitle, "text;html=1;fontSize=13;fontStyle=2;fontColor=#605E5C;align=left;verticalAlign=middle;whiteSpace=wrap;", 40, 60, self.width - 80, 30)

    def group(self, label: str, x: int, y: int, w: int, h: int, color: str, fill: str = "none", dashed: bool = True) -> str:
        style = (
            f"rounded=1;arcSize=3;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={color};dashed={1 if dashed else 0};"
            f"verticalAlign=top;align=left;spacingLeft=12;spacingTop=6;fontStyle=1;fontSize=13;fontColor={color};strokeWidth=2;"
        )
        return self.raw(self._id("g"), label, style, x, y, w, h)

    def tile(self, title: str, detail: str, x: int, y: int, w: int, h: int, color: str, icon: str | None = None,
             fill: str = "#ffffff", dashed: bool = False) -> str:
        label = f"<b>{escape(title)}</b>" + (f"<br><font style='font-size:10px' color='#323130'>{escape(detail)}</font>" if detail else "")
        style = (
            f"rounded=1;arcSize=10;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={color};strokeWidth=2;"
            f"fontSize=12;fontColor={color};verticalAlign=middle;dashed={1 if dashed else 0};"
            + (f"align=left;spacingLeft={int(h * 0.62) + 14};" if icon else "align=center;")
        )
        cid = self._id("n")
        # label is pre-built HTML: bypass a() escaping of the tag angle brackets, keep attribute-safe quotes
        self.cells.append(
            f'<mxCell id="{cid}" value="{escape(label).replace(chr(34), "&quot;")}" style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" /></mxCell>'
        )
        if icon:
            size = int(h * 0.62)
            self.raw(self._id("i"), "", f"aspect=fixed;html=1;points=[];image;image=img/lib/azure2/{ICONS[icon]};", x + 10, y + (h - size) // 2, size, size)
        return cid

    def note(self, text: str, x: int, y: int, w: int, h: int, color: str = GREY, fill: str = "#F3F2F1", valign: str = "top") -> str:
        style = f"rounded=1;arcSize=6;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={color};fontSize=11;fontColor=#323130;align=left;verticalAlign={valign};spacing=8;"
        cid = self._id("m")
        self.cells.append(
            f'<mxCell id="{cid}" value="{escape(text).replace(chr(34), "&quot;")}" style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" /></mxCell>'
        )
        return cid

    def edge(self, src: str, dst: str, color: str, label: str = "", dashed: bool = False, exit_: str = "", entry: str = "",
             pos: float = 0.0, both: bool = False, straight: bool = False) -> str:
        cid = self._id("e")
        style = (
            ("" if straight else "edgeStyle=orthogonalEdgeStyle;") + f"rounded=1;html=1;endArrow=classic;strokeColor={color};strokeWidth=2;"
            f"dashed={1 if dashed else 0};" + ("startArrow=classic;" if both else "") + exit_ + entry
        )
        self.cells.append(
            f'<mxCell id="{cid}" style="{style}" edge="1" parent="1" source="{src}" target="{dst}">'
            '<mxGeometry relative="1" as="geometry" /></mxCell>'
        )
        if label:
            self.cells.append(
                f'<mxCell id="{cid}l" value="{a(escape(label))}" style="edgeLabel;html=1;align=center;verticalAlign=middle;resizable=0;points=[];'
                f'fontColor={color};fontSize=10;fontStyle=1;labelBackgroundColor=#ffffff;" connectable="0" vertex="1" parent="{cid}">'
                f'<mxGeometry x="{pos}" y="0" relative="1" as="geometry"><mxPoint as="offset" /></mxGeometry></mxCell>'
            )
        return cid

    def xml(self) -> str:
        body = "".join(self.cells)
        return (
            f'<diagram id="{self.page_id}" name="{a(self.name)}"><mxGraphModel dx="1422" dy="800" grid="1" gridSize="10" guides="1" '
            f'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{self.width}" pageHeight="{self.height}" '
            f'math="0" shadow="0"><root><mxCell id="0" /><mxCell id="1" parent="0" />{body}</root></mxGraphModel></diagram>'
        )


R = "exitX=1;exitY=0.5;entryX=0;entryY=0.5;"


def page_architecture() -> Page:
    p = Page("arch", "1 - Solution architecture", 1900, 1060)
    p.title("Voice agent comparison: three upstreams, one bridge, one AI endpoint",
            "Browser and phone callers reach the same FastAPI WebSocket bridge. Each example app differs only in the upstream it talks to.")

    p.group("👥 Callers", 40, 110, 250, 640, USER)
    browser = p.tile("🎙️ Browser", "Microphone · PCM16 24 kHz", 60, 160, 210, 70, USER)
    pstn = p.tile("📞 PSTN caller", "Any phone", 60, 290, 210, 70, USER)
    pbx = p.tile("☎️ PBX (e.g. FreePBX)", "Extension / IVR option over SIP trunk", 60, 580, 210, 80, USER)
    sbc = p.tile("🏢 Contact center / SBC", "Existing platform", 60, 430, 210, 80, USER)

    p.group("📡 Telephony (optional)", 330, 110, 290, 640, BLUE)
    acs = p.tile("Azure Communication Services", "Phone number or Direct Routing · Call Automation", 350, 250, 250, 90, BLUE, "acs")
    eg = p.tile("Event Grid", "IncomingCall → /telephony/acs/events", 350, 380, 250, 70, BLUE, "eg")
    twilio = p.tile("Twilio", "Number or SIP Domain · Media Streams", 350, 580, 250, 80, BLUE)

    p.group("⚡ App tier · Azure Container Apps · region AZURE_APP_LOCATION", 660, 110, 520, 830, BLUE)
    core = p.note(
        "<b>Shared core (identical in every app)</b><br>"
        "• /ws browser socket · /telephony/acs · /telephony/twilio<br>"
        "• Audio adapters: PCM 24 kHz (ACS) · μ-law 8 kHz ↔ 24 kHz (Twilio)<br>"
        "• SessionHub: one admission cap (MAX_CONCURRENT_SESSIONS), overflow → human queue<br>"
        "• RealtimeStyleBridge: barge-in, tool calls, history trim, metrics<br>"
        "• Tools: search_knowledge_base (RAG) · record lookup · time",
        690, 160, 460, 150, BLUE, "#EFF6FC")
    vl_app = p.tile("examples/voice-live-api", "VoiceLiveBridge · sends instructions + tools", 690, 350, 460, 70, BLUE, "aca")
    rt_app = p.tile("examples/realtime-api", "RealtimeApiBridge · GA nested schema", 690, 450, 460, 70, BLUE, "aca")
    va_app = p.tile("examples/foundry-voice-agent  (preview)", "VoiceAgentBridge · no session config · agent owns greeting + audio", 690, 550, 460, 70, WARN, "aca", WARN_FILL, True)
    p.tile("Container Registry", "remote build", 690, 660, 220, 60, BLUE, "acr")
    p.tile("Log Analytics", "voice_turn · channel", 930, 660, 220, 60, BLUE, "log")
    p.tile("Managed identity", "Entra ID · no keys", 690, 740, 220, 60, BLUE, "mi")
    p.note("One replica per app so the admission cap is global.<br>Browser tabs and phone calls share the same counter.", 930, 740, 220, 80)

    p.group("🧠 AI tier · ONE Foundry resource · region AZURE_LOCATION (e.g. centralus)", 1220, 110, 640, 830, AI)
    vl = p.tile("Voice Live API · model mode", "Managed gpt-realtime-mini · no deployment", 1250, 340, 580, 80, AI, "speech")
    rt = p.tile("Azure OpenAI Realtime API", "Global Standard deployment gpt-realtime-2.1-mini", 1250, 440, 580, 80, AI, "openai")
    va = p.tile("Foundry voice agent (project route)", "Project 'voice-agents' · versioned agent · managed gpt-realtime-2.1-mini", 1250, 540, 580, 80, WARN, "foundry", WARN_FILL, True)
    p.tile("Azure AI Search", "index 'knowledge' · keyword + semantic ranker · called by the shared RAG tool (managed identity)", 1250, 680, 580, 70, AI, "search")
    p.note(
        "<b>Capacity</b><br>"
        "• Voice Live + voice agent: per-resource Voice Live limits (100 new connections/min, ≤120K TPM) — <b>shared</b> by both<br>"
        "• Realtime: deployment quota in RPM units (often 10) — separate pool<br>"
        "• Voice agent is <b>public preview</b>",
        1250, 160, 580, 130, WARN, WARN_FILL, "middle")

    p.edge(browser, core, USER, "WSS /ws", exit_="exitX=1;exitY=0.5;", entry="entryX=0;entryY=0.2;", pos=-0.5)
    p.edge(pstn, acs, USER, "", exit_=R.split("entry")[0], entry="entryX=0;entryY=0.3;")
    p.edge(sbc, acs, USER, "Direct Routing", exit_="exitX=1;exitY=0.5;", entry="entryX=0;entryY=0.8;", pos=-0.5)
    p.edge(pbx, twilio, USER, "SIP", exit_="exitX=1;exitY=0.5;", entry="entryX=0;entryY=0.5;")
    p.edge(acs, eg, BLUE, "", exit_="exitX=0.5;exitY=1;", entry="entryX=0.5;entryY=0;")
    p.edge(eg, core, BLUE, "webhook", exit_="exitX=1;exitY=0.5;", entry="entryX=0;entryY=0.75;", pos=0.1, straight=True)
    p.edge(acs, core, BLUE, "media WS", exit_="exitX=1;exitY=0.3;", entry="entryX=0;entryY=0.5;", pos=0.0, both=True, straight=True)
    p.edge(twilio, core, BLUE, "Media Streams", exit_="exitX=1;exitY=0.5;", entry="entryX=0;entryY=0.95;", pos=0.1, both=True, straight=True)
    p.edge(vl_app, vl, AI, "model", exit_=R, entry="", pos=0.0)
    p.edge(rt_app, rt, AI, "deployment", exit_=R, entry="", pos=0.0)
    p.edge(va_app, va, WARN, "project route", exit_=R, entry="", dashed=True, pos=0.0)
    return p


def page_three_ways() -> Page:
    p = Page("ways", "2 - Three ways to connect", 1800, 900)
    p.title("Three ways to connect the same bridge", "What the app sends, what it connects to, where the model lives, and what limits capacity.")
    headers = ["What the bridge sends", "WebSocket endpoint", "Model / agent", "What limits capacity"]
    xs = [300, 660, 1020, 1400]
    for x, h in zip(xs, headers):
        p.raw(p._id("h"), h, "text;html=1;fontSize=13;fontStyle=1;fontColor=#323130;align=center;", x, 110, 320 if x < 1400 else 360, 30)
    rows = [
        ("Voice Live API", "GA", AI, "#ffffff", False,
         "session.update with instructions, tools, voice, VAD, noise, echo, transcription (flat schema)",
         "wss://&lt;foundry&gt;.services.ai.azure.com/voice-live/realtime?api-version=2026-07-15&amp;model=gpt-realtime-mini",
         ("Managed model", "No deployment · service-managed lifecycle", "speech"),
         ("Per-resource Voice Live limits", "100 new connections/min · ≤120K TPM · 60-min sessions<br>Raise via support request · fails under load", WARN_FILL, WARN)),
        ("Realtime API", "GA", BLUE, "#ffffff", False,
         "session.update with instructions, tools, voice, semantic VAD, noise reduction (GA nested schema)",
         "wss://&lt;foundry&gt;.openai.azure.com/openai/v1/realtime?model=&lt;deployment&gt;",
         ("Your Global Standard deployment", "gpt-realtime-2.1-mini · you manage version + upgrade", "openai"),
         ("Deployment quota (RPM units)", "REALTIME_DEPLOYMENT_CAPACITY (default 10)<br>Pooled per subscription + model version · fails at deploy AND under load", BAD_FILL, USER)),
        ("Foundry voice agent", "PREVIEW", WARN, WARN_FILL, True,
         "No session.update and no greeting — the agent owns instructions, tools, voice, greeting, VAD, noise, echo, transcription; bridge streams audio and runs tools",
         "wss://&lt;foundry&gt;.services.ai.azure.com/api/projects/&lt;p&gt;/agents/&lt;a&gt;/endpoint/protocols/voice?api-version=2025-11-15-preview  + Foundry-Features: VoiceAgents=V1Preview",
         ("Versioned agent in a Foundry project", "Managed gpt-realtime-2.1-mini · traces, stored audio, evaluations", "foundry"),
         ("Same per-resource Voice Live limits", "Shared with the Voice Live app on the same resource<br>Agent Service: 60-min sessions · Entra ID only", WARN_FILL, WARN)),
    ]
    y = 160
    for name, status, color, fill, dashed, sends, url, model, limit in rows:
        p.group("", 40, y - 10, 1720, 200, color, fill if dashed else "none", dashed)
        head = p.tile(name, status, 60, y + 40, 200, 100, color, None, fill, dashed)
        s = p.note(sends, xs[0], y + 40, 320, 100, color, "#ffffff", "middle")
        u = p.note(f"<font face='Consolas'>{url}</font>", xs[1], y + 40, 320, 100, color, "#ffffff", "middle")
        m = p.tile(model[0], model[1], xs[2], y + 40, 340, 100, color, model[2], "#ffffff", dashed)
        lim = p.note(f"<b>{limit[0]}</b><br>{limit[1]}", xs[3], y + 30, 340, 120, limit[3], limit[2], "middle")
        p.edge(head, s, color, exit_=R)
        p.edge(s, u, color, exit_=R)
        p.edge(u, m, color, exit_=R)
        p.edge(m, lim, color, exit_=R, dashed=True)
        y += 220
    p.note("<b>Same in all three:</b> browser UI · ACS and Twilio adapters · admission control · search_knowledge_base RAG tool (function tools are executed by the bridge; for the voice agent they are declared on the agent) · metrics · load probe. "
           "The voice agent is created from config/agent-profile.json by scripts/create-voice-agent.py (azd postprovision hook).",
           40, 820, 1720, 60, GREY, "#F3F2F1", "middle")
    return p


def page_call_flow() -> Page:
    p = Page("call", "3 - Phone call flow", 1800, 780)
    p.title("How a phone call reaches the agent (ACS shown; Twilio is equivalent)",
            "Slots are reserved when the call arrives and claimed when media connects, so extra callers get the overflow number instead of dead air.")
    caller = p.tile("📞 Caller", "dials the ACS number", 40, 120, 200, 80, USER)
    acs = p.tile("Azure Communication Services", "Call Automation", 330, 120, 260, 80, BLUE, "acs")
    eg = p.tile("Event Grid", "IncomingCall event", 330, 320, 260, 70, BLUE, "eg")
    hook = p.tile("App · /telephony/acs/events", "checks ACS_EVENTGRID_SECRET", 680, 320, 280, 70, BLUE, "aca")
    hub = p.tile("SessionHub", "reserve slot (30 s) · claim on media", 680, 480, 280, 70, BLUE)
    busy = p.tile("🔁 Overflow / busy", "redirect to TELEPHONY_OVERFLOW_NUMBER or reject", 330, 480, 260, 80, USER, None, BAD_FILL)
    media = p.tile("App · /telephony/acs/media", "per-call HMAC token · pcm24KMono", 680, 120, 280, 80, BLUE, "aca")
    bridge = p.tile("Bridge", "audio in/out · barge-in · tool calls", 1060, 120, 260, 80, BLUE)
    up = p.tile("Upstream", "Voice Live · Realtime · voice agent", 1420, 120, 320, 80, AI, "speech")
    rag = p.tile("search_knowledge_base", "Azure AI Search (managed identity)", 1060, 320, 260, 80, AI, "search")

    p.edge(caller, acs, USER, "1 call", exit_=R)
    p.edge(acs, eg, BLUE, "2 IncomingCall", exit_="exitX=0.5;exitY=1;", entry="entryX=0.5;entryY=0;")
    p.edge(eg, hook, BLUE, "3 webhook", exit_=R)
    p.edge(hook, hub, BLUE, "4 reserve", exit_="exitX=0.5;exitY=1;", entry="entryX=0.5;entryY=0;")
    p.edge(hub, busy, USER, "no slot", exit_="exitX=0;exitY=0.5;", entry="entryX=1;entryY=0.5;", dashed=True)
    p.edge(hook, acs, BLUE, "5 answer_call (bidirectional media)", exit_="exitX=0.5;exitY=0;", entry="entryX=1;entryY=0.8;", dashed=True, pos=0.2)
    p.edge(acs, media, BLUE, "6 media WebSocket", exit_="exitX=1;exitY=0.3;", entry="entryX=0;entryY=0.3;", both=True)
    p.edge(media, bridge, BLUE, "7 AudioData", exit_=R, both=True)
    p.edge(bridge, up, AI, "8 input_audio_buffer.append", exit_=R, both=True, pos=0.1)
    p.edge(bridge, rag, AI, "9 function call → RAG", exit_="exitX=0.5;exitY=1;", entry="entryX=0.5;entryY=0;")
    p.note(
        "<b>10 · Agent speaks</b> — upstream audio → bridge → <i>AudioData</i> to ACS → caller.<br>"
        "<b>11 · Caller interrupts</b> — upstream speech_started → bridge sends <i>StopAudio</i> (ACS) or <i>clear</i> (Twilio) so queued speech stops.<br>"
        "<b>12 · Hang-up</b> — media socket closes → bridge closes upstream → slot released → voice_session_end logged with channel.",
        1060, 480, 680, 90, BLUE, "#EFF6FC", "middle")
    p.note(
        "<b>Twilio / PBX path</b>: Twilio number or SIP Domain → signed POST /telephony/twilio/voice (reserve slot) → "
        "TwiML &lt;Connect&gt;&lt;Stream&gt; with token → /telephony/twilio/media (claim) → μ-law 8 kHz ↔ PCM16 24 kHz → same bridge.",
        40, 620, 1700, 50, GREY, "#F3F2F1", "middle")
    return p


def page_deployment() -> Page:
    p = Page("deploy", "4 - Deployment and regions", 1800, 980)
    p.title("What gets deployed where (shared single-endpoint mode)",
            "One subscription. AI resources in AZURE_LOCATION; each app tier in AZURE_APP_LOCATION (set it when Container Apps capacity is constrained).")
    p.group("Subscription (AZURE_SUBSCRIPTION_ID)", 40, 110, 1720, 830, GREY, "none", False)
    p.group("platform/ · rg-<platform-env> · AZURE_LOCATION (centralus)", 70, 150, 620, 560, AI)
    p.tile("Foundry resource (AIServices)", "disableLocalAuth · allowProjectManagement", 100, 200, 560, 80, AI, "foundry")
    p.tile("Realtime deployment", "GlobalStandard · capacity REALTIME_DEPLOYMENT_CAPACITY (RPM units)", 130, 300, 530, 70, AI, "openai")
    p.tile("Project 'voice-agents'", "holds the Foundry voice agent (preview)", 130, 390, 530, 70, WARN, "foundry", WARN_FILL, True)
    p.tile("Azure AI Search", "Basic · semantic ranker · key auth off", 100, 490, 560, 70, AI, "search")
    p.tile("Communication Services", "global · phone numbers bought in portal", 100, 590, 560, 70, BLUE, "acs")

    ys = [150, 410, 670]
    apps = [("examples/voice-live-api", BLUE, False), ("examples/realtime-api", BLUE, False), ("examples/foundry-voice-agent (preview)", WARN, True)]
    hooks = ["", "preprovision: check-realtime-quota.ps1", "postprovision: create-voice-agent.py"]
    for (name, color, dashed), y, hook in zip(apps, ys, hooks):
        p.group(f"{name} · rg-<env> · AZURE_APP_LOCATION", 760, y, 960, 240, color, WARN_FILL if dashed else "none", True)
        p.tile("Container App", "one replica · /ws /telephony/*", 790, y + 50, 280, 70, BLUE, "aca")
        p.tile("Container Registry", "remote build", 1090, y + 50, 280, 70, BLUE, "acr")
        p.tile("Log Analytics", "console logs", 1390, y + 50, 300, 70, BLUE, "log")
        p.tile("Managed identity", "Foundry role · Search reader · ACS contributor", 790, y + 140, 280, 70, BLUE, "mi")
        if hook:
            p.note(f"<b>azd hook</b><br>{hook}", 1090, y + 140, 600, 70, color, "#ffffff")
    p.note("<b>Order</b>: 1 platform azd provision → 2 scripts/load-knowledge-index.py → 3 buy ACS number → "
           "4 scripts/use-shared-platform.ps1 -Example &lt;x&gt; [-AppLocation eastus2] → 5 azd up per example → 6 scripts/configure-telephony.ps1",
           70, 740, 620, 80, GREY, "#F3F2F1", "middle")
    p.note("<b>Roles granted to each app identity</b> (shared-access.bicep)<br>"
           "• Foundry: Cognitive Services User + Foundry User (Voice Live, voice agent) or Cognitive Services OpenAI User (Realtime)<br>"
           "• Azure AI Search: Search Index Data Reader · ACS: Contributor (Call Automation)<br>"
           "• Deploying user: Foundry/OpenAI roles + Search contributor roles (agent creation, index load)",
           70, 840, 620, 90, AI, "#F4EFFA", "middle")
    return p


def build() -> str:
    pages = [page_architecture(), page_three_ways(), page_call_flow(), page_deployment()]
    return '<mxfile host="Electron" modified="2026-09-29T00:00:00.000Z" version="26.0.0">' + "".join(p.xml() for p in pages) + "</mxfile>\n"


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}")
