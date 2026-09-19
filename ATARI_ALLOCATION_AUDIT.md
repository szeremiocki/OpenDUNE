# Atari ST/STE allocation audit

Date: 2026-09-19. Audio rows updated after direct ST-RAM playback implementation.
Other source locations refer to the working tree at the time of the audit.

## Summary and scope

Almost all game allocations are eligible for CPU-addressable Alt/TT RAM.
The important exceptions are retained audio samples and the conversion/
on-demand DMA sound buffer. The ST/STE planar
screen must also remain in ST-RAM, but the game currently reuses TOS's
screen rather than allocating one.

The game uses ordinary library `malloc`, `calloc` and `realloc` extensively.
The tables below inventory application-level allocation callsites relevant
to the ST/STE TOS build. Other-platform backends and build tools are excluded;
Falcon's two screen-allocation calls are noted for contrast. A callsite may
produce many simultaneous allocations. Allocations internal to libc (for
example stdio buffers) are not individually inventoried.

The local build uses MiNTLib. Its heap can obtain memory through GEMDOS
`Malloc`; the inspected executable had PRG flags `0x7`, including TT-load
and TT-allocation flags. These permit/prefer alternate memory on supporting
systems, but do not guarantee every allocation lands there.

## Classification

- **Alt: Yes**: CPU accesses only; no identified hardware restriction.
- **Alt: I/O**: CPU-accessible storage also used for file reads/writes.
  Eligible when the installed OS/disk driver supports Alt-RAM buffers.
- **Alt: No**: directly consumed by hardware requiring ST-RAM.
- **Static: Good**: bounded storage with straightforward ownership changes.
- **Static: Conditional**: requires an explicit capacity, pool, or
  lifetime/reentrancy design.

All Alt-RAM conclusions assume the memory is addressable by the actual CPU
and expansion hardware. A plain 68000 cannot acquire a wider address bus
merely because C pointers are 32 bits.

**Static does not mean ST-RAM.** Ordinary global/BSS arrays follow program
placement. If the executable loads into Alt-RAM, its static arrays generally
do too. Replacing `Mxalloc(..., MX_STRAM)` with an ordinary global array
would lose the DMA buffer's placement guarantee.

Static conversion also requires removing or adapting matching `free` and
`realloc` operations, preserving alignment, and reproducing `calloc`'s
initialization on reinitialization paths. BSS is zeroed at process startup,
not each time a subsystem is initialized.

## 1. TOS allocations and physical screen

| Allocation / resource | Current size and allocator | Alt-RAM | Static-array assessment |
|---|---|---|---|
| Conversion/on-demand playback scratch, `src/audio/dsp_atari.c`, `DSP_Init` | 32,768 bytes, `Mxalloc(..., MX_STRAM)`; allocated once, released with `Mfree` | No | Also directly played for non-preloaded speech; retain explicit ST-RAM allocation. Ordinary BSS is unsuitable for an Alt-loaded program. |
| ST/STE physical screen, `src/video/video_atari.c`, video initialization | Existing TOS screen via `Logbase()`/`Physbase()`; no game allocation | No | An owned static screen requires ST-RAM placement, alignment and screen-base restoration. It would add roughly 32 KB rather than reuse the current screen. |
| Falcon physical screen, `src/video/video_atari.c:917,970` | Two `Srealloc` callsites: establish game screen and restore desktop screen | Hardware-constrained | Outside ST/STE scope; leave under the OS screen-allocation mechanism. |
| Largest-free-block diagnostic, `src/sprites.c:228` | `Malloc(-1L)` | N/A | Query only, not an allocation. |

No application-owned disk-DMA allocation was identified. OpenDUNE file
reading goes through the file/OS layer rather than programming the disk DMA
controller directly.

### Disk reads do not automatically make an application buffer ST-only

The hardware transfer buffer must be DMA-accessible; that need not be the
application's destination buffer.

The upstream EmuTOS implementation inspected for this audit uses intermediate
ST-RAM buffers for:

