# ST/STE unit damage reduction checklist

Scope: native-planar ST/STE only. TT/Falcon and other video backends retain
their original invalidation. Preserve simulation, animation cadence, occupancy,
fog, minimap updates and house/visibility accounting.

## Batch progression

The first batch stopped after **five of the ten audit rows** and was profiled
in STE11. The second batch completes the remaining five rows, current-harvest
and genuine-rotation bounds, explosion bounds and unchanged-spice suppression.
A checked row records implemented scope, not measured savings or a claim that
all possible optimization is exhausted.

| Batch | Cause | Original work | Change / remaining work |
|---|---|---|---|
| [x] | Harvest bookkeeping | Broad redraw after changing `amount` / `inTransport` | State-only update: preserve accounting and key clearing; no native redraw or tile damage. Real spice changes still invalidate terrain separately. |
| [x] | Harvest animation | Current position plus two historical positions, potentially three 5x5 regions | Old attachment-frame bounds, real directional offset and wobble, before phase change. No visual history traversal; registration/removal history remains. |
| [x] | Body/turret rotation | Generic damage on either 8- or 16-direction bucket changes | Skip unchanged native ground 8-direction buckets. Real turns mark old changed body/attachment/turret bounds, including offset turrets. Instant turns prepare old geometry too. |
| [x] | Blink/deviation recolour | Background repair despite unchanged opacity; expiry forces 5x5 | Repaint-only for recolour. Leaving HARVEST explicitly marks its old attachment before action changes; deviation retains conservative current-component repair where applicable. |
| [x] | Stop / far-target approach | Generic redraw for speed or target-orientation changes | State-only update. Keep near-target position-adjustment damage and later actual rotation/movement notifications. |
| [x] | Walking animation | Generic dimension-based damage, plus candidate halo | Mark actual old body bounds before frame change, including between-tile positions; queue the new body independently. |
| [x] | Selection changes | Generic unit damage, including smoke/harvester expansion | Repair old marker only before changing selection; repaint old/new composites and clear keys. Structure/placement selection coverage remains separate. |
| [x] | Successful firing | Final generic redraw after cooldown/salvo bookkeeping | Final notification is state-only. Sandworm victim/removal/addition work remains intact. |
| [x] | Death/idle frames, infantry formation, carryall load | Generic updates for genuine graphic changes | Prepare old components before explicit frame/type/load changes. Skip identical explicit frame/idle-offset requests; preserve RNG order. |
| [x] | Movement, placement, removal, hiding, deployment | Occupancy/fog/minimap work and old-image repair | Old actual geometry before position/wobble/cleanup changes; original registration footprints and history retained. Native pickup omits the redundant removal preceding `Unit_Hide`. |

## Implementation contract

- `Unit_UpdateMap` retains remove/add/redraw modes and adds repaint/state and
  prepared-removal modes. Repaint/state become the old redraw mode outside native
  planar video; prepared removal becomes ordinary removal.
- State-only does not clear existing dirty flags or counters: previously queued
  real movement/frame damage must survive.
- Repaint-only keeps the owning unit independently dirty, so the renderer does
  not require a dirty anchor tile to submit it. Opacity masks are independent of
  palette/remap variants in the planar component cache.
- Before-mutation hooks mark old body/layer bounds through the same selectors
  used by drawing. Repaint queues new graphics; it does not itself repair
  terrain. Generic native redraw/removal also uses actual component geometry.
- Removal callbacks retain occupancy/minimap work and viewport candidates,
  without turning every registration tile into terrain repair. The radius-based
  5x5 registration branch is intentionally unchanged.
- Wobble is chosen at the original RNG point but assigned after departure
  repair. Smoke start/clear and spice depletion also prepare disappearing or
  changing layers before mutating their render inputs.
- Existing smoke-local damage and its accepted neighbour-overlap limitations
  are unchanged. Repaint-only updates also add no neighbour candidates; the
  full composite still publishes damage through the existing filter. As with
  smoke-local damage, a clean neighbour anchored outside the candidate cells
  may retain incorrect cross-tile overlap order.
- Other component repairs still use `Map_Update(0)` and its existing shared
  candidate halo. No new filtering passes, damage-source records or persistent
  previous-draw bounds.

## Profile context, not promised savings

