# PII Redaction Tool

Reads a PDF or DOCX, finds personally identifiable information, and writes back the **same format with the
same layout**, every PII value replaced by a realistic fake — consistently (the same person is always the same
fake person, on every page and in every partial mention). Built for the "Red Herring Prospectus" assignment;
designed to be extended to new document types and new PII types through config.

```
Input  : samples/rhp.pdf  (or .docx)
Output : out/<doc_id>/rhp.redacted.pdf     same format, layout preserved (true redaction, text removed)
         out/<doc_id>/rhp.redacted.docx    DOCX version (assignment deliverable; approximate layout for PDF input)
         out/<doc_id>/mapping.json|csv     real -> fake table for this doc_id (keep private)
         out/<doc_id>/spans.csv            every redacted mention: page, text, type, entity, finder, confidence
         out/<doc_id>/review.csv           low-confidence candidates for a human to accept/reject
         out/<doc_id>/review.jsonl         LLM reviewer flags per page (leaks / wrong replacements / inconsistencies)
         out/<doc_id>/audit.jsonl          one record per stage per page: backend, latency, confidence, evidence
         out/<doc_id>/summary.json         run summary incl. the verify result
```

## Run it

```bash
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e ".[dev]"
brew install ollama && ollama serve &   && ollama pull qwen2.5:7b      # optional: local LLM finder + reviewer

python -m pii_redact.cli samples/rhp.pdf                  # full run (LLM on hard pages, reviewer on)
python -m pii_redact.cli samples/rhp.docx --no-review     # DOCX in -> DOCX out
python -m pii_redact.cli samples/rhp.pdf --pages 1-6,128 --no-llm   # quick, deterministic only
pytest -q                                                 # 56 tests
python eval/run_eval.py --note "what I changed"           # score on the labelled pages, log to eval/RUNS.md
```

No API keys are needed. With `llm.provider: none` in `config/backends.yaml` the whole pipeline is offline and
deterministic. Everything runs on CPU (Apple M4 Pro: ~2 s/page without the LLM).

## Approach: many finders, one judge

Recall comes from running several independent detectors and taking the **union**; precision comes from a rule-based
judge that only ever drops a span found by a single finder with low confidence.

| Step | What | Backend (config-selectable) |
|---|---|---|
| Parse | words with exact positions, images, per-page signals | PyMuPDF (PDF), python-docx (DOCX) |
| Normalize | two text views with a char→word offset map: raw, and layout (table cells rejoined, `P r o m o t e r` collapsed, hyphens/line-broken emails rejoined) | — |
| Route | page is "hard" if text density is low, >15% of tokens are single letters, or images cover >10% | rules, thresholds in config |
| OCR | image blocks only (the PAN card on page 128) | RapidOCR (ONNX, CPU) |
| Find | regex + checksum validators (email, phone, PAN, Aadhaar/Verhoeff, DIN, GSTIN, IFSC, card/Luhn, SSN, IP, DOB-with-context) | — |
| Find | PIN-code-anchored Indian address finder | — |
| Find | GLiNER2-PII encoder (labels come from config, no training) | `fastino/gliner2-privacy-filter-PII-multi` |
| Find | LLM on hard pages + 10% sample, returns verbatim strings that we locate ourselves | Ollama `qwen2.5:7b` (or `claude-haiku-4-5`) |
| Find | propagate: every confirmed name/org/email/phone is searched on every page incl. partial mentions ("Mr. Hegde") and spaced/glued spellings | — |
| Merge | union by word ids; validated identifiers set boundaries; a span running past an identifier is trimmed, not swallowed | — |
| Judge | type precedence (validated regex > GLiNER > LLM), regulator allowlist, generic-role filter ("our Company", "Managing Director", "BRLMs"), single-finder thresholds → keep / review / drop | — |
| Surrogates | entities clustered across pages; `HMAC(salt, value)` seeds Faker; names mapped **token by token** so "Rajesh Kushal Hegde" and "Mr. Hegde" agree; emails derived from the person's fake name | Faker |
| Write | PDF: `add_redact_annot` + `apply_redactions` (text is removed, not painted over), images re-inserted redacted, metadata scrubbed. DOCX: edits inside runs, images swapped, properties scrubbed | PyMuPDF, python-docx |
| Verify | output text searched for every original value and variant (whitespace/case-insensitive); any hit fails the run | — |
| Review | LLM re-reads original vs redacted page + expected mapping, flags problems; flag-only | Ollama |

What the LLM is used for: recall backstop on hard pages, and the reviewer. Not for parsing, replacement, or writing.

## What counts as PII here (explicit choices)

