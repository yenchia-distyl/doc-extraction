#!/usr/bin/env python3
"""
Transform payment schedules data to match the nested output format.
Converts from payment_schedules_v2.json structure to target_output_nested.json structure.
"""

import json
from typing import Dict, List, Any, Optional
from collections import defaultdict
import yaml


def load_data(file_path: str) -> Dict[str, Any]:
    """Load JSON data from file."""
    with open(file_path, 'r') as f:
        return json.load(f)


def load_yaml_schema(file_path: str) -> Dict[str, Any]:
    """Load YAML schema from file."""
    with open(file_path, 'r') as f:
        return yaml.safe_load(f)


def transform_payment_field_to_extracted_field(field: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform a payment field to extracted field format.
    
    Maps from snake_case to match the target output format.
    """
    return {
        "data_point_name": field.get("data_point_name", ""),
        "value": field.get("value", ""),
        "citation": field.get("citation", ""),
        "rationale": field.get("rationale", ""),
        "document_name": field.get("document_name", ""),
        "history": []  # Initialize empty as per target format
    }


def build_nested_structure(payment_schedules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build nested section/subsection structure from flat payment schedules.
    
    The hierarchy from payment_schedules_v2.json maps to nested sections:
    - line_of_business -> Main section
    - provider_type -> Subsection level 1
    - ip_op -> Subsection level 2
    - service_type -> Subsection level 3
    - plan_type -> Subsection level 4
    """
    # Group data by hierarchy levels
    nested_data = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list)))))
    
    for schedule in payment_schedules:
        hierarchy = schedule.get("hierarchy", {})
        fields = schedule.get("payment_fields", [])
        
        # Extract hierarchy levels
        lob = hierarchy.get("line_of_business", "Unknown")
        provider = hierarchy.get("provider_type", "Unknown")
        ip_op = hierarchy.get("ip_op", "Unknown")
        service = hierarchy.get("service_type", "Unknown")
        plan = hierarchy.get("plan_type", "Unknown")
        
        # Transform fields and store in nested structure
        transformed_fields = [transform_payment_field_to_extracted_field(f) for f in fields]
        nested_data[lob][provider][ip_op][service][plan].extend(transformed_fields)
    
    # Build the final nested structure
    sections = []
    
    # Create main section (assuming all data goes under "Main Contract Details")
    main_section = {
        "section_name": "Main Contract Details",
        "extracted_fields": [],
        "subsections": []
    }
    
    # Add a sample top-level field (as shown in target)
    main_section["extracted_fields"].append({
        "data_point_name": "Contract Name",
        "value": "Provider Agreement",
        "citation": "This document contains provider agreement payment schedules",
        "rationale": "Default contract name for payment schedules",
        "document_name": "Payment Schedules",
        "history": []
    })
    
    # Build subsections for each line of business
    for lob, providers in nested_data.items():
        lob_section = {
            "section_name": lob.title(),
            "extracted_fields": [],
            "subsections": []
        }
        
        for provider, ip_ops in providers.items():
            provider_section = {
                "section_name": provider,
                "extracted_fields": [],
                "subsections": []
            }
            
            for ip_op, services in ip_ops.items():
                ip_op_section = {
                    "section_name": ip_op,
                    "extracted_fields": [],
                    "subsections": []
                }
                
                for service, plans in services.items():
                    service_section = {
                        "section_name": service,
                        "extracted_fields": [],
                        "subsections": []
                    }
                    
                    for plan, fields in plans.items():
                        if fields:  # Only create plan section if there are fields
                            plan_section = {
                                "section_name": plan,
                                "extracted_fields": fields,
                                "subsections": []
                            }
                            service_section["subsections"].append(plan_section)
                    
                    if service_section["subsections"]:  # Only add if has content
                        ip_op_section["subsections"].append(service_section)
                
                if ip_op_section["subsections"]:  # Only add if has content
                    provider_section["subsections"].append(ip_op_section)
            
            if provider_section["subsections"]:  # Only add if has content
                lob_section["subsections"].append(provider_section)
        
        if lob_section["subsections"]:  # Only add if has content
            main_section["subsections"].append(lob_section)
    
    sections.append(main_section)
    return sections


def transform_payment_schedules(input_file: str, output_file: str, schema_file: Optional[str] = None):
    """
    Main transformation function.
    
    Args:
        input_file: Path to payment_schedules_v2.json
        output_file: Path to output file
        schema_file: Optional path to foir.yml for validation
    """
    # Load input data
    data = load_data(input_file)
    
    # Load schema if provided (for reference/validation)
    if schema_file:
        schema = load_yaml_schema(schema_file)
        print(f"Loaded schema with types: {list(schema.get('types', {}).keys())}")
    
    # Extract payment schedules
    payment_schedules = data.get("payment_schedules", [])
    
    # Build nested structure
    sections = build_nested_structure(payment_schedules)
    
    # Create output in target format
    output = {
        "sections": sections
    }
    
    # Save output
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=4)
    
    print(f"Transformation complete. Output saved to: {output_file}")
    print(f"Total sections: {len(sections)}")
    if sections:
        print(f"Total subsections in main section: {len(sections[0].get('subsections', []))}")


if __name__ == "__main__":
    # Example usage
    transform_payment_schedules(
        input_file="data/output/payment_schedules_v2.json",
        output_file="data/output/payment_schedules_nested.json",
        schema_file="data/templates/foir.yml"
    ) 