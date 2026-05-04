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
# GROUP 1 PATTERNS
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

SSN_PATTERN = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')

PHONE_PATTERN = re.compile(
    r'(?<!\d)'
    r'('
    r'\+?1?[\s\-\.]?\(?\d{3}\)?[\s\-\.]\d{3}[\s\-\.]\d{4}(?:\s*(?:x|ext\.?)\s*\d{1,6})?'
    r'|'
    r'(?:001|\+1)[\s\-]?\d{3}[\s\-]\d{3}[\s\-]\d{4}(?:\s*(?:x|ext\.?)\s*\d{1,6})?'
    r'|'
    r'\(\d{3}\)\s*\d{3}[\s\-]\d{4}(?:\s*(?:x|ext\.?)\s*\d{1,6})?'
    r')'
    r'(?!\d)',
    re.IGNORECASE
)

FAX_PATTERN = re.compile(
    r'\b(?:Fax|FAX|Fax\s*#|Fax\s*Number)[:\s]*'
    r'[\+]?[\d\s\-\(\)\.]{7,20}\b',
    re.IGNORECASE
)

EMAIL_PATTERN = re.compile(
    r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'
)

IP_PATTERN = re.compile(
    r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b'
)

URL_PATTERN = re.compile(
    r'https?://[^\s<>"\']+|www\.[^\s<>"\']+',
    re.IGNORECASE
)


# ─────────────────────────────────────────────
# GROUP 2 PATTERNS
# ─────────────────────────────────────────────

# All dates more specific than year-only (Safe Harbor requirement).
# Numeric format uses validated month (01-12) and day (01-31) ranges to
# prevent IP addresses (e.g. 10.51.194.72) from matching as dates.
ALL_DATE_PATTERN = re.compile(
    r'\b(?:'
    # MM/DD/YYYY — validated ranges prevent IP address false positives
    r'(?:0?[1-9]|1[0-2])[\/\-\.](?:0?[1-9]|[12]\d|3[01])[\/\-\.]\d{2,4}'
    r'|'
    # Month DD, YYYY  (full month name)
    r'(?:January|February|March|April|May|June|July|August'
    r'|September|October|November|December)\s+\d{1,2},?\s+\d{4}'
    r'|'
    # Mon DD, YYYY  (abbreviated)
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2},?\s+\d{4}'
    r'|'
    # Month YYYY  (month + year — more specific than year alone)
    r'(?:January|February|March|April|May|June|July|August'
    r'|September|October|November|December)\s+\d{4}'
    r'|'
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{4}'
    r'|'
    # ISO: YYYY-MM-DD with validated ranges
    r'\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])'
    r')\b',
    re.IGNORECASE
)

# Ages over 89 (Safe Harbor: ages 90+ must be redacted)
AGE_OVER_89_PATTERN = re.compile(
    r'\b(9\d|1[0-9]{2})[- ]year[- ]old\b'
    r'|\b(?:Age|AGE)[:\s]+(9\d|1[0-9]{2})\b',
    re.IGNORECASE
)

# ZIP codes — labeled or address context (State abbreviation + 5 digits)
ZIP_PATTERN = re.compile(
    r'\b(?:ZIP|Zip\s*Code|Postal\s*Code)[:\s]*\d{5}(?:-\d{4})?'
    r'|\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b'
)

# NPI — 10-digit National Provider Identifier
NPI_PATTERN = re.compile(
    r'\b(?:NPI|National\s*Provider\s*(?:Identifier|ID|Number)?)[:\s#]*(\d{10})\b',
    re.IGNORECASE
)

# Account numbers — labeled only
ACCOUNT_PATTERN = re.compile(
    r'\b(?:Account\s*(?:Number|No\.?|#)|Acct\.?\s*(?:Number|No\.?|#)?)'
    r'[:\s#]*([A-Z0-9\-]{4,17})\b',
    re.IGNORECASE
)

