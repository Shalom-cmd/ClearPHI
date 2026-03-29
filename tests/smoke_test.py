import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.engine.deid import deidentify_text

test = (
    "Patient:DOE, JANE K| DOB: 03/22/1975 | SSN: 987-65-4321 | "
    "MRN: MRN#456789 | NPI:1234567890 | "
    "Phone: 555-867-5309 | Fax: 555-867-5310 | "
    "Email: jane.doe@hospital.org | IP: 192.168.1.50 | "
    "Address: 123 Main St, Springfield, 90210 | "
    "Insurance: Member ID: ABC123456 | "
    "VIN: 1HGBH41JXMN109186 | Serial #: SN: ABC123XYZ789 | "
    "Age: 93 years old"
)

result = deidentify_text(test, document_id="hipaa_full_test")

print("\n--- REDACTED TEXT ---")
print(result["redacted_text"])
print("\n--- ENTITY COUNTS ---")
for entity, count in sorted(result["entity_counts"].items()):
    print(f"  {entity}: {count}")
print(f"\nTotal redactions: {result['total_redactions']}")