- [ACSI transfers](https://github.com/emutos/emutos/blob/master/bios/acsi.c)
  when the user buffer is outside ST-RAM or unaligned.
- [Normal floppy reads/writes](https://github.com/emutos/emutos/blob/master/bios/floppy.c)
  under the same conditions.

File-backed allocations below are valid Alt-RAM candidates with that
implementation. This does not establish compatibility with every original
TOS, third-party disk driver, or the exact EmuTOS version installed on the
target. That is a remaining platform qualification, not a reason to pin
all assets in ST-RAM.

## 2. Screen buffers, tiles and cursor caches

Paths in the following tables are relative to `src/`.

| Allocation site | Allocator, size and lifetime | Alt-RAM | Static-array assessment |
|---|---|---|---|
| `video/video_atari.c:891`, chunky framebuffer | `calloc`, 65,280 bytes (`320*204`), video lifetime | Yes, with I/O qualification where used as file/decode scratch | Good. One fixed array; preserve word/longword alignment and remove its `free`. Not the physical planar screen. |
| `gfx.c:412`, remaining screen buffers | One `calloc` block partitioned into the other logical screens | I/O | Good. Existing capacities are fixed. Preserve distinct storage and aliases; SCREEN_2 is also script/menu scratch. |
| `gfx.c:653`, decoded tile pixels | `malloc(decodedSize)`, rebuilt when tiles load | Yes | Conditional. Establish maximum tile count/geometry. A permanent maximum cache loses the current ability to fall back when allocation fails. |
| `gfx.c:654`, tile transparency flags | `malloc(s_tileCount)` | Yes | Conditional, but simple once tile capacity is established. |
| `sprites.c:266`, tile pixel data | `calloc(1, tilesDataLength)`; file read and in-place decoding | I/O | Conditional. Accommodate both the loaded chunk and decoder storage requirements. |
| `sprites.c:278`, `g_iconRTBL` | `calloc(1, tableLength)` | I/O | Conditional. Validate the maximum asset-table size. |
| `sprites.c:283`, `g_iconRPAL` | `calloc(1, paletteLength)` | I/O | Conditional. CPU-side logical tile palette, not hardware register storage. |
| `sprites.c:309` via `File_ReadWholeFileLE16`, `g_iconMap` | File-sized allocation owned until replacement/uninitialization | I/O | Conditional. Bound map size; the generic helper must still support independently owned results. This is an instance of the helper allocation, not an additional allocator callsite. |
| `video/video_atari.c:1244`, cursor phase pixels | `malloc(8 * height * groups)` per icon/phase; 7 icons times 16 phases possible | Yes | Conditional. A packed arena based on validated cursor dimensions is plausible; broad worst-case rectangular arrays waste RAM. |
| `video/video_atari.c:1245`, cursor phase masks | `malloc(2 * height * groups)` per icon/phase | Yes | Same as cursor pixels; plan capacities together. |
| `video/video_atari.c:1335`, temporary cursor-background backup | `malloc(width * height)`, freed during preload; accepted dimensions bound it at 20,480 bytes | Yes | Conditional. Static scratch works only if rebuilds cannot nest. Reserving the broad maximum permanently may be wasteful. |
| `sprites.c:440`, mouse-background buffer | `realloc`, capacity follows cursor dimensions | Yes | Conditional. Validate maximum geometry and clipping requirements. |
| `sprites.c:448`, current mouse sprite | `realloc`, capacity follows sprite storage size | Yes | Conditional. Bound its stored representation, not just its visible rectangle. |

Cursor caches contain planar-format data but are not hardware screen
buffers: the CPU reads them and writes the real screen. They can live in
Alt-RAM. Similarly, c2p reads chunky pixels and lookup tables using ordinary
CPU instructions; only its physical screen destination requires ST-RAM.

## 3. Sound and MIDI

| Allocation site | Allocator, size and lifetime | Alt-RAM | Static-array assessment |
|---|---|---|---|
| `audio/driver.c:131`, sound sequencer state | Four `calloc` allocations, each `MPU_GetDataSize()` = `sizeof(MSData)` | Yes | Good. Four correctly aligned typed objects, preferably owned within the MPU module rather than duplicating its private layout. |
| `audio/driver.c:136`, music sequencer state | One `calloc(sizeof(MSData))` | Yes | Good. Same ownership approach. MIDI output sends bytes; hardware does not DMA these objects. |
| `audio/driver.c:265`, `s_voiceLoadBuffer` | `realloc`; raw VOC file size rounded up to 4 KB, grows as needed | I/O | Conditional. Requires a verified maximum raw input size. The 32 KB output limit does not establish a 32 KB input limit. |
| `audio/sound.c`, `Sound_LoadVoc`, retained voice data | TOS: `DSP_AllocSample` -> `Mxalloc(..., MX_STRAM)` per converted VOC, bounded by 32 KB scratch; `DSP_FreeSample` -> `Mfree`. Other backends retain `malloc/free`. | No on TOS | Conditional; an arena must be explicitly ST-RAM allocated, not ordinary BSS. Many differently sized voices coexist. |

DMA now reads resident VOC payloads directly. The DSP stops playback before
freeing its active resident source; conversion scratch is stopped before
reuse and also serves non-preloaded speech. Raw input scratch is still
CPU/file-I/O-only. See `ATARI_TODO_VOC_RESAMPLING.md`.

## 4. Palettes and strings

| Allocation site | Allocator / size | Alt-RAM | Static-array assessment |
|---|---|---|---|
| `opendune.c:935`, gameplay `g_palette1` | `calloc`, 768 bytes | I/O | Good, but coordinate with the cutscene allocation of the same palette storage. |
| `opendune.c:937`, `g_palette2` | `calloc`, 768 bytes | Yes/I/O depending on use | Good, with shared lifecycle cleanup adjusted. |
| `cutscene.c:812`, palette bank | `calloc`, 7,680 bytes (`10*768`) | I/O | Good structurally. A permanent maximum bank costs more outside cutscenes than the smaller gameplay allocation. Do not count these as unrelated palette objects. |
| `cutscene.c:814`, secondary palette | `malloc`, 768 bytes | Yes/I/O | Good, coordinating with gameplay initialization/freeing. |
| `opendune.c:950`, mapping 1 | `malloc`, 256 bytes | Yes | Good. |
| `opendune.c:951`, mapping 2 | `malloc`, 256 bytes | Yes | Good. |
| `opendune.c:1170`, `g_palette_998A` | `calloc`, 768 bytes | Yes | Good. |
| `string.c:173`, string offsets | `malloc(sizeof(uint16) * MAX_STRING_COUNT)` | Yes | Good. Already has a compile-time capacity. |
| `string.c:175`, character storage | `malloc(MAX_CHARACTER_COUNT)` | Yes | Good. Preserve capacity checks. |

These are CPU-side palettes. Passing color values to `Setcolor()` does not
make their storage DMA-visible.

## 5. Sprites, fonts, scripts and animations

| Allocation site | Allocator / ownership | Alt-RAM | Static-array assessment |
|---|---|---|---|
| `sprites.c:80,93`, sprite-pointer table | Two `realloc` callsites; grows with loaded sprite count | Yes | Conditional. A fixed pointer array is reasonable with an enforced maximum supported count. |
| `sprites.c:112`, decoded sprite | Per-sprite `malloc`, header-derived size plus optional palette | Yes | Conditional. Many variable-sized simultaneous objects; use a sized arena/pool rather than one reusable array. |
| `sprites.c:135`, retained packed sprite | Per-sprite `malloc`, SHP-header size | Yes | Same: independently owned, data-dependent objects. |
| `gui/font.c:78`, font descriptor | `calloc(sizeof(Font))` per loaded font | Yes | Conditional. Fixed descriptor pool if the set of simultaneously loaded fonts is bounded. |
| `gui/font.c:86`, character descriptors | `calloc`, character count times `sizeof(FontChar)` | Yes | Conditional. Fixed tables per resident font with validated glyph-count bounds. |
| `gui/font.c:101`, glyph pixels | Per-glyph `malloc(usedLines * width)` | Yes | Conditional. Prefer a packed font arena to worst-case storage for every glyph. |
| `script/script.c:645`, TEXT chunk | `calloc(length)` when no caller buffer is supplied | I/O | Conditional. Separate capacities for simultaneous scripts and correct ownership flags. |
| `script/script.c:664`, ORDR chunk | Same conditional allocation | I/O | Same; preserve alignment. |
| `script/script.c:687`, DATA chunk | Same conditional allocation | I/O | Same; preserve addresses expected by active script engines. |
| `wsa.c:278`, WSA object/buffers | `calloc(wsaSize)` when caller storage is not used; header/data-dependent size | I/O | Conditional; generally keep dynamic. Different sizes and overlapping lifetimes make a single static buffer unsafe. |

Scripts and WSA already support caller-provided storage. Mechanically
replacing their allocations with globals would break independent ownership
or overlapping lifetimes.

## 6. File helpers, configuration, widgets and timers

| Allocation site | Allocator / ownership | Alt-RAM | Static-array assessment |
|---|---|---|---|
| `file.c:343`, directory metadata | `malloc(sizeof(FileInfoLinkedElem) + filename length)` per entry | Yes | Conditional. Bounded node/string pool, not one singleton. |
| `file.c:372`, PAK metadata | `malloc(sizeof(PakFileInfoLinkedElem) + filename length)` per entry | Yes | Same, with maximum archive-entry count. |
| `file.c:934`, `File_ReadWholeFile` | `malloc(length + 1)`, ownership returned to caller | I/O | Not one shared static buffer. Callers retain results concurrently. Dedicated caller storage would need a different API. |
| `file.c:972`, `File_ReadWholeFileLE16` | `malloc(count * sizeof(uint16))`, caller-owned | I/O | Same. |
| `inifile.c:130`, configuration text | `malloc(fileSize + 1)`, singleton | I/O | Conditional. Introduce a maximum INI size and explicit oversized-input handling. |
| `gui/widget.c:567,674,729`, widgets | Three `calloc` callsites, independently owned objects | Yes | Conditional. Fixed pool needs peak concurrent count and coordinated release/reuse. |
| `gui/widget.c:701`, scrollbar state | `calloc(sizeof(WidgetScrollbar))` | Yes | Conditional. Small fixed pool or embedded storage in an appropriate widget type. |
| `gui/gui.c:823`, modal screen backup | `malloc(GFX_GetSize(...))`, freed after modal operation | Yes | Conditional. Establish maximum rectangle size and nesting before sharing static scratch. |
| `timer.c:315`, timer nodes | `realloc`, capacity grows in pairs | Yes | Good candidate after bounding registrations, with explicit overflow handling. |

Whole-file helpers account for additional instances, not additional
allocator callsites: scenario text, temporary sprite/font/string files and
the icon map obtain storage through them. Replacing the helper's heap
allocation with one global buffer would invalidate retained results.

## 7. Existing statics and pools

- `g_readBuffer`: already 32 KB BSS. CPU-side scratch, no longer used for
  TOS gameplay voice staging; not a DMA source.
- c2p pair-LUT: already static and CPU-read; Alt-RAM eligible.
- Cursor slow-path data, masks and saved background: already static and
  CPU-read/write; Alt-RAM eligible.
- Fixed game-object pools do not need heap-to-static conversion merely
  because their APIs are named "Allocate".

Existing shared buffers must not become general replacement scratch without
checking simultaneous use. SCREEN_2, for example, holds unit scripts that
menu backups overwrite; restoration and pointer stability remain necessary.

## Recommendations and remaining qualification

Best straightforward static candidates:

- Palette mappings and fixed palette storage with unified ownership.
- String tables.
- Five MIDI sequencer-state objects.
- A bounded timer array.

The chunky framebuffer and auxiliary screens are also fixed-size candidates,
but moving them to BSS changes startup memory commitment and prevents
independent heap placement.

Keep individual sprites, cached voices, WSA objects, glyph pixels, file
metadata and generic whole-file results dynamic unless measurements justify
a redesign. Static arenas are possible, but require capacity and ownership
design, not just declaration changes.

Keep all DMA sources explicitly ST-RAM allocated. Continue reusing
the TOS planar screen.

The remaining platform qualification is the installed OS/disk driver's
handling of Alt-RAM I/O buffers. Source inspection supports CPU asset
placement in Alt-RAM; it does not certify every firmware/driver combination.
No target allocation-address/I/O matrix or static-conversion measurements
were performed as part of this report.
