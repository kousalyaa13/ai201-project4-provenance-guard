# Provenance Guard — Planning

This document is the plan for Provenance Guard. It is a backend system that
takes a piece of text, guesses if a human or an AI wrote it, gives a confidence
score, shows a plain-language label, and lets creators appeal.

---

## 1. Architecture Narrative — The Path of One Piece of Text

This is the journey of a single piece of text, from the moment someone sends it
to the moment a user sees a label. Each part of the system is named, with what
it does.

1. **The creator sends text.** A user sends a `POST /submit` request. The body
   holds the raw text and the creator's name or id.

2. **The Flask app receives it.** Flask is the web framework. It is the front
   door. It reads the request and checks that the text is present and not empty.

3. **The rate limiter checks the request.** Flask-Limiter counts how many
   requests this client has made. If they sent too many too fast, it stops the
   request here and returns an error. If they are within the limit, the request
   moves on.

4. **Signal 1 runs (LLM classification).** The text is sent to Groq
   (`llama-3.3-70b-versatile`). We ask the model: "Does this read as human or
   AI writing?" The model returns a number from 0 to 1. Higher means more likely
   AI. This signal looks at meaning and style as a whole.

5. **Signal 2 runs (stylometric heuristics).** A pure-Python function measures
   simple text statistics: how much sentence length varies, how rich the
   vocabulary is, and how dense the punctuation is. It turns these into a number
   from 0 to 1. Higher means more likely AI. This signal looks at structure and
   numbers, not meaning.

6. **The confidence scorer combines the two signals.** A scoring function takes
   both signal scores and blends them into one final score from 0 to 1. This is
   the confidence that the text is AI-generated.

7. **The label maker turns the score into words.** A function maps the final
   score into one of three plain-language labels: "likely AI," "uncertain," or
   "likely human." This is the transparency label the reader sees.

8. **The audit log records the decision.** Every decision is written to a
   structured log (SQLite or JSON). It saves the content id, both signal scores,
   the final score, the label, and the time.

9. **The response goes back.** Flask returns a JSON response with the result,
   the confidence score, and the label text. The creator and the platform now
   see the label.

For appeals, a creator who disagrees sends `POST /appeal` with the content id
and their reasoning. The system changes that content's status to "under review,"
writes the appeal to the audit log next to the original decision, and returns a
confirmation. A human reviewer can later read the appeal queue.

---

## 2. Detection Signals

The system uses two signals that measure genuinely different things. One is
about meaning (semantic). One is about structure (statistical). Because they are
independent, together they tell us more than either one alone.

### Signal 1 — LLM Classification (Groq)

- **What it measures:** Whether the text *reads* like human or AI writing, taken
  as a whole. It judges tone, flow, coherence, and style the way a careful
  reader would.
- **Why this differs between human and AI:** AI writing often sounds smooth,
  balanced, and "safe." It rarely takes odd risks or makes the small personal
  choices a human makes. A strong language model can sense this overall feel.
- **Output:** A number from 0 to 1. Higher = more likely AI.
- **Blind spot:** It can be fooled by edited AI text or by AI that copies a human
  voice. It can also wrongly flag formal, polished human writing as AI, because
  that writing is also smooth. It is not consistent — the same text may get
  slightly different scores on different runs.

### Signal 2 — Stylometric Heuristics (pure Python)

- **What it measures:** Simple, countable text properties:
  - **Sentence length variance** — how much sentence lengths jump around.
  - **Type-token ratio** — how many different words are used (vocabulary
    richness).
  - **Punctuation density** — how much punctuation appears per word.
- **Why this differs between human and AI:** AI text tends to be uniform.
  Sentences are similar in length, vocabulary is even, punctuation is regular.
  Human writing is more bumpy and varied. So low variance and even vocabulary
  push the score toward AI.
- **Output:** A number from 0 to 1. Higher = more likely AI.
- **Blind spot:** It is shallow. It does not understand meaning. Short text gives
  it too little to measure, so its numbers become noisy and unreliable. Some
  human styles (very plain, repetitive, or list-like writing) look statistically
  "AI" even when a person wrote them. Some AI text can be made bumpy on purpose.

### Combining the two signals

Both signals output 0–1 (higher = more likely AI). We combine them with a
weighted average:

```
final_score = (0.7 * llm_score) + (0.3 * stylometric_score)
```

- The LLM signal gets more weight (0.7) because it understands meaning, which is
  the stronger clue. (Original plan was 0.6/0.4; during Milestone 4 calibration
  the stylometric signal proved noisy — it scored some clearly-AI text near 0.48
  — so we shifted weight toward the more reliable LLM signal. The high AI
  threshold below, not a low LLM weight, is what protects against false
  positives.)
- The stylometric signal gets 0.3 because it is a useful, independent check, but
  it is shallow and noisy, especially on short text.
- If the text is very short (under 40 words), the stylometric signal is even less
  reliable. In that case we use weights 0.8 LLM / 0.2 stylometric, leaning more
  on the LLM signal.

