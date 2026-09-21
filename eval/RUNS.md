# Eval runs (labelled pages of samples/rhp.pdf)

Per-type columns are F1. Full report per run in `out/<doc_id>/EVAL_REPORT.md`; latest copied to `eval/LATEST_REPORT.md`.

| when | commit | note | micro P | micro R | micro F1 | token acc | PERSON | ORG | EMAIL | PHONE | ADDRESS | DIN | PAN | DOB | secs |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-09-21 13:40 | 4e7b1c2 | first end-to-end run: regex + GLiNER + LLM(hard pages) + propagate, no filters | 0.463 | 0.814 | 0.590 | 0.873 | 0.917 | 0.375 | 0.952 | 0.909 | 0.343 | 0.222 | 0.667 | 0.667 | 115.8 |
| 2026-09-21 13:55 | (uncommitted) | GLiNER lock; ORG generic-role filter; PERSON/ORG need a capital; DIN whitespace + page-scope context; PIN-anchored address finder; merge: structured type must fit text | 0.831 | 0.814 | 0.822 | 0.962 | 0.863 | 0.729 | 0.952 | 0.784 | 0.808 | 0.933 | 0.667 | 0.000 | 130.2 |
| 2026-09-21 13:47 | cbee65c | address trim in merge; propagate junk filter; acronym rule; PERSON generic words; allowlist whitespace | 0.896 | 0.905 | 0.900 | 0.9710 | 0.916 | 0.877 | 0.952 | 0.952 | 0.830 | 0.933 | 0.667 | 0.667 | 198.7 |
