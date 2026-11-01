/** @file src/gui/planar.c Write-only planar drawing primitives (TOS). */

#include "types.h"
#include "planar.h"

enum { PLANAR_MAX_GROUPS = 20 };

void Planar_SolidGroup(uint16 group[4], uint8 pen)
{
	uint16 plane;

	for (plane = 0; plane < 4; plane++) group[plane] = (uint16)-(int16)((pen >> plane) & 1);
}

#ifndef __mc68000__
/* The 68000 build uses planar_rows.s; this C version is the reference for the host test. */
static void Planar_FillRows(uint16 *dst, const uint16 *pattern, long strideBytes, long rows, long groups)
{
	for (; rows > 0; rows--, dst = (uint16 *)((uint8 *)dst + strideBytes)) {
		long i;
		for (i = 0; i < groups * 4; i++) dst[i] = pattern[i];
	}
}

/* One group word per plane: `base` outside `span`, and inside it up to three colour classes. */
static void Planar_Word(uint16 *out, const uint16 *base, uint16 span, const uint16 masks[3], const uint16 *const cls[3])
{
	uint16 plane;

	for (plane = 0; plane < 4; plane++) {
		out[plane] = (base[plane] & ~span)
		    | (masks[0] & cls[0][plane])
		    | (masks[1] & cls[1][plane])
		    | (masks[2] & cls[2][plane]);
	}
}

void Planar_DrawBorder(uint16 *dst, uint16 stride, uint16 x, uint16 width, uint16 height, const uint16 groups[16])
{
	uint16 pattern[3][PLANAR_MAX_GROUPS][4];
	const long strideBytes = (long)stride * 2;
	const uint16 *fill = groups, *bottomRight = groups + 4, *topLeft = groups + 8, *corner = groups + 12;
	uint16 x1 = x + width - 1, g0 = x >> 4, g1 = x1 >> 4, group, count = g1 - g0 + 1;

	/* Only the first and last group mix in the sampled margin; groups between them are pure class fills. */
	for (group = g0; group <= g1; group += g1 > g0 ? g1 - g0 : 1) {
		const uint16 *base = dst + stride + group * 4;
		uint16 a = x > group * 16 ? x - group * 16 : 0;
		uint16 b = x1 < group * 16 + 15 ? x1 - group * 16 : 15;
		uint16 span = (0xffffu >> a) & (0xffffu << (15 - b));
		uint16 edgeL = g0 == group ? (uint16)(0x8000u >> (x & 15)) : 0;
		uint16 edgeR = g1 == group ? (uint16)(0x8000u >> (x1 & 15)) : 0;
		uint16 masks[3];
		const uint16 *cls[3];

		/* top: topLeft, right corner */
		masks[0] = span & ~edgeR; masks[1] = edgeR; masks[2] = 0;
		cls[0] = topLeft; cls[1] = corner; cls[2] = fill;
		Planar_Word(pattern[0][group - g0], base, span, masks, cls);
		/* interior: left topLeft, right bottomRight, fill between */
		masks[0] = span & ~(edgeL | edgeR); masks[1] = edgeL; masks[2] = edgeR;
		cls[0] = fill; cls[1] = topLeft; cls[2] = bottomRight;
		Planar_Word(pattern[1][group - g0], base, span, masks, cls);
		/* bottom: bottomRight, left corner */
		masks[0] = span & ~edgeL; masks[1] = edgeL; masks[2] = 0;
		cls[0] = bottomRight; cls[1] = corner; cls[2] = fill;
		Planar_Word(pattern[2][group - g0], base, span, masks, cls);
	}
	if (count > 2) {
		const uint16 *mid[3] = { topLeft, fill, bottomRight };
		uint16 type;

		for (type = 0; type < 3; type++) {
			for (group = 1; group < count - 1; group++) {
				uint16 *out = pattern[type][group];
				out[0] = mid[type][0]; out[1] = mid[type][1]; out[2] = mid[type][2]; out[3] = mid[type][3];
			}
		}
	}
	dst += g0 * 4;
	Planar_FillRows(dst, pattern[0][0], strideBytes, 1, count);
	Planar_FillRows(dst + stride, pattern[1][0], strideBytes, height - 2, count);
	Planar_FillRows(dst + (height - 1) * stride, pattern[2][0], strideBytes, 1, count);
}
#endif
