import json
import os
import re
from typing import Dict, List, Any, Tuple
from pathlib import Path
import asyncio
import aiohttp
from datetime import datetime
import logging
import argparse

# Try to load .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class LLMBasedPaymentScheduleExtractor:
    """
    Version 2: Uses LLM for service category and plan type detection
    instead of hardcoded patterns, making it more flexible for new document types.
    """
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.schedule_dir = Path("data/headers/schedule")
        self.compensation_exhibits = []
        self.total_api_calls = 0
        self.single_file = None
        self.output_dir = Path("data/output")
        self.payment_model = 'gpt-4o-mini'
        self.output_filename = 'payment_schedules_v2_llm.json'
        
    def identify_compensation_exhibits(self) -> List[Path]:
        """Identify the actual compensation schedule EXHIBIT files."""
        exhibit_files = []
        
        # If single file is specified, use that
        if self.single_file and self.single_file.exists():
            exhibit_files.append(self.single_file)
            logger.info(f"Processing single file: {self.single_file.name}")
            return exhibit_files
        
        # Look specifically for EXHIBIT files that contain compensation schedules
        for file_path in self.schedule_dir.glob("*EXHIBIT*.md"):
            # This is still programmatic but could be made more flexible
            if any(keyword in file_path.name for keyword in ["Medicaid", "Medicare", "Commercial", "Exchange"]):
                exhibit_files.append(file_path)
                logger.info(f"Found compensation exhibit: {file_path.name}")
        
        return sorted(exhibit_files)
    
    async def extract_line_of_business_with_llm(self, session: aiohttp.ClientSession, 
                                                filename: str, content: str) -> str:
        """Use LLM to determine line of business from filename and content."""
        prompt = f"""
Analyze this medical contract filename and content excerpt to determine the Line of Business.

Filename: {filename}

Content excerpt (first 500 chars):
{content[:500]}

Common Lines of Business include:
- MEDICAID
- MEDICARE  
- COMMERCIAL-EXCHANGE

Return JSON with EXACTLY this format:
{{
  "line_of_business": "THE_LINE_OF_BUSINESS_IN_CAPS"
}}

Be precise and use standard industry terminology.
"""
        
        try:
            # Adjust parameters based on model
            api_params = {
                "model": self.payment_model,
                "messages": [
                    {"role": "system", "content": "You are a healthcare contract expert. Identify lines of business accurately. Always return valid JSON."},
                    {"role": "user", "content": prompt}
                ]
            }
            
            # Handle parameter differences for different models
            if self.payment_model in ['o3', 'o1-mini']:
                api_params["max_completion_tokens"] = 100
                # O3 only supports default temperature of 1
            else:
                api_params["temperature"] = 0.1
                api_params["max_tokens"] = 100
                api_params["response_format"] = {"type": "json_object"}
            
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=api_params
            ) as response:
                self.total_api_calls += 1
                if response.status == 200:
                    result = await response.json()
                    parsed = json.loads(result['choices'][0]['message']['content'])
                    return parsed.get("line_of_business", "UNKNOWN")
                else:
                    logger.error(f"Error determining line of business: {response.status}")
                    # Fallback to programmatic detection
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
{content[:3000]}  # Send more content for better detection

