import os
import re
import json
from datetime import datetime
from docx import Document
from docx.oxml.ns import qn


# ─────────────────────────────────────────────
# PATTERNS
# ─────────────────────────────────────────────

MRN_PATTERNS = [
    re.compile(r'\b(MRN|Medical\s*Record\s*(Number)?|Medical\s*Record\s*No\.?|Record\s*#|MR|Patient\s*ID)[:\s#]*([A-Z0-9\-]{4,12})\b', re.IGNORECASE),
]

DOB_LABEL_PATTERNS = [
    re.compile(
        r'\b(DOB|D\.O\.B\.?|Date\s*of\s*Birth|Birth\s*Date|Birthdate|Born)[:\s]*'
        r'('
        r'\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}'          # 01/15/1980 or 1-15-80
        r'|'
        r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}'  # Jan 15, 1980
        r'|'
        r'\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}'    # 15 Jan 1980
        r')',
        re.IGNORECASE

    ),
]

# Standalone dates only when near a DOB label — captured separately
STANDALONE_DATE_PATTERNS = [
    re.compile(r'\b\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}\b'),
    re.compile(r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b', re.IGNORECASE),
    re.compile(r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2},?\s+\d{4}\b', re.IGNORECASE),
]

NAME_LABEL_PATTERNS = [	
    re.compile(
        r'\b(Patient[\'\s]*s?\s*Name|Patient\s*Name|Full\s*Name|Patient|Name)[:\s]+'
        r'([A-Z][a-zA-Z\-\']+(?:,\s*[A-Z][a-zA-Z\-\']+)?(?:\s+[A-Z][a-zA-Z\-\'\.]+){0,3})'
        r'(?=\s*$|\s*\n|\s+(?:DOB|MRN|SSN|Phone|Address|Age|DATE|FILE|is\s+a\b|was\b|presents\b))',
        re.IGNORECASE
    ),
    re.compile(
        r'\bPatient\s+'
        r'([A-Z][a-zA-Z\-\']+(?:\s+[A-Z][a-zA-Z\-\'\.]+){0,3})'
        r'(?=\s+(?:is|was|has|had|presents|presented|denies|reports|states|called|reached)\b)',
        re.IGNORECASE
    ),
    # "Mr./Mrs./Ms./Miss FirstName LastName" — patient honorifics only, never Dr/Prof
        re.compile(
            r'\b(Mr|Mrs|Ms|Miss)\.?\s+'
            r'([A-Z][a-zA-Z\-\']+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][a-zA-Z\-\']+){0,2})',
            re.IGNORECASE
        ),
    # "Re: FirstName LastName" or "Re: FirstName LastName," — referral letter format
        re.compile(
            r'\bRe:\s+'
            r'([A-Z][a-zA-Z\-\']+(?:\s+[A-Z][a-zA-Z\-\']+){1,3})'
            r'(?=\s*,|\s+DOB|\s+MRN|\s+DOB)',
            re.IGNORECASE
        ),
]

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _get_all_text_from_docx(doc: Document) -> str:
    """Extract all text from a DOCX for name discovery."""
    parts = []
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text)
    return "\n".join(parts)

# Words that are section headings, not patient names
NON_NAME_WORDS = {
    'demographics', 'information', 'details', 'summary', 'report',
    'note', 'notes', 'record', 'data', 'history', 'profile',
    'unknown', 'confidential', 'patient', 'laboratory', 'discharge',
    'referral', 'clinical', 'medical', 'intake', 'admission'
}

def _normalize_name(name: str) -> str:
    """
    Convert last-name-first format to first-last.
    'MAKENA, SHALOM' → 'Shalom Makena'
    'DOE, REGINA' → 'Regina Doe'
    """
    comma_match = re.match(
        r'^([A-Za-z\-\']+),\s*([A-Za-z\-\']+(?:\s+[A-Za-z\-\']+)?)$',
        name.strip()
    )
    if comma_match:
        last = comma_match.group(1).strip().title()
        first = comma_match.group(2).strip().title()
        return f"{first} {last}"
    # Normalize ALL CAPS to title case
    if name.isupper():
        return name.title()
    return name

def _clean_name(name: str) -> str:
    """Strip trailing punctuation and whitespace from extracted name."""
    return re.sub(r'[\s.,;:]+$', '', name.strip())

