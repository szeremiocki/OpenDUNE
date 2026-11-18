# ST/STE native rendering: separation audit and remediation plan

Status: phases 0-7 complete. The findings below describe the pre-refactor
snapshot; implementation progress is recorded in section 8.

Scope: the current ST-Low colour and ST-High mono implementations on plain
68000 ST/STE. TT/Falcon, game logic and new visual styles are outside scope.

## 1. Agreed boundary

The engine and GUI decide **what to draw, where, when and in what order**.
They own logical geometry, selection edges, text layout, cache identity,
damage, fog visibility and asset lifetimes.

The native backend decides **how prepared pixels and commands represent that
request**: bitplanes, doubled mono cells, source-relative dither, physical
addressing, masks, shifts, CPU kernels and BLITTER launches.

The same frontend request must reach the same scheduling and damage policy
in both modes. A prepared native command may use CPU or BLITTER and may have
different geometry or pass counts. Those differences must not select a
different frontend algorithm.

Moving an existing `if (Mono())` into a differently named GUI helper is not
sufficient. Shared policy must actually become shared; native implementation
details must sit behind the backend boundary.

The recent `GFX_ComposePlanarTile()` change is a completed example of this
boundary, not evidence that the whole renderer is already unified:

- GFX chooses/cache-keys the base and overlay and classifies compact opacity.
- The startup-selected kernel overwrites all native pixels and masks.
- Neither kernel needs the caller to clear complete-output buffers.

## 2. Audit findings

References describe the current working tree; line numbers will move during
implementation. The audit followed explicit mode queries, mono helper calls,
native pointer arithmetic and plane loops through the affected frontends,
then inspected the relevant backend publication paths.

| ID | Location | Finding |
|---|---|---|
| S1 | `src/gfx.c:347-405`, `GFX_DrawPlanarSelectionTile` | GFX constructs logical edges correctly, but also expands mono pens/masks and edits colour planes. Both native painting implementations belong in the backend. |
| S2 | `src/gui/gui.c:457-486,525-537`, announcement banner | GUI generates native solid backgrounds and separately copies mono physical rows when restoring text footprints. Cache/timing policy is legitimate; native fill/copy is not GUI policy. |
| S3 | `src/gui/gui.c:699-766,1030-1053`, text targets and cached strips | GUI knows native group offsets, emits individual mono cells/colour plane bits, and repacks text strips differently by layout. Shared text bookkeeping should use native surface/rectangle operations. |
| S4 | `src/gui/glyph.c:77-210` | Colour uses prepared glyph masks and a word-oriented emitter; mono separately walks strings and raw glyph pixels. This duplicates layout/fit policy as well as native emission, and contributes to the measured mono text cost. |
| S5 | `src/gui/sidebar.c:139-181`, `GUI_Sidebar_AssetLoad` | GUI expands native masks and predicts command allocation using colour-specific set/clear analysis and byte counts, while mono calls the command compiler to determine size. Native preparation must return trustworthy sizing/metadata through one interface. |
| S6 | `src/gui/sidebar.c:327-440,685-698`; `src/gui/planar.c:8-97` | GUI implements shifted native merges and fills itself. The border shortcut rejects mono and uses explicitly four-plane primitives. Sidebar clipping/style remains shared GUI policy; native painting and its supported fast paths belong below it. |
| S7 | `src/gui/gui.c:4546-4683`, credits | Shifted-digit preparation, row composition and background repair each have separate mono/colour implementations inside GUI. Digit-change detection and scrolling policy can remain shared while these native operations move below the boundary. |
| S8 | `src/video/video.h:21-31`; native offsets in `gui/gui.c` and `gui/sidebar.c` | The general Atari interface includes the mono implementation header and exposes cell/group helpers. This makes frontend dependence on native representation easy. Remove those dependencies after callers migrate; retain only necessary shared contracts. |
| S9 | `src/video/video_atari.c:3055-3110,4430-4556,4604-4898,5000-5095` | Some public video operations still implement separate publication workflows, not just separate kernels. Mono text/compact sprites enter `MonoPublish`, which clips, flushes, applies protection, restores the cursor and clears damage; colour has separate scheduling/queue paths. These responsibilities need one common owner. |
| S10 | `src/video/video_atari.c:2279-2359` | Cursor writeback and placement-aware group merging duplicate save/update/reapply policy around layout-specific arithmetic. Share that lifecycle and dispatch only native read/write/merge/pen operations. Preserve mouse and placement backup footprints. |
| S11 | `src/video/video_atari.c:2687-2690,2784,3075-3077,3172-3180,4369,4430-4546`; `src/video/atari_viewport_tile.s:10,46,96` | Old tile-cursor protection state still has readers in C and assembly, although the current code only clears its tile bits. This is obsolete policy scaffolding after draw-last unification, not a reason to restore cursor protection. |
| S12 | `src/wsa.c:80-142,191-245,490,665,819-871` | WSA excludes mono from native recordings. Its delta grouping, masked overlay composition and `PWS4` cache format assume the colour representation. This is a genuine remaining coverage boundary, but removing the mode guards alone would be incorrect. |
| S13 | `src/video/video_atari.c:3919-3960,5020-5041,5141-5179` | Highlight state is represented by colour-plane recipes; mono treats a non-null recipe as texture inversion. Protected hardware eligibility also tests the mode directly. Semantic effect IDs and native command capabilities should be separated from their physical implementation. |