STE10 saw 267 harvest-bookkeeping notifications costing 0.91 ms per viewport
pass inside `Unit_UpdateMap`. Active harvest animation cost 1.24 ms/pass.
The two harvester-history traversals together cost 3.58 ms/pass **across all
update types**; only presentation work is reduced. These timings overlap and
must not be added. Rotation generated 1,527 invalidations, but the capture does
not say how many changed only a 16-direction bucket.

### STE11 results

The capture matches the preserved five-row build: 38,725 program instruction
samples validated against its executable, with byte-identical GUI/viewport
objects to STE10. The batch boundary remains unchanged.

| Metric | STE10 | STE11 | Change |
|---|---:|---:|---:|
| Viewport passes/second | 8.39 | 11.68 | +39.1% |
| Viewport inclusive ms/call | 36.61 | 23.75 | -35.1% |
| Terrain inclusive ms/pass | 9.37 | 5.56 | -40.7% |
| Map_Update variants + Map_UpdateAround own ms/pass | 11.62 | 6.95 | -40.2% |
| Sprite publications/pass | 7.35 | 4.37 | -40.6% |

Per-notification costs show that the changed paths actually benefited, not
just that the captures have different lengths or frame rates:

| Unit_UpdateMap caller/reason | STE10 ms/call | STE11 ms/call |
|---|---:|---:|
| Harvest bookkeeping | 13.45 | 0.218 |
| Active harvest animation | 12.49 | 5.12 |
| Blink | 3.88 | 0.189 |
| Stop | 4.69 | 0.196 |

STE11 recorded 792 returns through the new unchanged-8-direction ground
rotation guard. The harvester visual-history guard ran 456 times, skipping
both history traversals each time (912 omitted Map_UpdateAround calls).
Registration/history work remains: its two call sites together took
2.33 ms/pass versus 3.58 in STE10, across different workloads; this remaining
cost is not all redundant presentation damage.

These are not identical-scene runs, so +39.1% throughput is not an isolated
speedup measurement. Native script dispatches/second were nearly unchanged
(2,756 -> 2,702, -2.0%); their -29.5% count per viewport pass largely reflects
more frames per second, not proof of a comparably lighter simulation.
Far-target approach was not exercised. Deviation-colour changes were not
demonstrated by the profile. Cache lookups remain 99.11% hits.

### STE12 results

The capture matches the second-batch executable: 39,247 sampled program
instructions validated, over 292.91 seconds and 4,117 viewport passes.
GUI objects differ, but the reused cache/filter counter sites were checked
individually against both object disassemblies.

| Metric | STE11 | STE12 | Change |
|---|---:|---:|---:|
| Viewport passes/second | 11.68 | 14.06 | +20.4% |
| Viewport inclusive ms/call | 23.75 | 16.42 | -30.9% |
| Terrain inclusive ms/pass | 5.56 | 2.49 | -55.1% |
| Map traversal/update + bounds helpers ms/pass | 6.95 | 4.10 | -41.1% |
| Sprite publications/pass | 4.37 | 2.48 | -43.2% |
| Plain tile publications/pass | 13.14 | 5.81 | -55.8% |

Map_Update variants + Map_UpdateAround alone fall from 6.95 to 2.77 ms/pass.
The new bounds work costs another 1.33 ms/pass, included in the 4.10 above:
own Map_UpdateSprite/DamageUnit/Prepare work plus damage-side shared-selector
calls, without double-counting nested map updates or charging drawing-side
selectors as new repair overhead.

Traced helper time per animation notification, including old-bounds preparation
and repaint in STE12, falls from 5.12 to approximately 0.96 ms for active
harvesting and 1.77 to 0.72 ms for walking. These are helper costs, not the
entire animation-loop cost. Partial trace boundaries leave 342 harvest-prepare
versus 343 repaint records; the walking pair has 78 records each.

Both Map_UpdateAround -> Map_Update(0) call sites execute zero times in STE12.
Wide registration/candidate callbacks remain active; this is not evidence that
the general 5x5 branch was removed. Spice fixup performs 25 final-graphic
comparisons, suppresses 14 unchanged repairs and retains 11 actual changes.
That path is too rare here to explain the overall gain. Composite lookups
remain 99.14% hits.

