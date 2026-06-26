"""Transparency label generation for Provenance Guard.

Maps a final confidence score (0-1, higher = more likely AI) and its band to
the exact plain-language label a reader sees. The three variants are the same
text written in planning.md, section 4.

The label CHANGES with the score — high-AI, high-human, and uncertain each get
a different message. The score is always shown as a percent so a non-technical
reader can understand it.
"""


def build_label(final_score, band):
    """Return the transparency label text for a given score and band.

    final_score: float 0-1, higher = more likely AI.
    band: "likely_ai" | "uncertain" | "likely_human".
    """
    percent = round(final_score * 100)

    if band == "likely_ai":
        return (
            f"🤖 Likely AI-generated. Our checks strongly suggest this text was "
            f"created with AI tools (confidence: {percent}%). This is an "
            f"automated estimate, not proof. If you believe this is wrong, you "
            f"can appeal."
        )
    if band == "likely_human":
        return (
            f"✍️ Likely human-written. Our checks suggest a person wrote this "
            f"text (confidence it is AI: {percent}%). This is an automated "
            f"estimate, not a guarantee."
        )
    # uncertain
    return (
        f"❓ Uncertain. Our checks could not confidently tell whether a human "
        f"or AI wrote this text (confidence it is AI: {percent}%). We are "
        f"showing this honestly rather than guessing. The creator may add "
        f"context or appeal."
    )


if __name__ == "__main__":
    # Confirm all three variants are reachable and match the spec.
    for score, band in [(0.92, "likely_ai"), (0.08, "likely_human"), (0.55, "uncertain")]:
        print(f"[{band} @ {score}]")
        print("  " + build_label(score, band))
        print()