### A related performance regression, not another frontend branch

`Video_Atari_PrepareColour()` (`src/video/video_atari.c:3655-3686`) is already
inside the backend. However, constant colour mappings now take the generic
per-pixel pen pass before c2p. The placement is correct; forcing that slow
implementation is not required by unification.

The previous comparison measured approximately 46.5 versus 234.9 cycles per
converted asset pixel, with about 0.70% of the colour capture spent in the
additional pen pass. Restore fused mapping/c2p for phase-independent policies
without bypassing the authoritative palette mapping or disabling future
phase-aware policies.

### Differences that are not violations by themselves

- Resolution detection, palette polarity and hardware initialization.
- Mono opacity expansion, physical row addressing and colour plane arithmetic
  inside native kernels.
- Different native command layouts, source increments, heights and pass counts.
- A backend CPU command where another backend has a BLITTER command. Shared
  callers must not need to know why; identical acceleration is not required.
- Colour's protected-sprite halftone kernel versus a native CPU implementation
  for mono partial fog: a 32x32 physical mono tile cannot directly use the
  existing 16-word colour halftone scheme.
- A whole-buffer copy or a `groups * height * 4` storage allocation. Both
  layouts use the same total byte count per logical area. Subrectangle and
  group offsets still need layout-aware handling.
- Shared logical masks, glyph-mask construction and logical selection tests.

`src/gui/viewport.c` currently has no mono/colour mode checks. Its shared
viewport scheduling should be preserved, not rewritten to compensate for
backend differences.

## 3. Native operation contracts

Extend the existing startup-selected backend incrementally; do not introduce
a second renderer or a universal slow per-pixel compositor.

Required operation families, reusing current public operations where possible:

| Operation | Contract |
|---|---|
| Paint a logical mask with a pen | Used for selection edges, fills and borders. Native code expands the mask and samples the pen at an explicit stable logical origin. |
| Copy/extract a private native rectangle | Used for banner restore and text-strip compaction. Handles both mono physical rows and partial edges; performs no live-screen publication. |
| Merge/shift a private native image | Explicitly accumulates into initialized destination pixels/masks. Supports the necessary phase/clipping cases without inventing frontend mode branches. |
| Prepare/draw glyph masks | Shared font/string planning feeds backend-native word emission; preserve the optimized colour emitter and replace the mono raw-pixel loop. |
| Prepare native masked assets/commands | Returns sizes, opacity representation and command metadata. GUI does not reproduce pass analysis or machine-code byte formulas. |
| Publish a prepared draw | Common clipping, fog/overlay policy, queue lifetime and damage rules; the selected native operation supplies actual execution and addressing. |

Complete-output operations and accumulating operations must remain distinct.
The former write transparent output pixels to zero and assign compact masks.
The latter preserve uncovered destination pixels and require initialized
destinations. Do not remove initialization from genuine accumulating canvases.

