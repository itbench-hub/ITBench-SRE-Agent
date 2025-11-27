import shlex
import subprocess


def run_terminal_cmd(
    command: str,
    background: bool = False,
) -> str:
    """
    Run a terminal command.

    Args:
        command: The command to run.
        background: Whether to run in the background (not supported in this simple implementation, included for API compat).

    Returns:
        The stdout and stderr of the command.
    """
    try:
        # Split command string into list for subprocess
        args = shlex.split(command)

        if background:
            # Start and detach? For now, just warn it's not fully supported or run and return PID.
            # Keeping it simple/synchronous for safety in this diagnostic agent unless requested otherwise.
            return "Background execution is not supported in this diagnostic agent version."

        result = subprocess.run(args, capture_output=True, text=True, timeout=60)  # Timeout for safety

        output = f"Exit Code: {result.returncode}\n"
        if result.stdout:
            output += f"STDOUT:\n{result.stdout}\n"
        if result.stderr:
            output += f"STDERR:\n{result.stderr}\n"

        return output

    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 60 seconds."
    except Exception as e:
        return f"Error executing command: {str(e)}"

