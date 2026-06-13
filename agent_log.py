from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List, Optional


_GLOBAL_LOCK = threading.Lock()


class AgentLogger:
    def __init__(self) -> None:
        self._events: List[Dict[str, Any]] = []
        self._seq = 0
        self._lock = threading.Lock()

    def _add(self, kind: str, agent: str, message: str, detail: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            self._seq += 1
            self._events.append({
                "id": self._seq,
                "ts": time.time(),
                "kind": kind,
                "agent": agent,
                "message": message,
                "detail": detail or {},
            })

    # ── helpers pubblici ─────────────────────────────────────────────────────
    def agent_start(self, agent: str, message: str = "", detail: Optional[Dict] = None) -> None:
        self._add("agent_start", agent, message or f"{agent} avviato", detail)

    def tool_call(self, agent: str, tool_name: str, args: Any) -> None:
        try:
            preview = json.dumps(args, ensure_ascii=False)[:300]
        except Exception:
            preview = str(args)[:300]
        self._add("tool_call", agent, f"→ {tool_name}({preview})", {"tool": tool_name, "args": args})

    def tool_result(self, agent: str, tool_name: str, summary: str, detail: Optional[Dict] = None) -> None:
        self._add("tool_result", agent, f"↳ {tool_name}: {summary}", detail or {"tool": tool_name})

    def decision(self, agent: str, message: str, detail: Optional[Dict] = None) -> None:
        self._add("decision", agent, f"💭 {message}", detail)

    def agent_end(self, agent: str, message: str = "") -> None:
        self._add("agent_end", agent, message or f"{agent} completato")

    def warning(self, agent: str, message: str, detail: Optional[Dict] = None) -> None:
        self._add("warning", agent, f"⚠ {message}", detail)

    # ── lettura per UI ───────────────────────────────────────────────────────
    def events_after(self, last_id: int = 0) -> List[Dict[str, Any]]:
        with self._lock:
            return [e for e in self._events if e["id"] > last_id]

    def all_events(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._seq = 0
