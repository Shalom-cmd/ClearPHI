import os
import re
import json
import fitz  # PyMuPDF
from datetime import datetime
from PIL import Image
import pytesseract
import io
import shutil
import platform

# ─────────────────────────────────────────────
# TESSERACT PATH (cross-platform)
# ─────────────────────────────────────────────

if platform.system() == "Windows":
    tesseract_path = shutil.which("tesseract") or r"C:\Program Files\Tesseract-OCR\tesseract.exe"
else:
    tesseract_path = shutil.which("tesseract") or "/opt/homebrew/bin/tesseract"

pytesseract.pytesseract.tesseract_cmd = tesseract_path


# ─────────────────────────────────────────────
# REDACTION FILL COLOR
# Black box — change to (1,1,0) for yellow highlight review mode later
# ─────────────────────────────────────────────

REDACT_FILL = (0, 0, 0)   # RGB black
REDACT_LABEL = ""          # No text shown inside the box


# ─────────────────────────────────────────────
# PATTERNS (mirrors redactor.py)
# ─────────────────────────────────────────────

MRN_PATTERN = re.compile(
    r'\b(MRN|Medical\s*Record\s*(?:Number)?|Medical\s*Record\s*No\.?'
    r'|Record\s*#|Patient\s*ID)[:\s#]*(\d{5,12})\b',
    re.IGNORECASE
)

DOB_PATTERN = re.compile(
    r'\b(?:DOB|D\.O\.B\.?|Date\s*of\s*Birth|Birth\s*Date|Birthdate|Born)[:\s]*'
    r'('
    r'\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}'
    r'|'
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}'
    r'|'
    r'\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}'
    r')',
    re.IGNORECASE
)

# Name discovery patterns — used only for extracting the name from page 1 text
NAME_DISCOVERY_PATTERNS = [
    # "Patient Name: John Smith" / "Patient: DOE, JANE"
    re.compile(
        r'\b(?:Patient[\'\s]*s?\s*Name|Patient\s*Name|Full\s*Name|Patient|Name)[:\s]+'
        r'([A-Z][a-zA-Z\-\']+(?:,\s*[A-Z][a-zA-Z\-\']+)?(?:\s+[A-Z][a-zA-Z\-\'\.]+){0,3})'
        r'(?=\s*$|\s*\n|\s*\||\s+(?:DOB|MRN|SSN|Phone|Address|Age|DATE|FILE|is\s+a\b|was\b|presents\b))',
        re.IGNORECASE | re.MULTILINE
    ),
    # "Re: FirstName LastName, DOB/MRN"
    re.compile(
        r'\bRe:\s+([A-Z][a-zA-Z\-\']+(?:\s+[A-Z][a-zA-Z\-\']+){1,3})'
        r'(?=\s*,|\s+DOB|\s+MRN)',
        re.IGNORECASE
    ),
    # "Mr./Mrs./Ms. Last, First" or "Mr./Mrs./Ms. First Last"
    re.compile(
        r'\b(?:Mr|Mrs|Ms|Miss)\.?\s+'
        r'('
        r'[A-Z][A-Za-z\-\']+,\s+[A-Z][A-Za-z\-\']+(?:\s+[A-Z]\.?)?'
        r'|'
        r'[A-Z][a-zA-Z\-\']+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][a-zA-Z\-\']+){0,2}'
        r')',
        re.IGNORECASE
    ),
    # "patient, Last, First" or "patient, First Last"
    re.compile(
        r'\bpatient,?\s+([A-Z][A-Za-z\-\']+,\s+[A-Z][A-Za-z\-\']+(?:\s+[A-Z]\.?)?)'
        r'(?=\s*,|\s+DOB|\s+MRN|\s+\()',
        re.IGNORECASE
    ),
    # "Last, First" followed within 80 chars by DOB or MRN
    re.compile(
        r'\b([A-Z][A-Za-z\-\']+),\s+([A-Z][A-Za-z\-\']+(?:\s+[A-Z]\.?)?)'
        r'(?=[^.]{0,80}(?:DOB|D\.O\.B|Date\s+of\s+Birth|MRN|Medical\s+Record))',
        re.IGNORECASE
    ),
]

