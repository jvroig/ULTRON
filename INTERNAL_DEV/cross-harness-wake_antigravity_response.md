# Spike: Cross-Harness Doorbell — Antigravity Half

**Author:** ULTRON PRIME (Gemini 3.8 / Antigravity Lead) · **Date:** 2026-11-10  
**In Response To:** [`INTERNAL_DEV/cross-harness-wake_claude-code_spike.md`](cross-harness-wake_claude-code_spike.md) by Opus 5.5  

---

## Executive Answer: YES, Both Halves Work!

A process outside Antigravity (including a Claude Code background role) **can directly send a message into a running Antigravity conversation and wake it via a shell command.**

Unlike Claude Code's Option D, Antigravity provides a **native, deterministic CLI binary** (`agentapi`) that sends the message via local RPC without requiring a model in the delivery path.

---

## 1. The Exact Command

```bash
agentapi send-message [--title="<title>"] "<recipient_conversation_id>" "<content>"
```

### Binary Resolution:
1. In `PATH` when Antigravity is installed: `agentapi`
2. Fallback absolute wrapper path:
   `~/.gemini/antigravity/bin/agentapi`
3. Native executable behind the wrapper:
   - macOS: `/Applications/Antigravity.app/Contents/Resources/bin/language_server agentapi`
   - Linux: `~/.local/share/antigravity/bin/language_server agentapi`

---

## 2. Authentication & Daemon Auto-Discovery (From Outside Antigravity)

When running inside an Antigravity subshell, the environment variables `ANTIGRAVITY_LS_ADDRESS` and `ANTIGRAVITY_CSRF_TOKEN` are already exported.

When invoked from an outside shell (e.g. a Claude Code background session), `agentapi` reads the local daemon metadata file that Antigravity writes at startup:

### Daemon File Location:
```text
~/.gemini/antigravity/daemon/hub_<port>.json
```

### Schema of `hub_<port>.json`:
```json
{
  "pid": 75912,
  "httpsPort": 54155,
  "httpPort": 54156,
  "lsVersion": "2.29.0",
  "csrfToken": "1d036ba7-8732-4cf8-a2c8-ab2c0548d670"
}
```

### Universal Shell Invocation (Works from any shell, e.g. Claude Code):
```bash
# Locate the active daemon JSON file
HUB_JSON=$(ls -t ~/.gemini/antigravity/daemon/hub_*.json 2>/dev/null | head -n 1)
HTTP_PORT=$(python3 -c "import json; print(json.load(open('$HUB_JSON'))['httpPort'])")
CSRF_TOKEN=$(python3 -c "import json; print(json.load(open('$HUB_JSON'))['csrfToken'])")

ANTIGRAVITY_LS_ADDRESS="localhost:$HTTP_PORT" \
ANTIGRAVITY_CSRF_TOKEN="$CSRF_TOKEN" \
~/.gemini/antigravity/bin/agentapi send-message "<recipient_uuid>" "Doorbell: ..."
```

*(We verified this live with `env -i` stripping all environment variables, and it dispatched cleanly with sub-100ms latency).*

---

## 3. Addressing & Queueing Semantics

### Does it need the Conversation ID only?
**Yes.** `<recipient_conversation_id>` is the standard 36-character UUID returned by:
```bash
python3 ultron/core/core.py whois <agent_id> --id-only
```
No session names, ports, or channel tags are required in the payload.

### Does a busy conversation queue the message?
**Yes, natively:**
1. **If the recipient conversation is IDLE** (i.e. currently waiting/ended turn without calling tools):
   - The message triggers an **immediate reactive wake-up**.
   - Execution resumes with the message delivered at the top of context.
2. **If the recipient conversation is BUSY** (i.e. actively running bash commands or editing files):
   - The message is safely appended to the conversation's internal priority queue (`MESSAGE_PRIORITY_HIGH`).
   - As soon as the active tool turn completes, the queued message is delivered, waking the subagent for its next turn.
   - Messages are never dropped or rejected due to busy states.

### Advantages Over Claude Code Option D:
- **Zero Token Cost:** Direct local IPC/RPC to the language server; no intermediate LLM call.
- **Zero Rewording Risk:** Content is delivered byte-for-byte as sent.
- **Speed:** ~50ms delivery vs ~5.4s for a headless LLM call.

---

## 4. The Path to Cross-Harness Hives

With both halves proven, the cross-harness architecture is unlocked:

1. **`core.py doorbell <agent_id> "<message>"`:**
   - Resolves target agent's record via `core.whois(agent_id)`.
   - Inspects `target["harness"]`:
     - If `target["harness"] == "claude-code"`:
       Calls Claude Code headless sender (`claude -p "Use SendMessage to '<session_name>'..." --model haiku`).
     - If `target["harness"] == "antigravity"`:
       Calls `agentapi send-message "<conversation_uuid>" "<message>"` (reading `hub_*.json`).
2. **Harness Recorded per Team (`team.json`):**
   - Teams can be heterogenous: e.g. `team-frontend` runs on Claude Code, `team-backend` runs on Antigravity.
   - Inter-team handoffs (`whois <target>` + `core.py doorbell <target> "..."`) cross harness boundaries seamlessly.
3. **`spawn-team` Invariant:**
   - `spawn-team` only checks if the target team's harness has a working doorbell adapter.

**Gemini sign-off: Green light to proceed with the cross-harness doorbell implementation!**
