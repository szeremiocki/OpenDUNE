/** @file src/gui/glyph.c Planar glyph cell cache shared by the ST sidebar and the message banner. */

#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "types.h"
#include "glyph.h"
#include "font.h"
#include "../os/error.h"
#include "../os/math.h"
#include "../video/video.h"

enum { GLYPH_WAYS = 6 };

static GlyphCell *s_glyphs[256][GLYPH_WAYS];
static uint16 s_generation;

void GUI_Glyph_Free(void)
{
	uint16 i, way;

	for (i = 0; i < 256; i++) {
		for (way = 0; way < GLYPH_WAYS; way++) {
			free(s_glyphs[i][way]);
			s_glyphs[i][way] = NULL;
		}
	}
}

const GlyphCell *GUI_Glyph_Get(unsigned char c, const uint8 colours[16])
{
	const FontChar *fc = &g_fontCurrent->chars[c];
	GlyphCell *glyph = NULL;
	uint16 row, way, generation = Video_Atari_GetPaletteGeneration();

	assert(g_fontCurrent->height <= 16 && fc->width <= 16);
	if (generation != s_generation) {
		GUI_Glyph_Free();
		s_generation = generation;
	}
	for (way = 0; way < GLYPH_WAYS; way++) {
		glyph = s_glyphs[c][way];
		if (glyph != NULL && glyph->font == g_fontCurrent &&
		    memcmp(glyph->colours, colours, sizeof(glyph->colours)) == 0) break;
	}
	if (way == GLYPH_WAYS) {
		union { uint32 align; uint8 bytes[16 * 16]; } chunky;
		way = GLYPH_WAYS - 1;
		glyph = s_glyphs[c][way];
		if (glyph == NULL) {
			glyph = malloc(sizeof(*glyph));
			if (glyph == NULL) {
				Error("Out of memory for glyph %u\n", c);
				exit(1);
			}
			s_glyphs[c][way] = glyph;
		}
		glyph->font = g_fontCurrent;
		memcpy(glyph->colours, colours, sizeof(glyph->colours));
		memset(chunky.bytes, 0, sizeof(chunky.bytes));
		memset(glyph->masks, 0, sizeof(glyph->masks));
		for (row = 0; row < g_fontCurrent->height; row++) {
			uint16 column;
			for (column = 0; column < fc->width; column++) {
				uint8 colour = colours[0];
				if (row >= fc->unusedLines && row < fc->unusedLines + fc->usedLines)
					colour = colours[fc->data[(row - fc->unusedLines) * fc->width + column] & 15];
				chunky.bytes[row * 16 + column] = colour;
				if (colour != 0) glyph->masks[row] |= 0x8000u >> column;
			}
		}
		Video_Atari_EncodePlanar(chunky.bytes, glyph->pixels, 16, g_fontCurrent->height);
	}
	for (; way != 0; way--) s_glyphs[c][way] = s_glyphs[c][way - 1];
	s_glyphs[c][0] = glyph;
	return glyph;
}

void GUI_Glyph_Merge(const GlyphCell *cell, uint16 *dst, uint16 stride,
                     uint16 groups, uint16 rows, uint16 x)
{
	uint16 row, plane, group = x >> 4, shift = x & 15;
	const uint16 rowCount = min(rows, cell->font->height);

	if (group >= groups) return;
	for (row = 0; row < rowCount; row++) {
		uint16 mask = cell->masks[row];
		const uint16 *pixels = cell->pixels + row * 4;
		uint16 *d = dst + row * stride + group * 4;
		uint16 part;

		if (mask == 0) continue;
		part = mask >> shift;
		for (plane = 0; plane < 4; plane++)
			d[plane] = (d[plane] & ~part) | ((pixels[plane] >> shift) & part);
		if (shift != 0 && group + 1 < groups) {
			part = mask << (16 - shift);
			if (part == 0) continue;
			for (plane = 0; plane < 4; plane++)
				d[plane + 4] = (d[plane + 4] & ~part) | ((pixels[plane] << (16 - shift)) & part);
		}
	}
}
