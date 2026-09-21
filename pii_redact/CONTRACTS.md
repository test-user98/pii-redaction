# Module contracts (all agents code against these; do not change model.py without saying so)

Shared types: `pii_redact/model.py` (Word, Image, PageText, Span, Page, Entity, Doc).
Config: `pii_redact/config.py` → `pii_types()` (list of type dicts from config/pii_types.yaml), `backends()` (dict from config/backends.yaml).
Audit: `pii_redact/audit.py` → `Audit(out_dir, run_id, doc_id).log(stage, page, backend, confidence=, evidence=, latency_ms=, cost_usd=, **extra)`.
Python 3.12 venv at `.venv` (activate with `source .venv/bin/activate`). Samples: `samples/rhp.pdf`, `samples/rhp.docx`.
Pages are 1-based everywhere (`Page.page_no`, `Word.page`, `Span.page`).

## parse.py
- `parse_document(path: str, cfg: dict) -> Doc`
  - PDF: PyMuPDF. `Word.loc = {"bbox": (x0,y0,x1,y1)}`, `block`, `line` from `page.get_text("words")`. `Page.images` with bbox, xref, and `png` (rendered crop, 300 DPI). `Page.signals` = {text_density, single_letter_ratio, image_area_ratio}; `Page.hard` per `cfg["routing"]`.
  - DOCX: python-docx. Traverse in document order: body paragraphs and tables (nested), then section headers/footers. `Word.loc = {"para": <index in traversal>, "run": <run idx>, "offset": <char offset in run>}`. One `Page` per 50 paragraphs (page_no = chunk index + 1). Inline images → `Page.images` with `ref` (relationship id) and `png`.
  - `iter_docx_paragraphs(document) -> list[Paragraph]` must be the single traversal used by both parser and writer (same index → same paragraph).
- `Doc.doc_id = sha256(file bytes)[:16]`, `Doc.fmt` = "pdf" | "docx".

## ocr.py
- `ocr_images(page: Page, cfg: dict) -> list[Word]` — RapidOCR on each `Image.png`; returns Words with `source="ocr"`, ids continuing after the page's last word id, `loc={"bbox": <page coords>}` for PDF (map crop px → page pt) or `loc={"image_ref": ref, "bbox": <px in image>}` for DOCX. Caller appends them to `page.words`.

## normalize.py
- `build_views(page: Page) -> dict[str, PageText]` → keys "raw" and "layout". Every non-whitespace char maps to a Word.id in `char_word`; inserted whitespace/newlines map to -1.
  - raw: words in id order joined by single spaces, newline between blocks.
  - layout: per block → per line join; collapse runs of single-char words that are x-aligned into one token; rejoin `word-` + newline + `word`; join lines inside a block with a space; blocks separated by newline. OCR words form their own block(s).
  - Keep `page.views` set by caller.

## finders/*.py  (each exposes `find(page: Page, types: list[dict], cfg: dict) -> list[Span]`)
- Spans reference a view: `Span.view` in {"raw","layout"}, `start/end` are char offsets in that view's text, `word_ids = page.views[view].word_ids(start, end)`.
- `regex_finder.py`: patterns from each type's `regex`; whitespace-tolerant for identifier types (PAN, AADHAAR, CREDIT_CARD, PHONE — match then strip whitespace before validating); `validator` from `finders/validators.py` (`luhn`, `verhoeff`, `pan`, `phone`, `ssn`, `ipv4`); `requires_context` → a `context_words` hit within 60 chars, else skip. confidence 1.0 if validator passed, 0.8 otherwise.
- `gliner_finder.py`: GLiNER2 `fastino/gliner2-privacy-filter-PII-multi` (`from gliner2 import GLiNER2`; `m.extract_entities(text, labels, threshold, include_confidence=True, include_spans=True)` → `{"entities": {label: [{"text","confidence","start","end"}]}}`). Labels = union of `ner_labels`; map label back to type name. Load model once (module-level cache). Run on "layout" view only, chunk at ~1500 chars on sentence/newline boundaries with 200-char overlap, offsets shifted back.
- `llm_finder.py`: providers `ollama` (POST {base_url}/api/chat, `format: "json"`) and `anthropic` (anthropic SDK, `claude-haiku-4-5`, structured JSON). Prompt lists types with `llm_hint`. **The model returns verbatim substrings + type only; we locate each by exact then whitespace-insensitive search in the view text.** Unlocatable → audit `llm_unlocated`. Runs on "layout" view. Chunk per `cfg["llm"]`. Only called for `page.hard` pages plus the sampled easy pages (caller decides; finder just runs).
- `propagate.py`: `find(doc: Doc, confirmed: list[Span], types, cfg) -> list[Span]` — build variant strings per confirmed PERSON/ORG/EMAIL/PHONE span (exact, case-insensitive, name minus honorific, surname alone, initials form) and search every page's views. Whole-word matches only. Common-word gating (`judge.common_word_names_gated`): if a single-token variant is a dictionary word (use a small bundled list + `str.istitle()` heuristics), require Title-case AND (preceding honorific OR adjacent known name token OR same table column). confidence 0.9 for multi-token, 0.6 for gated single-token.

