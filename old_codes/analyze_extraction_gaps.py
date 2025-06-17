import json
import re
from pathlib import Path

def analyze_extraction_results():
    """Analyze the extraction results to understand why some schedules had no data."""
    
    # Load the raw results
    with open("data/output/payment_schedules.json", "r") as f:
        results = json.load(f)
    
    # Analyze each schedule
    print("=== EXTRACTION ANALYSIS ===\n")
    
    empty_schedules = []
    filled_schedules = []
    
    for i, schedule in enumerate(results["payment_schedules"]):
        hierarchy = schedule["hierarchy"]
        fields = schedule["payment_fields"]
        
        # Check if any field has a value
        has_data = any(field["value"] for field in fields)
        
        if has_data:
            filled_schedules.append((i, schedule))
        else:
            empty_schedules.append((i, schedule))
    
    print(f"Total schedules: {len(results['payment_schedules'])}")
    print(f"Schedules with data: {len(filled_schedules)}")
    print(f"Empty schedules: {len(empty_schedules)}\n")
    
    # Analyze patterns in empty vs filled schedules
    print("=== SCHEDULES WITH DATA ===")
    for idx, schedule in filled_schedules:
        h = schedule["hierarchy"]
        print(f"\nSchedule {idx + 1}:")
        print(f"  LOB: {h['line_of_business']}")
        print(f"  Provider: {h['provider_type']}")
        print(f"  Service: {h['service_type']}")
        print(f"  Plan: {h['plan_type']}")
        
        # Show what was extracted
        for field in schedule["payment_fields"]:
            if field["value"]:
                print(f"  {field['data_point_name']}: {field['value'][:50]}...")
    
    print("\n=== EMPTY SCHEDULES ===")
    hierarchy_patterns = {}
    
    for idx, schedule in empty_schedules:
        h = schedule["hierarchy"]
        print(f"\nSchedule {idx + 1}:")
        print(f"  LOB: {h['line_of_business']}")
        print(f"  Provider: {h['provider_type']}")
        print(f"  Service: {h['service_type']}")
        print(f"  Plan: {h['plan_type']}")
        
        # Track patterns
        key = f"{h['line_of_business']}|{h['service_type']}"
        hierarchy_patterns[key] = hierarchy_patterns.get(key, 0) + 1
    
    print("\n=== PATTERN ANALYSIS ===")
    print("\nEmpty schedule patterns:")
    for pattern, count in hierarchy_patterns.items():
        print(f"  {pattern}: {count} occurrences")
    
    # Check for duplicates
    print("\n=== DUPLICATE ANALYSIS ===")
    hierarchy_combos = {}
    for i, schedule in enumerate(results["payment_schedules"]):
        h = schedule["hierarchy"]
        key = f"{h['line_of_business']}|{h['provider_type']}|{h['ip_op']}|{h['service_type']}|{h['plan_type']}"
        if key not in hierarchy_combos:
            hierarchy_combos[key] = []
        hierarchy_combos[key].append(i + 1)
    
    duplicates = {k: v for k, v in hierarchy_combos.items() if len(v) > 1}
    if duplicates:
        print("\nDuplicate hierarchies found:")
        for combo, indices in duplicates.items():
            print(f"  {combo}")
            print(f"    Schedules: {indices}")
    else:
        print("\nNo duplicate hierarchies found.")
    
    return empty_schedules, filled_schedules


def check_document_sections():
    """Check what's actually in the document sections that were identified."""
    doc_path = Path("data/example_document.md")
    with open(doc_path, "r") as f:
        document = f.read()
    
    print("\n=== COMPENSATION SCHEDULE LOCATIONS ===")
    
    # Find all occurrences of compensation-related headers
    comp_patterns = [
        r'COMPENSATION SCHEDULE',
        r'EXHIBIT \d+\s*\n.*COMPENSATION',
        r'Attachment [A-C].*EXHIBIT'
    ]
    
    for pattern in comp_patterns:
        matches = list(re.finditer(pattern, document, re.IGNORECASE))
        if matches:
            print(f"\nPattern '{pattern}' found {len(matches)} times:")
            for match in matches:
                # Get line number
                line_num = document[:match.start()].count('\n') + 1
                # Get surrounding context
                start = max(0, match.start() - 100)
                end = min(len(document), match.end() + 200)
                context = document[start:end].replace('\n', ' ')
                print(f"  Line {line_num}: ...{context}...")


if __name__ == "__main__":
    print("Analyzing extraction gaps...\n")
    empty_schedules, filled_schedules = analyze_extraction_results()
    check_document_sections() 