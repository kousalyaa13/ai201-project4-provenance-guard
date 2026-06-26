"""Provenance Guard — Flask app.

A backend that classifies submitted text as human- or AI-written, scores its
confidence, returns a plain-language transparency label, and lets creators
appeal. Every decision and appeal is written to a structured audit log.

Endpoints:
  POST /submit  - classify text (rate limited)
  POST /appeal  - contest a classification (sets status to "under review")
  GET  /log     - recent audit-log entries
  GET  /queue   - submissions currently under review (for human reviewers)
  GET  /health  - liveness check
"""

import uuid

from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import audit_log
from labels import build_label
from scoring import combine_scores
from signals import llm_signal, stylometric_signal

app = Flask(__name__)

# --- Rate limiting ---
# Per-IP limits on the submission endpoint. In-memory storage is fine for local
# development. Chosen limits and reasoning are documented in the README.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


@app.errorhandler(429)
def rate_limit_exceeded(error):
    """Return a clean JSON message when a client is rate limited."""
    return (
        jsonify(
            {
                "error": "Rate limit exceeded. Please slow down and try again later.",
                "detail": str(error.description),
            }
        ),
        429,
    )


@app.route("/health", methods=["GET"])
def health():
    """Simple check that the server is up."""
    return jsonify({"status": "ok"})


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    """Accept text, run both signals, score, label, log, and respond."""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    creator_id = (data.get("creator_id") or "").strip()

    # Basic input checks.
    if not text:
        return jsonify({"error": "Field 'text' is required and cannot be empty."}), 400
    if not creator_id:
        return jsonify({"error": "Field 'creator_id' is required."}), 400

    # Give this submission a unique id. The appeal endpoint needs it.
    content_id = str(uuid.uuid4())

    # --- Signal 1: LLM classification ---
    signal1 = llm_signal(text)
    llm_score = signal1["score"]

    # --- Signal 2: stylometric heuristics ---
    signal2 = stylometric_signal(text)
    stylo_score = signal2["score"]
    n_words = signal2["metrics"].get("n_words", len(text.split()))

    # --- Confidence scoring: combine both signals ---
    scored = combine_scores(llm_score, stylo_score, n_words)
    confidence = scored["final_score"]
    attribution = scored["band"]

    # --- Transparency label (varies by confidence band) ---
    label = build_label(confidence, attribution)

    # --- Audit log: record both signals and the combined result ---
    entry = {
        "event": "classification",
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": audit_log.now_iso(),
        "attribution": attribution,
        "confidence": confidence,
        "llm_score": round(llm_score, 4),
        "stylometric_score": round(stylo_score, 4),
        "stylometric_metrics": signal2["metrics"],
        "weights": scored["weights"],
        "short_text": scored["short_text"],
        "llm_ok": signal1["ok"],
        "label": label,
        "appealed": False,
        "status": "classified",
    }
    audit_log.write_entry(entry)

    # --- Live content state (what an appeal will later update) ---
    audit_log.save_content(
        content_id,
        {
            "content_id": content_id,
            "creator_id": creator_id,
            "text": text,
            "attribution": attribution,
            "confidence": confidence,
            "llm_score": round(llm_score, 4),
            "stylometric_score": round(stylo_score, 4),
            "label": label,
            "appealed": False,
            "status": "classified",
            "classified_at": entry["timestamp"],
        },
    )

    # --- Response ---
    return jsonify(
        {
            "content_id": content_id,
            "creator_id": creator_id,
            "attribution": attribution,
            "confidence": confidence,
            "label": label,
            "signals": {
                "llm": round(llm_score, 4),
                "stylometric": round(stylo_score, 4),
            },
        }
    )


@app.route("/appeal", methods=["POST"])
def appeal():
    """Let a creator contest a classification.

    Sets the content's status to "under review", logs the appeal next to the
    original decision, and confirms receipt. No automated re-classification.
    """
    data = request.get_json(silent=True) or {}
    content_id = (data.get("content_id") or "").strip()
    creator_reasoning = (data.get("creator_reasoning") or "").strip()

    if not content_id:
        return jsonify({"error": "Field 'content_id' is required."}), 400
    if not creator_reasoning:
        return jsonify({"error": "Field 'creator_reasoning' is required."}), 400

    # The content must exist before it can be appealed.
    record = audit_log.get_content(content_id)
    if record is None:
        return jsonify({"error": f"No content found with id '{content_id}'."}), 404

    timestamp = audit_log.now_iso()

    # Update the live status to "under review" and attach the appeal.
    updated = audit_log.update_status(
        content_id,
        "under_review",
        {
            "appealed": True,
            "appeal_reasoning": creator_reasoning,
            "appealed_at": timestamp,
        },
    )

    # Log the appeal as its own event, alongside the original decision context.
    audit_log.write_entry(
        {
            "event": "appeal",
            "content_id": content_id,
            "creator_id": record.get("creator_id"),
            "timestamp": timestamp,
            "appeal_reasoning": creator_reasoning,
            "original_attribution": record.get("attribution"),
            "original_confidence": record.get("confidence"),
            "appealed": True,
            "status": "under_review",
        }
    )

    return jsonify(
        {
            "content_id": content_id,
            "status": "under_review",
            "appealed": True,
            "message": (
                "Appeal received. This content is now under review by a human "
                "moderator. No automated re-classification is performed."
            ),
            "original_attribution": updated.get("attribution"),
            "original_confidence": updated.get("confidence"),
        }
    )


@app.route("/queue", methods=["GET"])
def queue():
    """Return submissions currently under review, for human reviewers."""
    items = audit_log.list_contents(status="under_review")
    return jsonify({"under_review": items, "count": len(items)})


@app.route("/log", methods=["GET"])
def log():
    """Return the most recent audit-log entries as JSON."""
    return jsonify({"entries": audit_log.get_log()})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