# Beneficiary / Member / Policy / Group / Insurance IDs — labeled only.
# Requires a colon or # between label and value to prevent matching
# facility names containing "Group" (e.g. "Valley View Medical Group").
BENEFICIARY_PATTERN = re.compile(
    r'\b(?:Beneficiary\s*(?:ID|Number|No\.?)?|Member\s*(?:ID|Number|No\.?)?'
    r'|Subscriber\s*(?:ID|Number|No\.?)?|Policy\s*(?:Number|No\.?)?'
    r'|Group\s*(?:Number|No\.?)?|Plan\s*(?:ID|Number)'
    r'|Insurance\s*(?:ID|Number|No\.?)?)'
    r'\s*[:#]\s*([A-Z0-9\-]{4,20})\b',
    re.IGNORECASE
)

# Address — labeled only; redacts street, city, state, ZIP as a unit.
# Negative lookbehind for "IP " prevents "IP address: x.x.x.x" from matching.
ADDRESS_PATTERN = re.compile(
    r'(?<![Ii][Pp] )(\b(?:Patient\s*)?Address[:\s]+)([^\n\|]{10,120})',
    re.IGNORECASE
)

# License / DEA / Certificate numbers — labeled only
LICENSE_PATTERN = re.compile(
    r'\b(?:(?:Medical\s*)?License\s*(?:Number|No\.?|#)?'
    r'|DEA\s*(?:Number|No\.?|#)?'
    r'|(?:State|Professional)\s*License)'
    r'[:\s#]*([A-Z0-9\-]{4,15})\b',
    re.IGNORECASE
)

# Device / Serial / UDI numbers — labeled only
DEVICE_PATTERN = re.compile(
    r'\b(?:(?:Device|Serial|Implant)\s*(?:ID|Number|No\.?|#)|UDI|Serial\s*#)'
    r'[:\s#]*([A-Z0-9\-\/]{4,20})\b',
    re.IGNORECASE
)

# VINs — labeled only (17-char alphanumeric, no I/O/Q per ISO 3779)
VIN_PATTERN = re.compile(
    r'\b(?:VIN|Vehicle\s*Identification\s*(?:Number)?|License\s*Plate\s*(?:Number)?)'
    r'[:\s#]*([A-HJ-NPR-Z0-9]{17})\b',
    re.IGNORECASE
)


# ─────────────────────────────────────────────
# NAME DISCOVERY PATTERNS
# ─────────────────────────────────────────────

