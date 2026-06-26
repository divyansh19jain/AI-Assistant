"""
Run this script once after placing ODM07216fillx.pdf in backend/app/pdf/
to print all AcroForm widget field names and their page numbers.

Usage:
  cd backend
  python -m app.pdf.inspect_fields
"""
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print("PyMuPDF not installed. Run: pip install pymupdf")
    sys.exit(1)

PDF_PATH = Path(__file__).parent / "ODM07216fillx.pdf"

if not PDF_PATH.exists():
    print(f"PDF not found at: {PDF_PATH}")
    print("Place ODM07216fillx.pdf in backend/app/pdf/ and re-run.")
    sys.exit(1)

doc = fitz.open(str(PDF_PATH))
print(f"PDF: {PDF_PATH.name} — {len(doc)} pages\n")

fields = []
for page_num, page in enumerate(doc, start=1):
    for widget in page.widgets() or []:
        fields.append({
            "page": page_num,
            "name": widget.field_name,
            "type": widget.field_type_string,
            "rect": list(widget.rect),
        })

if not fields:
    print("No AcroForm widgets found — PDF may not have fillable fields.")
else:
    print(f"Found {len(fields)} AcroForm fields:\n")
    for f in fields:
        print(f"  Page {f['page']:2d}  {f['type']:12s}  {f['name']}")

doc.close()
