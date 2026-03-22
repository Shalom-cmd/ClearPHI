from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig
from datetime import datetime
import json
import os
import re


# ─────────────────────────────────────────────
# CUSTOM RECOGNIZERS — filling HIPAA gaps
# ─────────────────────────────────────────────

# 1. SSN — catches XXX-XX-XXXX and 9-digit no-dash
ssn_recognizer = PatternRecognizer(
    supported_entity="US_SSN",
    patterns=[
        Pattern(name="ssn_dashes", regex=r"\b\d{3}-\d{2}-\d{4}\b", score=0.95),
        Pattern(name="ssn_no_dashes", regex=r"\b\d{9}\b", score=0.5),
    ]
)

# 2. ZIP codes — 5 digit and ZIP+4
zip_recognizer = PatternRecognizer(
    supported_entity="ZIP_CODE",
    patterns=[
        Pattern(name="zip_plus4", regex=r"\b\d{5}-\d{4}\b", score=0.9),
        Pattern(name="zip_5digit", regex=r"\b\d{5}\b", score=0.5),
    ]
)

# 3. Medical Record Numbers
mrn_recognizer = PatternRecognizer(
    supported_entity="MEDICAL_RECORD_NUMBER",
    patterns=[
        Pattern(name="mrn_labeled", regex=r"\bMRN[:\s#]*\d{4,10}\b", score=0.95),
        Pattern(name="mrn_prefix", regex=r"\b(MR|MRN|ID)[:\s]?\d{5,10}\b", score=0.85),
    ]
)

# 4. Health plan / beneficiary numbers (Medicare, insurance IDs)
beneficiary_recognizer = PatternRecognizer(
    supported_entity="BENEFICIARY_NUMBER",
    patterns=[
        # Correct CMS MBI format: 1EG4-TE5-MK72
        Pattern(
            name="medicare_mbi_dashes",
            regex=r"\b[1-9][A-Z]{2}\d-[A-Z]{2}\d-[A-Z]{2}\d{2}\b",
            score=0.95
        ),
        # MBI without dashes: 1EG4TE5MK72
        Pattern(
            name="medicare_mbi_plain",
            regex=r"\b[1-9][A-Z]{2}\d[A-Z]{2}\d[A-Z]{2}\d{2}\b",
            score=0.9
        ),
        Pattern(name="hicn", regex=r"\b(HIC|HICN|MBI)[:\s]?[A-Z0-9\-]{9,15}\b", score=0.9),
        Pattern(name="insurance_id", regex=r"\b(Member\s*ID|Policy\s*#|Subscriber\s*ID|Plan\s*ID)[:\s]*[A-Z0-9\-]{6,15}\b", score=0.85),
    ]
)

# 5. Account numbers
account_recognizer = PatternRecognizer(
    supported_entity="ACCOUNT_NUMBER",
    patterns=[
        Pattern(name="account_labeled", regex=r"\b(Acct|Account|Acct\.?)[:\s#]*\d{6,17}\b", score=0.85),
    ]
)

# 6. Certificate and license numbers (non-medical)
license_recognizer = PatternRecognizer(
    supported_entity="LICENSE_NUMBER",
    patterns=[
        Pattern(name="license_labeled", regex=r"\b(License|Lic\.?|Cert\.?|Certificate)[:\s#]*[A-Z0-9\-]{5,15}\b", score=0.85),
    ]
)

# 7. VINs — 17 character vehicle identifiers
vin_recognizer = PatternRecognizer(
    supported_entity="VIN_NUMBER",
    patterns=[
        Pattern(name="vin_labeled", regex=r"\bVIN[:\s]*[A-HJ-NPR-Z0-9]{17}\b", score=0.95),
        Pattern(name="vin_plain", regex=r"\b[A-HJ-NPR-Z0-9]{17}\b", score=0.75),
    ]
)

# 8. Device identifiers and serial numbers
device_recognizer = PatternRecognizer(
    supported_entity="DEVICE_IDENTIFIER",
    patterns=[
        Pattern(name="serial_labeled", regex=r"\b(Serial\s*#|Serial\s*No\.?|Device\s*ID|SN)[:\s]*[A-Z0-9][A-Z0-9\-]{4,19}\b", score=0.9),
        Pattern(name="dev_prefix", regex=r"\bDEV[-:][A-Z0-9\-]{4,20}\b", score=0.85),
        Pattern(name="imei", regex=r"\b\d{15}\b", score=0.6),
    ]
)

# 9. Fax numbers
fax_recognizer = PatternRecognizer(
    supported_entity="FAX_NUMBER",
    patterns=[
        Pattern(name="fax_labeled", regex=r"\b(Fax|FAX|Fax\s*#)[:\s]*[\+]?[\d\s\-\(\)]{7,15}\b", score=0.9),
    ]
)

# 10. NPI — National Provider Identifier
npi_recognizer = PatternRecognizer(
    supported_entity="NPI_NUMBER",
    patterns=[
        Pattern(name="npi_labeled", regex=r"\bNPI[:\s]?\d{10}\b", score=0.95),
        Pattern(name="npi_plain", regex=r"\b\d{10}\b", score=0.4),
    ]
)