NON_NAME_WORDS = {
    'demographics', 'information', 'details', 'summary', 'report',
    'note', 'notes', 'record', 'data', 'history', 'profile',
    'unknown', 'confidential', 'patient', 'laboratory', 'discharge',
    'referral', 'clinical', 'medical', 'intake', 'admission',
    'letter', 'evaluation', 'consultation', 'assessment', 'follow', 'update',
    'the', 'and', 'for', 'with', 'date', 'birth',
    'none', 'n/a', 'na', 'mr', 'mrs', 'ms', 'miss', 'dr'
}

SUFFIXES = {'i', 'ii', 'iii', 'iv', 'v', 'jr', 'jr.', 'sr', 'sr.',
            'md', 'md.', 'do', 'do.', 'phd', 'phd.'}

CONNECTORS = {'de', 'la', 'van', 'von', 'del', 'le', 'el', 'bin', 'binti', 'al'}


# ─────────────────────────────────────────────
# NAME UTILITIES (mirrors redactor.py logic)
# ─────────────────────────────────────────────

def _normalize_name(name: str) -> str:
    """
    Normalize to 'Firstname [Middle] Lastname' order.
    Handles: ALL CAPS, Last/First comma format, mixed case.
    """
    name = name.strip()
    comma_match = re.match(
        r"^([A-Za-z][A-Za-z\-\']*(?:\s+[A-Za-z][A-Za-z\-\']*)*)"
        r",\s*([A-Za-z][A-Za-z\-\']*)((?:\s+[A-Za-z]\.?)*)?$",
        name
    )
    if comma_match:
        last  = comma_match.group(1).strip().title()
        first = comma_match.group(2).strip().title()
        mid   = (comma_match.group(3) or "").strip().title()
        return f"{first} {mid} {last}".strip() if mid else f"{first} {last}"
    if name.isupper():
        return name.title()
    return name


def _split_name_parts(name: str):
    parts = name.strip().split()
    if len(parts) < 2:
        return None, [], None
    while parts and parts[-1].lower() in SUFFIXES:
        parts.pop()
    if len(parts) < 2:
        return None, [], None
    return parts[0], parts[1:-1], parts[-1]


def _build_name_variants(original_name: str) -> list[str]:
    """
    Build all search variants from the discovered patient name.
    Returns longest variants first to prevent partial-match clobbering.

    For 'MAKENA, SHALOM M' produces:
      'Shalom M Makena', 'Shalom Makena', 'MAKENA, SHALOM M',
      'Makena, Shalom M', 'Makena, Shalom', 'SHALOM MAKENA',
      'Shalom', 'Makena'  (only if 5+ chars)
    """
    original_name = original_name.strip()
    if not original_name:
        return []

    variants = set()
    normalized = _normalize_name(original_name)
    variants.add(normalized)
    variants.add(original_name)

    first, middles, last = _split_name_parts(normalized)
    if not first or not last:
        return sorted(variants, key=len, reverse=True)

    # Full name variants
    variants.add(f"{first} {last}")
    variants.add(f"{last} {first}")
    variants.add(f"{last.upper()} {first.upper()}")
    variants.add(f"{first.upper()} {last.upper()}")

    # With middle name/initial
    for mid in middles:
        variants.add(f"{first} {mid} {last}")
        if len(mid) >= 1:
            variants.add(f"{first} {mid[0]}. {last}")
            variants.add(f"{first} {mid[0]} {last}")

    # Comma-separated (Last, First) formats
    variants.add(f"{last}, {first}")
    variants.add(f"{last.upper()}, {first.upper()}")
    for mid in middles:
        variants.add(f"{last}, {first} {mid}")
        if len(mid) >= 1:
            variants.add(f"{last}, {first} {mid[0]}.")
            variants.add(f"{last}, {first} {mid[0]}")

    # Standalone last/first — only if 5+ chars to reduce false positives
    if len(last) >= 5:
        variants.add(last)
        variants.add(last.upper())
    if len(first) >= 5:
        variants.add(first)
        variants.add(first.upper())

    # Filter out non-name words and empty strings
    variants = {
        v for v in variants
        if v and v.lower().strip() not in NON_NAME_WORDS and len(v) >= 3
    }

    return sorted(variants, key=len, reverse=True)


def _extract_name_from_text(text: str) -> str | None:
    """
    Discover the patient name from the first ~2000 chars of extracted text.
    Tries all NAME_DISCOVERY_PATTERNS in priority order.
    """
    sample = text[:2000]
    for pattern in NAME_DISCOVERY_PATTERNS:
        match = pattern.search(sample)
        if match:
            raw = match.group(1).strip() if match.lastindex >= 1 else ""
            raw = re.sub(r'[\s.,;:]+$', '', raw)
            parts = raw.split()
            if len(parts) < 2:
                continue
            if all(p.lower() in NON_NAME_WORDS for p in parts):
                continue
            return raw
    return None


