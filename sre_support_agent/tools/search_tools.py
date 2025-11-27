"""
Search tools for the SRE agent.

These tools provide grep, file search, and semantic search capabilities,
with optional blacklist filtering to prevent access to sensitive files.
"""

import fnmatch
import os
import subprocess
from typing import Callable, List, Optional


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


def _filter_grep_output(output: str) -> str:
    """Filter grep output to remove lines from blacklisted files."""
    if _blacklist_checker is None:
        return output
    
    filtered_lines = []
    for line in output.splitlines():
        # Grep output format is typically: filename:line_number:content
        # or just: filename:content
        if ":" in line:
            file_path = line.split(":")[0]
            if not _is_blacklisted(file_path):
                filtered_lines.append(line)
        else:
            # Line doesn't contain a file path, include it
            filtered_lines.append(line)
    
    return "\n".join(filtered_lines)


def grep(
    pattern: str,
    path: str = ".",
    case_insensitive: bool = True,
    recursive: bool = True,
    line_numbers: bool = True,
    max_matches: int = 10,
) -> str:
    """
    Search for a pattern in files using grep.

    Args:
        pattern: The regex pattern to search for.
        path: The directory or file to search in.
        case_insensitive: Whether to ignore case.
        recursive: Whether to search recursively.
        line_numbers: Whether to show line numbers.
        max_matches: Maximum matches per file.

    Returns:
        The grep output (filtered to exclude blacklisted files).
    """
    # If searching a specific file, check blacklist first
    if os.path.isfile(path) and _is_blacklisted(path):
        return f"Error: Access to {path} is not permitted (blacklisted)."

    command = ["grep"]
    if case_insensitive:
        command.append("-i")
    if recursive and os.path.isdir(path):
        command.append("-r")
    if line_numbers:
        command.append("-n")
    if max_matches and max_matches > 0:
        command.extend(["-m", str(max_matches)])

    command.append(pattern)
    command.append(path)

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,  # grep returns 1 if no matches, which is not an error for us
        )

        if result.returncode == 0:
            # Filter out blacklisted files from output
            filtered_output = _filter_grep_output(result.stdout)
            
            if not filtered_output.strip():
                return "No matches found."
            
            lines = filtered_output.splitlines()
            if len(lines) > 500:
                return "\n".join(lines[:500]) + f"\n... ({len(lines)-500} more matches truncated)"
            return filtered_output
        elif result.returncode == 1:
            return "No matches found."
        else:
            return f"Error executing grep: {result.stderr}"

    except Exception as e:
        return f"Error executing grep: {str(e)}"


def file_search(
    pattern: str,
    path: str = ".",
) -> str:
    """
    Find files matching a name pattern (glob).

    Args:
        pattern: The glob pattern (e.g. "*.py").
        path: The directory to search in.

    Returns:
        List of matching files (excluding blacklisted files).
    """
    matches = []
    try:
        for root, dirnames, filenames in os.walk(path):
            for filename in fnmatch.filter(filenames, pattern):
                file_path = os.path.join(root, filename)
                
                # Skip blacklisted files
                if _is_blacklisted(file_path):
                    continue
                    
                matches.append(file_path)

        if not matches:
            return "No matching files found."

        if len(matches) > 200:
            return "\n".join(matches[:200]) + f"\n... ({len(matches)-200} more files truncated)"

        return "\n".join(matches)

    except Exception as e:
        return f"Error searching files: {str(e)}"


def codebase_search(
    query: str,
) -> str:
    """
    Semantic search in the codebase.
    Note: Since we don't have an embedding index, this falls back to a keyword search using grep.

    Args:
        query: The search query.

    Returns:
        Search results (filtered to exclude blacklisted files).
    """
    # Fallback to grep for this implementation
    return f"Performing keyword search for '{query}'...\n" + grep(query, recursive=True, case_insensitive=True)
