"""
K8s spec change detection and analysis.
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


def _clean_spec_for_diff(obj: Any, path: str = "") -> Any:
    """Recursively clean a spec object, removing fields that cause churn."""
    if isinstance(obj, dict):
        cleaned = {}
        for key, value in obj.items():
            # Skip explicitly ignored fields
            if key in _IGNORE_SPEC_FIELDS:
                continue

            # Skip timestamp-like keys
            key_lc = key.lower()
            # Avoid overly-broad substring matching ("timeoutSeconds" is meaningful).
            # Only drop keys that *look like timestamps* by name.
            if key_lc not in _PRESERVE_TIMESTAMP_KEYS and (
                key_lc.endswith("timestamp") or key_lc.endswith("time") or key_lc.endswith("date")
            ):
                continue

            # Handle annotations specially
            if key == "annotations" and isinstance(value, dict):
                filtered_annotations = {
                    k: v for k, v in value.items() if k not in _IGNORE_ANNOTATIONS and "time" not in k.lower()
                }
                if filtered_annotations:
                    cleaned[key] = filtered_annotations
                continue

            # Recurse
            cleaned_value = _clean_spec_for_diff(value, f"{path}.{key}")
            if cleaned_value is not None:
                cleaned[key] = cleaned_value

        return cleaned if cleaned else None

    elif isinstance(obj, list):
        cleaned_list = []
        for item in obj:
            cleaned_item = _clean_spec_for_diff(item, path)
            if cleaned_item is not None:
                cleaned_list.append(cleaned_item)
        return cleaned_list if cleaned_list else None

    else:
        return obj


def _normalize_for_diff(obj: Any) -> Any:
    """Normalize spec shapes to make diffs stable and less noisy.

    Primary goal: avoid position-based diffs for "name-keyed" lists (containers/env/volumes/...).
    Converts lists of dicts that all have a unique string `name` into dicts keyed by that name.
    """
    if isinstance(obj, dict):
        return {k: _normalize_for_diff(v) for k, v in obj.items()}

    if isinstance(obj, list):
        if obj and all(isinstance(it, dict) and isinstance(it.get("name"), str) for it in obj):
            out: dict[str, Any] = {}
            for it in obj:
                name = it.get("name")
                if not isinstance(name, str) or not name:
                    # Shouldn't happen due to the all(...) guard, but be defensive.
                    return [_normalize_for_diff(x) for x in obj]
                if name in out:
                    # Duplicate keys -> keep list form rather than losing data.
                    return [_normalize_for_diff(x) for x in obj]

                # Drop the redundant "name" key so paths become containers.<name>.image, etc.
                item_no_name = {k: v for k, v in it.items() if k != "name"}
                out[name] = _normalize_for_diff(item_no_name)
            return out

        return [_normalize_for_diff(x) for x in obj]

    return obj


def _compute_diff(old: Any, new: Any, path: str = "") -> list[dict]:
    """Compute differences between two objects recursively.

    Returns a list of changes: {"path": "...", "type": "added|removed|changed", "old": ..., "new": ...}
    No truncation - full values are returned.
    """
    changes = []

    if type(old) != type(new):
        changes.append({"path": path or "root", "type": "changed", "old": old, "new": new})
        return changes

    if isinstance(old, dict) and isinstance(new, dict):
        all_keys = set(old.keys()) | set(new.keys())
        # Deterministic ordering so pagination + diffs are stable across runs.
        for key in sorted(all_keys, key=lambda k: str(k)):
            sub_path = f"{path}.{key}" if path else key
            if key not in old:
                changes.append({"path": sub_path, "type": "added", "new": new[key]})
            elif key not in new:
                changes.append({"path": sub_path, "type": "removed", "old": old[key]})
            else:
                changes.extend(_compute_diff(old[key], new[key], sub_path))

    elif isinstance(old, list) and isinstance(new, list):
        # For lists, do a simple length/content comparison
        if len(old) != len(new):
            changes.append({"path": path or "root", "type": "changed", "old": old, "new": new})
        else:
            for i, (o, n) in enumerate(zip(old, new)):
                changes.extend(_compute_diff(o, n, f"{path}[{i}]"))

    elif old != new:
        changes.append({"path": path or "root", "type": "changed", "old": old, "new": new})

    return changes


async def _k8s_spec_change_analysis(args: dict[str, Any]) -> list[TextContent]:
    """Analyze K8s object spec changes over time.

    Groups by entity (kind/name), computes diffs between consecutive observations,
    filters out timestamp-related churn, and reports meaningful spec changes with duration.

    Supports two input formats:
    1) Processed format: columns timestamp, object_kind, object_name, body
    2) Raw OTEL format: columns Timestamp/TimestampTime, Body (JSON with kind/metadata.name)
    """

    def _json_error(message: str) -> list[TextContent]:
        """Return a structured JSON error so callers can reliably parse the response."""
        payload = {
            "error": message,
            "reference_spec_file": args.get("k8s_objects_file", ""),
            "total_change_events": 0,
            "returned_change_events": 0,
            "total_change_item_total": 0,
            "returned_change_item_total": 0,
            "total_entities": 0,
            "returned_count": 0,
            "offset": args.get("offset", 0),
            "limit": args.get("limit"),
            "entities_with_changes": [],
        }
        return [TextContent(type="text", text=json.dumps(payload, indent=2))]

    if pd is None:
        return _json_error("pandas is required for this tool")

    k8s_objects_file = args.get("k8s_objects_file", "")
    k8_object_name = args.get("k8_object_name")  # Format: Kind/name
    start_time_str = args.get("start_time")
    end_time_str = args.get("end_time")
    limit = args.get("limit")
    offset = args.get("offset", 0)
    include_no_change = args.get("include_no_change", False)
    max_changes_per_diff = args.get("max_changes_per_diff")
    include_reference_spec = args.get("include_reference_spec", True)
    include_flat_change_items = args.get("include_flat_change_items", True)
    sort_by = args.get("sort_by", "entity")  # entity|change_count
    time_basis_arg = args.get("time_basis")  # observation|effective_update

    # Lifecycle inference controls.
    #
    # Raw OTEL k8sobjectsreceiver output is not a true lifecycle stream; default to "none" there.
    lifecycle_inference_arg = args.get("lifecycle_inference")  # none|window
    lifecycle_scope_arg = args.get("lifecycle_scope")  # global|per_kind
    removal_grace_period_sec_arg = args.get("removal_grace_period_sec")
    removal_min_cycles_arg = args.get("removal_min_cycles")

    start_time = _parse_time(start_time_str) if start_time_str else None
    end_time = _parse_time(end_time_str) if end_time_str else None

    if not Path(k8s_objects_file).exists():
        return _json_error(f"K8s objects file not found: {k8s_objects_file}")

    try:
        df = pd.read_csv(k8s_objects_file, sep="\t")
    except Exception as e:
        return _json_error(f"Error reading k8s objects file: {e}")

    # -------------------------------------------------------------------------
    # Detect input format and normalize columns
    # -------------------------------------------------------------------------
    # 1) Processed format (expected): timestamp, object_kind, object_name, body
    # 2) Raw OTEL format (ITBenchSnapshots): Timestamp/TimestampTime, Body, ...
    #    For raw format, extract kind/name from JSON in Body column.
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

        def _extract_k8s_metadata(raw: Any) -> tuple[str, str, str, Any, str, str]:
            """Extract kind/namespace/name and K8s metadata from a JSON Body string.

            Returns: (kind, namespace, name, creationTimestamp, resourceVersion, deletionTimestamp)

            Using K8s metadata for reliable lifecycle detection:
            - creationTimestamp: when the object was created (reliable for additions)
            - resourceVersion: changes when object is modified (reliable for modifications)
            - deletionTimestamp: set when object is being deleted (reliable for deletions)
            """
            obj = _parse_k8s_body_json(raw)
            if not isinstance(obj, dict):
                return ("", "", "", None, "", "")
            kind = obj.get("kind", "") or ""
            meta = obj.get("metadata") or {}
            name = meta.get("name", "") or ""
            namespace = meta.get("namespace", "") or ""
            # Extract K8s metadata for lifecycle detection
            creation_ts = _parse_k8s_timestamp(meta.get("creationTimestamp"))
            resource_version = str(meta.get("resourceVersion", "") or "")
            deletion_ts = meta.get("deletionTimestamp") or ""
            return (kind, namespace, name, creation_ts, resource_version, deletion_ts)

        extracted = df[body_col].apply(lambda x: pd.Series(_extract_k8s_metadata(x)))
        extracted.columns = [
            "object_kind",
            "object_namespace",
            "object_name",
            "k8s_creation_ts",
            "k8s_resource_version",
            "k8s_deletion_ts",
        ]
        df["object_kind"] = extracted["object_kind"]
        df["object_namespace"] = extracted["object_namespace"]
        df["object_name"] = extracted["object_name"]
        df["k8s_creation_ts"] = extracted["k8s_creation_ts"]
        df["k8s_resource_version"] = extracted["k8s_resource_version"]
        df["k8s_deletion_ts"] = extracted["k8s_deletion_ts"]
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

    # Normalize columns
    df["object_kind"] = df["object_kind"].fillna("").astype(str)
    # Handle namespace column - could be 'object_namespace' or 'namespace'
    if "object_namespace" not in df.columns:
        if "namespace" in df.columns:
            df["object_namespace"] = df["namespace"]
        else:
            df["object_namespace"] = ""
    df["object_namespace"] = df["object_namespace"].fillna("").astype(str)
    df["object_name"] = df["object_name"].fillna("").astype(str)
    # Use namespace/kind/name for namespaced resources; kind/name for cluster-scoped.
    df["entity_id"] = df["object_kind"] + "/" + df["object_name"]
    _ns_mask = df["object_namespace"].astype(str) != ""
    df.loc[_ns_mask, "entity_id"] = (
        df.loc[_ns_mask, "object_namespace"]
        + "/"
        + df.loc[_ns_mask, "object_kind"]
        + "/"
        + df.loc[_ns_mask, "object_name"]
    )

    # Ensure K8s metadata columns exist for both formats.
    # For raw OTEL, these are extracted above. For processed format, extract now.
    if "k8s_creation_ts" not in df.columns:

        def _extract_k8s_meta_from_body(raw: Any) -> tuple[Any, str, str]:
            """Extract K8s metadata (creationTimestamp, resourceVersion, deletionTimestamp) from body."""
            obj = _parse_k8s_body_json(raw)
            if not isinstance(obj, dict):
                return (None, "", "")
            meta = obj.get("metadata") or {}
            creation_ts = _parse_k8s_timestamp(meta.get("creationTimestamp"))
            resource_version = str(meta.get("resourceVersion", "") or "")
            deletion_ts = meta.get("deletionTimestamp") or ""
            return (creation_ts, resource_version, deletion_ts)

        meta_extracted = df["body"].apply(lambda x: pd.Series(_extract_k8s_meta_from_body(x)))
        meta_extracted.columns = ["k8s_creation_ts", "k8s_resource_version", "k8s_deletion_ts"]
        df["k8s_creation_ts"] = meta_extracted["k8s_creation_ts"]
        df["k8s_resource_version"] = meta_extracted["k8s_resource_version"]
        df["k8s_deletion_ts"] = meta_extracted["k8s_deletion_ts"]

    # Filter by specific object if provided
    # Supports formats: namespace/kind/name (preferred), kind/name, or name
    if k8_object_name:
        parsed_id = _parse_k8_object_identifier(k8_object_name)

        if parsed_id["format"] == "invalid":
            return _json_error(parsed_id.get("warning", "Invalid identifier"))

        mask = _build_k8_object_filter_mask(
            df,
            parsed_id,
            kind_col="object_kind",
            namespace_col="object_namespace",
            name_col="object_name",
            entity_id_col="entity_id",
        )
        df = df[mask]

        if df.empty:
            sample_entities = df["entity_id"].unique().tolist()[:10] if not df.empty else []
            return _json_error(
                f"No objects matching '{k8_object_name}' found. "
                f"Try using 'namespace/kind/name' format for precision."
            )

    # Parse timestamp (only for processed format; raw format already normalized above)
    if not is_raw_otel:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)

    # Filter by time range
    #
    # NOTE: If time_basis == "effective_update", we intentionally do NOT filter
    # the raw dataframe by observation time, because the updated object may be
    # observed later than its effective update time (managedFields/restartedAt).
    if time_basis_arg != "effective_update":
        if start_time:
            df = df[df["timestamp"] >= _to_utc_timestamp(start_time)]
        if end_time:
            df = df[df["timestamp"] <= _to_utc_timestamp(end_time)]

    if df.empty:
        return _json_error("No data after applying time filters")

    # Sort by entity and timestamp
    df = df.sort_values(["entity_id", "timestamp"])

    # Resolve time basis defaults now that we know the input format.
    # - raw OTEL: default to effective_update for "did this change happen in window?" semantics
    # - processed: keep existing behavior unless overridden
    time_basis = time_basis_arg
    if time_basis is None:
        time_basis = "effective_update" if is_raw_otel else "observation"
    if time_basis not in {"observation", "effective_update"}:
        return _json_error(f"Unsupported time_basis: {time_basis}. Expected 'observation' or 'effective_update'")

    # Resolve lifecycle inference defaults now that we know the input format.
    #
    # Lifecycle inference modes:
    # - "none": No lifecycle detection (only spec diffs between observations)
    # - "window": Infer additions/removals from observation timing (noisy for OTEL data)
    # - "k8s_metadata": Use K8s metadata for reliable lifecycle detection (RECOMMENDED):
    #   * Additions: creationTimestamp falls within investigation window (start_time, end_time)
    #   * Deletions: deletionTimestamp is set on the object
    #   * Modifications: resourceVersion changed between observations
    lifecycle_inference = lifecycle_inference_arg
    lifecycle_scope = lifecycle_scope_arg
    if lifecycle_inference is None:
        # Default to k8s_metadata for raw OTEL (reliable), window for processed format (historical behavior)
        lifecycle_inference = "k8s_metadata" if is_raw_otel else "window"
    if lifecycle_inference not in {"none", "window", "k8s_metadata"}:
        return _json_error(
            f"Unsupported lifecycle_inference: {lifecycle_inference}. Expected 'none', 'window', or 'k8s_metadata'"
        )
    if lifecycle_scope is None:
        lifecycle_scope = "per_kind" if is_raw_otel else "global"

    # Hysteresis defaults (only used for "window" mode):
    # - Processed format keeps historical behavior (no grace/cycle gating by default).
    # - Raw OTEL with "window" mode: require a gap and multiple subsequent cycles.
    if removal_grace_period_sec_arg is None:
        removal_grace_period_sec = 300 if (is_raw_otel and lifecycle_inference == "window") else 0
    else:
        removal_grace_period_sec = int(removal_grace_period_sec_arg)
    if removal_min_cycles_arg is None:
        removal_min_cycles = 2 if (is_raw_otel and lifecycle_inference == "window") else 0
    else:
        removal_min_cycles = int(removal_min_cycles_arg)

    # Global bounds within the filtered dataset. Used for lifecycle inference.
    #
    # IMPORTANT: lifecycle inference is about *observation presence within this window*.
    # - "added" means: first observed after the window start (as approximated by global_min_ts)
    # - "removed" means: last observed before the window end (as approximated by global_max_ts)
    # This is NOT a claim of permanent creation/deletion in the cluster; it's "not observed before/after"
    # given the data sampling in the TSV for this window.
    global_min_ts = df["timestamp"].min()
    global_max_ts = df["timestamp"].max()

    # Unique observation timestamps to approximate "collection cycles".
    all_unique_ts = sorted(df["timestamp"].dropna().unique())

    kind_min_ts: dict[str, Any] = {}
    kind_max_ts: dict[str, Any] = {}
    kind_unique_ts: dict[str, list[Any]] = {}
    if lifecycle_inference != "none" and lifecycle_scope == "per_kind":
        try:
            kind_min_ts = df.groupby("object_kind")["timestamp"].min().to_dict()
            kind_max_ts = df.groupby("object_kind")["timestamp"].max().to_dict()
            kind_unique_ts = {str(k): sorted(v.dropna().unique()) for k, v in df.groupby("object_kind")["timestamp"]}
        except Exception:
            # If anything goes wrong, fall back to global bounds.
            kind_min_ts = {}
            kind_max_ts = {}
            kind_unique_ts = {}

    # Process each entity
    results = []
    entities = df["entity_id"].unique()
    total_entities_observed = len(entities)

    def _apply_change_limit(diff: list[dict]) -> tuple[list[dict], bool, int]:
        """Optionally truncate a diff to max_changes_per_diff items."""
        total_items = len(diff)
        if isinstance(max_changes_per_diff, int) and max_changes_per_diff > 0 and total_items > max_changes_per_diff:
            return (diff[:max_changes_per_diff], True, total_items)
        return (diff, False, total_items)

    for entity_id in entities:
        entity_df = df[df["entity_id"] == entity_id].copy()

        if len(entity_df) == 0:
            continue

        first_ts = entity_df["timestamp"].min()
        last_ts = entity_df["timestamp"].max()
        observation_count = len(entity_df)

        # Determine lifecycle inference bounds.
        entity_kind = str(entity_df["object_kind"].iloc[0]) if "object_kind" in entity_df.columns else ""
        scope_min_ts = kind_min_ts.get(entity_kind, global_min_ts) if lifecycle_scope == "per_kind" else global_min_ts
        scope_max_ts = kind_max_ts.get(entity_kind, global_max_ts) if lifecycle_scope == "per_kind" else global_max_ts
        scope_ts_list = (
            kind_unique_ts.get(entity_kind, all_unique_ts) if lifecycle_scope == "per_kind" else all_unique_ts
        )

        # Extract K8s metadata from the entity's observations
        k8s_creation_ts = (
            entity_df["k8s_creation_ts"].dropna().iloc[0]
            if "k8s_creation_ts" in entity_df.columns and not entity_df["k8s_creation_ts"].dropna().empty
            else None
        )
        k8s_deletion_ts_vals = (
            entity_df["k8s_deletion_ts"].dropna().unique() if "k8s_deletion_ts" in entity_df.columns else []
        )
        k8s_deletion_ts_set = any(v and str(v).strip() for v in k8s_deletion_ts_vals)
        k8s_resource_versions = (
            entity_df["k8s_resource_version"].dropna().unique().tolist()
            if "k8s_resource_version" in entity_df.columns
            else []
        )
        k8s_rv_changed = len(set(str(rv) for rv in k8s_resource_versions if rv)) > 1

        inferred_added = False
        inferred_removed = False
        metadata_added = False
        metadata_removed = False
        metadata_modified = False
        creation_ts_str: str | None = None
        deletion_ts_str: str | None = None

        if lifecycle_inference == "k8s_metadata":
            # K8s metadata-based lifecycle detection (reliable, not affected by OTEL timing noise)
            # Addition: creationTimestamp falls within investigation window
            if k8s_creation_ts is not None and pd.notna(k8s_creation_ts):
                creation_ts_str = _format_k8s_timestamp(k8s_creation_ts)
                if start_time is not None and end_time is not None:
                    start_ts = _to_utc_timestamp(start_time)
                    end_ts = _to_utc_timestamp(end_time)
                    metadata_added = start_ts <= k8s_creation_ts <= end_ts
                elif start_time is not None:
                    start_ts = _to_utc_timestamp(start_time)
                    metadata_added = k8s_creation_ts >= start_ts
                elif end_time is not None:
                    end_ts = _to_utc_timestamp(end_time)
                    metadata_added = k8s_creation_ts <= end_ts

            # Deletion: deletionTimestamp is set
            if k8s_deletion_ts_set:
                metadata_removed = True
                # Get the actual deletion timestamp value for evidence
                for v in k8s_deletion_ts_vals:
                    if v and str(v).strip():
                        deletion_ts_str = str(v).strip()
                        break

            # Modification: resourceVersion changed between observations
            metadata_modified = k8s_rv_changed

        elif lifecycle_inference == "window":
            # Observation-based lifecycle inference (legacy, can be noisy for OTEL data)
            inferred_added = pd.notna(first_ts) and pd.notna(scope_min_ts) and first_ts > scope_min_ts

            if pd.notna(last_ts) and pd.notna(scope_max_ts) and last_ts < scope_max_ts:
                gap_sec = float((scope_max_ts - last_ts).total_seconds())
                post_cycles = sum(1 for t in scope_ts_list if t > last_ts)
                inferred_removed = gap_sec >= float(removal_grace_period_sec) and post_cycles >= int(removal_min_cycles)

        # Parse and clean specs
        specs = []
        for idx, row in entity_df.iterrows():
            try:
                body_obj = _parse_k8s_body_json(row.get("body"))
                if not body_obj:
                    continue

                meta = body_obj.get("metadata") or {}
                cleaned = _clean_spec_for_diff(body_obj)
                cleaned = _normalize_for_diff(cleaned)
                effective_ts = _effective_update_timestamp(body_obj)
                specs.append(
                    {
                        # Observation timestamp: when this object snapshot was recorded.
                        "timestamp": row["timestamp"],
                        # Effective update timestamp: best-effort "when the object was updated".
                        "effective_timestamp": effective_ts,
                        "spec": cleaned,
                        "meta": {
                            "namespace": meta.get("namespace") or "",
                            "uid": meta.get("uid") or "",
                            "deletionTimestamp": meta.get("deletionTimestamp"),
                            "ownerReferences": meta.get("ownerReferences") or [],
                        },
                    }
                )
            except (json.JSONDecodeError, TypeError):
                continue

        # Always keep deterministic time ordering for lifecycle + diff windows.
        specs.sort(key=lambda s: s["timestamp"])

        last_meta = (specs[-1].get("meta") if specs else {}) or {}
        deletion_ts = last_meta.get("deletionTimestamp")
        deletion_confirmed = deletion_ts is not None and deletion_ts != ""

        # Lifecycle changes: additions, deletions, and resourceVersion modifications.
        # This allows surfacing objects that were created/deleted/modified during the window,
        # even if we only captured one snapshot or there was no spec diff.
        lifecycle_changes: list[dict[str, Any]] = []

        # Handle additions
        if metadata_added and creation_ts_str:
            # K8s metadata-based: creationTimestamp is within investigation window
            lifecycle_changes.append(
                {
                    "timestamp": creation_ts_str,
                    "from_timestamp": None,
                    "changes_truncated": False,
                    "change_item_count": 1,
                    "change_item_total": 1,
                    "changes": [
                        {
                            "path": "entity",
                            "type": "entity_added",
                            "new": entity_id,
                            "inferred": False,
                            "source": "k8s_metadata",
                            "evidence": {
                                "creationTimestamp": creation_ts_str,
                                "investigation_start": _format_k8s_timestamp(start_time) if start_time else None,
                                "investigation_end": _format_k8s_timestamp(end_time) if end_time else None,
                            },
                        }
                    ],
                }
            )
        elif inferred_added and pd.notna(first_ts):
            # Observation-based (window mode): first observed after window start
            lifecycle_changes.append(
                {
                    "timestamp": str(first_ts),
                    "from_timestamp": None,
                    "changes_truncated": False,
                    "change_item_count": 1,
                    "change_item_total": 1,
                    "changes": [
                        {
                            "path": "entity",
                            "type": "entity_added",
                            "new": entity_id,
                            "inferred": True,
                            "source": "observation_timing",
                            "evidence": {
                                "first_seen": str(first_ts),
                                "window_first_seen": str(global_min_ts),
                                "window_last_seen": str(global_max_ts),
                            },
                        }
                    ],
                }
            )

        # Handle deletions
        if metadata_removed and deletion_ts_str:
            # K8s metadata-based: deletionTimestamp is set
            lifecycle_changes.append(
                {
                    "timestamp": deletion_ts_str,
                    "from_timestamp": None,
                    "changes_truncated": False,
                    "change_item_count": 1,
                    "change_item_total": 1,
                    "changes": [
                        {
                            "path": "entity",
                            "type": "entity_removed",
                            "old": entity_id,
                            "inferred": False,
                            "confirmed": True,
                            "source": "k8s_metadata",
                            "reason": "deletionTimestamp",
                            "evidence": {
                                "deletionTimestamp": deletion_ts_str,
                            },
                        }
                    ],
                }
            )
        elif (inferred_removed or deletion_confirmed) and pd.notna(last_ts):
            # Observation-based or legacy deletion detection
            lifecycle_changes.append(
                {
                    "timestamp": str(last_ts),
                    "from_timestamp": None,
                    "changes_truncated": False,
                    "change_item_count": 1,
                    "change_item_total": 1,
                    "changes": [
                        {
                            "path": "entity",
                            "type": "entity_removed",
                            "old": entity_id,
                            "inferred": not deletion_confirmed,
                            "confirmed": bool(deletion_confirmed),
                            "source": "observation_timing" if inferred_removed else "k8s_metadata",
                            "reason": "deletionTimestamp" if deletion_confirmed else "not_observed",
                            "evidence": {
                                "last_seen": str(last_ts),
                                "window_first_seen": str(scope_min_ts),
                                "window_last_seen": str(scope_max_ts),
                                "deletionTimestamp": deletion_ts,
                            },
                        }
                    ],
                }
            )

        # Handle resourceVersion modifications (k8s_metadata mode only)
        if metadata_modified and lifecycle_inference == "k8s_metadata":
            # resourceVersion changed between observations - this is a real modification
            lifecycle_changes.append(
                {
                    "timestamp": _format_k8s_timestamp(last_ts) if pd.notna(last_ts) else str(last_ts),
                    "from_timestamp": _format_k8s_timestamp(first_ts) if pd.notna(first_ts) else str(first_ts),
                    "changes_truncated": False,
                    "change_item_count": 1,
                    "change_item_total": 1,
                    "changes": [
                        {
                            "path": "metadata.resourceVersion",
                            "type": "entity_modified",
                            "old": str(k8s_resource_versions[0]) if k8s_resource_versions else None,
                            "new": str(k8s_resource_versions[-1]) if k8s_resource_versions else None,
                            "inferred": False,
                            "source": "k8s_metadata",
                            "evidence": {
                                "resourceVersions": [str(rv) for rv in k8s_resource_versions],
                                "observation_count": observation_count,
                            },
                        }
                    ],
                }
            )

        if len(specs) < 2:
            # Still surface entities that had lifecycle changes within the window.
            if include_no_change or lifecycle_changes:
                parts = entity_id.split("/")
                kind = parts[0] if parts else "Unknown"
                namespace = parts[1] if len(parts) == 3 else ""
                name = parts[-1] if parts else entity_id
                results.append(
                    {
                        "entity": entity_id,
                        "kind": kind,
                        "namespace": namespace,
                        "name": name,
                        "first_timestamp": str(first_ts),
                        "last_timestamp": str(last_ts),
                        "observation_count": observation_count,
                        "change_count": len(lifecycle_changes),
                        "duration_sec": (
                            (last_ts - first_ts).total_seconds() if pd.notna(first_ts) and pd.notna(last_ts) else 0
                        ),
                        "changes": lifecycle_changes,
                        "lifecycle": {
                            "inference_mode": lifecycle_inference,
                            "inferred_added": inferred_added,
                            "inferred_removed": inferred_removed,
                            "metadata_added": metadata_added,
                            "metadata_removed": metadata_removed,
                            "metadata_modified": metadata_modified,
                            "creationTimestamp": creation_ts_str,
                            "resourceVersions": (
                                [str(rv) for rv in k8s_resource_versions] if k8s_resource_versions else []
                            ),
                        },
                        "reference_spec": (
                            {
                                "timestamp": str(specs[0]["timestamp"]),
                                "spec": specs[0]["spec"],
                            }
                            if include_reference_spec and specs
                            else None
                        ),
                    }
                )
            continue

        # Compute diffs between consecutive specs
        all_changes = []
        change_items: list[dict[str, Any]] = []

        # Start with lifecycle changes (if any), then append actual diffs.
        all_changes.extend(lifecycle_changes)
        for i in range(1, len(specs)):
            prev_spec = specs[i - 1]["spec"]
            curr_spec = specs[i]["spec"]

            if prev_spec == curr_spec:
                continue

            diff = _compute_diff(prev_spec, curr_spec)
            if diff:
                event_ts = specs[i].get("timestamp")
                from_event_ts = specs[i - 1].get("timestamp")
                if time_basis == "effective_update":
                    event_ts = specs[i].get("effective_timestamp") or event_ts
                    from_event_ts = specs[i - 1].get("effective_timestamp") or from_event_ts

                limited, truncated, total_items = _apply_change_limit(diff)
                all_changes.append(
                    {
                        "timestamp": str(event_ts),
                        "from_timestamp": str(from_event_ts),
                        "changes": limited,
                        "changes_truncated": truncated,
                        "change_item_count": len(limited),
                        "change_item_total": total_items,
                    }
                )
                if include_flat_change_items:
                    for item in limited:
                        change_items.append(
                            {
                                "timestamp": str(event_ts),
                                "from_timestamp": str(from_event_ts),
                                **item,
                            }
                        )

        # If we're using effective_update time basis, filter *change events* by the window,
        # rather than filtering observations. This captures changes whose effects were observed
        # later than their update timestamp.
        if time_basis == "effective_update" and (start_time or end_time):
            start_ts = _to_utc_timestamp(start_time) if start_time else None
            end_ts = _to_utc_timestamp(end_time) if end_time else None

            def _in_window(ts_any: Any) -> bool:
                ts = pd.to_datetime(ts_any, errors="coerce", utc=True)
                if pd.isna(ts):
                    return False
                if start_ts is not None and ts < start_ts:
                    return False
                if end_ts is not None and ts > end_ts:
                    return False
                return True

            all_changes = [w for w in all_changes if _in_window(w.get("timestamp"))]
            if include_flat_change_items:
                change_items = [it for it in change_items if _in_window(it.get("timestamp"))]

        if all_changes or include_no_change:
            parts = entity_id.split("/")
            kind = parts[0] if parts else "Unknown"
            namespace = parts[1] if len(parts) == 3 else ""
            name = parts[-1] if parts else entity_id

            # Compute total duration of observation
            duration_sec = (last_ts - first_ts).total_seconds() if pd.notna(first_ts) and pd.notna(last_ts) else 0

            entity_out: dict[str, Any] = {
                "entity": entity_id,
                "kind": kind,
                "namespace": namespace,
                "name": name,
                "time_basis": time_basis,
                "first_timestamp": str(first_ts),
                "last_timestamp": str(last_ts),
                "observation_count": observation_count,
                "duration_sec": duration_sec,
                "change_count": len(all_changes),
                "changes": all_changes,
            }
            if include_reference_spec and specs:
                entity_out["reference_spec"] = {
                    "timestamp": str(specs[0]["timestamp"]),
                    "spec": specs[0]["spec"],
                }
            if include_flat_change_items:
                entity_out["change_items"] = change_items
                entity_out["change_item_count"] = len(change_items)
            entity_out["lifecycle"] = {
                "inference_mode": lifecycle_inference,
                "inferred_added": inferred_added,
                "inferred_removed": inferred_removed,
                "metadata_added": metadata_added,
                "metadata_removed": metadata_removed,
                "metadata_modified": metadata_modified,
                "creationTimestamp": creation_ts_str,
                "resourceVersions": [str(rv) for rv in k8s_resource_versions] if k8s_resource_versions else [],
            }
            results.append(entity_out)

    # Sort deterministically to ensure pagination is stable across calls.
    #
    # Primary goal: avoid duplicate entities across pages due to non-deterministic ordering.
    # Default: entity lexicographic (Kind/name).
    if sort_by == "change_count":
        results.sort(key=lambda x: (-int(x.get("change_count", 0) or 0), str(x.get("entity", "")).lower()))
    else:
        results.sort(key=lambda x: str(x.get("entity", "")).lower())

    def _sum_change_events(entities_list: list[dict[str, Any]]) -> int:
        return sum(int(e.get("change_count", 0) or 0) for e in entities_list)

    def _sum_change_item_totals(entities_list: list[dict[str, Any]]) -> int:
        total = 0
        for entity in entities_list:
            for window in entity.get("changes", []) or []:
                if isinstance(window, dict):
                    # Prefer the explicit total if present; else fall back to count/len.
                    total += int(
                        window.get("change_item_total")
                        or window.get("change_item_count")
                        or len(window.get("changes", []) or [])
                    )
        return total

    total_change_events = _sum_change_events(results)
    total_change_item_total = _sum_change_item_totals(results)

    # Apply pagination
    total_count = len(results)
    if offset:
        results = results[offset:]
    if limit:
        results = results[:limit]

    returned_change_events = _sum_change_events(results)
    returned_change_item_total = _sum_change_item_totals(results)

    # Build an entity-keyed map (ordered by insertion in Python 3.7+).
    # NOTE: JSON object order is not guaranteed by spec, but most consumers preserve it;
    # we still include stable sort + offset/limit to make paging reliable.
    entities_map: dict[str, Any] = {}
    entity_order: list[str] = []
    for entity in results:
        entity_id = str(entity.get("entity", ""))
        if not entity_id:
            continue
        entity_order.append(entity_id)
        changes_detected: dict[str, Any] = {}
        for idx, window in enumerate(entity.get("changes", []) or []):
            if not isinstance(window, dict):
                continue
            ts = str(window.get("timestamp", ""))
            from_ts = str(window.get("from_timestamp", ""))
            # Ensure key uniqueness even if timestamps collide.
            key = f"{ts} (from {from_ts})#{idx}"
            changes_detected[key] = {
                "timestamp": ts,
                "from_timestamp": from_ts,
                "changes_truncated": bool(window.get("changes_truncated", False)),
                "change_item_count": int(window.get("change_item_count", 0) or 0),
                "change_item_total": int(
                    window.get("change_item_total")
                    or window.get("change_item_count")
                    or len(window.get("changes", []) or [])
                ),
                "changes": window.get("changes", []),
            }

        entities_map[entity_id] = {
            "kind": entity.get("kind"),
            "name": entity.get("name"),
            "first_timestamp": entity.get("first_timestamp"),
            "last_timestamp": entity.get("last_timestamp"),
            "observation_count": entity.get("observation_count"),
            "duration_sec": entity.get("duration_sec"),
            "change_event_count": entity.get("change_count"),
            "reference_spec": entity.get("reference_spec"),
            "lifecycle": entity.get("lifecycle"),
            "changes_detected": changes_detected,
        }

    # Build output
    output = {
        "reference_spec_file": k8s_objects_file,
        "input_format": "raw_otel" if is_raw_otel else "processed",
        "sort_by": sort_by,
        "total_entities_observed": total_entities_observed,
        # Explicit names (requested): total entities with changes + returned entities in this page.
        "num_entities_with_changes": total_count,
        "entities_with_changes_returned": len(results),
        # Explicit stable ordering for page entities (do not rely on JSON object key ordering).
        "entity_order": entity_order,
        "total_change_events": total_change_events,
        "returned_change_events": returned_change_events,
        "total_change_item_total": total_change_item_total,
        "returned_change_item_total": returned_change_item_total,
        # Back-compat keys used by codex-eog pagination logic.
        "total_entities": total_count,
        "returned_count": len(results),
        "offset": offset,
        "limit": limit,
        # Back-compat: array of entity objects (page).
        "entities_with_changes": results,
        # New: entity-keyed map for consumers that prefer dict lookups.
        "entities": entities_map,
    }

    return [TextContent(type="text", text=json.dumps(output, indent=2))]


# =============================================================================
# Get K8s Spec - Retrieve K8s resource spec
# =============================================================================
