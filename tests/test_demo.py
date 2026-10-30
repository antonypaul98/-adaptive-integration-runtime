import json

from air.demo import main, run_offline_impact_demo


def contract(value_type="integer", *, required_query=False):
    operation = {
        "responses": {
            "200": {
                "description": "OK",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {"id": {"type": value_type}},
                        }
                    }
                },
            }
        }
    }
    if required_query:
        operation["parameters"] = [
            {"name": "account", "in": "query", "required": True,
             "schema": {"type": "string"}}
        ]
    return {
        "openapi": "3.1.0",
        "info": {"title": "Demo", "version": "1"},
        "paths": {
            "/items": {"get": operation},
            "/ledger": {"get": {"responses": {"200": {"description": "OK"}}}},
        },
    }


def dependency(name, location):
    return {
        "integration_id": name,
        "mapping_id": "item-id",
        "location": location,
        "operation": "GET /items",
        "integration_kind": "adapter",
    }


def registry():
    direct = dependency(
        "private-client",
        "/paths/~1items/get/responses/200/content/application~1json/schema/properties/id",
    )
    downstream = {
        **dependency("private-worker", "/paths/~1ledger/get/responses/200"),
        "operation": "GET /ledger",
    }
    return {
        "dependencies": [direct, downstream],
        "workflow_edges": [
            {"upstream": direct, "downstream": downstream,
             "relation": "consumes_output"}
        ],
    }


def test_demo_connects_changes_to_direct_and_downstream_review():
    report = run_offline_impact_demo(
        contract(), contract("string", required_query=True), registry()
    )

    assert report["change_evidence"]["change_count"] == 2
    assert report["impact_evidence"]["direct_impact_count"] >= 1
    assert report["impact_evidence"]["transitive_impact_count"] >= 1
    summary = report["projection_evidence"]["payload"]["impact_summary"]
    assert summary["recorded_review_node_count"] == 2
    assert report["authority"]["external_actions"] is False


def test_demo_is_deterministic_across_json_round_trip_and_input_order():
    first = run_offline_impact_demo(contract(), contract("string"), registry())
    reordered = registry()
    reordered["dependencies"].reverse()
    second = run_offline_impact_demo(
        json.loads(json.dumps(contract(), sort_keys=True)),
        json.loads(json.dumps(contract("string"), sort_keys=True)),
        reordered,
    )
    assert first == second


def test_redacted_visualization_omits_dependency_metadata():
    report = run_offline_impact_demo(contract(), contract("string"), registry())
    rendered = json.dumps(report["redacted_visualization"], sort_keys=True)
    assert "private-client" not in rendered
    assert "private-worker" not in rendered
    assert "/paths/" not in rendered


def test_no_change_never_claims_safety():
    report = run_offline_impact_demo(contract(), contract(), registry())
    assert report["change_evidence"]["change_count"] == 0
    assert report["impact_evidence"]["direct_impact_count"] == 0
    assert report["coverage"]["no_recorded_impact_is_not_safe"] is True


def test_cli_emits_canonical_repeatable_report(tmp_path, capsys):
    previous = tmp_path / "previous.json"
    current = tmp_path / "current.json"
    config = tmp_path / "registry.json"
    previous.write_text(json.dumps(contract()), encoding="utf-8")
    current.write_text(json.dumps(contract("string")), encoding="utf-8")
    config.write_text(json.dumps(registry()), encoding="utf-8")

    arguments = ["--previous", str(previous), "--current", str(current),
                 "--registry", str(config)]
    assert main(arguments) == 0
    first = capsys.readouterr().out
    assert main(arguments) == 0
    second = capsys.readouterr().out
    assert first == second
    assert json.dumps(json.loads(first), sort_keys=True, separators=(",", ":")) + "\n" == first


def test_cli_rejects_duplicate_keys_without_content_or_path_in_error(tmp_path, capsys):
    bad = tmp_path / "secret-name.json"
    bad.write_text('{"openapi":"3.1.0","openapi":"3.0.0"}', encoding="utf-8")
    valid = tmp_path / "valid.json"
    config = tmp_path / "registry.json"
    valid.write_text(json.dumps(contract()), encoding="utf-8")
    config.write_text(json.dumps(registry()), encoding="utf-8")

    assert main(["--previous", str(bad), "--current", str(valid),
                 "--registry", str(config)]) == 2
    error = capsys.readouterr().err
    assert error == "AIR_DEMO_ERROR:duplicate_json_key\n"
    assert "secret-name" not in error
