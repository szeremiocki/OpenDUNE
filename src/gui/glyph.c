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
	for (s = string; *s != '\0'; s++) {
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

	/* Glyph by glyph; a later glyph overwrites the pixels it draws and leaves the rest. */
	for (i = 0; i < count; i++) {
		const uint16 px = s_x[i], sh = 16 - (px & 15);
		const uint16 *src = s_mask[i];
		uint16 *dst = planes + rowStart * planeStride + (px >> 4) * 4;
		uint16 *mdst = masks != NULL ? masks + rowStart * maskStride + (px >> 4) : NULL;
		uint16 row;

		for (row = rowStart; row < rowEnd; row++, src++, dst += planeStride) {
			uint16 drawn = 0, s0 = 0, s1 = 0, s2 = 0, s3 = 0;
			uint32 v;
			uint16 hi, lo;

			for (j = 0; j < listed; j++) {
				const uint16 m = src[off[j]];
				const uint16 b = bits[j];

				if (m == 0) continue;
				drawn |= m;
				if (b & 1) s0 |= m;
				if (b & 2) s1 |= m;
				if (b & 4) s2 |= m;
				if (b & 8) s3 |= m;
			}
			if (drawn == 0) continue;

			v = (uint32)drawn << sh;
			hi = (uint16)(v >> 16);
			lo = (uint16)v;
			dst[0] = (dst[0] & ~hi) | (uint16)(((uint32)s0 << sh) >> 16);
			dst[1] = (dst[1] & ~hi) | (uint16)(((uint32)s1 << sh) >> 16);
			dst[2] = (dst[2] & ~hi) | (uint16)(((uint32)s2 << sh) >> 16);
			dst[3] = (dst[3] & ~hi) | (uint16)(((uint32)s3 << sh) >> 16);
			if (lo != 0) {
				dst[4] = (dst[4] & ~lo) | (uint16)((uint32)s0 << sh);
				dst[5] = (dst[5] & ~lo) | (uint16)((uint32)s1 << sh);
				dst[6] = (dst[6] & ~lo) | (uint16)((uint32)s2 << sh);
				dst[7] = (dst[7] & ~lo) | (uint16)((uint32)s3 << sh);
			}
			if (mdst != NULL) {
				mdst[(row - rowStart) * maskStride] |= hi;
				if (lo != 0) mdst[(row - rowStart) * maskStride + 1] |= lo;
			}
		}
	}
	return groups;
}