# 11. Ages over 90 — HIPAA requires these be generalized
age_recognizer = PatternRecognizer(
    supported_entity="AGE_OVER_90",
    patterns=[
        Pattern(name="age_over_90", regex=r"\b(9[1-9]|[1-9]\d{2,})\s*[-]?\s*(year|yr)s?\s*[-]?\s*old\b", score=0.9),
        Pattern(name="age_over_90_short", regex=r"\bage[:\s]*(9[1-9]|[1-9]\d{2,})\b", score=0.85),
    ]
)


# ─────────────────────────────────────────────
# ENGINE SETUP
# ─────────────────────────────────────────────

analyzer = AnalyzerEngine()

for recognizer in [
    ssn_recognizer,
    zip_recognizer,
    mrn_recognizer,
    beneficiary_recognizer,
    account_recognizer,
    license_recognizer,
    vin_recognizer,
    device_recognizer,
    fax_recognizer,
    npi_recognizer,
    age_recognizer,
]:
    analyzer.registry.add_recognizer(recognizer)

anonymizer = AnonymizerEngine()

HIPAA_ENTITIES = [
    # Built-in Presidio
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "US_SSN",
    "US_DRIVER_LICENSE",
    "MEDICAL_LICENSE",
    "URL",
    "IP_ADDRESS",
    "DATE_TIME",
    "LOCATION",
    "US_BANK_NUMBER",
    "CREDIT_CARD",
    "CRYPTO",
    "IBAN_CODE",
    "NRP",
    "AGE",
    "US_PASSPORT",
    "US_ITIN",
    # Custom
    "ZIP_CODE",
    "MEDICAL_RECORD_NUMBER",
    "BENEFICIARY_NUMBER",
    "ACCOUNT_NUMBER",
    "LICENSE_NUMBER",
    "VIN_NUMBER",
    "DEVICE_IDENTIFIER",
    "FAX_NUMBER",
    "NPI_NUMBER",
    "AGE_OVER_90",
]


# ─────────────────────────────────────────────
# FALSE POSITIVE FILTERS
# ─────────────────────────────────────────────

# Ages under 90 — HIPAA Safe Harbor: only ages 90+ are PHI
AGE_PATTERN = re.compile(
    r'\b(\d{1,2})\s*[-]?\s*(year|yr)s?\s*[-]?\s*old\b',
    re.IGNORECASE
)

# Clinical durations — not identifying dates
DURATION_PATTERN = re.compile(
    r'\b(x\s*)?\d+\s*[-]?\s*(day|days|week|weeks|wk|wks|month|months|mo|mos|'
    r'year|years|yr|yrs|hr|hrs|hour|hours|min|mins|minute|minutes)\b'
    r'|'
    r'\b(today|tonight|yesterday|now|currently|ongoing|chronic|acute|recent|immediate)\b'
    r'|'
    r'\bx\s*\d+\s*(wk|wks|yr|yrs|mo|mos|days|weeks|months|years)\b',
    re.IGNORECASE
)

# EKG / cardiology lead names that look like locations
EKG_LEADS = re.compile(
    r'\b(aVF|aVR|aVL|V1|V2|V3|V4|V5|V6)\b'
)

# Medical abbreviations that Presidio misreads as locations or other PHI
MEDICAL_ABBREVIATIONS = re.compile(
    r'^('
    # EKG / vitals
    r'ST|T-wave|T wave|U wave|PR|QT|QRS|RBBB|LBBB|STEMI|NSTEMI|'
    r'MD|DO|RN|NP|PA|PhD|DNP|CRNA|CNM|CNS|'
    # Vitals & measurements
    r'BP|HR|RR|O2|SpO2|FiO2|PEEP|GCS|BMI|BSA|Temp|Wt|Ht|'
    # Routes of administration
    r'IM|IV|SC|PO|SQ|SL|'
    # Care settings
    r'ED|ICU|CCU|NICU|PICU|OR|ER|OR|PACU|'
    # Clinical shorthand
    r'Pt|pt|Hx|hx|Dx|dx|Rx|rx|Sx|sx|Tx|tx|Cx|'
    r'c/o|s/p|h/o|r/o|w/u|f/u|y/o|y\.o\.|'
    # Diagnoses
    r'HTN|DM|CAD|CHF|COPD|CKD|AKI|CVA|TIA|MI|PE|DVT|AFib|VTach|VFib|'
    r'GERD|UGIB|LGIB|IBD|IBS|UTI|URI|URTI|LRTI|PNA|'
    # Imaging & procedures
    r'MRI|CT|CTA|CXR|EKG|ECG|EEG|EMG|PFT|ABG|TTE|TEE|'
    # Labs
    r'CBC|BMP|CMP|LFT|LFTs|UA|UCx|BCx|'
    r'WBC|RBC|Hgb|Hct|MCV|MCH|PLT|INR|PTT|PT|'
    r'Na|K|Cl|CO2|BUN|Cr|Ca|Mg|Phos|Glu|Alb|'
    r'HbA1c|TSH|T3|T4|PSA|CEA|AFP|'
    # Units
    r'mg|mL|mcg|kg|dL|mmHg|bpm|mmol|mEq|IU|units|'
    # Anatomical directions used clinically
    r'L|R|Bil|bilat|bilateral|ant|post|lat|med|sup|inf|'
    r')$',
    re.IGNORECASE
)


