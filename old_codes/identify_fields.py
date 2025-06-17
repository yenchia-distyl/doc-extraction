import json
import re
import os
from pathlib import Path
from collections import defaultdict
from typing import Dict, Set, List, Tuple
import logging
import asyncio
import aiohttp

# Try to load .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class FieldIdentifier:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.document_path = Path("data/example_document.md")
        self.fields = {
            'line_of_business': set(),
            'provider_type': set(),
            'ip_op': set(),
            'service_type': set(),
            'plan_type': set()
        }
        self.nested_structure = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(set))))
        
    def load_document(self) -> str:
        """Load the example document."""
        with open(self.document_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    async def identify_field_values(self, session: aiohttp.ClientSession, content: str, field_type: str) -> List[str]:
        """Use LLM to identify all values for a specific field type."""
        
        field_prompts = {
            'line_of_business': """
Analyze this medical contract and identify ALL lines of business mentioned.
Lines of business are typically major divisions of healthcare coverage (e.g., government programs, commercial insurance).

Return a JSON array of all unique lines of business found.
Extract the exact names as they appear in the document.
""",
            'provider_type': """
Analyze this medical contract and identify ALL provider types mentioned.
Provider types are categories of healthcare providers or facilities that deliver services.

Return a JSON array of all unique provider types found.
Extract the exact names as they appear in the document.
""",
            'ip_op': """
Analyze this medical contract and identify whether it covers inpatient and/or outpatient services.
Look for mentions of:
- Inpatient/IP
- Outpatient/OP
- Both

Return a JSON array with standardized values ["IP", "OP"] based on what's mentioned.
""",
            'service_type': """
Analyze this medical contract and identify ALL service types mentioned.
Service types are specific categories of medical services or procedures.

Pay special attention to:
- Tables listing service categories
- Compensation schedules
- Service descriptions
- Fee schedules

Return a JSON array of all unique service types found.
Extract the exact names as they appear in the document.
""",
            'plan_type': """
Analyze this medical contract and identify ALL specific plan or product names mentioned.

Look for plan/product names in:
- Headers and titles
- Attachment names
- Compensation schedules
- EXHIBIT sections
- Product descriptions
- Sections that define coverage types

Important: Return the EXACT plan/product names as they appear, including:
- Combined names with slashes or dashes
- Acronyms and abbreviations
- Full product names

Return a JSON array of all unique plan/product names EXACTLY as they appear in the document.
"""
        }
        
        prompt = field_prompts.get(field_type, "")
        if not prompt:
            return []
        
        try:
            # Create targeted content based on field type
            truncated_content = await self.extract_relevant_sections(content, field_type)
            
            response = await session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": "You are a medical contract analyst. Extract information and return only valid JSON arrays."},
                        {"role": "user", "content": f"{prompt}\n\nDocument:\n{truncated_content}"}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 500
                }
            )
            
            if response.status == 200:
                result = await response.json()
                content_str = result['choices'][0]['message']['content']
                
                # Extract JSON array from response
                json_match = re.search(r'\[.*?\]', content_str, re.DOTALL)
                if json_match:
                    values = json.loads(json_match.group())
                    return [str(v).strip() for v in values]
                else:
                    logger.warning(f"No JSON array found in response for {field_type}")
                    return []
            else:
                logger.error(f"API error for {field_type}: {response.status}")
                return []
                
        except Exception as e:
            logger.error(f"Error identifying {field_type}: {str(e)}")
            return []
    
    async def extract_relevant_sections(self, content: str, field_type: str) -> str:
        """Extract sections of the document most relevant to the field type."""
        sections = []
        
        # Common patterns to look for important sections
        section_patterns = {
            'headers': r'((?:Attachment|ATTACHMENT|Exhibit|EXHIBIT|Schedule|SCHEDULE)\s+[A-Z0-9]+[:\s].*?)(?=\n{2,}|\Z)',
            'compensation': r'(COMPENSATION\s+SCHEDULE.*?)(?=\n{2,}|COMPENSATION\s+SCHEDULE|\Z)',
            'tables': r'(Table\s+\d+.*?)(?=\n{2,}|Table\s+\d+|\Z)',
            'definitions': r'((?:Definitions?|DEFINITIONS?)[:\s].*?)(?=\n{2,}|\Z)',
            'products': r'((?:Product|PRODUCT|Plan|PLAN)\s+(?:Attachment|ATTACHMENT|Type|TYPE).*?)(?=\n{2,}|\Z)'
        }
        
        # Extract sections based on patterns
        for pattern_name, pattern in section_patterns.items():
            matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)
            for match in matches[:3]:  # Limit to first 3 of each type
                sections.append(match[:1000])  # Limit each section length
        
        # For specific field types, add targeted extraction
        if field_type == 'plan_type':
            # Look for sections that commonly contain plan/product names
            plan_indicators = ['product', 'plan', 'coverage', 'benefit', 'program']
            for indicator in plan_indicators:
                pattern = rf'(.{{0,200}}\b{indicator}\b.{{0,200}})'
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches[:5]:
                    sections.append(match)
        
        elif field_type == 'service_type':
            # Look for sections with service listings
            service_indicators = ['service', 'procedure', 'treatment', 'therapy', 'care']
            for indicator in service_indicators:
                pattern = rf'(.{{0,200}}\b{indicator}\b.{{0,200}})'
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches[:5]:
                    sections.append(match)
        
        # If no targeted sections found, use beginning of document
        if not sections:
            sections.append(content[:15000])
        
        return "\n\n---\n\n".join(sections)
    
    async def build_nested_structure_with_llm(self, session: aiohttp.ClientSession, content: str) -> Dict:
        """Use LLM to understand relationships between fields."""
        
        prompt = f"""
Analyze this medical contract and identify the hierarchical relationships between:
1. Lines of Business
2. Provider Types
3. IP/OP (Inpatient/Outpatient)
4. Service Types
5. Plan Types

Focus on which provider types operate under which lines of business, what services they provide, and what plans they accept.

Return ONLY a valid JSON structure showing these relationships in nested format.
The structure should follow the hierarchy: Line of Business > Provider Type > IP/OP > Service Type > Plan Types

Example format (use actual values from the document):
{{
  "LINE_OF_BUSINESS_NAME": {{
    "PROVIDER_TYPE_NAME": {{
      "IP_or_OP": {{
        "SERVICE_TYPE_NAME": ["PLAN_TYPE_1", "PLAN_TYPE_2"]
      }}
    }}
  }}
}}
"""
        
        try:
            # Extract key sections for analysis
            sections_to_analyze = await self.extract_relevant_sections(content, 'nested_structure')
            
            response = await session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": "You are a medical contract analyst. Return only valid JSON without any markdown formatting or extra text."},
                        {"role": "user", "content": f"{prompt}\n\nDocument sections:\n{sections_to_analyze}"}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 2000,
                    "response_format": {"type": "json_object"}
                }
            )
            
            if response.status == 200:
                result = await response.json()
                content_str = result['choices'][0]['message']['content']
                
                try:
                    # Try to parse the JSON directly
                    structure = json.loads(content_str)
                    return structure
                except json.JSONDecodeError:
                    # If direct parsing fails, try to extract JSON
                    json_match = re.search(r'\{.*\}', content_str, re.DOTALL)
                    if json_match:
                        try:
                            structure = json.loads(json_match.group())
                            return structure
                        except:
                            pass
                    
                    logger.warning("Could not parse LLM response for nested structure")
                    
            else:
                logger.error(f"API error for nested structure: {response.status}")
                
        except Exception as e:
            logger.error(f"Error building nested structure: {str(e)}")
        
        # Return a minimal structure if LLM fails
        logger.info("Using minimal fallback structure")
        return self.build_minimal_structure()
    
    def build_minimal_structure(self) -> Dict:
        """Build a minimal structure from identified fields."""
        structure = {}
        
        # Create a basic structure using identified fields
        for lob in self.fields.get('line_of_business', []):
            structure[lob] = {}
            
            # Add a default provider type if none identified
            provider_types = list(self.fields.get('provider_type', []))
            if not provider_types:
                provider_types = ['General Provider']
            
            # Use first provider type as example
            if provider_types:
                structure[lob][provider_types[0]] = {
                    "OP": {
                        "General Services": ["Standard Plan"]
                    }
                }
        
        return structure
    
    async def analyze_document(self) -> Dict:
        """Main method to analyze the document and extract all field values."""
        logger.info("Loading document...")
        content = self.load_document()
        
        async with aiohttp.ClientSession() as session:
            logger.info("Identifying field values using LLM...")
            
            # Identify all values for each field
            tasks = []
            for field_type in self.fields.keys():
                tasks.append(self.identify_field_values(session, content, field_type))
            
            results = await asyncio.gather(*tasks)
            
            # Store results
            for field_type, values in zip(self.fields.keys(), results):
                self.fields[field_type] = set(values)
                logger.info(f"Found {len(values)} {field_type} values")
            
            logger.info("Building nested structure using LLM...")
            nested_structure = await self.build_nested_structure_with_llm(session, content)
        
        # Convert sets to lists for JSON serialization
        fields_list = {k: sorted(list(v)) for k, v in self.fields.items()}
        
        result = {
            'field_values': fields_list,
            'field_counts': {k: len(v) for k, v in self.fields.items()},
            'nested_structure': nested_structure,
            'analysis_summary': self.generate_summary()
        }
        
        return result
    
    def generate_summary(self) -> Dict:
        """Generate a summary of the findings."""
        return {
            'total_lines_of_business': len(self.fields['line_of_business']),
            'total_provider_types': len(self.fields['provider_type']),
            'total_service_types': len(self.fields['service_type']),
            'total_plan_types': len(self.fields['plan_type']),
            'has_ip_op_distinction': len(self.fields['ip_op']) > 0
        }
    
    def save_results(self, results: Dict, output_path: str = "data/output/identified_fields.json"):
        """Save the analysis results to a JSON file."""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"Results saved to {output_path}")
    
    def print_results(self, results: Dict):
        """Print a formatted summary of the results."""
        print("\n" + "="*60)
        print("FIELD IDENTIFICATION RESULTS")
        print("="*60)
        
        print("\n## FIELD VALUES FOUND:")
        for field, values in results['field_values'].items():
            print(f"\n### {field.replace('_', ' ').title()} ({len(values)} values):")
            for value in sorted(values):
                print(f"  - {value}")
        
        print("\n## NESTED STRUCTURE:")
        def print_nested(d, indent=0):
            if isinstance(d, dict):
                for k, v in sorted(d.items()):
                    print("  " * indent + f"{k}:")
                    print_nested(v, indent + 1)
            elif isinstance(d, list):
                print("  " * indent + f"{', '.join(sorted(d))}")
            else:
                print("  " * indent + str(d))
        
        print_nested(results['nested_structure'])
        
        print("\n## SUMMARY:")
        for key, value in results['analysis_summary'].items():
            print(f"  {key.replace('_', ' ').title()}: {value}")
        print("="*60)


async def main():
    """Main function to run the field identification analysis."""
    # Get OpenAI API key
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("Please set OPENAI_API_KEY environment variable")
        return
    
    identifier = FieldIdentifier(api_key)
    results = await identifier.analyze_document()
    identifier.save_results(results)
    identifier.print_results(results)


if __name__ == "__main__":
    asyncio.run(main()) 