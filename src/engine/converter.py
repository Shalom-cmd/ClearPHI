import os
from pdf2docx import Converter
import fitz  # PyMuPDF


def pdf_to_docx(pdf_path: str) -> str:
    """
    Converts a PDF to DOCX.
    For complex PDFs with images, falls back to text-only extraction.
    Returns the path to the converted DOCX file.
    """
    base = os.path.splitext(pdf_path)[0]
    docx_path = base + "_converted.docx"

    try:
        cv = Converter(pdf_path)
        cv.convert(docx_path, start=0, end=None)
        cv.close()

        # Validate the output is a real DOCX
        from docx import Document
        Document(docx_path)
        return docx_path

    except Exception:
        # Fallback — extract text only via PyMuPDF and build a simple DOCX
        return _pdf_text_to_docx(pdf_path, docx_path)


def _pdf_text_to_docx(pdf_path: str, output_path: str) -> str:
    """
    Fallback: extract plain text from PDF using PyMuPDF
    and write it into a clean DOCX preserving paragraph breaks.
    """
    from docx import Document as DocxDocument

    pdf = fitz.open(pdf_path)
    doc = DocxDocument()

    for page_num, page in enumerate(pdf):
        blocks = page.get_text("blocks")
        blocks.sort(key=lambda b: (b[1], b[0]))
        for block in blocks:
            text = block[4].strip()
            if text:
                for line in text.split('\n'):
                    line = line.strip()
                    if line:
                        doc.add_paragraph(line)
        if page_num < len(pdf) - 1:
            doc.add_paragraph("─" * 40)

    pdf.close()
    doc.save(output_path)
    return output_path