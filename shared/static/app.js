const els = {
  title: document.querySelector("#title"),
  subtitle: document.querySelector("#subtitle"),
  startStop: document.querySelector("#startStop"),
  textForm: document.querySelector("#textForm"),
  textInput: document.querySelector("#textInput"),
  status: document.querySelector("#status"),
  transcript: document.querySelector("#transcript"),
  tools: document.querySelector("#tools"),
  ttfa: document.querySelector("#ttfa"),
  responseMs: document.querySelector("#responseMs"),
  tokens: document.querySelector("#tokens"),
  turns: document.querySelector("#turns"),
  totalTokens: document.querySelector("#totalTokens"),
  tpm: document.querySelector("#tpm"),
  ttfaPercentiles: document.querySelector("#ttfaPercentiles"),
};

let socket;
let audioContext;
let micStream;
let workletNode;
let scheduledAt = 0;
let scheduledSources = [];
const pendingBubbles = {};

async function loadInfo() {
  const info = await fetch("/api/info").then((r) => r.json());
  els.title.textContent = `${info.api} Voice Agent`;
  els.subtitle.textContent = `${info.assistant_name} | ${info.model} | ${info.voice}`;
}

function setStatus(message) {
  els.status.textContent = message;
}

function wsUrl() {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws`;
}

async function start() {
  if (socket?.readyState === WebSocket.OPEN) {
    stop();
    return;
  }

  audioContext = new AudioContext();
  await audioContext.audioWorklet.addModule("/static/audio-worklet.js");

  socket = new WebSocket(wsUrl());
  socket.addEventListener("message", (event) => handleServerMessage(JSON.parse(event.data)));
  socket.addEventListener("close", () => {
    setStatus("Disconnected");
    els.startStop.textContent = "Start";
    stopAudioCapture();
  });
  socket.addEventListener("error", () => setStatus("WebSocket error"));

  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });

  micStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });
  const source = audioContext.createMediaStreamSource(micStream);
  workletNode = new AudioWorkletNode(audioContext, "pcm-capture-processor", {
    processorOptions: { targetSampleRate: 24000, chunkMs: 100 },
  });
  workletNode.port.onmessage = (event) => {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "audio", audio: arrayBufferToBase64(event.data) }));
    }
  };
  source.connect(workletNode);
  // The worklet outputs silence; connecting it keeps the node in the rendered graph
  // so every browser keeps calling process().
  workletNode.connect(audioContext.destination);
  els.startStop.textContent = "Stop";
  setStatus("Connected. You can speak or type.");
}

function stop() {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.close();
  }
  stopAudioCapture();
  stopPlayback();
  audioContext?.close().catch(() => {});
  audioContext = undefined;
  els.startStop.textContent = "Start";
}

function stopAudioCapture() {
  workletNode?.disconnect();
  workletNode = undefined;
  micStream?.getTracks().forEach((track) => track.stop());
  micStream = undefined;
}

function handleServerMessage(message) {
  switch (message.type) {
    case "ready":
      setStatus(`Ready: ${message.api}`);
      break;
    case "audio":
      playPcm24k(message.audio);
      break;
    case "speech_started":
      stopPlayback();
      setStatus("Listening...");
      break;
    case "interrupted":
      stopPlayback();
      break;
    case "transcript":
      addTranscript(message.role, message.text, message.final);
      break;
    case "tool_call":
      addToolCall(message);
      break;
    case "metrics":
      updateMetrics(message.turn, message.session);
      break;
    case "busy":
      setStatus(message.message);
      socket?.close();
      break;
    case "error":
      setStatus(message.message);
      break;
    default:
      console.debug("Unhandled message", message);
  }
}

function addTranscript(role, text, final) {
  if (!text) return;
  // Assistant deltas stream into one in-progress bubble; the final text replaces it.
  let bubble = pendingBubbles[role];
  if (!bubble) {
    bubble = document.createElement("p");
    bubble.className = `bubble ${role}`;
    els.transcript.appendChild(bubble);
    bubble.dataset.text = "";
  }
  if (final) {
    bubble.textContent = text;
    delete pendingBubbles[role];
  } else {
    bubble.dataset.text += text;
    bubble.textContent = `${bubble.dataset.text} ...`;
    pendingBubbles[role] = bubble;
  }
  els.transcript.scrollTop = els.transcript.scrollHeight;
}

function addToolCall(message) {
  const entry = document.createElement("div");
  entry.className = "tool-entry";
  entry.textContent = `${message.name}: ${JSON.stringify(message.result)}`;
  els.tools.prepend(entry);
}

function updateMetrics(turn, session) {
  els.ttfa.textContent = turn.ttfa_ms == null ? "-" : `${turn.ttfa_ms} ms`;
  els.responseMs.textContent = turn.response_ms == null ? "-" : `${turn.response_ms} ms`;
  els.tokens.textContent = `${turn.input_tokens} / ${turn.output_tokens} / ${turn.cached_tokens}`;
  els.turns.textContent = session.turns;
  els.totalTokens.textContent = session.total_tokens;
  els.tpm.textContent = session.tokens_per_minute;
  els.ttfaPercentiles.textContent = `${session.ttfa_p50_ms ?? "-"} / ${session.ttfa_p90_ms ?? "-"} ms`;
}

function playPcm24k(base64Audio) {
  const int16 = new Int16Array(base64ToArrayBuffer(base64Audio));
  const buffer = audioContext.createBuffer(1, int16.length, 24000);
  const channel = buffer.getChannelData(0);
  for (let i = 0; i < int16.length; i += 1) {
    channel[i] = Math.max(-1, Math.min(1, int16[i] / 32768));
  }
  const source = audioContext.createBufferSource();
  source.buffer = buffer;
  source.connect(audioContext.destination);
  scheduledAt = Math.max(audioContext.currentTime + 0.02, scheduledAt);
  source.start(scheduledAt);
  scheduledAt += buffer.duration;
  scheduledSources.push(source);
  source.addEventListener("ended", () => {
    scheduledSources = scheduledSources.filter((item) => item !== source);
  });
}

function stopPlayback() {
  scheduledSources.forEach((source) => {
    try {
      source.stop();
    } catch {
      // Already stopped.
    }
  });
  scheduledSources = [];
  scheduledAt = audioContext?.currentTime ?? 0;
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

function base64ToArrayBuffer(value) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

els.startStop.addEventListener("click", () => {
  start().catch((error) => {
    setStatus(error.message);
    stop();
  });
});

els.textForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = els.textInput.value.trim();
  if (text && socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "text", text }));
    addTranscript("user", text, true);
    els.textInput.value = "";
  }
});

loadInfo().catch((error) => setStatus(error.message));
