# ClearPHI

A fully local, HIPAA-compliant de-identification tool for clinical documents. Redacts patient name, date of birth, 
and MRN from DOCX and PDF files before research upload — no patient data ever leaves the machine.

---

## Overview

| | |
|---|---|
| **Input formats** | `.docx`, `.pdf` (digital and scanned) |
| **Output formats** | `.docx` (for DOCX input), `.pdf` (for PDF input) |
| **Redacts** | Patient Name, Date of Birth, MRN |
| **Redaction modes** | Labeled `[PATIENT NAME]`, black box, yellow highlight |
| **OCR support** | Scanned/image-only PDFs via Tesseract 5.5.2 |
| **Deployment** | Mac Mini (production), Windows (development) |
| **Access** | Password-protected browser UI at `localhost:5001` |

---

## How It Works

```
Document In (DOCX or PDF)
        │
        ▼
  ┌─────────────────────────────────┐
  │         app.py (Flask)          │
  │   /deidentify/upload endpoint   │
  └──────────┬──────────────────────┘
             │
     ┌───────┴───────┐
     │               │
  .docx            .pdf
     │               │
     ▼               ▼
redactor.py    pdf_redactor.py
(python-docx   (PyMuPDF in-place
 XML in-place   redaction — PDF
 redaction)     stays as PDF)
     │               │
     └───────┬───────┘
             │
             ▼
     output_docs/REDACTED_*
             │
             ▼
     logs/*_redaction_log.json
```

PDFs are redacted in-place using PyMuPDF redaction annotations — the original layout, tables, images, and formatting are fully preserved. Only the PHI text is replaced. DOCX files are redacted at the XML level using python-docx, also preserving all formatting.

---

## Stack

| Component | Technology |
|---|---|
| PDF redaction | PyMuPDF 1.27+ — native redaction annotations |
| DOCX redaction | python-docx — XML-level in-place redaction |
| OCR | Tesseract 5.5.2 via pytesseract |
| PHI detection | Custom regex patterns + Microsoft Presidio |
| Web server | Flask + Gunicorn (2 workers, 120s timeout) |
| Auto-start | macOS launchd (production) |
| Encryption | macOS FileVault (production Mac Mini) |

---

## Project Structure

```
ClearPHI/
├── src/
│   ├── engine/
│   │   ├── pdf_redactor.py     # PDF in-place redaction (PyMuPDF)
│   │   ├── redactor.py         # DOCX in-place redaction (python-docx)
│   │   ├── deid.py             # Full 18-identifier Presidio engine (legacy)
│   │   ├── extractor.py        # Text extraction utility
│   │   └── converter.py        # PDF→DOCX converter (dead code, pending removal)
│   └── service/
│       ├── app.py              # Flask routes and endpoints
│       ├── ui.html             # Browser UI
│       └── login.html          # Login page
├── input_docs/                 # Drop files here for testing
├── output_docs/                # Redacted output files saved here
├── logs/                       # JSON audit logs per document
└── requirements.txt
```

---

## Setup

### Development (Windows)

```powershell
git clone https://github.com/Shalom-cmd/ClearPHI.git
cd ClearPHI
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
echo DEID_PASSWORD=yourpassword > .env
python src/service/app.py
# UI at http://localhost:5000
```

### Production (Mac Mini)

```bash
git pull
source venv/bin/activate
pip install -r requirements.txt
launchctl stop com.clearphi.service
launchctl start com.clearphi.service
# UI at http://localhost:5001
```

---

## Quick Test

```powershell
python -c "
from src.engine.pdf_redactor import redact_pdf
result = redact_pdf('input_docs/YOUR_FILE.pdf', document_id='test001', mode='labeled')
print('Output:', result['output_path'])
print('Redactions:', result['entity_counts'])
print('Name found:', result['patient_name_discovered'])
print('Scanned:', result['scanned_document'])
"
```

---

## Redaction Modes