---

## 3. Uncertainty Representation

The confidence score is `final_score`, a number from 0 to 1. It is the system's
confidence that the text is **AI-generated**.

- **What 0.6 means:** "We lean toward AI, but we are not sure." It is not a
  strong claim. It sits in the middle band and produces an "uncertain" label,
  not an accusation.
- **What 0.95 means:** "We are highly confident this is AI." It produces the
  strong AI label.
- **What 0.05 means:** "We are highly confident a human wrote this."

**Mapping raw outputs to a calibrated score.** Each signal already returns 0–1.
We blend them with the weighted average above. We do not pretend the number is a
perfect probability. Instead we test it: we run clearly human texts and clearly
AI texts through the system and check that human texts land low and AI texts land
high, with a wide gap in the middle. If the gap is too small, we adjust weights
and thresholds.

**Thresholds (tuned to make false positives hard).** Because flagging a human
as AI is the worst outcome on a writing platform, the bar for an AI label is
high.

| Final score        | Band         | Meaning                          |
|--------------------|--------------|----------------------------------|
| `>= 0.70`          | Likely AI    | High confidence the text is AI   |
| `0.40` to `0.69`   | Uncertain    | Not sure either way              |
| `< 0.40`           | Likely human | High confidence a human wrote it |

The "Likely AI" threshold is set high (0.70) on purpose. This protects human
creators: a borderline score becomes "uncertain," not "AI."

---

## 4. Transparency Label Design

Three label variants. Each is written for a non-technical reader. The exact text
is below (these same strings go in the README).

**High-confidence AI** (final score >= 0.70):

> 🤖 **Likely AI-generated.** Our checks strongly suggest this text was created
> with AI tools (confidence: {score}%). This is an automated estimate, not
> proof. If you believe this is wrong, you can appeal.

**High-confidence human** (final score < 0.40):

> ✍️ **Likely human-written.** Our checks suggest a person wrote this text
> (confidence it is AI: {score}%). This is an automated estimate, not a
> guarantee.

**Uncertain** (final score 0.40–0.69):

> ❓ **Uncertain.** Our checks could not confidently tell whether a human or AI
> wrote this text (confidence it is AI: {score}%). We are showing this honestly
> rather than guessing. The creator may add context or appeal.

`{score}` is the final score shown as a percent (for example, 0.62 → 62%).

---

## 5. Appeals Workflow

- **Who can appeal:** The creator of the content (or the platform acting for
  them). They reference the content by its id.
