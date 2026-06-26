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

# A small content store that holds the CURRENT status of each submission, keyed
# by content_id. The audit log is append-only (a history of events); this store
# is the live, mutable state an appeal updates ("classified" -> "under_review")
# and the reviewer queue reads from.
_CONTENT_PATH = os.path.join(os.path.dirname(__file__), "contents.json")


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


# --- Content status store (live, mutable state) ---


def _read_contents():
    """Load the content store as a dict {content_id: record}."""
    if not os.path.exists(_CONTENT_PATH):
        return {}
    with open(_CONTENT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_contents(contents):
    """Save the whole content store back to disk."""
    with open(_CONTENT_PATH, "w", encoding="utf-8") as f:
        json.dump(contents, f, indent=2)


def save_content(content_id, record):
    """Store the record for a new submission (status starts as 'classified')."""
    contents = _read_contents()
    contents[content_id] = record
    _write_contents(contents)


def get_content(content_id):
    """Return the stored record for a content_id, or None if not found."""
    return _read_contents().get(content_id)


def update_status(content_id, status, extra=None):
    """Update a content's status and merge in any extra fields.

    Returns the updated record, or None if the content_id is unknown.
    """
    contents = _read_contents()
    record = contents.get(content_id)
    if record is None:
        return None
    record["status"] = status
    if extra:
        record.update(extra)
    contents[content_id] = record
    _write_contents(contents)
    return record


def list_contents(status=None):
    """Return all content records, optionally filtered by status."""
    contents = list(_read_contents().values())
    if status is not None:
        contents = [c for c in contents if c.get("status") == status]
    return contents