Dispatch once per asset/rectangle/line or compiled command, not once per pixel
or native word. Keep native command storage immutable while queued, preserve
existing drain-before-mutation rules, and avoid new per-frame allocation or
large extra lookup tables.

Destination addressing may remain a small shared helper or surface view.
Callers must not implement "also copy the second physical mono row" themselves.

## 4. Proposed implementation order

Each phase is a separate reviewable change, with its own colour and mono
checks. Dependencies below are real API/behaviour prerequisites, not merely
the proposed order of execution.

### Phase 0: baseline and performance guard

Dependencies: none.

- Preserve the current binary, symbol maps and representative reference output.
- Keep the known colour cold-preparation regression visible; implement its
  backend fast path as a separate, independently reviewable fix.
- Fix only stale test fixtures needed to exercise the affected operation.
  Do not fold a broad test-suite repair into a renderer refactor.

`colorbattle1.txt` and `monobattle1.txt` were collected before the most recent
tile-composition change. They remain useful context, not exact baselines for
the current `769f5e77c752...` binary. Future profiles need matching binaries
and symbols; unlike workload averages cannot establish a regression alone.

### Phase 1: primitives and selection tiles

Dependencies: the operation contracts above; baseline checks from Phase 0.

- Add native masked-pen painting and private rectangle-copy/extract operations.
- Move selection-tile pixel painting behind the backend. GFX continues to
  compute logical edge masks, update compact opacity and manage cache keys.
- Leave the already-correct full-output tile composition operation intact.
- Validate arbitrary dirty output, mask endpoints, opaque zero pixels,
  distinct mono top/bottom patterns and both mono polarities.

Completion: no mono helpers or native plane painting in
`GFX_DrawPlanarSelectionTile()`.

### Phase 2: banner, text storage and sidebar

Dependencies: Phase 1.

- Migrate banner background fill/restore and cached text-strip extraction.
- Move sidebar native merge/fill/border kernels below GUI; keep sidebar
  clipping, widget ordering, clipping eligibility and style selection shared.
- Move sidebar native mask preparation and command sizing into the backend.
- Keep existing prepared CPU/BLITTER commands and batching. Do not replace
  colour's optimized kernels with the current general mono compositor.

Completion: these frontends manage logical content/cache state without
mode-selected pixel manipulation or command-size formulas.

### Phase 3: one glyph planner, native emitters

Dependencies: Phase 1; can be developed independently of Phase 2 after the
surface/painting contracts stabilize.

- Keep font metrics, glyph masks, fit rules, character advances and overlap
  ordering common.
- Give each backend a native word emitter, selected before line execution.
- Route individual-glyph fallback through the same preparation/painting
  boundary; remove the separate GUI mono-cell writer.
- Preserve transparency semantics, source-relative dither phase, negative
  spacing, clipping, text-state side effects and damage bounds.

Completion: no duplicated mono string traversal; no raw native bit insertion
inside GUI text-target code. Measure preparation separately from publication.

### Phase 4: credits and retained-window composition

Dependencies: Phase 1; reuses migrated private-surface operations from Phase 2.

- Use native shift/merge operations for prepared digit positions and row draws.
- Use private masked-copy operations for scrolling-pixel background repair.
- Retain one digit-change detector, scrolling algorithm and publication list.

Completion: no mono branches or physical plane loops in the credits frontend.

### Phase 5: common publication and overlay lifecycle

Dependencies: Phase 1 and existing native publication/overlay test coverage.
This is not a prerequisite for the independent frontend migrations above.

- First unify tile/text publication entry points; then migrate compact and
  expanded sprite fallback publication in small, separately checked steps.
- Centralize validation, logical clipping, protection splitting, queue/immediate
  choice, required flushes, cursor/placement repair and dirty-state completion.
- Keep layout/addressing/merge/execution inside native operations. A CPU kernel
  should not also own an alternative damage/protection scheduler.
- Share cursor-background/placement save-update-reapply ordering around native
  group kernels. Preserve whole-group backups, not only visible overlay bits.
- Carry semantic highlight IDs into native preparation instead of treating a
  colour-plane recipe pointer as universal state.
- Represent supported protected/effect draws as backend commands or explicit
  native capabilities, without exposing mode tests to GUI.

