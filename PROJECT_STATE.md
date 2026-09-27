# AIR implementation state

Updated 2026-09-27. GitHub is the source of truth.

## Reconciled source

The accessible repository is `antonypaul98/-adaptive-integration-runtime` (leading
hyphen). The supplied non-hyphen name returned 404. At the start of this run main
was `8ccd2db0e1f6ea31b0db021abab871d7b534ca05`, containing only README.md. The newest
accessible implementation was recovery/postgres-tenant-isolation at `b80ca97`,
containing packaging and a migration-loader stub, with no migrations or tests.
No older commit history was reconstructed; the older 39-test result is not used
as acceptance evidence for this repository.

## PostgreSQL checkpoint

Implemented and validated at code revision `406cd4bf4bd4b95347807132c34fdd7adbd1e841`:

- Versioned, checksum-verified, advisory-locked transactional migrations.
- Tenant-scoped immutable artifacts and database-created atomic audit events.
- ENABLE + FORCE RLS with a protected database-login-to-tenant binding.
- Missing, malformed, disabled or forged tenant contexts fail closed.
- Runtime cannot modify bindings, bypass RLS, mutate evidence or forge timestamps.
- Database-generated SHA-256 hashes; idempotent insertion and conflict detection.
- Explicit transactions, rollback on error, short-lived closed connections,
  statement/lock/idle transaction timeouts, verify-full TLS by default.
- Per-tenant database credentials, separately provisioned; no shared login tenant switch.

Validation actually executed:

- Local Python 3.12: 23 unit tests passed; compilation and git diff check passed.
- GitHub PR #1 workflow run 36344305949 on exact head 406cd4b:
  PostgreSQL 16 and 17 jobs both passed the complete 54-test suite, with no skips.
  https://github.com/antonypaul98/-adaptive-integration-runtime/actions/runs/36344305949
- Initial CI exposed a non-immutable generated-column expression; fixed using an
  insert trigger before recording the successful result above.
- Local PostgreSQL installation was unavailable; database tests ran on actual
  PostgreSQL service containers in CI, not an in-memory substitute.

The next documentation commit and merged main must also pass the same CI gate.
No production database was changed or deployed.

## Next checkpoint

Read-only HTTPS REST/OpenAPI JSON observer with SSRF defenses, pinned DNS/TLS,
bounded responses/time, redacted snapshots, tenant-scoped persistence and tests.

## Lifecycle

observe → detect → propose → sandbox → replay → verify → approve → deploy

This repository currently implements storage and is adding observation. It does
not implement automatic deployment or claim the other lifecycle stages are
complete. Consequential external changes require human approval. No LLM receives
production payloads, credentials or customer data.

## PostgreSQL merge verification

PR #1 merged at main `6aa33a827dc2eef9c7cbac6e180b2c06c4458482`.
Merged-main workflow 36344593469 passed both PostgreSQL 16 and 17 jobs.
Documentation head `3b07f6c` also passed before merge (run 36344531788).

## Observer implementation (CI pending)

Implemented HTTPS-only, address-pinned, certificate-verified JSON/OpenAPI
observation; DNS/host/IP/redirect validation; header/body/complexity/deadline
limits; credential and provenance redaction; immutable normalized snapshots;
tenant-checked PostgreSQL persistence; deterministic source-scoped change checks.

Executed locally: 91 observer cases passed, including actual TLS socket tests for
certificate trust/hostname validation, chunked responses, truncation, size limits,
and slow header/chunk deadline interruption. Two database snapshot cases are
included for the next exact-head PostgreSQL CI run. No live customer endpoint or
production database has been contacted.

Remaining acceptance: full observer + PostgreSQL CI on the pushed revision and
merged main. Limitations and operational boundaries are explicit in README.md.
