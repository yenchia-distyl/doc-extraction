#!/usr/bin/env python3
"""
Alternative transformation using GPT-4o-mini for intelligent mapping.
This approach uses an LLM to handle complex or ambiguous transformations.
"""

import json
import os
from typing import Dict, List, Any
from openai import OpenAI


def load_data(file_path: str) -> Dict[str, Any]:
    """Load JSON data from file."""
    with open(file_path, 'r') as f:
        return json.load(f)


def create_transformation_prompt(payment_schedule: Dict[str, Any], target_example: str) -> str:
    """Create a prompt for the LLM to transform a single payment schedule."""
    return f"""Transform the following payment schedule data to match the target nested structure format and return the result as JSON.

Source data:
{json.dumps(payment_schedule, indent=2)}

Target structure example (partial):
{target_example}

Instructions:
1. Map the hierarchy fields to nested sections:
   - line_of_business becomes a top-level subsection under "Main Contract Details"
   - provider_type, ip_op, service_type, and plan_type become nested subsections
2. Transform payment_fields to extracted_fields format with snake_case field names
3. Initialize empty history arrays
4. Preserve all field values exactly as provided

Return only the JSON for this specific data's section structure."""


def transform_with_llm(input_file: str, output_file: str, api_key: str = None):
    """
    Transform payment schedules using GPT-4o-mini.
    
    Args:
        input_file: Path to payment_schedules_v2.json
        output_file: Path to output file
        api_key: OpenAI API key (or set OPENAI_API_KEY env var)
    """
    # Initialize OpenAI client
    client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
    
    # Load input data and target example
    data = load_data(input_file)
    target_example = load_data("data/target_output_nested.json")
    
    # Prepare target example snippet
    target_snippet = json.dumps(target_example["sections"][0]["subsections"][0], indent=2)[:500] + "..."
    
    # Process each payment schedule
    all_subsections = []
    
    for i, schedule in enumerate(data.get("payment_schedules", [])):
        print(f"Processing schedule {i+1}/{len(data['payment_schedules'])}...")
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a data transformation expert. Transform data structures accurately, preserving all values. Always respond with valid JSON format."
                    },
                    {
                        "role": "user",
                        "content": create_transformation_prompt(schedule, target_snippet)
                    }
                ],
                temperature=0.1,  # Low temperature for consistent transformations
                response_format={ "type": "json_object" }
            )
            
            # Parse the response
            transformed = json.loads(response.choices[0].message.content)
            all_subsections.append(transformed)
            
        except Exception as e:
            print(f"Error processing schedule {i+1}: {e}")
            continue
    
    # Merge all subsections intelligently
    print("Merging subsections...")
    
    merge_prompt = f"""Merge the following subsections into a single coherent nested structure under "Main Contract Details" and return as JSON:

Subsections to merge:
{json.dumps(all_subsections, indent=2)}

Create a properly nested structure where:
1. Similar line_of_business sections are grouped together
2. The hierarchy is maintained: line_of_business > provider_type > ip_op > service_type > plan_type
3. No duplicate sections - merge fields from the same paths

Return the complete output in JSON format with a "sections" array containing "Main Contract Details"."""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "You are a data merging expert. Merge nested structures intelligently without losing data. Always respond with valid JSON format."
            },
            {
                "role": "user",
                "content": merge_prompt
            }
        ],
        temperature=0.1,
        response_format={ "type": "json_object" }
    )
    
    # Get final output
    output = json.loads(response.choices[0].message.content)
    
    # Ensure proper structure
    if "sections" not in output:
        output = {"sections": [output]}
    
    # Add default contract name if missing
    if output["sections"] and not output["sections"][0].get("extracted_fields"):
        output["sections"][0]["extracted_fields"] = [{
            "data_point_name": "Contract Name",
            "value": "Provider Agreement",
            "citation": "This document contains provider agreement payment schedules",
            "rationale": "Default contract name for payment schedules",
            "document_name": "Payment Schedules",
            "history": []
        }]
    
    # Save output
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=4)
    
    print(f"Transformation complete. Output saved to: {output_file}")


if __name__ == "__main__":
    # Example usage
    # Set OPENAI_API_KEY environment variable or pass it directly
    transform_with_llm(
        input_file="data/output/payment_schedules_v2.json",
        output_file="data/output/payment_schedules_nested_llm.json"
    ) 