def _extract_name_from_page1(doc: Document) -> str | None:

    def is_valid_name(name: str) -> bool:
        if not name or len(name.strip()) < 2:
            return False
        parts = name.strip().split()
        if len(parts) == 1 and parts[0].lower() in NON_NAME_WORDS:
            return False
        if name.isupper() and len(parts) < 2:
            return False
        if not name[0].isupper():
            return False
        if any(p.lower() in NON_NAME_WORDS for p in parts):
            return False
        if not re.match(r"^[A-Za-z\s\-\'\.]+$", name):
            return False
        return True
    
    # ── Highest priority: "Re: FirstName LastName, DOB..." line ──
    for para in doc.paragraphs[:30]:
        text = para.text.strip()
        match = re.search(
            r'\bRe:\s+([A-Z][a-zA-Z\-\']+(?:\s+[A-Z][a-zA-Z\-\']+){1,3})'
            r'(?=\s*,|\s+DOB|\s+MRN)',
            text, re.IGNORECASE
        )
        if match:
            name = match.group(1).strip()
            if is_valid_name(name):
                return _clean_name(_normalize_name(name))
            
    # ── Check tables FIRST — most reliable source ──
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            for i, cell in enumerate(cells):
                if re.match(r'^(Patient\s*Name|Full\s*Name|Name)$', cell, re.IGNORECASE):
                    if i + 1 < len(cells):
                        candidate = _normalize_name(cells[i + 1].strip())
                        if is_valid_name(candidate):
                            return _clean_name(candidate)
        break  # first table only

    # ── Then check first 20 paragraphs ──
    for para in doc.paragraphs[:20]:
        text = para.text.strip()
        # Pattern 0: "Patient Name: John Smith"
        match = NAME_LABEL_PATTERNS[0].search(text)
        if match:
            name = _normalize_name(match.group(2).strip())
            if is_valid_name(name):
                return _clean_name(name)
        # Pattern 1: "Patient John Smith is..."
        match = NAME_LABEL_PATTERNS[1].search(text)
        if match:
            name = match.group(1).strip()
            if is_valid_name(name):
                return name
        # Pattern 2: "Mr./Mrs./Ms. John Smith"
        match = NAME_LABEL_PATTERNS[2].search(text)
        if match:
            name = match.group(2).strip()
            if is_valid_name(name):
                return name
        match = NAME_LABEL_PATTERNS[3].search(text)
        if match:
            name = match.group(1).strip()
            if is_valid_name(name):
                return _clean_name(_normalize_name(name))
    return None

def _build_name_variants(original_name: str) -> list[str]:
    """Build all search variants from a patient name."""
    # Clean trailing punctuation from the whole name first
    original_name = _normalize_name(original_name)
    original_name = re.sub(r'[.,;:]+$', '', original_name.strip())
    parts = original_name.strip().split()
    clean_parts = []
    connectors = {'de', 'la', 'van', 'von', 'del', 'le', 'el', 'bin', 'binti'}

    for part in parts:
        stripped = part.rstrip('.,')
        if stripped[0].islower() and stripped.lower() not in connectors:
            break
        clean_parts.append(stripped)

    if not clean_parts:
        return []

    # Full name with suffix (e.g. Theodore James Harrington III)
    full_with_suffix = " ".join(clean_parts)

    # Core name without roman numerals/suffixes
    core_parts = [
        p for p in clean_parts
        if not re.match(r'^(I|II|III|IV|V|VI|VII|Jr\.?|Sr\.?|Esq\.?)$', p, re.IGNORECASE)
    ]
    core_name = " ".join(core_parts)

    variants = []

    if len(clean_parts) >= 2:
        variants.append(full_with_suffix)

    if core_name != full_with_suffix and len(core_parts) >= 2:
        variants.append(core_name)

    for part in core_parts:
        clean = part.rstrip('.,')
        if len(clean) >= 4:
            variants.append(clean)

    if len(core_parts) >= 2:
        variants.append(f"{core_parts[0]} {core_parts[-1][0]}")
        variants.append(f"{core_parts[0]} {core_parts[-1][0]}.")
        variants.append(f"{core_parts[-1]} {core_parts[0][0]}")
        variants.append(f"{core_parts[-1]}, {core_parts[0][0]}")

    variants.sort(key=len, reverse=True)

    seen = set()
    unique = []
    for v in variants:
        if v.lower() not in seen and len(v) >= 2:
            seen.add(v.lower())
            unique.append(v)

    return unique


