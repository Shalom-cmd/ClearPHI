"""
scorer.py
=========
Scores de-identified output files against the ground-truth manifest CSV.
Prints per-PHI-field recall and flags any leaked identifiers.
"""

import csv
import re
from pathlib import Path


# ─────────────────────────────────────────────
# FIELD REGISTRY
# ─────────────────────────────────────────────

PHI_FIELDS = {
    # Group 1
    "patient_name":  "patient_name",
    "first_name":    "first_name",
    "last_name":     "last_name",
    "dob":           "dob",
    "mrn":           "mrn",
    "ssn":           "ssn",
    "phone":         "phone",
    "email":         "email",
    "insurance_id":  "insurance_id",
    "provider_name": "provider_name",
    "last_login_ip": "last_login_ip",
    # Group 2
    "visit_date":    "visit_date",   # ALL_DATE coverage
    "address":       "address",      # ZIP coverage (ZIP extracted from full address)
}

# Fields where the FULL formatted value must appear as a substring.
# Splitting structured identifiers on punctuation produces short numeric
# tokens that match incidentally throughout clinical documents.
EXACT_MATCH_FIELDS = {
    "ssn", "phone", "last_login_ip", "dob", "mrn",
    "email", "insurance_id", "visit_date",
}

# Minimum token length for name-field tokenized matching.
MIN_NAME_TOKEN = 4


# ─────────────────────────────────────────────
# MATCHING HELPERS
# ─────────────────────────────────────────────

def _extract_zip(address: str) -> str | None:
    """Pull the first 5-digit ZIP out of an address string."""
    m = re.search(r'\b(\d{5})(?:-\d{4})?\b', address)
    return m.group(1) if m else None


def _is_leaked(field: str, val: str, text: str) -> bool:
    """
    Return True if val appears to still be present in text.

    Strategy by field type
    ──────────────────────
    address     → extract ZIP only; check that 5-digit string as substring.
                  We only redact ZIPs, not whole addresses.
    exact fields → check full formatted value as case-insensitive substring.
    name fields  → tokenize on whitespace/comma; flag if any token >=
                   MIN_NAME_TOKEN chars is still present.
    """
    val = val.strip()
    if not val:
        return False

    # address: check if the ZIP (most unique part) is still present.
    # The full address string may vary in whitespace/formatting in the
    # text layer, but the ZIP digits are always distinct.
    if field == "address":
        zip_code = _extract_zip(val)
        if not zip_code:
            return False
        return zip_code in text

    # Structured identifiers: full-value substring match
    if field in EXACT_MATCH_FIELDS:
        return val.lower() in text

    # Name fields: token-based (split on whitespace + commas only)
    tokens = [
        t.strip().lower()
        for t in re.split(r"[\s,]+", val)
        if len(t.strip()) >= MIN_NAME_TOKEN
    ]
    if not tokens:
        return False
    return any(token in text for token in tokens)


# ─────────────────────────────────────────────
# SCORER
# ─────────────────────────────────────────────

def score_deid_output(manifest_path: Path, deid_outdir: Path,
                      verbose: bool = False) -> dict:
    """
    Compare de-identified output files against the manifest ground truth.

    Gracefully skips manifest columns that don't exist yet — backwards
    compatible with older manifests that predate visit_date / address.

    Returns:
        {
          "results": {"patient_name": {"checked": N, "leaked": M}, ...},
          "file_leaks": [("filename.pdf", ["field1", "field2"]), ...],
          "overall_recall": 0.97
        }
    """
    results       = {f: {"checked": 0, "leaked": 0} for f in PHI_FIELDS}
    file_leaks    = []
    total_checked = 0
    total_leaked  = 0

    with open(manifest_path, newline="", encoding="utf-8") as f:
        reader      = csv.DictReader(f)
        csv_columns = set(reader.fieldnames or [])

        for row in reader:
            for fname in row["files"].split("|"):
                deid_file = deid_outdir / fname
                if not deid_file.exists():
                    if verbose:
                        print(f"  MISSING: {fname}")
                    continue

                try:
                    text = deid_file.read_text(
                        encoding="utf-8", errors="ignore"
                    ).lower()
                except Exception:
                    text = ""

                file_leaks_this = []
                for field, label in PHI_FIELDS.items():
                    # Skip fields not present in this manifest version
                    if field not in csv_columns:
                        continue

                    val = row.get(field, "").strip()
                    if not val:
                        continue

                    results[field]["checked"] += 1
                    total_checked += 1

                    if _is_leaked(field, val, text):
                        results[field]["leaked"] += 1
                        total_leaked += 1
                        file_leaks_this.append(label)
                        if verbose:
                            print(f"  LEAK  {fname} [{field}]: {val!r}")

                if file_leaks_this:
                    file_leaks.append((fname, file_leaks_this))

    overall_recall = (
        1 - (total_leaked / total_checked) if total_checked > 0 else 1.0
    )

    return {
        "results":        results,
        "file_leaks":     file_leaks,
        "overall_recall": overall_recall,
    }


# ─────────────────────────────────────────────
# REPORT PRINTER
# ─────────────────────────────────────────────

def print_score_report(score: dict) -> None:
    """Pretty-print the scoring results to stdout."""
    results    = score["results"]
    file_leaks = score["file_leaks"]
    overall    = score["overall_recall"]

    GROUP1 = ["patient_name", "first_name", "last_name", "dob", "mrn",
              "ssn", "phone", "email", "insurance_id", "provider_name",
              "last_login_ip"]
    GROUP2 = ["visit_date", "address"]

    def _section(title, fields):
        rows = [(f, results[f]) for f in fields
                if f in results and results[f]["checked"] > 0]
        if not rows:
            return
        print(f"\n  {title}")
        print("  " + "-" * 58)
        for field, stats in rows:
            recall = 1 - (stats["leaked"] / stats["checked"])
            flag   = "⚠️ " if recall < 0.95 else "✅"
            note   = " (ZIP)" if field == "address" else ""
            print(f"  {flag} {field + note:<23} {stats['checked']:<10} "
                  f"{stats['leaked']:<10} {recall:.1%}")

    print("\n📊 DEID Scoring Results")
    print("=" * 62)
    print(f"  {'PHI Field':<25} {'Checked':<10} {'Leaked':<10} {'Recall':<10}")
    _section("GROUP 1", GROUP1)
    _section("GROUP 2", GROUP2)
    print("\n" + "-" * 62)
    overall_flag = "⚠️ " if overall < 0.95 else "✅"
    print(f"  {overall_flag} {'OVERALL':<23} {'':<10} {'':<10} {overall:.1%}")

    if file_leaks:
        print(f"\n⚠️  Files with leaked PHI ({len(file_leaks)}):")
        for fname, fields in file_leaks[:30]:
            print(f"   {fname}: {', '.join(fields)}")
        if len(file_leaks) > 30:
            print(f"   ... and {len(file_leaks) - 30} more")
    else:
        print("\n✅ No PHI leakage detected in checked files.")
    print()