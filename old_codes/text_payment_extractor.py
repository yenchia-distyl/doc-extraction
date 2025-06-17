import json
import os
from typing import Dict, List, Any
import asyncio
import aiohttp
from datetime import datetime
import logging
import argparse
import time
from pathlib import Path

# Try to load .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TextPaymentExtractor:
    """
    Simplified payment schedule extractor that works with text input only.
    Uses the same LLM-based extraction logic as the flex version but eliminates
    file handling and header processing.
    """
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.total_api_calls = 0
        
    async def extract_line_of_business_with_llm(self, session: aiohttp.ClientSession, 
                                                content: str) -> str:
        """Use LLM to determine line of business from content only."""
        prompt = f"""
Analyze this medical contract content to determine the Line of Business.

Content to analyze:
{content[:1000]}

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

Be precise and use standard industry terminology. Look for keywords, plan names, and regulatory references to determine the line of business.
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
{content[:3000]}

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
                                   document_name: str = "Text Input") -> List[Dict]:
        """Extract the 5 payment fields from content using GPT-4."""
        prompt = f"""
Analyze this medical contract compensation schedule and extract payment information.

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
                                    "document_name": document_name
                                })
                        
                        if len(fields) != 5:
                            logger.warning(f"Expected 5 fields but got {len(fields)}")
                            return self._create_empty_fields(document_name)
                        
                        return fields
                        
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse JSON response: {e}")
                        return self._create_empty_fields(document_name)
                else:
                    error_text = await response.text()
                    logger.error(f"API error: {response.status} - {error_text}")
                    return self._create_empty_fields(document_name)
                    
        except Exception as e:
            logger.error(f"Exception during extraction: {str(e)}")
            return self._create_empty_fields(document_name)
    
    def _create_empty_fields(self, document_name: str = "") -> List[Dict]:
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
                "document_name": document_name
            }
            for name in field_names
        ]
    
    async def extract_from_text(self, text_content: str, document_name: str = "Text Input") -> Dict[str, Any]:
        """
        Main method to extract payment schedule information from a block of text.
        
        Args:
            text_content: The text content to analyze
            document_name: Optional name for the document (for tracking purposes)
            
        Returns:
            Dictionary containing all extracted payment schedule information
        """
        logger.info(f"Starting text-based extraction for: {document_name}")
        
        async with aiohttp.ClientSession() as session:
            # Extract line of business using LLM
            line_of_business = await self.extract_line_of_business_with_llm(session, text_content)
            
            # Find service categories using LLM
            service_types = await self.identify_service_categories_with_llm(session, text_content)
            
            # Extract plan types using LLM
            plan_types = await self.extract_plan_types_with_llm(session, text_content, line_of_business)
            
            # Create results for each combination
            payment_schedules = []
            
            for service_type in service_types:
                for plan_type in plan_types:
                    hierarchy = {
                        'line_of_business': line_of_business,
                        'provider_type': 'Professional Services',  # Default
                        'ip_op': 'OP',  # Default to outpatient
                        'service_type': service_type,
                        'plan_type': plan_type
                    }
                    
                    logger.info(f"Processing combination: {service_type} - {plan_type}")
                    
                    # Extract payment fields
                    fields = await self.extract_payment_fields(
                        session, text_content, hierarchy, f"{document_name} - {service_type}"
                    )
                    
                    # Create the payment schedule entry
                    schedule_entry = {
                        "source": document_name,
                        "hierarchy": hierarchy,
                        "payment_fields": fields
                    }
                    
                    payment_schedules.append(schedule_entry)
                    
                    # Small delay to avoid rate limiting
                    await asyncio.sleep(0.5)
        
        # Compile final results
        results = {
            "extraction_date": datetime.now().isoformat(),
            "source_document": document_name,
            "extraction_method": "Text-based LLM extraction",
            "total_api_calls": self.total_api_calls,
            "detected_line_of_business": line_of_business,
            "detected_service_types": service_types,
            "detected_plan_types": plan_types,
            "payment_schedules": payment_schedules
        }
        
        # Log summary
        total_schedules = len(payment_schedules)
        schedules_with_data = sum(
            1 for schedule in payment_schedules
            if any(field["value"] for field in schedule["payment_fields"])
        )
        
        logger.info(f"\n=== TEXT EXTRACTION COMPLETE ===")
        logger.info(f"Document: {document_name}")
        logger.info(f"Line of Business: {line_of_business}")
        logger.info(f"Service Types: {service_types}")
        logger.info(f"Plan Types: {plan_types}")
        logger.info(f"Total payment schedules created: {total_schedules}")
        logger.info(f"Schedules with extracted data: {schedules_with_data}")
        logger.info(f"Total API calls made: {self.total_api_calls}")
        
        return results


# Convenience function for quick extraction
async def extract_payment_info(text_content: str, api_key: str = None, document_name: str = "Text Input") -> Dict[str, Any]:
    """
    Convenience function to extract payment information from text.
    
    Args:
        text_content: The text to analyze
        api_key: OpenAI API key (if None, will try to get from environment)
        document_name: Optional document name for tracking
        
    Returns:
        Dictionary with extracted payment information
    """
    if api_key is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("API key must be provided or set in OPENAI_API_KEY environment variable")
    
    extractor = TextPaymentExtractor(api_key)
    return await extractor.extract_from_text(text_content, document_name)


