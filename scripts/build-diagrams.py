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
             pos: float = 0.0, both: bool = False, straight: bool = False,
             points: list[tuple[int, int]] | None = None, offset: tuple[int, int] = (0, 0)) -> str:
        cid = self._id("e")
        style = (
            ("" if straight else "edgeStyle=orthogonalEdgeStyle;") + f"rounded=1;html=1;endArrow=classic;strokeColor={color};strokeWidth=2;"
            f"dashed={1 if dashed else 0};" + ("startArrow=classic;" if both else "") + exit_ + entry
        )
        self.cells.append(
            f'<mxCell id="{cid}" style="{style}" edge="1" parent="1" source="{src}" target="{dst}">'
            + ('<mxGeometry relative="1" as="geometry"><Array as="points">'
               + "".join(f'<mxPoint x="{px}" y="{py}" />' for px, py in points)
               + '</Array></mxGeometry></mxCell>' if points else '<mxGeometry relative="1" as="geometry" /></mxCell>')
        )
        if label:
            self.cells.append(
                f'<mxCell id="{cid}l" value="{a(escape(label))}" style="edgeLabel;html=1;align=center;verticalAlign=middle;resizable=0;points=[];'
                f'fontColor={color};fontSize=10;fontStyle=1;labelBackgroundColor=#ffffff;" connectable="0" vertex="1" parent="{cid}">'
                f'<mxGeometry x="{pos}" y="0" relative="1" as="geometry"><mxPoint x="{offset[0]}" y="{offset[1]}" as="offset" /></mxGeometry></mxCell>'
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
    p.title("Voice agent comparison: three apps, shared bridge code, one Foundry resource",
            "Shared-platform mode shown. Each app uses a distinct upstream route; browser and phone channels reuse the same bridge implementation.")

    p.group("👥 Callers", 40, 110, 250, 640, USER)
    browser = p.tile("🎙️ Browser", "Microphone · PCM16 24 kHz", 60, 160, 210, 70, USER)
    pstn = p.tile("📞 PSTN caller", "Any phone", 60, 290, 210, 70, USER)
    pbx = p.tile("☎️ PBX (Asterisk)", "SIP trunk via Twilio, or WSS media (Asterisk chan_websocket)", 60, 580, 210, 80, USER)
    sbc = p.tile("🏢 Contact center / SBC", "Existing platform", 60, 430, 210, 80, USER)

    p.group("📡 Telephony (optional)", 330, 110, 290, 640, BLUE)
    acs = p.tile("Azure Communication Services", "Phone number or Direct Routing · Call Automation", 350, 250, 250, 90, BLUE, "acs")
    eg = p.tile("Event Grid", "IncomingCall → /telephony/acs/events", 350, 380, 250, 70, BLUE, "eg")
    twilio = p.tile("Twilio", "Number or SIP Domain · Media Streams", 350, 580, 250, 80, BLUE)

    p.group("⚡ App tier · each app in AZURE_APP_LOCATION", 660, 110, 520, 830, BLUE)
    core = p.note(
        "<b>Shared core code (runs separately in each app)</b><br>"
        "• /ws browser · /telephony/acs · /telephony/twilio · /telephony/asterisk<br>"
        "• Audio adapters: PCM 24 kHz (ACS, Asterisk slin24) · μ-law 8 kHz ↔ 24 kHz (Twilio)<br>"
        "• SessionHub: MAX_CONCURRENT_SESSIONS per app, shared across its channels<br>"
        "• RealtimeStyleBridge: barge-in, tool calls, history trim, metrics<br>"
        "• Tools: search_knowledge_base (RAG) · record lookup · time",
        690, 160, 460, 150, BLUE, "#EFF6FC")
    vl_app = p.tile("examples/voice-live-api", "VoiceLiveBridge · sends instructions + tools", 690, 350, 460, 70, BLUE, "aca")
    rt_app = p.tile("examples/realtime-api", "RealtimeApiBridge · GA nested schema", 690, 450, 460, 70, BLUE, "aca")
    va_app = p.tile("examples/foundry-voice-agent  (preview)", "VoiceAgentBridge · no session config · agent owns greeting + audio", 690, 550, 460, 70, WARN, "aca", WARN_FILL, True)
    p.tile("Container Registry", "remote build", 690, 660, 220, 60, BLUE, "acr")
    p.tile("Log Analytics", "voice_turn · channel", 930, 660, 220, 60, BLUE, "log")
    p.tile("Managed identity", "Entra ID · no keys", 690, 740, 220, 60, BLUE, "mi")
    p.note("One replica per app; one counter for its browser + phone sessions.<br>ACR, logs and identity are also per app.", 930, 740, 220, 80)
    rag = p.tile("Shared RAG tool · executed in each app", "search_knowledge_base · managed identity", 690, 840, 460, 70, TEAL)

    p.group("🧠 AI resources · AZURE_LOCATION (e.g. centralus)", 1220, 110, 640, 830, AI)
    p.group("ONE Foundry resource · three API routes", 1240, 150, 600, 510, AI, "#FAF8FF", False)
    vl = p.tile("Voice Live API · model mode", "Managed gpt-realtime-mini · no deployment", 1260, 340, 560, 80, AI, "speech")
    rt = p.tile("Azure OpenAI Realtime API", "Global Standard deployment gpt-realtime-2.1-mini", 1260, 440, 560, 80, AI, "openai")
    va = p.tile("Foundry voice agent (project route)", "Project 'voice-agents' · versioned agent · managed gpt-realtime-2.1-mini", 1260, 540, 560, 80, WARN, "foundry", WARN_FILL, True)
    search = p.tile("Azure AI Search · separate resource", "index 'knowledge' · 40 articles · keyword + semantic ranker", 1260, 840, 560, 70, TEAL, "search")
    p.note("<b>Shared data, app-side tools</b><br>RAG can also use local knowledge-base.json when Search is not configured.<br>Record lookup reads 30 local sample-data.json records, not the Search index.",
           1260, 725, 560, 85, TEAL, "#F0FAFA", "middle")
    p.note(
        "<b>Capacity</b><br>"
        "• Voice Live + voice agent: per-resource Voice Live limits (100 new connections/min, ≤120K TPM) — <b>shared</b> by both<br>"
        "• Realtime: deployment capacity units (1 = 10K TPM + 20 RPM; often 10 = 100K TPM) — separate pool<br>"
        "• Voice agent is <b>public preview</b>",
        1260, 195, 560, 120, WARN, WARN_FILL, "middle")

    p.edge(browser, core, USER, "WSS /ws", exit_="exitX=1;exitY=0.5;", entry="entryX=0;entryY=0.2;", pos=-0.5)
    p.edge(pstn, acs, USER, "", exit_=R.split("entry")[0], entry="entryX=0;entryY=0.3;")
    p.edge(sbc, acs, USER, "Direct Routing", exit_="exitX=1;exitY=0.5;", entry="entryX=0;entryY=0.8;", pos=-0.5)
    p.edge(pbx, twilio, USER, "SIP", exit_="exitX=1;exitY=0.5;", entry="entryX=0;entryY=0.5;")
    p.edge(pbx, core, USER, "WSS media (chan_websocket)", exit_="exitX=0.5;exitY=1;", entry="entryX=0;entryY=0.93;", dashed=True, pos=-0.4, straight=True,
           points=[(165, 730), (640, 730), (640, 300)])
    p.edge(acs, eg, BLUE, "", exit_="exitX=0.5;exitY=1;", entry="entryX=0.5;entryY=0;")
    p.edge(eg, core, BLUE, "webhook", exit_="exitX=1;exitY=0.5;", entry="entryX=0;entryY=0.75;", pos=0.1, straight=True)
    p.edge(acs, core, BLUE, "media WS", exit_="exitX=1;exitY=0.3;", entry="entryX=0;entryY=0.5;", pos=0.0, both=True, straight=True)
    p.edge(twilio, core, BLUE, "Media Streams", exit_="exitX=1;exitY=0.5;", entry="entryX=0;entryY=0.95;", pos=0.1, both=True, straight=True)
    p.edge(vl_app, vl, AI, "model", exit_=R, entry="", pos=0.0)
    p.edge(rt_app, rt, AI, "deployment", exit_=R, entry="", pos=0.0)
    p.edge(va_app, va, WARN, "project route", exit_=R, entry="", dashed=True, pos=0.0)
    p.edge(rag, search, TEAL, "HTTPS query", exit_=R, both=True, offset=(0, -18))
    p.note("<b>When an app is full:</b> browser → busy + close 1013; ACS/Twilio → configured overflow number or busy/reject; Asterisk → HANGUP (dialplan handles fallback). No built-in human queue.<br>"
           "<b>Standalone mode:</b> each example has its own Foundry resource + project. Shared mode pools Voice Live service limits, not the three apps' admission counters. Confirm effective service limits before sizing.",
           40, 970, 1820, 60, GREY, "#F3F2F1", "middle")
    return p


def page_three_ways() -> Page:
    p = Page("ways", "2 - Three ways to connect", 1800, 900)
    p.title("Three ways to connect the shared bridge implementation", "What each app sends, its upstream route, where the model lives, and what limits capacity. Endpoint lines wrap for readability.")
    headers = ["What the bridge sends", "WebSocket endpoint", "Model / agent", "What limits capacity"]
    xs = [300, 660, 1020, 1400]
    for x, h in zip(xs, headers):
        p.raw(p._id("h"), h, "text;html=1;fontSize=13;fontStyle=1;fontColor=#323130;align=center;", x, 110, 320 if x < 1400 else 360, 30)
    rows = [
        ("Voice Live API", "GA", AI, "#ffffff", False,
         "session.update with instructions, tools, voice, VAD, noise, echo, transcription (flat schema)",
         "wss://&lt;foundry&gt;.services.ai.azure.com<br>/voice-live/realtime<br>?api-version=2026-07-15<br>&amp;model=gpt-realtime-mini",
         ("Managed model", "No deployment · service-managed lifecycle", "speech"),
         ("Per-resource Voice Live limits", "100 new connections/min · ≤120K TPM · 60-min sessions<br>Raise via support request · fails under load", WARN_FILL, WARN)),
        ("Realtime API", "GA", BLUE, "#ffffff", False,
         "session.update with instructions, tools, voice, semantic VAD, noise reduction (GA nested schema)",
         "wss://&lt;foundry&gt;.openai.azure.com<br>/openai/v1/realtime<br>?model=&lt;deployment&gt;",
         ("Your Global Standard deployment", "gpt-realtime-2.1-mini · you manage version + upgrade", "openai"),
         ("Deployment capacity units", "REALTIME_DEPLOYMENT_CAPACITY (default 10 = 100K TPM / 200 RPM)<br>Pooled per subscription + model version · fails at deploy AND under load", BAD_FILL, USER)),
        ("Foundry voice agent", "PREVIEW", WARN, WARN_FILL, True,
         "No session.update and no greeting — the agent owns instructions, tools, voice, greeting, VAD, noise, echo, transcription; bridge streams audio and runs tools",
         "wss://&lt;foundry&gt;.services.ai.azure.com<br>/api/projects/&lt;p&gt;/agents/&lt;a&gt;<br>/endpoint/protocols/voice<br>?api-version=2025-11-15-preview<br><br>Header: Foundry-Features:<br>VoiceAgents=V1Preview",
         ("Versioned agent in a Foundry project", "Managed gpt-realtime-2.1-mini · traces, stored audio, evaluations", "foundry"),
         ("Same per-resource Voice Live limits", "Shared with the Voice Live app on the same resource<br>Agent Service: 60-min sessions · Entra ID only", WARN_FILL, WARN)),
    ]
    y = 160
    for name, status, color, fill, dashed, sends, url, model, limit in rows:
        p.group("", 40, y - 10, 1720, 200, color, fill if dashed else "none", dashed)
        head = p.tile(name, status, 60, y + 45, 200, 100, color, None, fill, dashed)
        s = p.note(sends, xs[0], y + 35, 320, 120, color, "#ffffff", "middle")
        u = p.note(f"<font face='Consolas'>{url}</font>", xs[1], y + 15, 320, 160, color, "#ffffff", "middle")
        m = p.tile(model[0], model[1], xs[2], y + 45, 340, 100, color, model[2], "#ffffff", dashed)
        lim = p.note(f"<b>{limit[0]}</b><br>{limit[1]}", xs[3], y + 35, 340, 120, limit[3], limit[2], "middle")
        p.edge(head, s, color, exit_=R)
        p.edge(s, u, color, exit_=R)
        p.edge(u, m, color, exit_=R)
        p.edge(m, lim, color, exit_=R, dashed=True)
        y += 220
    p.note("<b>Same code in all three:</b> browser UI · ACS, Twilio, and Asterisk (chan_websocket) adapters · per-app admission control · search_knowledge_base RAG tool (function tools are executed by the bridge; for the voice agent they are declared on the agent) · metrics · load probe. "
           "The voice agent is created from config/agent-profile.json by scripts/create-voice-agent.py (azd postprovision hook).",
           40, 820, 1720, 60, GREY, "#F3F2F1", "middle")
    return p


def page_call_flow() -> Page:
    p = Page("call", "3 - Phone call flow", 1800, 820)
    p.title("How a phone call reaches the agent (ACS shown; Twilio and Asterisk paths below)",
            "ACS/Twilio reserve on the incoming webhook and claim on media; Asterisk admits on MEDIA_START. All channels share their app's SessionHub.")
    caller = p.tile("📞 Caller", "dials the ACS number", 40, 140, 200, 90, USER)
    acs = p.tile("Azure Communication Services", "Call Automation", 320, 140, 260, 90, BLUE, "acs")
    eg = p.tile("Event Grid", "IncomingCall event", 320, 350, 260, 80, BLUE, "eg")
    hook = p.tile("ACS event webhook", "/telephony/acs/events · validates shared secret", 720, 350, 300, 80, BLUE, "aca")
    hub = p.tile("SessionHub · per app", "reserve slot (30 s) · claim on media", 720, 520, 300, 80, BLUE)
    busy = p.tile("🔁 Overflow / busy", "ACS redirects to configured number or rejects", 320, 520, 260, 80, USER, None, BAD_FILL)
    media = p.tile("ACS media endpoint", "/telephony/acs/media · per-call HMAC token", 720, 140, 300, 90, BLUE, "aca")
    bridge = p.tile("Bridge", "audio · barge-in · tool execution", 1180, 140, 220, 90, BLUE)
    up = p.tile("Upstream", "Voice Live / Realtime / voice agent", 1530, 140, 230, 90, AI, "speech")
    rag = p.tile("search_knowledge_base · executed by the bridge", "Azure AI Search (managed identity), or local JSON", 1180, 350, 580, 80, TEAL, "search")

    p.edge(caller, acs, USER, "1 · Call", exit_=R, offset=(0, -18))
    p.edge(acs, eg, BLUE, "2 · IncomingCall", exit_="exitX=0.5;exitY=1;", entry="entryX=0.5;entryY=0;")
    p.edge(eg, hook, BLUE, "3 · Webhook", exit_=R)
    p.edge(hook, hub, BLUE, "4 · Reserve", exit_="exitX=0.5;exitY=1;", entry="entryX=0.5;entryY=0;")
    p.edge(hub, busy, USER, "no slot", exit_="exitX=0;exitY=0.5;", entry="entryX=1;entryY=0.5;", dashed=True)
    p.edge(hook, acs, BLUE, "5 · Answer call + start media", exit_="exitX=0.5;exitY=0;", entry="entryX=1;entryY=0.8;", dashed=True,
              points=[(870, 280), (635, 280), (635, 212)], straight=True, offset=(0, -16))
    p.edge(acs, media, BLUE, "6 · WSS media", exit_=R, both=True, offset=(0, -18))
    p.edge(media, hub, BLUE, "claim slot", exit_="exitX=1;exitY=0.8;", entry="entryX=1;entryY=0.5;", dashed=True,
              points=[(1090, 212), (1090, 560)], straight=True, offset=(35, 0))
    p.edge(media, bridge, BLUE, "7 · PCM24 audio", exit_=R, both=True, offset=(0, -18))
    p.edge(bridge, up, AI, "8 · Audio + events", exit_=R, both=True, offset=(0, -18))
    p.edge(bridge, rag, TEAL, "9 · Tool call / result", exit_="exitX=0.5;exitY=1;", entry="entryX=0.19;entryY=0;", both=True)
    p.note("<b>Upstream direction</b><br>In: input_audio_buffer.append<br>Out: audio deltas + events", 1470, 250, 290, 75, AI, "#F4EFFA", "middle")
    p.note(
        "<b>10 · Agent speaks</b> — upstream audio → bridge → <i>AudioData</i> to ACS → caller.<br>"
        "<b>11 · Caller interrupts</b> — upstream speech_started → bridge sends <i>StopAudio</i> (ACS), <i>clear</i> (Twilio), or <i>FLUSH_MEDIA</i> (Asterisk) so queued speech stops.<br>"
        "<b>12 · Hang-up</b> — media socket closes → bridge closes upstream → slot released → voice_session_end logged with channel.",
        1180, 480, 580, 140, BLUE, "#EFF6FC", "middle")
    p.note(
        "<b>Twilio path</b>: Twilio number or SIP Domain → signed POST /telephony/twilio/voice (reserve slot) → "
        "TwiML &lt;Connect&gt;&lt;Stream&gt; with token → /telephony/twilio/media (claim) → μ-law 8 kHz ↔ PCM16 24 kHz → same bridge.<br>"
        "<b>Full:</b> busy message, with a Dial fallback when an overflow number is configured.",
        40, 660, 840, 100, GREY, "#F3F2F1", "middle")
    p.note(
        "<b>Asterisk path</b>: Dial(WebSocket/voice_agent/c(slin24)f(json)) → WSS /telephony/asterisk/media "
        "(Basic auth: ASTERISK_WEBSOCKET_SECRET) → MEDIA_START → admission → slin24 frames = bridge format (no resampling).<br>"
        "<b>Full:</b> HANGUP; configure the dialplan fallback. Barge-in uses FLUSH_MEDIA.",
        920, 660, 840, 100, GREY, "#F3F2F1", "middle")
    return p


def page_deployment() -> Page:
    p = Page("deploy", "4 - Deployment and regions", 1800, 1120)
    p.title("What gets deployed where (shared-resource mode)",
            "One subscription. AI resources in AZURE_LOCATION; each app tier in AZURE_APP_LOCATION (set it when Container Apps capacity is constrained).")
    p.group("Subscription (AZURE_SUBSCRIPTION_ID)", 40, 110, 1720, 970, GREY, "none", False)
    p.group("platform/ · rg-<platform-env> · AZURE_LOCATION", 70, 150, 620, 610, AI)
    p.group("ONE Foundry resource · AIServices S0", 90, 200, 580, 310, AI, "#FAF8FF", False)
    p.tile("Managed Voice Live models", "disableLocalAuth · allowProjectManagement", 110, 240, 540, 60, AI, "foundry")
    p.tile("Realtime deployment", "GlobalStandard · REALTIME_DEPLOYMENT_CAPACITY units (1 = 10K TPM + 20 RPM)", 110, 320, 540, 70, AI, "openai")
    p.tile("Project 'voice-agents'", "holds the Foundry voice agent (preview)", 110, 410, 540, 70, WARN, "foundry", WARN_FILL, True)
    p.tile("Azure AI Search · separate resource", "Basic · semantic ranker · key auth off · 'knowledge' index (40 articles)", 100, 530, 560, 70, TEAL, "search")
    p.tile("Communication Services · optional", "global · configure a number or Direct Routing for ACS calls", 100, 620, 560, 70, BLUE, "acs")
    p.note("<b>Platform preprovision:</b> check-realtime-quota.ps1 -Platform<br>Checks quota for the shared Realtime deployment before provisioning.",
           100, 700, 560, 45, AI, "#ffffff", "middle")

    ys = [150, 450, 750]
    apps = [("examples/voice-live-api", BLUE, False), ("examples/realtime-api", BLUE, False), ("examples/foundry-voice-agent (preview)", WARN, True)]
    details = [
        "<b>Per-app admission</b><br>Browser, ACS, Twilio and Asterisk share this app's SessionHub.<br>The other two apps have their own counters.",
        "<b>Realtime preprovision</b><br>Quota check skips in shared mode: the platform owns the deployment.<br>Standalone mode checks quota in this example instead.",
        "<b>Voice-agent postprovision</b><br>create-voice-agent.py publishes the agent in the shared project.<br>Repeat after profile edits; the bridge still executes function tools.",
    ]
    for (name, color, dashed), y, detail in zip(apps, ys, details):
        p.group(f"{name} · rg-<env> · AZURE_APP_LOCATION", 760, y, 960, 290, color, WARN_FILL if dashed else "none", True)
        p.tile("Container App", "one replica · browser + phone channels", 790, y + 50, 280, 80, BLUE, "aca")
        p.tile("Container Registry", "remote build · AcrPull", 1090, y + 50, 280, 80, BLUE, "acr")
        p.tile("Log Analytics", "console logs", 1390, y + 50, 300, 80, BLUE, "log")
        p.tile("Managed identity", "keyless access · roles listed at left", 790, y + 155, 280, 90, BLUE, "mi")
        p.note(detail, 1090, y + 155, 600, 90, color, "#ffffff", "middle")
    p.note("<b>Deploy</b>: platform azd provision → load-knowledge-index.py →<br>"
           "use-shared-platform.ps1 -Example &lt;x&gt; → azd up per example.<br>"
           "<b>Optional phones</b>: select acs, twilio, asterisk; configure the provider.<br>"
           "Use configure-telephony.ps1 for ACS/Twilio or Asterisk websocket_client.conf.<br>"
           "<b>Standalone instead</b>: each example owns its Foundry resource + project; "
           "knowledge/ can supply Search via use-knowledge-base.ps1.",
           70, 780, 620, 130, GREY, "#F3F2F1", "middle")
    p.note("<b>Roles granted to each app identity</b> (shared-access.bicep)<br>"
           "• Foundry: Cognitive Services User + Foundry User (Voice Live, voice agent) or Cognitive Services OpenAI User (Realtime)<br>"
           "• Azure AI Search: Search Index Data Reader · ACS: Contributor (Call Automation)<br>"
           "• Deploying user: Foundry/OpenAI roles + Search contributor roles (agent creation, index load)",
           70, 930, 620, 120, AI, "#F4EFFA", "middle")
    return p


def build() -> str:
    pages = [page_architecture(), page_three_ways(), page_call_flow(), page_deployment()]
    return '<mxfile host="Electron" modified="2026-09-30T00:00:00.000Z" version="26.0.0">' + "".join(p.xml() for p in pages) + "</mxfile>\n"


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}")
