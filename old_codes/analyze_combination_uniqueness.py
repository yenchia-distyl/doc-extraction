#!/usr/bin/env python3

import json
from collections import defaultdict

def analyze_combination_uniqueness():
    """Analyze if different service/plan combinations have genuinely different payment information."""
    
    with open('data/output/payment_schedules_comprehensive.json', 'r') as f:
        data = json.load(f)
    
    print("=== COMBINATION UNIQUENESS ANALYSIS ===")
    print("Goal: Determine if different service/plan combinations have different payment terms")
    print()
    
    # Focus on the file with most entries (Medicaid EXHIBIT)
    medicaid_entries = [entry for entry in data['payment_schedules'] 
                       if entry['source_file'] == 'Attachment_A_Medicaid__EXHIBIT 1.md']
    
    print(f"Analyzing: Attachment_A_Medicaid__EXHIBIT 1.md")
    print(f"Total combinations extracted: {len(medicaid_entries)}")
    print()
    
    # Group by service type to see if payment terms vary by service
    by_service = defaultdict(list)
    for entry in medicaid_entries:
        service = entry['hierarchy']['service_type']
        by_service[service].append(entry)
    
    print("=== BY SERVICE TYPE ===")
    for service, entries in by_service.items():
        print(f"\n{service} ({len(entries)} plan combinations):")
        
        # Check if payment terms vary across plan types for this service
        lesser_of_values = set()
        reimb_short_values = set()
        
        for entry in entries:
            if entry['payment_fields']:
                # Lesser of rate (field 1)
                if len(entry['payment_fields']) > 1:
                    lesser_of_values.add(entry['payment_fields'][1]['value'])
                # Reimb methodology short (field 3)  
                if len(entry['payment_fields']) > 3:
                    reimb_short_values.add(entry['payment_fields'][3]['value'])
        
        print(f"  Plan types: {[e['hierarchy']['plan_type'] for e in entries]}")
        print(f"  Unique 'Lesser of Rate' values: {len(lesser_of_values)}")
        for val in lesser_of_values:
            print(f"    - {val}")
        print(f"  Unique 'Reimb Methodology short' values: {len(reimb_short_values)}")
        for val in reimb_short_values:
            print(f"    - {val}")
    
    print("\n" + "="*60)
    print("=== MEDICARE COMPARISON ===")
    
    # Now check Medicare to see if it shows service-specific rates
    medicare_entries = [entry for entry in data['payment_schedules'] 
                       if entry['source_file'] == 'Attachment_B_Medicare__EXHIBIT 1.md']
    
    print(f"Analyzing: Attachment_B_Medicare__EXHIBIT 1.md")
    print(f"Total combinations extracted: {len(medicare_entries)}")
    
    medicare_by_service = defaultdict(list)
    for entry in medicare_entries:
        service = entry['hierarchy']['service_type']
        medicare_by_service[service].append(entry)
    
    print("\nMedicare service-specific rates:")
    for service, entries in medicare_by_service.items():
        if entries:
            # Get the "Lesser of Rate" value for this service
            entry = entries[0]  # Take first entry for this service
            if len(entry['payment_fields']) > 1:
                rate = entry['payment_fields'][1]['value']
                print(f"  {service}: {rate}")
    
    print("\n" + "="*60)
    print("=== INTERPRETATION ===")
    
    # Check if we see service-specific rates in Medicare (which should have them)
    medicare_rates = set()
    for entry in medicare_entries:
        if len(entry['payment_fields']) > 1 and entry['payment_fields'][1]['value']:
            medicare_rates.add(entry['payment_fields'][1]['value'])
    
    print(f"Medicare shows {len(medicare_rates)} unique payment rates:")
    for rate in medicare_rates:
        print(f"  - {rate}")
    
    if len(medicare_rates) > 1:
        print("\n✅ LEGITIMATE SERVICE-SPECIFIC RATES DETECTED")
        print("   Medicare file shows different rates for different services")
        print("   This validates the combination approach")
    else:
        print("\n⚠️  POTENTIALLY FILE-LEVEL RATES")
        print("   Most rates appear to be file-level rather than service-specific")
    
    # Check for plan-specific variations within the same service
    print(f"\n=== PLAN-SPECIFIC VARIATIONS ===")
    
    # Pick one service from Medicaid and see if plans have different terms
    if 'Professional Services' in by_service:
        prof_entries = by_service['Professional Services']
        print(f"Professional Services across {len(prof_entries)} plan types:")
        
        for entry in prof_entries:
            plan = entry['hierarchy']['plan_type']
            if len(entry['payment_fields']) > 1:
                rate = entry['payment_fields'][1]['value']
                print(f"  {plan}: {rate}")
    
    print(f"\n=== RECOMMENDATION ===")
    if len(medicare_rates) > 1:
        print("✅ Current approach is CORRECT")
        print("   Different services do have different payment terms")
        print("   Multiple extractions per file are legitimate")
    else:
        print("🤔 NEEDS INVESTIGATION")
        print("   May need to examine if payment terms are actually service-specific")
        print("   or if they're being interpreted differently by the LLM")

if __name__ == "__main__":
    analyze_combination_uniqueness() 