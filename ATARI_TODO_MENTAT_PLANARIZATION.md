# Further ST/STE Mentat planarization

## Current baseline

The picture loop opts into native WSA recordings through
`WSA_LoadFile(..., allowPlanar)`. Standalone PWS files retain the initial
planar image and native skip/XOR transitions between visits and sessions.
Playback has no WSA decompression, quantization or c2p. Original PAK files
are unchanged; remove PWS files manually when testing changed mappings.

The description/shoulder overlay is converted through the shared encoder
when its visible line count changes. Eyes, mouth and book sprites still
decode to chunky scratch and use the C transparent presenter. Initial
background composition, the subject list and spoken text also retain
chunky rendering paths.

Prefer expanding correct native rendering over adding repairs which hide
chunky fallback deficiencies. The book fits the 4,608-byte direct sprite
scratch buffer; the Mentat-specific overlap guard has been removed.

## Persistent planar Mentat sprites

- Add an explicit preparation flag to sprite collection loading, initially
  enabling only the Mentat SHP collections.
- Store independent planar images and opacity masks in standalone companion
  files. Sprites do not need WSA-style reversible inter-frame XOR history.
- Build masks from actual sprite opacity, before palette mapping: opaque
  logical colour 0 must not become a transparent hole.
- Recode through `Video_Atari_EncodePlanar`/the shared palette-mapping encoder,
  not an independent converter, so future dithering reaches these assets.
- `Sprites_Init()` precedes IBM.PAL setup. Defer cache-miss preparation until
  the authoritative mapping is ready, or explicitly arrange that ordering.
- Initially retain originals for existing chunky composition, such as the
  shoulder drawn into SCREEN_1. Associate native versions with the same
  sprites and select them for supported planar destinations.
- Preserve clipping, unaligned X placement and cursor-background updates.
  Avoid silently routing unsupported native draws through legacy fallbacks.

## Subject list as a planar composition

`GUI_Mentat_Draw()` rebuilds the background, title, shoulder, eleven labels,
scrollbar and arrows in SCREEN_1, then converts the whole 184x112 widget.
Scrolling takes this path; selection changes already redraw only the old
and new selected rows.

Keep the input/widget logic and existing text renderer. Cache the static
panel layers and prepared normal/selected label appearances, then compose
visible rows and controls in a retained planar buffer. Publish changed
regions together rather than visibly drawing each glyph/widget separately.

Use bounded/lazy label caching if preparing the whole catalog consumes too
much RAM. Preserve indentation for headings, font state, selection colours,
the scrollbar, and the shoulder overlapping lower rows. A one-row scroll
may reuse surviving native rows and prepare only the newly exposed row.

## Shared transparent conversion and text

The C transparent presenter currently uses `s_palette4BitMap` directly.
Assembly-only dithering would not affect it. Separate opacity from colour
conversion: padded/aligned chunky input, an opacity mask, the shared planar
encoder, then masked publication. Convert rectangles in batches, not by
invoking assembly once per tiny group.

Later, prepared font/glyph or complete text-strip caches can remove
conversion from spoken text and labels. Define dither origin/phase
consistently across backgrounds, WSA recordings, sprites and glyphs.

## Suggested progression

1. Preserve the working native WSA path while adapting intro/cutscene
   callers and their continuation/fade dependencies.
2. Add prepared Mentat sprite collections.
3. Replace full chunky subject-list rebuilding with native composition.
4. Move remaining text/background composition to shared prepared assets.

Measure first-use preparation, cache-hit loading, redraw costs and RAM
separately. Keep original/non-ST behavior available through explicit opt-out.
