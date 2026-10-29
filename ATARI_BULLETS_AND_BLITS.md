# Next ST/STE investigations: bullets and blits

Scope: plain 68000 ST/STE, ST-Low 320x200, four interleaved bitplanes.
TT/Falcon are out of scope. This is an investigation handoff, not a confirmed
bug report or authorization for a particular optimization.

Start from runtime commit `5ef190cf`. The completed repair work, STE16/17/18
comparison, exact profiling-build identity and open visual checks are recorded
in [ATARI_TODO_UNIT_DAMAGE.md](ATARI_TODO_UNIT_DAMAGE.md#session-close-ste17ste18).
Read `ATARI_NOTES.md` before changing the palette/c2p pipeline.

Use **`PATH=/usr/bin:/bin`** for all compiler/build commands; the compiler
earlier in the ordinary PATH is not the working cross-compiler:

```sh
PATH=/usr/bin:/bin make -s -j2
```

The local quiz bypass in `src/opendune.c` is unrelated and remains uncommitted.
Do not stage unrelated captures, game assets or notes.

## 1. Firing, bullet and rocket animations

Goal: attribute the cost of a shot to shooter changes, projectile movement,
impact/explosion animation, terrain restoration and foreground recomposition.
Find unnecessary presentation work without changing simulation timing,
trajectory, collision, damage, RNG consumption, audio or visibility.

### Code-path map

| Stage | Entry points and references | What to inspect |
|---|---|---|
| Unit firing | [`Script_Unit_Fire`, src/script/unit.c:596](src/script/unit.c#L596) | Target/range/orientation checks, projectile type, salvo/cooldown bookkeeping and projectile creation. Its final notification is already `UNIT_UPDATE_MAP_STATE`, not a generic redraw. Do not undo that optimization. |
| Turret firing | [`Script_Structure_Fire`, src/script/structure.c:513](src/script/structure.c#L513) | Structure-origin bullets/missiles and their cooldown path. Keep separate from moving-unit firing when attributing costs. |
| Projectile creation | [`Unit_CreateBullet`, src/unit.c:2088](src/unit.c#L2088) | Missile and bullet/sonic branches differ in initial position, targeting, lifetime and `bulletIsBig`. Check allocation/first-frame damage as well as steady movement. |
| Tick and movement | [`GameLoop_Unit`, src/unit.c:188](src/unit.c#L188), [`Unit_MovementTick`, :109](src/unit.c#L109), [`Unit_Move`, :1391](src/unit.c#L1391) | Old-position removal/repair, animation flip, collision/arrival, new-position registration and disappearance. Impact branches around :1506-1560 can remove the projectile before the normal movement epilogue at :1619-1621. |
| Native damage | [`Unit_PrepareSpriteChange`, src/unit.c:132](src/unit.c#L132), [`Unit_UpdateMap`, :2605](src/unit.c#L2605), [`GUI_Widget_Viewport_DamageUnit`, src/gui/viewport.c:870](src/gui/viewport.c#L870), [`Map_UpdateSprite`, src/map.c:612](src/map.c#L612) | Preserve old graphic bounds before mutations and independent new-sprite dirtiness. WINGER and ground paths differ; `bulletIsBig` retains conservative registration/candidate handling. Registration callbacks are not merely drawing work. |
| Projectile graphics | [`GUI_Widget_Viewport_AirSprite`, src/gui/viewport.c:826](src/gui/viewport.c#L826), air draw loop at [:1307](src/gui/viewport.c#L1307) | Bullet single-frame/big variant, 16-direction rocket frames and flips, animation-set offset and clipping. Projectiles can be in the air-unit pool even though they travel across terrain. |
| Data definitions | [`g_table_unitInfo`, src/table/unitinfo.c:1402](src/table/unitinfo.c#L1402), bullet entry at [:1694](src/table/unitinfo.c#L1694) | Rocket/bullet dimensions, movement type, display mode, sprite IDs and animation flags. The bullet entry uses WINGER, pool indices 12-15, sprite 174 and a single-frame display mode. |
| Impact/gameplay | [`Map_MakeExplosion`, src/map.c:431](src/map.c#L431), [`Explosion_Start`, src/explosion.c:312](src/explosion.c#L312) | Separate real terrain/gameplay effects from transient sprite repair; do not suppress crater, structure damage, spice or fog updates as redundant presentation. |
| Explosion animation | [`Explosion_Tick`, src/explosion.c:348](src/explosion.c#L348), [`Explosion_Update`, :33](src/explosion.c#L33), frame/move/stop handlers at [:207-275](src/explosion.c#L207), [`src/table/explosion.c:7`](src/table/explosion.c#L7) | Native old-frame damage is already sprite-bounded, identical sprite-ID changes already return early, and position changes repair old coverage. Commands can repeat a sprite ID with different delays/side effects; do not remove script commands merely because the frame repeats. |
| Explosion publication | [`src/gui/viewport.c:1249`](src/gui/viewport.c#L1249), [`GUI_ViewportPlanarSprite`, src/gui/gui.c:1882](src/gui/gui.c#L1882) | Active/dirty checks, cached sprite lookup/composition, background repair and actual screen publication. Submission counts are not publication counts. |
| Terrain animation | [`Animation_Start`, src/animation.c:248](src/animation.c#L248), [`Animation_Tick`, :301](src/animation.c#L301) | A separate tile-animation system used by tracks/impact aftermath; do not treat it as only another explosion sprite frame. |

### First experiment

Record a short firing-heavy capture with identifiable bullet and rocket phases,
plus an idle/no-firing reference. Ideally repeat the same save/camera actions.
Count projectile creations, moves/removals, frame changes, sprite submissions,
cache misses/compositions, terrain repairs and actual publications. Attribute
inclusive costs without summing nested rows.

Questions, not established defects: are tiny projectiles paying disproportionate
tile/candidate-repair cost; do rocket direction/flip changes churn cache entries;
does firing dirty an unchanged shooter through another path; does impact cleanup
repair the same area more than once across passes? Check the existing before-
mutation hooks and early returns before adding new ones.

Verify small/big bullets, every rocket direction/flip, spawn-to-first-draw,
impact/removal, frame-size changes, viewport clipping/scrolling, fog, and overlap
with ground sprites, explosions, cursor and placement preview. Preserve the
existing draw order: ground sprites, explosions, remaining terrain repair, air
sprites, then message text. The late air pass is significant for projectile
damage/restoration.

## 2. BLiTTER versus CPU blitting performance

Goal: distinguish cache preparation, terrain repair, clipping/overlay handling,
register setup and actual pixel transfer. Small masked sprites may be
setup-bound; larger sprites/opaque tiles may have different tradeoffs.
Measure rather than assuming BLiTTER always wins.

### Code-path map

| Stage | Entry points and references | Current behavior |
|---|---|---|
| Backend selection | [`Video_Init`, src/video/video_atari.c:1102](src/video/video_atari.c#L1102), [`Video_Atari_ViewportBlitter`, :2863](src/video/video_atari.c#L2863) | `viewport_blitter` defaults to zero; an explicit request also requires detected ST-family BLiTTER hardware. Unsupported requests warn and retain CPU rendering. |
| Cache/backend split | [`GUI_ViewportPlanarSprite`, src/gui/gui.c:1882-2070](src/gui/gui.c#L1882) | CPU composite keys include horizontal phase; BLiTTER uses unshifted composites, expands opacity masks per plane, and builds sixteen phase-specific blit plans. Cache-miss work must be separated from hit/publication work. |
| CPU sprite publication | [`Video_Atari_PresentPlanarSpriteStrided`, src/video/video_atari.c:3281](src/video/video_atari.c#L3281), [`Video_Atari_PublishPlanarSpritePlain`, :3256](src/video/video_atari.c#L3256) | CPU-prealigned cached strips are published in tile-boundary fragments after repair. Zero masks skip writes; opaque masks copy; partial masks merge. |
| Unshifted sprite dispatch | [`Video_Atari_PresentPlanarSpriteUnshifted`, src/video/video_atari.c:3355](src/video/video_atari.c#L3355) | Uses BLiTTER when enabled and not overlapping placement. Cursor overlap permits BLiTTER plus backup refresh. Placement forces CPU shifted/overlay-aware merging. Clipped sprites may build a temporary plan. |
| BLiTTER setup/plans | [`Video_Atari_BlitterSetup`, src/video/video_atari.c:2893](src/video/video_atari.c#L2893), [`Video_Atari_BuildSpriteBlitPlan`, :2927](src/video/video_atari.c#L2927) | Skew, FXSR/NFSR, first/last masks and X/Y increments; one-word and clipped-source cases need particular care. Normal phase plans are already cached. |
| Masked BLiTTER kernel | [`Video_Atari_BlitMasked`, src/video/video_atari.c:2983](src/video/video_atari.c#L2983), [`Video_Atari_BlitterStart`, :2887](src/video/video_atari.c#L2887) | Two passes, four planes: eight starts per sprite, mask operation then colour OR. Each start uses control `0xc0` and waits for completion. Current code has no CPU/BLiTTER overlap. |
| Opaque terrain | [`Video_Atari_BlitOpaque`, src/video/video_atari.c:2965](src/video/video_atari.c#L2965), tile dispatch at [:3060-3110](src/video/video_atari.c#L3060) | One opaque tile launch, cached setup until a masked blit invalidates it. Only eligible overlay-free viewport tiles with prepared copy pixels use this path; selection/fog/overlay cases differ. |
| CPU primitives | [`Video_Atari_PlanarMergePlain`, src/video/video_atari.c:1955](src/video/video_atari.c#L1955), [`Video_Atari_PlanarCopyGroup`, :1964](src/video/video_atari.c#L1964), [`Video_Atari_ComposePlanarSprite`, :3195](src/video/video_atari.c#L3195) | Distinguish mask merge/copy on the screen from cache composition. Inspect actual 68000 assembly and register spills before introducing handwritten kernels. |
| Overlay protection | [`Video_Atari_PlanarOverlaysOverlap`, src/video/video_atari.c:1931](src/video/video_atari.c#L1931), cursor refresh at [:3331-3353](src/video/video_atari.c#L3331) | Backups cover whole 16-pixel groups, not just visible cursor/placement pixels. Fast paths must keep those backups current and must not resurrect stale pixels when overlays move. |
| Supervisor dispatch | [`src/os/atari.h:11-23`](src/os/atari.h#L11) | Resident builds call directly while supervisor-resident; otherwise the helper uses `Supexec`. Do not charge a trap per blit without checking the actual build/runtime path. |

### First experiment

Compare CPU and BLiTTER with the same save, camera, sprite population and overlay
state, recording the option and hardware model. Keep stock 8 MHz ST/STE and
16 MHz Mega STE results separate. Different cache keys mean a backend comparison
also changes cache/composition workload; report that explicitly.

Break results down by sprite width/height, alignment, clipping, opacity and
cursor/placement overlap. Count setup calls, starts, transfers, cache misses,
CPU-fallback publications and repaired tiles. Profile waiting/bus time as well
as CPU instruction overhead. Investigate thresholds, fewer transfers/setup
writes or CPU loop improvements only after establishing the dominant costs.
Do not add asynchronous ownership or reorder sprites as an unmeasured shortcut.

## Shared correctness and validation

Keep 68000-compatible instructions, word-aligned interleaved screen memory,
the selected planar buffer, before-draw terrain repair, foreground dependency
propagation and post-publication dirty-block clearing. Preserve existing palette
mapping and cache semantics; these tasks do not require a new quantizer.
Do not remove registration callbacks or tighten the shared `Map_Update(0)` halo
as a side effect of faster drawing.

Existing starting points:

- `tools/test_unit_damage.py`, `tools/test_sprite_bounds.py` and
  `tools/test_viewport_sprite_damage.py`: state/damage separation, component
  coverage and foreground dependencies.
- `tools/test_animation_damage.py`: real tile-animation invalidation.
- `tools/test_viewport_sprite_cache.py`: cache/composition, CPU publication and
  register-level BLiTTER model, including shift/clipping cases.
- `tools/test_viewport_cursor_post_blit.py`: pixels, backups, overlay movement
  and generated plain-loop assembly checks.

Run targeted tests with the trusted PATH, then build for 68000. Archive each
new executable with matching objects/disassembly before profiling; validate
sampled bytes including relocated operands. Never reuse old object-relative
branch offsets after changing/rebuilding the relevant object. Complete visual
checks for disappearance, overlap and scroll transitions on Atari/Hatari;
performance data alone does not establish correctness.

## Goal: remove `forceRedraw` from the engine

`GUI_Widget_Viewport_Draw` still carries a `forceRedraw` flag
(`g_viewport_forceRedraw`), tested per unit, per explosion and in several
setup decisions. The goal is to delete it and, in the rare cases that set it
(interface change, jump scroll without overlap, returning from options, mode
switch), mark all 15x10 viewport tiles dirty instead. That is about 10
dirty-row word writes, so it is cheap, and every consumer then needs only the
normal dirty-tile test.

Blockers to clear first:
- The legacy chunky viewport path (`drawToMainScreen`, `trackCopyDamage`,
  selection-rectangle repaint) and the planar/chunky switch near the top of
  `GUI_Widget_Viewport_Draw` must go; all ST/STE drawing is planar anyway.
- Verify `Video_Atari_CursorDirect()` is true wherever the viewport is drawn.
- `BeginSpriteDamage(planarViewport && !forceRedraw && !hasScrolled)` turns the
  sprite-damage filter off when forced; check that all-dirty tiles give the
  same result.

A ground-unit loop precheck (inline viewport bounds reject, `e067ad38`) was
tried and retired: capture 40 showed only ~0.3k cycles saved per pass, not
worth the added code.
