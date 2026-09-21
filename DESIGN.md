# PII Redaction System — Design

Status: planning, 2026-09-21. Nothing measured yet; latency/cost numbers are estimates or vendor claims and are labelled so. Step 5 (eval harness) replaces them with measured values.

## Principles

1. **Recall first.** Every finder's output is unioned. A span is dropped only if it came from a single finder with confidence below the config threshold.
2. **Every tool is a plugin.** Parser, OCR, NER, LLM, judge, faker are registries; the choice is a config string.
3. **Page = unit of work.** Everything is keyed by `(doc_id, page_no)`; workers are stateless; results merge by `page_no`.
4. **Offset map from the start.** Detection runs on normalized text; every character of that text knows which source word it came from. Nothing is written back without it.
5. **Audit every stage.** One structured log record per stage per page; every final span carries provenance.

## Stated defaults (assumptions — change in config)

| Decision | Default | Alternatives in config |
|---|---|---|
| LLM | Claude Haiku 4.5 (~$0.35 / 128-page doc, est.) | Gemini 3.8 Flash, DeepSeek V4.1 Flash, Ollama local |
| Company names | redact all ORGs | allowlist for regulators/exchanges/statutes: SEBI, BSE, NSE, RBI, Companies Act, SEBI ICDR Regulations |
| Order/ticket/page numbers, CIN, SEBI registration numbers | **not** PII — left as-is | flip per type in `pii_types.yaml` |
| Indian identifiers (PAN, Aadhaar, DIN, GSTIN, IFSC, UPI ID) | included as PII types | disable per type |

## Pipeline

```
0 ingest → 1 parse → 2 offset map + normalize → 3 route → 4 OCR (routed only)
→ 5 finders (regex | GLiNER2-PII | LLM | propagation) → 6 merge → 7 judge
→ 8 entity clustering + surrogates → 9 write DOCX (+ PDF) → 10 verify → 11 audit/eval
```

Steps 1–7 run per page in parallel. Step 8 needs the whole document (consistent fake names). Step 9 writes in `page_no` order.

### Step 0 — Ingest

- `doc_id = sha256(file bytes)`. Work key = `(doc_id, page_no, pipeline_version, config_hash)`. Same key → cached result. Retries and re-uploads are idempotent.
- Input: PDF or DOCX. Store original untouched.
- Latency: ms. Cost: $0. Dev: 0.5 day.

### Step 1 — Parse

| | Primary | Fallback |
|---|---|---|
| PDF | **Docling** → `DoclingDocument` (typed blocks: text / table / picture / section_header / list_item, each with bbox + score, reading order, table cells) | Docling fails on page → PyMuPDF text only → if empty → treat page as scanned (step 4) |
| PDF, raw view | **PyMuPDF** `page.get_text("words")` → word boxes `(x0,y0,x1,y1,text,block,line,word_no)`; page render to PNG at 300 DPI for OCR | — |
| DOCX | Docling (paragraphs, tables, inline images) | python-docx |

Why both Docling and PyMuPDF: Docling gives structure (what is a table, what is a picture); PyMuPDF gives the exact word rectangles needed for the offset map and for PDF in-place redaction.

- Latency (est.): PyMuPDF ~10 ms/page; Docling with layout model ~0.3–1 s/page on CPU. 128 pages on 8 cores ≈ 30–60 s.
- Cost: $0. Dev: 1.5 days.

### Step 2 — Offset map + normalized views

Build two text views per page. Each character in each view carries `source_word_id` (from PyMuPDF words, or from an OCR word after step 4).

- **View A (raw):** PyMuPDF words joined in reading order. Catches whatever Docling's layout mis-segments.
- **View B (layout):** Docling blocks in reading order; table cells joined; fixes applied:
  - collapse columns of single characters (`P r o m o t e r` → `Promoter`) when the chars are x-aligned in one cell
  - rejoin `word-\nword` hyphenation
  - join lines inside a block (`cs.connect@kshinternational.co` + `m`)
  - strip trailing footnote markers `*^#&()` from tokens (kept in output)
  - prepend the last 50 words of the previous page (window) so entities split across pages are seen once whole
- Repeated headers/footers detected by cross-page repetition and tagged (finders still run on them; the tag is provenance).

Spans found in either view resolve to source word ids → rects → output positions.

- Latency: ms/page. Cost: $0. Dev: 2 days (this is the hardest piece; do it before any finder).

### Step 3 — Route

Rules on Docling block types + three PyMuPDF signals (text-layer chars per page area, image count/area, single-letter-token ratio). No ML classifier.

