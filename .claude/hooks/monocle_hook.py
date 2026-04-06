#!/usr/bin/env python3
"""
Monocle Claude Code Hook

Observes Claude Code CLI sessions by parsing transcript files and emitting
OpenTelemetry spans using Monocle's metamodel pattern.

This script is called by Claude Code's Stop hook after each turn completes.

Usage:
    Configure in .claude/settings.local.json:
    {
        "hooks": {
            "Stop": [{
                "type": "command",
                "command": "bash examples/scripts/claude_code_hook/run_hook.sh"
            }]
        }
    }

Environment Variables:
    MONOCLE_CLAUDE_ENABLED      Enable/disable hook (default: true)
    MONOCLE_EXPORTER            Exporter(s) to use (e.g., "okahu,file")
    OKAHU_INGESTION_ENDPOINT    Okahu ingestion endpoint
    OKAHU_API_KEY               Okahu API key
    MONOCLE_CLAUDE_DEBUG        Enable debug logging (default: false)
    MONOCLE_SERVICE_NAME        Service name for spans (default: claude-cli)
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# --- Configuration ---
STATE_DIR = Path.home() / ".claude" / "state"
LOG_FILE = STATE_DIR / "monocle_hook.log"
STATE_FILE = STATE_DIR / "monocle_state.json"
LOCK_FILE = STATE_DIR / "monocle_state.lock"

DEBUG = os.environ.get("MONOCLE_CLAUDE_DEBUG", "").lower() == "true"
SERVICE_NAME = os.environ.get("MONOCLE_SERVICE_NAME", "claude-cli")

# --- Logging (fail-open, never block) ---
def _log(level: str, message: str) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{ts} [{level}] {message}\n")
    except Exception:
        pass

def debug(msg: str) -> None:
    if DEBUG:
        _log("DEBUG", msg)

def info(msg: str) -> None:
    _log("INFO", msg)

def error(msg: str) -> None:
    _log("ERROR", msg)

# --- State Management ---
class FileLock:
    def __init__(self, path: Path, timeout_s: float = 2.0):
        self.path = path
        self.timeout_s = timeout_s
        self._fh = None

    def __enter__(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+", encoding="utf-8")
        try:
            import fcntl
            deadline = time.time() + self.timeout_s
            while True:
                try:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.time() > deadline:
                        break
                    time.sleep(0.05)
        except Exception:
            pass
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            import fcntl
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            self._fh.close()
        except Exception:
            pass

def load_state() -> Dict[str, Any]:
    try:
        if not STATE_FILE.exists():
            return {}
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_state(state: Dict[str, Any]) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        debug(f"save_state failed: {e}")

def state_key(session_id: str, transcript_path: str) -> str:
    raw = f"{session_id}::{transcript_path}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

# --- Hook Payload ---
def read_hook_payload() -> Dict[str, Any]:
    try:
        data = sys.stdin.read()
        if not data.strip():
            return {}
        return json.loads(data)
    except Exception:
        return {}

def extract_session_and_transcript(payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[Path]]:
    session_id = (
        payload.get("sessionId")
        or payload.get("session_id")
        or payload.get("session", {}).get("id")
    )
    transcript = (
        payload.get("transcriptPath")
        or payload.get("transcript_path")
        or payload.get("transcript", {}).get("path")
    )
    if transcript:
        try:
            return session_id, Path(transcript).expanduser().resolve()
        except Exception:
            pass
    return session_id, None

# --- Main ---
def main() -> int:
    start = time.time()
    debug("Monocle hook started")

    if os.environ.get("MONOCLE_CLAUDE_ENABLED", "true").lower() == "false":
        debug("Hook disabled via MONOCLE_CLAUDE_ENABLED=false")
        return 0

    payload = read_hook_payload()
    session_id, transcript_path = extract_session_and_transcript(payload)

    if not session_id or not transcript_path:
        debug("Missing session_id or transcript_path from hook payload")
        return 0

    if not transcript_path.exists():
        debug(f"Transcript path does not exist: {transcript_path}")
        return 0

    info(f"Processing session {session_id}")
    debug(f"Transcript: {transcript_path}")

    try:
        # Import Monocle components
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME as SVC_NAME
        from monocle_apptrace.exporters.monocle_exporters import get_monocle_exporter
        from monocle_apptrace.instrumentation.metamodel.claude_code._helper import (
            SessionState, build_turns, read_new_jsonl,
        )
        from monocle_apptrace.instrumentation.metamodel.claude_code.transcript_processor import (
            process_transcript,
        )
    except ImportError as e:
        error(f"Missing dependency: {e}")
        return 0

    try:
        import importlib.metadata
        sdk_version = importlib.metadata.version("monocle_apptrace")
    except Exception:
        sdk_version = "0.7.6"

    try:
        with FileLock(LOCK_FILE):
            state = load_state()
            key = state_key(session_id, str(transcript_path))

            # Restore session state
            s = state.get(key, {})
            ss = SessionState(
                offset=int(s.get("offset", 0)),
                buffer=str(s.get("buffer", "")),
                turn_count=int(s.get("turn_count", 0)),
                subagents_processed=list(s.get("subagents_processed", [])),
            )

            # Read new messages
            msgs, ss = read_new_jsonl(transcript_path, ss)
            if not msgs:
                state[key] = {
                    "offset": ss.offset, "buffer": ss.buffer,
                    "turn_count": ss.turn_count,
                    "subagents_processed": ss.subagents_processed,
                    "updated": datetime.now(timezone.utc).isoformat(),
                }
                save_state(state)
                debug("No new messages")
                return 0

            turns = build_turns(msgs)
            if not turns:
                state[key] = {
                    "offset": ss.offset, "buffer": ss.buffer,
                    "turn_count": ss.turn_count,
                    "subagents_processed": ss.subagents_processed,
                    "updated": datetime.now(timezone.utc).isoformat(),
                }
                save_state(state)
                debug("No complete turns")
                return 0

            # Set up TracerProvider with Okahu exporters
            resource = Resource.create({SVC_NAME: SERVICE_NAME})
            provider = TracerProvider(resource=resource)
            exporters = get_monocle_exporter()
            debug(f"Exporters: {[type(e).__name__ for e in exporters]}")
            for exp in exporters:
                provider.add_span_processor(SimpleSpanProcessor(exp))
            trace.set_tracer_provider(provider)

            tracer = trace.get_tracer("monocle.claude-code", "1.0.0")

            # Emit spans using the transcript processor
            emitted = process_transcript(
                session_id=session_id,
                turns=turns,
                tracer=tracer,
                sdk_version=sdk_version,
                service_name=SERVICE_NAME,
                start_turn=ss.turn_count,
            )
            ss.turn_count += len(turns)

            # Save state
            state[key] = {
                "offset": ss.offset, "buffer": ss.buffer,
                "turn_count": ss.turn_count,
                "subagents_processed": ss.subagents_processed,
                "updated": datetime.now(timezone.utc).isoformat(),
            }
            save_state(state)

            # Flush and shutdown
            try:
                provider.force_flush(timeout_millis=10000)
                provider.shutdown()
            except Exception as e:
                debug(f"Flush/shutdown: {e}")

        dur = time.time() - start
        info(f"Processed {emitted} turns in {dur:.2f}s (session={session_id})")
        return 0

    except Exception as e:
        error(f"Unexpected failure: {e}")
        import traceback
        debug(traceback.format_exc())
        return 0  # Always exit 0 to not block Claude Code

if __name__ == "__main__":
    sys.exit(main())
