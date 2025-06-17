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

class LLMBasedPaymentScheduleExtractor:
    """
    Version 2: Uses LLM for service category and plan type detection
    instead of hardcoded patterns, making it more flexible for new document types.
    """
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.test_file = Path("data/test_text.md")
        self.total_api_calls = 0
        
    def identify_compensation_exhibits(self) -> List[Path]:
        """Return the test file path."""
        if self.test_file.exists():
            logger.info(f"Using test file: {self.test_file.name}")
            return [self.test_file]
        else:
            logger.error("Test file not found!")
            return []
    
    async def extract_line_of_business_with_llm(self, session: aiohttp.ClientSession, 
                                                filename: str, content: str) -> str:
        """Use LLM to determine line of business from filename and content."""
        prompt = f"""
Analyze this medical contract filename and content to determine the Line of Business.

Filename: {filename}

Content:
{content}

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
{content}

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
{content}

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
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": "You are a healthcare insurance expert. Identify plan types accurately. Always return valid JSON."},
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
        # This remains the same as the original
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
- For "Lesser of Rate", use the Table 1 rate for this service if available
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
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": "You are a medical contract expert. Extract payment information exactly as requested. Always return valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 1000,
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
        
        # Run initial detection calls in parallel for faster processing
        detection_tasks = [
            self.extract_line_of_business_with_llm(session, file_path.name, content),
            self.identify_service_categories_with_llm(session, content)
        ]
        
        line_of_business, service_types = await asyncio.gather(*detection_tasks)
        
        # Plan types extraction needs line_of_business, so run it after
        plan_types = await self.extract_plan_types_with_llm(session, content, line_of_business)
        
        # Identify which combinations actually exist in the document
        valid_combinations = await self.identify_valid_combinations(
            session, content, service_types, plan_types, line_of_business
        )
        
        logger.info(f"All detected services: {service_types}")
        logger.info(f"All detected plans: {plan_types}")
        logger.info(f"Valid combinations to process: {len(valid_combinations)}")
        
        # Build base hierarchy
        base_hierarchy = {
            'line_of_business': line_of_business,
            'provider_type': 'Professional Services',  # Could also be made dynamic
            'ip_op': 'OP',  # Could also be made dynamic
            'service_type': None,
            'plan_type': None
        }
        
        # Process only the valid combinations
        for combination in valid_combinations:
            hierarchy = base_hierarchy.copy()
            hierarchy['service_type'] = combination['service_type']
            hierarchy['plan_type'] = combination['plan_type']
            
            logger.info(f"Processing: {file_path.name} - {combination['service_type']} - {combination['plan_type']}")
            logger.info(f"  Rationale: {combination['rationale']}")
            logger.info(f"  Has specific rates: {combination['has_specific_rates']}")
            
            # Extract payment fields
            fields = await self.extract_payment_fields(
                session, content, hierarchy, file_path.name
            )
            
            # Evaluate data quality using sophisticated assessment
            quality_assessment = self.evaluate_payment_data_quality(fields, combination)
            
            logger.info(f"  Quality Assessment:")
            logger.info(f"    Meaningful: {quality_assessment['is_meaningful']}")
            logger.info(f"    Confidence: {quality_assessment['confidence_score']:.2f}")
            logger.info(f"    Quality indicators: {len(quality_assessment['quality_indicators'])}")
            logger.info(f"    Red flags: {len(quality_assessment['red_flags'])}")
            
            if quality_assessment['is_meaningful'] or combination['has_specific_rates']:
                # Add document name and metadata to each field
                for field in fields:
                    field["document_name"] = f"{file_path.name} - {combination['service_type']}"
                    field["combination_rationale"] = combination['rationale']
                    field["has_specific_rates"] = combination['has_specific_rates']
                
                # Create the payment schedule entry
                schedule_entry = {
                    "source_file": file_path.name,
                    "hierarchy": hierarchy,
                    "payment_fields": fields,
                    "combination_info": combination,
                    "quality_assessment": quality_assessment,
                    "metadata": {
                        "all_detected_services": service_types,
                        "all_detected_plans": plan_types
                    }
                }
                
                results.append(schedule_entry)
            else:
                logger.info(f"  Skipping - data quality assessment failed")
                for red_flag in quality_assessment['red_flags']:
                    logger.info(f"    Red flag: {red_flag}")
            
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.2)
        
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
            "source_directory": str(self.test_file),
            "extraction_method": "LLM-based (v2)",
            "payment_schedules": []
        }
        
        async with aiohttp.ClientSession() as session:
            for exhibit_file in exhibit_files:
                logger.info(f"\nProcessing exhibit: {exhibit_file.name}")
                results = await self.process_exhibit_file(session, exhibit_file)
                all_results["payment_schedules"].extend(results)
        
        # Save results
        output_path = "data/output/payment_schedules_v2_llm.json"
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

    async def identify_valid_combinations(self, session: aiohttp.ClientSession,
                                         content: str, service_types: List[str], 
                                         plan_types: List[str], line_of_business: str) -> List[Dict[str, str]]:
        """Use LLM to identify which service-plan combinations actually exist in the document."""
        prompt = f"""
Analyze this medical contract content for the {line_of_business} line of business and identify which SPECIFIC service-plan combinations actually have payment information or are explicitly mentioned together.

