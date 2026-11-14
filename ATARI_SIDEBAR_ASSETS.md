# ST/STE sidebar prepared-asset inventory

This enumerates the 86 static assets prepared by `GUI_Sidebar_PrepareAssets()`
for the normal, complete widget setup in the ST/STE BLITTER backend.
Inventory numbers below are reference IDs, not preparation order.

`S` means the named private `s_sidebar` members in `src/gui/sidebar.c`.
`C` means the directly indexed `g_sidebarCaptions` members declared in
`src/gui/sidebar.h`. Each row is one descriptor and one prepared fragment,
not one on-screen widget.

## Geometry and storage

All dimensions include the pixels actually stored, including baked borders.
Small command fragments are reused at the four command-widget positions:
there are 42 action/state assets, not four copies of each of those 42 assets.

| Shape | Stored rectangle | Opacity | Pixel bytes + generated code |
|---|---|---|---|
| Background | 64x82 | Opaque | 2624 + 82 |
| Command/repair/upgrade button | 64x12 with normal widget geometry | Opaque | 384 + 82 |
| Cancel button | 64x13 with normal widget geometry | Opaque | 416 + 82 |
| Production face | 64x37 with normal widget geometry | Opaque | 1184 + 82 |
| Production caption/bottom strip | 64x10, rows 113-122 | Opaque | 320 + 82 |
| Ordinary production percentage background | 64x10, rows 113-122 | Opaque | 320 + 82 |
| Upgrade-percentage background | 64x20, rows 103-122 | Opaque | 640 + 82 |
| Title/power/starport caption | 64x(font height x line count), clipped to sidebar | Opaque | 32 bytes/row + 82 |
| Portrait frame | 16-pixel-aligned bounding width x (widget height + 2) | Masked; portrait interior excluded | Pixels plus replicated masks; code depends on required passes |
| Combined DMG/gauge/health frame | 32x(14 + font height); 32x22 in capture107 | Masked; health interior excluded | Pixels plus replicated masks; code depends on required passes |
| Separator | 64x1 | Masked outside its 52-pixel line | Pixels plus replicated masks; code depends on required passes |

General small-button height is `widget.height + 2`. Production strips run from
their text's top row through the button's bottom outline. Font/language changes
can change the standalone caption heights, but not the fixed button rectangles.

For aligned opaque fragments, compiled code is 82 bytes. Aligned masked
fragments use a 50-byte common portion plus 32 bytes per required clear/set
pass. A descriptor occupies 14 bytes on the target ABI. These figures exclude
the destination/call entry submitted to the shared display-list arena.

The standard-font/artwork fixture measures 45,474 bytes of packed pixels,
masks and code, plus 1,204 bytes for the 86 descriptors and three 4-byte
background-command pointers: 46,690 bytes, or approximately 45.6 KiB.
This is not an exact in-game total for every language
and resource set, and it excludes separately decoded sprite storage.

Ready text-button assets are anchored at the widget centre rather than the
measured text edge. After selecting font/style state, the wrapper directly
submits ready command, cancel and repair/upgrade images without scanning,
formatting, measuring or aligning their strings. It still updates colour slots
0/1 as the ordinary text draw would. Initial preparation and non-ready captions
retain normal layout; production captions and CPU drawing are unchanged.
No descriptors, image bytes or cache entries are added by this shortcut.

Separately decoded sprites use an 82-slot direct map for IDs 24-105, indexed by
ID minus 24, with no remap variants. The map costs 328 bytes on Atari; image,
mask and alignment-command allocations are additional and demand-driven.
Compared with the former 355-by-3 pointer map, this saves 3,932 bytes of BSS.
Native flat-button images stay unremapped when pressed. Out-of-range IDs and
nonzero remap counts are rejected rather than drawing an incorrect variant.

Stock 32x24 portraits/icons at IDs 28-30 and 65-105 bypass opacity decoding and
mask packing, as well as scratch clearing and final planar masking. Their
compact CPU masks point directly into one shared 192-word all-ones buffer
(384 bytes of BSS, initialized once). BLITTER commands instead use opaque
source copies: shifted/clipped copies use hardware endmasks on both edges,
without an opacity-clear pass. Each image
owns only its 384-byte planar pixels plus a 104-byte descriptor, rather than the
former 964-byte image/descriptor/masks allocation: 476 bytes saved per decoded
portrait, excluding alignment commands. Other sprite descriptors grow by four
bytes for the mask pointer. The shared buffer is palette-independent and is not
freed with individual images.

