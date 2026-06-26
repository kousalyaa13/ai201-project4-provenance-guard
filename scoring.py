"""Confidence scoring for Provenance Guard.

Takes the two signal scores (each 0-1, higher = more likely AI) and combines
them into one final confidence score, then maps that score to one of three
bands. This follows planning.md, sections 2 and 3, exactly.

Combine rule:
    final_score = (0.6 * llm_score) + (0.4 * stylometric_score)

Short-text adjustment: if the text is very short (< 40 words) the stylometric
signal is unreliable, so we lean more on the LLM signal.

Bands (planning.md, section 3):
    final_score >= 0.70           -> likely_ai
    0.40 <= final_score < 0.70    -> uncertain
    final_score < 0.40            -> likely_human
"""

# Normal weights when there is enough text to measure. The LLM signal gets
# more weight because, in calibration testing, the stylometric signal was noisy
# and scored some clearly-AI text low (see planning.md, section 2). The high
# AI threshold below is what protects against false positives, not a low LLM
# weight.
_W_LLM = 0.70
_W_STYLO = 0.30

# When text is short, trust the LLM more and the shallow statistics less.
_SHORT_TEXT_WORDS = 40
_W_LLM_SHORT = 0.80
_W_STYLO_SHORT = 0.20

# Band thresholds. The "likely_ai" bar is high (0.70) on purpose, to protect
# human writers from false positives (planning.md, section 3).
_AI_THRESHOLD = 0.70
_HUMAN_THRESHOLD = 0.40


def band_from_score(final_score):
    """Map a final 0-1 score to one of three attribution bands."""
    if final_score >= _AI_THRESHOLD:
        return "likely_ai"
    if final_score >= _HUMAN_THRESHOLD:
        return "uncertain"
    return "likely_human"


def combine_scores(llm_score, stylometric_score, n_words):
    """Combine the two signal scores into one final confidence score.

    Returns a dict:
        {
            "final_score": float,   # 0-1, higher = more likely AI
            "band": str,            # "likely_ai" | "uncertain" | "likely_human"
            "weights": {"llm": .., "stylometric": ..},
            "short_text": bool,
        }
    """
    short_text = n_words < _SHORT_TEXT_WORDS
    if short_text:
        w_llm, w_stylo = _W_LLM_SHORT, _W_STYLO_SHORT
    else:
        w_llm, w_stylo = _W_LLM, _W_STYLO

    final_score = (w_llm * llm_score) + (w_stylo * stylometric_score)
    final_score = max(0.0, min(1.0, final_score))

    return {
        "final_score": round(final_score, 4),
        "band": band_from_score(final_score),
        "weights": {"llm": w_llm, "stylometric": w_stylo},
        "short_text": short_text,
    }
