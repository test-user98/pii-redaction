# PII Redaction Tool

Takes a PDF or DOCX, finds personal data, and writes back the **same file format with the same layout**, every
value replaced by a realistic fake. The same person is always the same fake person — on every page, in every
partial mention ("Rajesh Kushal Hegde", "Mr. Hegde"), and in their email. New PII types are added in a YAML file.

**Evaluation report (public):** https://claude.ai/artifact/5xUfowKhS8MqsAhhFP5rCJ

## How it works

![PII redaction pipeline](docs/architecture.svg)

1. **Parse** the file into words with exact positions (PyMuPDF / python-docx) and build a text view where table
   cells, hyphenated lines and letter-broken names are rejoined. Every character knows its source word.
2. **Route**: a page is "hard" if its text layer is thin, tokens are single letters, or images cover it. Only image
   blocks get OCR (RapidOCR); only hard pages get the LLM.
3. **Find** with independent detectors and take the **union**: regex + checksum validators (email, phone, PAN,
   Aadhaar, DIN, GSTIN, IFSC, card, SSN, IP, DOB), a PIN-code-anchored address finder, the GLiNER2-PII encoder
   (labels from config), an LLM on hard pages (local Ollama `qwen2.5:7b`, or Claude Haiku), and propagation of every
   confirmed name to every page.
4. **Judge**: validated identifiers win type; regulators/exchanges/statutes are allowlisted; generic role phrases
   ("our Company", "Managing Director") are dropped; single-finder low-confidence spans go to `review.csv`.
5. **Surrogates**: entities are clustered across pages; `HMAC(salt, value)` seeds Faker; names map token by token.
6. **Write** in place: PDF true redaction (text removed, fake drawn in the same box), DOCX run-level edits, images
   re-inserted redacted, metadata scrubbed. Then **verify** by searching the output for every original value, and an
   LLM reviewer flags anything suspicious per page.

Every step logs backend, latency and confidence to `audit.jsonl`; `mapping.csv` is the real→fake table for the run.

## Run

```bash
uv venv --python 3.12 && source .venv/bin/activate && uv pip install -e ".[dev]"
python -m pii_redact.cli samples/rhp.pdf            # → out/<doc_id>/rhp.redacted.pdf + .docx + mapping.csv
python -m pii_redact.cli samples/rhp.docx           # DOCX in → DOCX out
uvicorn pii_redact.api:app                          # POST /redact (file) → job id → GET /jobs/{id}/download
pytest -q                                           # unit, end-to-end, failure paths
python eval/run_eval.py --note "what changed"       # score on the labelled pages, appends to eval/RUNS.md
```

LLM backend is a config switch (`config/backends.yaml`): `ollama` (default, free, local) or `anthropic`
(`ANTHROPIC_API_KEY`, ~$0.40 per 128-page document). `provider: none` runs fully offline.

## What is treated as PII

Redacted: names, emails, phones, private companies/banks/law firms/auditors/trusts, addresses, dates of birth,
PAN, Aadhaar, DIN, GSTIN, IFSC, SSN, card numbers, IPs.
Not redacted (explicit choice): regulators and statutes (SEBI, BSE, NSE, RBI, Companies Act), CIN and SEBI
registration numbers, page numbers, offer/filing dates, amounts, order/ticket-style numbers. Change per type in
`config/pii_types.yaml`.

## Adding a PII type

```yaml
- name: PASSPORT
  regex: ['\b[A-Z][0-9]{7}\b']
  ner_labels: ["passport number"]
  llm_hint: "Indian passport numbers"
  context_words: ["passport"]
  faker: alnum_same_shape
  policy: redact          # redact | exempt | review
```

## Evaluation

Ground truth: 199 PII mentions hand-labelled on 14 pages (cover, general information, the scanned PAN card).
Matching: same page and type, whitespace/case-insensitive, one-to-one. Every code change is committed with its
score in `eval/RUNS.md`; a change that lowers recall is not kept.

| precision | recall | F1 | token accuracy |
|---|---|---|---|
| 0.902 | 0.930 | 0.916 | 0.977 |

Full report with per-type numbers, misses and false hits: the public link above, `EVAL_REPORT.md`, and
`deliverables/` (redacted PDF, redacted DOCX, mapping).

Trade-offs noticed: the LLM occasionally labels amounts as card numbers (now filtered by shape); OCR spelling on the
scanned card differs from the transcribed truth; a building that is also a firm name is ORG to the model and ADDRESS
to the truth — redacted either way.

## Future scope

- **Self-learning loop**: reviewed misses/false hits retune thresholds and gazetteers automatically, and fine-tune the
  GLiNER judge on a schedule, gated on held-out recall.
- **Monitoring**: per-step metrics (latency, spans, confidence, verify result) exported to Grafana; automatic
  LLM-written run summaries and alerts per stage.
- Upload API with object storage and a worker queue; Docling / VLM-OCR backends for scanned inputs; review UI.

## Layout

```
pii_redact/   parse, normalize, ocr, finders/, merge, judge, surrogates, writers/, verify, review, pipeline, cli, api
config/       pii_types.yaml (what is PII)   backends.yaml (which tools, thresholds)
eval/         ground_truth/, eval.py, run_eval.py, RUNS.md
docs/         architecture.html / .svg       DESIGN.md: full design and production path
```
