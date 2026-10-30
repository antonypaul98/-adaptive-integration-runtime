"""Offline, deterministic end-to-end demonstration of AIR change impact.

The demo deliberately accepts local JSON values only.  It performs no network
access, persistence, repair, approval, deployment, or external action.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Iterable

from air.change_intelligence import compare_openapi
from air.dependency_impact import (
    Dependency,
    ImpactError,
    WorkflowEdge,
    analyze_changes,
)
from air.dependency_projection import project_dependency_graph
from air.dependency_visualization import visualize_dependency_projection
from air.postgres import MAX_PAYLOAD_BYTES, canonical_json

DEMO_VERSION = "air-offline-impact-demo-v1"
MAX_INPUT_BYTES = 512_000


class DemoError(ValueError):
    """Fixed codes only; never include input content or local paths."""


def _reject_constant(_: str) -> None:
    raise DemoError("invalid_json")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DemoError("duplicate_json_key")
        result[key] = value
    return result


def _load_json(path: Path) -> Any:
    try:
        with path.open("rb") as source:
            raw = source.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise DemoError("input_size_limit")
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_reject_constant,
        )
    except DemoError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise DemoError("invalid_json") from None


def _registry(value: Any) -> tuple[list[Dependency], list[WorkflowEdge]]:
    if not isinstance(value, dict) or set(value) != {"dependencies", "workflow_edges"}:
        raise DemoError("invalid_registry_shape")
    if not isinstance(value["dependencies"], list) or not isinstance(value["workflow_edges"], list):
        raise DemoError("invalid_registry_shape")
    dependency_keys = {
        "integration_id", "mapping_id", "location", "operation", "integration_kind"
    }
    if any(not isinstance(item, dict) or set(item) != dependency_keys
           for item in value["dependencies"]):
        raise DemoError("invalid_registry_shape")
    if any(not isinstance(item, dict)
           or set(item) != {"upstream", "downstream", "relation"}
           or not isinstance(item["upstream"], dict)
           or set(item["upstream"]) != dependency_keys
           or not isinstance(item["downstream"], dict)
           or set(item["downstream"]) != dependency_keys
           for item in value["workflow_edges"]):
        raise DemoError("invalid_registry_shape")
    try:
        dependencies = [Dependency(**item) for item in value["dependencies"]]
        edges = [
            WorkflowEdge(
                upstream=Dependency(**item["upstream"]),
                downstream=Dependency(**item["downstream"]),
                relation=item["relation"],
            )
            for item in value["workflow_edges"]
        ]
    except (ImpactError, KeyError, TypeError):
        raise DemoError("invalid_registry") from None
    return dependencies, edges


def run_offline_impact_demo(
    previous: dict[str, Any],
    current: dict[str, Any],
    registry: dict[str, Any],
) -> dict[str, Any]:
    """Run AIR's existing pure evidence pipeline over caller-supplied values."""
    if not isinstance(previous, dict) or not isinstance(current, dict):
        raise DemoError("invalid_contract_shape")
    dependencies, edges = _registry(registry)
    changes = compare_openapi(previous, current)
    impacts = analyze_changes(changes, dependencies, workflow_edges=edges)
    projection = project_dependency_graph(
        dependencies, workflow_edges=edges, impact_report=impacts
    )
    visualization = visualize_dependency_projection(projection)
    change_payload = changes.to_dict()
    impact_payload = impacts.to_dict()
    projection_payload = projection.to_dict()
    visualization_payload = visualization.to_dict()
    report = {
        "demo_version": DEMO_VERSION,
        "inputs": {
            "previous_semantic_hash": changes.previous_semantic_hash,
            "current_semantic_hash": changes.new_semantic_hash,
            "registry_hash": impact_payload["dependencies_hash"],
            "workflow_edges_hash": projection_payload["workflow_edges_hash"],
        },
        "change_evidence": {
            "content_hash": changes.content_hash,
            "review_required": changes.review_required,
            "change_count": len(changes.changes),
            "payload": change_payload,
        },
        "impact_evidence": {
            "content_hash": impacts.content_hash,
            "direct_impact_count": len(impact_payload["impacts"]),
            "transitive_impact_count": len(impact_payload.get("downstream_impacts", [])),
            "payload": impact_payload,
        },
        "projection_evidence": {
            "content_hash": projection.content_hash,
            "payload": projection_payload,
        },
        "redacted_visualization": {
            "content_hash": visualization.content_hash,
            "payload": visualization_payload,
        },
        "coverage": {
            "scope": "explicit_registry_and_local_openapi_only",
            "dependency_discovery_performed": False,
            "no_recorded_impact_is_not_safe": True,
            "production_observation_performed": False,
        },
        "authority": {
            "read_only": True,
            "network_access": False,
            "external_actions": False,
            "repair_authority": False,
            "approval_authority": False,
            "deployment_authority": False,
        },
    }
    encoded = canonical_json(report)
    return {"report_hash": sha256(encoded.encode("utf-8")).hexdigest(), **report}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m air.demo",
        description="Run AIR's deterministic offline OpenAPI impact demo.",
    )
    parser.add_argument("--previous", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = run_offline_impact_demo(
            _load_json(args.previous),
            _load_json(args.current),
            _load_json(args.registry),
        )
        output = canonical_json(report) + "\n"
        if len(output.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise DemoError("output_size_limit")
        if args.output is None:
            sys.stdout.write(output)
        else:
            args.output.write_text(output, encoding="utf-8")
        return 0
    except (DemoError, ImpactError, ValueError) as exc:
        code = str(exc)
        if not code or any(character.isspace() for character in code):
            code = "demo_rejected"
        sys.stderr.write(f"AIR_DEMO_ERROR:{code}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
