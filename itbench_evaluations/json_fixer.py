"""JSON fixing utilities for ITBench Evaluations."""

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("itbench_evaluations.json_fixer")


def remove_trailing_commas(json_str: str) -> str:
    """Remove trailing commas from JSON-like string.
    
    Handles trailing commas before ] and } which are common LLM mistakes.
    """
    import re
    # Remove trailing commas before closing brackets/braces
    # Match comma followed by optional whitespace and closing bracket/brace
    json_str = re.sub(r',(\s*[\]\}])', r'\1', json_str)
    return json_str


def add_missing_commas(json_str: str) -> str:
    """Add missing commas between JSON elements.
    
    Handles missing commas which are common LLM mistakes, like:
    - "value1" "key2" -> "value1", "key2" (with or without newline)
    - } { -> }, {
    - ] [ -> ], [
    - "value" { -> "value", {
    - } " -> }, "
    """
    import re
    
    # Add comma after string value followed by whitespace and string key
    # "value"    "key" -> "value",    "key" (preserves original whitespace)
    json_str = re.sub(r'(")(\s+)(")', r'\1,\2\3', json_str)
    
    # Add comma after } followed by whitespace and {
    json_str = re.sub(r'(\})(\s+)(\{)', r'\1,\2\3', json_str)
    
    # Add comma after ] followed by whitespace and [
    json_str = re.sub(r'(\])(\s+)(\[)', r'\1,\2\3', json_str)
    
    # Add comma after } followed by whitespace and "
    json_str = re.sub(r'(\})(\s+)(")', r'\1,\2\3', json_str)
    
    # Add comma after ] followed by whitespace and "
    json_str = re.sub(r'(\])(\s+)(")', r'\1,\2\3', json_str)
    
    # Add comma after number followed by whitespace and " (for number values)
    json_str = re.sub(r'(\d)(\s+)(")', r'\1,\2\3', json_str)
    
    # Add comma after true/false/null followed by whitespace and "
    json_str = re.sub(r'(true|false|null)(\s+)(")', r'\1,\2\3', json_str)
    
    # Add comma after number followed by whitespace and { or [
    json_str = re.sub(r'(\d)(\s+)([\{\[])', r'\1,\2\3', json_str)
    
    # Add comma after true/false/null followed by whitespace and { or [
    json_str = re.sub(r'(true|false|null)(\s+)([\{\[])', r'\1,\2\3', json_str)
    
    return json_str


def fix_unbalanced_braces(json_str: str) -> str:
    """Fix unbalanced braces/brackets at the end of JSON.
    
    LLMs sometimes add extra closing braces/brackets.
    This function removes trailing unmatched closers.
    """
    # Count braces and brackets
    open_braces = json_str.count('{')
    close_braces = json_str.count('}')
    open_brackets = json_str.count('[')
    close_brackets = json_str.count(']')
    
    # Remove excess closing braces from the end
    while close_braces > open_braces and json_str.rstrip().endswith('}'):
        json_str = json_str.rstrip()
        json_str = json_str[:-1]
        close_braces -= 1
    
    # Remove excess closing brackets from the end
    while close_brackets > open_brackets and json_str.rstrip().endswith(']'):
        json_str = json_str.rstrip()
        json_str = json_str[:-1]
        close_brackets -= 1
    
    return json_str


def fix_misordered_array_closure(json_str: str) -> str:
    """Fix a common LLM bug for top-level arrays: ending with `]\n}` or `]}`.

    We see the judge sometimes emits:
        [ { ... } ] }
    i.e. a stray `}` after the array close. Often that `}` was meant to close the
    last object *before* the `]`. This transform rewrites the tail:
        ... ] }  ->  ... } ]

    This is intentionally conservative: only applied when the payload appears to
    be a top-level JSON array.
    """
    s = json_str.strip()
    if not s.startswith("["):
        return json_str

    # If it ends like ... ] } (allow whitespace between)
    if not (s.endswith("}") and "]" in s):
        return json_str

    # Only attempt this fix when total braces are balanced.
    # Rationale:
    # - If there's an *extra* trailing "}", then close_braces > open_braces and we should
    #   just drop it (handled by fix_unbalanced_braces).
    # - If braces are balanced but the payload ends with `] }`, it's likely the model
    #   missed a `}` before `]` and then added it after (misordered closure).
    if s.count("{") != s.count("}"):
        return json_str

    # Find the last closing bracket for the top-level array
    last_bracket = s.rfind("]")
    last_brace = s.rfind("}")

    # Only act when the final '}' comes after the final ']'
    if last_brace <= last_bracket:
        return json_str

    # And the very end looks like: ] <ws> }
    tail = s[last_bracket:last_brace + 1]
    if not (tail.startswith("]") and tail.endswith("}")):
        return json_str

    # Replace the tail "] <ws> }" with "} ]" (preserve the whitespace that was between ] and })
    # Example:
    #   ... ]\n}  ->  ... }\n]
    between = s[last_bracket + 1:last_brace]
    s2 = s[:last_bracket] + "}" + between + "]"
    return s2