# ─────────────────────────────────────────────
# SCANNED PDF DETECTION
# ─────────────────────────────────────────────

def _is_scanned(pdf_path: str) -> bool:
    try:
        doc = fitz.open(pdf_path)
        total_text = "".join(page.get_text() for page in doc)
        doc.close()
        return len(total_text.strip()) < 100
    except Exception:
        return True


# ─────────────────────────────────────────────
# DIGITAL PDF — SEARCH AND REDACT
# ─────────────────────────────────────────────

def _redact_digital_pdf(doc: fitz.Document, name_variants: list[str],
                         counts: dict, mode: str = "labeled") -> None:
    """
    mode options:
      "labeled"    — white box with [PATIENT NAME] etc. in black text
      "blackbox"   — solid black box, no text
      "highlight"  — yellow highlight (for review mode, not final sharing)
    """

    def make_annot(page, rect, label):
        if mode == "blackbox":
            page.add_redact_annot(rect, fill=(0, 0, 0))
        elif mode == "highlight":
            page.add_redact_annot(rect, fill=(1, 1, 0))
        else:  # labeled (default)
            page.add_redact_annot(rect, text=label, fill=(1, 1, 1),
                                  fontsize=8, text_color=(0, 0, 0))

    for page in doc:
        page_text = page.get_text()

        # ── Patient name variants ──
        for variant in name_variants:
            rects = page.search_for(variant, quads=False)
            for rect in rects:
                make_annot(page, rect, "[PATIENT NAME]")
                counts["PATIENT_NAME"] += 1

        # ── DOB — redact the date value only ──
        for match in DOB_PATTERN.finditer(page_text):
            date_val = match.group(1).strip()
            rects = page.search_for(date_val, quads=False)
            for rect in rects:
                make_annot(page, rect, "[DATE OF BIRTH]")
                counts["DATE_OF_BIRTH"] += 1

        # ── MRN — redact the number value only ──
        for match in MRN_PATTERN.finditer(page_text):
            mrn_val = match.group(2).strip()
            rects = page.search_for(mrn_val, quads=False)
            for rect in rects:
                make_annot(page, rect, "[MRN]")
                counts["MRN"] += 1

        page.apply_redactions()

# ─────────────────────────────────────────────
# SCANNED PDF — OCR + COORDINATE MAPPING
# ─────────────────────────────────────────────