Solid IDs 24-26 (5x5, 8x8, 8x8) generate rectangular masks without opacity
decoding, preserving transparent padding and opaque logical colour zero.
Other IDs, including sprites 27, 63 and 64, retain the generic opacity decoder.
Known IDs with unexpected dimensions also use generic decoding. This is a
stock-SHAPES.SHP opacity contract; replacement artwork with holes at the same
IDs and dimensions requires updating eligibility.

The bank includes three additional 82-byte, code-only background-restore commands.
They copy the existing background image's stats rows 88-123 (64x36), title
rows 42-50 (64x9) and repair button rows 75-86 (64x12), with no duplicate pixels
or additional descriptors. Preparation still captures and converts 86 images;
it compiles 89 copy recipes.
Stats restoration clears old text before partial storage, power, radar-count or
Starport updates, including shorter numbers and countdown-to-caption transitions.
Visible repair/upgrade states use their complete prepared button assets;
repair restoration is needed only when that button disappears. Its shared
portrait/production outline rows are then restored with ordered line commands.
Health, stats, repair and production are independently dispatched in one batch,
without special combined handlers.

Unit-to-unit selection uses independent redraw-category bits for background,
portrait, name, gauge/frame, health and commands. Enemy-to-enemy and
player-to-player selections retain the background and gauge; changing unit type
redraws the portrait and restores only the title band before drawing the new name.
Same-type selections retain portrait/name too. Health updates only if its visible
width/colour changes. Player commands refresh visibility and shortcuts but redraw
only changed labels, selection states or normal-button hover states.
Same-type enemy-to-player transitions also retain the upper panel while adding
the commands. Player-to-enemy, different-type enemy-to-player and non-unit
transitions retain full redraws. Debug/player/language changes, invalidated
panels, non-stock portrait geometry/opacity contracts and titles taller than the
reserved band also use full redraws. A forced request for the already displayed
selection still restores the whole panel; a forced request for a different unit
may retain components.

## Named frame/background members: 7

| ID | Asset | Contents/state | Shape |
|---|---|---|---|
| 1 | `S.background` | Static sidebar background and outer decoration, without live panel contents | Background |
| 2 | `S.damageGauge` | DMG text, miniature gauge sprite27 and health frame; no health fill | Combined DMG/gauge/health frame |
| 3 | `S.separator` | Horizontal decoration at y95 | Separator |
| 4 | `S.portraitFrame[0]` | Raised portrait-button frame | Portrait frame |
| 5 | `S.portraitFrame[1]` | Flat pressed portrait-button frame | Portrait frame |
| 6 | `S.productionFace[0]` | Shared raised production-button face; no object image or percentage | Production face |
| 7 | `S.productionFace[1]` | Shared flat production-button face; no object image or percentage | Production face |

## Standalone static captions: 5

These contain their static background/decorations as well as glyphs.

| ID | Asset | Caption |
|---|---|---|
| 8 | `C.title[0]` | `STR_TARGET` |
| 9 | `C.title[1]` | `STR_MOVEMENT` |
| 10 | `C.title[2]` | `STR_HARVEST` |
| 11 | `C.power` | `STR_POWER_INFONEEDEDOUTPUT`, including the intersecting separator |
| 12 | `C.starport` | `STR_FRIGATE_INORBIT_ANDAWAITINGORDER` |

## Complete unit-command buttons: 42

Every fragment contains the full-width background, surrounding decoration,
outer outline, bevel/flat edges and localized action caption. State index0 is
idle raised, index1 is active orange raised, and index2 is pressed idle-colour
flat. Press overrides selection: there is no active-orange pressed asset.

All 14 action enums are prepared, including AI actions and actions that may
not be reachable through the currently selected player's four command buttons.
The caption comes from `g_table_actionInfo[action].stringID`.

