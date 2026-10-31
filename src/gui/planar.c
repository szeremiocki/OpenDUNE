/** @file src/gui/planar.c Write-only planar drawing primitives (TOS). */

#include "types.h"
#include "planar.h"

enum { PLANAR_MAX_GROUPS = 20 };

/* One group word per plane: `base` outside `span`, and inside it up to three colour classes. */
static void Planar_Word(uint16 *out, const uint16 *base, uint16 span, const uint16 masks[3], const uint8 pens[3])
{
	uint16 plane, i;

	for (plane = 0; plane < 4; plane++) {
		uint16 word = base[plane] & ~span;
		for (i = 0; i < 3; i++) if (pens[i] & (1 << plane)) word |= masks[i];
		out[plane] = word;
	}
}

void Planar_DrawBorder(uint16 *dst, uint16 stride, uint16 x, uint16 width, uint16 height, const uint8 pens[4])
{
	uint16 pattern[3][PLANAR_MAX_GROUPS][4];
	uint16 x1 = x + width - 1, g0 = x >> 4, g1 = x1 >> 4, group, row, type;

	for (group = g0; group <= g1; group++) {
		const uint16 *base = dst + stride + group * 4;
		uint16 a = x > group * 16 ? x - group * 16 : 0;
		uint16 b = x1 < group * 16 + 15 ? x1 - group * 16 : 15;
		uint16 span = (0xffffu >> a) & (0xffffu << (15 - b));
		uint16 edgeL = g0 == group ? (uint16)(0x8000u >> (x & 15)) : 0;
		uint16 edgeR = g1 == group ? (uint16)(0x8000u >> (x1 & 15)) : 0;
		uint16 masks[3];
		uint8 classPens[3];

		/* top: pens[2], right corner pens[3] */
		masks[0] = span & ~edgeR; masks[1] = edgeR; masks[2] = 0;
		classPens[0] = pens[2]; classPens[1] = pens[3]; classPens[2] = 0;
		Planar_Word(pattern[0][group], base, span, masks, classPens);
		/* interior: left pens[2], right pens[1], fill pens[0] between */
		masks[0] = span & ~(edgeL | edgeR); masks[1] = edgeL; masks[2] = edgeR;
		classPens[0] = pens[0]; classPens[1] = pens[2]; classPens[2] = pens[1];
		Planar_Word(pattern[1][group], base, span, masks, classPens);
		/* bottom: pens[1], left corner pens[3] */
		masks[0] = span & ~edgeL; masks[1] = edgeL; masks[2] = 0;
		classPens[0] = pens[1]; classPens[1] = pens[3]; classPens[2] = 0;
		Planar_Word(pattern[2][group], base, span, masks, classPens);
	}
	for (row = 0; row < height; row++) {
		uint16 *d = dst + row * stride + g0 * 4;
		type = row == 0 ? 0 : (row == height - 1 ? 2 : 1);
		for (group = g0; group <= g1; group++, d += 4) {
			d[0] = pattern[type][group][0]; d[1] = pattern[type][group][1];
			d[2] = pattern[type][group][2]; d[3] = pattern[type][group][3];
		}
	}
}
