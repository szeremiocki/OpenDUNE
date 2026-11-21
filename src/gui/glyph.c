/** @file src/gui/glyph.c Per-font planar glyph masks and the planar text line renderer (TOS). */

#include <stdlib.h>
#include <string.h>
#include "types.h"
#include "glyph.h"
#include "font.h"
#include "../video/video.h"

enum { GLYPH_MAX_VALUES = 8 };

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
	static VideoAtariGlyph s_glyphs[GLYPH_MAX_CHARS];
	const GlyphFont *gf = font->planar;
	const uint16 values = gf != NULL ? gf->values : 0, spanRows = gf != NULL ? gf->rows : 0;
	VideoAtariGlyphValue paint[GLYPH_MAX_VALUES];
	uint16 count = 0, x = phase, extent = phase, groups, listed = 0, rowStart, rowEnd, j;
	const char *s;

	if (!GUI_Glyph_Usable(font) || maxGroups > GLYPH_MAX_GROUPS || phase > 15 || colours[0] != 0) return GLYPH_LINE_UNSUPPORTED;
	for (s = string; *s != '\0' && *s != '\n' && *s != '\r'; s++) {
		const FontChar *fc = &font->chars[(unsigned char)*s];

		if ((int)fc->width + g_fontCharOffset < 0) return GLYPH_LINE_UNSUPPORTED;
		/* As GUI_DrawChar(): a glyph that does not fit entirely is skipped. */
		if (fc->data != NULL && count < GLYPH_MAX_CHARS && x + fc->width <= maxGroups * 16) {
			s_glyphs[count].masks = gf->masks + (size_t)(unsigned char)*s * values * spanRows;
			s_glyphs[count].x = x;
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
		paint[listed].offset = j * spanRows;
		paint[listed].colour = c;
		listed++;
	}
	rowStart = gf->firstRow;
	rowEnd = gf->firstRow + spanRows < rows ? gf->firstRow + spanRows : rows;
	if (listed == 0 || rowStart >= rowEnd) return groups;

	{
		const VideoAtariGlyphRun run = {s_glyphs, paint, count, listed, rowStart, rowEnd - rowStart};
		Video_Atari_DrawPlanarGlyphs(&run, planes, planeStride, masks, maskStride);
	}
	return groups;
}
