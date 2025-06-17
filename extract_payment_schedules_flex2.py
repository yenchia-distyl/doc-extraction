import json
import os
import re
from typing import Dict, List, Any, Tuple, Optional
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

class ComprehensivePaymentScheduleExtractor:
    """
    Comprehensive version that processes ALL header files, not just EXHIBIT files.
    Uses content-based detection to identify payment information wherever it appears.
    """
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.schedule_dir = Path("data/headers/schedule")
        self.total_api_calls = 0
        self.semaphore = asyncio.Semaphore(5)  # Limit to 5 concurrent API calls
        
    def identify_all_header_files(self) -> List[Path]:
        """Identify ALL header files for processing."""
        all_files = []
        
        # Get all .md files in the schedule directory
        for file_path in self.schedule_dir.glob("*.md"):
            all_files.append(file_path)
            logger.info(f"Found header file: {file_path.name}")
        
        return sorted(all_files)
    
    async def detect_payment_content(self, session: aiohttp.ClientSession, 
                                   filename: str, content: str) -> Dict[str, Any]:
        """Use LLM to detect if a file contains payment/compensation information."""
        
        # First do a quick regex check for obvious payment indicators
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
        ]
        
        has_payment_indicators = any(
            re.search(pattern, content[:4000], re.IGNORECASE) or  # Check first 4000 chars
            re.search(pattern, content[-4000:], re.IGNORECASE)    # Check last 4000 chars
            for pattern in payment_indicators
        )
        
        if not has_payment_indicators:
            return {
                "has_payment_info": False,
                "confidence": "low",
                "payment_types": [],
                "reasoning": "No obvious payment indicators found in content"
            }
        
        # Use LLM for more sophisticated analysis
        prompt = f"""
Analyze this medical contract file to determine if it contains payment/compensation information.

Filename: {filename}

Content from beginning (first 3000 characters):
{content[:3000]}

Content from end (last 3000 characters):
{content[-3000:]}

Look for:
1. Payment rates, percentages, or dollar amounts
2. Compensation schedules or fee schedules  
3. Tables with rates or payment information
4. Reimbursement methodologies
5. "Lesser of" payment logic
6. Flat fees or specific payment amounts

Return JSON with EXACTLY this format:
{{
  "has_payment_info": true/false,
  "confidence": "high/medium/low",
  "payment_types": [
    "list of specific payment types found (e.g., 'Table 1 rates', 'TCM reimbursement', 'lesser of logic')"
  ],
  "reasoning": "explain what payment information was found or why none was found"
}}

Be thorough - even references to "current Medicaid rate" or "compensation schedule" count as payment info.
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
                        {"role": "system", "content": "You are a medical contract expert. Analyze documents for payment information. Always return valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 500,
                    "response_format": {"type": "json_object"}
                }
            ) as response:
                self.total_api_calls += 1
                if response.status == 200:
                    result = await response.json()
                    parsed = json.loads(result['choices'][0]['message']['content'])
                    logger.info(f"Payment detection for {filename}: {parsed.get('has_payment_info', False)} - {parsed.get('reasoning', '')}")
                    return parsed
                else:
                    logger.error(f"Error in payment detection: {response.status}")
                    return {
                        "has_payment_info": has_payment_indicators,
                        "confidence": "low", 
                        "payment_types": ["regex_detected"] if has_payment_indicators else [],
                        "reasoning": "LLM call failed, using regex fallback"
                    }
        except Exception as e:
            logger.error(f"Exception in payment detection: {e}")
            return {
                "has_payment_info": has_payment_indicators,
                "confidence": "low",
                "payment_types": ["regex_detected"] if has_payment_indicators else [],
                "reasoning": f"Exception occurred: {str(e)}"
            }
    
    async def extract_line_of_business_with_llm(self, session: aiohttp.ClientSession, 
                                                filename: str, content: str) -> str:
        """Use LLM to determine line of business from filename and content."""
        prompt = f"""
Analyze this medical contract filename and content to determine the Line of Business.

Filename: {filename}

Content excerpt (first 500 chars):
{content[:500]}

Common Lines of Business include:
- MEDICAID
- MEDICARE  
- COMMERCIAL
- COMMERCIAL-EXCHANGE
- MANAGED CARE
- WORKERS COMPENSATION
- TRICARE

Return JSON with EXACTLY this format:
{{
  "line_of_business": "THE_LINE_OF_BUSINESS_IN_CAPS"
}}