| ID | Asset | State |
|---|---|---|
| 13 | `C.action[ACTION_ATTACK][0]` | Idle raised |
| 14 | `C.action[ACTION_ATTACK][1]` | Active orange raised |
| 15 | `C.action[ACTION_ATTACK][2]` | Pressed idle-colour flat |
| 16 | `C.action[ACTION_MOVE][0]` | Idle raised |
| 17 | `C.action[ACTION_MOVE][1]` | Active orange raised |
| 18 | `C.action[ACTION_MOVE][2]` | Pressed idle-colour flat |
| 19 | `C.action[ACTION_RETREAT][0]` | Idle raised |
| 20 | `C.action[ACTION_RETREAT][1]` | Active orange raised |
| 21 | `C.action[ACTION_RETREAT][2]` | Pressed idle-colour flat |
| 22 | `C.action[ACTION_GUARD][0]` | Idle raised |
| 23 | `C.action[ACTION_GUARD][1]` | Active orange raised |
| 24 | `C.action[ACTION_GUARD][2]` | Pressed idle-colour flat |
| 25 | `C.action[ACTION_AREA_GUARD][0]` | Idle raised |
| 26 | `C.action[ACTION_AREA_GUARD][1]` | Active orange raised |
| 27 | `C.action[ACTION_AREA_GUARD][2]` | Pressed idle-colour flat |
| 28 | `C.action[ACTION_HARVEST][0]` | Idle raised |
| 29 | `C.action[ACTION_HARVEST][1]` | Active orange raised |
| 30 | `C.action[ACTION_HARVEST][2]` | Pressed idle-colour flat |
| 31 | `C.action[ACTION_RETURN][0]` | Idle raised |
| 32 | `C.action[ACTION_RETURN][1]` | Active orange raised |
| 33 | `C.action[ACTION_RETURN][2]` | Pressed idle-colour flat |
| 34 | `C.action[ACTION_STOP][0]` | Idle raised |
| 35 | `C.action[ACTION_STOP][1]` | Active orange raised |
| 36 | `C.action[ACTION_STOP][2]` | Pressed idle-colour flat |
| 37 | `C.action[ACTION_AMBUSH][0]` | Idle raised |
| 38 | `C.action[ACTION_AMBUSH][1]` | Active orange raised |
| 39 | `C.action[ACTION_AMBUSH][2]` | Pressed idle-colour flat |
| 40 | `C.action[ACTION_SABOTAGE][0]` | Idle raised |
| 41 | `C.action[ACTION_SABOTAGE][1]` | Active orange raised |
| 42 | `C.action[ACTION_SABOTAGE][2]` | Pressed idle-colour flat |
| 43 | `C.action[ACTION_DIE][0]` | Idle raised |
| 44 | `C.action[ACTION_DIE][1]` | Active orange raised |
| 45 | `C.action[ACTION_DIE][2]` | Pressed idle-colour flat |
| 46 | `C.action[ACTION_HUNT][0]` | Idle raised |
| 47 | `C.action[ACTION_HUNT][1]` | Active orange raised |
| 48 | `C.action[ACTION_HUNT][2]` | Pressed idle-colour flat |
| 49 | `C.action[ACTION_DEPLOY][0]` | Idle raised |
| 50 | `C.action[ACTION_DEPLOY][1]` | Active orange raised |
| 51 | `C.action[ACTION_DEPLOY][2]` | Pressed idle-colour flat |
| 52 | `C.action[ACTION_DESTRUCT][0]` | Idle raised |
| 53 | `C.action[ACTION_DESTRUCT][1]` | Active orange raised |
| 54 | `C.action[ACTION_DESTRUCT][2]` | Pressed idle-colour flat |

## Complete repair/upgrade/cancel buttons: 14

Repair has two variants with its special idle caption colour (logical index239).
The other four labels have the same three-state convention as command buttons.
These are complete fragments, not captions followed by separate frame draws.

| ID | Asset | Caption/state | Shape |
|---|---|---|---|
| 55 | `C.repair[0]` | Repair, idle raised | Command/repair/upgrade button |
| 56 | `C.repair[1]` | Repair, pressed flat with idle colour | Command/repair/upgrade button |
| 57 | `C.repairing[0]` | Repairing, idle raised | Command/repair/upgrade button |
| 58 | `C.repairing[1]` | Repairing, active orange raised | Command/repair/upgrade button |
| 59 | `C.repairing[2]` | Repairing, pressed idle-colour flat | Command/repair/upgrade button |
| 60 | `C.upgrade[0]` | Upgrade, idle raised | Command/repair/upgrade button |
| 61 | `C.upgrade[1]` | Upgrade, active orange raised | Command/repair/upgrade button |
| 62 | `C.upgrade[2]` | Upgrade, pressed idle-colour flat | Command/repair/upgrade button |
| 63 | `C.upgrading[0]` | Upgrading, idle raised | Command/repair/upgrade button |
| 64 | `C.upgrading[1]` | Upgrading, active orange raised | Command/repair/upgrade button |
| 65 | `C.upgrading[2]` | Upgrading, pressed idle-colour flat | Command/repair/upgrade button |
| 66 | `C.cancel[0]` | Cancel, idle raised | Cancel button |
| 67 | `C.cancel[1]` | Cancel, active orange raised | Cancel button |
| 68 | `C.cancel[2]` | Cancel, pressed idle-colour flat | Cancel button |

## Production caption and percentage-background strips: 18

The seven static production labels each have raised and flat-bottom-strip
variants. These are not 37-row copies of the whole production face: the
shared face is IDs6-7. Object portraits/icons and construction-footprint
decorations are drawn separately.

