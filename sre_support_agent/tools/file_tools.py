"""
File operation tools for the SRE agent.

These tools provide read/write access to the filesystem, with optional
blacklist filtering to prevent access to sensitive files.
"""

import json
import os
from typing import Callable, Optional


# Global blacklist checker - set by langchain_tools.py when tools are initialized
_blacklist_checker: Optional[Callable[[str], bool]] = None


def set_blacklist_checker(checker: Callable[[str], bool]) -> None:
    """Set the global blacklist checker function."""
    global _blacklist_checker
    _blacklist_checker = checker


def _is_blacklisted(file_path: str) -> bool:
    """Check if a file is blacklisted."""
    if _blacklist_checker is None:
        return False
    return _blacklist_checker(file_path)


def read_file(
    file_path: str,
    offset: int = 1,
    limit: int = 50,
) -> str:
    """
    Read a section of a file.

    IMPORTANT: Use small limits (30-50 lines) to avoid context exhaustion.
    For large files (TSV, logs), use grep first to find relevant sections.

    Args:
        file_path: The path to the file to read.
        offset: The line number to start reading from (1-indexed).
        limit: The maximum number of lines to read. Default: 50. KEEP THIS SMALL.

    Returns:
        The content of the file section with line count info.
    """
    # Check blacklist
    if _is_blacklisted(file_path):
        return f"Error: Access to {file_path} is not permitted (blacklisted)."

    try:
        if not os.path.exists(file_path):
            return f"Error: File {file_path} does not exist"

        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        total_lines = len(lines)

        # Warn if file is large and full read is attempted
        if total_lines > 100 and limit > 50 and offset == 1:
            warning = f"⚠️ WARNING: This file has {total_lines} lines. Consider using grep first to find relevant sections, then read_file with specific offset.\n\n"
        else:
            warning = ""

        # Convert to 0-indexed
        start_idx = max(0, offset - 1)
        end_idx = min(total_lines, start_idx + limit)

        content_lines = lines[start_idx:end_idx]
        content = "".join(content_lines)

        remaining = total_lines - end_idx
        remaining_note = (
            f"\n[... {remaining} more lines. Use offset={end_idx+1} to continue reading ...]" if remaining > 0 else ""
        )

        return (
            f"{warning}--- {file_path} (lines {start_idx+1}-{end_idx} of {total_lines}) ---\n{content}{remaining_note}"
        )

    except Exception as e:
        return f"Error reading file {file_path}: {str(e)}"


def edit_file(
    file_path: str,
    edit_instruction: str,
    code_edit: str,
) -> str:
    """
    Edit a file by replacing exact string matches.

    Args:
        file_path: The path to the file to edit.
        edit_instruction: Description of the change (for logging/audit).
        code_edit: A JSON string mapping old_string -> new_string or just the new content if replacing whole file (not recommended).
                   Format: {"old_string": "new_string"}

    Returns:
        Status message.
    """
    # Check blacklist
    if _is_blacklisted(file_path):
        return f"Error: Access to {file_path} is not permitted (blacklisted)."

    try:
        if not os.path.exists(file_path):
            return f"Error: File {file_path} does not exist"

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        try:
            edits = json.loads(code_edit)
        except json.JSONDecodeError:
            # Fallback or strict? Let's be strict for SRE safety.
            return "Error: code_edit must be a valid JSON object mapping old text to new text."

        if not isinstance(edits, dict):
            return "Error: code_edit must be a dictionary."

        for old, new in edits.items():
            if old not in content:
                return f"Error: Could not find exact match for content to replace: '{old[:50]}...'"
            content = content.replace(old, new)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return f"Successfully edited {file_path}"

    except Exception as e:
        return f"Error editing file {file_path}: {str(e)}"


def create_file(
    file_path: str,
    content: str,
) -> str:
    """
    Create a new file with the given content.

    Args:
        file_path: The path to the file to create.
        content: The content to write to the file.

    Returns:
        Status message.
    """
    # Check blacklist
    if _is_blacklisted(file_path):
        return f"Error: Access to {file_path} is not permitted (blacklisted)."

    try:
        if os.path.exists(file_path):
            return f"Error: File {file_path} already exists. Use edit_file to modify it."

        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return f"Successfully created file {file_path}"

    except Exception as e:
        return f"Error creating file {file_path}: {str(e)}"


def delete_file(
    file_path: str,
) -> str:
    """
    Delete a file.

    Args:
        file_path: The path to the file to delete.

    Returns:
        Status message.
    """
    # Check blacklist
    if _is_blacklisted(file_path):
        return f"Error: Access to {file_path} is not permitted (blacklisted)."

    try:
        if not os.path.exists(file_path):
            return f"Error: File {file_path} does not exist"

        os.remove(file_path)
        return f"Successfully deleted {file_path}"

    except Exception as e:
        return f"Error deleting file {file_path}: {str(e)}"


def list_directory(
    path: str = ".",
) -> str:
    """
    List contents of a directory.

    Args:
        path: The directory path to list.

    Returns:
        List of files and directories (excluding blacklisted items).
    """
    try:
        if not os.path.exists(path):
            return f"Error: Path {path} does not exist"

        items = os.listdir(path)
        result = []
        for item in items:
            item_path = os.path.join(path, item)
            
            # Skip blacklisted items
            if _is_blacklisted(item_path):
                continue
                
            type_str = "DIR" if os.path.isdir(item_path) else "FILE"
            result.append(f"{type_str}: {item}")

        return "\n".join(sorted(result))

    except Exception as e:
        return f"Error listing directory {path}: {str(e)}"
