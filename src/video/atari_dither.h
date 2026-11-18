/** @file src/video/atari_dither.h Shared asset-relative output-pen patterns. */

#ifndef VIDEO_ATARI_DITHER_H
#define VIDEO_ATARI_DITHER_H

#include "types.h"

typedef uint8 AtariDitherPattern[4][4];

/* Phase-major preparation form; no palette data is duplicated by including this header. */
typedef struct AtariDitherLookup {
	uint8 pens[4][4][256];
	bool flat; /* Conservative hint: all colours are independent of phase. */
} AtariDitherLookup;

typedef struct AtariDitherSource {
	const uint8 *pixels;
	uint16 width, height, stride; /* Logical dimensions and byte stride. */
	int16 originX, originY;
	int8 stepX, stepY; /* +1/-1 source-coordinate direction, not memory increments. */
} AtariDitherSource;

typedef struct AtariDitherTarget {
	uint8 *pixels;
	uint16 stride; /* Bytes per physical output row. */
	uint8 scale;   /* 1 for colour, 2 for expanded mono pens. */
} AtariDitherTarget;

extern void Video_Atari_DitherPrepareLookup(AtariDitherLookup *lookup,
	const AtariDitherPattern patterns[256]);
/* Replace one colour's entire pattern with a constant output pen (0..15).
 * Initialize through DitherPrepareLookup or zero-initialize before updates.
 * Incremental updates preserve, but never promote, the conservative flat hint. */
extern void Video_Atari_DitherSetPen(AtariDitherLookup *lookup, uint8 colour, uint8 pen);

/* Sample resolved palette indices into output pens, without packing bitplanes
 * or inferring opacity. Colour zero is an ordinary colour.
 *
 * originX/Y are stable asset coordinates of the first supplied logical pixel.
 * Adjust them for crops; never use destination screen coordinates. Input rows
 * and pixels are always read forwards; negative steps describe already-flipped
 * input and also mirror the subpixels within an expanded cell.
 *
 * Source and target must not overlap. Dimensions are nonzero and strides cover
 * their row widths. Only width*scale bytes in height*scale rows are written;
 * target row padding is untouched. Sampling is modulo four in both axes.
 * Splitting work into bands requires advancing the source origin as well. */
extern void Video_Atari_PreparePens(const AtariDitherSource *source,
	const AtariDitherLookup *lookup, const AtariDitherTarget *target);

#endif