NAME_DISCOVERY_PATTERNS = [
    re.compile(
        r'\b(?:Patient[\'\s]*s?\s*Name|Patient\s*Name|Full\s*Name|Patient|Name)[:\s]+'
        r'([A-Z][a-zA-Z\-\']+(?:,\s*[A-Z][a-zA-Z\-\']+)?(?:\s+[A-Z][a-zA-Z\-\'\.]+){0,3})'
        r'(?=\s*$|\s*\n|\s*\||\s+(?:DOB|MRN|SSN|Phone|Address|Age|DATE|FILE|is\s+a\b|was\b|presents\b))',
        re.IGNORECASE | re.MULTILINE
    ),
    re.compile(
        r'\bRe:\s+([A-Z][a-zA-Z\-\']+(?:\s+[A-Z][a-zA-Z\-\']+){1,3})'
        r'(?=\s*,|\s+DOB|\s+MRN)',
        re.IGNORECASE
    ),
    re.compile(
        r'\b(?:Mr|Mrs|Ms|Miss)\.?\s+'
        r'('
        r'[A-Z][A-Za-z\-\']+,\s+[A-Z][A-Za-z\-\']+(?:\s+[A-Z]\.?)?'
        r'|'
        r'[A-Z][a-zA-Z\-\']+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][a-zA-Z\-\']+){0,2}'
        r')',
        re.IGNORECASE
    ),
    re.compile(
        r'\bpatient,?\s+([A-Z][A-Za-z\-\']+,\s+[A-Z][A-Za-z\-\']+(?:\s+[A-Z]\.?)?)'
        r'(?=\s*,|\s+DOB|\s+MRN|\s+\()',
        re.IGNORECASE
    ),
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
# NAME UTILITIES
# ─────────────────────────────────────────────

def _normalize_name(name: str) -> str:
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

    variants.add(f"{first} {last}")
    variants.add(f"{last} {first}")
    variants.add(f"{last.upper()} {first.upper()}")
    variants.add(f"{first.upper()} {last.upper()}")

    for mid in middles:
        variants.add(f"{first} {mid} {last}")
        if len(mid) >= 1:
            variants.add(f"{first} {mid[0]}. {last}")
            variants.add(f"{first} {mid[0]} {last}")

    variants.add(f"{last}, {first}")
    variants.add(f"{last.upper()}, {first.upper()}")
    for mid in middles:
        variants.add(f"{last}, {first} {mid}")
        if len(mid) >= 1:
            variants.add(f"{last}, {first} {mid[0]}.")
            variants.add(f"{last}, {first} {mid[0]}")

    if len(last) >= 5:
        variants.add(last)
        variants.add(last.upper())
    if len(first) >= 5:
        variants.add(first)
        variants.add(first.upper())

    variants = {
        v for v in variants
        if v and v.lower().strip() not in NON_NAME_WORDS and len(v) >= 3
    }

    return sorted(variants, key=len, reverse=True)


def _extract_name_from_text(text: str) -> str | None:
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
# RECT MERGING
# ─────────────────────────────────────────────

def _merge_rects(rects: list[fitz.Rect],
                 y_tolerance: float = 3.0,
                 x_gap_tolerance: float = 20.0) -> list[fitz.Rect]:
    if not rects:
        return []
    rects = sorted(rects, key=lambda r: (round(r.y0 / y_tolerance), r.x0))
    merged = []
    current = rects[0]
    for next_rect in rects[1:]:
        same_line   = abs(next_rect.y0 - current.y0) <= y_tolerance
        close_enough = (next_rect.x0 - current.x1) <= x_gap_tolerance
        if same_line and close_enough:
            current = fitz.Rect(
                min(current.x0, next_rect.x0),
                min(current.y0, next_rect.y0),
                max(current.x1, next_rect.x1),
                max(current.y1, next_rect.y1)
            )
        else:
            merged.append(current)
            current = next_rect
    merged.append(current)
    return merged


# ─────────────────────────────────────────────
# DIGITAL PDF — SEARCH AND REDACT
# ─────────────────────────────────────────────

def _redact_digital_pdf(doc: fitz.Document, name_variants: list[str],
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
        page_text = page.get_text()

        # ── Patient name ──
        all_name_rects = []
        for variant in name_variants:
            all_name_rects.extend(page.search_for(variant, quads=False))
        for rect in _merge_rects(all_name_rects):
            make_annot(page, rect, "[PATIENT NAME]")
            counts["PATIENT_NAME"] += 1

        # ── DOB — track caught values so ALL_DATE doesn't re-annotate them ──
        dob_caught = set()
        for match in DOB_PATTERN.finditer(page_text):
            date_val = match.group(1).strip()
            dob_caught.add(date_val.lower())
            for rect in page.search_for(date_val, quads=False):
                make_annot(page, rect, "[DATE OF BIRTH]")
                counts["DATE_OF_BIRTH"] += 1

        # ── MRN ──
        for match in MRN_PATTERN.finditer(page_text):
            mrn_val = match.group(2).strip()
            for rect in page.search_for(mrn_val, quads=False):
                make_annot(page, rect, "[MRN]")
                counts["MRN"] += 1

        # ── SSN ──
        for match in SSN_PATTERN.finditer(page_text):
            for rect in page.search_for(match.group(0), quads=False):
                make_annot(page, rect, "[SSN]")
                counts["SSN"] += 1

        # ── Phone ──
        for match in PHONE_PATTERN.finditer(page_text):
            val = match.group(0).strip()
            for rect in page.search_for(val, quads=False):
                make_annot(page, rect, "[PHONE]")
                counts["PHONE"] += 1

        # ── Fax ──
        for match in FAX_PATTERN.finditer(page_text):
            val = match.group(0).strip()
            for rect in page.search_for(val, quads=False):
                make_annot(page, rect, "[FAX]")
                counts["FAX"] += 1

        # ── Email ──
        for match in EMAIL_PATTERN.finditer(page_text):
            val = match.group(0).strip()
            for rect in page.search_for(val, quads=False):
                make_annot(page, rect, "[EMAIL]")
                counts["EMAIL"] += 1

        # ── IP Address ──
        for match in IP_PATTERN.finditer(page_text):
            val = match.group(0).strip()
            for rect in page.search_for(val, quads=False):
                make_annot(page, rect, "[IP ADDRESS]")
                counts["IP_ADDRESS"] += 1

        # ── URL ──
        for match in URL_PATTERN.finditer(page_text):
            val = match.group(0).strip()
            for rect in page.search_for(val, quads=False):
                make_annot(page, rect, "[URL]")
                counts["URL"] += 1

        # All dates — skip any value already annotated as DOB
        for match in ALL_DATE_PATTERN.finditer(page_text):
            val = match.group(0).strip()
            if val.lower() in dob_caught:
                continue
            for rect in page.search_for(val, quads=False):
                make_annot(page, rect, "[DATE]")
                counts["DATE"] += 1

        # Ages over 89
        for match in AGE_OVER_89_PATTERN.finditer(page_text):
            val = match.group(0).strip()
            for rect in page.search_for(val, quads=False):
                make_annot(page, rect, "[AGE]")
                counts["AGE"] += 1

        # Address — run before ZIP so we can track covered values
        address_caught = set()
        for match in ADDRESS_PATTERN.finditer(page_text):
            val = match.group(2).strip()
            address_caught.add(val.lower())
            for rect in page.search_for(val, quads=False):
                make_annot(page, rect, "[ADDRESS]")
                counts["ADDRESS"] += 1

        # ZIP codes — skip any that are already inside a caught address
        for match in ZIP_PATTERN.finditer(page_text):
            val = match.group(0).strip()
            if any(val.lower() in addr for addr in address_caught):
                continue
            for rect in page.search_for(val, quads=False):
                make_annot(page, rect, "[ZIP]")
                counts["ZIP"] += 1

        # NPI — redact value only
        for match in NPI_PATTERN.finditer(page_text):
            val = match.group(1).strip()
            for rect in page.search_for(val, quads=False):
                make_annot(page, rect, "[NPI]")
                counts["NPI"] += 1

        # Account numbers — redact value only
        for match in ACCOUNT_PATTERN.finditer(page_text):
            val = match.group(1).strip()
            for rect in page.search_for(val, quads=False):
                make_annot(page, rect, "[ACCOUNT NUMBER]")
                counts["ACCOUNT_NUMBER"] += 1

        # Beneficiary / Member / Policy IDs — redact value only
        for match in BENEFICIARY_PATTERN.finditer(page_text):
            val = match.group(1).strip()
            for rect in page.search_for(val, quads=False):
                make_annot(page, rect, "[BENEFICIARY ID]")
                counts["BENEFICIARY_ID"] += 1

        # License / DEA numbers — redact value only
        for match in LICENSE_PATTERN.finditer(page_text):
            val = match.group(1).strip()
            for rect in page.search_for(val, quads=False):
                make_annot(page, rect, "[LICENSE NUMBER]")
                counts["LICENSE_NUMBER"] += 1

        # Device / Serial / UDI numbers — redact value only
        for match in DEVICE_PATTERN.finditer(page_text):
            val = match.group(1).strip()
            for rect in page.search_for(val, quads=False):
                make_annot(page, rect, "[DEVICE ID]")
                counts["DEVICE_ID"] += 1

        # VINs — redact value only
        for match in VIN_PATTERN.finditer(page_text):
            val = match.group(1).strip()
            for rect in page.search_for(val, quads=False):
                make_annot(page, rect, "[VIN]")
                counts["VIN"] += 1

        page.apply_redactions()


# ─────────────────────────────────────────────
# SCANNED PDF — OCR + COORDINATE MAPPING
# ─────────────────────────────────────────────

def _get_ocr_word_boxes(page: fitz.Page) -> list[dict]:
    scale = 300 / 72
    mat   = fitz.Matrix(scale, scale)
    pix   = page.get_pixmap(matrix=mat)

    img_bytes = pix.tobytes("png")
    img  = Image.open(io.BytesIO(img_bytes))
    data = pytesseract.image_to_data(img, lang='eng',
                                      output_type=pytesseract.Output.DICT)
    words = []
    for i in range(len(data['text'])):
        word = data['text'][i].strip()
        if not word:
            continue
        if int(data['conf'][i]) < 30:
            continue
        scale_inv = 1 / scale
        words.append({
            'word': word,
            'x0': data['left'][i] * scale_inv,
            'y0': data['top'][i]  * scale_inv,
            'x1': (data['left'][i] + data['width'][i])  * scale_inv,
            'y1': (data['top'][i]  + data['height'][i]) * scale_inv,
        })
    return words


def _words_to_text(word_boxes: list[dict]) -> str:
    return " ".join(w['word'] for w in word_boxes)


def _find_phrase_rects(phrase: str, word_boxes: list[dict]) -> list[fitz.Rect]:
    phrase_tokens = phrase.lower().split()
    n = len(phrase_tokens)
    if n == 0:
        return []
    rects       = []
    words_lower = [w['word'].lower() for w in word_boxes]
    for i in range(len(word_boxes) - n + 1):
        window = words_lower[i:i + n]
        if all(phrase_tokens[j] in window[j] or window[j] in phrase_tokens[j]
               for j in range(n)):
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

        # ── Patient name ──
        all_name_rects = []
        for variant in name_variants:
            all_name_rects.extend(_find_phrase_rects(variant, word_boxes))
        for rect in _merge_rects(all_name_rects):
            make_annot(page, rect, "[PATIENT NAME]")
            counts["PATIENT_NAME"] += 1

        # ── DOB — track caught values ──
        dob_caught = set()
        for match in DOB_PATTERN.finditer(page_text):
            dob_caught.add(match.group(1).strip().lower())
            for rect in _find_phrase_rects(match.group(1).strip(), word_boxes):
                make_annot(page, rect, "[DATE OF BIRTH]")
                counts["DATE_OF_BIRTH"] += 1

        # ── MRN ──
        for match in MRN_PATTERN.finditer(page_text):
            for rect in _find_phrase_rects(match.group(2).strip(), word_boxes):
                make_annot(page, rect, "[MRN]")
                counts["MRN"] += 1

        # ── SSN ──
        for match in SSN_PATTERN.finditer(page_text):
            for rect in _find_phrase_rects(match.group(0), word_boxes):
                make_annot(page, rect, "[SSN]")
                counts["SSN"] += 1

        # ── Phone ──
        for match in PHONE_PATTERN.finditer(page_text):
            for rect in _find_phrase_rects(match.group(0).strip(), word_boxes):
                make_annot(page, rect, "[PHONE]")
                counts["PHONE"] += 1

        # ── Fax ──
        for match in FAX_PATTERN.finditer(page_text):
            for rect in _find_phrase_rects(match.group(0).strip(), word_boxes):
                make_annot(page, rect, "[FAX]")
                counts["FAX"] += 1

        # ── Email ──
        for match in EMAIL_PATTERN.finditer(page_text):
            for rect in _find_phrase_rects(match.group(0).strip(), word_boxes):
                make_annot(page, rect, "[EMAIL]")
                counts["EMAIL"] += 1

        # ── IP Address ──
        for match in IP_PATTERN.finditer(page_text):
            for rect in _find_phrase_rects(match.group(0).strip(), word_boxes):
                make_annot(page, rect, "[IP ADDRESS]")
                counts["IP_ADDRESS"] += 1

        # ── URL ──
        for match in URL_PATTERN.finditer(page_text):
            for rect in _find_phrase_rects(match.group(0).strip(), word_boxes):
                make_annot(page, rect, "[URL]")
                counts["URL"] += 1

        # ── GROUP 2 ────────────────────────────────────────

        for match in ALL_DATE_PATTERN.finditer(page_text):
            val = match.group(0).strip()
            if val.lower() in dob_caught:
                continue
            for rect in _find_phrase_rects(val, word_boxes):
                make_annot(page, rect, "[DATE]")
                counts["DATE"] += 1

        for match in AGE_OVER_89_PATTERN.finditer(page_text):
            for rect in _find_phrase_rects(match.group(0).strip(), word_boxes):
                make_annot(page, rect, "[AGE]")
                counts["AGE"] += 1

        for match in ZIP_PATTERN.finditer(page_text):
            val = match.group(0).strip()
            if any(val.lower() in addr for addr in address_caught):
                continue
            for rect in _find_phrase_rects(val, word_boxes):
                make_annot(page, rect, "[ZIP]")
                counts["ZIP"] += 1

        address_caught = set()
        for match in ADDRESS_PATTERN.finditer(page_text):
            val = match.group(2).strip()
            address_caught.add(val.lower())
            for rect in _find_phrase_rects(val, word_boxes):
                make_annot(page, rect, "[ADDRESS]")
                counts["ADDRESS"] += 1

        for match in NPI_PATTERN.finditer(page_text):
            for rect in _find_phrase_rects(match.group(1).strip(), word_boxes):
                make_annot(page, rect, "[NPI]")
                counts["NPI"] += 1

        for match in ACCOUNT_PATTERN.finditer(page_text):
            for rect in _find_phrase_rects(match.group(1).strip(), word_boxes):
                make_annot(page, rect, "[ACCOUNT NUMBER]")
                counts["ACCOUNT_NUMBER"] += 1

        for match in BENEFICIARY_PATTERN.finditer(page_text):
            for rect in _find_phrase_rects(match.group(1).strip(), word_boxes):
                make_annot(page, rect, "[BENEFICIARY ID]")
                counts["BENEFICIARY_ID"] += 1

        for match in LICENSE_PATTERN.finditer(page_text):
            for rect in _find_phrase_rects(match.group(1).strip(), word_boxes):
                make_annot(page, rect, "[LICENSE NUMBER]")
                counts["LICENSE_NUMBER"] += 1

        for match in DEVICE_PATTERN.finditer(page_text):
            for rect in _find_phrase_rects(match.group(1).strip(), word_boxes):
                make_annot(page, rect, "[DEVICE ID]")
                counts["DEVICE_ID"] += 1

        for match in VIN_PATTERN.finditer(page_text):
            for rect in _find_phrase_rects(match.group(1).strip(), word_boxes):
                make_annot(page, rect, "[VIN]")
                counts["VIN"] += 1

        page.apply_redactions()


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def redact_pdf(input_path: str, document_id: str = "unknown",
               mode: str = "labeled", output_dir: str = "output_docs") -> dict:
    """
    Performs targeted in-place redaction of a PDF file.
    Redacts Group 1 + Group 2 Safe Harbor identifiers.
    Preserves all original PDF formatting, tables, images, and layout.
    Works on both digital and scanned (OCR) PDFs.
    """
    doc = fitz.open(input_path)
    counts = {
        # Group 1
        "PATIENT_NAME": 0, "DATE_OF_BIRTH": 0, "MRN": 0,
        "SSN": 0, "PHONE": 0, "FAX": 0, "EMAIL": 0,
        "IP_ADDRESS": 0, "URL": 0,
        # Group 2
        "DATE": 0, "AGE": 0, "ZIP": 0, "NPI": 0,
        "ADDRESS": 0, "ACCOUNT_NUMBER": 0, "BENEFICIARY_ID": 0,
        "LICENSE_NUMBER": 0, "DEVICE_ID": 0, "VIN": 0,
    }
    scanned = _is_scanned(input_path)

    # Step 1: Discover patient name from page 1
    if scanned:
        word_boxes = _get_ocr_word_boxes(doc[0])
        page1_text = _words_to_text(word_boxes)
    else:
        page1_text = doc[0].get_text()

    patient_name  = _extract_name_from_text(page1_text)
    name_variants = _build_name_variants(patient_name) if patient_name else []

    # Step 2: Redact all pages
    if scanned:
        _redact_scanned_pdf(doc, name_variants, counts, mode=mode)
    else:
        _redact_digital_pdf(doc, name_variants, counts, mode=mode)

    # Step 3: Save
    os.makedirs(output_dir, exist_ok=True)
    base_name       = os.path.splitext(os.path.basename(input_path))[0]
    output_path     = os.path.join(output_dir, f"REDACTED_{base_name}.pdf")
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()

    # Step 4: Audit log
    total  = sum(counts.values())
    result = {
        "document_id":             document_id,
        "timestamp":               datetime.utcnow().isoformat() + "Z",
        "output_path":             output_path,
        "output_format":           "pdf",
        "scanned_document":        scanned,
        "patient_name_discovered": patient_name or "not found",
        "name_variants_searched":  name_variants,
        "entity_counts":           counts,
        "total_redactions":        total,
    }

    log_dir  = "logs"
    os.makedirs(log_dir, exist_ok=True)
    ts       = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"{ts}_{document_id}_redaction_log.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    result["log_path"] = log_path

    return result