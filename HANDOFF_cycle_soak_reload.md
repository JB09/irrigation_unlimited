# Handoff: Cycle-and-Soak Under-Delivery — Root Cause is Valves Self-Closing (NOT IU)

**Date:** 2026-06-19 (corrected)
**Component:** Irrigation Unlimited (rgc99 fork `JB09/irrigation_unlimited`), branch
`claude/peaceful-franklin-XyDsS`, version `2026.6.3`.
**Status:** Root cause **confirmed** in the valve/Zigbee layer. **No IU code change is the fix.**
An optional IU robustness watchdog is deferred (see end).

> **This document corrects two earlier, WRONG conclusions about the same 06-19 run:**
> 1. *"Soak consumes the duration budget"* — wrong. IU's cycle-and-soak math is correct.
> 2. *"A mid-run config reload tore down the run"* — wrong for this run; **no reload occurred.**
>
> Both were misled by the same artifact: the **~10-minute physical valve on-times** were read as
> a *software* cycle length / budget. They are not. IU commanded full-length cycles; the physical
> valves closed early.

---

## TL;DR

On the 06-19 04:30 run, IU delivered the full schedule **in its model** — per-zone commanded
on-time matches the Smart-Irrigation (SI) allocation almost exactly. But the physical SONOFF
SWV-ZFU valves closed ~10 minutes into each cycle and IU never re-asserted them, so any cycle
longer than ~10 min delivered only its first ~10 min. IU's `today_total` reported full delivery
throughout, masking the shortfall. **Confirmed:** the valve's on-device `manual_default_settings`
is `irrigation_mode: duration, irrigation_duration: 10` — it runs a built-in 10-minute timed
cycle and self-closes, ignoring IU's hold. Root cause is the valve's on-device duration mode.

---

## Decisive evidence: IU model vs physical valve

Source 1 — IU component event log (`custom_components.irrigation_unlimited`, what IU *commanded*).
Source 2 — valve `switch.*` recorder history (what the valve *physically did*). Times local (EDT).

| Zone (IU id) | SI allocated | IU commanded (event log) | Valve actually ran (switch history) | Delivered |
|---|---|---|---|---|
| Front (z1) | 201.5 m | 04:44→05:51 (67m), 06:53→08:00 (67m), 08:45→ (ongoing) | 04:44–04:54 (10m), 06:53–07:03 (10m) | **~20 m** |
| Side Right (z2) | 48.0 m | 05:51→06:39 (48m, single cycle) | 05:51–06:01 (10m) | **~10 m** |
| Side Left (z3) | 56.0 m | 3 × ~14m (04:30, 06:39, 08:01) | 10m × 3 | ~30 m |
| Back Right (z4) | 106.3 m | 04:44→05:37 (53m), 06:31→07:24 (53m) | 04:44–04:54 (10m), 06:31–06:41 (10m) | **~20 m** |
| Back Center (z5) | 41.5 m | 3 × ~14m (04:30, 06:17, 08:05) | 10m × 3 | ~30 m |
| Back Left (z6) | 80.5 m | 05:37→06:17 (40m), 07:25→08:05 (40m) | 05:37–06:17 (**40m**), 07:25–07:35 (10m) | ~50 m |

Read off this table:

1. **IU's commanded totals ≈ SI allocations.** Back Right 53+53 = 106.3 = SI 106.3 exactly;
   Back Center 3×13.8 = 41.5 = SI 41.5; Back Left 40+40 = 80.5 = SI 80.5. IU's cycle-and-soak
   split/schedule is **correct**, and `today_total` reflected it (Front showed 134 = two completed
   67-min cycles, not a clamp).
2. **The valve ran far less than IU commanded, and the gap scales with cycle length.** 53–67 min
   cycles → valve delivered only ~10 min (~19%); ~14 min cycles → ~10 of 14 (~72%). Signature of a
   valve that closes ~10 min after opening regardless of IU's hold. IU does not re-assert
   mid-cycle, so the remainder is dry while IU believes the zone is watering.

**Anomaly:** Back Left's first cycle ran the full 40 min, then its second closed at 10 min — so
it is **not** a perfectly hard 10-min device timer everywhere. More consistent with on-device
plan/inching variability or intermittent Zigbee loss. Either way: valve layer.

---

## Proof there was NO reload (correcting the prior handoff)

`grep` of the component log for the run window shows:
- One `service: adjust_time` burst at **04:15:30** (the SI push; Front `3:21:27`, …).
- A continuous `EVENT controller/zone state` stream from **04:30:00** to **08:45:53** with **no
  load/reload/setup line**.
- The 04:43:59 master "off" is one second — zones 3 & 5 went off at 04:43:50–59 and zones 4 & 1
  went on at 04:44:00–09: a normal cycle boundary where both bibs hand off at once.

The prior handoff's "reload ≈ 08:30" was a **UTC/local mix-up**: `08:30:00Z` = `04:30` local =
the scheduled run start, not a reload. Cycle lengths did **not** change mid-run either — Front's
*first* cycle at 04:44 was already 67 min in IU's model; the "10-min early cycles → 67-min later
cycle" story was the valve's 10-min closes vs IU's 67-min command, not a config change.

> Note: the reload **teardown** mechanism described in the prior handoff is real in general — a
> reload *does* discard an in-flight run. It simply **did not happen** on 06-19.

Why the harness couldn't reproduce it: simulated switches obey IU exactly, so a 67-min command
delivers 67 min (100%). Real valves don't. "Cannot reproduce a static-config shortfall" was
itself the clue that the defect is **outside** IU's code.

---

## CONFIRMED root cause (valve on-device duration mode)