Completion: common publication policy with backend execution. This does not
promise a mono BLITTER implementation of every effect or partial-fog case.

### Phase 6: WSA native-cache coverage

Dependencies: Phase 1 and the publication contracts consolidated in Phase 5.
Proposed as a later scope item, not part of the first primitive patch.

- Keep WSA decoding, frame progression and dirty-region scheduling common.
- Move native delta grouping/replay and masked window composition below the
  storage-layout boundary. Logical dirty groups must cover both mono rows.
- Define cache compatibility before enabling mono: native layout, polarity
  where relevant, and palette/dither policy identity must be distinguishable.
- Preserve valid colour recordings and existing TOS filename constraints.
  Reject incompatible recordings explicitly; retain the established original
  animation fallback until the native path is ready.
- Do not merely remove the two mono guards or reinterpret colour `PWS4` data
  as mono.

Completion: one WSA lifecycle, with compatible backend-native recording and
publication, or an explicitly documented remaining limitation.

### Phase 7: interface and legacy-policy cleanup

Dependencies: migration of the relevant callers in Phases 1-6.

- Stop including `atari_mono.h` through the general video interface; frontend
  files should not call mono native helpers.
- Remove obsolete tile-cursor protection state/checks from C and assembly
  together, after confirming there are no remaining writers.
- Verify and retire the legacy `Video_Atari_DrawPlanarTileFogged()` path and its
  helper if still unused. The current GFX fog cache calls
  `Video_Atari_DrawPlanarTile()` instead; do not confuse that with removing
  active fog protection or GFX fog composition.
- Update structural guards and architecture documentation after each migration,
  rather than declaring the whole renderer unified after a local fix.

## 5. Appearance and support limitations requiring separate agreement

These are not to be silently changed during structural work:

- All current mono highlight effects use inversion, unlike colour's distinct
  plane effects. Preserve current appearance while separating semantic state
  from implementation; any revised mono visual policy needs consultation.
- Mono palette fades currently install the final mapping immediately
  (`video_atari.c:977-988`). Identical colour hardware fades are not available
  on the mono display. Do not emulate them through stale chunky repaints.
- FPS display is disabled in mono (`video_atari.c:1394-1401`).

Keep these limitations explicit, rather than disguising them as native geometry.
Enabling/redefining them is not required to move pixel operations out of GFX/GUI.

## 6. Validation and acceptance

- Extend existing pixel-oracle suites: `test_dither_preparation`,
  `test_mono_rendering`, `test_mono_packer`, `test_sidebar_planar`,
  `test_announcement_phase`, `test_credits_planar`, `test_wsa_planar` and
  `test_planar_scroll`, as appropriate to each phase.
- Check both layouts, mono polarities, all relevant X phases, masks and
  partial edges, source immutability, dirty-output handling, and caller-owned
  initialization for accumulating operations.
- Check deferred and immediate drawing, pending-scroll barriers, drain before
  cache mutation, fog, placement, mouse backups and draw-last tile cursor order.
- Run the existing native 68000 command/display-list checks and cross-build.
  Use sanitizers for affected host-side kernels. Keep non-TOS builds compiling.
- Add focused boundary checks: migrated GFX/GUI functions must not query mode
  or call mono implementation helpers. Do not use a blanket ban on `4`, plane
  words inside backend kernels, or valid logical masks.
- Obtain external host-emulator/hardware profiles from the user; do not run
  Hatari in this environment. Separate warm drawing, cache preparation, text,
  cold load/sidebar preparation and native launch costs.

Recommended first implementation: **Phase 1**, with the known colour
preparation fast-path repair tracked separately under **Phase 0**. Then
migrate frontend families incrementally rather than performing one large
renderer rewrite.

## 7. Follow-up palette policies

After the structural refactor, explore deriving backend-specific 4x4 patterns
directly from original 256-slot VGA RGB entries, rather than first reducing
them to the 16 hardware pens. This is a separate visual-policy change.

Keep the current mappings selectable: flat colour repeats its selected ST pen
in every pattern cell; legacy mono bakes the existing 16-pen-derived pattern
for each palette slot. Direct-VGA mono and future colour dithering are additional
policies using the same preparation interface. A policy change must invalidate
affected prepared assets; it must not change scheduling or drawing algorithms.

