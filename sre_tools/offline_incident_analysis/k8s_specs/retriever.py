"""
K8s spec retrieval utilities.
"""

import ast
import csv
import json
import re
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import numpy as np
    import pandas as pd
except ImportError:
    pd = None
    np = None

try:
    from drain3 import TemplateMiner
    from drain3.masking import MaskingInstruction
    from drain3.template_miner_config import TemplateMinerConfig
except ImportError:
    TemplateMiner = None
    TemplateMinerConfig = None
    MaskingInstruction = None

from mcp.types import TextContent, Tool

from sre_tools.utils import format_timestamp, read_json_file, read_tsv_file, truncate_string

from ..shared import (
    _build_k8_object_filter_mask,
    _get_matched_entities_summary,
    _parse_k8_object_identifier,
    _parse_k8s_body_json,
)


async def _get_k8_spec(args: dict[str, Any]) -> list[TextContent]:
    """Retrieve the Kubernetes spec for a specific resource.

    Reads k8s_objects_raw.tsv (or similar TSV file) and returns the spec
    for the specified resource.

    Supports identifier formats:
    - namespace/kind/name (PREFERRED - unambiguous)
    - kind/name (returns all matches across namespaces)
    - name (returns all matches across kinds and namespaces)

    Supports two TSV input formats:
    1) Processed format: columns timestamp, object_kind, object_name, body
    2) Raw OTEL format: columns Timestamp/TimestampTime, Body (JSON with kind/metadata.name)
    """

    def _json_error(message: str) -> list[TextContent]:
        """Return a structured JSON error so callers can reliably parse the response."""
        payload = {
            "error": message,
            "k8s_objects_file": args.get("k8s_objects_file", ""),
            "k8_object_name": args.get("k8_object_name", ""),
            "found": False,
            "spec": None,
        }
        return [TextContent(type="text", text=json.dumps(payload, indent=2))]

    if pd is None:
        return _json_error("pandas is required for this tool")

    k8s_objects_file = args.get("k8s_objects_file", "")
    k8_object_name = args.get("k8_object_name", "")
    return_all_observations = args.get("return_all_observations", False)
    include_metadata = args.get("include_metadata", True)

    if not k8s_objects_file:
        return _json_error("k8s_objects_file is required")

    if not k8_object_name:
        return _json_error(
            "k8_object_name is required. Formats: 'namespace/kind/name' (preferred), 'kind/name', or 'name'"
        )

    if not Path(k8s_objects_file).exists():
        return _json_error(f"K8s objects file not found: {k8s_objects_file}")

    try:
        df = pd.read_csv(k8s_objects_file, sep="\t")
    except Exception as e:
        return _json_error(f"Error reading k8s objects file: {e}")

    # -------------------------------------------------------------------------
    # Detect input format and normalize columns
    # -------------------------------------------------------------------------
    cols = set(df.columns)
    is_raw_otel = False

    if "object_kind" not in cols or "object_name" not in cols:
        # Try to detect and handle raw OTEL format
        body_col = "Body" if "Body" in cols else ("body" if "body" in cols else None)
        if body_col is None:
            return _json_error(
                "Unsupported k8s objects format: missing object_kind/object_name columns and no Body column found"
            )

        # Find timestamp source column
        if "TimestampTime" in cols:
            ts_src = "TimestampTime"
        elif "Timestamp" in cols:
            ts_src = "Timestamp"
        elif "timestamp" in cols:
            ts_src = "timestamp"
        else:
            return _json_error(
                "Unsupported k8s objects format: no timestamp column (TimestampTime/Timestamp/timestamp)"
            )

        def _extract_k8s_info(raw: Any) -> tuple[str, str, str]:
            """Extract kind/namespace/name from a JSON Body string."""
            obj = _parse_k8s_body_json(raw)
            if not isinstance(obj, dict):
                return ("", "", "")
            kind = obj.get("kind", "") or ""
            meta = obj.get("metadata") or {}
            name = meta.get("name", "") or ""
            namespace = meta.get("namespace", "") or ""
            return (kind, namespace, name)

        extracted = df[body_col].apply(lambda x: pd.Series(_extract_k8s_info(x)))
        extracted.columns = ["object_kind", "object_namespace", "object_name"]
        df["object_kind"] = extracted["object_kind"]
        df["object_namespace"] = extracted["object_namespace"]
        df["object_name"] = extracted["object_name"]
        df["body"] = df[body_col].astype(str)
        df["timestamp"] = pd.to_datetime(df[ts_src], errors="coerce", utc=True)

        # Drop rows where extraction failed
        df = df[(df["object_kind"].astype(str) != "") & (df["object_name"].astype(str) != "")]
        is_raw_otel = True
    else:
        # Processed format - ensure required columns exist
        if "timestamp" not in cols:
            return _json_error("Unsupported k8s objects format: missing 'timestamp' column")
        if "body" not in cols:
            if "Body" in cols:
                df["body"] = df["Body"].astype(str)
            else:
                return _json_error("Unsupported k8s objects format: missing 'body' column")
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        # Handle namespace column - could be 'object_namespace' or 'namespace'
        if "object_namespace" not in df.columns:
            if "namespace" in df.columns:
                df["object_namespace"] = df["namespace"]
            else:
                df["object_namespace"] = ""

    # Normalize columns
    df["object_kind"] = df["object_kind"].fillna("").astype(str)
    df["object_namespace"] = df["object_namespace"].fillna("").astype(str)
    df["object_name"] = df["object_name"].fillna("").astype(str)

    # Build entity_id: namespace/kind/name for namespaced, kind/name for cluster-scoped
    # Note: We use namespace/kind/name as the canonical format (not kind/namespace/name)
    df["entity_id"] = df["object_kind"] + "/" + df["object_name"]
    _ns_mask = df["object_namespace"].astype(str) != ""
    df.loc[_ns_mask, "entity_id"] = (
        df.loc[_ns_mask, "object_namespace"]
        + "/"
        + df.loc[_ns_mask, "object_kind"]
        + "/"
        + df.loc[_ns_mask, "object_name"]
    )

    # -------------------------------------------------------------------------
    # Filter by the requested object using flexible identifier parsing
    # -------------------------------------------------------------------------
    # Supported formats:
    # - namespace/kind/name (PREFERRED - unambiguous)
    # - kind/name (ambiguous - returns all matches across namespaces)
    # - name (most ambiguous - returns all matches)

    parsed_id = _parse_k8_object_identifier(k8_object_name)

    if parsed_id["format"] == "invalid":
        return _json_error(parsed_id.get("warning", "Invalid identifier"))

    # Build filter mask using the helper
    mask = _build_k8_object_filter_mask(
        df,
        parsed_id,
        kind_col="object_kind",
        namespace_col="object_namespace",
        name_col="object_name",
        entity_id_col="entity_id",
    )

    filtered_df = df[mask]

    if filtered_df.empty:
        # Provide helpful error with available entities
        available_kinds = df["object_kind"].unique().tolist()[:20]
        sample_entities = df["entity_id"].unique().tolist()[:10]
        return _json_error(
            f"No objects matching '{k8_object_name}' found. "
            f"Available kinds: {available_kinds}. "
            f"Sample entities: {sample_entities}"
        )

    # Get list of matched entities for reporting
    matched_entities = _get_matched_entities_summary(df, mask, "entity_id")

    # Sort by timestamp to get chronological order
    filtered_df = filtered_df.sort_values("timestamp", ascending=True)

    # -------------------------------------------------------------------------
    # Build response
    # -------------------------------------------------------------------------
    observations = []
    for _, row in filtered_df.iterrows():
        body_raw = row.get("body", "")
        spec_obj = _parse_k8s_body_json(body_raw)

        if not include_metadata and isinstance(spec_obj, dict):
            # Remove metadata fields if not requested
            spec_obj = {k: v for k, v in spec_obj.items() if k != "metadata"}

        ts = row.get("timestamp")
        ts_str = str(ts) if pd.notna(ts) else ""

        observations.append(
            {
                "timestamp": ts_str,
                "entity_id": row.get("entity_id", ""),
                "kind": row.get("object_kind", ""),
                "namespace": row.get("object_namespace", ""),
                "name": row.get("object_name", ""),
                "spec": spec_obj,
            }
        )

    if not observations:
        return _json_error(f"No valid specs found for '{k8_object_name}'")

    # Build output with metadata about the query
    base_output = {
        "k8s_objects_file": k8s_objects_file,
        "k8_object_name": k8_object_name,
        "identifier_format": parsed_id["format"],
        "input_format": "raw_otel" if is_raw_otel else "processed",
        "found": True,
    }

    # Add warning for ambiguous formats
    if parsed_id["is_ambiguous"] and parsed_id.get("warning"):
        base_output["warning"] = parsed_id["warning"]

    # Add matched entities info (especially useful for ambiguous queries)
    if len(matched_entities) > 1:
        base_output["matched_entities"] = matched_entities
        base_output["matched_entity_count"] = len(matched_entities)

    # Group observations by entity_id for multi-entity responses
    unique_entities = filtered_df["entity_id"].unique().tolist()

    if return_all_observations or len(unique_entities) > 1:
        # Return all observations (grouped by entity if multiple)
        if len(unique_entities) > 1:
            # Multiple entities matched - group by entity
            entities_data = {}
            for entity_id in unique_entities:
                entity_obs = [o for o in observations if o["entity_id"] == entity_id]
                if entity_obs:
                    latest = entity_obs[-1]
                    entities_data[entity_id] = {
                        "kind": latest["kind"],
                        "namespace": latest["namespace"],
                        "name": latest["name"],
                        "observation_count": len(entity_obs),
                        "first_timestamp": entity_obs[0]["timestamp"],
                        "last_timestamp": entity_obs[-1]["timestamp"],
                        "latest_spec": latest["spec"],
                        "all_observations": entity_obs if return_all_observations else None,
                    }
                    # Remove None values
                    entities_data[entity_id] = {k: v for k, v in entities_data[entity_id].items() if v is not None}

            output = {
                **base_output,
                "entity_count": len(unique_entities),
                "total_observation_count": len(observations),
                "entities": entities_data,
            }
        else:
            # Single entity with all observations
            output = {
                **base_output,
                "observation_count": len(observations),
                "first_timestamp": observations[0]["timestamp"],
                "last_timestamp": observations[-1]["timestamp"],
                "observations": observations,
            }
    else:
        # Return only the latest observation for single entity
        latest = observations[-1]
        output = {
            **base_output,
            "observation_count": len(observations),
            "timestamp": latest["timestamp"],
            "entity_id": latest["entity_id"],
            "kind": latest["kind"],
            "namespace": latest["namespace"],
            "name": latest["name"],
            "spec": latest["spec"],
        }

    return [TextContent(type="text", text=json.dumps(output, indent=2))]


# =============================================================================
# Get Context Contract - Aggregated Context Tool
# =============================================================================
