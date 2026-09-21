"""Score pipeline spans against hand-labelled ground truth.

    python eval/eval.py --pred out/<doc>/spans.csv --truth eval/ground_truth/rhp_pages.csv --out EVAL_REPORT.md
        [--pages 1,2,5] [--pdf samples/rhp.pdf]

Matching (CONTRACTS.md): same page, same type, whitespace/case-insensitive equality or
containment either way. One-to-one, greedy by longest match.
Token accuracy: whitespace-split tokens of each labelled page (from --pdf); a token is correct
when "covered by truth" == "covered by a prediction".
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").casefold()


def read_rows(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["page"] = int(r["page"])
        r["type"] = (r.get("type") or "").strip().upper()
        r["text"] = r.get("text") or ""
    return rows


def match(pred: list[dict], truth: list[dict], fuzzy: float = 0.0) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Return (pairs of (truth_idx, pred_idx), unmatched truth idxs, unmatched pred idxs).
    fuzzy > 0 also accepts pairs whose normalised texts have difflib similarity >= fuzzy."""
    from difflib import SequenceMatcher
    cands = []
    by_key = defaultdict(list)
    for j, p in enumerate(pred):
        by_key[(p["page"], p["type"])].append(j)
    for i, t in enumerate(truth):
        nt = norm(t["text"])
        for j in by_key.get((t["page"], t["type"]), []):
            np_ = norm(pred[j]["text"])
            if nt and np_ and (nt == np_ or nt in np_ or np_ in nt):
                cands.append((min(len(nt), len(np_)), nt == np_, i, j))
            elif fuzzy and nt and np_ and SequenceMatcher(None, nt, np_).ratio() >= fuzzy:
                cands.append((min(len(nt), len(np_)), False, i, j))
    cands.sort(key=lambda c: (-c[0], not c[1], c[2], c[3]))
    used_t, used_p, pairs = set(), set(), []
    for _, _, i, j in cands:
        if i in used_t or j in used_p:
            continue
        used_t.add(i); used_p.add(j); pairs.append((i, j))
    fn = [i for i in range(len(truth)) if i not in used_t]
    fp = [j for j in range(len(pred)) if j not in used_p]
    return pairs, fn, fp


def _coverage(tokens: list[str], texts: list[str]) -> list[bool]:
    """Mark tokens covered by the given mention texts (whitespace-insensitive search).
    A match must start/end at a token edge, allowing only punctuation on the outside
    (so 'nuvama' inside 'www.nuvama.com' does not count). Each text marks as many
    non-overlapping occurrences as it has rows."""
    joined, tok_of = "", []
    for k, tok in enumerate(tokens):
        n = norm(tok)
        joined += n
        tok_of += [k] * len(n)
    covered = [False] * len(tokens)
    taken = [False] * len(joined)
    counts = defaultdict(int)
    for t in texts:
        counts[norm(t)] += 1
    for nt, want in sorted(counts.items(), key=lambda kv: -len(kv[0])):
        if not nt:
            continue
        got = 0
        for strict in (True, False):   # strict: only punctuation outside the match inside the edge tokens
            start = 0                  # relaxed: the neighbouring char is punctuation ('Rastogi/Abhijit')
            while got < want:
                pos = joined.find(nt, start)
                if pos < 0:
                    break
                end = pos + len(nt)
                start = pos + 1
                if any(taken[pos:end]):
                    continue
                head, tail = _prefix(joined, tok_of, pos), _suffix(joined, tok_of, end)
                if strict and re.search(r"[0-9a-z]", head + " " + tail):
                    continue
                if not strict and ((head and head[-1].isalnum()) or (tail and tail[0].isalnum())):
                    continue
                for q in range(pos, end):
                    taken[q] = True
                for k in range(tok_of[pos], tok_of[end - 1] + 1):
                    covered[k] = True
                got += 1
    return covered


def _prefix(joined: str, tok_of: list[int], pos: int) -> str:
    k = tok_of[pos]
    s = pos
    while s > 0 and tok_of[s - 1] == k:
        s -= 1
    return joined[s:pos]


def _suffix(joined: str, tok_of: list[int], end: int) -> str:
    k = tok_of[end - 1]
    e = end
    while e < len(joined) and tok_of[e] == k:
        e += 1
    return joined[end:e]


