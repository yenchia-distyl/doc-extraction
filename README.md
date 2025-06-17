# Document Extraction and Transformation System

This system extracts structured payment data from contract documents and transforms it into different output formats. It consists of two main phases: **extraction** and **transformation**.

## Overview

The system processes document chunks stored in `data/headers/` and:
1. **Extracts** payment schedule data using GPT-4o-mini
2. **Transforms** the data into nested structure formats

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set your OpenAI API key as an environment variable:
```bash
export OPENAI_API_KEY="your-api-key-here"
```

Alternatively, create a `.env` file in the project root:
```
OPENAI_API_KEY=your-api-key-here
```

## Phase 1: Data Extraction

### Extraction Approaches

#### 1. Original Extraction (Hardcoded Patterns)

**Advantages:**
- Faster (7 API calls)
- More cost-effective
- Proven for known document formats

**Limitations:**
- **Would miss new service categories** not in hardcoded patterns
- **Would miss new plan types** not explicitly programmed
- Requires code changes for new document types

**Usage:**
```bash
python extract_payment_schedules.py
```

**Performance**: ~72 seconds (7 API calls)

#### 2. LLM-Based Extraction (Dynamic Detection)

**Advantages:**
- **Automatically detects new service categories** and plan types
- More flexible for varying document formats
- No code changes needed for new document types
- More precise terminology detection

**Trade-offs:**
- More API calls (18 vs 7)
- Slightly higher cost and time

**Usage:**
```bash
python extract_payment_schedules_v2.py
```

**Performance**: ~81 seconds (18 API calls)

### Quick Start - Extraction

1. **Test the setup** (recommended):
```bash
python test_extraction.py
```

2. **Choose your extraction method:**
```bash
# Option A: Original (fast, hardcoded patterns)
python extract_payment_schedules.py

# Option B: LLM-based (flexible, dynamic detection)
python extract_payment_schedules_v2.py
```

### Extraction Outputs

- `data/output/payment_schedules_v2.json` - Original extraction (flat structure)
- `data/output/payment_schedules_v2_llm.json` - LLM-based extraction (flat structure)

### Fields Being Extracted

The system extracts the following payment fields:
- Lesser of Logic Language included (Y/N)
- Lesser of Rate
- Reimb Methodology
- Reimb Methodology short
- Flat Fee
- Provider Type, IP/OP, Service Type, Plan Type (hierarchy fields)

## Phase 2: Data Transformation

Transform the extracted flat data into nested hierarchical structures that match the target format.

### Programmatic Transformation

**Advantages:**
- Fast and deterministic (~0.047 seconds)
- No external API dependencies
- Consistent results
- Cost-effective

**Usage:**
```bash
# Transform original extraction
python transform_payment_data.py

# Or modify the script to transform LLM-based extraction:
# Change input file from payment_schedules_v2.json to payment_schedules_v2_llm.json
```

**Performance**: ~47 milliseconds (**1,700x faster than extraction!**)

### Transformation Output

- `data/output/payment_schedules_nested.json` - Nested structure format

## Complete Workflow

### Option A: Original Extraction + Transformation
```bash
# 1. Extract payment data (~72 seconds, 7 API calls)
python extract_payment_schedules.py

# 2. Transform to nested structure (~0.047 seconds)
python transform_payment_data.py
```

### Option B: LLM-Based Extraction + Transformation
```bash
# 1. Extract payment data (~81 seconds, 18 API calls)
python extract_payment_schedules_v2.py

# 2. Transform to nested structure (~0.047 seconds)
# Note: Modify transform_payment_data.py input file to payment_schedules_v2_llm.json
python transform_payment_data.py
```

## Data Structure Flow

### Input → Extraction → Transformation

```
Contract Documents (markdown)
    ↓ (extract_payment_schedules.py OR extract_payment_schedules_v2.py)
payment_schedules_v2.json OR payment_schedules_v2_llm.json (flat structure)
    ↓ (transform_payment_data.py)
payment_schedules_nested.json (nested structure)
```

### Detailed Structure Mapping

**Flat Structure** (`payment_schedules_v2.json`):
```json
{
  "hierarchy": {
    "line_of_business": "MEDICARE",
    "provider_type": "Professional Services",
    "ip_op": "OP",
    "service_type": "Therapy Services",
    "plan_type": "MA PLAN"
  },
  "payment_fields": [...]
}
```

