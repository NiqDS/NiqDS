"""FastAPI app + routes.

Three server-rendered pages: upload, bundle view, report + chase. No login, no
dashboard. The demo is: drag files in, see red, read the email that fixes it.
"""

from __future__ import annotations

import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app import auth, config, db, mail, oauth, retention
from app.api import router as api_router
from app.ingest.extract import extract_document
from app.ingest.loader import load_file
from app.models import Bundle, ExtractedDocument
from app.report.chase import build_chase
from app.report.gaps import build_gap_report
from app.rules.engine import run_bundle, sort_flags
from app.scenarios import build_bundle as build_scenario_bundle
from app.scenarios import scenario_names
from app.single import check_single

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = config.UPLOAD_DIR
SCAN_DIR = config.SCAN_DIR
_MAX_UPLOAD_BYTES = config.MAX_UPLOAD_MB * 1024 * 1024


@asynccontextmanager
async def _lifespan(app: FastAPI):
    config.ensure_dirs()
    db.init_db()
    removed = retention.sweep()
    if removed:
        print(f"retention: removed {removed} file(s) older than {config.RETENTION_DAYS} days")
    yield


app = FastAPI(title="Intake Gate (UK)", lifespan=_lifespan)
app.add_middleware(
    SessionMiddleware, secret_key=auth.session_secret(),
    same_site="lax", https_only=config.SESSION_SECURE,
)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(api_router)


@app.middleware("http")
async def _security_and_limits(request: Request, call_next):
    # Reject oversized uploads early (declared Content-Length).
    if request.method == "POST" and request.url.path in {"/upload", "/scan", "/api/scan"}:
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > _MAX_UPLOAD_BYTES:
            detail = f"File too large (max {config.MAX_UPLOAD_MB} MB)."
            if request.url.path.startswith("/api"):
                return JSONResponse({"detail": detail}, status_code=413)
            return PlainTextResponse(detail, status_code=413)
    response = await call_next(request)
    # Baseline security headers.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if config.HSTS:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


# Error rendering: JSON under /api, a branded HTML 404 elsewhere.
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith("/api"):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
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


def _current_user(request: Request) -> dict | None:
    uid = request.session.get("uid")
    if uid is None:
        return None
    return db.get_user(int(uid))


# --------------------------------------------------------------------------- #
# Upload
# --------------------------------------------------------------------------- #


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    user = _current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "upload.html",
        {"bundles": db.list_bundles(user["id"]), "scenarios": scenario_names()},
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
    user = _current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    bundle_id = "B-" + uuid.uuid4().hex
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
    db.save_bundle(bundle, user["id"])
    return RedirectResponse(url=f"/bundle/{bundle_id}", status_code=303)


@app.post("/demo")
def load_demo(request: Request, scenario: str = Form(...)):
    """Seed a demo bundle from the shipped fixtures (no upload needed)."""

    user = _current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    src = build_scenario_bundle(scenario)
    bundle_id = "B-" + uuid.uuid4().hex
    bundle = src.model_copy(update={"bundle_id": bundle_id})
    db.save_bundle(bundle, user["id"])
    return RedirectResponse(url=f"/bundle/{bundle_id}", status_code=303)


# --------------------------------------------------------------------------- #
# Bundle view
# --------------------------------------------------------------------------- #


@app.get("/bundle/{bundle_id}", response_class=HTMLResponse)
def bundle_view(request: Request, bundle_id: str):
    user = _current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    bundle = db.get_bundle(bundle_id, user["id"])
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
    user = _current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    bundle = db.get_bundle(bundle_id, user["id"])
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
def chase_text(request: Request, bundle_id: str):
    user = _current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    bundle = db.get_bundle(bundle_id, user["id"])
    if bundle is None:
        raise HTTPException(status_code=404, detail="That bundle doesn't exist.")
    _flags, _report, chase = _compute(bundle)
    return PlainTextResponse(chase.text)


# --------------------------------------------------------------------------- #
# Scan app — log in, take/upload one photo, check it's complete & correct
# --------------------------------------------------------------------------- #

VERDICT_CLASS = {"ready": "ok", "fix": "block", "unreadable": "warn", "unknown": "warn"}
STATUS_ICON = {"ok": "✓", "invalid": "✕", "missing": "✕", "warn": "!", "optional": "–"}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get("uid"):
        return RedirectResponse(url="/app", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"mode": "login", "error": None})


@app.post("/login")
def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    uid = auth.authenticate(email, password)
    if uid is None:
        return templates.TemplateResponse(
            request, "login.html",
            {"mode": "login", "error": "Email or password not recognised.", "email": email},
            status_code=401,
        )
    request.session["uid"] = uid
    return RedirectResponse(url="/app", status_code=303)