## 8. Implementation progress

Phases 0-7 are complete. The palette-policy pivot remains separate follow-up work.

| Phase | State | Implemented / remaining |
|---|---|---|
| 0 | Complete | Preserved the original binary. Restored fused colour preparation for compatible flat authoritative mappings and frozen flat terrain mappings; phase-dependent/custom/unaligned inputs retain the generic path. |
| 1 | Complete | Native offset, copy, masked painting, row merge and complete-output group shift operations. |
| 2 | Complete | Selection painting, banners, cached text strips, individual glyph fallback, sidebar fills/masks/command sizing and native borders migrated. Optimized colour border kernels now live under `src/video/`. |
| 3 | Complete | One glyph layout/mask traversal; colour-specialized word emitter and native mono word emitter below the boundary. |
| 4 | Complete | Credits preparation, scrolling repair and row composition use native operations without GUI mode branches. |
| 5 | Complete | Tile/text and compact/expanded sprite publication share scheduling, protection, overlay and damage policy. Native CPU row kernels own representation/execution only. Mouse/placement group writes share save/update/reapply ordering; mono also uses the common post-BLITTER mouse repair path. Highlight state is a semantic effect ID; colour recipes stay in colour kernels. |
| 6 | Complete | WSA traversal/publication is shared. Native delta grouping/replay and overlay merges handle both layouts. Colour `.PWS` and mono `.PWM` coexist; PWS5 validates layout, polarity and the used source slots' complete dither mapping. |
| 7 | Complete | Public-header separation retained. Removed obsolete tile-cursor protection arrays, masks and readers together in C and assembly, including dead rectangle/conversion fallback branches. Retired the unused backend fogged-tile entry point/helper; active GFX composition, fog protection and cursor restoration remain. |

GFX and GUI sources no longer query mono mode or invoke mono implementation
helpers. Native execution capabilities still differ between backends.
Masked display-list tile/text commands remain a colour-backend capability;
the shared publisher uses native CPU execution when unavailable.

Current mono/colour mappings and highlight appearance are preserved. Native
border painting retains the original fill/edge source phases, including the
bottom-right pixel's vertical-edge phase. No direct-VGA visual policy or
policy-selection UI has been introduced.

The completed sprite-publication migration removes `Video_Atari_MonoPublish`.
Compact and expanded sprites now use the same clipping/protection split,
queue/immediate decision, flush barriers, cursor/placement repair and dirty
completion in both modes. Actual native row writes, source/destination offsets
and physical row counts remain backend operations. BLITTER effects and
partial-fog eligibility are explicit backend capabilities, not mode-selected
publication workflows. Mono retains texture inversion for every highlight ID;
colour retains the existing nine effects. The tight colour compact-sprite word
loop remains separate from scheduling.

Non-viewport native rectangles use the same native CPU row operations without
inheriting viewport highlights or protection. The unused chunky-sprite adapter
also feeds the common prepared-sprite publisher rather than separate mode
workflows.

The WSA migration keeps original indexed Format80/Format40 reconstruction
before native preparation. Native XOR transitions are derived from complete
prepared frames, not from quantized source deltas. Backend operations interpret
logical changed groups in either layout; WSA owns frame traversal and dirty-run
publication. Private animation pixels and composed overlays remain separate,
including mono's two physical rows and partial right edges.

Colour `.PWS` and mono `.PWM` files have separate 8.3-compatible namespaces.
The common PWS5 header identifies layout/polarity and fingerprints every dither
phase of the original palette slots used anywhere in the animation. Unused
slots do not invalidate a recording. Old PWS4 files cannot establish mapping
compatibility and receive a one-time rebuild from the original in colour mode;
mono never opens or changes them. Source-file edits still require cache removal.
Prepared objects retain a fixed asset mapping for their lifetime; callers with
palette-animated indexed content remain opted out. Intro source mapping is
reinstalled before each lookup/preparation, including after mono uniform effects.
This does not introduce new dither policies or redefine mono fades.