Array index is `stringID - STR_PLACE_IT`; index0 is raised and index1 is flat.
Place It keeps its special caption colour. Other production captions use their
normal colour in both variants; there is no orange pressed variant.

| ID | Asset | Caption/state | Shape |
|---|---|---|---|
| 69 | `C.production[0][0]` | Place It, raised | Production caption/bottom strip |
| 70 | `C.production[0][1]` | Place It, flat | Production caption/bottom strip |
| 71 | `C.production[1][0]` | Completed, raised | Production caption/bottom strip |
| 72 | `C.production[1][1]` | Completed, flat | Production caption/bottom strip |
| 73 | `C.production[2][0]` | On Hold, raised | Production caption/bottom strip |
| 74 | `C.production[2][1]` | On Hold, flat | Production caption/bottom strip |
| 75 | `C.production[3][0]` | Build It, raised | Production caption/bottom strip |
| 76 | `C.production[3][1]` | Build It, flat | Production caption/bottom strip |
| 77 | `C.production[4][0]` | Launch, raised | Production caption/bottom strip |
| 78 | `C.production[4][1]` | Launch, flat | Production caption/bottom strip |
| 79 | `C.production[5][0]` | Fremen, raised | Production caption/bottom strip |
| 80 | `C.production[5][1]` | Fremen, flat | Production caption/bottom strip |
| 81 | `C.production[6][0]` | Saboteur, raised | Production caption/bottom strip |
| 82 | `C.production[6][1]` | Saboteur, flat | Production caption/bottom strip |
| 83 | `C.productionPercent[0]` | Empty ordinary-percentage band, raised | Ordinary production percentage background |
| 84 | `C.productionPercent[1]` | Empty ordinary-percentage band, flat | Ordinary production percentage background |
| 85 | `C.productionUpgradePercent[0]` | Empty upgrade-percentage band, raised | Upgrade-percentage background |
| 86 | `C.productionUpgradePercent[1]` | Empty upgrade-percentage band, flat | Upgrade-percentage background |

IDs83-86 contain no percentage glyphs. Each numeric update restores the
appropriate strip and then merges live text, including when the digit count
shrinks. Percentage-only updates retain the shared face and object images.

## What is not one of these 86 assets

- Unit/structure portraits and production icons: decoded on demand into the
  separate sidebar sprite storage, not baked into the static bank.
- Construction-footprint sprites24 and63: separate sprite submissions, not
  additional static-bank descriptors.
- Variable health fill: a parameterized CPU command, not a stored image.
- Unit/structure names, percentages, countdowns, numerical statistics and
  blinking target/placement prompts: ordered live text, not pre-generated
  variants for every possible value.
- Viewport terrain, units, projectiles and effects: separate backend/storage.
- Chunky chrome/button templates and per-asset staging buffers: temporary
  preparation workspace, released after the final bank is packed.

## Preparation and lifetime

Original chunky primitives render the elements in a preserved `SCREEN_1`
workspace. A static chrome template and reusable button template avoid
repainting the same decoration for every caption. Each asset is captured once
and converted once through `Video_Atari_EncodePlanarStrided()`. Geometry supplies
opaque coverage; masked members use explicit frame/sprite/glyph coverage.

Prepared pixel blocks are temporarily staged while the exact packed bank size
is accumulated. They are then copied into the bank and each final BLITTER
command is compiled once. There is no second rendering/conversion pass.
Preparation restores `SCREEN_1`, the active screen and GUI text/routing state.

Preload runs after publishing interface chrome, before the native sidebar and
viewport are drawn. The current interface-rebuild path still calls preload
unconditionally. Ordinary health/button/percentage updates reuse the bank.
Palette-generation changes or resource/interface rebuilding can replace it.

## Why command playback measures about 0.224 ms

The capture107 command recipe has BLITTER X_COUNT16 and Y_COUNT12:
16 planar words per row x12 rows =192 words, or384 bytes.
An opaque copy reads each source word and writes each destination word.

At approximately four cycles per word bus access:

```
192 words x (4 source-read cycles + 4 destination-write cycles) = 1536 cycles
```

At the profile's 8,021,247 cycles/second this is about0.1915 ms. Register setup,
launch/arbitration, NOP and return bring the sampled recipe to about1795 cycles,
or0.224 ms. A 64x14 rectangle instead contains224 words and would need about
1792 data-transfer cycles before setup overhead.

The 0.224 ms figure is generated-copy playback, not the complete GUI callback
or command-queue cost. There is no c2p conversion during that playback.
