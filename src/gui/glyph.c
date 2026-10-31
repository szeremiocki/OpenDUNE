/** @file src/gui/glyph.c Per-font planar glyph masks and the planar text line renderer (TOS). */

#include <stdlib.h>
#include <string.h>
#include "types.h"
#include "glyph.h"
#include "font.h"
#include "../video/video.h"

enum { GLYPH_MAX_VALUES = 8, GLYPH_MAX_CHARS = 128 };

typedef struct GlyphFont {
	uint8 values;                     /*!< Number of glyph pixel values in use (value 0 excluded). */
	uint8 value[GLYPH_MAX_VALUES];    /*!< The pixel values, ascending. */
	uint8 firstRow, rows;             /*!< Row span used by any glyph of the font. */
	uint16 masks[];                   /*!< [char][value][row]: bit 15 = leftmost pixel. */
} GlyphFont;

void GUI_Glyph_FontFree(Font *f)
{
	free(f->planar);
	f->planar = NULL;
}

void GUI_Glyph_FontBuild(Font *f)
{
	GlyphFont *gf;
	uint16 used = 0, c, x, y, j, first = 255, last = 0, rows, values = 0;
	uint8 index[16];

	f->planar = NULL;
	if (f->height == 0 || f->height > 16) return;
	for (c = 0; c < f->count; c++) {
		const FontChar *fc = &f->chars[c];

		if (fc->width > 16) return;
		if (fc->data == NULL || fc->usedLines == 0) continue;
		for (y = 0; y < (uint16)fc->usedLines * fc->width; y++) used |= 1 << (fc->data[y] & 15);
		if (fc->unusedLines < first) first = fc->unusedLines;
		if (fc->unusedLines + fc->usedLines > last) last = fc->unusedLines + fc->usedLines;
	}
	used &= ~1;
	for (j = 1; j < 16; j++) if (used & (1 << j)) values++;
	if (values > GLYPH_MAX_VALUES || last > f->height) return;
	rows = last > first ? last - first : 0;

	gf = calloc(1, sizeof(*gf) + (size_t)f->count * values * rows * sizeof(uint16));
	if (gf == NULL) return;
	gf->values = values;
	gf->firstRow = rows != 0 ? first : 0;
	gf->rows = rows;
	for (j = 1, c = 0; j < 16; j++) {
		index[j] = c;
		if (used & (1 << j)) gf->value[c++] = j;
	}
	for (c = 0; c < f->count; c++) {
		const FontChar *fc = &f->chars[c];

		if (fc->data == NULL) continue;
		for (y = 0; y < fc->usedLines; y++) {
			for (x = 0; x < fc->width; x++) {
				uint8 v = fc->data[y * fc->width + x] & 15;

				if (v == 0) continue;
				gf->masks[((size_t)c * values + index[v]) * rows + fc->unusedLines + y - first] |= 0x8000u >> x;
			}
		}
	}
	f->planar = gf;
}

bool GUI_Glyph_Usable(const Font *font)
{
	return font != NULL && font->planar != NULL;
}

/* Draws one pixel value of one glyph. `pen` is a constant in every expansion, so the plane
 * tests fold away: each drawn row costs one shift and a set or clear per plane word. */
static inline __attribute__((always_inline)) void GUI_Glyph_Value(
	const uint16 *src, uint16 *dst, uint16 *mdst, uint16 rows, uint16 sh,
	uint16 planeStride, uint16 maskStride, const uint16 pen)
{
	uint16 moff = 0;

	for (; rows != 0; rows--, src++, dst += planeStride, moff += maskStride) {
		uint32 v;
		uint16 hi, lo;

		if (*src == 0) continue;
		v = (uint32)*src << sh;
		hi = (uint16)(v >> 16);
		lo = (uint16)v;
		if (pen & 1) dst[0] |= hi; else dst[0] &= ~hi;
		if (pen & 2) dst[1] |= hi; else dst[1] &= ~hi;
		if (pen & 4) dst[2] |= hi; else dst[2] &= ~hi;
		if (pen & 8) dst[3] |= hi; else dst[3] &= ~hi;
		if (lo != 0) {
			if (pen & 1) dst[4] |= lo; else dst[4] &= ~lo;
			if (pen & 2) dst[5] |= lo; else dst[5] &= ~lo;
			if (pen & 4) dst[6] |= lo; else dst[6] &= ~lo;
			if (pen & 8) dst[7] |= lo; else dst[7] &= ~lo;
		}
		if (mdst != NULL) {
			mdst[moff] |= hi;
			if (lo != 0) mdst[moff + 1] |= lo;
		}
	}
}

