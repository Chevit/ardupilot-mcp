# `diff_parameter` assumes one shared firmware version

ADR 0001 gave `diff_parameter` a `version_a`/`version_b` pair and a
`version_mismatch` flag, because the Vehicle Roster could pin Vehicles to
different Firmware versions. In practice an install uses one version: every
Roster URL is the unversioned `parameters.html`, and the store holds all
Vehicles at the same release. The version fields were also confusing to LLM
clients — `differences[]` reused `version_a`/`version_b` to mean *field
values*. We dropped all three version fields from the diff payload; each
difference now reports `value_a`/`value_b`.

## Considered Options

- **Enforce one version at ingest** (reject, or warn about, a Vehicle whose
  detected version differs from the others). Rejected: ArduPilot releases
  each Vehicle separately, so the unversioned pages can legitimately diverge
  for a while, and `--all` would start failing for a reason the user can't
  fix.

## Consequences

- Nothing enforces a shared version. If versions do diverge, the diff
  no longer says so; `firmware_version` is still returned as provenance by
  `lookup_parameter`, the search tools, and `list_vehicles`
  (`ingested_version`), which is where a client can see it.
- Supersedes the `version_a`/`version_b`/`version_mismatch` consequence of
  ADR 0001. The rest of ADR 0001 (one version per Vehicle, wholesale
  re-ingest) stands.