def _replace_in_text(text: str, pattern_or_string, replacement: str, is_regex: bool = True) -> tuple[str, int]:
    """Replace all occurrences in text. Returns (new_text, count)."""
    if is_regex:
        new_text, count = re.subn(pattern_or_string, replacement, text)
    else:
        count = text.count(pattern_or_string)
        new_text = text.replace(pattern_or_string, replacement)
    return new_text, count


def _merge_runs_text(para) -> str:
    """Get full paragraph text from all runs combined."""
    return "".join(run.text for run in para.runs)


def _apply_to_merged_runs(para, replacements: list[tuple]) -> int:
    """
    Merge all runs into one text string, apply replacements,
    then put result back into first run. Preserves paragraph
    formatting but consolidates run-level formatting to first run.
    """
    if not para.runs:
        return 0

    full_text = _merge_runs_text(para)
    if not full_text.strip():
        return 0

    new_text = full_text
    total = 0
    for pattern_or_string, replacement, is_regex in replacements:
        new_text, count = _replace_in_text(new_text, pattern_or_string, replacement, is_regex)
        total += count

    if new_text != full_text:
        # Put all text in first run, clear the rest
        para.runs[0].text = new_text
        for run in para.runs[1:]:
            run.text = ""

    return total


def _process_paragraph(para, replacements: list[tuple]) -> int:
    """Apply replacements to a paragraph using merged run strategy."""
    return _apply_to_merged_runs(para, replacements)


def _process_table_cell(cell, replacements: list[tuple]) -> int:
    """Apply replacements to all paragraphs in a table cell."""
    total = 0
    for para in cell.paragraphs:
        total += _process_paragraph(para, replacements)
    return total


# ─────────────────────────────────────────────
# MAIN REDACTION FUNCTION
# ─────────────────────────────────────────────

def redact_docx(input_path: str, document_id: str = "unknown") -> dict:
    """
    Performs targeted in-place redaction of:
      - Patient name
      - Date of birth
      - Medical record number

    Preserves all DOCX formatting, fonts, tables, and structure.
    Returns result dict with output_path, redaction counts, and audit log path.
    """
    doc = Document(input_path)
    redaction_log = []
    counts = {"PATIENT_NAME": 0, "DATE_OF_BIRTH": 0, "MRN": 0}

    # ── Step 1: Discover patient name from page 1 ──
    patient_name = _extract_name_from_page1(doc)
    name_variants = _build_name_variants(patient_name) if patient_name else []

# ── Step 2: Build tagged replacement list ──
    # Each entry: (pattern, replacement, is_regex, entity_type)
    tagged_replacements = []
    # MRN — must have explicit label, min 5 digits, no Gleason-style patterns
    tagged_replacements.append((
        re.compile(
            r'\b(MRN|Medical\s*Record\s*(?:Number)?|Medical\s*Record\s*No\.?|Record\s*#|Patient\s*ID)'
            r'([:\s#]*)(\d{5,12})\b',
            re.IGNORECASE
        ),
        r'\1\2[MRN]',
        True,
        "MRN"
    ))

    # DOB
    tagged_replacements.append((
        re.compile(
            r'(\b(?:DOB|D\.O\.B\.?|Date\s*of\s*Birth|Birth\s*Date|Birthdate|Born)[:\s]*)'
            r'('
            r'\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}'
            r'|'
            r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}'
            r'|'
            r'\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}'
            r')',
            re.IGNORECASE
        ),
        r'\1[DATE OF BIRTH]',
        True,
        "DATE_OF_BIRTH"
    ))

    # Name variants
    for variant in name_variants:
        escaped = re.escape(variant)
        tagged_replacements.append((
            re.compile(r'\b' + escaped + r'\b', re.IGNORECASE),
            '[PATIENT NAME]',
            True,
            "PATIENT_NAME"
        ))