uint16 GUI_Glyph_Line(const Font *font, const uint8 colours[16], const char *string, uint16 phase,
                      uint16 maxGroups, uint16 rows, uint16 *planes, uint16 planeStride,
                      uint16 *masks, uint16 maskStride)
{
	static uint16 s_x[GLYPH_MAX_CHARS];
	static const uint16 *s_mask[GLYPH_MAX_CHARS];
	const GlyphFont *gf = font->planar;
	const uint16 values = gf != NULL ? gf->values : 0, spanRows = gf != NULL ? gf->rows : 0;
	uint16 off[GLYPH_MAX_VALUES], bits[GLYPH_MAX_VALUES];
	uint16 count = 0, x = phase, extent = phase, groups, listed = 0, rowStart, rowEnd, i, j;
	const char *s;

	if (!GUI_Glyph_Usable(font) || maxGroups > GLYPH_MAX_GROUPS || phase > 15 || colours[0] != 0) return GLYPH_LINE_UNSUPPORTED;
	for (s = string; *s != '\0' && *s != '\n' && *s != '\r'; s++) {
		const FontChar *fc = &font->chars[(unsigned char)*s];

		if ((int)fc->width + g_fontCharOffset < 0) return GLYPH_LINE_UNSUPPORTED;
		/* As GUI_DrawChar(): a glyph that does not fit entirely is skipped. */
		if (fc->data != NULL && count < GLYPH_MAX_CHARS && x + fc->width <= maxGroups * 16) {
			s_mask[count] = gf->masks + (size_t)(unsigned char)*s * values * spanRows;
			s_x[count] = x;
			count++;
			if (x + fc->width > extent) extent = x + fc->width;
		}
		x += fc->width + g_fontCharOffset;
	}
	if (count == 0) return 0;
	groups = (extent + 15) >> 4;

	for (j = 0; j < values; j++) {
		const uint8 c = colours[gf->value[j]];

		if (c == 0) continue;
		off[listed] = j * spanRows;
		bits[listed] = Video_Atari_GetPalettePen(c);
		listed++;
	}
	rowStart = gf->firstRow;
	rowEnd = gf->firstRow + spanRows < rows ? gf->firstRow + spanRows : rows;
	if (listed == 0 || rowStart >= rowEnd) return groups;

	/* Glyph by glyph, then value by value: a later glyph overwrites the pixels it draws and
	 * leaves the rest, and the values of one glyph never share a pixel. */
	for (i = 0; i < count; i++) {
		const uint16 px = s_x[i], sh = 16 - (px & 15), nrows = rowEnd - rowStart;
		uint16 *dst = planes + rowStart * planeStride + (px >> 4) * 4;
		uint16 *mdst = masks != NULL ? masks + rowStart * maskStride + (px >> 4) : NULL;

		for (j = 0; j < listed; j++) {
			const uint16 *src = s_mask[i] + off[j];

#define VALUE(n) case n: GUI_Glyph_Value(src, dst, mdst, nrows, sh, planeStride, maskStride, n); break
			switch (bits[j] & 15) {
			VALUE(0); VALUE(1); VALUE(2); VALUE(3); VALUE(4); VALUE(5); VALUE(6); VALUE(7);
			VALUE(8); VALUE(9); VALUE(10); VALUE(11); VALUE(12); VALUE(13); VALUE(14); VALUE(15);
			}
#undef VALUE
		}
	}
	return groups;
}
