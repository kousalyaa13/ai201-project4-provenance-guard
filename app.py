"""Provenance Guard — Flask app.

Milestone 3: a POST /submit endpoint that runs the first detection signal
(Groq LLM), gives each submission a unique content_id, writes a structured
audit-log entry, and returns a JSON response. A GET /log endpoint surfaces the
audit log. Confidence scoring and the real transparency label arrive in
Milestones 4 and 5 — for now those fields are clearly marked placeholders.
"""

import uuid

from flask import Flask, jsonify, request

import audit_log
from scoring import combine_scores
from signals import llm_signal, stylometric_signal

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health():
    """Simple check that the server is up."""
    return jsonify({"status": "ok"})


@app.route("/submit", methods=["POST"])
def submit():
    """Accept text, run signal 1, log it, and return a structured response."""
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

    # The real transparency label arrives in Milestone 5.
    label = "[placeholder] Final transparency label is added in Milestone 5."

    # --- Audit log: record both signals and the combined result ---
    entry = {
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
        "status": "classified",
    }
    audit_log.write_entry(entry)

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
            "_note": "label is a placeholder until M5",
        }
    )


@app.route("/log", methods=["GET"])
def log():
    """Return the most recent audit-log entries as JSON."""
    return jsonify({"entries": audit_log.get_log()})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
