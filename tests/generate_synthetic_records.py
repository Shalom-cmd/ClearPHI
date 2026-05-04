"""
generate_synthetic_records.py
==============================
CLI entry point for synthetic patient record generation and DEID scoring.

Usage:
    # Generate 30 records (all 6 layouts, PDF + DOCX)
    python tests/generate_synthetic_records.py --count 30 --formats pdf docx

    # Generate text only for quick testing
    python tests/generate_synthetic_records.py --count 10 --formats txt

    # Score ClearPHI output against the manifest
    python tests/generate_synthetic_records.py --score \\
        --manifest ./tests/test_records/manifest.csv \\
        --deid-outdir ./tests/deid_output
"""

import argparse
import csv
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.generators.phi_data import generate_phi
from tests.generators.layout_renderers import LAYOUT_RENDERERS
from tests.generators.pdf_writers import PDF_WRITERS
from tests.generators.docx_writers import DOCX_WRITERS
from tests.generators.scorer import score_deid_output, print_score_report


# Six layouts — cycles through all of them
LAYOUT_CYCLE = [
    "plain_note",
    "table_labs",
    "discharge_summary",
    "footer_heavy",
    "referral_letter",
    "lab_email",
]

# All PHI fields written to the manifest for ground-truth scoring
MANIFEST_PHI_FIELDS = [
    "patient_name", "first_name", "last_name", "dob", "mrn",
    "ssn", "phone", "fax", "address", "email", "insurance_id",
    "portal_url", "last_login_ip", "visit_date", "provider_name", "facility",
]


def generate_records(count: int, formats: list, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    manifest_path = outdir / "manifest.csv"
    manifest_rows = []

    print(f"\n🏥 Generating {count} synthetic patient records "
          f"({', '.join(f.upper() for f in formats)})...")
    print(f"   Output: {outdir.resolve()}\n")

    for i in range(count):
        phi = generate_phi()
        layout = LAYOUT_CYCLE[i % len(LAYOUT_CYCLE)]
        record_id = f"rec_{i+1:04d}"
        generated_files = []

        if "txt" in formats:
            txt_path = outdir / f"{record_id}_{layout}.txt"
            txt_path.write_text(LAYOUT_RENDERERS[layout](phi), encoding="utf-8")
            generated_files.append(txt_path.name)

        if "pdf" in formats:
            pdf_path = outdir / f"{record_id}_{layout}.pdf"
            try:
                PDF_WRITERS[layout](phi, str(pdf_path))
                generated_files.append(pdf_path.name)
            except Exception as e:
                print(f"  ⚠️  PDF error {record_id}: {e}")

        if "docx" in formats:
            docx_path = outdir / f"{record_id}_{layout}.docx"
            try:
                DOCX_WRITERS[layout](phi, str(docx_path))
                generated_files.append(docx_path.name)
            except Exception as e:
                print(f"  ⚠️  DOCX error {record_id}: {e}")

        row = {
            "record_id": record_id,
            "layout": layout,
            "files": "|".join(generated_files),
        }
        for field in MANIFEST_PHI_FIELDS:
            row[field] = phi.get(field, "")
        row["medications"] = "|".join(f"{m} {d}" for m, d, _ in phi["medications"])
        manifest_rows.append(row)

        print(f"  [{i+1:03d}/{count}] {record_id} | {layout:<20} | "
              f"{', '.join(generated_files)}")

    fieldnames = ["record_id", "layout", "files"] + MANIFEST_PHI_FIELDS + ["medications"]
    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(manifest_rows)

    print(f"\n✅ Done! {count} records written.")
    print(f"   Manifest: {manifest_path.resolve()}")
    print(f"\n📋 Layout distribution:")
    for layout in LAYOUT_CYCLE:
        n = sum(1 for r in manifest_rows if r["layout"] == layout)
        print(f"   {layout:<25} {n} records")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Synthetic Patient Record Generator for ClearPHI Testing"
    )
    parser.add_argument("--count", type=int, default=30,
                        help="Number of records to generate (default: 30)")
    parser.add_argument("--formats", nargs="+", default=["pdf", "docx"],
                        choices=["pdf", "txt", "docx"],
                        help="Output formats (default: pdf docx)")
    parser.add_argument("--outdir", type=str, default="./tests/test_records",
                        help="Output directory")
    parser.add_argument("--score", action="store_true",
                        help="Score DEID output against manifest")
    parser.add_argument("--manifest", type=str,
                        help="Path to manifest.csv (for --score)")
    parser.add_argument("--deid-outdir", type=str,
                        help="Path to de-identified output directory (for --score)")
    parser.add_argument("--verbose", action="store_true",
                        help="Show per-file results during scoring")

    args = parser.parse_args()

    if args.score:
        if not args.manifest or not args.deid_outdir:
            parser.error("--score requires --manifest and --deid-outdir")
        score = score_deid_output(
            Path(args.manifest),
            Path(args.deid_outdir),
            verbose=args.verbose,
        )
        print_score_report(score)
    else:
        generate_records(
            count=args.count,
            formats=args.formats,
            outdir=Path(args.outdir),
        )