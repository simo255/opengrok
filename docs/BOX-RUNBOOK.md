# Grok Bot box runbook (stock host + GLM hop)

Operational guide for a sand box running OpenGrok: GLM hop inference, host
updates, and silent-reply failures. Read after a **sand-host self-update** or when
messages are **accepted but never appear in chat**.

Related:

- [`STOCK-HOST.md`](STOCK-HOST.md) — install and wrap
- [`FAILURE-MODES.md`](FAILURE-MODES.md) — F19 silent SendToUser
- On the box: `/home/box/sand-data/OPENGROK-BOX-RUNBOOK.md` (sand-data copy with
  gateway examples and solvedx agent IDs)

---

## Architecture

```
User (Grok Bot UI)
    ↕  SendToUser only visible in chat
sand-host (host-main.cjs)
    ↕  createProtoSessionProvider wrapped (opengrok-stock-wrap)
opengrok-runtime.cjs (in /home/box/sand-data after install)
    ↕  OpenAI-shaped messages + SendToUser recovery
GLM hop (127.0.0.1:18790 default, or 18792 on ZCode boxes)
```

**Critical:** Plain assistant text is invisible in Grok Bot chat. User-visible
replies require the **`SendToUser`** tool (alias `SendMessage`).

---

## After a sand-host update

On a configured box:

```bash
bash /home/box/sand-data/reinstall-opengrok.sh
```

That script syncs `tools/opengrok-runtime.cjs` from this repo into sand-data,
re-wraps the host, restarts the hop, and bounces sand-host.

After reinstall, run a **ping test** (below). Recovery lives in stock
`tools/opengrok-runtime.cjs` since 2026-09-02 — no manual re-patch unless you
skipped sync.

---

## F19 — GLM JSON-as-text, no chat reply

See [`FAILURE-MODES.md`](FAILURE-MODES.md) § F19.

**Recovery** (`buildSendToUserArgs`, `recoverTextToolCalls` in
`tools/opengrok-runtime.cjs`):

- Detects hop text like `{"type":"text","content":"Pong","end_turn":true}`
- Emits tool **`SendToUser`** with `{"type":"text","content":"…"}`
- Log: `recovered text tool-call -> SendToUser`
- Transcript: `messageId: t…sN` on success

**Wrong shapes that fail** (historical bug):

- Tool name `send_message` without host alias match
- Args `{text:{content}}` — old proto shape; current host expects `type` + `content`

---

## Diagnosis

| Check | Healthy |
|-------|---------|
| `/tmp/opengrok-session.log` | `route … -> http://127.0.0.1:…` |
| After user message | `recovered text tool-call -> SendToUser` or native tool call |
| Agent transcript jsonl | `messageId: t…sN` after user tag |
| `send-acceptance.json` | `accepted: true` |

Ping test: gateway `sendPrompt` with `"Ping"`, then inspect log + transcript
within ~30s.

---

## Changelog

| Date | Change |
|------|--------|
| 2026-09-02 | SendToUser recovery in `opengrok-runtime.cjs`; BOX-RUNBOOK added |
