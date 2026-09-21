"""Minimal HTTP API over the same pipeline.

    uvicorn pii_redact.api:app --port 8000
    curl -F file=@samples/rhp.pdf 'localhost:8000/redact?llm=false&review=false'   -> {"job_id": ...}
    curl localhost:8000/jobs/<id>                                                  -> status + summary
    curl -O localhost:8000/jobs/<id>/download                                      -> redacted file (same format)

Jobs run in a background thread; state is in memory (one process). A queue + object store is the production path.
"""
from __future__ import annotations

import shutil
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .pipeline import run

app = FastAPI(title="pii-redact")
JOBS: dict[str, dict] = {}
WORK = Path("out/api")


def _work(job_id: str, src: Path, llm: bool, review: bool):
    try:
        summary = run(str(src), str(WORK / job_id), use_llm=llm, use_review=review)
        JOBS[job_id]["summary"] = summary
        JOBS[job_id]["status"] = "done" if summary["verify"]["ok"] else "verify_failed"
    except Exception as e:                       # surfaced to the client; never crashes the server
        JOBS[job_id].update(status="failed", error=str(e)[:500])


@app.post("/redact")
async def redact(file: UploadFile, llm: bool = True, review: bool = False):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".docx"):
        raise HTTPException(400, "upload a .pdf or .docx")
    job_id = uuid.uuid4().hex[:12]
    dst = WORK / job_id
    dst.mkdir(parents=True, exist_ok=True)
    src = dst / f"input{suffix}"
    with open(src, "wb") as f:
        shutil.copyfileobj(file.file, f)
    JOBS[job_id] = {"status": "running", "file": file.filename}
    threading.Thread(target=_work, args=(job_id, src, llm, review), daemon=True).start()
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
def job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "no such job")
    return JOBS[job_id]


@app.get("/jobs/{job_id}/download")
def download(job_id: str):
    j = JOBS.get(job_id)
    if not j or j.get("status") != "done":
        raise HTTPException(409, "job not finished")
    return FileResponse(j["summary"]["output"], filename=Path(j["summary"]["output"]).name)


@app.get("/jobs/{job_id}/mapping")
def mapping(job_id: str):
    j = JOBS.get(job_id)
    if not j or j.get("status") != "done":
        raise HTTPException(409, "job not finished")
    return FileResponse(Path(j["summary"]["output"]).parent / "mapping.csv", filename="mapping.csv")
