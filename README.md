```markdown
# ClearPHI

A fully local, HIPAA-compliant de-identification service for clinical documents. Redacts patient name, date of birth, and MRN from DOCX and PDF files before research upload — no patient data ever leaves the machine.

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

## Architecture

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

---

## Stack

| Component | Technology |
|---|---|
| PDF redaction | PyMuPDF 1.27+ — in-place redaction annotations |
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
├── input_docs/
├── output_docs/
├── logs/
├── requirements.txt
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
launchctl stop com.eric.deid-service
launchctl start com.eric.deid-service
# UI at http://localhost:5001
```

---

## Redaction Modes

| Mode | Appearance | Use case |
|---|---|---|
| `labeled` | White box with `[PATIENT NAME]` | Default |
| `blackbox` | Solid black box | Maximum opacity |
| `highlight` | Yellow highlight | Review only — not for final sharing |

---

## PHI Detection

**Name** — discovered from first 2000 chars, expanded into 15+ variants (full name, ALL CAPS, Last/First comma, with/without middle initial, standalone first/last if 5+ chars).

**DOB** — all date formats after labels: `DOB`, `D.O.B.`, `Date of Birth`, `Birth Date`, `Birthdate`, `Born`.

**MRN** — 6+ label styles: `MRN`, `Medical Record Number`, `Medical Record No.`, `Record #`, `Patient ID`. Ignores Gleason scores, biopsy percentages, room numbers.

---

## Scanned PDF Support

Auto-detects image-only PDFs. Falls back to Tesseract OCR: renders at 300 DPI → word-level bounding boxes → coordinate mapping → redaction boxes at exact pixel locations. Takes 30–60 seconds per document.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Browser UI |
| `POST` | `/login` | Authenticate |
| `POST` | `/deidentify/upload` | Upload and redact |
| `GET` | `/deidentify/download?path=` | Download output |
| `GET` | `/health` | Health check |

---

## Known Issues

- **Split `[PATIENT NAME]` labels** — adjacent name variant matches each get their own box. Rect-merging fix is next.
- **"Re: , DOB , MRN" residue** — field labels remain after value redaction. Cosmetic only.

---

## Roadmap

- [ ] Rect-merging fix for split name labels
- [ ] All 18 HIPAA Safe Harbor identifiers
- [ ] Offline LLM (Qwen / Granite via Ollama) for semantic PHI detection
- [ ] Folder batch processing
- [ ] User-selectable redaction mode in UI
- [ ] Cross-platform installer (Mac + Windows)
- [ ] RAG on de-identified document corpus
```

Save that as `README.md` in your project root alongside `requirements.txt`, then include it in your commit.