**Nested Structure** (`payment_schedules_nested.json`):
```json
{
  "sections": [{
    "section_name": "Main Contract Details",
    "subsections": [{
      "section_name": "Medicare",
      "subsections": [{
        "section_name": "Professional Services",
        "subsections": [{
          "section_name": "OP",
          "subsections": [{
            "section_name": "Therapy Services",
            "subsections": [{
              "section_name": "MA PLAN",
              "extracted_fields": [...]
            }]
          }]
        }]
      }]
    }]
  }]
}
```

## Templates and Schema

### Schema Definition (`data/templates/foir.yml`)
Defines the data types and structure:
- `ExtractedData`: Base fields for each data point
- `ExtractedField`: Extends ExtractedData with history and subfields
- `FinalOutputIntermediateRepresentation`: Top-level structure

### Target Example (`data/target_output_nested.json`)
Shows the desired nested output format with sample data.

## File Structure

```
/
├── data/
│   ├── headers/              # Input: Pre-chunked documents
│   ├── templates/
│   │   └── foir.yml         # Schema definition
│   ├── target_output_nested.json # Example output format
│   └── output/              # Generated results
│       ├── payment_schedules_v2.json         # Original extraction
│       ├── payment_schedules_v2_llm.json     # LLM-based extraction
│       └── payment_schedules_nested.json     # Nested (transformed)
├── extract_payment_schedules.py      # Original extraction (hardcoded)
├── extract_payment_schedules_v2.py   # LLM-based extraction (dynamic)
├── transform_payment_data.py         # Programmatic transformation
├── test_extraction.py                # Test setup
├── requirements.txt
└── README.md
```

## Performance Summary

| Method | Time | API Calls | Flexibility | Cost |
|--------|------|-----------|-------------|------|
| **Original Extraction** | ~72 seconds | 7 | ❌ Hardcoded | $ |
| **LLM-Based Extraction** | ~81 seconds | 18 | ✅ Dynamic | $$ |
| **Transformation** | ~0.047 seconds | 0 | ✅ Fast | Free |

## Extraction Method Comparison

| Feature | Original | LLM-Based v2 |
|---------|----------|--------------|
| **Service Detection** | 5 hardcoded patterns | 7+ dynamically detected |
| **New Categories** | ❌ Would miss | ✅ Auto-detects |
| **New Plan Types** | ❌ Would miss | ✅ Auto-detects |
| **API Calls** | 7 | 18 |
| **Schedules Created** | 7 | 9 |
| **Code Changes for New Docs** | Required | Not needed |

## How It Works

### Original Extraction Phase
1. **Document Processing**: Reads pre-chunked contract documents
2. **Pattern Matching**: Uses hardcoded regex patterns for service/plan detection
3. **LLM Analysis**: Uses GPT-4o-mini only for payment field extraction
4. **Hierarchical Organization**: Organizes by predefined categories

### LLM-Based Extraction Phase
1. **Document Processing**: Reads pre-chunked contract documents
2. **LLM Detection**: Uses GPT-4o-mini for line of business, service categories, and plan types
3. **LLM Analysis**: Uses GPT-4o-mini for payment field extraction
4. **Dynamic Organization**: Organizes by LLM-detected categories

### Transformation Phase
1. **Structure Mapping**: Maps flat hierarchy to nested sections/subsections
2. **Field Transformation**: Converts `payment_fields` to `extracted_fields` format
3. **Data Preservation**: Maintains all field values, citations, and rationales

## Customization

### Modify Extraction Fields
Update the extraction fields in either extraction script

### Modify Transformation Logic
Edit hierarchy mapping in `transform_payment_data.py`

### Change Output Structure
Modify the target schema in `data/templates/foir.yml`

## Troubleshooting

- **API Key Error**: Make sure your OpenAI API key is set correctly
- **Rate Limiting**: Reduce API call frequency if needed
- **Memory Issues**: Process fewer chunks at a time for large documents
- **Slow Performance**: Use original extraction for speed, LLM-based for flexibility
- **Missing Categories**: Use LLM-based extraction for new document types

## Best Practices

1. **Use original extraction** for known document formats (faster, cheaper)
2. **Use LLM-based extraction** for new/varying document types (more flexible)
3. **Always use programmatic transformation** for speed (1,700x faster than LLM)
4. **Test extraction first** with `test_extraction.py` before full runs
5. **Monitor API costs** during extraction phase

## When to Use Which Approach

### Use Original Extraction When:
- Document formats are stable and known
- Service categories don't change frequently
- Speed and cost are priorities
- You have a consistent document template

### Use LLM-Based Extraction When:
- Processing new document types
- Service categories may vary
- Plan types are not standardized
- You need maximum flexibility and accuracy 