The captures are not controlled identical-scene benchmarks. Script dispatches
per second rise slightly, 2,702 -> 2,787 (+3.2%), while their count per viewport
pass falls with the increased rendering throughput. Neither those counts nor
the profile establish visual correctness or resolved halo/overlap behavior.

Subsequent user context: the harvester was outside the viewport for a
significant part of STE12. This can materially affect terrain repairs, sprite
redraws and throughput, so the cross-capture percentages must not be attributed
entirely to the code changes. Even per-notification costs depend on visibility.
Harvester draw submissions are 919 in STE11 versus 556 in STE12
(2.41 versus 1.90 per second), but those counters combine scene visibility and
changed redraw eligibility; they cannot measure time on screen or isolate its
contribution. A harvester-visible comparison would strengthen attribution.
The user reports substantially less noticeable flicker, but not its elimination.

### STE12a additional workload

Validated 40,248 program samples against the same executable. Over 388.03
seconds and 4,907 viewport passes, STE12a records 1,351 harvester submissions
(3.48/s, versus STE11's 2.41/s and STE12's 1.90/s). These are redraw submissions,
not visible-time counters. The harvester was still absent for part of the run;
the user reports that faster gameplay changed siege and harvester routes, so
an exact old playthrough is neither feasible nor required.

STE12a reaches 12.65 viewport passes/s (+8.3% versus STE11), 18.88 ms per
viewport call (-20.5%), 2.96 ms terrain/pass (-46.8%) and 2.77 sprite
publications/pass (-36.5%). Script dispatches/s are 2,947 versus STE11's
2,702 (+9.1%). The harvest bounds+repaint helpers total about 1.24 ms per
notification, versus 5.12 in STE11. This supports benefits in another, more
harvester-active workload, without claiming an isolated same-scene speedup.

### Shared halo audit

Three separate mechanisms can recruit/redraw nearby units:

1. `Map_UpdateSprite` currently uses `Map_Update(0)`: actual old-component
   repair tiles also mark a 3x3 candidate halo (`src/map.c:608-647`).
2. Registration still marks candidates across its original footprint, including
   5x5/history visits. That policy remains a separate follow-up.
3. In the STE12/12a baseline, every accepted composite adds its entire
   tile-rounded bounding rectangle to the cumulative sprite-damage filter.
   A later clean candidate can therefore pass without actually touching an
   earlier sprite. The rectangle includes transparent gaps between attachments.

A production-function harness in session artifacts (`halo-audit.py`) confirms
that A=[0,17), B=[31,33), C=[47,49), at the same vertical interval, can form
an accepted A->B->C chain despite 14-pixel gaps. Candidate admission remains a
separate prerequisite; a halo/registration visit supplies it. This establishes
a mechanism for non-touching neighbour redraw, not a capture-level count of
which source caused each publication.

An initially proposed experiment was single-tile mode 4 for sprite-originated
component repairs, keeping generic terrain/fog/structure `Map_Update(0)`,
registration and the cumulative filter unchanged. It would remove the
extra candidate halo, not tile-rounded erasure or all neighbour redraw.
Omitting overhanging clean neighbours can leave erased pixels/order artifacts,
as already accepted for smoke-local updates; extending that policy is a
behavioral decision, not a universally correctness-preserving optimization.
That proposal was not implemented; the user instead chose the clean-relay
experiment below. The candidate halo remains unchanged.

Prior STE8/STE9 decisions remain relevant: ordinary body-to-body ordering flips
were deliberately accepted; infantry underneath crushing vehicles and smoke
coverage were the important exceptions. STE8 implemented infantry-only
propagation and separate smoke publication. STE9 restored baked smoke and
tested an infantry/downward guard with source records. These implementations
were reverted for performance/bookkeeping cost, not because those accepted
ordering tradeoffs were disproved. The current unrestricted cumulative filter
is the restored baseline, not evidence that general painter-order preservation
is required. Smoke is currently baked into composites, so an always-on-top
smoke rule is not guaranteed by the present implementation.

STE9 directly suppressed only 54 candidates while added measured bookkeeping
blocks cost about 0.344 ms/pass; nearly 98% of accepted ground draws already
qualified through independent dirtiness/base damage. Those counts predate
the upstream damage reductions and cannot establish today's propagation cost
or justify retaining all cascades. Terrain-erasure dependencies must remain
distinct from ordering-only sprite publication dependencies.