Be precise and use standard industry terminology.
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
                        {"role": "system", "content": "You are a healthcare contract expert. Identify lines of business accurately. Always return valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 100,
                    "response_format": {"type": "json_object"}
                }
            ) as response:
                self.total_api_calls += 1
                if response.status == 200:
                    result = await response.json()
                    parsed = json.loads(result['choices'][0]['message']['content'])
                    return parsed.get("line_of_business", "UNKNOWN")
                else:
                    logger.error(f"Error determining line of business: {response.status}")
                    # Fallback to filename parsing
                    if 'Medicaid' in filename:
                        return 'MEDICAID'
                    elif 'Medicare' in filename:
                        return 'MEDICARE'
                    elif 'Commercial' in filename or 'Exchange' in filename:
                        return 'COMMERCIAL-EXCHANGE'
                    return 'UNKNOWN'
        except Exception as e:
            logger.error(f"Exception in line of business detection: {e}")
            return 'UNKNOWN'
    
    async def identify_service_categories_with_llm(self, session: aiohttp.ClientSession, 
                                                  content: str) -> List[str]:
        """Use LLM to identify all service categories in the content."""
        prompt = f"""
Analyze this medical contract content and identify ALL distinct service categories mentioned.

Content to analyze:
{content[:4000]}

Look for:
1. Medical service categories (e.g., Radiology, Laboratory, DME, Therapy)
2. Professional vs Facility services
3. Specialized services (e.g., Behavioral Health, Emergency Services)
4. Any service types mentioned in tables, fee schedules, or service descriptions
5. Specific program services (e.g., TCM, RBMS, TFC, ITFC)
6. Drug and biological services

Return JSON with EXACTLY this format:
{{
  "service_categories": [
    "Service Category 1",
    "Service Category 2",
    ...
  ]
}}

Important:
- List ONLY specific service categories actually mentioned in the text
- Use standard medical terminology (e.g., "Radiology Services" not just "X-rays")
- Include program-specific services like "Targeted Case Management (TCM)"
- If no specific services are mentioned, return ["Covered Services"]
- Don't include generic terms like "medical services" unless that's the actual category
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
                        {"role": "system", "content": "You are a medical contract expert. Identify service categories precisely. Always return valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 500,
                    "response_format": {"type": "json_object"}
                }
            ) as response:
                self.total_api_calls += 1
                if response.status == 200:
                    result = await response.json()
                    parsed = json.loads(result['choices'][0]['message']['content'])
                    services = parsed.get("service_categories", [])
                    
                    if not services:
                        services = ["Covered Services"]
                    
                    logger.info(f"LLM identified service categories: {services}")
                    return services
                else:
                    logger.error(f"Error identifying service categories: {response.status}")
                    return ["Covered Services"]
        except Exception as e:
            logger.error(f"Exception in service category detection: {e}")
            return ["Covered Services"]
    
    async def extract_plan_types_with_llm(self, session: aiohttp.ClientSession,
                                         content: str, line_of_business: str) -> List[str]:
        """Use LLM to extract specific plan types from content."""
        prompt = f"""
Analyze this medical contract content for the {line_of_business} line of business and identify ALL specific plan types mentioned.

Content to analyze:
{content[:2000]}

For {line_of_business}, look for specific plan types such as:
- For MEDICARE: MA Plan, MA-PD Plan, DSNP Plan, Medicare Advantage, Part D Plans, etc.
- For MEDICAID: Medicaid Managed Care, CHIP, SoonerSelect, Specialty Program, etc.
- For COMMERCIAL: PPO, HMO, EPO, Exchange plans, specific commercial products

Return JSON with EXACTLY this format:
{{
  "plan_types": [
    "Specific Plan Type 1",
    "Specific Plan Type 2"
  ]
}}