| Condition | Action |
|---|---|
| block is `text` and page has a text layer | no OCR |
| block is `picture` (ID card, stamp, signature) | VLM OCR on the crop |
| block is `table` on a page without a text layer | table-aware OCR |
| page has no text layer, or gibberish ratio > threshold (legacy fonts) | RapidOCR on full page |
| layout score low / signals conflict | OCR anyway and union with text layer (recall wins) |
| page is "hard" (any OCR, or high single-letter ratio) | mark for LLM finder |

- Latency: ms. Cost: $0. Dev: 0.5 day.

### Step 4 — OCR (only routed blocks)

| Region | Engine | Fallback |
|---|---|---|
| scanned text | **RapidOCR** (PaddleOCR models on ONNX, CPU; vendor claim 0.2–1 s/page) | char confidence < 0.7 → PaddleOCR-VL (GPU) or VLM via LLM provider |
| table on scan | PaddleOCR-VL / Docling TableFormer | RapidOCR + cell clustering |
| picture (PAN card etc.) | VLM OCR: PaddleOCR-VL locally if GPU, else the configured LLM's vision endpoint (Haiku 4.5) | RapidOCR on the crop |

OCR words get ids and rects like PyMuPDF words and enter the offset map.

On this prospectus: 127 pages have a text layer → 0 OCR; 1 page (PAN card image) → 1 VLM call.

- Latency (est.): RapidOCR ~0.5 s/page routed; VLM crop 2–5 s. Cost: RapidOCR $0; VLM ~$0.005/image. Dev: 1.5 days.

### Step 5 — Finders (run in parallel per page, on both views)