Content to analyze:
{content}

Detected Service Types: {service_types}
Detected Plan Types: {plan_types}

Look for:
1. Tables or sections that specify payment rates for specific services
2. Service categories that are explicitly mentioned with specific plans
3. Any service-plan combinations that have distinct payment methodologies
4. Skip combinations where there's no specific mention or payment information

Return JSON with EXACTLY this format:
{{
  "valid_combinations": [
    {{
      "service_type": "Specific Service Name",
      "plan_type": "Specific Plan Name",
      "has_specific_rates": true/false,
      "rationale": "why this combination is valid"
    }}
  ]
}}

Important:
- Only include combinations that actually exist in the document
- Set "has_specific_rates" to true if there are specific payment rates for this combination
- If no specific combinations are found, return at least one general combination
- Be conservative - better to miss a combination than create fake ones
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
                        {"role": "system", "content": "You are a medical contract expert. Identify valid service-plan combinations accurately. Always return valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 800,
                    "response_format": {"type": "json_object"}
                }
            ) as response:
                self.total_api_calls += 1
                if response.status == 200:
                    result = await response.json()
                    parsed = json.loads(result['choices'][0]['message']['content'])
                    combinations = parsed.get("valid_combinations", [])
                    
                    if not combinations:
                        # Fallback to at least one combination
                        combinations = [{
                            "service_type": service_types[0] if service_types else "Professional Services",
                            "plan_type": plan_types[0] if plan_types else f"{line_of_business} Product",
                            "has_specific_rates": False,
                            "rationale": "Fallback combination"
                        }]
                    
                    logger.info(f"LLM identified {len(combinations)} valid combinations")
                    return combinations
                else:
                    logger.error(f"Error identifying valid combinations: {response.status}")
                    return [{
                        "service_type": service_types[0] if service_types else "Professional Services",
                        "plan_type": plan_types[0] if plan_types else f"{line_of_business} Product",
                        "has_specific_rates": False,
                        "rationale": "Error fallback"
                    }]
        except Exception as e:
            logger.error(f"Exception in combination detection: {e}")
            return [{
                "service_type": service_types[0] if service_types else "Professional Services",
                "plan_type": plan_types[0] if plan_types else f"{line_of_business} Product",
                "has_specific_rates": False,
                "rationale": "Exception fallback"
            }]

    def evaluate_payment_data_quality(self, fields: List[Dict], combination: Dict) -> Dict[str, Any]:
        """
        Evaluate the quality and meaningfulness of extracted payment data.
        Returns a detailed assessment of the data quality.
        """
        assessment = {
            "is_meaningful": False,
            "has_specific_rates": False,
            "has_service_specific_info": False,
            "has_plan_specific_info": False,
            "confidence_score": 0.0,
            "quality_indicators": [],
            "red_flags": []
        }
        
        service_type = combination.get('service_type', '').lower()
        plan_type = combination.get('plan_type', '').lower()
        
        for field in fields:
            value = field.get('value', '').strip()
            citation = field.get('citation', '').strip()
            field_name = field.get('data_point_name', '')
            
            if not value:
                continue
                
            # Check for specific rates/percentages
            if any(indicator in value.lower() for indicator in [
                '%', 'percent', '$', 'dollar', 'fee schedule', 'rate', 'per unit'
            ]):
                assessment["has_specific_rates"] = True
                assessment["quality_indicators"].append(f"{field_name}: Contains specific rate information")
                assessment["confidence_score"] += 0.3
            
            # Check for service-specific mentions
            if service_type in value.lower() or service_type in citation.lower():
                assessment["has_service_specific_info"] = True
                assessment["quality_indicators"].append(f"{field_name}: Service-specific information found")
                assessment["confidence_score"] += 0.2
            
            # Check for plan-specific mentions  
            if plan_type in value.lower() or plan_type in citation.lower():
                assessment["has_plan_specific_info"] = True
                assessment["quality_indicators"].append(f"{field_name}: Plan-specific information found")
                assessment["confidence_score"] += 0.2
            
            # Check for generic/boilerplate language
            generic_phrases = [
                "as set forth herein",
                "pursuant to this agreement", 
                "covered services",
                "contracted provider",
                "allowable charges"
            ]
            if any(phrase in value.lower() for phrase in generic_phrases):
                assessment["red_flags"].append(f"{field_name}: Contains generic language")
                assessment["confidence_score"] -= 0.1
            
            # Check for empty or meaningless values
            if value.lower() in ["", "n/a", "not applicable", "see agreement", "as applicable"]:
                assessment["red_flags"].append(f"{field_name}: Empty or meaningless value")
                assessment["confidence_score"] -= 0.1
        
        # Determine if data is meaningful
        assessment["is_meaningful"] = (
            assessment["confidence_score"] > 0.3 or
            assessment["has_specific_rates"] or
            (assessment["has_service_specific_info"] and assessment["has_plan_specific_info"])
        )
        
        # Cap confidence score
        assessment["confidence_score"] = max(0.0, min(1.0, assessment["confidence_score"]))
        
        return assessment


async def main():
    # Get OpenAI API key
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("Please set OPENAI_API_KEY environment variable")
        return
    
    extractor = LLMBasedPaymentScheduleExtractor(api_key)
    await extractor.run()


if __name__ == "__main__":
    asyncio.run(main()) 