Look for:
1. Medical service categories (e.g., Radiology, Laboratory, DME, Therapy)
2. Professional vs Facility services
3. Specialized services (e.g., Behavioral Health, Emergency Services)
4. Any service types mentioned in tables, fee schedules, or service descriptions
5. Drug and biological services

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
- If no specific services are mentioned, return ["Covered Services"]
- Don't include generic terms like "medical services" unless that's the actual category
"""
        
        try:
            # Adjust parameters based on model
            api_params = {
                "model": self.payment_model,
                "messages": [
                    {"role": "system", "content": "You are a medical contract expert. Identify service categories precisely. Always return valid JSON."},
                    {"role": "user", "content": prompt}
                ]
            }
            
            # Handle parameter differences for different models
            if self.payment_model in ['o3', 'o1-mini']:
                api_params["max_completion_tokens"] = 500
            else:
                api_params["temperature"] = 0.1
                api_params["max_tokens"] = 500
                api_params["response_format"] = {"type": "json_object"}
            
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=api_params
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
- For MEDICAID: Medicaid Managed Care, CHIP, specific state Medicaid products
- For COMMERCIAL: PPO, HMO, EPO, Exchange plans, specific commercial products

Return JSON with EXACTLY this format:
{{
  "plan_types": [
    "Specific Plan Type 1",
    "Specific Plan Type 2"
  ]
}}

Important:
- List ONLY plan types explicitly mentioned in the text
- Use the exact terminology from the document
- If multiple related plans are mentioned together (e.g., "MA PLAN/MA-PD PLAN/DSNP PLAN"), keep them grouped
- If no specific plan types are found, return ["{line_of_business} Product"]
"""
        
        try:
            # Adjust parameters based on model
            api_params = {
                "model": self.payment_model,
                "messages": [
                    {"role": "system", "content": "You are a healthcare insurance expert. Identify plan types accurately. Always return valid JSON."},
                    {"role": "user", "content": prompt}
                ]
            }
            
            # Handle parameter differences for different models
            if self.payment_model in ['o3', 'o1-mini']:
                api_params["max_completion_tokens"] = 300
            else:
                api_params["temperature"] = 0.1
                api_params["max_tokens"] = 300
                api_params["response_format"] = {"type": "json_object"}
            
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=api_params
            ) as response:
                self.total_api_calls += 1
                if response.status == 200:
                    result = await response.json()
                    parsed = json.loads(result['choices'][0]['message']['content'])
                    plan_types = parsed.get("plan_types", [])
                    
                    if not plan_types:
                        plan_types = [f"{line_of_business} Product"]
                    
                    logger.info(f"LLM identified plan types: {plan_types}")
                    return plan_types
                else:
                    logger.error(f"Error identifying plan types: {response.status}")
                    return [f"{line_of_business} Product"]
        except Exception as e:
            logger.error(f"Exception in plan type detection: {e}")
            return [f"{line_of_business} Product"]
    
    async def extract_payment_fields(self, session: aiohttp.ClientSession, 
                                   content: str, hierarchy: Dict[str, str],
                                   filename: str) -> List[Dict]:
        """Extract the 5 payment fields from content using GPT-4."""
        prompt = f"""
Analyze this medical contract compensation schedule and extract payment information.

Document: {filename}
Line of Business: {hierarchy['line_of_business']}
Service Type: {hierarchy['service_type']}

Text to analyze:
{content}

IMPORTANT CONTEXT: Payment fields are usually broad, meaning most combinations of line of business, provider type, service type, IP/OP, and plan type are covered the same way. However, look carefully for EXCEPTIONS and CLAUSES that may be mentioned elsewhere in the contract for specific services, provider types, or plan combinations.

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
- For "Reimb Methodology short", use abbreviations like MCR=Medicare, MCD=Medicaid
- Leave "Flat Fee" empty unless specific dollar amounts are mentioned
- If you find general payment terms, apply them unless there are specific exceptions for this service/plan combination
- Look for phrases like "except for", "however", "with the exception of", or service-specific sections that override general terms
"""
        
        try:
            # Adjust parameters based on model
            api_params = {
                "model": self.payment_model,
                "messages": [
                    {"role": "system", "content": "You are a medical contract expert. Extract payment information exactly as requested. Always return valid JSON."},
                    {"role": "user", "content": prompt}
                ]
            }
            
            # Handle parameter differences for different models
            if self.payment_model in ['o3', 'o1-mini']:
                api_params["max_completion_tokens"] = 1000
            else:
                api_params["temperature"] = 0.1
                api_params["max_tokens"] = 1000
                api_params["response_format"] = {"type": "json_object"}
            
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=api_params
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
        
        # Extract line of business using LLM
        line_of_business = await self.extract_line_of_business_with_llm(session, file_path.name, content)
        
        # Build base hierarchy
        base_hierarchy = {
            'line_of_business': line_of_business,
            'provider_type': 'Professional Services',  # Could also be made dynamic
            'ip_op': 'OP',  # Could also be made dynamic
            'service_type': None,
            'plan_type': None
        }
        
        # Find service categories using LLM
        service_types = await self.identify_service_categories_with_llm(session, content)
        
        # Extract plan types using LLM
        plan_types = await self.extract_plan_types_with_llm(session, content, line_of_business)
        
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
        """Run the LLM-based extraction pipeline."""
        logger.info("Starting LLM-based payment schedule extraction (v2)...")
        logger.info("This version uses AI to detect service categories and plan types dynamically.")
        
        # Find all compensation exhibit files
        exhibit_files = self.identify_compensation_exhibits()
        
        if not exhibit_files:
            logger.error("No compensation exhibit files found!")
            return
        
        logger.info(f"Found {len(exhibit_files)} exhibit files to process")
        
        all_results = {
            "extraction_date": datetime.now().isoformat(),
            "source_directory": str(self.schedule_dir),
            "extraction_method": "LLM-based (v2)",
            "payment_schedules": []
        }
        
        async with aiohttp.ClientSession() as session:
            for exhibit_file in exhibit_files:
                logger.info(f"\nProcessing exhibit: {exhibit_file.name}")
                results = await self.process_exhibit_file(session, exhibit_file)
                all_results["payment_schedules"].extend(results)
        
        # Save results
        output_path = f"{self.output_dir}/{self.output_filename}"
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
        logger.info(f"Total API calls made: {self.total_api_calls}")
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
        
        # Show detected service categories
        all_services = set()
        for schedule in all_results["payment_schedules"]:
            all_services.add(schedule["hierarchy"]["service_type"])
        
        logger.info(f"\nDetected Service Categories: {sorted(all_services)}")
        
        return all_results


async def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Extract payment schedules from medical contracts')
    parser.add_argument('--input-dir', '-i', type=str, default='data/headers/schedule',
                       help='Input directory containing contract files (default: data/headers/schedule)')
    parser.add_argument('--output-dir', '-o', type=str, default='data/output',
                       help='Output directory for results (default: data/output)')
    parser.add_argument('--output-file', type=str, default='payment_schedules_v2_llm.json',
                       help='Output filename (default: payment_schedules_v2_llm.json)')
    parser.add_argument('--input-file', '-f', type=str,
                       help='Single input file to process (overrides input-dir)')
    parser.add_argument('--model', '-m', type=str, default='gpt-4o-mini',
                       choices=['gpt-4o-mini', 'gpt-4-turbo', 'gpt-4', 'o3-mini', 'o1-mini', 'gpt-4.1', 'o3'],
                       help='Model to use for payment extraction (default: gpt-4o-mini)')
    
    args = parser.parse_args()
    
    # Get OpenAI API key
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("Please set OPENAI_API_KEY environment variable")
        return
    
    extractor = LLMBasedPaymentScheduleExtractor(api_key)
    
    # Set the model for payment extraction
    extractor.payment_model = args.model
    
    # Set output filename
    extractor.output_filename = args.output_file
    
    # Set input directory or file
    if args.input_file:
        extractor.schedule_dir = Path(args.input_file).parent
        extractor.single_file = Path(args.input_file)
    else:
        extractor.schedule_dir = Path(args.input_dir)
        extractor.single_file = None
    
    # Set output directory
    extractor.output_dir = Path(args.output_dir)
    
    await extractor.run()


if __name__ == "__main__":
    asyncio.run(main()) 