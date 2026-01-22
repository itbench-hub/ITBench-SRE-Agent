"""Data loading utilities for ITBench Evaluations."""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from .json_fixer import simple_json_repair

logger = logging.getLogger("itbench_evaluations.loader")


def canonicalize_scenario_id(name: str) -> str:
    """Extract canonical scenario ID from directory/scenario name.

    Handles various naming conventions:
    - "1", "2", "102" -> "1", "2", "102" (numeric, unchanged)
    - "Scenario-1", "scenario-1" -> "1"
    - "Scenario_1", "scenario_1" -> "1"
    - "incident-1", "Incident-1" -> "1"
    - "scenario1" -> "1"

    Args:
        name: Directory or scenario name

    Returns:
        Canonical ID (usually just the numeric part)
    """
    # If it's already just a number, return as-is
    if name.isdigit():
        return name

    # Try to extract number from common patterns
    patterns = [
        r"^[Ss]cenario[-_]?(\d+)$",  # Scenario-1, scenario_1, scenario1
        r"^[Ii]ncident[-_]?(\d+)$",  # Incident-1, incident_1
        r"^(\d+)$",  # Just a number
        r"[-_](\d+)$",  # anything-1, anything_1
    ]

    for pattern in patterns:
        match = re.match(pattern, name)
        if match:
            return match.group(1)

    # If no pattern matches, return original name
    logger.debug(f"Could not canonicalize scenario name: {name}, using as-is")
    return name


def load_ground_truth(path: str) -> Dict[str, Dict[str, Any]]:
    """Load ground truth from JSON or YAML.

    Supports multiple formats:
    - JSON array: [{"id": "1", "groups": [...], ...}, ...]
    - Single JSON file: {"id": "1", "groups": [...], ...}
    - Single YAML file: {groups: [...], propagations: [...], ...}
    - Directory of YAML files: path/<incident_id>/ground_truth.yaml

    Args:
        path: Path to ground truth file or directory

    Returns:
        Dict mapping incident_id -> ground truth dict

    Raises:
        ValueError: If the path is invalid or cannot be parsed
    """
    path = Path(path)

    if path.is_file():
        if path.suffix == ".json":
            with open(path) as f:
                data = json.load(f)

            # Handle array format
            if isinstance(data, list):
                return {str(item["id"]): item for item in data}
            # Handle single object format
            elif isinstance(data, dict):
                if "id" in data:
                    return {str(data["id"]): data}
                else:
                    # Use filename as id
                    incident_id = path.stem
                    data["id"] = incident_id
                    return {incident_id: data}

        elif path.suffix in (".yaml", ".yml"):
            with open(path) as f:
                data = yaml.safe_load(f)

            # Handle array format in YAML
            if isinstance(data, list):
                return {str(item["id"]): item for item in data}

            # Single file - use filename as id if not present
            if "id" not in data:
                incident_id = path.stem
                data["id"] = incident_id
            else:
                incident_id = str(data["id"])

            return {incident_id: data}

    elif path.is_dir():
        result = {}

        # Check for ground_truths.json in the directory (consolidated format)
        gt_json = path / "ground_truths.json"
        if gt_json.exists():
            logger.info(f"Loading consolidated ground truths from: {gt_json}")
            with open(gt_json) as f:
                data = json.load(f)
            if isinstance(data, list):
                return {str(item["id"]): item for item in data}
            return {str(data["id"]): data}

        # Scan for scenario subdirectories (ITBench-Snapshots structure)
        # Expected: path/<scenario_id>/ground_truth.yaml
        logger.info(f"Scanning directory for scenario ground truths: {path}")
        for scenario_dir in sorted(path.iterdir()):
            if scenario_dir.is_dir():
                # Try multiple ground truth file names
                gt_candidates = [
                    scenario_dir / "ground_truth.yaml",
                    scenario_dir / "ground_truth.yml",
                    scenario_dir / "ground_truth.json",
                    scenario_dir / "gt.yaml",
                    scenario_dir / "gt.json",
                ]

                for gt_file in gt_candidates:
                    if gt_file.exists():
                        if gt_file.suffix == ".json":
                            with open(gt_file) as f:
                                data = json.load(f)
                        else:
                            with open(gt_file) as f:
                                data = yaml.safe_load(f)

                        # Canonicalize the ID
                        canonical_id = canonicalize_scenario_id(scenario_dir.name)

                        if "id" not in data:
                            data["id"] = canonical_id

                        # Store with canonical ID as key
                        result[canonical_id] = data
                        # Also store original dir name for path lookups
                        data["_dir_name"] = scenario_dir.name
                        logger.debug(f"Loaded ground truth for scenario: {scenario_dir.name} -> {canonical_id}")
                        break

        if result:
            logger.info(f"Loaded {len(result)} ground truths from directory")
            return result

        raise ValueError(f"No ground truth files found in directory: {path}")

    raise ValueError(f"Invalid ground truth path: {path}")


