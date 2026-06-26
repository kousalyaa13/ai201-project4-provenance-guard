"""Structured audit log for Provenance Guard.

Every attribution decision and every appeal is written here as a JSON line.
We use a JSON Lines file (one JSON object per line) so the log is structured,
easy to append to, and easy to read back. This is not print() — it is a real
record other code and the README can rely on.

Milestone 3: log each submission (timestamp, content id, attribution, llm
score, status). Milestones 4 and 5 extend the same entries with the second
signal, the final score, and appeals.
"""

import json
import os
from datetime import datetime, timezone

# The log file lives next to this code.
_LOG_PATH = os.path.join(os.path.dirname(__file__), "audit_log.jsonl")


def now_iso():
    """Return the current time as an ISO 8601 string in UTC."""
    return datetime.now(timezone.utc).isoformat()


def write_entry(entry):
    """Append one structured entry (a dict) to the audit log."""
    with open(_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def get_log(limit=50):
    """Return the most recent log entries, newest first.

    limit: how many entries to return (default 50).
    """
    if not os.path.exists(_LOG_PATH):
        return []
    entries = []
    with open(_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    # newest first
    entries.reverse()
    return entries[:limit]