def _get_ocr_word_boxes(page: fitz.Page) -> list[dict]:
    """
    Render a PDF page at 300 DPI and run Tesseract word-level OCR.
    Returns list of dicts: {word, x0, y0, x1, y1} in PDF point coordinates.
    """
    # Render at 300 DPI
    scale = 300 / 72
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat)

    img_bytes = pix.tobytes("png")
    img = Image.open(io.BytesIO(img_bytes))

    # Get word-level bounding boxes from Tesseract
    data = pytesseract.image_to_data(img, lang='eng',
                                      output_type=pytesseract.Output.DICT)

    words = []
    n = len(data['text'])
    for i in range(n):
        word = data['text'][i].strip()
        if not word:
            continue
        conf = int(data['conf'][i])
        if conf < 30:   # ignore low-confidence OCR tokens
            continue

        # Pixel coords → PDF point coords (divide by scale factor)
        x0 = data['left'][i] / scale
        y0 = data['top'][i] / scale
        x1 = (data['left'][i] + data['width'][i]) / scale
        y1 = (data['top'][i] + data['height'][i]) / scale

        words.append({'word': word, 'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1})

    return words


def _words_to_text(word_boxes: list[dict]) -> str:
    """Reconstruct plain text from OCR word boxes for pattern matching."""
    return " ".join(w['word'] for w in word_boxes)


def _find_phrase_rects(phrase: str, word_boxes: list[dict]) -> list[fitz.Rect]:
    """
    Find all occurrences of a multi-word phrase in the OCR word list.
    Returns a list of fitz.Rect spanning all words in each match.

    Strategy: tokenize the phrase, slide a window over word_boxes looking
    for a consecutive sequence that matches (case-insensitive).
    """
    phrase_tokens = phrase.lower().split()
    n = len(phrase_tokens)
    if n == 0:
        return []

    rects = []
    words_lower = [w['word'].lower() for w in word_boxes]

    for i in range(len(word_boxes) - n + 1):
        window = words_lower[i:i + n]
        # Allow partial token matching for hyphenated/punctuated words
        match = all(
            phrase_tokens[j] in window[j] or window[j] in phrase_tokens[j]
            for j in range(n)
        )
        if match:
            # Span rect from first to last word in the match
            x0 = min(word_boxes[i + j]['x0'] for j in range(n))
            y0 = min(word_boxes[i + j]['y0'] for j in range(n))
            x1 = max(word_boxes[i + j]['x1'] for j in range(n))
            y1 = max(word_boxes[i + j]['y1'] for j in range(n))
            rects.append(fitz.Rect(x0, y0, x1, y1))

    return rects


def _redact_scanned_pdf(doc: fitz.Document, name_variants: list[str],
                         counts: dict, mode: str = "labeled") -> None:

    def make_annot(page, rect, label):
        if mode == "blackbox":
            page.add_redact_annot(rect, fill=(0, 0, 0))
        elif mode == "highlight":
            page.add_redact_annot(rect, fill=(1, 1, 0))
        else:
            page.add_redact_annot(rect, text=label, fill=(1, 1, 1),
                                  fontsize=8, text_color=(0, 0, 0))

    for page in doc:
        word_boxes = _get_ocr_word_boxes(page)
        if not word_boxes:
            continue

        page_text = _words_to_text(word_boxes)

        for variant in name_variants:
            rects = _find_phrase_rects(variant, word_boxes)
            for rect in rects:
                make_annot(page, rect, "[PATIENT NAME]")
                counts["PATIENT_NAME"] += 1

        for match in DOB_PATTERN.finditer(page_text):
            date_val = match.group(1).strip()
            for rect in _find_phrase_rects(date_val, word_boxes):
                make_annot(page, rect, "[DATE OF BIRTH]")
                counts["DATE_OF_BIRTH"] += 1

        for match in MRN_PATTERN.finditer(page_text):
            mrn_val = match.group(2).strip()
            for rect in _find_phrase_rects(mrn_val, word_boxes):
                make_annot(page, rect, "[MRN]")
                counts["MRN"] += 1

        page.apply_redactions()


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def redact_pdf(input_path: str, document_id: str = "unknown", 
               mode: str = "labeled") -> dict:
    """
    Performs targeted in-place redaction of a PDF file.
    Redacts: Patient Name, Date of Birth, MRN.
    Preserves all original PDF formatting, tables, images, and layout.

    Works on both digital and scanned (OCR) PDFs.
    Returns result dict with output_path, redaction counts, and audit log path.
    """
    doc = fitz.open(input_path)
    counts = {"PATIENT_NAME": 0, "DATE_OF_BIRTH": 0, "MRN": 0}
    scanned = _is_scanned(input_path)

    # ── Step 1: Extract text from page 1 to discover patient name ──
    if scanned:
        # For scanned PDFs, OCR page 1 for name discovery
        page0 = doc[0]
        word_boxes = _get_ocr_word_boxes(page0)
        page1_text = _words_to_text(word_boxes)
    else:
        page1_text = doc[0].get_text()

    patient_name = _extract_name_from_text(page1_text)
    name_variants = _build_name_variants(patient_name) if patient_name else []

    # ── Step 2: Redact all pages ──
    if scanned:
        _redact_scanned_pdf(doc, name_variants, counts, mode=mode)
    else:
        _redact_digital_pdf(doc, name_variants, counts, mode=mode)

    # ── Step 3: Save redacted PDF ──
    output_dir = "output_docs"
    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    output_filename = f"REDACTED_{base_name}.pdf"
    output_path = os.path.join(output_dir, output_filename)

    # garbage=4 + deflate = compact, clean PDF output
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()

    # ── Step 4: Audit log ──
    total = sum(counts.values())
    result = {
        "document_id": document_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "output_path": output_path,
        "output_format": "pdf",
        "scanned_document": scanned,
        "patient_name_discovered": patient_name or "not found",
        "name_variants_searched": name_variants,
        "entity_counts": counts,
        "total_redactions": total,
    }

    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"{ts}_{document_id}_redaction_log.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    result["log_path"] = log_path

    return result