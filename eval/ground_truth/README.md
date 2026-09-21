# Ground truth: `rhp_pages.csv`

Hand-labelled PII mentions on 14 pages of `samples/rhp.pdf`:
**1, 2, 3, 4, 5, 6, 110, 111, 112, 113, 114, 115, 116, 128** (1-based, PyMuPDF page order).

Columns: `page,text,type,note`. One row per mention. The same string on the same page
appears once per occurrence (e.g. `Nuvama` twice on page 112).

## Counts (199 rows)

| type | rows |
|---|---|
| PERSON | 55 |
| ORG | 54 |
| EMAIL | 31 |
| ADDRESS | 28 |
| PHONE | 21 |
| DIN | 8 |
| PAN | 1 |
| DOB | 1 |

Rows per page: 1: 18, 2: 3, 3: 2, 4: 15, 5: 27, 6: 21, 110: 25, 111: 3, 112: 20, 113: 0 (blank page),
114: 19, 115: 6, 116: 32, 128: 8.

Page 113 is labelled and empty (only a page number). `eval.py` defaults to the pages present in
this file, so it evaluates 13 pages; to count false hits on page 113 too, pass
`--pages 1,2,3,4,5,6,110,111,112,113,114,115,116,128`. Page 128 has no text layer, so it is
excluded from token accuracy (mention-level scores still include it).

## How `text` was written

- `text` is a verbatim substring of `page.get_text()` (PyMuPDF) unless `note` says otherwise.
  A build-time check confirmed that every non-image row is a whitespace-stripped substring of its page.
- `note = linebreak`: the mention spans a line break in the extracted text. The break (and any
  trailing spaces around it) is replaced by ONE space. Example: `cs.connect@kshinternational.co m`.
  DIN is the exception: the digits are joined with no space (`0013507` + `0` -> `00135070`).
- `note = letterbreak`: page 4 renders some cells letter by letter (`L`/`ok`/`esh`). The row holds
  the readable form (`Lokesh Shah`). Match whitespace-insensitively.
- `note = image`: page 128 is a scanned PAN card. `get_text()` returns only the page number, so the
  values are transcribed from the image as printed (front: PAN, name, father's name, DOB; back:
  NSDL address, Tel, Fax, e-mail). The Hindi copy of the address is not labelled separately.
- Typos are kept verbatim (`Sarthak.malvadkar@kshinterantional.com`, page 112).

## What is labelled

- **PERSON** – every mention of a real person, including repeats and the father's name on the PAN card.
- **EMAIL** – every address, including generic mailboxes (`customercare@...`, `Ipocmg@...`).
- **PHONE** – every telephone or fax number, in the spacing printed.
- **ORG** – private companies, banks, law firms, auditors, trusts, LLPs, the registrar, and the
  issuer itself (`KSH International Limited`, its former names). Short forms used as coordinator
  labels (`Nuvama`, `I-Sec` on pages 112/114) are labelled too so surname-style propagation is measured.
- **ADDRESS** – the full postal string as one row (office addresses and directors' home addresses).
  Department names before an address (`Capital Market Division`) are excluded; `FIG-OPS Department –
  Lodha ...` is included because the building name is glued to it on the same line.
- **DIN** – the 8-digit numbers in the board table (pages 110-111).
- **PAN / DOB** – page 128 only.

## What is NOT labelled (by policy in `config/pii_types.yaml`)

- Regulators, exchanges, statutes, government bodies: SEBI, BSE Limited, NSE, RBI, RoC / Registrar of
  Companies (and its office address on page 110), Companies Act, Income Tax Department, NSDL.
- CIN, company registration number, SEBI registration numbers, filing / offer / certificate dates,
  the PAN card print date `06072020`, page numbers, section titles, currency amounts, share counts.
- Website URLs (`www.kshinternational.com`, the SEBI URL on page 116).
- Role words that are not names (`Company Secretary`, `Independent Director`).

## Borderline calls

| item | call | why |
|---|---|---|
| Issuer name `KSH International Limited` and former names | ORG (labelled, every occurrence) | DESIGN.md: "redact all ORGs"; only the allowlist is exempt |
| `Nuvama` / `I-Sec` coordinator cells (12 rows) | ORG | partial ORG mention; leaving them would leak the entity after redaction |
| Newspapers `Financial Express`, `Jansatta`, `Loksatta` (page 5) | not labelled | publications named as advertising venues, not in the enumerated ORG list |
| RoC office address, page 110 | not labelled | address of an exempt public body |
| `ICICI Venture House` (page 114, last line) | ADDRESS | address block split across pages 114/115; each page gets its own row |
| Handwritten signature `Vishal Singh` on the PAN card | not labelled | not machine-readable text; the printed name is labelled |
| `HDFC Bank Limited` twice on page 116 | ORG x2 | second one starts the address line; labelled as ORG, not part of ADDRESS |
| `Registration number: 141032` | not labelled | company registration number, same class as CIN |
