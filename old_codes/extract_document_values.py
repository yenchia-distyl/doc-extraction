import json
import os
import re
from typing import Dict, List, Any
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

# Fields to extract
SCHEMA_FIELDS = {
    # Hierarchical classification fields
    "Provider Type",
    "IP/OP", 
    "Service Type",
    "Plan Type",
    
    # Payment fields (leaf level)
    "Lesser of Logic Language included (Y/N)",
    "Lesser of Rate",
    "Reimb Methodology",
    "Reimb Methodology short",
    "Flat Fee"
}

class DocumentExtractor:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers_dir = Path("data/headers")
        self.field_definitions = self._load_field_definitions()
        self.extractor_prompt = self._load_extractor_prompt()
        
    def _load_field_definitions(self) -> Dict:
        """Load field definitions from JSON file."""
        with open("data/field_definitions.json", "r") as f:
            definitions = json.load(f)
        
        # Create a mapping of field names to their definitions
        field_map = {}
        for section in definitions.get("sections", []):
            for data_point in section.get("data_points", []):
                field_map[data_point["data_point_name"]] = data_point
        return field_map
    
    def _load_extractor_prompt(self) -> str:
        """Load the extraction prompt template."""
        with open("prompts/extractor_prompt.txt", "r") as f:
            return f.read()
    
    def _prepare_field_template(self, fields: set) -> List[Dict]:
        """Prepare the field template for the LLM prompt."""
        template = []
        for field_name in fields:
            # Normalize field name for matching
            normalized_name = field_name.lower().replace(" ", "_").replace("-", "_")
            
            # Find matching definition
            matching_def = None
            for def_name, definition in self.field_definitions.items():
                if def_name.lower().replace(" ", "_").replace("-", "_") == normalized_name:
                    matching_def = definition
                    break
            
            if matching_def:
                template.append(matching_def)
            else:
                # Create a basic template if definition not found
                template.append({
                    "data_point_name": field_name,
                    "description": f"Extract {field_name} from the document",
                    "related_routine_steps": [],
                    "rationale": "",
                    "extraction_instructions": "",
                    "examples": ""
                })
        
        return template
    
    async def extract_from_chunk(self, session: aiohttp.ClientSession, chunk_content: str, 
                                chunk_name: str, fields: set) -> Dict:
        """Extract fields from a single chunk using GPT-4o-mini."""
        field_template = self._prepare_field_template(fields)
        
        # Build the prompt
        prompt = f"""
{self.extractor_prompt}

ir_template:
{json.dumps(field_template, indent=2)}

Text:
{chunk_content}
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
                        {"role": "system", "content": "You are a legal expert specializing in contract law extraction."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"}
                }
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    extracted_json = json.loads(result['choices'][0]['message']['content'])
                    logger.info(f"Successfully extracted from {chunk_name}")
                    return {
                        "chunk_name": chunk_name,
                        "extracted_fields": extracted_json.get("extracted_fields", [])
                    }
                else:
                    error_text = await response.text()
                    logger.error(f"Error extracting from {chunk_name}: {response.status} - {error_text}")
                    return {"chunk_name": chunk_name, "extracted_fields": [], "error": error_text}
                    
        except Exception as e:
            logger.error(f"Exception extracting from {chunk_name}: {str(e)}")
            return {"chunk_name": chunk_name, "extracted_fields": [], "error": str(e)}
    
    async def extract_all_chunks(self, batch_size: int = 5) -> List[Dict]:
        """Extract from all chunks in batches."""
        # Get all header files
        header_files = list(self.headers_dir.glob("*.md"))
        logger.info(f"Found {len(header_files)} header files to process")
        
        all_results = []
        
        async with aiohttp.ClientSession() as session:
            # Process in batches
            for i in range(0, len(header_files), batch_size):
                batch = header_files[i:i + batch_size]
                logger.info(f"Processing batch {i//batch_size + 1} ({len(batch)} files)")
                
                # Prepare tasks for this batch
                tasks = []
                for file_path in batch:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    
                    task = self.extract_from_chunk(
                        session, 
                        content, 
                        file_path.name,
                        SCHEMA_FIELDS
                    )
                    tasks.append(task)
                
                # Execute batch
                batch_results = await asyncio.gather(*tasks)
                all_results.extend(batch_results)
                
                # Small delay between batches to avoid rate limiting
                if i + batch_size < len(header_files):
                    await asyncio.sleep(1)
        
        return all_results
    
    def _determine_section_hierarchy(self, chunk_name: str, extracted_fields: List[Dict]) -> Dict[str, Any]:
        """Determine the section hierarchy based on chunk name and extracted fields."""
        # Clean up chunk name
        clean_name = chunk_name.replace(".md", "").replace("_", " ")
        
        # Determine section type based on patterns
        section_info = {
            "section_name": clean_name,
            "section_type": None
        }
        
        # Check for line of business indicators
        if "medicaid" in clean_name.lower():
            section_info["line_of_business"] = "MEDICAID"
        elif "medicare" in clean_name.lower():
            section_info["line_of_business"] = "MEDICARE"  
        elif "commercial" in clean_name.lower() or "exchange" in clean_name.lower():
            section_info["line_of_business"] = "COMMERCIAL-EXCHANGE"
        
        # Check for provider type indicators
        if "professional" in clean_name.lower():
            section_info["provider_type"] = "Professional Services"
        elif "facility" in clean_name.lower() or "hospital" in clean_name.lower():
            section_info["provider_type"] = "Facility Services"
        elif "ancillary" in clean_name.lower():
            section_info["provider_type"] = "Ancillary Services"
            
        return section_info
    
    def organize_results(self, extraction_results: List[Dict]) -> Dict:
        """
        Organize extraction results into the target nested structure.
        
        Target Hierarchy:
        Line Of Business
        └── Provider Type
            └── In Patient or Out Patient  
                └── Service Type
                    └── Plan Type
                        └── [5 payment fields] ← leaf level:
                            ├── "Lesser of Logic Language included (Y/N)"
                            ├── "Lesser of Rate"
                            ├── "Reimb Methodology" 
                            ├── "Reimb Methodology short"
                            └── "Flat Fee"
        
        Each payment field follows this structure:
        {
          "data_point_name": "[FIELD_NAME]",
          "value": "[EXTRACTED_VALUE]",
          "citation": "[EXACT_TEXT_FROM_DOCUMENT]",
          "rationale": "[EXPLANATION_OF_WHY_THIS_VALUE_WAS_CHOSEN]",
          "document_name": "[SOURCE_DOCUMENT_NAME]",
          "history": []
        }
        """
        # Initialize the output structure
        output = {
            "sections": [{
                "section_name": "Main Contract Details",
                "extracted_fields": [],
                "subsections": []
            }]
        }
        
        # Track nested structure: LOB -> Provider Type -> IP/OP -> Service Type -> Plan Type
        hierarchy_map = {}
        main_contract_fields = []
        
        for result in extraction_results:
            if "error" in result:
                continue
                
            chunk_name = result["chunk_name"]
            fields = result["extracted_fields"]
            
            if not fields:
                continue
            
            # Determine section hierarchy from chunk name and fields
            section_info = self._determine_section_hierarchy(chunk_name, fields)
            
            # Extract hierarchy components
            line_of_business = section_info.get("line_of_business")
            provider_type = section_info.get("provider_type", "General Services")
            
            # Extract IP/OP and Service Type from the extracted fields
            ip_op = None
            service_type = None
            plan_type = None
            
            for field in fields:
                field_name_lower = field.get("data_point_name", "").lower()
                if field_name_lower == "ip/op":
                    ip_op = field.get("value", "OP")
                elif field_name_lower == "service type":
                    service_type = field.get("value", "Covered Services")
                elif field_name_lower == "plan type":
                    plan_type = field.get("value", "Standard Plan")
            
            # Set defaults if not found
            if not ip_op:
                ip_op = "OP"
            if not service_type:
                service_type = "Covered Services"
            if not plan_type:
                plan_type = "Standard Plan"
            
            if line_of_business:
                # Build the 5-level hierarchy path
                hierarchy_key = f"{line_of_business}|{provider_type}|{ip_op}|{service_type}|{plan_type}"
                
                if hierarchy_key not in hierarchy_map:
                    hierarchy_map[hierarchy_key] = {
                        "line_of_business": line_of_business,
                        "provider_type": provider_type,
                        "ip_op": ip_op,
                        "service_type": service_type,
                        "plan_type": plan_type,
                        "payment_fields": []
                    }
                
                # Process only the 5 payment fields for the leaf level
                payment_field_names = {
                    "Lesser of Logic Language included (Y/N)",
                    "Lesser of Rate",
                    "Reimb Methodology",
                    "Reimb Methodology short",
                    "Flat Fee"
                }
                
                # Create lowercase versions for case-insensitive matching
                payment_field_names_lower = {name.lower() for name in payment_field_names}
                
                for field in fields:
                    field_name = field.get("data_point_name", "")
                    field_name_lower = field_name.lower()
                    
                    # Case-insensitive check for payment fields
                    if field_name_lower in payment_field_names_lower:
                        # Find the correct case version
                        correct_field_name = None
                        for correct_name in payment_field_names:
                            if correct_name.lower() == field_name_lower:
                                correct_field_name = correct_name
                                break
                        
                        # Format field according to specifications
                        payment_field = {
                            "data_point_name": correct_field_name or field_name,
                            "value": field.get("value", ""),
                            "citation": field.get("citation", ""),
                            "rationale": field.get("rationale", ""),
                            "document_name": chunk_name.replace(".md", "").replace("_", " "),
                            "history": []
                        }
                        hierarchy_map[hierarchy_key]["payment_fields"].append(payment_field)
            else:
                # No specific line of business - check if there are payment fields
                payment_field_names = {
                    "Lesser of Logic Language included (Y/N)",
                    "Lesser of Rate",
                    "Reimb Methodology",
                    "Reimb Methodology short",
                    "Flat Fee"
                }
                
                # Create lowercase versions for case-insensitive matching
                payment_field_names_lower = {name.lower() for name in payment_field_names}
                
                # Collect payment fields and non-payment fields separately
                general_payment_fields = []
                
                for field in fields:
                    field_name = field.get("data_point_name", "")
                    field_name_lower = field_name.lower()
                    
                    # Case-insensitive check for payment fields
                    if field_name_lower in payment_field_names_lower:
                        # Find the correct case version
                        correct_field_name = None
                        for correct_name in payment_field_names:
                            if correct_name.lower() == field_name_lower:
                                correct_field_name = correct_name
                                break
                        
                        # Format payment field
                        payment_field = {
                            "data_point_name": correct_field_name or field_name,
                            "value": field.get("value", ""),
                            "citation": field.get("citation", ""),
                            "rationale": field.get("rationale", ""),
                            "document_name": chunk_name.replace(".md", "").replace("_", " "),
                            "history": []
                        }
                        general_payment_fields.append(payment_field)
                    elif field_name not in {"IP/OP", "Service Type", "Plan Type", "Provider Type"}:
                        # Non-payment, non-hierarchy fields go to main contract
                        formatted_field = {
                            "data_point_name": field_name,
                            "value": field.get("value", ""),
                            "citation": field.get("citation", ""),
                            "rationale": field.get("rationale", ""),
                            "document_name": chunk_name.replace(".md", "").replace("_", " "),
                            "history": []
                        }
                        main_contract_fields.append(formatted_field)
                
                # Apply general payment fields to all lines of business
                if general_payment_fields:
                    # Get all extracted values for hierarchy from this chunk
                    chunk_ip_op = "OP"  # Default
                    chunk_service_type = "Covered Services"  # Default
                    chunk_plan_type = "Standard Plan"  # Default
                    
                    for field in fields:
                        field_name_lower = field.get("data_point_name", "").lower()
                        if field_name_lower == "ip/op":
                            chunk_ip_op = field.get("value", "OP")
                        elif field_name_lower == "service type":
                            chunk_service_type = field.get("value", "Covered Services")
                        elif field_name_lower == "plan type":
                            chunk_plan_type = field.get("value", "Standard Plan")
                    
                    # Apply to all lines of business
                    for lob in ["MEDICAID", "MEDICARE", "COMMERCIAL-EXCHANGE"]:
                        hierarchy_key = f"{lob}|General Services|{chunk_ip_op}|{chunk_service_type}|{chunk_plan_type}"
                        
                        if hierarchy_key not in hierarchy_map:
                            hierarchy_map[hierarchy_key] = {
                                "line_of_business": lob,
                                "provider_type": "General Services",
                                "ip_op": chunk_ip_op,
                                "service_type": chunk_service_type,
                                "plan_type": chunk_plan_type,
                                "payment_fields": []
                            }
                        
                        # Add the payment fields to this hierarchy
                        hierarchy_map[hierarchy_key]["payment_fields"].extend(general_payment_fields)
        
        # Build the nested structure from hierarchy_map
        lob_sections = {}
        
        for hierarchy_key, hierarchy_data in hierarchy_map.items():
            lob = hierarchy_data["line_of_business"]
            provider_type = hierarchy_data["provider_type"]
            ip_op = hierarchy_data["ip_op"]
            service_type = hierarchy_data["service_type"]
            plan_type = hierarchy_data["plan_type"]
            payment_fields = hierarchy_data["payment_fields"]
            
            # Create LOB section if not exists
            if lob not in lob_sections:
                lob_sections[lob] = {
                    "section_name": lob,
                    "section_type": "Line of Business",
                    "extracted_fields": [],
                    "subsections": {}
                }
            
            # Create Provider Type subsection if not exists
            if provider_type not in lob_sections[lob]["subsections"]:
                lob_sections[lob]["subsections"][provider_type] = {
                    "section_name": provider_type,
                    "section_type": "Provider Type",
                    "extracted_fields": [],
                    "subsections": {}
                }
            
            # Create IP/OP subsection if not exists
            if ip_op not in lob_sections[lob]["subsections"][provider_type]["subsections"]:
                lob_sections[lob]["subsections"][provider_type]["subsections"][ip_op] = {
                    "section_name": ip_op,
                    "section_type": "IP/OP",
                    "extracted_fields": [],
                    "subsections": {}
                }
            
            # Create Service Type subsection if not exists
            if service_type not in lob_sections[lob]["subsections"][provider_type]["subsections"][ip_op]["subsections"]:
                lob_sections[lob]["subsections"][provider_type]["subsections"][ip_op]["subsections"][service_type] = {
                    "section_name": service_type,
                    "section_type": "Service Type",
                    "extracted_fields": [],
                    "subsections": {}
                }
            
            # Create Plan Type subsection (leaf level with payment fields)
            # Ensure all 5 payment fields are present in the correct order
            all_payment_fields = []
            payment_field_order = [
                "Lesser of Logic Language included (Y/N)",
                "Lesser of Rate",
                "Reimb Methodology",
                "Reimb Methodology short",
                "Flat Fee"
            ]
            
            # Create a map of existing payment fields
            payment_field_map = {}
            for field in payment_fields:
                payment_field_map[field["data_point_name"]] = field
            
            # Add all fields in order, with empty values for missing ones
            for field_name in payment_field_order:
                if field_name in payment_field_map:
                    all_payment_fields.append(payment_field_map[field_name])
                else:
                    # Add empty field
                    all_payment_fields.append({
                        "data_point_name": field_name,
                        "value": "",
                        "citation": "",
                        "rationale": "",
                        "document_name": ""
                    })
            
            lob_sections[lob]["subsections"][provider_type]["subsections"][ip_op]["subsections"][service_type]["subsections"][plan_type] = {
                "section_name": plan_type,
                "section_type": "Plan Type",
                "extracted_fields": all_payment_fields,
                "subsections": []
            }
        
        # Convert nested dictionaries to lists
        def convert_subsections_to_list(section):
            if "subsections" in section and isinstance(section["subsections"], dict):
                section["subsections"] = list(section["subsections"].values())
                for subsection in section["subsections"]:
                    convert_subsections_to_list(subsection)
        
        # Convert all subsections from dicts to lists
        for lob_section in lob_sections.values():
            convert_subsections_to_list(lob_section)
        
        # Populate the final output structure
        output["sections"][0]["extracted_fields"] = main_contract_fields
        output["sections"][0]["subsections"] = list(lob_sections.values())
        
        return output
    
    async def run_extraction(self, output_path: str = "data/output/extracted_values.json"):
        """Run the full extraction pipeline."""
        logger.info("Starting extraction process...")
        
        # Extract from all chunks
        extraction_results = await self.extract_all_chunks(batch_size=5)
        
        # Save raw results for traceability
        raw_output_path = output_path.replace(".json", "_raw.json")
        os.makedirs(os.path.dirname(raw_output_path), exist_ok=True)
        with open(raw_output_path, "w") as f:
            json.dump(extraction_results, f, indent=2)
        logger.info(f"Saved raw extraction results to {raw_output_path}")
        
        # Organize into target structure
        organized_output = self.organize_results(extraction_results)
        
        # Save organized output
        with open(output_path, "w") as f:
            json.dump(organized_output, f, indent=2)
        logger.info(f"Saved organized output to {output_path}")
        
        # Print summary
        total_fields = sum(len(r.get("extracted_fields", [])) for r in extraction_results)
        logger.info(f"\nExtraction complete!")
        logger.info(f"Processed {len(extraction_results)} chunks")
        logger.info(f"Extracted {total_fields} total fields")
        
        return organized_output


async def main():
    # You'll need to set your OpenAI API key
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("Please set OPENAI_API_KEY environment variable")
        return
    
    extractor = DocumentExtractor(api_key)
    await extractor.run_extraction()


if __name__ == "__main__":
    asyncio.run(main()) 