"""Strip code blocks and scripts from bot text before Telegram delivery."""
from __future__ import annotations

import re

_FENCE = re.compile(r"```[\s\S]*?```")
_HEREDOC = re.compile(
    r"(?:python3?|pypy3?|bash|sh)\s+-[a-zA-Z]*\s*<<['\"]?\w+['\"]?[\s\S]*?(?:^['\"]?\w+['\"]?\s*$)",
    re.MULTILINE | re.IGNORECASE,
)
_PY_C = re.compile(r"python3?\s+-c\s+['\"].{80,}", re.IGNORECASE | re.DOTALL)
_CODEY_LINE = re.compile(
    r"^\s*(def |class |async def |import |from [A-Za-z0-9_\.]+ import |"
    r"if __name__|@dataclass|@staticmethod|@classmethod|"
    r"diff --git |index [0-9a-f]{6}|@@ |--- a/|\+\+\+ b/|"
    r"name:\s+\S+\s*$|strategies:\s*$|portfolios:\s*$|"
    r"#!|/usr/bin/env |"
    r"old_string|new_string|"
    r"python3?\s+-<<|python3?\s+-\w*\s*<<)",
    re.IGNORECASE,
)
_CODEY_INLINE = re.compile(
    r"(json\.load|pd\.read_|pandas as pd|subprocess\.|fcntl\.|"
    r"Path\(|isinstance\(|__name__\s*==|"
    r"old_string|new_string|"
    r"python3?\s+-<<|<<['\"]PY['\"])",
    re.IGNORECASE,
)


def looks_like_code(block: str) -> bool:
    s = block.strip()
    if not s:
        return False
    if "```" in s:
        return True
    if _HEREDOC.search(s) or _PY_C.search(s):
        return True
    if "<<'PY'" in s or '<<"PY"' in s or "<<PY" in s or "<<'EOF'" in s:
        return True
    lines = [ln for ln in block.splitlines() if ln.strip()]
    if not lines:
        return False
    hits = 0
    for ln in lines:
        if _CODEY_LINE.search(ln) or _CODEY_INLINE.search(ln):
            hits += 1
        elif ln.startswith("    ") or ln.startswith("\t"):
            hits += 1
    if hits >= 2:
        return True
    if "def " in block and ("return " in block or "self." in block) and len(lines) >= 3:
        return True
    if len(lines) >= 3 and hits / len(lines) >= 0.3:
        return True
    return False


def human_text(text: str) -> str:
    if not text:
        return ""
    text = _FENCE.sub("\n[code omitted]\n", text)
    text = _HEREDOC.sub("\n[script omitted]\n", text)
    text = _PY_C.sub("\n[script omitted]\n", text)
    paras = re.split(r"\n{2,}", text)
    kept: list[str] = []
    for para in paras:
        if looks_like_code(para):
            if kept and kept[-1] in ("[script omitted]", "[code omitted]"):
                continue
            kept.append("[script omitted]")
            continue
        lines = []
        for ln in para.splitlines():
            if _CODEY_LINE.search(ln) and len(ln.strip()) > 8:
                continue
            if _CODEY_INLINE.search(ln) and len(ln.strip()) > 40:
                continue
            lines.append(ln)
        chunk = "\n".join(lines).strip()
        if chunk:
            kept.append(chunk)
    out = re.sub(r"\n{3,}", "\n\n", "\n\n".join(kept)).strip()
    return out
