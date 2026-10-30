# Offline OpenAPI impact demo

This repeatable demo exercises AIR's primary evidence path without a database,
network, credential, external account, model download, or production system. It
compares two local OpenAPI JSON contracts, matches consequential changes against
an explicit dependency registry, follows declared downstream workflow edges,
and emits deterministic change, impact, projection, and redacted visualization
evidence.

Run the checked-in example with Python 3.12:

```sh
python -m air.demo \
  --previous examples/offline-impact/previous-openapi.json \
  --current examples/offline-impact/current-openapi.json \
  --registry examples/offline-impact/registry.json \
  --output /tmp/air-offline-impact-report.json
```

Run it again and compare the report bytes or `report_hash`; identical inputs
produce identical output. The example demonstrates a breaking response type
change and required query parameter, direct declared consumers, downstream
workflow review, stable evidence hashes, explicit coverage limits, and an
actionless redacted visualization.

The registry file has exactly two top-level arrays: `dependencies` contains the
existing `Dependency` fields, and `workflow_edges` contains `upstream` and
`downstream` copies of those dependencies plus the supported
`consumes_output` relation. Inputs are local JSON files capped at 512,000 bytes
each. Duplicate keys, non-finite numbers, malformed shapes, unsupported OpenAPI
versions, invalid dependencies, unregistered workflow endpoints, and evidence
bounds fail closed with fixed error codes.

This is an offline review aid over caller-declared dependencies. It does not
discover undeclared dependencies, establish compatibility or safety, observe
production, use cookies or credentials, access the network, propose or execute
repairs, approve changes, deploy, or perform external actions. No recorded
impact is explicitly not evidence that a dependency is safe.

## Reuse-first competitor assessment

Assessment performed 2026-10-30 against public primary documentation:

- [Optic](https://github.com/opticdev/optic/wiki/Diff-and-Lint-OpenAPI)
  compares OpenAPI files or Git revisions and detects breaking changes. Its
  repository is archived, and its documented output does not provide AIR's
  explicit declared-integration and downstream workflow evidence chain.
- [Bump.sh](https://docs.bump.sh/help/continuous-integration/cli/) provides
  human-readable OpenAPI diffs and CI breaking-change gates, with broader hosted
  documentation and changelog features. AIR does not reproduce those surfaces;
  this demo stays local and connects changes to caller-declared dependency impact.
- [Schemathesis](https://schemathesis.readthedocs.io/en/stable/quick-start/)
  generates and sends requests to exercise an API. That is complementary but
  outside this demo's authorization: AIR performs no API execution or network I/O.

The bounded competitive gap demonstrated here is not another OpenAPI diff. It is
the deterministic binding from a classified contract change to explicit direct
consumers, declared downstream workflow review, stable evidence hashes, coverage
limits, and an actionless redacted visualization. Existing AIR contracts already
implemented every stage, so the slice adds only orchestration, fixtures, and a
CLI. No third-party source, algorithm, model, dependency, translation, download,
external account, or license obligation was adopted.