The standard intro window at (8,24) now opts explicitly into a 320-wide native
canvas: its 304-pixel picture is padded with eight native-black pixels per side
before deriving deltas. PWS5 flag bit 2 identifies this layout and triggers a
one-time recode of compact intro recordings, independently in colour and mono.
The full initial image establishes the baseline after scene changes/dissolves;
normal transitions then use the shared native XOR operation directly on the
live screen through LiveBegin/LiveEnd. No per-frame retained/composed copy is
required. Offscreen/regional requests snapshot the accumulator before private
replay resumes. This exclusive intro ownership does not apply to Mentat or
other general WSA playback; the intro's (0,0) shot remains compact. Native
addressing, bit layout, polarity and black painting remain backend operations.
Native intro timing now excludes loading's pending cooperative timer debt and
dissolve work from the playback budget. Mode-2 tails remain paced with speech
pumping and skip handling. Temporary per-scene/per-frame timing instrumentation
has been removed after target validation; genuine failure warnings remain.
Timing remains shared between colour and mono and does not change the existing
timer rates.

Legacy cleanup removes only the abandoned cursor write-exclusion policy:
`g_videoTileCursorTiles` had no writer other than reset, and
`s_tileCursorWritable` had no writer at all. C and assembly queue gates retain
the active mouse backup-footprint checks. Immediate writers still restore the
tile cursor, while deferred publication retains the explicitly scheduled tail.
Fog writable masks and hidden/protected-row metadata remain independent.
The unused `Video_Atari_DrawPlanarTileFogged()` and its private cursor helper
are removed; `GFX_DrawPlanarTileFogged()` still prepares/reuses its composite
and submits it through `Video_Atari_DrawPlanarTile()`.

Validation completed across these deliveries:

- Affected preparation, mono packing/rendering, sidebar, announcement, credits,
  scroll, display-list, cursor-pointer and c2p-stride suites, with targeted
  fixture reruns after dependency repairs.
- Address/undefined-behaviour sanitizers on private surfaces, glyph/fallback
  rendering, publication/backup ordering, credits and mono border phases.
- Stock 68000 cross-build and the colour plain-sprite loop's no-spill guard.
- Non-TOS syntax checks of the changed shared `gfx.c` and `gui/gui.c`;
  glyph/sidebar implementation files are TOS-only in `source.list`.
- Whitespace checks and confirmation that user-owned startup changes remain
  untouched. No Hatari execution or new target-side performance measurement.
- Sprite-specific phase/crop/fog matrices with no overlays, mouse only,
  placement only and both; immediate/deferred native execution; immutable
  prepared sources; all nine highlight IDs and reset handling.
- Native 68000 command execution, including both layouts' compiled sprite
  geometry, and the shared compact publisher's queue-to-CPU barrier.
- Original versus recorded WSA replay using the synthetic fixture and available
  Mentat/intro assets in colour and both mono polarities; continuation seeds,
  forward/reverse/loop traversal, dirty repair, overlays, partial/subrect draws,
  cache-only replay, format/mapping/polarity rejection and allocation/I/O faults.
- Colour-to-mono-to-colour cache switching without source reads or changes to
  the other mode's recording; unused-slot reuse and dither-phase invalidation.
  The affected selection passes 30 tests; the expanded replay oracle also
  passes address/undefined-behaviour sanitizers.
- Phase 7 reruns native rectangles, cursor/fog/placement publication, credits,
  dither preparation, mono packing, WSA replay and 68000 display-list execution.
  Structural guards reject the retired C/assembly state and backend fog entry
  point; fog-metadata checks retain independent cursor and fog lifecycles.

The older complete `test_viewport_cursor_post_blit` and standalone
`test_viewport_tile_sprite_repair` pixel fixtures lack current native/refresh
scaffolding. The former's standalone object guard passes; the shared publication
oracle independently checks colour and mono tiles/text/sprites, cursor-only
repair, placement overlap and saved backups. This is not a claim that every
historical repository fixture passes. `monobattle3`/`colorbattle3` cover the
sprite-publication migration with no broad performance regression apparent.
The WSA migration still needs external visual/performance checks of Mentat
pictures and the intro; battlefield captures do not exercise those paths.
