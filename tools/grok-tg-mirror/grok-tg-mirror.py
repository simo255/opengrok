#!/usr/bin/env python3
"""Mirror Grok Bot send_message (SendToUser) deliveries to Telegram.

Tails agent transcript JSONL under sand-data/agent-transcripts, forwards each
successful send_message after human_text cleanup. Does not read telegram tokens
into logs.

Install: copy this directory to ~/bin or set GROK_TG_MIRROR_BIN in ctl.
Env: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID in a dotenv file (see GROK_TG_MIRROR_ENV).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
try:
    from telegram_human_text import human_text
except ImportError:
    def human_text(text: str) -> str:  # type: ignore[misc]
        return (text or "").strip()

UUID_DIR = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
TRANSCRIPTS_ROOT = Path(
    os.environ.get(
        "GROK_TG_MIRROR_TRANSCRIPTS",
        os.path.expanduser("~/sand-data/agent-transcripts"),
    )
)
AGENTS_ROOT = Path(
    os.environ.get(
        "GROK_TG_MIRROR_AGENTS_ROOT",
        os.path.expanduser("~/sand-data/agents"),
    )
)
ENV_FILE = Path(
    os.environ.get(
        "GROK_TG_MIRROR_ENV",
        os.environ.get(
            "SOLVEDX_TG_ENV",
            os.path.expanduser("~/.config/solvedx-researcher/telegram.env"),
        ),
    )
)
STATE_DIR = Path(
    os.environ.get(
        "GROK_TG_MIRROR_STATE",
        os.path.expanduser("~/.local/state/grok-tg-mirror"),
    )
)
LOG = Path(os.environ.get("GROK_TG_MIRROR_LOG", "/tmp/grok-tg-mirror.log"))
POLL_SEC = float(os.environ.get("GROK_TG_MIRROR_POLL_SEC", "1.5"))
API = "https://api.telegram.org"
DRY_RUN = os.environ.get("GROK_TG_MIRROR_DRY_RUN", "").strip() in ("1", "true", "yes")
AGENT_FILTER = os.environ.get("GROK_TG_MIRROR_AGENT_IDS", "").strip()


def log(msg: str) -> None:
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(line + "\n")
    if sys.stdout.isatty():
        print(line, flush=True)


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        k, v = raw.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def tg(token: str, method: str, data: dict | None = None, timeout: int = 30) -> dict:
    url = f"{API}/bot{token}/{method}"
    body = urllib.parse.urlencode(data or {}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode(errors="replace")[:400]
        raise RuntimeError(f"telegram {method} HTTP {e.code}: {err}") from e


def chunks(text: str, n: int = 3900) -> list[str]:
    text = text.strip() or "(empty)"
    return [text[i : i + n] for i in range(0, len(text), n)]


def send_text(token: str, chat_id: str, text: str) -> None:
    parts = chunks(text)
    if len(parts) > 50:
        parts = parts[:50]
        parts[-1] += "\n\n[truncated]"
    for part in parts:
        if DRY_RUN:
            log(f"dry-run send {len(part)} chars")
            continue
        tg(
            token,
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": part,
                "disable_web_page_preview": "true",
            },
            timeout=30,
        )


def extract_send_text(inp: dict | None) -> str:
    if not inp:
        return ""
    text_field = inp.get("text")
    if isinstance(text_field, dict):
        return (text_field.get("content") or "").strip()
    if isinstance(text_field, str):
        return text_field.strip()
    if inp.get("type") == "text":
        msg = inp.get("message") or inp.get("content")
        if isinstance(msg, str):
            return msg.strip()
    return ""


def agent_name(agent_id: str) -> str:
    profile = AGENTS_ROOT / agent_id / "profile.json"
    if not profile.is_file():
        return agent_id[:8]
    try:
        data = json.loads(profile.read_text())
        name = (data.get("name") or "").strip()
        return name if name else agent_id[:8]
    except Exception:
        return agent_id[:8]


def allowed_agent(agent_id: str) -> bool:
    if not AGENT_FILTER:
        return True
    allowed = {x.strip() for x in AGENT_FILTER.split(",") if x.strip()}
    return agent_id in allowed


def discover_transcripts() -> dict[str, Path]:
    out: dict[str, Path] = {}
    if not TRANSCRIPTS_ROOT.is_dir():
        return out
    for child in TRANSCRIPTS_ROOT.iterdir():
        if not child.is_dir() or child.name.startswith("sand-subagent"):
            continue
        if not UUID_DIR.match(child.name):
            continue
        if not allowed_agent(child.name):
            continue
        path = child / f"{child.name}.jsonl"
        if path.is_file():
            out[str(path)] = path
    return out


def load_state() -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = STATE_DIR / "state.json"
    if not p.is_file():
        return {"seen": [], "files": {}, "pending": {}}
    try:
        data = json.loads(p.read_text())
    except Exception:
        return {"seen": [], "files": {}, "pending": {}}
    data.setdefault("seen", [])
    data.setdefault("files", {})
    data.setdefault("pending", {})
    return data


def save_state(state: dict) -> None:
    p = STATE_DIR / "state.json"
    tmp = STATE_DIR / "state.json.tmp"
    seen = state.get("seen", [])
    if len(seen) > 20000:
        state["seen"] = seen[-15000:]
    tmp.write_text(json.dumps(state, separators=(",", ":")) + "\n")
    tmp.replace(p)


def bootstrap_file(path: Path, agent_id: str, state: dict) -> None:
    """Mark existing successful sends as seen without forwarding (first run)."""
    key = str(path)
    seen = set(state.get("seen", []))
    pending_local: list[str] = []
    offset = 0
    with path.open("rb") as f:
        while True:
            line = f.readline()
            if not line:
                break
            offset = f.tell()
            try:
                d = json.loads(line.decode("utf-8"))
            except Exception:
                continue
            _handle_payload(d, agent_id, key, seen, pending_local, forward=False)
    state["files"][key] = {"offset": offset}
    state["pending"][key] = pending_local
    state["seen"] = list(seen)


def _handle_payload(
    d: dict,
    agent_id: str,
    file_key: str,
    seen: set[str],
    pending: list[str],
    forward: bool,
    token: str = "",
    chat_id: str = "",
) -> None:
    content = d.get("message", {}).get("content")
    if not isinstance(content, list):
        return
    for item in content:
        if item.get("name") != "send_message":
            continue
        if item.get("type") == "tool_use":
            pending.append(extract_send_text(item.get("input")))
            continue
        if item.get("type") != "tool_result":
            continue
        text = pending.pop(0) if pending else ""
        result = item.get("result") or {}
        success = result.get("success")
        if not success or not success.get("messageId"):
            continue
        mid = success["messageId"]
        dedup = f"{agent_id}:{mid}"
        if dedup in seen:
            continue
        seen.add(dedup)
        if not text:
            continue
        cleaned = human_text(text)
        if not cleaned:
            continue
        if not forward:
            continue
        label = agent_name(agent_id)
        body = f"[{label}]\n{cleaned}"
        try:
            send_text(token, chat_id, body)
            log(f"forwarded {dedup} ({len(cleaned)} chars)")
        except Exception as e:
            log(f"send failed {dedup}: {e}")


def process_file(
    path: Path,
    agent_id: str,
    state: dict,
    token: str,
    chat_id: str,
) -> None:
    key = str(path)
    seen = set(state.get("seen", []))
    pending = state.get("pending", {}).get(key, [])
    if not isinstance(pending, list):
        pending = []

    file_state = state.get("files", {}).get(key)
    if file_state is None:
        bootstrap_file(path, agent_id, state)
        save_state(state)
        return

    offset = int(file_state.get("offset", 0))
    size = path.stat().st_size
    if size < offset:
        offset = 0
        pending = []

    with path.open("rb") as f:
        f.seek(offset)
        while True:
            line = f.readline()
            if not line:
                break
            offset = f.tell()
            try:
                d = json.loads(line.decode("utf-8"))
            except Exception:
                continue
            _handle_payload(
                d, agent_id, key, seen, pending, forward=True, token=token, chat_id=chat_id
            )

    state["files"][key] = {"offset": offset}
    state["pending"][key] = pending
    state["seen"] = list(seen)


def main() -> None:
    if not ENV_FILE.is_file():
        log(f"missing env file {ENV_FILE}")
        sys.exit(1)
    env = load_env(ENV_FILE)
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = env.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        log("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID empty")
        sys.exit(1)

    log(
        f"mirror on root={TRANSCRIPTS_ROOT} dry_run={DRY_RUN} "
        f"agents={AGENT_FILTER or 'all'}"
    )
    state = load_state()

    while True:
        transcripts = discover_transcripts()
        for path in transcripts.values():
            agent_id = path.parent.name
            try:
                process_file(path, agent_id, state, token, chat_id)
            except Exception as e:
                log(f"process {agent_id}: {e}")
        save_state(state)
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
