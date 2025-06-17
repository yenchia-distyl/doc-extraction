#!/usr/bin/env python3
"""
Test script to verify the extraction setup and test on a single chunk.
"""

import json
import os
import asyncio
from pathlib import Path
from extract_document_values import DocumentExtractor

async def test_single_extraction():
    """Test extraction on a single chunk to verify setup."""
    
    # Check API key
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("❌ ERROR: OPENAI_API_KEY environment variable not set")
        print("Please set it with: export OPENAI_API_KEY='your-key-here'")
        return False
    
    print("✅ OpenAI API key found")
    
    # Check if header files exist
    headers_dir = Path("data/headers")
    if not headers_dir.exists():
        print(f"❌ ERROR: Headers directory not found at {headers_dir}")
        return False
    
    header_files = list(headers_dir.glob("*.md"))
    if not header_files:
        print(f"❌ ERROR: No .md files found in {headers_dir}")
        return False
    
    print(f"✅ Found {len(header_files)} header files")
    
    # Test extraction on first file
    test_file = header_files[0]
    print(f"\n📄 Testing extraction on: {test_file.name}")
    
    try:
        extractor = DocumentExtractor(api_key)
        
        # Read test file content
        with open(test_file, "r", encoding="utf-8") as f:
            content = f.read()
        
        print(f"   File size: {len(content)} characters")
        print(f"   First 200 chars: {content[:200]}...")
        
        # Test extraction
        import aiohttp
        async with aiohttp.ClientSession() as session:
            result = await extractor.extract_from_chunk(
                session,
                content,
                test_file.name,
                {"Provider Type", "IP/OP", "Service Type"}  # Test with subset of fields
            )
        
        if "error" in result:
            print(f"\n❌ Extraction failed: {result['error']}")
            return False
        
        print(f"\n✅ Extraction successful!")
        print(f"   Extracted {len(result['extracted_fields'])} fields")
        
        if result['extracted_fields']:
            print("\n📊 Sample extracted fields:")
            for field in result['extracted_fields'][:3]:  # Show first 3 fields
                print(f"\n   Field: {field['data_point_name']}")
                print(f"   Value: {field['value']}")
                print(f"   Citation: {field['citation'][:100]}...")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error during test: {str(e)}")
        return False


async def main():
    """Run the test."""
    print("🧪 Document Extraction Test\n")
    
    success = await test_single_extraction()
    
    if success:
        print("\n✅ All tests passed! You can now run the full extraction with:")
        print("   python extract_document_values.py")
    else:
        print("\n❌ Tests failed. Please fix the issues above before running the full extraction.")


if __name__ == "__main__":
    asyncio.run(main()) 