def token_accuracy(page_texts: dict[int, str], truth: list[dict], pred: list[dict]) -> tuple[int, int, list[int]]:
    """Return (correct, total, pages_skipped). Pages with < 5 tokens (blank or image-only,
    where get_text() yields just the page number) are skipped."""
    correct = total = 0
    skipped = []
    for page, text in sorted(page_texts.items()):
        tokens = text.split()
        if len(tokens) < 5:
            skipped.append(page)
            continue
        tc = _coverage(tokens, [r["text"] for r in truth if r["page"] == page])
        pc = _coverage(tokens, [r["text"] for r in pred if r["page"] == page])
        correct += sum(a == b for a, b in zip(tc, pc))
        total += len(tokens)
    return correct, total, skipped


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def evaluate(pred: list[dict], truth: list[dict], pages: list[int], page_texts: dict[int, str] | None) -> dict:
    pred = [r for r in pred if r["page"] in pages]
    truth = [r for r in truth if r["page"] in pages]
    pairs, fn, fp = match(pred, truth)
    types = sorted({r["type"] for r in truth} | {r["type"] for r in pred})
    per_type = {}
    for ty in types:
        tp_ = sum(1 for i, _ in pairs if truth[i]["type"] == ty)
        fp_ = sum(1 for j in fp if pred[j]["type"] == ty)
        fn_ = sum(1 for i in fn if truth[i]["type"] == ty)
        per_type[ty] = (tp_, fp_, fn_, *prf(tp_, fp_, fn_))
    tp, fpn, fnn = len(pairs), len(fp), len(fn)
    # Detection view: was the value caught at all? Type is ignored and OCR spelling differences are
    # tolerated (similarity >= 0.85), so "ORG vs ADDRESS" and "nsdLco" vs "nsdl.co" do not count as errors.
    d_pairs, d_fn, d_fp = match([{**r, "type": "*"} for r in pred], [{**r, "type": "*"} for r in truth], fuzzy=0.85)
    res = {
        "pages": pages, "per_type": per_type, "micro": (tp, fpn, fnn, *prf(tp, fpn, fnn)),
        "detection": (len(d_pairs), len(d_fp), len(d_fn), *prf(len(d_pairs), len(d_fp), len(d_fn))),
        "misses": [truth[i] for i in fn], "false_hits": [pred[j] for j in fp], "token": None,
    }
    if page_texts is not None:
        res["token"] = token_accuracy({p: page_texts.get(p, "") for p in pages}, truth, pred)
    return res


def write_report(res: dict, out: str, pred_path: str, truth_path: str) -> None:
    L = ["# PII eval report", "", f"pred: `{pred_path}`  ", f"truth: `{truth_path}`  ",
         f"pages: {', '.join(map(str, res['pages']))}", "",
         "## Per type", "", "| type | TP | FP | FN | precision | recall | F1 |", "|---|---|---|---|---|---|---|"]
    for ty, (tp, fp, fn, p, r, f) in res["per_type"].items():
        L.append(f"| {ty} | {tp} | {fp} | {fn} | {p:.3f} | {r:.3f} | {f:.3f} |")
    tp, fp, fn, p, r, f = res["micro"]
    L.append(f"| **micro** | {tp} | {fp} | {fn} | {p:.3f} | {r:.3f} | {f:.3f} |")
    dtp, dfp, dfn, dp, dr, df = res["detection"]
    L += ["", f"Detection (any type, OCR-tolerant): TP={dtp} FP={dfp} FN={dfn} → **precision {dp:.3f} · recall {dr:.3f} · F1 {df:.3f}**  ",
          "(strict table above also requires the same type and exact/contained text)"]
    L.append("")
    if res["token"]:
        c, n, skipped = res["token"]
        acc = c / n if n else 0.0
        L.append(f"Token accuracy: **{acc:.4f}** ({c}/{n} tokens)" + (f"; pages without extractable text skipped: {skipped}" if skipped else ""))
    else:
        L.append(f"Token accuracy: n/a (source PDF not found: `{res.get('pdf') or '--pdf not given'}`)")
    L += ["", "## Misses (FN)", "", "| page | text | type | reason |", "|---|---|---|---|"]
    L += [f"| {r['page']} | {_cell(r['text'])} | {r['type']} |  |" for r in res["misses"]] or ["| | (none) | | |"]
    L += ["", "## False hits (FP)", "", "| page | text | type | reason |", "|---|---|---|---|"]
    L += [f"| {r['page']} | {_cell(r['text'])} | {r['type']} |  |" for r in res["false_hits"]] or ["| | (none) | | |"]
    Path(out).write_text("\n".join(L) + "\n", encoding="utf-8")


def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def load_page_texts(pdf: str, pages: list[int]) -> dict[int, str]:
    import pymupdf
    doc = pymupdf.open(pdf)
    return {p: doc[p - 1].get_text() for p in pages if 1 <= p <= len(doc)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pred", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--out", default="EVAL_REPORT.md")
    ap.add_argument("--pages", help="comma-separated 1-based pages (default: pages in the truth file)")
    ap.add_argument("--pdf", default="samples/rhp.pdf", help="source PDF for token accuracy ('' to skip)")
    a = ap.parse_args(argv)
    pred, truth = read_rows(a.pred), read_rows(a.truth)
    pages = sorted({int(x) for x in a.pages.split(",")} if a.pages else {r["page"] for r in truth})
    page_texts = load_page_texts(a.pdf, pages) if a.pdf and Path(a.pdf).exists() else None
    res = evaluate(pred, truth, pages, page_texts)
    res["pdf"] = a.pdf
    write_report(res, a.out, a.pred, a.truth)
    tp, fp, fn, p, r, f = res["micro"]
    print(f"pages={len(pages)} TP={tp} FP={fp} FN={fn} P={p:.3f} R={r:.3f} F1={f:.3f} -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
