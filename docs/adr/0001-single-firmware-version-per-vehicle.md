# Store a single firmware version per vehicle

The store originally held many firmware versions per vehicle so that
`diff_parameter` could answer "what changed when I upgrade?". Supporting all six
ArduPilot vehicles rotated the interesting axis: we now store exactly one
firmware version per Vehicle — whichever the Vehicle Roster's URL points at —
and `diff_parameter` compares one Parameter **across two Vehicles** instead of
across two versions.

## Considered Options

- **Keep the version axis and add the vehicle axis.** Rejected: 6 vehicles x N
  versions turns a ~5,600-row table into a storage matrix nobody asked for, and
  the semantic index only ever queried the newest version anyway
  (`ParameterCatalog.semantic_search` resolved `_latest_version(vehicle)` and
  never exposed the others).
- **Drop `diff_parameter` entirely.** Rejected: the field-by-field comparison
  does not care whether the two rows differ by version or by vehicle, so
  re-aiming it cost a signature change rather than a rewrite — and "how does
  `RTL_ALT` differ between plane and copter?" is the question a six-vehicle
  install actually raises.

## Consequences

- `firmware_version` survives as a **provenance column** — always populated,
  never a query key. It is what makes an answer citable ("`Q_A_RAT_RLL_P` on
  copter 4.8.0") and it is what `version_mismatch` is computed from.
- The Vehicle Roster can pin different Vehicles to different versions, so a
  cross-vehicle diff may compare 4.7.0 against 4.8.0. The payload therefore
  carries `version_a`/`version_b` plus a `version_mismatch` flag rather than
  refusing the query — a legitimate comparison should not fail because of an
  unrelated config choice.
- ArduPilot only publishes pinned `parameters-<Vehicle>-stable-V<x.y.z>.html`
  URLs for *superseded* versions; the current stable lives at unversioned
  `parameters.html` only. Every version except the newest can be pinned, and the
  newest is what the default URL already tracks.
- The uniqueness key drops to `(vehicle, name, backend)`, and re-ingesting a
  Vehicle wipes that Vehicle's rows wholesale. Previously-stored older versions
  (plane 4.6.3) are deleted by the first re-ingest, with no migration step —
  `data/` is gitignored and fully rebuildable.
- The LanceDB table is replaced per **vehicle**, not per (vehicle, version), so
  the index cannot accumulate unreachable vectors and its filter stays a flat
  `vehicle IN (...)`.