The STE12/12a baseline filter branch counters distinguish clean accepted candidates:
STE12 has 5,104 clean acceptances out of 10,227 total; STE12a has 6,333 out
of 13,622 (46.5%, or 1.29 per viewport pass). In STE12a the remaining
acceptances are 6,999 independently dirty and 290 with the filter disabled.
These totals reconcile with the GUI acceptance counter. They do not distinguish
original terrain/dirty-source hits from relay-only hits, nor say whether each
clean publication expands the bitmap. Preventing clean sprites from relaying
would keep their own necessary draws and remove only later relay-dependent
publications. Terrain repair and harvester self-flicker are not directly
reduced by that rule. Any ordering tradeoff must still consider infantry and
smoke rather than assuming all clean publications are harmless.

### Withdrawn clean-ground relay experiment (STE13)

**Reverted after STE13.** The current renderer is restored to the STE12/12a
implementation: every accepted sprite propagates its full rounded composite
rectangle. The narrow strip, infantry-anchor exception and extra draw-call
arguments described below were removed together, including their experimental
tests. The proven unit/effect/spice damage improvements remain. This section
records the withdrawn experiment, not the current rendering contract.

- [x] Retain the original clean-sprite acceptance test against any intersecting
  accumulated-damage tile.
- [x] Accepted clean ground sprites add only the row below their logical anchor,
  horizontally intersected with rounded composite bounds and anchor column +/-1.
  The strip is clipped to the viewport and contains at most three columns.
- [x] Clean infantry gets that same strip and additionally ORs its anchor tile.
  The anchor write is redundant when already damaged, but can extend damage
  when a between-tile body qualified through its non-anchor portion.
- [x] Dirty sprites, non-ground sprites, selection-outline propagation and
  forced/scroll/non-native handling retain their previous behavior.
- [x] Pass the current logical anchor and infantry status by value through
  the existing draw call. No extra bitmap, source records, unit-history fields,
  neighbour lookup, tracked-target restriction or separate smoke pass.
- [x] Keep pending terrain repair before even a clean sprite publication.
  The filter creates no terrain repair, registration or candidate bits.
- [x] 21 focused renderer/cache/repair-order/selection tests, with sanitizers
  where supported; final added chain/rejection cases rechecked separately.
- [x] Assertion-enabled trusted 68000 compilation of both changed C files
  and `/usr/bin:/bin` release build.
- [ ] User visual assessment, especially harvester neighbours, infantry/crushing
  and smoke overlap.
- [x] STE13 matching-build profile: no observed publication reduction; increased
  clean redraw rate and a verified new-chain mechanism, detailed below.

Ordinary same-row body ordering is deliberately relaxed. Smoke remains baked
into composites; this strip is the agreed heuristic, not an always-on-top
guarantee and not a smoke-height/source test. Permitted downward chains remain,
and already-published earlier units cannot be revisited by this filter.
The ground anchor comes from the current logical packed tile, not a composite
edge, cached top-left or wobble-shifted display position.

Regression coverage exercises retained damage after terrain consumption,
dirty-A -> clean-B -> skipped-C chains across 14-pixel gaps, strip-only
successors, infantry anchor/no-op cases, clean rejection, viewport clipping,
offscreen anchors and exhaustive 1..5-column bounds against the three-column
cap. Draw-dispatch tests cover native and legacy modes, palette/remap argument
ordering, harvester temporary keys and unchanged composite identity.

The withdrawn STE13 executable had SHA-256
`5ae88ff24bd08586286b9b5cbc425a54a7884486494c01b836b7f7a53b61485e`.
Its matching executable/objects remain archived as `clean-ground-relay-*` in
session artifacts. The STE12/12a baseline archives are preserved unchanged.

### STE13 results: the downward strip is not purely restrictive

The capture matches the clean-ground-relay executable above: 41,304 sampled
program instructions validated, over 303.80 seconds and 3,312 viewport passes.
The current renderer objects match the archived build; `unit.o` and `map.o`
are byte-identical to their STE12/12a counterparts.