## merge.py
- `merge(page: Page) -> list[Span]` — take spans from all finders/views, map to word_ids, dedupe; overlapping word sets → keep the longer span, but carry all finders/confidences in `Span.finder` as "regex+gliner" and confidence = max. Deterministic order by first word id.

## judge.py
- `judge(page: Page, types, cfg) -> tuple[list[Span], list[Span]]` → (kept, review). Rules: validator-passed regex type wins; else GLiNER type; else LLM type. ORG `allowlist` substring match → span dropped as exempt (audit it). Single-finder span with confidence < `drop_single_finder_below` → dropped; between drop and `review_single_finder_below` → review list.

## surrogates.py
- `cluster_entities(doc: Doc) -> list[Entity]` — group kept spans across pages: same type + normalized text (casefold, collapse spaces, strip honorifics/punct); PERSON also links partial mentions (surname alone, initials) to the full-name entity when unambiguous.
- `assign_surrogates(entities, cfg) -> None` — deterministic: `seed = int(hmac_sha256(salt, type + "|" + canonical)[:16], 16)`; `Faker` seeded per entity. PERSON: token-level map (each real name token → fake token via its own HMAC seed, so shared surnames share fakes); mention surrogate = map tokens of that mention. EMAIL: if local part matches a known person's tokens, build from their surrogate tokens `first.last@example.com`, else faker. PHONE: keep `+CC` and spacing, replace other digits. ORG: fake company + same suffix. ADDRESS: faker address, same number of lines. DOB: shift by per-entity 30–400 days. PAN/AADHAAR/CREDIT_CARD/GSTIN/IFSC: format-valid fakes (checksum-valid where applicable). Length-match names/orgs within ±20% when possible.
- `write_mapping(doc, out_dir)` → `mapping.json` and `mapping.csv` (entity_id, type, real, surrogate, mention_count, pages).
- `mention_surrogate(entity: Entity, span: Span) -> str`.

## writers/pdf_writer.py
- `write_pdf(doc: Doc, src_path, out_path, cfg)` — for each kept span: word bboxes (group by line) → `page.add_redact_annot(rect, text=surrogate_fragment, fontsize=<from span words>, fontname="helv", fill=(1,1,1), text_color=<original>)` then `page.apply_redactions()`. OCR spans inside images → `writers/image_redact.py` produces a redacted PNG (boxes over word bboxes with surrogate text) and `page.insert_image(image_bbox, stream=png)` after redacting the image rect. Scrub metadata. If `cfg["surrogates"]["legend"] != "none"` append a page with the legend table.
## writers/docx_writer.py
- `write_docx(doc: Doc, src_path, out_path, cfg)` — open source, use `iter_docx_paragraphs`, replace inside runs by (para, run, offset); span crossing runs → surrogate in first run, others emptied for the covered chars. Replace images whose OCR words were redacted. Scrub core properties. Legend table appended per config.
## writers/pdf_to_docx.py
- `pdf_to_docx(redacted_pdf_path, out_path)` — paragraphs from blocks, tables via `page.find_tables()`. Approximate layout; this is the assignment's .docx deliverable for PDF input.

## verify.py
- `verify(doc: Doc, out_path, cfg) -> dict` — extract text from the output (PyMuPDF or python-docx); search every entity's real text and variants (whitespace-insensitive); return {"leaks": [...], "ok": bool}.

## review.py (step 10b)
- `review_page(original_text, redacted_text, page_mapping: list[dict], cfg) -> dict` via Ollama JSON: {"leaks": [...], "wrong_replacements": [...], "inconsistent": [...]}. Flag-only; pipeline writes `review.jsonl`.

## eval/eval.py
- Ground truth CSV: `page,text,type` (one row per mention as it appears on that page). Prediction CSV from pipeline: `spans.csv` with `page,text,type,entity_id,finder,confidence`.
- Match: same page, same type, whitespace/case-insensitive text equality OR one contains the other (partial credit counts as TP). Report per type: TP/FP/FN, precision, recall, F1; overall micro; token accuracy; miss list and false-hit list. Write `EVAL_REPORT.md`.
