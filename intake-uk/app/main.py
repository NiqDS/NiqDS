"""FastAPI app + routes.

Three server-rendered pages: upload, bundle view, report + chase. No login, no
dashboard. The demo is: drag files in, see red, read the email that fixes it.
"""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import db
from app.ingest.extract import extract_document
from app.ingest.loader import load_file
from app.models import Bundle
from app.report.chase import build_chase
from app.report.gaps import build_gap_report
from app.rules.engine import run_bundle, sort_flags
from app.scenarios import build_bundle as build_scenario_bundle
from app.scenarios import scenario_names

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR.parent / "data" / "uploads"

app = FastAPI(title="Intake Gate (UK)")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


# #1 custom 404 — render a branded page instead of bare JSON.
@app.exception_handler(StarletteHTTPException)
async def not_found_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return templates.TemplateResponse(
            request, "404.html", {"detail": exc.detail}, status_code=404
        )
    return PlainTextResponse(str(exc.detail), status_code=exc.status_code)


# #10 robots.txt — the app is behind sign-in; keep crawlers out entirely.
@app.get("/robots.txt", response_class=PlainTextResponse)
def robots() -> str:
    return "User-agent: *\nDisallow: /\n"


SEVERITY_CLASS = {"BLOCK": "block", "WARN": "warn", "INFO": "info"}


def _compute(bundle: Bundle):
    flags = sort_flags(run_bundle(bundle))
    report = build_gap_report(bundle, flags)
    chase = build_chase(bundle, flags)
    return flags, report, chase


# --------------------------------------------------------------------------- #
# Upload
# --------------------------------------------------------------------------- #


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request,
        "upload.html",
        {"bundles": db.list_bundles(), "scenarios": scenario_names()},
    )


@app.post("/upload")
async def upload(
    request: Request,
    client_name: str = Form(...),
    declared_period_start: str = Form(...),
    declared_period_end: str = Form(...),
    expected_accounts: str = Form(""),
    files: list[UploadFile] = File(default=[]),
):
    bundle_id = "B-" + uuid.uuid4().hex[:8]
    dest = UPLOAD_DIR / bundle_id
    dest.mkdir(parents=True, exist_ok=True)

    documents = []
    for uf in files:
        if not uf.filename:
            continue
        target = dest / Path(uf.filename).name
        target.write_bytes(await uf.read())
        loaded = load_file(target)
        documents.append(extract_document(loaded))

    accounts = [a.strip() for a in expected_accounts.replace("\n", ",").split(",") if a.strip()]
    bundle = Bundle(
        bundle_id=bundle_id,
        client_name=client_name,
        declared_period_start=date.fromisoformat(declared_period_start),
        declared_period_end=date.fromisoformat(declared_period_end),
        expected_accounts=accounts,
        documents=documents,
    )
    db.save_bundle(bundle)
    return RedirectResponse(url=f"/bundle/{bundle_id}", status_code=303)


@app.post("/demo")
def load_demo(scenario: str = Form(...)):
    """Seed a demo bundle from the shipped fixtures (no upload needed)."""

    src = build_scenario_bundle(scenario)
    bundle_id = "B-" + uuid.uuid4().hex[:8]
    bundle = src.model_copy(update={"bundle_id": bundle_id})
    db.save_bundle(bundle)
    return RedirectResponse(url=f"/bundle/{bundle_id}", status_code=303)


# --------------------------------------------------------------------------- #
# Bundle view
# --------------------------------------------------------------------------- #


@app.get("/bundle/{bundle_id}", response_class=HTMLResponse)
def bundle_view(request: Request, bundle_id: str):
    bundle = db.get_bundle(bundle_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="That bundle doesn't exist.")
    _flags, report, _chase = _compute(bundle)
    doc_reports = {d.source_file: d for d in report.documents}
    return templates.TemplateResponse(
        request,
        "bundle.html",
        {
            "bundle": bundle,
            "report": report,
            "doc_reports": doc_reports,
            "severity_class": SEVERITY_CLASS,
        },
    )


@app.get("/bundle/{bundle_id}/report", response_class=HTMLResponse)
def report_view(request: Request, bundle_id: str):
    bundle = db.get_bundle(bundle_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="That bundle doesn't exist.")
    _flags, report, chase = _compute(bundle)
    return templates.TemplateResponse(
        request,
        "report.html",
        {
            "bundle": bundle,
            "report": report,
            "chase": chase,
            "severity_class": SEVERITY_CLASS,
        },
    )


@app.get("/bundle/{bundle_id}/chase", response_class=PlainTextResponse)
def chase_text(bundle_id: str):
    bundle = db.get_bundle(bundle_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="That bundle doesn't exist.")
    _flags, _report, chase = _compute(bundle)
    return PlainTextResponse(chase.text)
