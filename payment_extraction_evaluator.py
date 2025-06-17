import json
import os
from typing import Dict, List, Any, Set, Tuple
import asyncio
import aiohttp
from datetime import datetime
import logging
from collections import defaultdict, Counter
import argparse
from pathlib import Path

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PaymentExtractionEvaluator:
    """
    Evaluates payment field extraction results for completeness, accuracy, and consistency
    using GPT-4 as the evaluation judge.
    """
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.total_api_calls = 0
        
    def load_extraction_results(self, file_path: str) -> Dict[str, Any]:
        """Load the extraction results from JSON file."""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            logger.info(f"Loaded extraction results from: {file_path}")
            return data
        except Exception as e:
            logger.error(f"Error loading file {file_path}: {e}")
            raise
    
    def identify_source_documents(self, data: Dict[str, Any]) -> List[str]:
        """Identify the source documents that were used for extraction."""
        source_files = set()
        
        # Check source_directory if available
        source_dir = data.get('source_directory', '')
        if source_dir and source_dir.endswith('.md'):
            source_files.add(source_dir)
        
        # Check individual schedule source files
        schedules = data.get('payment_schedules', [])
        for schedule in schedules:
            source_file = schedule.get('source_file', '')
            if source_file:
                # Handle cases where source_file might be just filename
                if not source_file.startswith('data/'):
                    # Try common locations
                    possible_paths = [
                        f"data/{source_file}",
                        f"data/test_text.md",
                        f"data/headers/schedule/{source_file}"
                    ]
                    for path in possible_paths:
                        if Path(path).exists():
                            source_files.add(path)
                            break
                else:
                    source_files.add(source_file)
        
        # If no sources found, try to infer from common locations
        if not source_files:
            common_paths = [
                "data/test_text.md",
                "data/headers/schedule"
            ]
            for path in common_paths:
                if Path(path).exists():
                    if Path(path).is_file() and path.endswith('.md'):
                        source_files.add(path)
                    elif Path(path).is_dir():
                        # Add all .md files in directory
                        for md_file in Path(path).glob("*.md"):
                            source_files.add(str(md_file))
        
        result = list(source_files)
        logger.info(f"Identified {len(result)} source documents: {result}")
        return result
    
    def load_source_documents(self, source_paths: List[str]) -> Dict[str, str]:
        """Load the content of source documents."""
        source_content = {}
        
        for path in source_paths:
            try:
                if Path(path).exists():
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    source_content[path] = content
                    logger.info(f"Loaded source document: {path} ({len(content)} chars)")
                else:
                    logger.warning(f"Source document not found: {path}")
            except Exception as e:
                logger.error(f"Error loading source document {path}: {e}")
        
        return source_content
    
    def analyze_structure(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze the structure and basic statistics of the extraction results."""
        schedules = data.get('payment_schedules', [])
        
        # Extract all unique combinations
        combinations = set()
        service_types = set()
        plan_types = set()
        lines_of_business = set()
        provider_types = set()
        ip_ops = set()
        
        # Track field completeness
        field_completeness = defaultdict(int)
        total_schedules = len(schedules)
        
        for schedule in schedules:
            hierarchy = schedule.get('hierarchy', {})
            
            # Create combination tuple
            combination = (
                hierarchy.get('line_of_business'),
                hierarchy.get('provider_type'),
                hierarchy.get('ip_op'),
                hierarchy.get('service_type'),
                hierarchy.get('plan_type')
            )
            combinations.add(combination)
            
            # Add to individual sets
            lines_of_business.add(hierarchy.get('line_of_business'))
            provider_types.add(hierarchy.get('provider_type'))
            ip_ops.add(hierarchy.get('ip_op'))
            service_types.add(hierarchy.get('service_type'))
            plan_types.add(hierarchy.get('plan_type'))
            
            # Check field completeness
            payment_fields = schedule.get('payment_fields', [])
            for field in payment_fields:
                field_name = field.get('data_point_name', '')
                if field.get('value', '').strip():
                    field_completeness[field_name] += 1
        
        return {
            'total_schedules': total_schedules,
            'unique_combinations': len(combinations),
            'combinations_list': list(combinations),
            'lines_of_business': list(lines_of_business),
            'provider_types': list(provider_types),
            'ip_ops': list(ip_ops),
            'service_types': list(service_types),
            'plan_types': list(plan_types),
            'field_completeness': dict(field_completeness),
            'expected_total_combinations': len(lines_of_business) * len(provider_types) * len(ip_ops) * len(service_types) * len(plan_types)
        }
    
    def find_duplicates(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find duplicate combinations and conflicting data."""
        schedules = data.get('payment_schedules', [])
        combination_groups = defaultdict(list)
        
        # Group schedules by combination
        for i, schedule in enumerate(schedules):
            hierarchy = schedule.get('hierarchy', {})
            combination = (
                hierarchy.get('line_of_business'),
                hierarchy.get('provider_type'),
                hierarchy.get('ip_op'),
                hierarchy.get('service_type'),
                hierarchy.get('plan_type')
            )
            combination_groups[combination].append((i, schedule))
        
        # Find duplicates and conflicts
        duplicates = []
        conflicts = []
        
        for combination, schedule_list in combination_groups.items():
            if len(schedule_list) > 1:
                # This is a duplicate combination
                duplicate_info = {
                    'combination': combination,
                    'count': len(schedule_list),
                    'schedule_indices': [idx for idx, _ in schedule_list],
                    'schedules': [schedule for _, schedule in schedule_list]
                }
                duplicates.append(duplicate_info)
                
                # Check for conflicts in payment fields
                field_values = defaultdict(set)
                for _, schedule in schedule_list:
                    for field in schedule.get('payment_fields', []):
                        field_name = field.get('data_point_name', '')
                        field_value = field.get('value', '').strip()
                        if field_value:
                            field_values[field_name].add(field_value)
                
                # Find conflicting values
                for field_name, values in field_values.items():
                    if len(values) > 1:
                        conflicts.append({
                            'combination': combination,
                            'field_name': field_name,
                            'conflicting_values': list(values),
                            'schedule_indices': [idx for idx, _ in schedule_list]
                        })
        
        return {
            'duplicates': duplicates,
            'conflicts': conflicts
        }
    
    async def generate_ground_truth(self, session: aiohttp.ClientSession, 
                                  source_content: Dict[str, str]) -> Dict[str, Any]:
        """Generate ground truth from source documents using GPT-4."""
        ground_truth = {}
        
        for file_path, content in source_content.items():
            logger.info(f"Generating ground truth for: {file_path}")
            
            prompt = f"""
Analyze this medical contract document to identify ALL payment information that should be extractable.

DOCUMENT: {file_path}
CONTENT:
{content}

Your task is to identify ALL possible combinations of:
- Line of Business (e.g., MEDICAID, MEDICARE, COMMERCIAL-EXCHANGE)
- Provider Type (e.g., Professional Services, Facility Services)  
- IP/OP Status (e.g., IP, OP)
- Service Type (e.g., Radiology, Laboratory, Emergency Services, etc.)
- Plan Type (e.g., specific plan names mentioned)

For each valid combination that has payment information in the document, extract:
1. Lesser of Logic Language included (Y/N)
2. Lesser of Rate (specific rate if mentioned)
3. Reimbursement Methodology (full description)
4. Reimbursement Methodology short (abbreviated version)
5. Flat Fee (specific dollar amounts if mentioned)

Return JSON with EXACTLY this format:
{{
  "line_of_business": "identified line of business",
  "available_combinations": [
    {{
      "hierarchy": {{
        "line_of_business": "LOB",
        "provider_type": "Provider Type", 
        "ip_op": "IP or OP",
        "service_type": "Service Type",
        "plan_type": "Plan Type"
      }},
      "payment_fields": {{
        "lesser_of_logic": "Y/N with exact citation",
        "lesser_of_rate": "specific rate with citation",
        "reimb_methodology": "full methodology with citation", 
        "reimb_methodology_short": "abbreviated with citation",
        "flat_fee": "dollar amount with citation or empty"
      }},
      "rationale": "why this combination is valid and has payment info"
    }}
  ],
  "document_summary": "overall summary of payment information in this document"
}}

Be thorough - identify every combination that has ANY payment information, even if incomplete.
"""
            
            try:
                async with session.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "gpt-4o",
                        "messages": [
                            {"role": "system", "content": "You are an expert medical contract analyst. Identify ALL payment information thoroughly and accurately."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.1,
                        "max_tokens": 4000,
                        "response_format": {"type": "json_object"}
                    }
                ) as response:
                    self.total_api_calls += 1
                    if response.status == 200:
                        result = await response.json()
                        ground_truth[file_path] = json.loads(result['choices'][0]['message']['content'])
                    else:
                        logger.error(f"Error generating ground truth for {file_path}: {response.status}")
                        ground_truth[file_path] = {"error": f"API error: {response.status}"}
            except Exception as e:
                logger.error(f"Exception generating ground truth for {file_path}: {e}")
                ground_truth[file_path] = {"error": str(e)}
            
            # Small delay to avoid rate limiting
            await asyncio.sleep(1)
        
        return ground_truth
    
    async def evaluate_completeness(self, session: aiohttp.ClientSession, 
                                  data: Dict[str, Any], 
                                  analysis: Dict[str, Any],
                                  ground_truth: Dict[str, Any]) -> Dict[str, Any]:
        """Use ground truth to evaluate completeness of the extraction."""
        
        # Extract all combinations from ground truth
        gt_combinations = set()
        gt_total = 0
        
        for file_path, gt_data in ground_truth.items():
            if "available_combinations" in gt_data:
                for combo in gt_data["available_combinations"]:
                    hierarchy = combo.get("hierarchy", {})
                    gt_combination = (
                        hierarchy.get('line_of_business'),
                        hierarchy.get('provider_type'),
                        hierarchy.get('ip_op'),
                        hierarchy.get('service_type'),
                        hierarchy.get('plan_type')
                    )
                    gt_combinations.add(gt_combination)
                    gt_total += 1
        
        # Extract all combinations from extracted results
        extracted_combinations = set(analysis['combinations_list'])
        
        # Calculate metrics
        found_combinations = extracted_combinations.intersection(gt_combinations)
        missing_combinations = gt_combinations - extracted_combinations
        extra_combinations = extracted_combinations - gt_combinations
        
        completeness_percentage = len(found_combinations) / len(gt_combinations) if gt_combinations else 0
        
        prompt = f"""
Evaluate the COMPLETENESS of this medical contract payment extraction against ground truth.

GROUND TRUTH ANALYSIS:
- Total combinations available in source documents: {len(gt_combinations)}
- Total combinations extracted: {len(extracted_combinations)}
- Combinations found correctly: {len(found_combinations)}
- Combinations missing: {len(missing_combinations)}
- Extra combinations (not in ground truth): {len(extra_combinations)}
- Completeness percentage: {completeness_percentage:.2%}

MISSING COMBINATIONS:
{json.dumps(list(missing_combinations)[:10], indent=2)}

EXTRA COMBINATIONS:
{json.dumps(list(extra_combinations)[:10], indent=2)}

GROUND TRUTH SUMMARY:
{json.dumps({path: gt.get("document_summary", "No summary") for path, gt in ground_truth.items()}, indent=2)}

Return JSON with EXACTLY this format:
{{
  "completeness_score": 1-10,
  "completeness_percentage": {completeness_percentage:.3f},
  "combinations_analysis": {{
    "total_available": {len(gt_combinations)},
    "total_extracted": {len(extracted_combinations)},
    "correctly_found": {len(found_combinations)},
    "missing_count": {len(missing_combinations)},
    "extra_count": {len(extra_combinations)}
  }},
  "missing_combinations": {json.dumps(list(missing_combinations)[:5])},
  "extra_combinations": {json.dumps(list(extra_combinations)[:5])},
  "recommendations": [
    "Specific recommendations to improve completeness based on ground truth"
  ],
  "overall_assessment": "assessment based on actual ground truth comparison"
}}
"""
        
        try:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o",
                    "messages": [
                        {"role": "system", "content": "You are an expert medical contract analyst. Evaluate extraction completeness against ground truth objectively."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 1500,
                    "response_format": {"type": "json_object"}
                }
            ) as response:
                self.total_api_calls += 1
                if response.status == 200:
                    result = await response.json()
                    parsed_result = json.loads(result['choices'][0]['message']['content'])
                    # Add computed metrics
                    parsed_result["completeness_percentage"] = completeness_percentage
                    parsed_result["combinations_analysis"] = {
                        "total_available": len(gt_combinations),
                        "total_extracted": len(extracted_combinations),
                        "correctly_found": len(found_combinations),
                        "missing_count": len(missing_combinations),
                        "extra_count": len(extra_combinations)
                    }
                    return parsed_result
                else:
                    logger.error(f"Error in completeness evaluation: {response.status}")
                    return {"error": f"API error: {response.status}"}
        except Exception as e:
            logger.error(f"Exception in completeness evaluation: {e}")
            return {"error": str(e)}
    
    async def evaluate_accuracy(self, session: aiohttp.ClientSession, 
                               data: Dict[str, Any],
                               ground_truth: Dict[str, Any]) -> Dict[str, Any]:
        """Use ground truth to evaluate accuracy of the extraction."""
        
        # Build ground truth lookup
        gt_lookup = {}
        for file_path, gt_data in ground_truth.items():
            if "available_combinations" in gt_data:
                for combo in gt_data["available_combinations"]:
                    hierarchy = combo.get("hierarchy", {})
                    gt_combination = (
                        hierarchy.get('line_of_business'),
                        hierarchy.get('provider_type'),
                        hierarchy.get('ip_op'),
                        hierarchy.get('service_type'),
                        hierarchy.get('plan_type')
                    )
                    gt_lookup[gt_combination] = combo.get("payment_fields", {})
        
        # Compare extracted results against ground truth
        schedules = data.get('payment_schedules', [])
        accuracy_results = []
        field_matches = defaultdict(list)
        
        for schedule in schedules[:10]:  # Sample first 10 for detailed analysis
            hierarchy = schedule.get('hierarchy', {})
            extracted_combination = (
                hierarchy.get('line_of_business'),
                hierarchy.get('provider_type'),
                hierarchy.get('ip_op'),
                hierarchy.get('service_type'),
                hierarchy.get('plan_type')
            )
            
            if extracted_combination in gt_lookup:
                gt_fields = gt_lookup[extracted_combination]
                extracted_fields = {field.get('data_point_name', ''): field for field in schedule.get('payment_fields', [])}
                
                # Compare each field
                field_comparison = {}
                for field_name in ["Lesser of Logic Language included (Y/N)", "Lesser of Rate", "Reimb Methodology", "Reimb Methodology short", "Flat Fee"]:
                    extracted_field = extracted_fields.get(field_name, {})
                    extracted_value = extracted_field.get('value', '').strip()
                    
                    # Map to ground truth field names
                    gt_field_map = {
                        "Lesser of Logic Language included (Y/N)": "lesser_of_logic",
                        "Lesser of Rate": "lesser_of_rate", 
                        "Reimb Methodology": "reimb_methodology",
                        "Reimb Methodology short": "reimb_methodology_short",
                        "Flat Fee": "flat_fee"
                    }
                    
                    gt_value = gt_fields.get(gt_field_map.get(field_name, ''), '').strip()
                    
                    # Simple similarity check
                    is_match = False
                    if extracted_value and gt_value:
                        # For Y/N fields, exact match
                        if field_name == "Lesser of Logic Language included (Y/N)":
                            is_match = extracted_value.upper() in gt_value.upper() or gt_value.upper() in extracted_value.upper()
                        else:
                            # For other fields, check if core content matches
                            is_match = (
                                extracted_value.lower() in gt_value.lower() or 
                                gt_value.lower() in extracted_value.lower() or
                                # Check for semantic similarity in rates/percentages
                                (any(char.isdigit() for char in extracted_value) and 
                                 any(char.isdigit() for char in gt_value) and
                                 any(num in gt_value for num in extracted_value.split() if num.replace('%', '').replace('$', '').isdigit()))
                            )
                    elif not extracted_value and not gt_value:
                        is_match = True  # Both empty
                    
                    field_comparison[field_name] = {
                        "extracted": extracted_value,
                        "ground_truth": gt_value,
                        "match": is_match
                    }
                    field_matches[field_name].append(is_match)
                
                accuracy_results.append({
                    "combination": extracted_combination,
                    "field_comparison": field_comparison
                })
        
        # Calculate field accuracy percentages
        field_accuracy_scores = {}
        for field_name, matches in field_matches.items():
            if matches:
                accuracy_pct = sum(matches) / len(matches)
                field_accuracy_scores[field_name] = accuracy_pct
            else:
                field_accuracy_scores[field_name] = 0
        
        # Generate detailed analysis with GPT-4
        sample_comparisons = accuracy_results[:3]
        
        prompt = f"""
Evaluate the ACCURACY of this medical contract payment extraction against ground truth.

FIELD ACCURACY SCORES:
{json.dumps(field_accuracy_scores, indent=2)}

SAMPLE FIELD COMPARISONS:
{json.dumps(sample_comparisons, indent=2)}

GROUND TRUTH VS EXTRACTED ANALYSIS:
- Total combinations compared: {len(accuracy_results)}
- Field-by-field match rates calculated above

Return JSON with EXACTLY this format:
{{
  "accuracy_score": 1-10,
  "field_accuracy_percentages": {json.dumps(field_accuracy_scores)},
  "field_accuracy": {{
    "lesser_of_logic": {{
      "score": 1-10,
      "accuracy_percentage": {field_accuracy_scores.get("Lesser of Logic Language included (Y/N)", 0):.3f},
      "issues": ["specific issues found in this field"]
    }},
    "lesser_of_rate": {{
      "score": 1-10,
      "accuracy_percentage": {field_accuracy_scores.get("Lesser of Rate", 0):.3f},
      "issues": ["specific issues found in this field"]
    }},
    "reimb_methodology": {{
      "score": 1-10,
      "accuracy_percentage": {field_accuracy_scores.get("Reimb Methodology", 0):.3f},
      "issues": ["specific issues found in this field"]
    }},
    "reimb_methodology_short": {{
      "score": 1-10,
      "accuracy_percentage": {field_accuracy_scores.get("Reimb Methodology short", 0):.3f},
      "issues": ["specific issues found in this field"]
    }},
    "flat_fee": {{
      "score": 1-10,
      "accuracy_percentage": {field_accuracy_scores.get("Flat Fee", 0):.3f},
      "issues": ["specific issues found in this field"]
    }}
  }},
  "recommendations": [
    "Specific recommendations to improve accuracy based on ground truth comparison"
  ],
  "overall_assessment": "assessment based on actual ground truth field-by-field comparison"
}}
"""
        
        try:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o",
                    "messages": [
                        {"role": "system", "content": "You are an expert medical contract analyst. Evaluate extraction accuracy against ground truth objectively."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 2000,
                    "response_format": {"type": "json_object"}
                }
            ) as response:
                self.total_api_calls += 1
                if response.status == 200:
                    result = await response.json()
                    parsed_result = json.loads(result['choices'][0]['message']['content'])
                    # Add computed metrics
                    parsed_result["field_accuracy_percentages"] = field_accuracy_scores
                    parsed_result["comparisons_made"] = len(accuracy_results)
                    return parsed_result
                else:
                    logger.error(f"Error in accuracy evaluation: {response.status}")
                    return {"error": f"API error: {response.status}"}
        except Exception as e:
            logger.error(f"Exception in accuracy evaluation: {e}")
            return {"error": str(e)}
    
    async def evaluate_consistency(self, session: aiohttp.ClientSession, 
                                 duplicates_info: Dict[str, Any]) -> Dict[str, Any]:
        """Use GPT-4 to evaluate consistency and identify problematic duplications."""
        
        duplicates = duplicates_info['duplicates']
        conflicts = duplicates_info['conflicts']
        
        prompt = f"""
Analyze this medical contract payment extraction for CONSISTENCY issues.

DUPLICATE COMBINATIONS FOUND: {len(duplicates)}
CONFLICTING VALUES FOUND: {len(conflicts)}

DUPLICATE COMBINATIONS:
{json.dumps(duplicates[:5], indent=2) if duplicates else "None"}

CONFLICTING VALUES:
{json.dumps(conflicts[:10], indent=2) if conflicts else "None"}

EVALUATION CRITERIA:
1. Are duplicate combinations problematic or expected?
2. Do conflicting values represent real inconsistencies or legitimate variations?
3. Are there patterns in the conflicts that suggest systematic issues?
4. Should the same combination have identical payment information?

For medical contracts, consider:
- Some duplications might be legitimate if different sections provide different details
- Conflicts in core payment rates are serious issues
- Variations in methodology descriptions might be acceptable if they're semantically equivalent

Return JSON with EXACTLY this format:
{{
  "consistency_score": 1-10,
  "duplicate_analysis": {{
    "total_duplicates": {len(duplicates)},
    "problematic_duplicates": "number of duplicates that are actually problematic",
    "acceptable_duplicates": "number of duplicates that might be acceptable"
  }},
  "conflict_analysis": {{
    "total_conflicts": {len(conflicts)},
    "critical_conflicts": [
      "list of conflicts that are critical issues"
    ],
    "minor_conflicts": [
      "list of conflicts that are minor or acceptable"
    ]
  }},
  "patterns": [
    "patterns observed in the consistency issues"
  ],
  "recommendations": [
    "specific recommendations to improve consistency"
  ],
  "overall_assessment": "comprehensive assessment of data consistency"
}}
"""
        
        try:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o",
                    "messages": [
                        {"role": "system", "content": "You are an expert data quality analyst specializing in medical contract analysis. Evaluate consistency objectively."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 1500,
                    "response_format": {"type": "json_object"}
                }
            ) as response:
                self.total_api_calls += 1
                if response.status == 200:
                    result = await response.json()
                    return json.loads(result['choices'][0]['message']['content'])
                else:
                    logger.error(f"Error in consistency evaluation: {response.status}")
                    return {"error": f"API error: {response.status}"}
        except Exception as e:
            logger.error(f"Exception in consistency evaluation: {e}")
            return {"error": str(e)}
    
    async def generate_overall_assessment(self, session: aiohttp.ClientSession,
                                        completeness: Dict[str, Any],
                                        accuracy: Dict[str, Any], 
                                        consistency: Dict[str, Any],
                                        analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Generate an overall assessment combining all evaluation dimensions."""
        
        completeness_pct = completeness.get('completeness_percentage', 'N/A')
        field_accuracy = accuracy.get('field_accuracy_percentages', {})
        
        prompt = f"""
Generate an overall assessment of this medical contract payment extraction system.

COMPLETENESS RESULTS (Ground Truth Based):
Score: {completeness.get('completeness_score', 'N/A')}/10
Completeness Rate: {completeness_pct if completeness_pct != 'N/A' else 'No ground truth'}
{json.dumps(completeness, indent=2)}

ACCURACY RESULTS (Ground Truth Based):
Score: {accuracy.get('accuracy_score', 'N/A')}/10
Field Accuracy Rates: {json.dumps(field_accuracy, indent=2)}
{json.dumps(accuracy, indent=2)}

CONSISTENCY RESULTS:
Score: {consistency.get('consistency_score', 'N/A')}/10
{json.dumps(consistency, indent=2)}

EXTRACTION STATISTICS:
- Total schedules: {analysis['total_schedules']}
- Unique combinations: {analysis['unique_combinations']}
- Service types: {len(analysis['service_types'])}
- Plan types: {len(analysis['plan_types'])}

KEY METRICS:
- Ground truth enabled: {'Yes' if completeness_pct != 'N/A' else 'No'}
- Completeness rate: {completeness_pct if completeness_pct != 'N/A' else 'N/A'}
- Average field accuracy: {sum(field_accuracy.values()) / len(field_accuracy) if field_accuracy else 'N/A'}

Provide a comprehensive overall assessment that:
1. Weights the three dimensions appropriately for medical contract extraction
2. Considers ground truth metrics heavily for completeness and accuracy
3. Identifies the strongest and weakest aspects of the system
4. Provides actionable recommendations for improvement
5. Gives a production-readiness assessment

Return JSON with EXACTLY this format:
{{
  "overall_score": 1-10,
  "dimensional_scores": {{
    "completeness": {completeness.get('completeness_score', 0)},
    "accuracy": {accuracy.get('accuracy_score', 0)},
    "consistency": {consistency.get('consistency_score', 0)}
  }},
  "ground_truth_metrics": {{
    "completeness_percentage": {completeness_pct if completeness_pct != 'N/A' else 'null'},
    "avg_field_accuracy": {sum(field_accuracy.values()) / len(field_accuracy) if field_accuracy else 'null'},
    "ground_truth_available": {'true' if completeness_pct != 'N/A' else 'false'}
  }},
  "strengths": [
    "key strengths of the extraction system"
  ],
  "weaknesses": [
    "key weaknesses that need attention"
  ],
  "priority_improvements": [
    "ranked list of improvements to focus on first"
  ],
  "production_readiness": {{
    "ready": true/false,
    "confidence_level": "high/medium/low",
    "key_blockers": ["critical issues preventing production use"],
    "recommended_next_steps": ["immediate next steps"]
  }},
  "summary": "executive summary of the evaluation"
}}
"""
        
        try:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o",
                    "messages": [
                        {"role": "system", "content": "You are a senior AI system evaluator specializing in medical contract processing. Provide balanced, actionable assessments."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 2000,
                    "response_format": {"type": "json_object"}
                }
            ) as response:
                self.total_api_calls += 1
                if response.status == 200:
                    result = await response.json()
                    return json.loads(result['choices'][0]['message']['content'])
                else:
                    logger.error(f"Error in overall assessment: {response.status}")
                    return {"error": f"API error: {response.status}"}
        except Exception as e:
            logger.error(f"Exception in overall assessment: {e}")
            return {"error": str(e)}
    
    async def evaluate_extraction(self, file_path: str) -> Dict[str, Any]:
        """Main evaluation pipeline with ground truth comparison."""
        logger.info("Starting payment extraction evaluation with ground truth...")
        
        # Load and analyze data
        data = self.load_extraction_results(file_path)
        analysis = self.analyze_structure(data)
        duplicates_info = self.find_duplicates(data)
        
        logger.info(f"Found {analysis['total_schedules']} payment schedules")
        logger.info(f"Found {analysis['unique_combinations']} unique combinations")
        logger.info(f"Found {len(duplicates_info['duplicates'])} duplicate combinations")
        logger.info(f"Found {len(duplicates_info['conflicts'])} conflicting values")
        
        # Identify and load source documents
        source_files = self.identify_source_documents(data)
        source_content = self.load_source_documents(source_files)
        
        if not source_content:
            logger.warning("No source documents found - evaluation will be limited")
            ground_truth = {}
        else:
            logger.info(f"Loaded {len(source_content)} source documents for ground truth")
        
        # Perform GPT-4 evaluations
        async with aiohttp.ClientSession() as session:
            # Generate ground truth from source documents
            if source_content:
                logger.info("Generating ground truth from source documents...")
                ground_truth = await self.generate_ground_truth(session, source_content)
                logger.info("Ground truth generation complete")
            else:
                ground_truth = {}
            
            logger.info("Evaluating completeness against ground truth...")
            completeness = await self.evaluate_completeness(session, data, analysis, ground_truth)
            
            logger.info("Evaluating accuracy against ground truth...")
            accuracy = await self.evaluate_accuracy(session, data, ground_truth)
            
            logger.info("Evaluating consistency...")
            consistency = await self.evaluate_consistency(session, duplicates_info)
            
            logger.info("Generating overall assessment...")
            overall = await self.generate_overall_assessment(session, completeness, accuracy, consistency, analysis)
        
        # Compile final results
        results = {
            "evaluation_metadata": {
                "evaluation_date": datetime.now().isoformat(),
                "source_file": file_path,
                "total_api_calls": self.total_api_calls,
                "evaluator_version": "2.0",
                "ground_truth_enabled": len(source_content) > 0,
                "source_documents": list(source_content.keys())
            },
            "structural_analysis": analysis,
            "ground_truth_data": ground_truth,
            "duplicates_and_conflicts": duplicates_info,
            "completeness_evaluation": completeness,
            "accuracy_evaluation": accuracy,
            "consistency_evaluation": consistency,
            "overall_assessment": overall
        }
        
        return results
    
    def save_evaluation_report(self, results: Dict[str, Any], output_file: str):
        """Save the evaluation results to a JSON file."""
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        logger.info(f"Evaluation report saved to: {output_file}")
    
    def print_summary(self, results: Dict[str, Any]):
        """Print a summary of the evaluation results."""
        overall = results.get('overall_assessment', {})
        dimensional = overall.get('dimensional_scores', {})
        
        print("\n" + "="*60)
        print("PAYMENT EXTRACTION EVALUATION SUMMARY")
        print("="*60)
        
        print(f"\n📊 OVERALL SCORE: {overall.get('overall_score', 'N/A')}/10")
        
        print(f"\n📈 DIMENSIONAL SCORES:")
        print(f"  • Completeness: {dimensional.get('completeness', 'N/A')}/10")
        print(f"  • Accuracy: {dimensional.get('accuracy', 'N/A')}/10") 
        print(f"  • Consistency: {dimensional.get('consistency', 'N/A')}/10")
        
        # Show ground truth metrics if available
        completeness_eval = results.get('completeness_evaluation', {})
        accuracy_eval = results.get('accuracy_evaluation', {})
        
        if completeness_eval.get('completeness_percentage') is not None:
            print(f"\n📊 GROUND TRUTH METRICS:")
            print(f"  • Completeness rate: {completeness_eval.get('completeness_percentage', 0):.1%}")
            
            combinations_analysis = completeness_eval.get('combinations_analysis', {})
            print(f"  • Found {combinations_analysis.get('correctly_found', 0)}/{combinations_analysis.get('total_available', 0)} available combinations")
            print(f"  • Missing {combinations_analysis.get('missing_count', 0)} combinations")
            print(f"  • Extra {combinations_analysis.get('extra_count', 0)} combinations")
        
        if accuracy_eval.get('field_accuracy_percentages'):
            print(f"\n🎯 FIELD ACCURACY RATES:")
            field_acc = accuracy_eval['field_accuracy_percentages']
            for field_name, accuracy in field_acc.items():
                short_name = field_name.replace('Lesser of Logic Language included (Y/N)', 'Lesser of Logic').replace('Reimb Methodology short', 'Reimb Method (short)')
                print(f"  • {short_name}: {accuracy:.1%}")
        
        metadata = results.get('evaluation_metadata', {})
        if metadata.get('ground_truth_enabled'):
            print(f"\n📋 SOURCE DOCUMENTS:")
            for doc in metadata.get('source_documents', [])[:3]:
                print(f"  • {doc}")
            if len(metadata.get('source_documents', [])) > 3:
                print(f"  • ... and {len(metadata.get('source_documents', [])) - 3} more")
        
        analysis = results.get('structural_analysis', {})
        print(f"\n📋 EXTRACTION STATISTICS:")
        print(f"  • Total payment schedules: {analysis.get('total_schedules', 'N/A')}")
        print(f"  • Unique combinations: {analysis.get('unique_combinations', 'N/A')}")
        print(f"  • Service types: {len(analysis.get('service_types', []))}")
        print(f"  • Plan types: {len(analysis.get('plan_types', []))}")
        
        duplicates = results.get('duplicates_and_conflicts', {})
        print(f"  • Duplicate combinations: {len(duplicates.get('duplicates', []))}")
        print(f"  • Conflicting values: {len(duplicates.get('conflicts', []))}")
        
        production = overall.get('production_readiness', {})
        print(f"\n🚀 PRODUCTION READINESS:")
        print(f"  • Ready: {production.get('ready', 'N/A')}")
        print(f"  • Confidence: {production.get('confidence_level', 'N/A')}")
        
        if overall.get('strengths'):
            print(f"\n✅ KEY STRENGTHS:")
            for strength in overall['strengths'][:3]:
                print(f"  • {strength}")
        
        if overall.get('weaknesses'):
            print(f"\n❌ KEY WEAKNESSES:")
            for weakness in overall['weaknesses'][:3]:
                print(f"  • {weakness}")
        
        if overall.get('priority_improvements'):
            print(f"\n🔧 PRIORITY IMPROVEMENTS:")
            for improvement in overall['priority_improvements'][:3]:
                print(f"  • {improvement}")
        
        print(f"\n📝 SUMMARY:")
        print(f"  {overall.get('summary', 'N/A')}")
        
        print("\n" + "="*60)


def create_parser():
    """Create command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Evaluate payment field extraction results using GPT-4",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Evaluate extraction results
  python payment_extraction_evaluator.py --input payment_schedules_all_combinations.json
  
  # Save detailed report
  python payment_extraction_evaluator.py --input results.json --output evaluation_report.json
  
  # Quiet mode with summary only
  python payment_extraction_evaluator.py --input results.json --quiet
        """
    )
    
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Input JSON file with payment extraction results"
    )
    
    parser.add_argument(
        "--output", "-o",
        help="Output file for detailed evaluation report (default: auto-generated)"
    )
    
    parser.add_argument(
        "--api-key",
        help="OpenAI API key (default: from OPENAI_API_KEY env var)"
    )
    
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Only show summary, reduce detailed output"
    )
    
    return parser


async def main():
    """Main function."""
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
    
    # Check input file
    if not Path(args.input).exists():
        print(f"❌ Error: Input file not found: {args.input}")
        return 1
    
    try:
        # Run evaluation
        evaluator = PaymentExtractionEvaluator(api_key)
        results = await evaluator.evaluate_extraction(args.input)
        
        # Determine output file
        if args.output:
            output_file = args.output
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            input_name = Path(args.input).stem
            output_file = f"evaluation_report_{input_name}_{timestamp}.json"
        
        # Save detailed report
        evaluator.save_evaluation_report(results, output_file)
        
        # Print summary
        evaluator.print_summary(results)
        
        print(f"\n💾 Detailed report saved to: {output_file}")
        print(f"🔧 Total API calls made: {results['evaluation_metadata']['total_api_calls']}")
        
        return 0
        
    except Exception as e:
        print(f"❌ Error during evaluation: {e}")
        return 1


if __name__ == "__main__":
    exit(asyncio.run(main())) 