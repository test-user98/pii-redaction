"""Run the pipeline on the labelled pages, score it, and append one row to eval/RUNS.md.

    python eval/run_eval.py --note "what changed"  [--no-llm] [--pages 1-6,110-116,128]

RUNS.md is the change log: commit, note, and the scores that resulted. Commit after each run.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRUTH = ROOT / "eval/ground_truth/rhp_pages.csv"
RUNS = ROOT / "eval/RUNS.md"
HEADER = ("| when | commit | note | micro P | micro R | micro F1 | token acc | PERSON | ORG | EMAIL | PHONE | ADDRESS | "
          "DIN | PAN | DOB | secs | det P | det R | det F1 |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--note", required=True)
    ap.add_argument("--pages", default="1-6,110-116,128")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--sample", default=str(ROOT / "samples/rhp.pdf"))
    a = ap.parse_args()

    cmd = [sys.executable, "-m", "pii_redact.cli", a.sample, "--pages", a.pages, "--no-review", "--out", "out"]
    if a.no_llm:
        cmd.append("--no-llm")
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    m = re.search(r'"doc_id": "(\w+)"', out.stdout)
    secs = re.search(r'"seconds": ([\d.]+)', out.stdout)
    if not m:
        print(out.stdout[-2000:], out.stderr[-2000:])
        sys.exit("pipeline failed")
    run_dir = ROOT / "out" / m.group(1)
    report = run_dir / "EVAL_REPORT.md"
    subprocess.run([sys.executable, "eval/eval.py", "--pred", str(run_dir / "spans.csv"), "--truth", str(TRUTH),
                    "--out", str(report)], cwd=ROOT, check=True, capture_output=True)
    text = report.read_text()

    def f1(t):
        r = re.search(rf"\| {t} \| \d+ \| \d+ \| \d+ \| [\d.]+ \| [\d.]+ \| ([\d.]+) \|", text)
        return r.group(1) if r else "-"

    micro = re.search(r"\| \*\*micro\*\* \| \d+ \| \d+ \| \d+ \| ([\d.]+) \| ([\d.]+) \| ([\d.]+) \|", text)
    tok = re.search(r"Token accuracy: \*\*([\d.]+)\*\*", text)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    det = re.search(r"precision ([\d.]+) · recall ([\d.]+) · F1 ([\d.]+)", text)
    row = (f"| {dt.datetime.now():%Y-%m-%d %H:%M} | {commit} | {a.note}{' (no LLM)' if a.no_llm else ''} | {micro.group(1)} | "
           f"{micro.group(2)} | {micro.group(3)} | {tok.group(1) if tok else '-'} | {f1('PERSON')} | {f1('ORG')} | {f1('EMAIL')} | "
           f"{f1('PHONE')} | {f1('ADDRESS')} | {f1('DIN')} | {f1('PAN')} | {f1('DOB')} | {secs.group(1) if secs else '-'} | "
           f"{det.group(1) if det else '-'} | {det.group(2) if det else '-'} | {det.group(3) if det else '-'} |\n")
    if not RUNS.exists():
        RUNS.write_text("# Eval runs (labelled pages of samples/rhp.pdf)\n\nPer-type columns are F1. Full report per run in `out/<doc_id>/EVAL_REPORT.md`.\n\n" + HEADER)
    RUNS.write_text(RUNS.read_text() + row)
    # keep the latest full report next to the log for review
    (ROOT / "eval/LATEST_REPORT.md").write_text(text)
    print(row)


if __name__ == "__main__":
    main()