_PROFILE_OPTS = {"business_types": auth.BUSINESS_TYPES, "mtd_statuses": auth.MTD_STATUSES}


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    if request.session.get("uid"):
        return RedirectResponse(url="/app", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"mode": "signup", "error": None, **_PROFILE_OPTS}
    )


@app.post("/signup")
def signup_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    business_type: str = Form(""),
    vat_registered: str = Form(""),
    vat_number: str = Form(""),
    mtd_status: str = Form(""),
):
    uid, error = auth.register(
        email, password,
        business_type=business_type or None,
        vat_registered=bool(vat_registered),
        vat_number=vat_number or None,
        mtd_status=mtd_status or None,
    )
    if error:
        return templates.TemplateResponse(
            request, "login.html",
            {"mode": "signup", "error": error, "email": email,
             "business_type": business_type, "vat_registered": bool(vat_registered),
             "vat_number": vat_number, "mtd_status": mtd_status, **_PROFILE_OPTS},
            status_code=400,
        )
    request.session["uid"] = uid
    return RedirectResponse(url="/app", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/app", response_class=HTMLResponse)
def scan_home(request: Request):
    user = _current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request, "scan.html", {"user": user, "recent": db.list_scans(user["id"])}
    )


@app.post("/scan")
async def scan_submit(request: Request, file: UploadFile = File(...)):
    user = _current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    if not file or not file.filename:
        return RedirectResponse(url="/app", status_code=303)

    scan_id = "S-" + uuid.uuid4().hex
    dest = SCAN_DIR / str(user["id"]) / scan_id
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / Path(file.filename).name
    target.write_bytes(await file.read())

    doc = extract_document(load_file(target))
    result = check_single(doc)
    db.save_scan(scan_id, user["id"], doc.doc_type.value, result.verdict, doc.model_dump_json())
    return RedirectResponse(url=f"/scan/{scan_id}", status_code=303)


@app.get("/scan/{scan_id}", response_class=HTMLResponse)
def scan_result(request: Request, scan_id: str):
    user = _current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    row = db.get_scan(scan_id, user["id"])
    if row is None:
        raise HTTPException(status_code=404, detail="That scan doesn't exist.")
    doc = ExtractedDocument.model_validate_json(row["data_json"])
    result = check_single(doc)
    return templates.TemplateResponse(
        request, "scan_result.html",
        {"user": user, "doc": doc, "result": result,
         "verdict_class": VERDICT_CLASS, "status_icon": STATUS_ICON},
    )


# --------------------------------------------------------------------------- #
# Send to accountant — bundle selected scans into a draft
# --------------------------------------------------------------------------- #


def _scan_items(user_id: int, scan_ids: list[str], include_bytes: bool = False):
    items = []
    for sid in scan_ids:
        row = db.get_scan(sid, user_id)
        if row is None:
            continue
        doc = ExtractedDocument.model_validate_json(row["data_json"])
        result = check_single(doc)
        file_bytes = None
        if include_bytes:
            folder = SCAN_DIR / str(user_id) / sid
            target = folder / doc.source_file
            if target.exists():
                file_bytes = target.read_bytes()
            elif folder.exists():
                found = [p for p in folder.iterdir() if p.is_file()]
                file_bytes = found[0].read_bytes() if found else None
        items.append(
            mail.DraftItem(
                scan_id=sid, label=result.doc_type_label, source_file=doc.source_file,
                verdict=result.verdict, fixes=result.fixes, file_bytes=file_bytes,
            )
        )
    return items


def _provider_status(user_id: int) -> list[dict]:
    connected = set(db.list_connections(user_id))
    out = []
    for pid, cfg in oauth.PROVIDERS.items():
        out.append({"id": pid, "label": cfg["label"],
                    "configured": oauth.is_configured(pid), "connected": pid in connected})
    return out


@app.get("/draft", response_class=HTMLResponse)
def draft_select(request: Request):
    user = _current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request, "draft_select.html",
        {"user": user, "recent": db.list_scans(user["id"], limit=50),
         "max_docs": mail.MAX_ATTACHMENTS, "accountant_email": user.get("accountant_email") or "",
         "connected": request.query_params.get("connected"),
         "err": request.query_params.get("err")},
    )


@app.post("/draft", response_class=HTMLResponse)
def draft_build(
    request: Request,
    accountant_email: str = Form(...),
    scan_ids: list[str] = Form(default=[]),
    note: str = Form(""),
):
    user = _current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    if not scan_ids:
        return RedirectResponse(url="/draft", status_code=303)
    db.set_accountant_email(user["id"], accountant_email)
    items = _scan_items(user["id"], scan_ids[: mail.MAX_ATTACHMENTS])
    draft = mail.build_draft(user["email"], accountant_email.strip(), items, extra_note=note)
    return templates.TemplateResponse(
        request, "draft_preview.html",
        {"user": user, "draft": draft, "scan_ids": [i.scan_id for i in items],
         "note": note, "accountant_email": accountant_email.strip(),
         "mailto": mail.to_mailto(draft), "providers": _provider_status(user["id"])},
    )


