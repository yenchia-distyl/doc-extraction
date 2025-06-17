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

class ImprovedPaymentScheduleExtractor:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.schedule_dir = Path("data/headers/schedule")
        self.compensation_exhibits = []
        
    def identify_compensation_exhibits(self) -> List[Path]:
        """Identify the actual compensation schedule EXHIBIT files."""
        exhibit_files = []
        
        # Look specifically for EXHIBIT files that contain compensation schedules
        for file_path in self.schedule_dir.glob("*EXHIBIT*.md"):
            if any(keyword in file_path.name for keyword in ["Medicaid", "Medicare", "Commercial"]):
                exhibit_files.append(file_path)
                logger.info(f"Found compensation exhibit: {file_path.name}")
        
        return sorted(exhibit_files)
    
    def extract_hierarchy_from_filename(self, filename: str) -> Dict[str, str]:
        """Extract hierarchy information from the filename."""
        hierarchy = {
            'line_of_business': None,
            'provider_type': 'Professional Services',  # Default
            'ip_op': 'OP',  # Default to outpatient
            'service_type': 'Covered Services',  # Default
            'plan_type': None
        }
        
        # Determine line of business from filename
        if 'Medicaid' in filename:
            hierarchy['line_of_business'] = 'MEDICAID'
            hierarchy['plan_type'] = 'Medicaid Product'
        elif 'Medicare' in filename:
            hierarchy['line_of_business'] = 'MEDICARE'
            hierarchy['plan_type'] = 'Medicare Product'
        elif 'Commercial' in filename or 'Exchange' in filename:
            hierarchy['line_of_business'] = 'COMMERCIAL-EXCHANGE'
            hierarchy['plan_type'] = 'Commercial-Exchange Product'
        
        return hierarchy
    
    def identify_service_categories_in_content(self, content: str) -> List[Dict[str, str]]:
        """Identify specific service categories mentioned in the content."""
        service_categories = []
        
        # Look for tables with service categories
        table_pattern = r'Table\s+\d+\.?\s*\n([^\n]+)\n'
        table_matches = re.finditer(table_pattern, content, re.IGNORECASE)
        
        # Also look for specific service mentions
        service_patterns = {
            'Radiology Services': r'radiology\s+services',
            'Laboratory Services': r'laboratory\s+services',
            'DME Services': r'dme\s+services',
            'Therapy Services': r'(?:physical|occupational|speech)\s+therapy',
            'Drugs and Biologicals': r'drugs?\s+(?:and|&)\s+biologicals?'
        }
        
        found_services = set()
        
        # Check content for service types
        for service_name, pattern in service_patterns.items():
            if re.search(pattern, content, re.IGNORECASE):
                found_services.add(service_name)
        
        # If no specific services found, default to Covered Services
        if not found_services:
            found_services.add('Covered Services')
        
        return list(found_services)
    
    def extract_plan_types_from_content(self, content: str, line_of_business: str) -> List[str]:
        """Extract specific plan types from content."""
        plan_types = []
        
        if line_of_business == 'MEDICARE':
            # Look for specific Medicare plan types
            if re.search(r'MA\s*PLAN|MA-PD\s*PLAN|DSNP\s*PLAN', content, re.IGNORECASE):
                plan_types.append('MA PLAN/MA-PD PLAN/DSNP PLAN')
            else:
                plan_types.append('Medicare Product')
        elif line_of_business == 'MEDICAID':
            plan_types.append('Medicaid Product')
        elif line_of_business == 'COMMERCIAL-EXCHANGE':
            plan_types.append('Commercial-Exchange Product')
        
        return plan_types if plan_types else ['Standard Plan']
    
    async def extract_payment_fields(self, session: aiohttp.ClientSession, 
                                   content: str, hierarchy: Dict[str, str],
                                   filename: str) -> List[Dict]:
        """Extract the 5 payment fields from content using GPT-4."""
        # Build a more focused prompt
        prompt = f"""
Analyze this medical contract compensation schedule and extract payment information.

Document: {filename}
Line of Business: {hierarchy['line_of_business']}
Service Type: {hierarchy['service_type']}

Text to analyze:
{content}

IMPORTANT: Look for Table 1 if present. For "{hierarchy['service_type']}", find the SPECIFIC contracted rate from Table 1.

Return a JSON object with this EXACT structure:
{{
  "fields": [
    {{
      "data_point_name": "Lesser of Logic Language included (Y/N)",
      "value": "Y or N",
      "citation": "exact text from document",
      "rationale": "why this value was chosen"
    }},
    {{
      "data_point_name": "Lesser of Rate", 
      "value": "the specific rate (e.g., 85% of the Medicare Rate for Radiology)",
      "citation": "exact text from document",
      "rationale": "why this value was chosen"
    }},
    {{
      "data_point_name": "Reimb Methodology",
      "value": "full payment calculation description",
      "citation": "exact text from document", 
      "rationale": "why this value was chosen"
    }},
    {{
      "data_point_name": "Reimb Methodology short",
      "value": "concise version (e.g., 85% MCR)",
      "citation": "exact text from document",
      "rationale": "why this value was chosen"
    }},
    {{
      "data_point_name": "Flat Fee",
      "value": "dollar amount or empty if none",
      "citation": "exact text from document",
      "rationale": "why this value was chosen"
    }}
  ]
}}

Key instructions:
- For "Lesser of Logic Language included", answer Y if you find "lesser of" language
- For "Lesser of Rate", use the Table 1 rate for this service if available (e.g., "85% of the Medicare Rate" for Radiology)
- For "Reimb Methodology short", use abbreviations like MCR=Medicare, MCD=Medicaid
- Leave "Flat Fee" empty unless specific dollar amounts are mentioned
"""
        
        try:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "o3-mini",
                    "messages": [
                        {"role": "system", "content": "You are a medical contract expert. Extract payment information exactly as requested. Always return valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 1000,
                    "response_format": {"type": "json_object"}
                }
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    content_str = result['choices'][0]['message']['content']
                    
                    # Parse JSON response
                    try:
                        parsed = json.loads(content_str)
                        
                        # Create the standard 5-field structure
                        fields = []
                        
                        # Check if the response has a "fields" array
                        if "fields" in parsed and isinstance(parsed["fields"], list):
                            for field in parsed["fields"]:
                                fields.append({
                                    "data_point_name": field.get("data_point_name", ""),
                                    "value": field.get("value", ""),
                                    "citation": field.get("citation", ""),
                                    "rationale": field.get("rationale", ""),
                                    "document_name": filename
                                })
                        else:
                            # Try to extract from numbered keys or direct field names
                            field_mapping = [
                                ("Lesser of Logic Language included (Y/N)", ["lesser_of_logic", "1", "lesser_of_logic_language_included"]),
                                ("Lesser of Rate", ["lesser_of_rate", "2", "lesser_of_rate_value"]),
                                ("Reimb Methodology", ["reimb_methodology", "3", "reimbursement_methodology"]),
                                ("Reimb Methodology short", ["reimb_methodology_short", "4", "reimbursement_methodology_short"]),
                                ("Flat Fee", ["flat_fee", "5", "flat_fee_amount"])
                            ]
                            
                            for field_name, possible_keys in field_mapping:
                                field_data = {"data_point_name": field_name, "value": "", "citation": "", "rationale": "", "document_name": filename}
                                
                                # Try to find the field data
                                for key in possible_keys:
                                    if key in parsed:
                                        if isinstance(parsed[key], dict):
                                            field_data["value"] = parsed[key].get("value", "")
                                            field_data["citation"] = parsed[key].get("citation", "")
                                            field_data["rationale"] = parsed[key].get("rationale", "")
                                            break
                                        elif isinstance(parsed[key], str):
                                            field_data["value"] = parsed[key]
                                            break
                                
                                fields.append(field_data)
                        
                        # Ensure we have exactly 5 fields
                        if len(fields) != 5:
                            logger.warning(f"Expected 5 fields but got {len(fields)}")
                            return self._create_empty_fields()
                        
                        return fields
                        
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse JSON response: {e}")
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
    
    async def process_exhibit_file(self, session: aiohttp.ClientSession, 
                                  file_path: Path) -> List[Dict[str, Any]]:
        """Process a single exhibit file and extract all payment schedules."""
        results = []
        
        # Read the file content
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Extract base hierarchy from filename
        base_hierarchy = self.extract_hierarchy_from_filename(file_path.name)
        
        # Find service categories in content
        service_types = self.identify_service_categories_in_content(content)
        
        # Extract plan types
        plan_types = self.extract_plan_types_from_content(content, base_hierarchy['line_of_business'])
        
        # Create a schedule entry for each unique combination
        for service_type in service_types:
            for plan_type in plan_types:
                hierarchy = base_hierarchy.copy()
                hierarchy['service_type'] = service_type
                hierarchy['plan_type'] = plan_type
                
                logger.info(f"Processing: {file_path.name} - {service_type} - {plan_type}")
                
                # Extract payment fields
                fields = await self.extract_payment_fields(
                    session, content, hierarchy, file_path.name
                )
                
                # Add document name to each field
                for field in fields:
                    field["document_name"] = f"{file_path.name} - {service_type}"
                
                # Create the payment schedule entry
                schedule_entry = {
                    "source_file": file_path.name,
                    "hierarchy": hierarchy,
                    "payment_fields": fields
                }
                
                results.append(schedule_entry)
                
                # Small delay to avoid rate limiting
                await asyncio.sleep(0.5)
        
        return results
    
    async def run(self):
        """Run the improved extraction pipeline."""
        logger.info("Starting improved payment schedule extraction...")
        
        # Find all compensation exhibit files
        exhibit_files = self.identify_compensation_exhibits()
        
        if not exhibit_files:
            logger.error("No compensation exhibit files found!")
            return
        
        logger.info(f"Found {len(exhibit_files)} exhibit files to process")
        
        all_results = {
            "extraction_date": datetime.now().isoformat(),
            "source_directory": str(self.schedule_dir),
            "payment_schedules": []
        }
        
        async with aiohttp.ClientSession() as session:
            for exhibit_file in exhibit_files:
                logger.info(f"\nProcessing exhibit: {exhibit_file.name}")
                results = await self.process_exhibit_file(session, exhibit_file)
                all_results["payment_schedules"].extend(results)
        
        # Save results
        output_path = "data/output/payment_schedules_v2.json"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(all_results, f, indent=2)
        
        # Print summary
        total_schedules = len(all_results["payment_schedules"])
        schedules_with_data = sum(
            1 for schedule in all_results["payment_schedules"]
            if any(field["value"] for field in schedule["payment_fields"])
        )
        
        logger.info(f"\n=== EXTRACTION COMPLETE ===")
        logger.info(f"Total payment schedules created: {total_schedules}")
        logger.info(f"Schedules with extracted data: {schedules_with_data}")
        logger.info(f"Results saved to: {output_path}")
        
        # Show summary by line of business
        lob_summary = {}
        for schedule in all_results["payment_schedules"]:
            lob = schedule["hierarchy"]["line_of_business"]
            if lob not in lob_summary:
                lob_summary[lob] = {"total": 0, "with_data": 0}
            lob_summary[lob]["total"] += 1
            if any(field["value"] for field in schedule["payment_fields"]):
                lob_summary[lob]["with_data"] += 1
        
        logger.info("\nSummary by Line of Business:")
        for lob, counts in lob_summary.items():
            logger.info(f"  {lob}: {counts['with_data']}/{counts['total']} with data")
        
        return all_results


async def main():
    # Get OpenAI API key
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("Please set OPENAI_API_KEY environment variable")
        return
    
    extractor = ImprovedPaymentScheduleExtractor(api_key)
    await extractor.run()


if __name__ == "__main__":
    asyncio.run(main()) 