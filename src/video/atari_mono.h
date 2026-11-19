/** @file src/video/atari_mono.h Source-anchored 2x monochrome asset preparation. */

#ifndef VIDEO_ATARI_MONO_H
#define VIDEO_ATARI_MONO_H

#include "atari_dither.h"

/* Four words: top-left/right, then bottom-left/right physical spans. */
extern void Video_Atari_MonoPenWords(uint8 pen, int16 x, int16 y, uint16 words[4]);

/* Each byte holds TL, TR, BL, BR in bits 3..0, indexed by source parity/colour. */
typedef struct AtariMonoLookup {
	uint8 cells[2][2][256];
} AtariMonoLookup;

/* Two-bit top/bottom cells in the high/low words, ready for shift-and-OR packing. */
typedef struct AtariMonoPackedLookup {
	uint32 cells[2][2][256];
} AtariMonoPackedLookup;

extern void Video_Atari_MonoPreparePackedLookup(AtariMonoPackedLookup *lookup,
	const AtariDitherLookup *dither, uint16 first, uint16 count, bool whiteIsOne);

/* Native output uses logical row-pair strides; padding to 16 logical pixels is zero. */
extern void Video_Atari_MonoPackNative(const AtariDitherSource *source,
	const AtariMonoPackedLookup *lookup, uint16 *pixels, uint16 stride);

typedef struct AtariMonoSource {
	const uint8 *pixels;
	const uint16 *opacity;
	uint16 width, height;
	uint16 pixelStride;   /* Bytes per logical row. */
	uint16 opacityStride; /* Words per logical row; ignored when opacity is NULL. */
	int16 originX, originY;
} AtariMonoSource;

typedef struct AtariMonoBitmap {
	uint16 *pixels;
	uint16 *opacity;
	uint16 stride; /* Words per physical row, for both buffers. */
} AtariMonoBitmap;

/* Compile a selected mono policy/palette once, not once per asset.
 * Pattern values must be semantic black=0/white=1. whiteIsOne selects the
 * hardware polarity without changing opacity or adding per-pixel inversion. */
extern void Video_Atari_MonoPrepareLookup(AtariMonoLookup *lookup,
	const AtariDitherPattern patterns[256], bool whiteIsOne);

/* Input pixels are resolved palette indices, not packed bits. Each emits a 2x2
 * cell, giving 2*width pixels in 2*height rows. Width/height must be nonzero;
 * no group alignment is required. Each row uses ceil(width/8) native uint16
 * words, MSB leftmost; unused low bits of the final word are zero.
 *
 * originX/Y are stable logical asset coordinates of the first input pixel,
 * including crop offsets, never destination coordinates. Apply flips to the
 * prepared bitmap if its texture should mirror with the source.
 *
 * Source opacity is an independent MSB-first logical bitmap; NULL means all
 * valid pixels are opaque, including colour zero. Each source bit expands to
 * a 2x2 opacity cell. Output opacity is required for masked input, optional
 * otherwise. Transparent output pixels are zero regardless of white polarity.
 *
 * Pixel and opacity output buffers must be word-aligned, nonoverlapping, and
 * separate from input/lookup storage. Stride padding beyond the final word is
 * untouched. This prepares assets; it does not merge them into a screen. */
extern void Video_Atari_MonoPack(const AtariMonoSource *source,
	const AtariMonoLookup *lookup, const AtariMonoBitmap *target);

/* Pack already phase-sampled physical pixels (0/1) into native mono words. */
extern void Video_Atari_MonoPackPens(const uint8 *pens, uint16 *pixels,
	uint16 width, uint16 height, uint16 srcStride, uint16 dstStride, bool whiteIsOne);

/* Native surfaces use a word stride per pair of physical rows. A logical
 * 16-pixel group has two words in each physical row, not four bitplanes. */
extern void Video_Atari_MonoReadGroup(const uint16 *pixels, uint16 stride,
	uint16 row, uint16 group, uint16 words[4]);
extern void Video_Atari_MonoWriteGroup(uint16 *pixels, uint16 stride,
	uint16 row, uint16 group, const uint16 words[4]);
extern void Video_Atari_MonoMaskWords(uint16 mask, uint16 words[4]);
extern void Video_Atari_MonoOutline(uint16 *pixels, const uint16 *masks,
	uint16 width, uint16 height, bool outlineIsOne);
extern void Video_Atari_MonoComposeTile(const uint16 *pixels, const uint16 *masks,
	const uint16 *overlay, const uint16 *overlayMasks, uint16 *result, uint16 *resultMasks);
extern void Video_Atari_MonoMergeWords(uint16 dst[4], const uint16 pixels[4], uint16 mask);
extern uint16 Video_Atari_MonoReadMask(const uint16 *masks, uint16 width,
	uint16 row, int16 x, bool expanded);
extern void Video_Atari_MonoReadSpan(const uint16 *pixels, uint16 stride,
	uint16 row, int16 x, uint16 words[4]);
extern void Video_Atari_MonoMaskBitmap(uint16 *pixels, uint16 *expanded,
	const uint16 *compact, uint16 width, uint16 height);
extern void Video_Atari_MonoCompose(uint16 *dst, uint16 dstStride,
	uint16 *dstMasks, uint16 dstMaskStride, uint16 dstWidth, uint16 dstHeight,
	const uint16 *pixels, const uint16 *masks, uint16 width, uint16 height, int16 x, int16 y);

#endif
