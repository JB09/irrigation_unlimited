# Handoff: Cycle-and-Soak Under-Delivery Caused by Mid-Run Config Reload

**Date:** 2026-06-19
**Component:** Irrigation Unlimited (rgc99 fork `JB09/irrigation_unlimited`), branch
`claude/peaceful-franklin-XyDsS`, version at investigation `2026.6.2` → `2026.6.3`.
**Status:** Root cause identified and reproduced. Diagnostic-only `export_config` fix shipped
(PR #5, merged). The actual hardening for the reload issue is **not yet implemented** — see
"Recommended hardening" below.

---

## TL;DR

The 2026-06-19 "soak is consuming the duration budget" symptom was **not** a soak-accounting
bug. It was caused by **editing the Irrigation Unlimited (IU) config and reloading IU while the
morning run was still in progress.** A reload tears down and rebuilds the whole controller; the
in-flight cycle-and-soak run is discarded, today's schedule slot has already fired so it is not
re-created, remaining cycles are dropped, and a zone valve can be left switched on. With the
config left alone, the current code (2026.6.x) delivers **100%** of the Smart-Irrigation (SI)
pushed on-time — verified by reproduction and by the live system's own *planned* next run.

---

## Symptom (as reported)

- 6 zones, 2 sequences (Bib 1 = zones 1–3, Bib 2 = zones 4–6), cycle-and-soak, SI pushes a
  per-zone total via `adjust_time` at 04:15; "Morning" schedule fires 04:30 (mon/thu/fri).
- On 06-19 every "done" zone stopped far short of its SI allocation. Bib 2 ran ~225 min
  wall-clock (≈ the soak-exclusive sum of its on-times, 228 min), delivered only ~100 min
  (~44%), then marked all three zones "done → next Monday". Per-zone delivery was non-uniform
  (Back Right 20/106, Back Center 30/41, Back Left 50/80).

## Evidence gathered (HA-MCP, read-only)

1. **Valve history (authoritative), 06-19, Bib 2** confirmed the shortfall exactly:
   z4 = 2×10 min = 20 min; z5 = 3×10 min = 30 min; z6 = ~50 min; total 100/228 = 44%, all
   stopped by ~08:15 EDT.
2. **`adjust_time` was pushed once at 04:15:30** (six values matching the report: Front
   `3:21:27`, … Back Left `1:20:28`) and **never again during the run** → mid-run SI re-push is
   NOT the cause.
3. **No schedule `duration`** exists (via `export_config`) → the `duration_factor` window-scaling
   theory is ruled out.
4. **Live version is `2026.6.2`** (confirmed from the IU startup banner `Version: 2026.6.2`) →
   not a stale build.
5. **The live system's *planned* next run was already correct:** Bib 2's next-run
   `sequence_status` showed `duration == adjustment` for all three zones (106 / 41 / 80 min,
   full delivery).
6. **Cycle length changed mid-morning:** 04:30–08:15 cycles were ~10 min; by 08:45 Front was
   running a **67-min** cycle (matches the *current* config, `max_duration "01:30"` = 90 min →
   3×67 min). Bib 1's master `last_changed` was **08:30:00** — i.e. the config was edited and IU
   reloaded ≈08:30, mid-run.

## Reproduction (deterministic, in the test harness)

- Single sequence and two concurrent sequences, cycle-and-soak, SI totals pushed once before
  the run → **100% delivery** in `2026.6.2`. Could not reproduce any shortfall with a static
  config (tried small totals, real-magnitude totals, large `min_soak`).
- **Reload mid-run reproduces it:** run a cycle sequence, then call `irrigation_unlimited.reload`
  partway through → delivery collapses to **33% / 50%** and a zone is left switched **on**.
  (Harness: `IUExam.reload(...)` between `run_until("…06:00")` and `run_until(None)`.)

## Root cause (code)

`IUController.load()` (`custom_components/irrigation_unlimited/irrigation_unlimited.py:5016`)
calls `self.clear()` (`:5018`) at the top, so a reload **rebuilds the whole controller** and
drops existing runs. After the rebuild, `muster_sequence`
(`:5110`) re-derives schedules; the "Morning" slot (04:30) has already fired for the day, so
today's run is not re-created and the in-flight cycle-and-soak plan is lost. Cycle-and-soak is
hit hardest because its runs are spread over a long soak-inclusive timeline, so most of the
remaining cycles are still pending at reload time. Zone valve teardown on reload does not
reliably turn an actively-on zone off (observed stuck valve in repro; see `IUZone.finalise`
`:2485`, which only turns off on zone *removal*).

This is general IU reload behavior, not specific to the cycle math. `calc_cycles`
(`:346`), `_build_cycle` (`:3232`), `duration_factor` (`:4360`) and `total_time_final` (`:4348`)
are all correct — they deliver full on-time when the run is not interrupted.

## What is NOT the cause (ruled out)

- Soak counted against the duration budget (soak is additive; full on-time delivered when
  uninterrupted).
- Schedule `duration` / `duration_factor` scaling (no schedule duration configured).
- Stale / old build (live is 2026.6.2).
- The cycle split / interleave logic (delivers 100% in all static reproductions).
- The "double constrain" idea (idempotent `min(min(x))`) and the merge-added `_update_all`
  ordering (followed by a rebuild) — both investigated and dismissed.

## Immediate user guidance (no code change needed)

1. **Only edit/reload IU when no sequence is running** (after the morning run completes, or
   midday/evening). The interrupted run does not resume.
2. **Units check:** cycle durations use HH:MM. `max_duration: "01:00"` = **60 minutes**, Front's
   `"01:30"` = 90 min. For heavy clay you almost certainly want short cycles (e.g. `"00:10"`–
   `"00:15"`) to prevent runoff. This does not change total on-time delivered, only cycle length
   and total run-window length. Change it while idle, then reload.

## Recommended hardening (next session — decision needed)

Pick an approach (they differ in scope and upstream-acceptance risk):

- **A. Preserve the running run (recommended).** If a sequence is running when the config
  reloads, leave its in-flight run intact and apply config changes only to its next run.
  Directly fixes the under-delivery. Larger change to the load/clear flow; precedent exists in
  `clear_runs(include_sequence)` which already preserves "manual and running schedules"
  (`:1804`, `:2025`).
- **B. Safety-close + document.** Keep "reload cancels the in-flight run", but guarantee no
  valve is left on and document the behavior. Smallest / most upstream-friendly; does not make
  the run resume.
- **C. Re-derive the remainder.** On reload, rebuild but credit on-time already delivered today
  so remaining cycles continue. Closest to "just works" but the most complex/fragile (needs
  per-zone delivered-on-time tracking across rebuilds).

Independently of A/B/C: **add a valve-close guarantee** so an interrupted run never leaves a
zone switched on (observed in the repro).

## Related change already shipped

- **PR #5 (merged):** `export_config` now serialises the `cycle` block (sequence-level and
  per-zone overrides). Previously it omitted them, which hid the cycle config from
  diagnostics/round-trip. Version bumped to `2026.6.3`.

## Environment / validation notes

- The merged tree pins `homeassistant==2026.5.0` / `pytest-homeassistant-custom-component
  ==0.13.329` (Python ≥3.14). The investigation sandbox only had Python 3.13, so local runs used
  an **off-pin** HA `2026.2.3` / plugin `0.13.316`, which is unstable for the *full* suite
  (segfaults) and flakes `test_sequence_cycle_adjust` (confirmed flaky on unmodified HEAD).
  **CI runs the pinned environment and is authoritative.**
- Reproduction tip: avoid `manual_run` while testing (a double `manual_run` has corrupted IU's
  zone model before); drive via the schedule path.
