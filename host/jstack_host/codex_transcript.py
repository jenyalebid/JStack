"""Codex rollout adapter for jRemote's engine-neutral transcript surfaces."""

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path

# Codex wraps an attachment in markup that it splits across content blocks: the
# open tag, the image block, the close tag, and only then what the user typed. Each
# half is machine-written and goes — but it goes BEFORE the noise test and after
# the blocks are joined, because a prompt that opens with a screenshot is still
# The user talking, and a lone '<' or '</image>' left at the front would read as
# injection and take their words down with the tag.
_ATTACHMENT = re.compile(r"<image\b[^>]*>|</image>")

# Machine-injected openings — a whole user message starting with one is dropped.
_NOISE_PREFIXES = ("<", "Caveat:", "# AGENTS.md instructions for ")


def strip_attachments(text: str) -> str:
    """A prompt's own words, with Codex's inlined attachment markup removed."""
    return _ATTACHMENT.sub("", text or "").strip()


def root() -> Path:
    return Path.home() / ".codex" / "sessions"


def session_id(path: Path) -> str:
    meta = metadata(path)
    return str(meta.get("session_id") or meta.get("id") or "")


def metadata(path: Path) -> dict:
    try:
        with path.open() as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") == "session_meta":
                    return entry.get("payload") or {}
    except OSError:
        pass
    return {}


def path_for_id(sid: str) -> Path | None:
    base = root()
    if not base.exists():
        return None
    matches = list(base.glob(f"**/*-{sid}.jsonl"))
    return matches[-1] if matches else None


def rollout_started_after(started_at: float, cwd: str = "") -> Path | None:
    """The rollout Codex created for a launch at ``started_at``.

    Codex does not hold its JSONL open: it opens, appends, and closes on each
    write, so lsof cannot bind a live process to the file.  The session_meta
    timestamp and cwd are facts Codex itself writes before the first turn.
    Pick the earliest matching rollout born after this launch; an older pane
    in the same cwd is therefore ineligible, and simultaneous launches each
    claim the file immediately following their own start.
    """
    candidates = []
    for path in root().glob("**/rollout-*.jsonl"):
        meta = metadata(path)
        if cwd and meta.get("cwd") != cwd:
            continue
        raw = str(meta.get("timestamp") or "")
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            continue
        if stamp >= started_at:
            candidates.append((stamp, path))
    return min(candidates, default=(0, None), key=lambda item: item[0])[1]


def bind_open_session(board_sid: str, started_at: float, cwd: str = "",
                      attempts: int = 80) -> None:
    """Record the rollout created by this managed Codex launch."""
    def run() -> None:
        from . import managed
        for _ in range(attempts):
            path = rollout_started_after(started_at, cwd)
            if path:
                managed.record_transcript(board_sid, str(path))
                return
            time.sleep(.25)
    threading.Thread(target=run, name=f"codex-rollout-{board_sid[:8]}",
                     daemon=True).start()


def message_entries(path: Path) -> list[dict]:
    """Normalize Codex response items to jRemote's message shape."""
    out = []
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return out
    for raw in lines:
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "response_item":
            continue
        payload = entry.get("payload") or {}
        ptype = payload.get("type")
        if ptype == "message" and payload.get("role") in ("user", "assistant"):
            segments = []
            for block in payload.get("content") or []:
                if not isinstance(block, dict):
                    continue
                text = block.get("text")
                if block.get("type") in ("input_text", "output_text") and text:
                    segments.append({"type": "text", "text": text})
            if payload["role"] == "user":
                typed = strip_attachments(
                    "\n".join(s["text"] for s in segments))
                segments = [{"type": "text", "text": typed}] if typed else []
            if segments:
                text = "\n".join(s["text"] for s in segments)
                if payload["role"] == "user" and text.startswith(_NOISE_PREFIXES):
                    continue
                out.append({"role": payload["role"], "segments": segments,
                            "text": text[:4000],
                            "timestamp": entry.get("timestamp", "")})
        elif ptype in ("custom_tool_call", "function_call"):
            name = payload.get("name") or "tool"
            inp = payload.get("input") or payload.get("arguments") or ""
            summary = str(inp).replace("\n", " ")[:90]
            out.append({"role": "assistant",
                        "segments": [{"type": "tool", "name": name,
                                      "summary": summary}],
                        "text": "", "timestamp": entry.get("timestamp", "")})
    return out