- **Redacted:** people's names (full and partial), emails, phones, private companies / banks / law firms / auditors /
  trusts / LLPs, physical addresses (offices and directors' homes), dates of birth, PAN, Aadhaar, DIN, GSTIN, IFSC,
  UPI IDs, SSNs, card numbers, IPs.
- **Not redacted (documented choice):** regulators, exchanges and statutes (SEBI, BSE, NSE, RBI, RoC, Companies Act —
  `allowlist` in `config/pii_types.yaml`), CIN and SEBI registration numbers (identify a filing, not a person), page
  numbers, offer/filing/meeting dates, amounts, share counts, newspaper names, the company's own website.
- Order/ticket-style numbers are not treated as sensitive. Flip any of this per type in the config.

## Adding or removing a PII type

One block in `config/pii_types.yaml`:

```yaml
- name: PASSPORT
  enabled: true
  regex: ['\b[A-Z][0-9]{7}\b']
  validator: null              # or a function name in finders/validators.py
  ner_labels: ["passport number"]
  llm_hint: "Indian passport numbers, one letter + 7 digits"
  context_words: ["passport"]
  requires_context: true
  faker: alnum_same_shape
  policy: redact               # redact | exempt | review
```

Regex, GLiNER labels and the LLM hint all read from this block; the surrogate generator falls back to
"same shape" for unknown types. `enabled: false` removes a type. Backends (parser, OCR, NER model, LLM provider,
reviewer, thresholds, legend mode, salt) live in `config/backends.yaml`.

## Evaluation

**Ground truth:** 199 PII mentions hand-labelled on 14 pages of the prospectus (cover pages 1–6, general-information
pages 110–116 with directors' home addresses and DINs, and page 128, the scanned PAN card) —
`eval/ground_truth/rhp_pages.csv`, rules in `eval/ground_truth/README.md`.

**Matching:** same page, same type, case/whitespace-insensitive equality or containment; one-to-one, greedy by longest.
Token accuracy = fraction of tokens on the labelled pages whose redact/keep decision is right.

**Every change is logged with its score** in `eval/RUNS.md` (commit, note, per-type F1); the latest full report with
the miss list and false-hit list is `eval/LATEST_REPORT.md`, and each run's report sits in `out/<doc_id>/EVAL_REPORT.md`.

Latest labelled-page result (commit `f2299bb`, see `eval/RUNS.md`):

| micro precision | micro recall | micro F1 | token accuracy |
|---|---|---|---|
| 0.902 | 0.930 | 0.916 | 0.977 |

Per type F1: PERSON 0.945 · ORG 0.903 · EMAIL 0.952 · PHONE 0.930 · ADDRESS 0.852 · DIN 0.933 · PAN 0.667 · DOB 0.667
(PAN/DOB are each 1 true mention; the "false hit" is the same value found in the second copy of the card image the PDF embeds).

**Recall on unlabelled pages** is covered by `verify.py` (every original value from the mapping searched in the
output; a hit fails the run) and the flag-only LLM review pass. Both are evidence, not proof; the review queue is
where a human closes the gap.

## False positives / negatives observed

- Names broken letter-by-letter in narrow table cells ("L ok esh Sh ah") are missed on their first sighting;
  they are caught by propagation once the same name appears cleanly elsewhere.
- Two names joined by a slash ("Kishan Rastogi/Abhijit Diwan") are one token in the text layer; both get redacted,
  but as one span, so the evaluation counts one of them as missed.
- A building name that is also a firm's name ("ICICI Venture House") is labelled ORG by the model and ADDRESS by the
  ground truth; it is redacted either way.
- OCR of the scanned card reads "tininfo@nsdLco.in" for "tininfo@nsdl.co.in" — redacted, but counted as a
  false hit against the transcribed truth. The card's back-side address is partially captured.
- DIN on a continuation page (111) is missed because the "DIN" column header is on the previous page
  (`context_scope: page`).
- Generic-role filter can hide a real company whose name is entirely generic words; none in this document.

## Design trade-offs (v1)

- **PyMuPDF instead of Docling/Firecrawl** for parsing: this document has a text layer; PyMuPDF gives the exact word
  rectangles needed for in-place redaction in ~10 ms/page. Docling (local) or Firecrawl (hosted) fit behind the same
  `Parser` contract for scanned or messy layouts. Both were evaluated, neither is used in v1.
- **RapidOCR** only on image blocks, never on whole text-layer pages: 127 of 128 pages skip OCR entirely.
- **GLiNER2-PII** rather than spaCy or Presidio: labels are passed at inference time from config, so a new type needs
  no training; 205M params, Apache-2.0, ~1 s/page on CPU. Its confidence is well calibrated on names/emails/phones,
  poor on addresses (hence the PIN-anchored finder) and on scanned text.
- **Local Ollama (`qwen2.5:7b`)** as the LLM: free and private; ~15 s/page, so it runs only on hard pages and a
  sample. `claude-haiku-4-5` is a config switch (~$0.35 for this document). DeepSeek/Gemini Flash can be added as
  providers; DeepSeek's API is China-hosted, which matters for real Indian financial PII.
- **No JEV / learned judge in v1**: the rule judge plus the review queue is enough for this document; a calibrated
  judge needs labelled data the review loop will produce.
- **Legend `full`** (real→fake table appended to the output) is on for the graded submission so the mapping is
  visible; production default is `none`, with the mapping kept in `mapping.json` only.
- **True redaction in PDF** removes the text objects; the surrogate is drawn in Helvetica at ~80% of the original
  size in the same box, so a longer fake can look slightly smaller. DOCX keeps the original runs and styles.

## Known limitations

- PDF→DOCX conversion (assignment deliverable for PDF input) is approximate: paragraphs and tables, no colours,
  columns or images.
- OCR redaction of images draws over word boxes; a very poor scan may leave fragments legible in the image.
- The 7B reviewer sometimes flags correct replacements and misses planted leaks; `verify.py` is the real leak check.
- Handwritten or Devanagari text is not handled (RapidOCR's default English model).
- Unit of work is the page, so a 300-page file is just slower; upload API, object storage, queue and multi-tenant
  concurrency are out of scope for v1 (see DESIGN.md).

## Future scope (agreed, not built)

Self-learning loop (thresholds and gazetteer updated from reviewed misses, periodic GLiNER fine-tune gated on
held-out recall), JEV as a calibrated judge, Docling/VLM-OCR backends, upload API + S3 + workers, review UI.

## Layout

```
pii_redact/            parse, ocr, normalize, finders/, merge, judge, surrogates, writers/, verify, review, pipeline, cli
config/                pii_types.yaml (what is PII), backends.yaml (which tools, thresholds)
eval/                  ground_truth/, eval.py, run_eval.py, RUNS.md (change log with scores), LATEST_REPORT.md
tests/                 56 tests: unit per module, end-to-end on a synthetic PDF, failure paths
DESIGN.md              full design incl. production path and future scope
```
