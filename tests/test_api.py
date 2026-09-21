import time

import pymupdf
from fastapi.testclient import TestClient

from pii_redact.api import app


def test_api_roundtrip(tmp_path):
    pdf = tmp_path / "a.pdf"
    d = pymupdf.open(); p = d.new_page()
    p.insert_text((40, 72), "Contact: Sarthak Malvadkar, tel +91 20 4505 3237, cs@kshinternational.com"); d.save(pdf)
    c = TestClient(app)
    assert c.post("/redact?llm=false", files={"file": ("x.txt", b"hi")}).status_code == 400
    job = c.post("/redact?llm=false&review=false", files={"file": ("a.pdf", pdf.read_bytes())}).json()["job_id"]
    for _ in range(400):   # GLiNER load + page pass; slow on a busy CPU
        s = c.get(f"/jobs/{job}").json()
        if s["status"] not in ("queued", "running"):
            break
        time.sleep(1)
    assert s["status"] == "done", s
    out = c.get(f"/jobs/{job}/download")
    assert out.status_code == 200 and b"Malvadkar" not in pymupdf.open(stream=out.content)[0].get_text().encode()
    assert c.get(f"/jobs/{job}/mapping").status_code == 200
    assert c.get("/jobs/nope").status_code == 404
