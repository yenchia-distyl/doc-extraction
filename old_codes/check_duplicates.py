#!/usr/bin/env python3

import json
from collections import defaultdict

def analyze_duplicates():
    """Analyze the comprehensive results for actual duplicates vs legitimate variations."""
    
    with open('data/output/payment_schedules_comprehensive.json', 'r') as f:
        data = json.load(f)
    
    print("=== DUPLICATE ANALYSIS ===")
    print(f"Total payment schedules: {len(data['payment_schedules'])}")
    print()
    
    # Group by source file
    by_file = defaultdict(list)
    for entry in data['payment_schedules']:
        by_file[entry['source_file']].append(entry)
    
    print("Entries per file:")
    for filename, entries in by_file.items():
        print(f"  {filename}: {len(entries)} entries")
    print()
    
    # Focus on the file with most entries
    max_file = max(by_file.keys(), key=lambda k: len(by_file[k]))
    max_entries = by_file[max_file]
    
    print(f"=== DETAILED ANALYSIS: {max_file} ===")
    print(f"Total combinations: {len(max_entries)}")
    print()
    
    # Check for actual content differences
    print("=== UNIQUENESS ANALYSIS ===")
    
    # Compare citations for Lesser of Logic field
    citations = []
    for entry in max_entries:
        if entry['payment_fields'] and entry['payment_fields'][0]['citation']:
            citations.append(entry['payment_fields'][0]['citation'])
    
    unique_citations = set(citations)
    print(f"Total citations for 'Lesser of Logic': {len(citations)}")
    print(f"Unique citations: {len(unique_citations)}")
    
    print("\nUnique citation texts:")
    for i, citation in enumerate(unique_citations, 1):
        print(f"{i}. {citation}")
        print()
    
    # Check reimbursement methodology variations
    reimb_methods = []
    for entry in max_entries:
        if len(entry['payment_fields']) > 2 and entry['payment_fields'][2]['value']:
            reimb_methods.append(entry['payment_fields'][2]['value'])
    
    unique_reimb = set(reimb_methods)
    print(f"Total 'Reimb Methodology' values: {len(reimb_methods)}")
    print(f"Unique 'Reimb Methodology' values: {len(unique_reimb)}")
    
    print("\nUnique reimbursement methodologies:")
    for i, method in enumerate(unique_reimb, 1):
        print(f"{i}. {method}")
        print()
    
    # Calculate duplication ratio
    total_extractions = len(max_entries)
    unique_payment_info = len(unique_citations)
    duplication_ratio = total_extractions / unique_payment_info if unique_payment_info > 0 else 0
    
    print(f"=== DUPLICATION METRICS ===")
    print(f"Total extractions: {total_extractions}")
    print(f"Unique payment information: {unique_payment_info}")
    print(f"Duplication ratio: {duplication_ratio:.1f}x")
    
    if duplication_ratio > 2:
        print("⚠️  HIGH DUPLICATION DETECTED")
        print("   Same payment info extracted multiple times for different combinations")
        print("   This suggests the payment terms are file-level, not service/plan specific")
    else:
        print("✅ LOW DUPLICATION")
        print("   Most combinations have unique payment information")
    
    # Analyze across all files
    print(f"\n=== CROSS-FILE ANALYSIS ===")
    total_schedules = len(data['payment_schedules'])
    
    # Count unique citation texts across all files
    all_citations = set()
    for entry in data['payment_schedules']:
        if entry['payment_fields'] and entry['payment_fields'][0]['citation']:
            all_citations.add(entry['payment_fields'][0]['citation'])
    
    overall_duplication = total_schedules / len(all_citations) if all_citations else 0
    print(f"Total payment schedules across all files: {total_schedules}")
    print(f"Unique payment citations across all files: {len(all_citations)}")
    print(f"Overall duplication ratio: {overall_duplication:.1f}x")

if __name__ == "__main__":
    analyze_duplicates() 