| Metric | STE12a | STE13 | Change |
|---|---:|---:|---:|
| Viewport passes/second | 12.65 | 10.90 | -13.8% |
| Viewport inclusive ms/call | 18.88 | 23.68 | +25.4% |
| Sprite publications/pass | 2.77 | 4.54 | +63.7% |
| Sprite publications/second | 35.08 | 49.50 | +41.1% |
| Clean filter acceptances/second | 16.32 | 30.65 | +87.8% |
| Independently dirty acceptances/second | 18.04 | 18.28 | +1.4% |
| Terrain inclusive ms/pass | 2.96 | 3.24 | +9.6% |
| Filter own ms/pass | 0.515 | 0.950 | +84.6% |
| Filter own microseconds/request | 97.8 | 132.7 | +35.7% |

Per-second counts matter here because a slower viewport accumulates more work
per pass. Almost all of the publication-rate growth is in clean acceptances,
not independently dirty sprites. Terrain cost per wall-clock second actually
falls from 37.42 to 35.36 ms; plain tile publications fall from 85.22 to 79.50/s.
Harvester submissions are nearly unchanged at 3.48 versus 3.51/s, although
these are not visible-time measurements. Script dispatches rise 7.2%, from
2,947 to 3,159/s. Spatial density, ordering and scene differences remain
confounders: these captures cannot isolate the rule's exact causal cost.

STE13 records 23,740 native requests, 23,714 filter calls and 15,042 accepted
requests: 5,554 independently dirty, 9,311 clean and 177 filter-disabled.
Of the clean acceptances, 8,372 are ground sprites using the new rule and
939 retain non-ground propagation. The strip OR executes 7,516 times and
the additional infantry-anchor OR 214 times. These count executed ORs, not
newly set bits or publications attributable to a particular source.
Actual masked sprite publications total 15,038. Composite lookup hits remain
99.15% (201 misses, 175 completed fills).

The clean-rule blocks themselves cost 0.161 ms/pass and their GUI vararg
parsing blocks 0.082 ms/pass. These are measured block costs, not isolated
net overhead: they exclude other dispatch/compiler changes and replace some
old full-rectangle work. GCC now inlines the native compositor into
`GUI_DrawSprite`, so old GUI counter offsets are invalid. The verified new
`gui.o` sites are request `0x4ac8`, filter call `0x4cb6`, accepted `0x4cc6`
and miss `0x4db4`; harvester NULL-key sites in `viewport.o` are `0x4190`
and `0x4ac6`. Reproduction and counters are in session
`battleste13-details.py/.json/.log`.

There is a concrete mechanism for extra clean draws: the strip is horizontally
bounded but not restricted to the composite's vertical bounds. A tile-centred
16x16 body can therefore mark the next row even though it wrote no pixels
there. A later clean unit in that row can repeat the operation, forming a
vertical or diagonal cascade that the old full-bounds filter would not create.

A sanitizer-enabled production-function harness in session
`clean-relay-row-audit.py/.log` demonstrates the difference: offer ten
tile-centred, vertically adjacent, non-overlapping bodies, all assumed already
admitted as candidates in top-to-bottom order, with terrain damage only under
the first. The previous full-rectangle rule accepts **one**; the new strip
accepts **all ten**. No terrain repairs or candidate recruitment are added.
This proves the new rule can increase propagation, not how often that happened
in STE13. The original horizontal-gap suppression remains valid too.

No renderer code or binary was changed during the profile analysis itself.
The subsequent decision was to discard this propagation experiment entirely,
not refine its strip. STE12/12a full-rectangle propagation and draw interfaces
were restored while retaining the earlier component-bound terrain improvements.
Any future propagation experiment requires a separate decision.

### Accepted STE12/12a restoration

The original cumulative sprite filter and draw interfaces are restored with
no STE13 relay code or experimental test changes remaining. Both proven
invalidation batches, smoke-local repairs, shared component selectors,
explosion bounds and unchanged-spice suppression are retained.

The restored trusted 68000 release is byte-for-byte identical to the archived
STE12/12a executable, SHA-256
`6ef16938bb23979f605853b488f4bc263962e2f66928802315d5a701c2b51e12`.
All 34 focused tests passed across sprite bounds, unit damage, smoke timing,
unit recount, sprite cache/damage, animation damage, phase reversal and planar
selection, with sanitizers where supported. This is the accepted implementation
baseline; the STE13 artifacts remain only for historical analysis.

