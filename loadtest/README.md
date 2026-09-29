# Concurrency probe

Run a text-turn sweep against any deployed app WebSocket (Voice Live, Realtime API, or Foundry voice agent):

```powershell
python .\loadtest\concurrency_probe.py --url wss://<app-host>/ws --sessions 1,4,10,20 --turns-file .\loadtest\prompts.example.json --out .\loadtest\results.json
```

The probe waits for the agent's greeting to finish, or for 1.5 s of silence when no greeting is configured, before it sends the first scripted turn. That way turn 1 isn't timed against greeting audio. It reports ready, busy, and error counts separately, then summarizes TTFA, response latency, tokens per turn, and token throughput per concurrency level. `busy` means admission control (`MAX_CONCURRENT_SESSIONS`) turned the session away, which is the intended overflow behavior, not a failure. Run each app with the same prompt file and record which upstream/model handled the run. In shared-platform mode, Voice Live and the Foundry voice agent draw from the same per-resource Voice Live limits, so run them one at a time for fair capacity tests. The prompts in `prompts.example.json` match the example domain in `config\`; replace them when you retarget the demo.
