# Eval runs (labelled pages of samples/rhp.pdf)

Per-type columns are F1. Full report per run in `out/<doc_id>/EVAL_REPORT.md`; latest copied to `eval/LATEST_REPORT.md`.

| when | commit | note | micro P | micro R | micro F1 | token acc | PERSON | ORG | EMAIL | PHONE | ADDRESS | DIN | PAN | DOB | secs |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-09-21 13:40 | 4e7b1c2 | first end-to-end run: regex + GLiNER + LLM(hard pages) + propagate, no filters | 0.463 | 0.814 | 0.590 | 0.873 | 0.917 | 0.375 | 0.952 | 0.909 | 0.343 | 0.222 | 0.667 | 0.667 | 115.8 |
| 2026-09-21 13:55 | (uncommitted) | GLiNER lock; ORG generic-role filter; PERSON/ORG need a capital; DIN whitespace + page-scope context; PIN-anchored address finder; merge: structured type must fit text | 0.831 | 0.814 | 0.822 | 0.962 | 0.863 | 0.729 | 0.952 | 0.784 | 0.808 | 0.933 | 0.667 | 0.000 | 130.2 |
| 2026-09-21 13:47 | cbee65c | address trim in merge; propagate junk filter; acronym rule; PERSON generic words; allowlist whitespace | 0.896 | 0.905 | 0.900 | 0.9710 | 0.916 | 0.877 | 0.952 | 0.952 | 0.830 | 0.933 | 0.667 | 0.667 | 198.7 |
| 2026-09-21 13:53 | f2299bb | merge trims at validated identifiers (address no longer swallowed by DIN); propagate matches spaced/glued multi-token names | 0.894 | 0.930 | 0.911 | 0.9767 | 0.945 | 0.887 | 0.952 | 0.930 | 0.852 | 0.933 | 0.667 | 0.667 | 199.4 |
| 2026-09-21 13:57 | f2299bb | merge trims at validated identifiers (address no longer swallowed by DIN); propagate matches spaced/glued multi-token names | 0.902 | 0.930 | 0.916 | 0.9768 | 0.945 | 0.903 | 0.952 | 0.930 | 0.852 | 0.933 | 0.667 | 0.667 | 205.7 |
| 2026-09-21 15:06 | f877419 | judge: structured shape gate (regex+validator on span text, any finder), min_chars 4 for PERSON/ORG/ADDRESS, single-token ORG from one finder needs corporate context; DIN context_scope doc (prev page); slash-joined names split at Word level; verify needle filter | 0.880 | 0.884 | 0.882 | 0.9401 | 0.964 | 0.769 | 0.952 | 0.952 | 0.772 | 1.000 | 0.667 | 1.000 | 108.4 |
| 2026-09-21 15:15 | 5e5545f | same code as 15:06 row + ORG single_token_needs_context knob (default on); reproducibility rerun | 0.880 | 0.884 | 0.882 | 0.9392 | 0.964 | 0.769 | 0.952 | 0.952 | 0.772 | 1.000 | 0.667 | 1.000 | 103.7 |
