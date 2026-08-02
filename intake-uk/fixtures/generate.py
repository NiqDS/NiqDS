"""Generate the synthetic document fixtures as PDFs.

Reproducible: run ``python fixtures/generate.py`` to (re)create the 12 files in
``fixtures/documents/``. The content is derived from the hand-written extracted
JSON in ``fixtures/extracted/`` so the rendered PDFs and the ground-truth
records stay in sync. No real client data is used — every value here is
invented.

Fixture 5 is deliberately degraded (rotate + blur + noise) to trigger the
legibility rule; it is rendered as an image and embedded in a PDF.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

FIX = Path(__file__).resolve().parent
EXTRACTED = FIX / "extracted"
DOCS = FIX / "documents"


def _money(m):
    if not m:
        return ""
    sym = {"GBP": "£", "EUR": "€", "USD": "$"}.get(m.get("currency", "GBP"), "")
    return f"{sym}{m['amount']}"


def _lines_for(rec: dict) -> list[str]:
    dt = rec["doc_type"]
    out: list[str] = []
    if dt == "BANK_STATEMENT":
        out.append("Barclays Bank plc")
        out.append("Business Current Account — Statement")
        out.append(f"Account number: {rec.get('account_identifier', '')}")
        out.append("Sort code: 20-00-00")
        out.append(f"Statement period: {rec.get('period_start')} to {rec.get('period_end')}")
        out.append("Opening balance: £1,000.00     Closing balance: £1,250.00")
        out.append("")
        out.append("Date        Description                 Amount")
        out.append("01 ...      Card payment                -45.00")
        out.append("15 ...      Bank credit                 +295.00")
        return out

    title = {
        "PURCHASE_INVOICE": "INVOICE",
        "SALES_INVOICE": "SALES INVOICE",
        "RECEIPT": "RECEIPT",
        "UNKNOWN": "DELIVERY NOTE",
    }.get(dt, "DOCUMENT")
    out.append(rec.get("supplier_name") or "")
    if rec.get("supplier_vat_number"):
        out.append(f"VAT No: {rec['supplier_vat_number']}")
    out.append("")
    out.append(title)
    if rec.get("document_number"):
        out.append(f"Number: {rec['document_number']}")
    if rec.get("customer_name"):
        out.append(f"Bill to: {rec['customer_name']}")
    if rec.get("document_date"):
        out.append(f"Date: {rec['document_date']}")
    out.append("")
    for li in rec.get("line_items", []):
        out.append(f"  {li.get('description') or 'Item':<24} {_money(li.get('net')):>10}")
    out.append("")
    if rec.get("net_total"):
        out.append(f"Net total:   {_money(rec['net_total'])}")
    if rec.get("vat_total"):
        out.append(f"VAT total:   {_money(rec['vat_total'])}")
    if rec.get("gross_total"):
        out.append(f"Gross total: {_money(rec['gross_total'])}")
    if dt == "UNKNOWN":
        out.append("Goods received: 5 boxes timber. Signed on delivery.")
    return out


def _render_pdf(path: Path, lines: list[str]) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    y = height - 72
    c.setFont("Helvetica-Bold", 14)
    c.drawString(72, y, lines[0] if lines else "")
    c.setFont("Helvetica", 11)
    y -= 24
    for line in lines[1:]:
        c.drawString(72, y, line)
        y -= 16
        if y < 72:
            c.showPage()
            y = height - 72
            c.setFont("Helvetica", 11)
    c.showPage()
    c.save()


def _render_degraded_pdf(path: Path, rec: dict) -> None:
    """Render a receipt to an image, degrade it, embed it in a PDF."""

    from PIL import Image, ImageDraw, ImageFilter
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    img = Image.new("RGB", (500, 320), "white")
    d = ImageDraw.Draw(img)
    text = "\n".join(
        [
            rec.get("supplier_name") or "RECEIPT",
            "RECEIPT",
            "Coffee .......... 2.80",
            "Pastry .......... 1.40",
            "TOTAL ........... 4.20",
            "Thank you!",
        ]
    )
    d.multiline_text((30, 30), text, fill=(60, 60, 60), spacing=14)

    # Degrade: low contrast, rotate, blur, add noise.
    img = Image.blend(img, Image.new("RGB", img.size, (150, 150, 150)), 0.45)
    img = img.rotate(7, expand=True, fillcolor=(200, 200, 200))
    img = img.filter(ImageFilter.GaussianBlur(1.6))
    rnd = random.Random(5)
    px = img.load()
    for _ in range(6000):
        x = rnd.randint(0, img.size[0] - 1)
        yy = rnd.randint(0, img.size[1] - 1)
        v = rnd.randint(0, 255)
        px[x, yy] = (v, v, v)

    img_path = path.with_suffix(".png")
    img.save(img_path)

    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    c.drawImage(str(img_path), 72, height - 400, width=400, preserveAspectRatio=True)
    c.showPage()
    c.save()
    img_path.unlink(missing_ok=True)


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    records = sorted(EXTRACTED.glob("*.json"))
    for path in records:
        rec = json.loads(path.read_text(encoding="utf-8"))
        out = DOCS / rec["source_file"]
        if rec["doc_type"] == "RECEIPT" and rec["confidence"] < 0.4:
            _render_degraded_pdf(out, rec)
        else:
            _render_pdf(out, _lines_for(rec))
        print("wrote", out.name)


if __name__ == "__main__":
    main()