def _is_age_under_90(text: str, start: int, end: int) -> bool:
    """Ages under 90 are not PHI under HIPAA Safe Harbor."""
    snippet = text[max(0, start - 5):end + 5]
    match = AGE_PATTERN.search(snippet)
    if match:
        try:
            age = int(match.group(1))
            return age < 90
        except ValueError:
            return False
    return False


def _is_clinical_duration(text: str, start: int, end: int) -> bool:
    """Clinical durations like '6 weeks' or '12 months' are not identifying dates."""
    snippet = text[start:end].strip()
    return bool(DURATION_PATTERN.fullmatch(snippet))


def _is_medical_abbreviation(text: str, start: int, end: int) -> bool:
    """
    Returns True if the match is a medical abbreviation misread as a location.
    Handles:
      - Standalone abbreviations (ST, BP, IV, etc.)
      - ST followed by cardiac context words (elevation, depression, segment)
      - EKG lead names (aVF, V1-V6)
    """
    snippet = text[start:end].strip()

    # Direct abbreviation match
    if MEDICAL_ABBREVIATIONS.match(snippet):
        return True

    # EKG lead names
    if EKG_LEADS.fullmatch(snippet):
        return True

    # ST + cardiac context: "ST elevation", "ST depression", "ST segment", "ST changes"
    if re.match(r'^ST$', snippet, re.IGNORECASE):
        # Look at the 30 chars after the match for cardiac context
        context_after = text[end:end + 30].lower()
        cardiac_context = [
            'elevation', 'depression', 'segment', 'change',
            'abnormality', 'flattening', 'inversion', 'wave'
        ]
        if any(word in context_after for word in cardiac_context):
            return True

    return False


# ─────────────────────────────────────────────
# CORE FUNCTIONS
# ─────────────────────────────────────────────

def deidentify_text(text: str, document_id: str = "unknown") -> dict:
    """
    Accepts raw extracted text.
    Returns redacted text, entity counts, full redaction report,
    and an audit trail of values intentionally preserved.
    """
    results = analyzer.analyze(
        text=text,
        entities=HIPAA_ENTITIES,
        language="en"
    )

    filtered_results = []
    skipped = []

    for result in results:
        value = text[result.start:result.end]

        # 1. Preserve ages under 90
        if result.entity_type == "DATE_TIME" and _is_age_under_90(text, result.start, result.end):
            skipped.append({
                "entity_type": "AGE_PRESERVED",
                "value": value,
                "reason": "Age under 90 — preserved per HIPAA Safe Harbor"
            })
            continue

        # 2. Preserve clinical durations
        if result.entity_type == "DATE_TIME" and _is_clinical_duration(text, result.start, result.end):
            skipped.append({
                "entity_type": "DURATION_PRESERVED",
                "value": value,
                "reason": "Clinical duration — not an identifying date"
            })
            continue

        # 3. Preserve medical abbreviations misread as locations
        if result.entity_type == "LOCATION" and _is_medical_abbreviation(text, result.start, result.end):
            skipped.append({
                "entity_type": "MEDICAL_ABBREV_PRESERVED",
                "value": value,
                "reason": "Medical abbreviation — not a location identifier"
            })
            continue

        filtered_results.append(result)

    operators = {
        entity: OperatorConfig("replace", {"new_value": f"[{entity}]"})
        for entity in HIPAA_ENTITIES
    }

    anonymized = anonymizer.anonymize(
        text=text,
        analyzer_results=filtered_results,
        operators=operators
    )

    report = []
    entity_counts = {}

    for result in filtered_results:
        entity_type = result.entity_type
        original_value = text[result.start:result.end]
        report.append({
            "entity_type": entity_type,
            "original_value": original_value,
            "start": result.start,
            "end": result.end,
            "score": round(result.score, 3)
        })
        entity_counts[entity_type] = entity_counts.get(entity_type, 0) + 1

    return {
        "document_id": document_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "redacted_text": anonymized.text,
        "entity_counts": entity_counts,
        "total_redactions": len(filtered_results),
        "redaction_report": report,
        "preserved_values": skipped
    }


def save_redaction_log(result: dict, log_dir: str = "logs") -> str:
    """
    Saves the full redaction report as a JSON audit log.
    Returns the path to the saved file.
    """
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    doc_id = result.get("document_id", "unknown").replace(" ", "_")
    log_filename = f"{timestamp}_{doc_id}_redaction_log.json"
    log_path = os.path.join(log_dir, log_filename)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    return log_path