## First-batch validation / progression

- [x] Focused native/legacy damage, registration and rotation regressions.
- [x] Script behavior and animation/state equivalence.
- [x] Trusted `/usr/bin:/bin` 68000 compilation and release build.
- [x] STE11 profile: matching build and observed invalidation/drawing reductions.
- [ ] User visual check for overlap, recolour and harvesting regressions.

The focused run passed 17 tests across `test_unit_damage`,
`test_unit_smoke_damage`, `test_unit_recount`, `test_viewport_sprite_damage`
and `test_viewport_sprite_cache`, with ASan/UBSan enabled for harnesses
supporting `TEST_CFLAGS`. It checks all update modes on native and legacy
backends, pending-damage preservation, 75-to-25 tile repair reduction for
three separate active-harvester regions, unchanged registration callbacks,
rotation state/bucket equivalence, script random/timing/spice effects and
the deviation/harvest-layer exception.

Reproduce with:

```sh
PATH=/usr/bin:/bin PYTHONPATH=.:tools \
TEST_CFLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer -fno-pie -no-pie' \
python3 -m unittest tools.test_unit_damage tools.test_unit_smoke_damage \
  tools.test_unit_recount tools.test_viewport_sprite_damage \
  tools.test_viewport_sprite_cache
PATH=/usr/bin:/bin make -s -j2
```

## Second-batch validation / progression

- [x] Renderer-derived component geometry, odd dimensions, subtile positions,
  wobble, directional harvest offsets, death frames and air/load variants.
- [x] Old-frame repair before walking/harvest advancement, explicit death-frame
  shrink/repeated-frame suppression, incremental/instant rotation and zero-position
  initialization.
- [x] Real removal callback occupancy/destination/forced-cleanup behavior;
  native viewport-only versus legacy terrain repair.
- [x] Movement-prefix regression: old wobble through departure, unchanged RNG
  consumption/order including track-animation calls.
- [x] Explosion shrink/move/stop, repeated-frame suppression and legacy path.
- [x] Spice final-graphic suppression, centre grade changes, world edges and
  disappearing harvest-layer hook.
- [x] Final sanitizer-supported focused regression run: 23 tests; assertion-enabled
  compilation of all six changed C files and trusted 68000 release build.
- [x] STE12 matching-build profile and measured changed-path reductions.
- [x] User reports substantially reduced, but not eliminated, flicker.
- [ ] New-build visual check for halo/overlap and selection/message coverage.

The additional geometry/effect/spice regressions are in
`tools/test_sprite_bounds.py`. Reproduce the complete focused run with:

```sh
PATH=/usr/bin:/bin PYTHONPATH=.:tools \
TEST_CFLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer -fno-pie -no-pie' \
python3 -m unittest tools.test_sprite_bounds tools.test_unit_damage \
  tools.test_unit_smoke_damage tools.test_unit_recount \
  tools.test_viewport_sprite_cache tools.test_viewport_sprite_damage \
  tools.test_animation_damage
PATH=/usr/bin:/bin make -s -j2
```

The release executable is `bin/opendune.tos`; its matching executable/objects
are preserved as `remaining-damage-bounds-*` in session artifacts, separately
from STE11. Existing strategic-map `snprintf` and unused factory-scroll warnings
remain unrelated to this batch.

## Adjacent producers and deferred policy

- [x] Explosion frame damage: actual old sprite bounds, existing candidate halo.
- [x] Skip unchanged visual invalidation in `Map_FixupSpiceEdges`.
- [ ] Discuss global 5x5 registration/candidate policy separately; no footprint
  shrink was made in this batch.
- [ ] Review the shared `Map_Update(0)` neighbour-candidate halo independently
  of actual terrain repairs from structures, animation, walls, fog and spice.
- [ ] Keep existing narrow shifted-scroll edge damage; full rebuild/message and
  structure-selection repairs need separate old/new coverage analysis.
- [ ] Optional cleanup: fold smoke-local damage into a named Unit_UpdateMap
  mode to share bookkeeping, preserving its accepted no-neighbour-halo policy.
  This was deferred after STE10; it is not a demonstrated major speed target.
