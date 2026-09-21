import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))
import eval as ev  # noqa: E402

TRUTH = [
    (1, "Kushal Hegde", "PERSON"),
    (1, "cs@x.com", "EMAIL"),
    (1, "Acme Private Limited", "ORG"),
    (2, "Rohit Hegde", "PERSON"),
    (2, "+91 22 1234 5678", "PHONE"),
    (3, "Someone Missed", "PERSON"),
]
PRED = [
    (1, "KUSHAL HEGDE", "PERSON"),        # TP: case-insensitive equality
    (1, "cs@x.com", "EMAIL"),             # TP
    (1, "Acme", "ORG"),                   # TP: pred contained in truth
    (1, "SEBI", "ORG"),                   # FP
    (2, "Hegde", "PERSON"),               # FP: truth already taken by the longer match below
    (2, "Rohit Hegde", "PERSON"),         # TP: longest wins
    (2, "+912212345678", "PHONE"),        # TP: whitespace-insensitive
    (4, "Off Page", "PERSON"),            # ignored: page 4 not in truth
]


def _write(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["page", "text", "type"])
        w.writerows(rows)


def test_counts_and_report(tmp_path):
    p, t, out = tmp_path / "pred.csv", tmp_path / "truth.csv", tmp_path / "EVAL_REPORT.md"
    _write(p, PRED)
    _write(t, TRUTH)
    assert ev.main(["--pred", str(p), "--truth", str(t), "--out", str(out), "--pdf", ""]) == 0
    res = ev.evaluate(ev.read_rows(str(p)), ev.read_rows(str(t)), [1, 2, 3], None)
    tp, fp, fn, prec, rec, f1 = res["micro"]
    assert (tp, fp, fn) == (5, 2, 1)
    assert abs(prec - 5 / 7) < 1e-9 and abs(rec - 5 / 6) < 1e-9
    assert res["per_type"]["PERSON"][:3] == (2, 1, 1)
    assert res["per_type"]["ORG"][:3] == (1, 1, 0)
    assert [r["text"] for r in res["misses"]] == ["Someone Missed"]
    assert sorted(r["text"] for r in res["false_hits"]) == ["Hegde", "SEBI"]
    report = out.read_text()
    assert "| PERSON | 2 | 1 | 1 |" in report
    assert "| 3 | Someone Missed | PERSON |  |" in report
    assert "| 1 | SEBI | ORG |  |" in report


def test_pages_filter(tmp_path):
    res = ev.evaluate([dict(page=a, text=b, type=c) for a, b, c in PRED],
                      [dict(page=a, text=b, type=c) for a, b, c in TRUTH], [1], None)
    assert res["micro"][:3] == (3, 1, 0)


def test_token_accuracy():
    text = "Contact Kushal Hegde at cs@x.com from Acme Private Limited and SEBI or www.acme.com"
    truth = [dict(page=1, text=b, type=c) for a, b, c in TRUTH if a == 1]
    pred = [dict(page=1, text=b, type=c) for a, b, c in PRED if a == 1]
    correct, total, skipped = ev.token_accuracy({1: text, 5: "12"}, truth, pred)
    # 13 tokens; wrong: Private, Limited (truth only) and SEBI (pred only); 'www.acme.com' is not 'Acme'
    assert (correct, total, skipped) == (10, 13, [5])