async def load_agent_outputs(
    output_dir: str,
    incident_id: str,
) -> Tuple[List[Dict[str, Any]], int]:
    """Load agent outputs for an incident.

    Searches for agent output files in trial subdirectories:
    - output_dir/<incident_id>/<trial>/outputs/agent_output.json
    - output_dir/<incident_id>/<trial>/outputs/agent_response.json
    - output_dir/<incident_id>/<trial>/agent_output.json

    Args:
        output_dir: Base directory containing agent outputs
        incident_id: Incident identifier to load outputs for

    Returns:
        Tuple of (list of trial outputs, count of bad/unreadable runs)
        Each trial output contains:
        - "trial": trial number (int)
        - "output": agent output dict
    """
    outputs = []
    bad_runs = 0
    incident_dir = Path(output_dir) / incident_id

    logger.debug(f"Looking for agent outputs in: {incident_dir}")

    if not incident_dir.exists():
        logger.warning(f"No directory found for incident {incident_id} at {incident_dir}")
        return outputs, bad_runs

    # Find all trial directories (directories with numeric names)
    trial_dirs = sorted(
        [d for d in incident_dir.iterdir() if d.is_dir() and d.name.isdigit()], key=lambda d: int(d.name)
    )

    logger.debug(f"Found {len(trial_dirs)} trial directories for incident {incident_id}")

    for trial_dir in trial_dirs:
        # Try multiple possible file locations
        candidates = [
            trial_dir / "outputs" / "agent_output.json",
            trial_dir / "outputs" / "agent_response.json",
            trial_dir / "agent_output.json",
            trial_dir / "agent_response.json",
        ]

        output_file = None
        for candidate in candidates:
            if candidate.exists():
                output_file = candidate
                break

        if output_file:
            try:
                with open(output_file) as f:
                    file_content = f.read()

                # Try to parse as regular JSON
                try:
                    output_data = json.loads(file_content)

                    # Handle case where JSON contains a markdown-wrapped string
                    if isinstance(output_data, str):
                        logger.debug("Output data is a string, attempting to extract JSON")
                        if "```json" in output_data:
                            json_start = output_data.find("```json") + 7
                            json_end = output_data.rfind("```")
                            if json_start > 6 and json_end > json_start:
                                json_str = output_data[json_start:json_end].strip()
                                output_data = json.loads(json_str)
                        else:
                            output_data = json.loads(output_data)

                    # Load remediation plan if it exists
                    remediation_candidates = [
                        trial_dir / "outputs" / "agent_remediation.json",
                        trial_dir / "agent_remediation.json",
                    ]

                    for rem_file in remediation_candidates:
                        if rem_file.exists():
                            try:
                                with open(rem_file) as rf:
                                    rem_content = rf.read()
                                
                                rem_data = None
                                try:
                                    rem_data = json.loads(rem_content)
                                except json.JSONDecodeError:
                                    # Try to clean markdown if present
                                    if "```json" in rem_content:
                                        rem_clean = rem_content.split("```json")[1].split("```")[0].strip()
                                        try:
                                            rem_data = json.loads(rem_clean)
                                        except:
                                            rem_data = simple_json_repair(rem_content)
                                    else:
                                        rem_data = simple_json_repair(rem_content)
                                
                                if rem_data:
                                    output_data["remediation_plan"] = rem_data
                                    logger.debug(f"Loaded remediation plan from {rem_file}")
                                    break
                            except Exception as e:
                                logger.warning(f"Failed to load remediation plan from {rem_file}: {e}")

                    outputs.append(
                        {
                            "trial": int(trial_dir.name),
                            "output": output_data,
                        }
                    )
                    logger.debug(f"Successfully loaded trial {trial_dir.name}")

                except json.JSONDecodeError as e:
                    logger.warning(f"JSON parsing failed for {output_file}: {e}")

                    # Try simple JSON repair
                    fixed_data = simple_json_repair(file_content)

                    if fixed_data is not None:
                        outputs.append(
                            {
                                "trial": int(trial_dir.name),
                                "output": fixed_data,
                            }
                        )
                        logger.info(f"Fixed and loaded trial {trial_dir.name}")
                    else:
                        logger.error(f"JSON repair failed for {output_file}")
                        bad_runs += 1

            except Exception as e:
                logger.error(f"Error reading {output_file}: {e}")
                bad_runs += 1
        else:
            logger.warning(f"No agent output found in {trial_dir}")
            bad_runs += 1

    logger.info(f"Loaded {len(outputs)} valid trial outputs for incident {incident_id}, " f"found {bad_runs} bad runs")
    return outputs, bad_runs


def load_agent_outputs_sync(
    output_dir: str,
    incident_id: str,
) -> Tuple[List[Dict[str, Any]], int]:
    """Synchronous version of load_agent_outputs.

    Args:
        output_dir: Base directory containing agent outputs
        incident_id: Incident identifier to load outputs for

    Returns:
        Tuple of (list of trial outputs, count of bad/unreadable runs)
    """
    import asyncio

    return asyncio.run(load_agent_outputs(output_dir, incident_id))