Valve device profile (`switch.irrigation_zone_1_bib_1`; SONOFF "Zigbee smart water valve",
sw 1.0.7). The on-device settings entity is definitive:

```
sensor.irrigation_zone_1_bib_1_manual_default_settings =
  {'fail_safe': 0, 'irrigation_amount': 0, 'irrigation_amount_unit': 'liter',
   'irrigation_duration': 10, 'irrigation_mode': 'duration'}
```

The valve is in **`irrigation_mode: duration`, `irrigation_duration: 10`** — on an "on" command
it runs a built-in 10-minute timed cycle and closes itself, ignoring IU's hold. Corroborated by
siblings: `hour_irrigation_duration: 10`, `real_time_irrigation_duration: 30` (= Front's three
10-min cycles today). Other on-device logic is inactive (`irrigation_plan_settings` empty,
`seasonal_watering_adjustment` all 1.0, `rain_delay` off,
`enable_water_shortage_auto_close: false`) — so it is specifically the manual duration mode.

**Integration:** valves are **Zigbee2MQTT-backed** (MQTT entities; no ZHA). The settings
composite is exposed **read-only** in HA; there is no HA service to write it. Change it via the
**Z2M frontend** (device → Exposes/Settings) or an MQTT publish to the device `/set` topic.

**Per-valve caveat:** settings may not be uniform — Back Left ran one full 40-min cycle then a
10-min cycle, so its `manual_default_settings` likely differs. **Audit all six valves; do not
assume identical config.**

---

## Fix (two layers — do both for the clean end state)

1. **Make IU the sole controller (device side):** change each valve's
   `manual_default_settings.irrigation_mode` from `duration` to a stay-open / switch mode so the
   valve holds open until IU closes it. Then any IU cycle length is honored.
2. **Short cycles for clay (IU side):** set cycle-and-soak `max_duration` to ~`"00:10"`–`"00:15"`.
   Correct for heavy clay regardless; and if a valve must stay in 10-min duration mode, a 10-min
   IU cycle **matches** the auto-close so delivery is no longer truncated — IU just needs enough
   cycles (e.g. Front 201 min ÷ 10 ≈ 20 cycles).

If only one change is possible short-term, **#2 alone resolves the under-delivery** (IU cycle ≈
valve auto-close); #1 is the robust long-term state.

> Units note: cycle durations parse as **HH:MM**, so `max_duration: "01:00"` = **60 minutes** and
> Front's `"01:30"` = 90 min (this is why IU's cycles are 67 min). For clay you want short cycles
> (`"00:10"`–`"00:15"`). Change cycle length only while the controller is idle, then
> `irrigation_unlimited.reload`.

---

## IU robustness gap (deferred — optional upstream, warn-only)

IU does **not** detect a valve that closed under it — no mid-cycle poll or re-assert — so its
model and `today_total` report full delivery while the valve is shut. A **warn / emit-event on
divergence** during an active cycle would make this failure visible (a self-healing re-assert was
considered but is **not** wanted for now).

Clean extension point (from a read-only code survey, for a future session):
- `IUSwitch.muster` (`custom_components/irrigation_unlimited/irrigation_unlimited.py:1105`) and
  `_check_back` (`:1035`) already drive `check_switch` (`:1110`) and emit `EVENT_SYNC_ERROR` via
  `log_sync_error` (`:6303`).
- Today check_back only verifies briefly **after a state change** (delay × retries), then stops.
  A mid-cycle check would gate on `self._state` (zone on) and drive `next_event` (`:1065`) to wake
  each interval during an active run, calling `check_switch(..., resync=False, log=True)` to warn
  when switch state ≠ model state.

**Not implemented.** Recorded here so it can be picked up later if desired.

---

## Verification of the fix (user-side)

After switching the valve mode (and/or shortening IU cycles): run a short schedule and confirm
the IU event log and the valve `switch.*` history stay in **lockstep** for every cycle, and that
per-zone SI buckets climb toward 0 by the credited (now full) amounts.

## Guardrails / don't-touch

- Do **not** change the SI precipitation source (`sensor.rainfall_24h`, aggregation "Last") —
  separate, working subsystem.
- IU is YAML-configured; `irrigation_unlimited.reload` to apply, and only **while idle** (a reload
  tears down an in-flight run).
- Avoid `manual_run` while testing (a double `manual_run` has corrupted IU's zone model before);
  drive via the schedule path.

## Data appendix — IU event timeline (local), 2026-06-19

```
04:15:30  adjust_time push (Front 3:21:27, SR 0:47:57, SL 0:55:57, BR 1:46:19, BC 0:41:30, BL 1:20:28)
04:30:00  z3 on, z5 on
04:43:50  z5 off
04:43:59  z3 off, master off
04:44:00  master on, z4 on
04:44:09  z1 on
05:37:10  z4 off
05:37:20  z6 on
05:51:18  z1 off
05:51:28  z2 on
06:17:34  z6 off
06:17:44  z5 on
06:31:34  z5 off
06:31:44  z4 on
06:39:25  z2 off
06:39:35  z3 on
06:53:34  z3 off
06:53:44  z1 on
07:24:53  z4 off
07:25:03  z6 on
08:00:53  z1 off
08:01:03  z3 on
08:05:17  z6 off
08:05:27  z5 on
08:15:02  z3 off
08:19:17  z5 off, master off
08:45:53  master on, z1 on
```
Valve switch on-times (local): z1 04:44–04:54, 06:53–07:03 · z2 05:51–06:01 · z3 04:30–04:40,
06:39–06:49, 08:01–08:11 · z4 04:44–04:54, 06:31–06:41 · z5 04:30–04:40, 06:17–06:27, 08:05–08:15 ·
z6 05:37–06:17, 07:25–07:35.
