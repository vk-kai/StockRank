from __future__ import annotations

import threading
from datetime import datetime


SCAN_LOCK = threading.Lock()
RECENT_COMPLETION_WINDOW = 10
runtime_state = {
    "last_run_slot": "",
    "running": False,
    "current_code": "",
    "current_name": "",
    "current_index": 0,
    "total_count": 0,
    "progress_pct": 0,
    "current_message": "",
    "estimated_remaining_seconds": 0,
    "recent_completion_times": [],
}


def set_running(running: bool):
    runtime_state["running"] = bool(running)


def reset_progress_state():
    runtime_state["current_code"] = ""
    runtime_state["current_name"] = ""
    runtime_state["current_index"] = 0
    runtime_state["total_count"] = 0
    runtime_state["progress_pct"] = 0
    runtime_state["current_message"] = ""
    runtime_state["estimated_remaining_seconds"] = 0
    runtime_state["recent_completion_times"] = []


def append_completion_time(now: datetime):
    recent_times = runtime_state.get("recent_completion_times") or []
    recent_times.append(now)
    if len(recent_times) > RECENT_COMPLETION_WINDOW + 1:
        recent_times = recent_times[-(RECENT_COMPLETION_WINDOW + 1):]
    runtime_state["recent_completion_times"] = recent_times


def update_progress_state(code: str, name: str, current_index: int, total_count: int):
    safe_total = max(int(total_count), 1)
    pct = min(round(current_index / safe_total * 100), 100)
    recent_times = runtime_state.get("recent_completion_times") or []
    estimated = 0
    if len(recent_times) >= 2 and current_index < safe_total:
        intervals = [
            max((later - earlier).total_seconds(), 0.0)
            for earlier, later in zip(recent_times, recent_times[1:])
        ]
        intervals = [value for value in intervals if value > 0]
        if intervals:
            avg_seconds = sum(intervals) / len(intervals)
            remaining = max(safe_total - current_index, 0)
            estimated = int(avg_seconds * remaining)
    runtime_state["current_code"] = code
    runtime_state["current_name"] = name
    runtime_state["current_index"] = int(current_index)
    runtime_state["total_count"] = int(total_count)
    runtime_state["progress_pct"] = pct
    runtime_state["estimated_remaining_seconds"] = estimated
    runtime_state["current_message"] = (
        f"并行扫描股票{name}（{code}） {current_index}/{total_count} 进度{pct}%"
    )
