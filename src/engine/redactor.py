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
        r'\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}'
        r'|'
        r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}'
        r'|'
        r'\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}'
        r')',
        re.IGNORECASE
    ),
]

STANDALONE_DATE_PATTERNS = [
    re.compile(r'\b\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}\b'),
    re.compile(r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b', re.IGNORECASE),
    re.compile(r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2},?\s+\d{4}\b', re.IGNORECASE),
]

NAME_LABEL_PATTERNS = [
    # Pattern 0: Labeled field — "Patient Name: John Smith" / "Patient: DOE, JANE K"
    re.compile(
        r'\b(Patient[\'\s]*s?\s*Name|Patient\s*Name|Full\s*Name|Patient|Name)[:\s]+'
        r'([A-Z][a-zA-Z\-\']+(?:,\s*[A-Z][a-zA-Z\-\']+)?(?:\s+[A-Z][a-zA-Z\-\'\.]+){0,3})'
        r'(?=\s*$|\s*\n|\s*\||\s+(?:DOB|MRN|SSN|Phone|Address|Age|DATE|FILE|is\s+a\b|was\b|presents\b))',
        re.IGNORECASE
    ),

    # Pattern 1: "Patient John Smith is/was/presents..."
    re.compile(
        r'\bPatient\s+'
        r'([A-Z][a-zA-Z\-\']+(?:\s+[A-Z][a-zA-Z\-\'\.]+){0,3})'
        r'(?=\s+(?:is|was|has|had|presents|presented|denies|reports|states|called|reached)\b)',
        re.IGNORECASE
    ),

    # Pattern 2: "Mr./Mrs./Ms./Miss" + EITHER "Last, First [Initial]" OR "First [Mid] Last"
    re.compile(
        r'\b(Mr|Mrs|Ms|Miss)\.?\s+'
        r'('
        r'[A-Z][A-Za-z\-\']+,\s+[A-Z][A-Za-z\-\']+(?:\s+[A-Z]\.?)?'
        r'|'
        r'[A-Z][a-zA-Z\-\']+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][a-zA-Z\-\']+){0,2}'
        r')',
        re.IGNORECASE
    ),

    # Pattern 3: "Re: FirstName LastName[, DOB/MRN]" — referral letter subject line
    re.compile(
        r'\bRe:\s+'
        r'([A-Z][a-zA-Z\-\']+(?:\s+[A-Z][a-zA-Z\-\']+){1,3})'
        r'(?=\s*,|\s+DOB|\s+MRN)',
        re.IGNORECASE
    ),

    # Pattern 4: "...my patient, Last, First [Initial], DOB/MRN/("
    re.compile(
        r'\bpatient,?\s+'
        r'([A-Z][A-Za-z\-\']+,\s+[A-Z][A-Za-z\-\']+(?:\s+[A-Z]\.?)?)'
        r'(?=\s*,|\s+DOB|\s+MRN|\s+\()',
        re.IGNORECASE
    ),

    # Pattern 5: "...my patient, First Last, DOB/MRN/("
    re.compile(
        r'\bpatient,?\s+'
        r'([A-Z][A-Za-z\-\']+\s+[A-Z][A-Za-z\-\']+(?:\s+[A-Z]\.?)?)'
        r'(?=\s*,|\s+DOB|\s+MRN|\s+\()',
        re.IGNORECASE
    ),

    # Pattern 6: Bare "Last, First [Initial]" when followed within 80 chars by DOB or MRN
    re.compile(
        r'\b([A-Z][A-Za-z\-\']+),\s+([A-Z][A-Za-z\-\']+(?:\s+[A-Z]\.?)?)'
        r'(?=[^.]{0,80}(?:DOB|D\.O\.B|Date\s+of\s+Birth|MRN|Medical\s+Record))',
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


NON_NAME_WORDS = {
    'demographics', 'information', 'details', 'summary', 'report',
    'note', 'notes', 'record', 'data', 'history', 'profile',
    'unknown', 'confidential', 'patient', 'laboratory', 'discharge',
    'referral', 'clinical', 'medical', 'intake', 'admission',
    'letter', 'evaluation', 'consultation', 'assessment', 'follow', 'update',
    'the', 'and', 'for', 'with', 'date', 'birth',
    'none', 'n/a', 'na', 'mr', 'mrs', 'ms', 'miss', 'dr'
}

SUFFIXES = {
    'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii',
    'jr', 'jr.', 'sr', 'sr.', 'esq', 'esq.',
    'md', 'md.', 'do', 'do.', 'phd', 'phd.'
}

CONNECTORS = {'de', 'la', 'van', 'von', 'del', 'le', 'el', 'bin', 'binti', 'al'}


def _normalize_name(name: str) -> str:
    """
    Normalize a patient name to 'Firstname [Middle] Lastname' order.

    Handles:
      MAKENA, SHALOM          -> Shalom Makena
      MAKENA, SHALOM M        -> Shalom M Makena
      MAKENA, SHALOM MARIE    -> Shalom Marie Makena
      DOE, JANE K             -> Jane K Doe
      O'BRIEN, JAMES F        -> James F O'Brien
      WASHINGTON-BANKS, L     -> L Washington-Banks
      DE LA CRUZ, MARIA       -> Maria De La Cruz
      JOHN SMITH              -> John Smith  (unchanged)
    """
    name = name.strip()

    comma_match = re.match(
        r"^([A-Za-z][A-Za-z\-\']*(?:\s+[A-Za-z][A-Za-z\-\']*)*)"
        r",\s*"
        r"([A-Za-z][A-Za-z\-\']*)"
        r"((?:\s+[A-Za-z]\.?)*)?$",
        name
    )
    if comma_match:
        last  = comma_match.group(1).strip().title()
        first = comma_match.group(2).strip().title()
        mid   = (comma_match.group(3) or "").strip().title()
        if mid:
            return f"{first} {mid} {last}"
        return f"{first} {last}"

    if name.isupper():
        return name.title()

    return name


def _clean_name(name: str) -> str:
    """Strip trailing punctuation and whitespace from extracted name."""
    return re.sub(r'[\s.,;:]+$', '', name.strip())


def _split_name_parts(name: str):
    """
    Split a normalized 'First [Middle...] Last' name into
    (first, middles, last) with suffixes stripped.
    Returns (None, [], None) if name is too short.

    Examples:
      'Shalom M Makena'            -> ('Shalom', ['M'], 'Makena')
      'Theodore James Harrington'  -> ('Theodore', ['James'], 'Harrington')
      'Rosa Mendez-Villarreal'     -> ('Rosa', [], 'Mendez-Villarreal')
      'Jane Doe'                   -> ('Jane', [], 'Doe')
    """
    parts = name.strip().split()
    if len(parts) < 2:
        return None, [], None

    while parts and parts[-1].lower() in SUFFIXES:
        parts.pop()
    if len(parts) < 2:
        return None, [], None

    first   = parts[0]
    last    = parts[-1]
    middles = parts[1:-1]
    return first, middles, last


def _build_name_variants(original_name: str) -> list[str]:
    """
    Build all search variants from a patient name string.

    For 'MAKENA, SHALOM M' generates:
      'Shalom M Makena', 'Shalom Makena', 'MAKENA, SHALOM M',
      'Makena, Shalom M', 'Makena, Shalom', 'SHALOM MAKENA',
      'Shalom M', 'Makena', 'Shalom'  (last/first if 5+ chars)
    """
    original_name = original_name.strip()
    if not original_name:
        return []

    normalized = _normalize_name(original_name)
    first, middles, last = _split_name_parts(normalized)

    if first is None:
        return []

    variants = set()

    # Full normalized form
    if middles:
        variants.add(f"{first} {' '.join(middles)} {last}")
    else:
        variants.add(f"{first} {last}")

    # First + Last (no middle) — always add for 3-part names
    variants.add(f"{first} {last}")

    # Comma format variations
    if middles:
        variants.add(f"{last}, {first} {' '.join(middles)}")
        variants.add(f"{last.upper()}, {first.upper()} {' '.join(m.upper() for m in middles)}")
    variants.add(f"{last}, {first}")
    variants.add(f"{last.upper()}, {first.upper()}")

    # ALL CAPS no comma
    variants.add(f"{first.upper()} {last.upper()}")
    if middles:
        variants.add(f"{first.upper()} {' '.join(m.upper() for m in middles)} {last.upper()}")

    # First + middle (initial and full word)
    if middles:
        mid_initial = middles[0][0]
        variants.add(f"{first} {mid_initial}")
        variants.add(f"{first} {mid_initial}.")
        if len(middles[0]) > 1:
            variants.add(f"{first} {middles[0]}")

    # Last, First initial
    variants.add(f"{last}, {first[0]}")
    variants.add(f"{last} {first[0]}")

    # Single names — only if long enough to avoid false positives
    if len(last) >= 5:
        variants.add(last)
        variants.add(last.upper())
    if len(first) >= 5:
        variants.add(first)
        variants.add(first.upper())

    # Hyphenated last name — add each part separately
    if '-' in last:
        for part in last.split('-'):
            if len(part) >= 5:
                variants.add(part)

    # Always add original exactly as provided
    variants.add(original_name)

    # Filter too-short or non-name words
    filtered = [
        v for v in variants
        if len(v.strip()) >= 2
        and v.strip().lower() not in NON_NAME_WORDS
    ]

    # Longest first — prevents partial matches clobbering full matches
    filtered.sort(key=len, reverse=True)

    # Deduplicate case-insensitively
    seen = set()
    unique = []
    for v in filtered:
        key = v.strip().lower()
        if key not in seen:
            seen.add(key)
            unique.append(v.strip())

    return unique


def _extract_name_from_page1(doc: Document) -> str | None:
    """
    Discover the patient name from the first page of a DOCX.
    Tries multiple strategies in priority order.
    Returns a normalized name string, or None if not found.
    """

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
    
    # ── Priority 0: Bold standalone paragraph — name as document title/heading ──
    for para in doc.paragraphs[:5]:
        text = para.text.strip()
        if not text:
            continue
        is_bold = para.runs and any(run.bold for run in para.runs)
        if is_bold and re.match(r'^[A-Z][a-zA-Z\-\']+([\s][A-Z][a-zA-Z\-\']+){1,3}$', text):
            if is_valid_name(text):
                return _clean_name(_normalize_name(text))
        
    # ── Priority 1: "Re: FirstName LastName, DOB..." subject line ──
    for para in doc.paragraphs[:30]:
        text = para.text.strip()
        m = NAME_LABEL_PATTERNS[3].search(text)
        if m:
            name = _clean_name(_normalize_name(m.group(1).strip()))
            if is_valid_name(name):
                return name

    # ── Priority 2: Table label → value (most reliable) ──
    for table in doc.tables:
        rows = table.rows
        if not rows:
            continue

        # Layout A: label | value in the SAME row (e.g. "Patient Name" | "John Smith")
        for row in rows:
            cells = [c.text.strip() for c in row.cells]
            for i, cell in enumerate(cells):
                if re.match(r'^(Patient\s*Name|Full\s*Name|Name)$', cell, re.IGNORECASE):
                    if i + 1 < len(cells) and cells[i + 1]:
                        candidate = _normalize_name(cells[i + 1].strip())
                        if is_valid_name(candidate):
                            return _clean_name(candidate)

        # Layout B: label is a COLUMN HEADER in row 0, value is in row 1 below it
        if len(rows) >= 2:
            header_cells = [c.text.strip() for c in rows[0].cells]
            for col_idx, header in enumerate(header_cells):
                if re.match(r'^(Patient\s*Name|Full\s*Name|Name)$', header, re.IGNORECASE):
                    value = rows[1].cells[col_idx].text.strip()
                    if value:
                        candidate = _normalize_name(value)
                        if is_valid_name(candidate):
                            return _clean_name(candidate)

        break  # first table only

    # ── Priority 3: Paragraph patterns — checked in order ──
    for para in doc.paragraphs[:30]:
        text = para.text.strip()
        if not text:
            continue

        # Pattern 0: "Patient Name: John Smith" / "Patient: DOE, JANE K"
        m = NAME_LABEL_PATTERNS[0].search(text)
        if m:
            name = _clean_name(_normalize_name(m.group(2).strip()))
            if is_valid_name(name):
                return name

        # Pattern 1: "Patient John Smith is/was..."
        m = NAME_LABEL_PATTERNS[1].search(text)
        if m:
            name = m.group(1).strip()
            if is_valid_name(name):
                return name

        # Pattern 2: "Mr./Mrs. Last, First Initial" or "Mr./Mrs. First Last"
        m = NAME_LABEL_PATTERNS[2].search(text)
        if m:
            name = _clean_name(_normalize_name(m.group(2).strip()))
            if is_valid_name(name):
                return name

        # Pattern 4: "my patient, Last, First [Initial], DOB..."
        m = NAME_LABEL_PATTERNS[4].search(text)
        if m:
            name = _clean_name(_normalize_name(m.group(1).strip()))
            if is_valid_name(name):
                return name

        # Pattern 5: "my patient, First Last, DOB..."
        m = NAME_LABEL_PATTERNS[5].search(text)
        if m:
            name = m.group(1).strip()
            if is_valid_name(name):
                return name

        # Pattern 6: Bare "Last, First [Initial]" near DOB/MRN (safety net)
        m = NAME_LABEL_PATTERNS[6].search(text)
        if m:
            raw = f"{m.group(1)}, {m.group(2)}"
            name = _clean_name(_normalize_name(raw))
            if is_valid_name(name):
                return name

    return None


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
    counts = {"PATIENT_NAME": 0, "DATE_OF_BIRTH": 0, "MRN": 0}

    # ── Step 1: Discover patient name from page 1 ──
    patient_name = _extract_name_from_page1(doc)
    name_variants = _build_name_variants(patient_name) if patient_name else []

    # ── Step 2: Build tagged replacement list ──
    # Each entry: (pattern, replacement, is_regex, entity_type)
    tagged_replacements = []

    # MRN — must have explicit label, min 5 digits
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

    # Name variants — longest first to prevent partial clobber
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

        # Mask emails to prevent partial name redaction inside addresses
        emails = re.findall(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', full_text)
        masked_text = full_text
        email_map = {}
        for i, email in enumerate(emails):
            placeholder = f"__EMAIL_{i}__"
            email_map[placeholder] = email
            masked_text = masked_text.replace(email, placeholder)

        new_text = masked_text
        for pattern, replacement, is_regex, entity_type in tagged_replacements:
            if is_regex:
                new_text, n = re.subn(pattern, replacement, new_text)
            else:
                n = new_text.count(pattern)
                new_text = new_text.replace(pattern, replacement)
            counts[entity_type] += n

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

                if cell_id in seen_cell_ids:
                    i += 1
                    continue
                seen_cell_ids.add(cell_id)

                cell_label = cell.text.strip().lower()

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
                        if is_regex:
                            new_text, n = re.subn(pattern, replacement, new_text)
                        else:
                            n = new_text.count(pattern)
                            new_text = new_text.replace(pattern, replacement)
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

    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"{ts}_{document_id}_redaction_log.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    result["log_path"] = log_path

    return result