| Mode | Appearance | Use case |
|---|---|---|
| `labeled` | White box with `[PATIENT NAME]` in black text | Default — clean, readable output |
| `blackbox` | Solid black box | Maximum opacity |
| `highlight` | Yellow highlight | Review mode — not for final sharing |

Pass via the API as a form field: `mode=labeled`

---

## PHI Detection

### Patient Name

Discovered from the first 2000 characters of the document using priority-ordered patterns, then expanded into 15+ search variants:

| Pattern | Example |
|---|---|
| Referral line | `Re: James R. Wilson, DOB...` |
| Labeled field | `Patient Name: Maria Gonzalez` |
| Honorific | `Mr. / Mrs. / Ms. Last, First` |
| ALL CAPS | `WILSON, JAMES ROBERT` |
| Mid-sentence | `patient, Last First (DOB...)` |

Variants searched: full name, first/last only, ALL CAPS, comma-reversed (Last, First), with/without middle initial, standalone first and last name if 5+ characters.

### Date of Birth

All common date formats following any of these labels: `DOB`, `D.O.B.`, `Date of Birth`, `Birth Date`, `Birthdate`, `Born`

Formats caught: `MM/DD/YYYY`, `MM-DD-YY`, `Jan 1, 2000`, `1 January 2000`, and more.

### MRN

Six label styles: `MRN`, `Medical Record Number`, `Medical Record No.`, `Record #`, `Patient ID`

Intentionally ignores: Gleason scores (`3+4=7`), biopsy percentages (`20% of tissue`), room numbers, blood pressure readings.

---

## Scanned PDF Support

ClearPHI auto-detects whether a PDF contains real text or scanned images. If fewer than 100 characters of extractable text are found, it falls back to OCR:

1. Each page rendered at 300 DPI
2. Tesseract returns word-level bounding boxes with confidence scores
3. PHI matched against OCR word list
4. Redaction boxes placed at exact pixel coordinates, converted to PDF point space

OCR processing takes 30–60 seconds per document depending on page count.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Browser UI (login required) |
| `GET` | `/login` | Login page |
| `POST` | `/login` | Authenticate with password |
| `POST` | `/logout` | Clear session |
| `POST` | `/deidentify/upload` | Upload and redact a file |
| `GET` | `/deidentify/download?path=` | Download redacted output |
| `POST` | `/deidentify/text` | Redact raw text (JSON body) |
| `GET` | `/health` | Service health check |

---

## Audit Logs

Every document processed generates a JSON log in `logs/`:

```json
{
  "document_id": "sample_clinical_note",
  "timestamp": "2024-09-25T00:00:00Z",
  "output_path": "output_docs/REDACTED_sample_clinical_note.pdf",
  "output_format": "pdf",
  "scanned_document": false,
  "patient_name_discovered": "James Robert Wilson",
  "name_variants_searched": ["James Robert Wilson", "Wilson, James", "WILSON", "..."],
  "entity_counts": {
    "PATIENT_NAME": 14,
    "DATE_OF_BIRTH": 1,
    "MRN": 1
  },
  "total_redactions": 16
}
```

---

## Security

- Flask bound to `127.0.0.1` — not accessible from the network
- Session-based password authentication via `.env`
- Temporary files deleted immediately after processing
- FileVault full-disk encryption on production Mac Mini
- Download endpoint validates all paths stay within `output_docs/`

---

## Known Issues

- **Split `[PATIENT NAME]` labels** — when individual name variants match separately on the same line, each gets its own redaction box instead of one merged box. Rect-merging fix is next.
- **"Re: , DOB , MRN" label residue** — field labels remain visible after their values are redacted on page 1. PHI values are correctly removed; this is cosmetic only.

---

## Roadmap

- [ ] Rect-merging fix for split `[PATIENT NAME]` labels
- [ ] All 18 HIPAA Safe Harbor identifiers
- [ ] Offline LLM layer (Qwen / Granite via Ollama) for semantic PHI detection
- [ ] Folder batch processing
- [ ] User-selectable redaction mode in the UI
- [ ] Cross-platform installer (Mac + Windows)
- [ ] RAG on de-identified document corpus
````