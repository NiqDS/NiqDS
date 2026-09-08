"""JSON API for native clients (the iOS app, or a future fully-native client).

Same engine, same doctrine — the model extracts, deterministic code decides — but
returned as typed JSON instead of server-rendered HTML. Endpoints:

    POST /api/login        {email, password} -> {token, email}
    POST /api/scan         multipart file    -> ScanResult
    GET  /api/scans                          -> [ScanSummary]
    GET  /api/scan/{id}                       -> ScanResult
    GET  /api/health                          -> {status}

Auth: a bearer token (issued by /api/login, signed & time-limited, stateless) or
the browser session cookie — so the same endpoints serve a native app and the
web app. A scan created here is stored like any other, so it shows up in the web
history and can be bundled into an accountant draft.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel

from app import auth, db
from app.ingest.extract import extract_document
from app.ingest.loader import load_file
from app.models import ExtractedDocument
from app.single import SingleResult, check_single

router = APIRouter(prefix="/api", tags=["api"])
SCAN_DIR = Path(__file__).resolve().parents[1] / "data" / "scans"
TOKEN_MAX_AGE = 30 * 24 * 3600  # 30 days

_serializer: URLSafeTimedSerializer | None = None


def _tokens() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        _serializer = URLSafeTimedSerializer(auth.session_secret(), salt="intake-api-v1")
    return _serializer


def issue_token(user_id: int) -> str:
    return _tokens().dumps({"uid": user_id})


def current_user(request: Request) -> dict | None:
    """Resolve the user from a bearer token, falling back to the session cookie."""

    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        try:
            data = _tokens().loads(header[7:].strip(), max_age=TOKEN_MAX_AGE)
            return db.get_user(int(data["uid"]))
        except (BadSignature, SignatureExpired, KeyError, ValueError, TypeError):
            return None
    uid = request.session.get("uid") if "session" in request.scope else None
    return db.get_user(int(uid)) if uid else None


def _require(request: Request) -> dict:
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


# --- response models -------------------------------------------------------


class LoginIn(BaseModel):
    email: str
    password: str


class LoginOut(BaseModel):
    token: str
    email: str


class FieldOut(BaseModel):
    key: str
    label: str
    status: str  # ok | missing | invalid | warn | optional
    value: str | None = None
    note: str | None = None


class FlagOut(BaseModel):
    rule_id: str
    severity: str
    field: str | None = None


class ScanResult(BaseModel):
    scan_id: str | None = None
    source_file: str
    doc_type: str
    doc_type_label: str
    confidence: float
    verdict: str  # ready | fix | unreadable | unknown
    headline: str
    subhead: str
    fields: list[FieldOut] = []
    fixes: list[str] = []
    flags: list[FlagOut] = []


class ScanSummary(BaseModel):
    scan_id: str
    doc_type: str
    verdict: str
    created_at: str


def _to_result(result: SingleResult, scan_id: str | None = None) -> ScanResult:
    return ScanResult(
        scan_id=scan_id,
        source_file=result.source_file,
        doc_type=result.doc_type.value,
        doc_type_label=result.doc_type_label,
        confidence=result.confidence,
        verdict=result.verdict,
        headline=result.headline,
        subhead=result.subhead,
        fields=[FieldOut(key=f.key, label=f.label, status=f.status, value=f.value, note=f.note)
                for f in result.fields],
        fixes=result.fixes,
        flags=[FlagOut(rule_id=f.rule_id, severity=f.severity, field=f.field) for f in result.flags],
    )


# --- endpoints -------------------------------------------------------------


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/login", response_model=LoginOut)
def api_login(body: LoginIn) -> LoginOut:
    user_id = auth.authenticate(body.email, body.password)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Email or password not recognised.")
    user = db.get_user(user_id)
    return LoginOut(token=issue_token(user_id), email=user["email"])


@router.post("/scan", response_model=ScanResult)
async def api_scan(request: Request, file: UploadFile = File(...)) -> ScanResult:
    user = _require(request)
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")
    scan_id = "S-" + uuid.uuid4().hex[:8]
    dest = SCAN_DIR / str(user["id"]) / scan_id
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / Path(file.filename).name
    target.write_bytes(await file.read())

    doc = extract_document(load_file(target))
    result = check_single(doc)
    db.save_scan(scan_id, user["id"], doc.doc_type.value, result.verdict, doc.model_dump_json())
    return _to_result(result, scan_id)


@router.get("/scans", response_model=list[ScanSummary])
def api_scans(request: Request) -> list[ScanSummary]:
    user = _require(request)
    return [ScanSummary(**row) for row in db.list_scans(user["id"], limit=50)]


@router.get("/scan/{scan_id}", response_model=ScanResult)
def api_get_scan(request: Request, scan_id: str) -> ScanResult:
    user = _require(request)
    row = db.get_scan(scan_id, user["id"])
    if row is None:
        raise HTTPException(status_code=404, detail="Scan not found.")
    doc = ExtractedDocument.model_validate_json(row["data_json"])
    return _to_result(check_single(doc), scan_id)
