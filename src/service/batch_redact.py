"""
batch_redact.py
===============
Batch de-identification — process an entire folder of PDFs and DOCXs.

Usage:
    python batch_redact.py --input ./input_docs --output ./output_docs
    python batch_redact.py --input ./input_docs --output ./output_docs --mode blackbox
    python batch_redact.py --input ./input_docs --output ./output_docs --recursive
"""

import argparse
import sys
import json
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.engine.pdf_redactor import redact_pdf
from src.engine.redactor import redact_docx

SUPPORTED = {".pdf", ".docx"}


def batch_redact(input_dir: Path, output_dir: Path,
                 mode: str = "labeled", recursive: bool = False) -> dict:

    output_dir.mkdir(parents=True, exist_ok=True)

    pattern = "**/*" if recursive else "*"
    all_files = [
        f for f in input_dir.glob(pattern)
        if f.is_file() and f.suffix.lower() in SUPPORTED
    ]

    if not all_files:
        print(f"  No PDF or DOCX files found in {input_dir}")
        return {}

    total    = len(all_files)
    ok       = 0
    errors   = []
    results  = []
    t_start  = time.time()

    print(f"\n🏥 ClearPHI Batch Redaction")
    print(f"   Input:  {input_dir.resolve()}")
    print(f"   Output: {output_dir.resolve()}")
    print(f"   Mode:   {mode}")
    print(f"   Files:  {total} ({sum(1 for f in all_files if f.suffix == '.pdf')} PDF, "
          f"{sum(1 for f in all_files if f.suffix == '.docx')} DOCX)")
    print()

    for i, f in enumerate(sorted(all_files), 1):
        prefix = f"  [{i:03d}/{total}]"
        try:
            if f.suffix.lower() == ".pdf":
                result = redact_pdf(
                    str(f),
                    document_id=f.stem,
                    mode=mode,
                    output_dir=str(output_dir),
                )
            else:
                result = redact_docx(
                    str(f),
                    document_id=f.stem,
                    output_dir=str(output_dir),
                )

            total_redactions = result["total_redactions"]
            name_found       = result["patient_name_discovered"]
            print(f"{prefix} ✅ {f.name:<45} "
                  f"{total_redactions:>4} redactions  |  {name_found}")
            results.append(result)
            ok += 1

        except Exception as e:
            print(f"{prefix} ❌ {f.name:<45} ERROR: {e}")
            errors.append({"file": str(f), "error": str(e)})

    elapsed = time.time() - t_start

    # ── Summary ──────────────────────────────────────────────
    print()
    print("=" * 70)
    print(f"  ✅ Processed:  {ok}/{total} files  ({elapsed:.1f}s)")
    if errors:
        print(f"  ❌ Errors:     {len(errors)}")
        for e in errors:
            print(f"     {Path(e['file']).name}: {e['error']}")

    if results:
        # Aggregate entity counts across all files
        totals = {}
        for r in results:
            for k, v in r.get("entity_counts", {}).items():
                totals[k] = totals.get(k, 0) + v

        print()
        print("  Redaction summary (all files):")
        for entity, count in sorted(totals.items(), key=lambda x: -x[1]):
            if count > 0:
                print(f"    {entity:<25} {count}")

    print("=" * 70)

    # ── Batch audit log ──────────────────────────────────────
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    ts       = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"{ts}_batch_redaction_log.json"
    with open(log_path, "w", encoding="utf-8") as lf:
        json.dump({
            "timestamp":   datetime.utcnow().isoformat() + "Z",
            "input_dir":   str(input_dir.resolve()),
            "output_dir":  str(output_dir.resolve()),
            "mode":        mode,
            "total_files": total,
            "processed":   ok,
            "errors":      errors,
            "files":       results,
        }, lf, indent=2)
    print(f"\n  Audit log: {log_path}")
    print()

    return {"ok": ok, "total": total, "errors": errors, "results": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ClearPHI Batch De-identification"
    )
    parser.add_argument("--input",  required=True,
                        help="Folder containing documents to redact")
    parser.add_argument("--output", required=True,
                        help="Folder to write redacted documents to")
    parser.add_argument("--mode",   default="labeled",
                        choices=["labeled", "blackbox", "highlight"],
                        help="Redaction mode (default: labeled)")
    parser.add_argument("--recursive", action="store_true",
                        help="Recurse into subfolders")

    args = parser.parse_args()

    batch_redact(
        input_dir  = Path(args.input),
        output_dir = Path(args.output),
        mode       = args.mode,
        recursive  = args.recursive,
    )