@app.post("/draft.eml")
def draft_eml(
    request: Request,
    accountant_email: str = Form(...),
    scan_ids: list[str] = Form(default=[]),
    note: str = Form(""),
):
    user = _current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    items = _scan_items(user["id"], scan_ids[: mail.MAX_ATTACHMENTS], include_bytes=True)
    draft = mail.build_draft(user["email"], accountant_email.strip(), items, extra_note=note)
    eml = mail.to_eml(draft, user["email"])
    return Response(
        content=eml, media_type="message/rfc822",
        headers={"Content-Disposition": 'attachment; filename="records-for-accountant.eml"'},
    )


# --------------------------------------------------------------------------- #
# Link a work mailbox (OAuth) + create the draft in it
# --------------------------------------------------------------------------- #


def _redirect_uri(request: Request, provider: str) -> str:
    base = os.environ.get("OAUTH_REDIRECT_BASE") or str(request.base_url).rstrip("/")
    return f"{base}/oauth/callback/{provider}"


def _access_token(user_id: int, provider: str) -> str | None:
    """Return a valid access token, refreshing it if it's expired/near expiry."""

    row = db.get_oauth_token(user_id, provider)
    if not row:
        return None
    if row["access_token"] and row["expires_at"] > int(time.time()) + 60:
        return row["access_token"]
    if not row["refresh_token"]:
        return None
    try:
        tok = oauth.refresh_access_token(provider, row["refresh_token"])
    except oauth.OAuthError:
        return None
    db.save_oauth_token(
        user_id, provider, refresh_token=tok.get("refresh_token"),
        access_token=tok.get("access_token"),
        expires_at=int(time.time()) + int(tok.get("expires_in", 3600)),
        account_email=row["account_email"],
    )
    return tok.get("access_token")


@app.get("/connect/{provider}")
def connect(request: Request, provider: str):
    user = _current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    if provider not in oauth.PROVIDERS or not oauth.is_configured(provider):
        return RedirectResponse(url="/draft?err=notconfigured", status_code=303)
    state = oauth.new_state()
    verifier, challenge = oauth.new_pkce()
    request.session["oauth"] = {"provider": provider, "state": state, "verifier": verifier}
    url = oauth.authorization_url(provider, _redirect_uri(request, provider), state, challenge)
    return RedirectResponse(url=url, status_code=303)


@app.get("/oauth/callback/{provider}")
def oauth_callback(request: Request, provider: str, code: str = "", state: str = "", error: str = ""):
    user = _current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    sess = request.session.get("oauth") or {}
    request.session.pop("oauth", None)
    if error or not code or sess.get("provider") != provider or sess.get("state") != state:
        return RedirectResponse(url="/draft?err=oauth", status_code=303)
    try:
        tok = oauth.exchange_code(provider, code, _redirect_uri(request, provider), sess["verifier"])
    except oauth.OAuthError:
        return RedirectResponse(url="/draft?err=oauth", status_code=303)
    db.save_oauth_token(
        user["id"], provider, refresh_token=tok.get("refresh_token"),
        access_token=tok.get("access_token"),
        expires_at=int(time.time()) + int(tok.get("expires_in", 3600)), account_email=None,
    )
    return RedirectResponse(url=f"/draft?connected={provider}", status_code=303)


@app.get("/disconnect/{provider}")
def disconnect(request: Request, provider: str):
    user = _current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    db.delete_oauth_token(user["id"], provider)
    return RedirectResponse(url="/draft", status_code=303)


@app.post("/draft/remote", response_class=HTMLResponse)
def draft_remote(
    request: Request,
    provider: str = Form(...),
    accountant_email: str = Form(...),
    scan_ids: list[str] = Form(default=[]),
    note: str = Form(""),
):
    user = _current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    token = _access_token(user["id"], provider)
    if token is None:
        return RedirectResponse(url="/draft?err=link", status_code=303)
    items = _scan_items(user["id"], scan_ids[: mail.MAX_ATTACHMENTS], include_bytes=True)
    draft = mail.build_draft(user["email"], accountant_email.strip(), items, extra_note=note)
    try:
        link = mail.create_remote_draft(draft, user["email"], provider, token)
    except Exception:
        return RedirectResponse(url="/draft?err=send", status_code=303)
    return templates.TemplateResponse(
        request, "draft_sent.html",
        {"user": user, "provider_label": oauth.provider_label(provider), "link": link,
         "count": len(items)},
    )
