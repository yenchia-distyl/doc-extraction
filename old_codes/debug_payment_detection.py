import re
from pathlib import Path

def test_payment_detection():
    # Enhanced payment indicators from the main script
    payment_indicators = [
        r'table\s*\d+.*(?:rate|fee|payment|compensation)',
        r'(?:contracted\s+rate|compensation\s+schedule|fee\s+schedule)',
        r'(?:reimburse|payment).*(?:rate|amount|percentage|\%|\$)',
        r'(?:\d+\%|\$\d+).*(?:medicare|medicaid|rate)',
        r'(?:lesser\s+of|allowed\s+amount|flat\s+fee)',
        r'(?:TCM|RBMS|TFC|ITFC).*(?:reimburse|rate)',
        r'(?:current\s+medicaid\s+rate|current\s+medicare\s+rate)',
        r'(?:shall\s+be\s+reimbursed|will\s+be\s+reimbursed)',
        r'(?:payment.*methodology|reimbursement.*methodology)',
        r'(?:average\s+sales\s+price|ASP|average\s+wholesale\s+cost|AWP)',
        r'(?:\d+\%\s*(?:of|off)\s*(?:medicare|medicaid|rate))',
        r'(?:compensation\s+schedule|fee\s+change|rate\s+update)',
        # Add more specific patterns for the content we know is there
        r'provider\s+payment',
        r'reimbursed\s+at\s+the\s+current',
        r'shall\s+be\s+reimbursed',
        r'table\s+1',
        r'\d+\%\s+of\s+the\s+medicare\s+rate',
    ]
    
    schedule_dir = Path("data/headers/schedule")
    
    # Test specific files we know have payment info
    test_files = [
        "Attachment_A_Medicaid__SCHEDULE A-2.md",
        "Attachment_B_Medicare__SCHEDULE A.md"
    ]
    
    for filename in test_files:
        file_path = schedule_dir / filename
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            print(f"\n{'='*60}")
            print(f"Testing: {filename}")
            print(f"{'='*60}")
            print(f"Total content length: {len(content)} characters")
            
            # Test NEW detection logic (first 4000 + last 4000)
            found_patterns_new = []
            for i, pattern in enumerate(payment_indicators):
                matches_start = list(re.finditer(pattern, content[:4000], re.IGNORECASE))
                matches_end = list(re.finditer(pattern, content[-4000:], re.IGNORECASE))
                matches = matches_start + matches_end
                if matches:
                    found_patterns_new.append((i, pattern, matches))
                    print(f"✓ NEW Pattern {i}: {pattern}")
                    for match in matches[:2]:  # Show first 2 matches
                        if match in matches_start:
                            start, end = match.span()
                            context = content[max(0, start-50):end+50]
                            print(f"  START Match: '{context}'")
                        else:  # match in matches_end
                            start, end = match.span()
                            # Adjust position for end-of-file search
                            actual_start = len(content) - 4000 + start
                            actual_end = len(content) - 4000 + end
                            context = content[max(0, actual_start-50):actual_end+50]
                            print(f"  END Match: '{context}'")
            
            # Test OLD detection logic (first 8000 only)
            found_patterns_old = []
            for i, pattern in enumerate(payment_indicators):
                matches = list(re.finditer(pattern, content[:8000], re.IGNORECASE))
                if matches:
                    found_patterns_old.append((i, pattern, matches))
            
            print(f"\n📊 COMPARISON:")
            print(f"  NEW logic (start+end): {len(found_patterns_new)} patterns found")
            print(f"  OLD logic (start only): {len(found_patterns_old)} patterns found")
            
            if len(found_patterns_new) > len(found_patterns_old):
                print(f"  🎯 NEW logic found {len(found_patterns_new) - len(found_patterns_old)} additional patterns!")
            
            # Show specific table content if found
            if "Table 1" in content:
                table_pos = content.find("Table 1")
                table_content = content[table_pos:table_pos+500]
                print(f"\n📋 Table 1 content found at position {table_pos}:")
                print(table_content)

if __name__ == "__main__":
    test_payment_detection() 