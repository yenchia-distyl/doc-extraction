import json
import os
import re
from typing import Dict, List, Any, Tuple
from pathlib import Path
import asyncio
import aiohttp
from datetime import datetime
import logging

# Try to load .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PaymentScheduleExtractor:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.document_path = Path("data/example_document.md")
        
    def load_document(self) -> str:
        """Load the medical contract document."""
        with open(self.document_path, "r", encoding="utf-8") as f:
            return f.read()
    
    def identify_sections(self, document: str) -> List[Dict[str, Any]]:
        """Identify major sections in the document that might contain payment schedules."""
        sections = []
        
        # Split document by major headers
        lines = document.split('\n')
        current_section = []
        current_title = ""
        
        for line in lines:
            if line.startswith('## ') or line.startswith('### '):
                if current_section and current_title:
                    sections.append({
                        'title': current_title,
                        'content': '\n'.join(current_section)
                    })
                current_title = line.strip('#').strip()
                current_section = [line]
            else:
                current_section.append(line)
        
        # Add the last section
        if current_section and current_title:
            sections.append({
                'title': current_title,
                'content': '\n'.join(current_section)
            })
        
        return sections
    
    def extract_hierarchy_from_section(self, section_title: str, section_content: str) -> Dict[str, str]:
        """Extract hierarchical information from section title and content."""
        hierarchy = {
            'line_of_business': None,
            'provider_type': None,
            'ip_op': None,
            'service_type': None,
            'plan_type': None
        }
        
        # Look for line of business indicators
        title_lower = section_title.lower()
        content_lower = section_content.lower()
        
        if 'medicaid' in title_lower or 'medicaid' in content_lower[:500]:
            hierarchy['line_of_business'] = 'MEDICAID'
        elif 'medicare' in title_lower or 'medicare' in content_lower[:500]:
            hierarchy['line_of_business'] = 'MEDICARE'
        elif 'commercial' in title_lower or 'exchange' in title_lower:
            hierarchy['line_of_business'] = 'COMMERCIAL-EXCHANGE'
        
        # Look for provider type
        if 'professional' in title_lower or 'professional services' in content_lower[:500]:
            hierarchy['provider_type'] = 'Professional Services'
        elif 'facility' in title_lower or 'hospital' in title_lower:
            hierarchy['provider_type'] = 'Facility Services'
        elif 'ancillary' in title_lower:
            hierarchy['provider_type'] = 'Ancillary Services'
        
        # Look for plan type
        if 'ma plan' in content_lower or 'ma-pd plan' in content_lower:
            hierarchy['plan_type'] = 'MA PLAN/MA-PD PLAN/DSNP PLAN'
        elif 'dsnp' in content_lower:
            hierarchy['plan_type'] = 'DSNP PLAN'
        
        return hierarchy
    
    async def extract_payment_fields(self, session: aiohttp.ClientSession, 
                                   section_content: str, hierarchy: Dict[str, str]) -> List[Dict]:
        """Extract the 5 payment fields from a section using GPT-4."""
        prompt = f"""
You are a legal expert specializing in medical contract analysis. Extract payment information from the following contract section.

Context:
- Line of Business: {hierarchy.get('line_of_business', 'Unknown')}
- Provider Type: {hierarchy.get('provider_type', 'Unknown')}

Extract the following 5 payment fields from the text. For each field, provide:
1. The exact value found in the document
2. The exact citation (quote) from the document
3. A brief rationale for why this value was chosen
4. Leave blank if not found

Fields to extract:
1. "Lesser of Logic Language included (Y/N)" - Look for phrases like "lesser of", "the lesser of billed charges", etc.
2. "Lesser of Rate" - The specific rate mentioned in the lesser-of clause (e.g., "100% of Medicare fee schedule")
3. "Reimb Methodology" - The full description of how payment is calculated
4. "Reimb Methodology short" - A concise version of the methodology (e.g., "100% of Medicare")
5. "Flat Fee" - Any specific dollar amounts mentioned

Return ONLY a valid JSON array with exactly 5 objects, one for each field.

Text:
{section_content[:3000]}  # Limit to prevent token overflow

Output format:
[
    {{
        "data_point_name": "Lesser of Logic Language included (Y/N)",
        "value": "",
        "citation": "",
        "rationale": ""
    }},
    ... (all 5 fields)
]
"""
        
        try:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": "You are a legal expert. Return only valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"}
                }
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    content = result['choices'][0]['message']['content']
                    
                    # Parse the JSON response
                    try:
                        parsed = json.loads(content)
                        # Handle both array and object with array
                        if isinstance(parsed, dict) and 'fields' in parsed:
                            return parsed['fields']
                        elif isinstance(parsed, dict) and 'extracted_fields' in parsed:
                            return parsed['extracted_fields']
                        elif isinstance(parsed, list):
                            return parsed
                        else:
                            # Try to find an array in the response
                            for key, value in parsed.items():
                                if isinstance(value, list) and len(value) == 5:
                                    return value
                            return self._create_empty_fields()
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse JSON response: {content}")
                        return self._create_empty_fields()
                else:
                    error_text = await response.text()
                    logger.error(f"API error: {response.status} - {error_text}")
                    return self._create_empty_fields()
                    
        except Exception as e:
            logger.error(f"Exception during extraction: {str(e)}")
            return self._create_empty_fields()
    
    def _create_empty_fields(self) -> List[Dict]:
        """Create empty payment fields structure."""
        field_names = [
            "Lesser of Logic Language included (Y/N)",
            "Lesser of Rate",
            "Reimb Methodology",
            "Reimb Methodology short",
            "Flat Fee"
        ]
        return [
            {
                "data_point_name": name,
                "value": "",
                "citation": "",
                "rationale": "",
                "document_name": ""
            }
            for name in field_names
        ]
    
    def find_compensation_schedules(self, document: str) -> List[Tuple[str, Dict[str, str]]]:
        """Find all compensation schedule sections and their hierarchical context."""
        schedules = []
        
        # Split the document into lines for easier processing
        lines = document.split('\n')
        
        # Look for sections that contain compensation information
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Check for attachment headers with compensation schedules
            if ('Attachment' in line and ('Medicaid' in line or 'Medicare' in line or 'Commercial' in line)) or \
               ('COMPENSATION SCHEDULE' in line) or \
               ('EXHIBIT' in line and ('Medicaid' in lines[max(0, i-5):i+5] or 
                                       'Medicare' in lines[max(0, i-5):i+5] or
                                       'Commercial' in lines[max(0, i-5):i+5])):
                
                # Extract the section content
                section_start = i
                section_content = []
                
                # Capture content until next major section or end
                j = i + 1
                while j < len(lines):
                    if lines[j].startswith('## Page') or \
                       (lines[j].startswith('Attachment') and j > section_start + 10) or \
                       (lines[j].startswith('ARTICLE') and j > section_start + 10):
                        break
                    section_content.append(lines[j])
                    j += 1
                
                content = '\n'.join(section_content)
                
                # Only process if content has payment-related information
                if any(keyword in content.lower() for keyword in ['allowed amount', 'lesser of', 'compensation', 'fee schedule', 'reimbursement']):
                    # Extract hierarchy information
                    hierarchy = {
                        'line_of_business': None,
                        'provider_type': 'Professional Services',  # Default
                        'ip_op': 'OP',  # Default to outpatient
                        'service_type': 'Covered Services',
                        'plan_type': None
                    }
                    
                    # Determine line of business from attachment name or content
                    full_section = line + '\n' + content
                    if 'attachment a' in full_section.lower() or 'medicaid' in full_section.lower():
                        hierarchy['line_of_business'] = 'MEDICAID'
                        hierarchy['plan_type'] = 'Medicaid Product'
                    elif 'attachment b' in full_section.lower() or 'medicare' in full_section.lower():
                        hierarchy['line_of_business'] = 'MEDICARE'
                        if 'ma plan' in full_section.lower() or 'ma-pd' in full_section.lower() or 'dsnp' in full_section.lower():
                            hierarchy['plan_type'] = 'MA PLAN/MA-PD PLAN/DSNP PLAN'
                        else:
                            hierarchy['plan_type'] = 'Medicare Product'
                    elif 'attachment c' in full_section.lower() or 'commercial' in full_section.lower() or 'exchange' in full_section.lower():
                        hierarchy['line_of_business'] = 'COMMERCIAL-EXCHANGE'
                        hierarchy['plan_type'] = 'Commercial-Exchange Product'
                    
                    # Look for specific provider types
                    if 'professional' in full_section.lower():
                        hierarchy['provider_type'] = 'Professional Services'
                    elif 'facility' in full_section.lower() or 'hospital' in full_section.lower():
                        hierarchy['provider_type'] = 'Facility Services'
                    
                    # Look for specific service types
                    if 'radiology' in content.lower():
                        hierarchy['service_type'] = 'Radiology Services'
                    elif 'laboratory' in content.lower():
                        hierarchy['service_type'] = 'Laboratory Services'
                    elif 'dme' in content.lower():
                        hierarchy['service_type'] = 'DME Services'
                    elif 'therapy' in content.lower():
                        hierarchy['service_type'] = 'Therapy Services'
                    elif 'drugs' in content.lower() or 'biologicals' in content.lower():
                        hierarchy['service_type'] = 'Drugs and Biologicals'
                    
                    if hierarchy['line_of_business']:
                        schedules.append((full_section, hierarchy))
                
                i = j
            else:
                i += 1
        
        # Also look for specific compensation language patterns
        compensation_patterns = [
            r'(?i)allowed amount[^.]+lesser of[^.]+',
            r'(?i)maximum compensation[^.]+shall be[^.]+',
            r'(?i)reimbursement.*?shall be[^.]+',
            r'(?i)payor shall pay[^.]+fee schedule[^.]+'
        ]
        
        for pattern in compensation_patterns:
            matches = re.finditer(pattern, document, re.DOTALL)
            for match in matches:
                # Get surrounding context
                start = max(0, match.start() - 500)
                end = min(len(document), match.end() + 500)
                context = document[start:end]
                
                # Skip if already covered
                if any(context in sched[0] for sched in schedules):
                    continue
                
                # Determine hierarchy from context
                hierarchy = {
                    'line_of_business': None,
                    'provider_type': 'Professional Services',
                    'ip_op': 'OP',
                    'service_type': 'Covered Services',
                    'plan_type': None
                }
                
                # Check for line of business
                lines_before = document[max(0, match.start()-1000):match.start()].split('\n')
                for line in reversed(lines_before):
                    if 'medicaid' in line.lower():
                        hierarchy['line_of_business'] = 'MEDICAID'
                        hierarchy['plan_type'] = 'Medicaid Product'
                        break
                    elif 'medicare' in line.lower():
                        hierarchy['line_of_business'] = 'MEDICARE'
                        hierarchy['plan_type'] = 'Medicare Product'
                        break
                    elif 'commercial' in line.lower() or 'exchange' in line.lower():
                        hierarchy['line_of_business'] = 'COMMERCIAL-EXCHANGE'
                        hierarchy['plan_type'] = 'Commercial-Exchange Product'
                        break
                
                if hierarchy['line_of_business'] and context not in [s[0] for s in schedules]:
                    schedules.append((context, hierarchy))
        
        return schedules
    
    async def process_all_schedules(self) -> Dict[str, Any]:
        """Process all compensation schedules in the document."""
        document = self.load_document()
        schedules = self.find_compensation_schedules(document)
        
        logger.info(f"Found {len(schedules)} compensation schedules to process")
        
        results = {
            "extraction_date": datetime.now().isoformat(),
            "document_name": str(self.document_path),
            "payment_schedules": []
        }
        
        async with aiohttp.ClientSession() as session:
            for i, (content, hierarchy) in enumerate(schedules):
                logger.info(f"Processing schedule {i+1}/{len(schedules)}: {hierarchy}")
                
                # Extract payment fields
                fields = await self.extract_payment_fields(session, content, hierarchy)
                
                # Add document name to each field
                for field in fields:
                    field["document_name"] = f"{self.document_path.name} - {hierarchy['line_of_business']} - {hierarchy['plan_type']}"
                
                # Create the payment schedule entry
                schedule_entry = {
                    "hierarchy": hierarchy,
                    "payment_fields": fields
                }
                
                results["payment_schedules"].append(schedule_entry)
                
                # Small delay to avoid rate limiting
                await asyncio.sleep(0.5)
        
        return results
    
    def save_results(self, results: Dict[str, Any], output_path: str = "data/output/payment_schedules.json"):
        """Save extraction results to JSON file."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)
        logger.info(f"Results saved to {output_path}")
    
    async def run(self):
        """Run the full extraction pipeline."""
        logger.info("Starting payment schedule extraction...")
        
        results = await self.process_all_schedules()
        
        # Save results
        self.save_results(results)
        
        # Print summary
        total_schedules = len(results["payment_schedules"])
        schedules_with_data = sum(
            1 for schedule in results["payment_schedules"]
            if any(field["value"] for field in schedule["payment_fields"])
        )
        
        logger.info(f"\nExtraction complete!")
        logger.info(f"Total payment schedules found: {total_schedules}")
        logger.info(f"Schedules with extracted data: {schedules_with_data}")
        
        # Print a sample
        if results["payment_schedules"]:
            sample = results["payment_schedules"][0]
            logger.info(f"\nSample extraction:")
            logger.info(f"Hierarchy: {sample['hierarchy']}")
            for field in sample['payment_fields']:
                if field['value']:
                    logger.info(f"  {field['data_point_name']}: {field['value']}")
        
        return results


async def main():
    # Get OpenAI API key
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("Please set OPENAI_API_KEY environment variable")
        return
    
    extractor = PaymentScheduleExtractor(api_key)
    await extractor.run()


if __name__ == "__main__":
    asyncio.run(main()) 