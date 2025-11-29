"""
LangChain tool wrappers for SRE Agent.

Tool descriptions are designed to encourage efficient context usage:
- Prefer grep over read_file for large files
- Use small limits when reading files
- Search first, read targeted sections later
- Use summarize=False for important context files (topology, config, etc.)
"""

from typing import Any, List

from langchain_core.tools import tool

from .tools import file_tools, search_tools, system_tools

# Prefix added to tool output when summarization should be skipped
NO_SUMMARIZE_PREFIX = "[NO_SUMMARIZE]"

# Threshold for refusing large unsummarized content
LARGE_CONTENT_THRESHOLD = 5000

# Error message when content is too large with summarize=False
LARGE_CONTENT_ERROR = """⚠️ REFUSED: Output too large ({char_count} chars) with summarize=False.

To proceed, you MUST either:
1. Use summarize=True (recommended for large files)
2. Use smaller limit (e.g., limit=10-20 lines)
3. Use grep with a more specific pattern first

Content was NOT returned to protect context window.
"""


def _check_large_content(result: str, summarize: bool) -> str:
    """Check content size and refuse if too large with summarize=False."""
    if not summarize and len(result) > LARGE_CONTENT_THRESHOLD:
        # REFUSE to return - just return error message
        return LARGE_CONTENT_ERROR.format(char_count=len(result))
    elif not summarize:
        return f"{NO_SUMMARIZE_PREFIX}\n{result}"
    return result


@tool
def read_file(file_path: str, offset: int = 1, limit: int = 50, summarize: bool = True) -> str:
    """Read a section of a file.

    Args:
        file_path: Path to the file to read.
        offset: Line number to start from (1-indexed). Default: 1.
        limit: Max lines to read (30-50 recommended). Default: 50.
        summarize: If True, large outputs may be summarized to save context.
                   Set to False for important files you need in full:
                   - topology.md (service dependencies)
                   - config files
                   - small reference files
                   Default: True.

    Returns:
        File content for the specified range.

    When to use summarize=False:
        - topology.md or architecture docs (need full context for reasoning)
        - Configuration files (need exact values)
        - Small files (<100 lines) with important details
        - Files you'll reference multiple times

    When to use summarize=True (default):
        - Large TSV/log files (traces, events, metrics)
        - Files where you only need key findings
        - Exploratory reads before you know what's important
    """
    result = file_tools.read_file(file_path, offset, limit)
    return _check_large_content(result, summarize)


@tool
def list_directory(path: str = ".") -> str:
    """List contents of a directory. Use this FIRST to understand available files.

    Args:
        path: Directory path to list.

    Returns:
        List of files and directories with FILE/DIR prefix.
    """
    return file_tools.list_directory(path)


@tool
def grep(
    pattern: str,
    path: str = ".",
    case_insensitive: bool = False,
    recursive: bool = True,
    line_numbers: bool = True,
    summarize: bool = True,
    max_matches: int = 10,
) -> str:
    """Search for patterns in files. THIS IS YOUR PRIMARY INVESTIGATION TOOL.

    Args:
        pattern: Regex pattern. Use | for OR: "error|fail|exception"
        path: File or directory to search.
        case_insensitive: True for case-insensitive search.
        recursive: True to search subdirectories.
        line_numbers: True to show line numbers (useful for read_file offset).
        summarize: If True, large outputs may be summarized.
                   Set to False when you need all matches for analysis.
                   Default: True.

    USEFUL PATTERNS:
        Errors: "error|Error|fail|Fail|exception"
        HTTP: "5[0-9][0-9]|timeout|refused"
        K8s: "Killing|Unhealthy|BackOff|Failed|OOMKilled"
        Connection: "ECONNREFUSED|EPERM|connection refused"
    """
    result = search_tools.grep(pattern, path, case_insensitive, recursive, line_numbers, max_matches)
    return _check_large_content(result, summarize)


@tool
def file_search(pattern: str, path: str = ".") -> str:
    """Find files matching a name pattern (glob).

    Args:
        pattern: Glob pattern (e.g., "*.json", "alerts_*.json")
        path: Directory to search in.

    Returns:
        List of matching file paths.
    """
    return search_tools.file_search(pattern, path)


@tool
def codebase_search(query: str) -> str:
    """Semantic search (falls back to keyword grep).

    Args:
        query: Search query.
    """
    return search_tools.codebase_search(query)


@tool
def run_terminal_cmd(command: str) -> str:
    """Run a terminal command.

    Args:
        command: Shell command to execute.
    """
    return system_tools.run_terminal_cmd(command)


@tool
def todo_write(todos: str) -> str:
    """Manage the investigation PLAN and hypothesis table.

    Use this tool to:
    1. Track your investigation plan (next steps).
    2. Maintain your hypothesis table.
    3. Track explained alerts.

    Args:
        todos: JSON array of items. Each item has:
            - id: Unique identifier (string)
            - content: The plan step OR hypothesis OR alert tracking info (string)
            - status: "pending" | "in_progress" | "completed"

    CRITICAL:
    1. You MUST include the Hypothesis Table and Alerts Table in your updates.
    2. You MUST include a specific PLAN step for every INVESTIGATING hypothesis.

    Example content formats:
    - Plan: "PLAN: Validate H1 by grepping for connection errors in checkout logs"
    - Hypothesis: "| H1: Network Issue | Ev: None | Status: INVESTIGATING |"
    - Alert: "| Alert: 503 Error | Explained: False |"
    """
    import json

    try:
        items = json.loads(todos)
        output = ["📋 Investigation Progress:"]
        for item in items:
            status_icon = {"pending": "⬜", "in_progress": "🔄", "completed": "✅", "cancelled": "❌"}
            icon = status_icon.get(item.get("status", "pending"), "⬜")
            output.append(f"  {icon} {item.get('content', 'Unknown')}")
        return "\n".join(output)
    except Exception:
        return f"Todo updated: {todos}"


def get_tools_list(config: Any) -> List[Any]:
    """Return list of enabled tools based on config."""
    global LARGE_CONTENT_THRESHOLD
    if hasattr(config, "max_tool_output_length"):
        LARGE_CONTENT_THRESHOLD = config.max_tool_output_length

    # Set up blacklist checker if configured
    if hasattr(config, "blacklist") and config.blacklist.patterns:
        file_tools.set_blacklist_checker(config.blacklist.is_blacklisted)
        search_tools.set_blacklist_checker(config.blacklist.is_blacklisted)

    tools = []

    if config.search_tools.enabled:
        if config.search_tools.enable_grep:
            tools.append(grep)
        if config.search_tools.enable_file_search:
            tools.append(file_search)
        if config.search_tools.enable_codebase_search:
            tools.append(codebase_search)

    if config.file_tools.enabled:
        if config.file_tools.enable_list_directory:
            tools.append(list_directory)
        if config.file_tools.enable_read_file:
            tools.append(read_file)
        if config.file_tools.enable_edit_file:
            tools.append(edit_file)
        if config.file_tools.enable_create_file:
            tools.append(create_file)

    if config.system_tools.enabled and config.system_tools.enable_run_terminal_cmd:
        tools.append(run_terminal_cmd)

    tools.append(todo_write)

    return tools


@tool
def edit_file(file_path: str, edit_instruction: str, code_edit: str) -> str:
    """Edit a file by replacing exact string matches."""
    return file_tools.edit_file(file_path, edit_instruction, code_edit)


@tool
def create_file(file_path: str, content: str) -> str:
    """Create a new file with the given content."""
    return file_tools.create_file(file_path, content)
