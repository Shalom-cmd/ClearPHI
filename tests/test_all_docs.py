import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.engine.redactor import redact_docx

docs = [
    'input_docs/discharge_summary.docx',
    'input_docs/lab_report.docx',
    'input_docs/referral_letter.docx',
    'input_docs/edge_cases.docx',
    'input_docs/sample_patient_note.docx',
]

for path in docs:
    result = redact_docx(path, os.path.basename(path))
    name = result['patient_name_discovered']
    counts = result['entity_counts']
    total = result['total_redactions']
    print(f"\n{os.path.basename(path)}")
    print(f"  Name found : {name}")
    print(f"  Counts     : {counts}")
    print(f"  Total      : {total}")