| Finder | Catches | Latency (est.) | Cost |
|---|---|---|---|
| **Regex + validators** — email, phone (digit-run tolerant, `+ 91 20 4505 3237`), PAN (`AAAAA9999A`), Aadhaar (Verhoeff), DIN, CIN, GSTIN, IFSC, UPI ID, IPv4/6, credit card (Luhn), SSN, dates with DOB context words | structured identifiers | ms | $0 |
| **GLiNER2-PII** (fastino, Apache-2.0, 205M params, labels passed at inference from config) | names, orgs, addresses, DOB, free-form IDs | ~100–300 ms/page CPU (vendor claim) | $0 |
| **LLM finder** (Haiku 4.5 default) — runs on pages routed "hard" only, plus a configurable random sample of easy pages as a recall spot-check | spaced letters, context-dependent items (“Father's Name”), addresses across lines | 2–5 s/chunk, 10 concurrent | ~$0.003/page |
| **Entity propagation** — after the three above, build a dictionary of confirmed entities and their variants (case, initials, without middle name, without honorific) and string-search every page | second and later mentions, split mentions | ms | $0 |

LLM finder rules:
- Chunk ~1500 tokens with 100-token overlap.
- Prompt: "list every PII span verbatim with its type from this list: [config types]". Structured JSON output.
- **The LLM returns verbatim substrings, never offsets.** We locate them by exact (then whitespace-tolerant) search in the page text. Unlocatable strings are logged and discarded.
- API error → retry ×2 → fall back to Ollama if configured → else page marked `llm_skipped` in audit (never silent).

- Dev: regex 1 day; GLiNER 0.5 day; LLM finder 1 day; propagation 0.5 day.

### Step 6 — Merge

Union spans from all finders and both views; map to source word ids; overlapping spans → longest wins, all votes kept in provenance. Deterministic order by `(page_no, start_word_id)`.

- Latency: ms. Dev: 0.5 day.

### Step 7 — Judge (type + keep/drop)

Order:
1. **Rules** — validator-passed structured types are final (PAN, Aadhaar, card, email, IP…).
2. **GLiNER type** — for names/orgs/addresses when finders agree.
3. **Tie-breaker on conflicts** — JEV `Choice` over the config label set + `NOT_PII` (calibrated probability), or Haiku structured output if JEV isn't configured. Input: span + ±200 chars context + finder votes.
4. **Policy** — ORG allowlist marks a span `exempt` (kept in audit, not redacted).

Drop rule: a span is dropped only if exactly one finder produced it and its confidence < threshold. Multi-finder spans are never dropped. Below-threshold single-finder name-like spans go to the review queue instead of being dropped.

- Latency: ~100 ms per conflict; ~50 conflicts/doc (est.). Cost: JEV $0.0004/decision → ~$0.02/doc. Dev: 1 day.

### Step 8 — Entity clustering + surrogates (whole document)

Goal: **same real value → same surrogate, everywhere, every time** — including partial mentions — so the pattern in the redacted document is preserved for a downstream model.

1. **Cluster spans into entities**: normalized string match + variant rules (case, initials, honorific dropped, middle name dropped). "Kushal Subbayya Hegde", "KUSHAL S. HEGDE", "Mr. Hegde" → one person entity with name tokens `{first: Kushal, middle: Subbayya, last: Hegde}`.
2. **Deterministic surrogate = HMAC(secret_salt, canonical_value) → seed → Faker.** Same input, same output across runs *and across documents*; without the salt the mapping cannot be reversed or linked.
3. **Names are mapped token-by-token**, not as a whole string: `Kushal→John`, `Subbayya→Michael`, `Hegde→Doe`. Then every partial mention stays consistent: "Mr. Hegde" → "Mr. Doe", "Kushal" → "John", "Rajesh Kushal Hegde" → "Peter John Doe". Family members sharing a surname share the fake surname — correct behaviour.
4. **Derived identifiers follow the name**: `rohan.dey@gmail.com` → `peter.parker@example.com` (the email surrogate is built from the person's name surrogate, matching the assignment example).
5. Type-aware surrogates elsewhere: phone → same country code and format, different digits; PAN/Aadhaar/card → format- and checksum-valid fakes; address → fake address with the same line count; company → fake name + same suffix ("Private Limited"); DOB → date shifted by a per-entity offset; IP → RFC 5737 documentation range.
6. **Length-matched where possible** (name and company surrogates chosen from candidates within ±20% of the original length) so in-place PDF replacement does not overflow the original box.
7. Persist `mapping.json` — real ↔ surrogate ↔ type ↔ entity_id — encrypted at rest, access-controlled. This is the reversible audit trail and the reviewer's key.

**What goes inside the redacted document (config `legend`):**
- `none` — body only (default for production; the real↔fake map never travels with the redacted file).
- `surrogates` — an appended "Redaction legend" table listing *surrogate → type → entity_id* (e.g. "John Doe · PERSON · P1"). No real values. Lets a downstream model see that P1 is one consistent person without leaking who.
- `full` — real → fake table appended. **Only for the graded submission / internal review**; this defeats redaction if the file leaves the trust boundary.

- Latency: ms. Dev: 1.5 days.

### Step 8b — Names that are also ordinary words

Examples in this document: **Broad** Family Trust, **Everest**, **Rakhi** (festival), **Sandesh** (means "message"), **Anand**, **Bijlee**; English: May, Bill, Mark, Hope, Rose. Two failure modes, both break the pattern: redacting the common word (false hit) or missing the name (miss).

Rules:
1. Finders that use context (GLiNER2-PII, LLM) decide the first mention — never a bare gazetteer.
2. **Propagation (step 5d) is gated** when the token is in the common-word list: require whole-word match **and** at least one of — capitalisation matches the entity, a title/honorific precedes it (Mr./Smt./Dr.), it sits in a name-shaped sequence (another known name token adjacent), or it is inside a table column already labelled as a name column. A lowercase "broad view" or "a broad range" is never touched.
3. Ambiguous single-token hits (capitalised at sentence start, no other signal) go to the **judge** (JEV/Haiku with ±200 chars context) → `PERSON` / `NOT_PII`; below threshold → review queue, not silently dropped.
4. Multi-token mentions ("Broad Family Trust") are always safe: matched as the full entity string.

### Step 9 — Write the redacted document (same format as input, same layout)

Rule: **PDF in → PDF out; DOCX in → DOCX out.** Layout, fonts, tables, colours, images, headers/footers are preserved because we edit the original in place — we do not rebuild the document.

**PDF → PDF (PyMuPDF, in place):**
- For every span: source word rects from the offset map → `page.add_redact_annot(rect, text=surrogate, fontname=<original font>, fontsize=<original>)` → `page.apply_redactions()`. This **removes the underlying text objects** (true redaction), then draws the surrogate in the same box, same font, same colour. Spans across line breaks get one annot per line fragment, surrogate split proportionally.
- Overflow: length-matched surrogates (step 8.6); if still too long, PyMuPDF shrinks the font to fit; logged as `fit_shrunk` in the audit.
- Images with PII (PAN card): render the crop, draw opaque boxes over the OCR word rects of detected spans, write the surrogate text into the boxes, re-insert the image at the same rect. Alternative via config: solid block + "[identity document redacted]".
- Bookmarks, links, form fields, metadata (`author`, `title`) are scrubbed too — metadata is a common leak.
- Vector/outline text (no text layer) is handled by the OCR path: rects come from OCR words.

**DOCX → DOCX (python-docx, in place):**
- Iterate every paragraph in body, tables (nested included), headers, footers, footnotes, text boxes, comments. Spans map to run offsets; replacement is done **inside runs** so bold/italic/colour/size are untouched. A span crossing run boundaries: put the surrogate in the first run, empty the rest.
- Inline images with PII: same image-redaction as PDF, image part replaced in the package.
- Document properties (core.xml author, last modified by) scrubbed.
- Tracked changes/comments: redacted as text (they are text).

**Both:** pages/paragraphs are processed in parallel but written back in document order; a single writer commits the file.

**Assignment note:** the brief asks for a `.docx` output for a PDF input. We produce **both**: the same-format redacted PDF (primary) and a DOCX conversion of it (via Docling → python-docx) to satisfy the brief; the README says which is which.

- Latency (est.): PDF a few seconds per document; DOCX < 1 s. Cost: $0. Dev: PDF in place 2 days; DOCX in place 1.5 days; image redaction 1 day.

### Step 10 — Verify the output

1. Extract text from the produced DOCX/PDF.
2. Search for every original entity string and variant from `mapping.json`. Any hit → job fails, page listed.
3. Re-run regex + GLiNER on the output; new spans → review queue.
4. Optional LLM residual-leak pass: "list any remaining PII" per page. This is the all-pages safety net when only a subset is hand-labelled.

- Latency: ~ same as steps 5a–b. Cost: $0 without LLM pass. Dev: 0.5 day.

### Step 11 — Audit + eval

**Stage log** (JSONL, one record per stage per page):
```
run_id, doc_id, page_no, stage, backend, backend_version, input_ref, output_ref,
confidence, evidence, latency_ms, cost_usd, ts
```
**Span table** (one row per final span): `doc_id, page_no, start_word_id, end_word_id, text, type, decision (redact|exempt|review|dropped), judge_prob, provenance[], surrogate, human_label`.

**Eval** (`eval.py`): ground truth = hand-labelled CSV for ~15 pages (cover, promoter tables, bankers page, PAN card). Reports per-type precision / recall / F1 (partial-overlap credit) + token accuracy, plus the miss list and false-hit list with a one-word reason each. Measured recall is reported for the labelled subset; step 10 covers the rest.

**Review**: CSV + HTML side-by-side (original vs redacted, spans highlighted). Reviewer fills `human_label`. Later: UI.

**Learning loop** (later): thresholds and regex/gazetteer additions auto from confirmed misses; GLiNER2-PII fine-tune and JEV calibration on a schedule, gated on held-out recall ≥ current.

- Dev: eval 1 day; review export 0.5 day.

## What the LLM is used for (and not)

Used for:
1. **Recall backstop** on hard pages (OCR'd, spaced letters, images) — finder of last resort.
2. **Context adjudication** on conflicts — person vs place (“Hegde”, “Baner”), private company vs regulator.
3. **VLM OCR** of picture blocks (ID cards) when no local VLM.
4. **Residual-leak pass** on the output (optional).

Not used for: parsing, offset mapping, text replacement, document generation. Those are deterministic.

## Config

`pii_types.yaml` — one block per type:
```yaml
- name: PAN
  enabled: true
  regex: ["[A-Z]{5}[0-9]{4}[A-Z]"]
  validator: pan_format
  ner_labels: ["permanent account number", "PAN"]
  llm_hint: "Indian income-tax PAN, 10 chars AAAAA9999A"
  context_words: ["PAN", "permanent account"]
  faker: pan
  policy: redact          # redact | exempt | review
```
`backends.yaml` — `parser: docling`, `ocr: {text: rapidocr, picture: haiku_vision}`, `ner: gliner2-pii`, `llm: {provider: haiku, model: claude-haiku-4-5}`, `judge: [rules, gliner, jev]`, thresholds, ORG allowlist.

## Totals for this document (128 pages, estimates)

| Configuration | Wall time | $ |
|---|---|---|
| Deterministic only (steps 1–2, 5a, 5b, 5d, 6–10) | ~1–2 min on 8 cores | $0 |
| + LLM on hard pages + PAN-card VLM + JEV tie-breaks | ~2–3 min | ~$0.05–0.40 |
| + LLM on every page + residual-leak pass | ~4–5 min | ~$0.70 |

## Build order and effort

| Phase | Steps | Dev effort |
|---|---|---|
| 1. Skeleton: config, interfaces, audit record, idempotency | 0, 11 (log only) | 1.5 days |
| 2. Parse + offset map + regex → first redacted DOCX | 1, 2, 5a, 6, 8, 9-DOCX | 5 days |
| 3. GLiNER2-PII + propagation + judge rules | 5b, 5d, 7 | 2 days |
| 4. Ground truth + eval harness → first numbers | 11 | 1.5 days |
| 5. Routing + OCR + LLM finder + JEV, each justified by an eval delta | 3, 4, 5c, 7-tiebreak | 4 days |
| 6. Verify pass + PDF in-place + review export | 10, 9-PDF | 2 days |

Total ≈ 16 dev-days for the full design; phases 1–4 (≈ 10 days) produce a complete, evaluated submission.