Important:
- Look for actual plan names mentioned in the document
- Include program names like "SoonerSelect" or "Children's Specialty Program"
- If no specific plan types are mentioned, return a generic one for the line of business
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
                        {"role": "system", "content": "You are a medical contract expert. Identify plan types accurately. Always return valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 300,
                    "response_format": {"type": "json_object"}
                }
            ) as response:
                self.total_api_calls += 1
                if response.status == 200:
                    result = await response.json()
                    parsed = json.loads(result['choices'][0]['message']['content'])
                    plan_types = parsed.get("plan_types", [])
                    
                    # Provide fallback if no plan types found
                    if not plan_types:
                        if line_of_business == 'MEDICARE':
                            plan_types = ['Medicare Product']
                        elif line_of_business == 'MEDICAID':
                            plan_types = ['Medicaid Product']
                        elif line_of_business == 'COMMERCIAL-EXCHANGE':
                            plan_types = ['Commercial-Exchange Product']
                        else:
                            plan_types = ['Standard Plan']
                    
                    logger.info(f"LLM identified plan types: {plan_types}")
                    return plan_types
                else:
                    logger.error(f"Error extracting plan types: {response.status}")
                    return ['Standard Plan']
        except Exception as e:
            logger.error(f"Exception in plan type extraction: {e}")
            return ['Standard Plan']
    
    async def extract_payment_fields(self, session: aiohttp.ClientSession, 
                                   content: str, hierarchy: Dict[str, str],
                                   filename: str) -> List[Dict]:
        """Extract the 5 payment fields from content using GPT-4."""
        async with self.semaphore:  # Rate limiting
            prompt = f"""
Analyze this medical contract content and extract payment information.

Document: {filename}
Line of Business: {hierarchy['line_of_business']}
Service Type: {hierarchy['service_type']}

Text to analyze:
{content}

IMPORTANT: Look carefully for ANY payment-related information. This could be in:
- Table 1 or other tables with rates
- Specific percentage rates (e.g., "85% of Medicare Rate")
- References to "current Medicaid rate"
- Lesser of logic language
- Flat fee amounts
- Reimbursement methodologies

Return a JSON object with this EXACT structure:
{{
  "fields": [
    {{
      "data_point_name": "Lesser of Logic Language included (Y/N)",
      "value": "Y or N (Y if any 'lesser of' language found)",
      "citation": "exact text from document",
      "rationale": "why this value was chosen"
    }},
    {{
      "data_point_name": "Lesser of Rate", 
      "value": "the specific rate if found (e.g., '85% of Medicare Rate')",
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
      "value": "concise version (e.g., 85% MCR, Current MCD Rate)",
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
- For "Lesser of Logic Language included", answer Y if you find ANY "lesser of" language anywhere
- For rates, capture specific percentages or references to rate schedules
- For "Reimb Methodology short", use abbreviations like MCR=Medicare, MCD=Medicaid
- Be thorough - even indirect references to payment rates should be captured
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
                            {"role": "system", "content": "You are a medical contract expert. Extract payment information exactly as requested. Always return valid JSON."},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 1500,
                        "response_format": {"type": "json_object"}
                    }
                ) as response:
                    self.total_api_calls += 1
                    if response.status == 200:
                        result = await response.json()
                        content_str = result['choices'][0]['message']['content']
                        
                        try:
                            parsed = json.loads(content_str)
                            fields = []
                            
                            if "fields" in parsed and isinstance(parsed["fields"], list):
                                for field in parsed["fields"]:
                                    fields.append({
                                        "data_point_name": field.get("data_point_name", ""),
                                        "value": field.get("value", ""),
                                        "citation": field.get("citation", ""),
                                        "rationale": field.get("rationale", ""),
                                        "document_name": filename
                                    })
                            
                            if len(fields) != 5:
                                logger.warning(f"Expected 5 fields but got {len(fields)} for {hierarchy['service_type']}")
                                return self._create_empty_fields()
                            
                            return fields
                            
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse JSON response for {hierarchy['service_type']}: {e}")
                            return self._create_empty_fields()
                    else:
                        error_text = await response.text()
                        logger.error(f"API error for {hierarchy['service_type']}: {response.status} - {error_text}")
                        return self._create_empty_fields()
                        
            except Exception as e:
                logger.error(f"Exception during extraction for {hierarchy['service_type']}: {str(e)}")
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
    
    async def process_header_file(self, session: aiohttp.ClientSession, 
                                 file_path: Path) -> List[Dict[str, Any]]:
        """Process a single header file and extract payment schedules if present."""
        results = []
        
        # Read the file content
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        logger.info(f"Processing: {file_path.name}")
        
        # First, detect if this file contains payment information
        payment_detection = await self.detect_payment_content(session, file_path.name, content)
        
        if not payment_detection.get("has_payment_info", False):
            logger.info(f"No payment information detected in {file_path.name}")
            return results
        
        logger.info(f"Payment information detected in {file_path.name}: {payment_detection.get('payment_types', [])}")
        
        # Extract line of business using LLM
        line_of_business = await self.extract_line_of_business_with_llm(session, file_path.name, content)
        
        # Build base hierarchy
        base_hierarchy = {
            'line_of_business': line_of_business,
            'provider_type': 'Professional Services',  # Could be made dynamic
            'ip_op': 'OP',  # Could be made dynamic
            'service_type': None,
            'plan_type': None
        }
        
        # Find service categories using LLM
        service_types = await self.identify_service_categories_with_llm(session, content)
        
        # Extract plan types using LLM
        plan_types = await self.extract_plan_types_with_llm(session, content, line_of_business)
        
        # Create all combinations and batch process them
        tasks = []
        combinations = []
        
        for service_type in service_types:
            for plan_type in plan_types:
                hierarchy = base_hierarchy.copy()
                hierarchy['service_type'] = service_type
                hierarchy['plan_type'] = plan_type
                combinations.append((hierarchy, service_type, plan_type))
                
                # Create async task for payment field extraction
                task = self.extract_payment_fields(session, content, hierarchy, file_path.name)
                tasks.append(task)
        
        logger.info(f"Batch processing {len(tasks)} combinations for {file_path.name}")
        
        # Process all combinations in parallel
        all_fields = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Create schedule entries from results
        for i, fields in enumerate(all_fields):
            if isinstance(fields, Exception):
                logger.error(f"Error processing combination {i}: {fields}")
                fields = self._create_empty_fields()
            
            hierarchy, service_type, plan_type = combinations[i]
            
            # Add document name to each field
            for field in fields:
                field["document_name"] = f"{file_path.name} - {service_type}"
            
            # Create the payment schedule entry
            schedule_entry = {
                "source_file": file_path.name,
                "file_type": self._determine_file_type(file_path.name),
                "payment_detection": payment_detection,
                "hierarchy": hierarchy,
                "payment_fields": fields
            }
            
            results.append(schedule_entry)
        
        return results
    
    def _determine_file_type(self, filename: str) -> str:
        """Determine the type of header file."""
        if "EXHIBIT" in filename:
            return "EXHIBIT"
        elif "SCHEDULE" in filename:
            return "SCHEDULE"
        elif "PRODUCT ATTACHMENT" in filename:
            return "PRODUCT_ATTACHMENT"
        else:
            return "OTHER"
    
    async def run(self):
        """Run the comprehensive extraction pipeline."""
        logger.info("Starting comprehensive payment schedule extraction...")
        logger.info("This version processes ALL header files and uses content-based payment detection.")
        
        # Find all header files
        header_files = self.identify_all_header_files()
        
        if not header_files:
            logger.error("No header files found!")
            return
        
        logger.info(f"Found {len(header_files)} header files to process")
        
        all_results = {
            "extraction_date": datetime.now().isoformat(),
            "source_directory": str(self.schedule_dir),
            "extraction_method": "comprehensive-content-based",
            "files_processed": len(header_files),
            "payment_schedules": []
        }
        
        files_with_payment_info = 0
        
        async with aiohttp.ClientSession() as session:
            for i, header_file in enumerate(header_files):
                logger.info(f"\n{'='*60}")
                logger.info(f"Processing {i+1}/{len(header_files)}: {header_file.name}")
                logger.info(f"{'='*60}")
                
                try:
                    results = await self.process_header_file(session, header_file)
                    if results:
                        files_with_payment_info += 1
                        all_results["payment_schedules"].extend(results)
                        logger.info(f"✅ Extracted {len(results)} payment schedules from {header_file.name}")
                    else:
                        logger.info(f"⏭️  No payment information in {header_file.name}")
                except Exception as e:
                    logger.error(f"❌ Error processing {header_file.name}: {e}")
                    continue
        
        # Save results
        output_path = "data/output/payment_schedules_comprehensive.json"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(all_results, f, indent=2)
        
        # Print summary
        total_schedules = len(all_results["payment_schedules"])
        schedules_with_data = sum(
            1 for schedule in all_results["payment_schedules"]
            if any(field["value"] for field in schedule["payment_fields"])
        )
        
        logger.info(f"\n{'='*60}")
        logger.info(f"COMPREHENSIVE EXTRACTION COMPLETE")
        logger.info(f"{'='*60}")
        logger.info(f"Total files processed: {len(header_files)}")
        logger.info(f"Files with payment information: {files_with_payment_info}")
        logger.info(f"Total payment schedules created: {total_schedules}")
        logger.info(f"Schedules with extracted data: {schedules_with_data}")
        logger.info(f"Total API calls made: {self.total_api_calls}")
        logger.info(f"Results saved to: {output_path}")
        
        # Show summary by file type
        file_type_summary = {}
        for schedule in all_results["payment_schedules"]:
            file_type = schedule["file_type"]
            if file_type not in file_type_summary:
                file_type_summary[file_type] = {"total": 0, "with_data": 0}
            file_type_summary[file_type]["total"] += 1
            if any(field["value"] for field in schedule["payment_fields"]):
                file_type_summary[file_type]["with_data"] += 1
        
        logger.info("\nSummary by File Type:")
        for file_type, counts in file_type_summary.items():
            logger.info(f"  {file_type}: {counts['with_data']}/{counts['total']} with data")
        
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
        
        # Show detected service categories
        all_services = set()
        for schedule in all_results["payment_schedules"]:
            all_services.add(schedule["hierarchy"]["service_type"])
        
        logger.info(f"\nDetected Service Categories: {sorted(all_services)}")
        
        return all_results


async def main():
    # Get OpenAI API key
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("Please set OPENAI_API_KEY environment variable")
        return
    
    extractor = ComprehensivePaymentScheduleExtractor(api_key)
    await extractor.run()


if __name__ == "__main__":
    asyncio.run(main()) 