def create_parser():
    """Create command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Extract payment schedule information from contract text using LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract from file
  python text_payment_extractor.py --input data/test_text.md
  
  # Extract with custom output file
  python text_payment_extractor.py --input contract.txt --output results.json
  
  # Extract with timing information
  python text_payment_extractor.py --input contract.txt --timing
  
  # Extract from stdin
  cat contract.txt | python text_payment_extractor.py --input -
        """
    )
    
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Input file path (use '-' for stdin)"
    )
    
    parser.add_argument(
        "--output", "-o",
        help="Output JSON file path (default: auto-generated)"
    )
    
    parser.add_argument(
        "--api-key",
        help="OpenAI API key (default: from OPENAI_API_KEY env var)"
    )
    
    parser.add_argument(
        "--timing",
        action="store_true",
        help="Show timing and performance metrics"
    )
    
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Reduce output verbosity"
    )
    
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty print results to stdout"
    )
    
    return parser


async def main_cli():
    """Main CLI function."""
    parser = create_parser()
    args = parser.parse_args()
    
    # Set up logging level
    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)
    
    # Get API key
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("❌ Error: OpenAI API key required. Set OPENAI_API_KEY env var or use --api-key")
        return 1
    
    # Read input
    try:
        if args.input == "-":
            # Read from stdin
            import sys
            content = sys.stdin.read()
            document_name = "stdin"
        else:
            # Read from file
            input_path = Path(args.input)
            if not input_path.exists():
                print(f"❌ Error: Input file not found: {args.input}")
                return 1
            
            with open(input_path, "r", encoding="utf-8") as f:
                content = f.read()
            document_name = input_path.name
    except Exception as e:
        print(f"❌ Error reading input: {e}")
        return 1
    
    # Start timing if requested
    start_time = time.time() if args.timing else None
    
    try:
        # Extract payment information
        print(f"🚀 Extracting payment information from: {document_name}")
        if args.timing:
            print(f"📊 Content size: {len(content):,} characters")
        
        results = await extract_payment_info(content, api_key, document_name)
        
        # Calculate timing
        if args.timing:
            end_time = time.time()
            total_time = end_time - start_time
            chars_per_second = len(content) / total_time
            print(f"⏱️  Extraction completed in {total_time:.2f} seconds")
            print(f"⚡ Processing speed: {chars_per_second:,.0f} chars/second")
            print(f"🔧 API calls made: {results['total_api_calls']}")
        
        # Determine output file
        if args.output:
            output_file = args.output
        else:
            timestamp = int(time.time())
            safe_name = "".join(c for c in document_name if c.isalnum() or c in "._-")
            output_file = f"extraction_results_{safe_name}_{timestamp}.json"
        
        # Save results
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2)
        
        print(f"💾 Results saved to: {output_file}")
        
        # Show summary
        print(f"\n📋 EXTRACTION SUMMARY:")
        print(f"   Line of Business: {results['detected_line_of_business']}")
        print(f"   Service Types: {len(results['detected_service_types'])}")
        print(f"   Plan Types: {len(results['detected_plan_types'])}")
        print(f"   Payment Schedules: {len(results['payment_schedules'])}")
        
        # Count schedules with data
        schedules_with_data = sum(
            1 for schedule in results['payment_schedules']
            if any(field["value"] for field in schedule["payment_fields"])
        )
        print(f"   Schedules with data: {schedules_with_data}/{len(results['payment_schedules'])}")
        
        # Pretty print if requested
        if args.pretty:
            print(f"\n📄 DETAILED RESULTS:")
            print("=" * 50)
            print(json.dumps(results, indent=2))
        
        return 0
        
    except Exception as e:
        print(f"❌ Error during extraction: {e}")
        if args.timing and start_time:
            error_time = time.time() - start_time
            print(f"⏱️  Time before error: {error_time:.2f} seconds")
        return 1


# Example usage for backwards compatibility
async def main():
    """Example usage of the text payment extractor."""
    
    # Example text (you would replace this with actual contract text)
    sample_text = """
    MEDICAID COMPENSATION SCHEDULE
    
    Table 1: Radiology Services Compensation
    
    For all Radiology Services provided to Medicaid members, Provider shall be compensated 
    at the lesser of (a) Provider's usual and customary charges, or (b) 85% of the Medicare 
    Rate for such services.
    
    All claims shall be submitted within 90 days of service delivery.
    """
    
    # Get API key
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("Please set OPENAI_API_KEY environment variable")
        return
    
    # Extract payment information
    results = await extract_payment_info(sample_text, api_key, "Sample Contract")
    
    # Print results
    print(json.dumps(results, indent=2))
    
    # Optionally save to file
    with open("text_extraction_results.json", "w") as f:
        json.dump(results, f, indent=2)
    
    logger.info("Results saved to text_extraction_results.json")


if __name__ == "__main__":
    # Check if running as CLI or as example
    import sys
    if len(sys.argv) > 1:
        # CLI mode
        exit_code = asyncio.run(main_cli())
        exit(exit_code)
    else:
        # Example mode
        asyncio.run(main()) 