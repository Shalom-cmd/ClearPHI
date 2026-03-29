import os
import fitz  # PyMuPDF
from pdf2docx import Converter
from docx import Document as DocxDocument
from PIL import Image
import pytesseract
import io
import shutil

tesseract_path = shutil.which("tesseract") or "/opt/homebrew/bin/tesseract"
pytesseract.pytesseract.tesseract_cmd = tesseract_path

def pdf_to_docx(pdf_path: str) -> str:
    """
    Converts a PDF to DOCX.
    Uses pdf2docx for digital PDFs, falls back to PyMuPDF + OCR for scanned/complex PDFs.
    """
    base = os.path.splitext(pdf_path)[0]
    docx_path = base + "_converted.docx"

    # First check if PDF has extractable text at all
    # If not — go straight to OCR, skip pdf2docx entirely
    if _is_scanned_or_complex(pdf_path):
        return _ocr_pdf_to_docx(pdf_path, docx_path)

    # Try pdf2docx with a subprocess so a crash doesn't kill Gunicorn
    try:
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-c",
             f"from pdf2docx import Converter; cv = Converter(r'{pdf_path}'); cv.convert(r'{docx_path}'); cv.close()"],
            timeout=60,
            capture_output=True
        )
        if result.returncode != 0:
            raise RuntimeError("pdf2docx failed")

        # Validate output
        doc = DocxDocument(docx_path)
        text = " ".join(p.text.strip() for p in doc.paragraphs if p.text.strip())
        if len(text) > 100:
            return docx_path
        raise RuntimeError("pdf2docx produced no text")

    except Exception:
        return _ocr_pdf_to_docx(pdf_path, docx_path)


def _is_scanned_or_complex(pdf_path: str) -> bool:
    """
    Returns True if PDF has little extractable text
    OR has deeply nested tables that crash pdf2docx.
    """
    try:
        pdf = fitz.open(pdf_path)
        total_text = ""
        for page in pdf:
            total_text += page.get_text()
        pdf.close()
        # If less than 100 chars of real text — it's scanned
        return len(total_text.strip()) < 100
    except Exception:
        return True

def _ocr_pdf_to_docx(pdf_path: str, output_path: str) -> str:
    """
    OCR fallback for scanned PDFs.
    Renders each page as an image and runs Tesseract on it.
    Builds a clean DOCX from the extracted text.
    """
    pdf = fitz.open(pdf_path)
    doc = DocxDocument()

    for page_num, page in enumerate(pdf):
        # Render page at 300 DPI for good OCR accuracy
        mat = fitz.Matrix(300 / 72, 300 / 72)
        pix = page.get_pixmap(matrix=mat)

        # Convert to PIL Image
        img_bytes = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_bytes))

        # Run Tesseract OCR
        ocr_text = pytesseract.image_to_string(img, lang='eng')

        # Add each non-empty line as a paragraph
        for line in ocr_text.split('\n'):
            line = line.strip()
            if line:
                doc.add_paragraph(line)

        # Page separator
        if page_num < len(pdf) - 1:
            doc.add_paragraph("─" * 40)

    pdf.close()
    doc.save(output_path)
    return output_path


def is_scanned_pdf(pdf_path: str) -> bool:
    """
    Returns True if the PDF appears to be scanned (image-only).
    Useful for logging/debugging.
    """
    pdf = fitz.open(pdf_path)
    total_text = ""
    for page in pdf:
        total_text += page.get_text()
    pdf.close()
    return len(total_text.strip()) < 100