def fix_json_string(json_str: str) -> str:
    """Apply all JSON fixes: remove trailing commas, add missing commas, fix braces."""
    json_str = remove_trailing_commas(json_str)
    json_str = add_missing_commas(json_str)
    json_str = fix_unbalanced_braces(json_str)
    json_str = fix_misordered_array_closure(json_str)
    return json_str


def simple_json_repair(content: str) -> Optional[Dict[str, Any]]:
    """Simple JSON repair function that handles common formatting issues.
    
    This function attempts to fix malformed JSON by:
    - Removing markdown code blocks
    - Removing trailing commas (common LLM mistake)
    - Unescaping common escape sequences
    - Removing surrounding quotes
    
    Args:
        content: Potentially malformed JSON string
    
    Returns:
        Parsed JSON object if successful, None if failed
    """
    try:
        # Remove markdown code blocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            parts = content.split("```")
            if len(parts) >= 2:
                content = parts[1].strip()
        
        # Remove surrounding quotes if present
        content = content.strip()
        if content.startswith('"') and content.endswith('"'):
            content = content[1:-1]
        
        # Try to unescape common escape sequences
        content = content.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t')
        
        # Remove trailing commas (very common LLM mistake)
        content = remove_trailing_commas(content)
        
        # Try to parse
        result = json.loads(content)
        logger.debug("Simple JSON repair successful")
        return result
        
    except json.JSONDecodeError as e:
        logger.debug(f"Simple JSON repair failed: {e}")
        return None
    except Exception as e:
        logger.debug(f"Unexpected error in JSON repair: {e}")
        return None


def extract_json_from_text(content: str) -> Optional[Dict[str, Any]]:
    """Extract and parse JSON from text that may contain non-JSON content.
    
    Tries to find JSON object or array boundaries in the text.
    
    Args:
        content: Text that may contain JSON
    
    Returns:
        Parsed JSON object if found, None otherwise
    """
    try:
        # Try direct parse first
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    
    # Try to find JSON boundaries
    json_start = -1
    json_end = -1
    
    # Look for object
    obj_start = content.find('{')
    obj_end = content.rfind('}')
    
    # Look for array
    arr_start = content.find('[')
    arr_end = content.rfind(']')
    
    # Use whichever starts first
    if obj_start >= 0 and (arr_start < 0 or obj_start < arr_start):
        json_start = obj_start
        json_end = obj_end + 1
    elif arr_start >= 0:
        json_start = arr_start
        json_end = arr_end + 1
    
    if json_start >= 0 and json_end > json_start:
        try:
            json_str = content[json_start:json_end]
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
    
    return None


# JSON fixing prompt for LLM-based repair (if needed in future)
JSON_FIX_PROMPT = """You are a JSON formatting expert. Your task is to fix malformed JSON content and return a valid JSON object.

The input may contain:
1. Malformed JSON with syntax errors
2. JSON wrapped in markdown code blocks
3. JSON with unescaped characters
4. JSON with missing quotes, brackets, or commas
5. JSON mixed with explanatory text
6. JSON with trailing commas
7. JSON with unquoted keys
8. JSON with invalid escape sequences

Your response should be ONLY the corrected JSON object, nothing else. Do not include any explanations, markdown formatting, or additional text.

If the input cannot be converted to valid JSON, return empty JSON

Common fixes to apply:
- Add missing quotes around keys and string values
- Remove trailing commas
- Fix unescaped quotes and special characters
- Add missing brackets or braces
- Remove any non-JSON text before or after the JSON content

Now fix this JSON content:"""