- **What they provide:** The content id and a short written reason explaining
  why they think the label is wrong (for example, "I wrote this myself, here is
  my draft history").
- **What the system does when an appeal arrives:**
  1. It finds the original decision by content id.
  2. It changes that content's status to **"under review."**
  3. It writes the appeal to the audit log, right next to the original decision,
     with the creator's reason and the time.
  4. It returns a confirmation that the appeal was received.
  5. Automated re-classification is **not** done. A human decides later.
- **What a human reviewer sees in the appeal queue:** A list of items with status
  "under review." For each: the content id, the original text, both signal
  scores, the final score, the label that was shown, the creator's appeal reason,
  and the timestamps. This gives the reviewer everything needed to judge the
  case.

---

## 6. Anticipated Edge Cases

These are specific cases the system will likely handle poorly.

1. **A minimalist poem with heavy repetition and simple words.** Short poems use
   few words, repeat lines, and keep sentence length even. The stylometric
   signal reads this as low variance and low vocabulary richness — the same
   pattern AI shows. So a real human poem could be pushed toward an AI score.
   Mitigation: lower the stylometric weight on short text and lean on the LLM
   signal; favor "uncertain" over "AI" when text is short.

2. **A polished, formal essay by a skilled human writer.** Clean, balanced,
   grammatically perfect prose is exactly what AI also produces. A professional
   human essay can read as "too smooth" to the LLM signal and score high for AI.
   This is the classic false positive. Mitigation: the high 0.70 AI threshold
   and the clear appeal path.

3. **Lightly edited AI text.** A person who takes AI output and rewrites a few
   sentences can break both signals. The text gains some human bumpiness but
   keeps AI smoothness. This often lands in "uncertain," which is the honest
   answer.

4. **Very short submissions (a sentence or two).** Too little text for either
   signal to be reliable. The system should treat these as low-confidence and
   prefer the "uncertain" label.

---

## Architecture

### Submission flow

```
            raw text + creator id
Creator  ───────────────────────────▶  POST /submit  (Flask)
                                            │
                                            │ raw text
                                            ▼
                                       Rate Limiter (Flask-Limiter)
                                            │ allowed request
                                            ▼
                                       Signal 1: LLM (Groq)
                                            │ llm_score (0–1)
                                            ▼
                                       Signal 2: Stylometry (Python)
                                            │ stylometric_score (0–1)
                                            ▼
                                       Confidence Scorer
                                            │ final_score (0–1)
                                            ▼
                                       Label Maker
                                            │ label text + band
                                            ▼
                                       Audit Log (SQLite/JSON)
                                            │ decision saved
                                            ▼
Creator  ◀───────────────────────────  JSON response
            result + final_score + label text
```

### Appeal flow

```
            content id + appeal reason
Creator  ───────────────────────────▶  POST /appeal  (Flask)
                                            │ content id + reason
                                            ▼
                                       Status Update  (status = "under review")
                                            │ updated record
                                            ▼
                                       Audit Log  (appeal saved next to decision)
                                            │ appeal logged
                                            ▼
Creator  ◀───────────────────────────  JSON response
            confirmation + new status
```

**Narrative.** In the submission flow, raw text enters through `POST /submit`,
passes the rate limiter, then runs through both detection signals; the scorer
blends their scores into one confidence value, the label maker turns that value
into plain-language text, the decision is saved to the audit log, and the
response returns the result, score, and label. In the appeal flow, a creator
sends `POST /appeal` with the content id and their reasoning; the system sets the
content status to "under review," writes the appeal into the audit log beside the
original decision, and returns a confirmation — no automatic re-scoring happens.

---

## API Surface (the contract)

| Endpoint        | Method | Accepts                                   | Returns                                                                 |
|-----------------|--------|-------------------------------------------|------------------------------------------------------------------------|
| `/submit`       | POST   | `{ "text": "...", "creator_id": "..." }`  | `{ content_id, result, final_score, signals: {llm, stylometric}, label }` |
| `/appeal`       | POST   | `{ "content_id": "...", "reason": "..." }`| `{ content_id, status: "under review", message }`                       |
| `/log`          | GET    | (optional) query filters                  | List of audit log entries (decisions + appeals)                        |
| `/queue`        | GET    | (none)                                     | List of items with status "under review" for human reviewers           |
| `/health`       | GET    | (none)                                     | `{ "status": "ok" }`                                                    |

Example `/submit` response:

```json
{
  "content_id": "c_123",
  "result": "likely_ai",
  "final_score": 0.81,
  "signals": { "llm": 0.88, "stylometric": 0.70 },
  "label": "🤖 Likely AI-generated. Our checks strongly suggest this text was created with AI tools (confidence: 81%). ..."
}
```

---

## False Positive Walkthrough

A human writer submits a clean, formal essay. The LLM signal scores it 0.60
("formal but specific, so not clearly AI"). The stylometric signal scores it
0.59 (uniform sentences — its blind spot). The final score is
`(0.7 * 0.60) + (0.3 * 0.59) = 0.60`. Because 0.60 is below the 0.70 AI
threshold, the label is **"uncertain,"** not "AI." The score honestly shows the
doubt, and the label says we are not sure rather than accusing the writer. The
creator can still appeal: they send `POST /appeal` with their content id and the
reason ("I wrote this; here is my draft history"). The status flips to "under
review," the appeal is logged next to the decision, and a human reviewer can open
the queue and decide. This walkthrough is why the AI threshold is high and why
the middle band exists — it directly shapes the Milestone 2 thresholds.

---

## AI Tool Plan

For each implementation milestone, this lists which parts of this plan I will
give the AI tool, what I will ask it to build, and how I will check the result.

### M3 — Submission endpoint + first signal

- **Spec sections I will provide:** Section 2 (Detection Signals, especially
  Signal 1), the API Surface table, and the submission-flow diagram.
- **What I will ask for:** A Flask app skeleton with a `POST /submit` endpoint,
  plus the Signal 1 function that calls Groq and returns a 0–1 score.
- **How I will verify:** I will call the Signal 1 function alone with a few
  clearly human and clearly AI texts and check the scores look sensible *before*
  wiring it into the endpoint. Then I will test the endpoint with a sample
  request.

### M4 — Second signal + confidence scoring

- **Spec sections I will provide:** Section 2 (Detection Signals, Signal 2 and
  the combine rule), Section 3 (Uncertainty Representation), and the diagram.
- **What I will ask for:** The Signal 2 stylometric function and the confidence
  scorer that blends both signals into one final score.
- **How I will check:** I will run clearly AI text and clearly human text and
  confirm the scores differ meaningfully (human low, AI high, with a real gap).
  I will tune weights/thresholds if the gap is too small.

### M5 — Production layer (labels + appeals + audit log + rate limit)

- **Spec sections I will provide:** Section 4 (Transparency Label variants),
  Section 5 (Appeals Workflow), and the appeal-flow diagram.
- **What I will ask for:** The label generation logic (three variants), the
  `POST /appeal` endpoint, the audit log writer, and rate limiting on `/submit`.
- **How I will verify:** I will craft inputs that hit each of the three label
  bands so all three label variants are reachable, and I will submit an appeal
  and confirm the status changes to "under review" and the appeal appears in the
  audit log.

---

## Notes

- Confidence score direction: higher = more likely AI, throughout the system.
- The false-positive asymmetry (hint from the spec) is handled by the high 0.70
  AI threshold and the wide "uncertain" middle band.
- **Update this file before starting any stretch feature.**