# ── Step 3: Process all paragraphs ──
    for para in doc.paragraphs:
        full_text = "".join(run.text for run in para.runs)
        if not full_text.strip():
            continue

        # Temporarily mask email addresses to prevent partial redaction
        emails = re.findall(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', full_text)
        masked_text = full_text
        email_map = {}
        for i, email in enumerate(emails):
            placeholder = f"__EMAIL_{i}__"
            email_map[placeholder] = email
            masked_text = masked_text.replace(email, placeholder)

        new_text = masked_text
        for pattern, replacement, is_regex, entity_type in tagged_replacements:
            new_text, n = re.subn(pattern, replacement, new_text) if is_regex else (new_text.replace(pattern, replacement), new_text.count(pattern))
            counts[entity_type] += n

        # Restore email addresses
        for placeholder, email in email_map.items():
            new_text = new_text.replace(placeholder, email)

        if new_text != full_text and para.runs:
            para.runs[0].text = new_text
            for run in para.runs[1:]:
                run.text = ""

# ── Step 4: Process all tables ──
    for table in doc.tables:
        seen_cell_ids = set()
        for row in table.rows:
            cells = row.cells
            i = 0
            while i < len(cells):
                cell = cells[i]
                cell_id = id(cell._tc)

                # Skip merged cell duplicates
                if cell_id in seen_cell_ids:
                    i += 1
                    continue
                seen_cell_ids.add(cell_id)

                cell_label = cell.text.strip().lower()

                # Check if this cell is a known label — direct replace next cell
                if re.match(r'^(mrn|medical record|medical record number|record #|patient id)$', cell_label):
                    if i + 1 < len(cells):
                        val = cells[i + 1]
                        seen_cell_ids.add(id(val._tc))
                        for p in val.paragraphs:
                            if p.text.strip() and p.runs:
                                p.runs[0].text = '[MRN]'
                                for r in p.runs[1:]: r.text = ''
                                counts["MRN"] += 1
                    i += 2
                    continue

                elif re.match(r'^(dob|date of birth|birth date|birthdate|born)$', cell_label):
                    if i + 1 < len(cells):
                        val = cells[i + 1]
                        seen_cell_ids.add(id(val._tc))
                        for p in val.paragraphs:
                            if p.text.strip() and p.runs:
                                p.runs[0].text = '[DATE OF BIRTH]'
                                for r in p.runs[1:]: r.text = ''
                                counts["DATE_OF_BIRTH"] += 1
                    i += 2
                    continue

                elif re.match(r'^(patient\s*name|full\s*name)$', cell_label):
                    if i + 1 < len(cells):
                        val = cells[i + 1]
                        seen_cell_ids.add(id(val._tc))
                        for p in val.paragraphs:
                            if p.text.strip() and p.runs:
                                p.runs[0].text = '[PATIENT NAME]'
                                for r in p.runs[1:]: r.text = ''
                                counts["PATIENT_NAME"] += 1
                    i += 2
                    continue

                # All other cells — apply regex replacements
                for cell_para in cell.paragraphs:
                    full_text = "".join(run.text for run in cell_para.runs)
                    if not full_text.strip():
                        continue
                    emails = re.findall(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', full_text)
                    masked_text = full_text
                    email_map = {}
                    for j, email in enumerate(emails):
                        placeholder = f"__EMAIL_{j}__"
                        email_map[placeholder] = email
                        masked_text = masked_text.replace(email, placeholder)
                    new_text = masked_text
                    for pattern, replacement, is_regex, entity_type in tagged_replacements:
                        new_text, n = re.subn(pattern, replacement, new_text) if is_regex else (new_text.replace(pattern, replacement), new_text.count(pattern))
                        counts[entity_type] += n
                    for placeholder, email in email_map.items():
                        new_text = new_text.replace(placeholder, email)
                    if new_text != full_text and cell_para.runs:
                        cell_para.runs[0].text = new_text
                        for r in cell_para.runs[1:]: r.text = ""
                i += 1
                                    
    # ── Step 5: Save redacted DOCX ──
    output_dir = "output_docs"
    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    base_name = base_name.replace("_converted", "")
    output_filename = f"REDACTED_{base_name}.docx"
    output_path = os.path.join(output_dir, output_filename)
    doc.save(output_path)

    # ── Step 6: Build audit log ──
    total = sum(counts.values())
    result = {
        "document_id": document_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "output_path": output_path,
        "patient_name_discovered": patient_name or "not found",
        "name_variants_searched": name_variants,
        "entity_counts": counts,
        "total_redactions": total,
    }

    # Save log
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"{ts}_{document_id}_redaction_log.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    result["log_path"] = log_path

    return result
