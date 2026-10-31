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

uint16 GUI_Glyph_Line(const Font *font, const uint8 colours[16], const char *string,
                      uint16 phase, uint16 maxGroups, uint16 *planes, uint16 *masks)
{
	uint16 stride;

	return GUI_Glyph_LineFill(font, colours, string, phase, maxGroups, 0, &stride, planes, masks);
}

uint16 GUI_Glyph_LineFill(const Font *font, const uint8 colours[16], const char *string,
                          uint16 phase, uint16 maxGroups, uint16 fillGroups, uint16 *stride,
                          uint16 *planes, uint16 *masks)
{
	static uint16 s_x[GLYPH_MAX_CHARS], s_box[GLYPH_MAX_CHARS];
	static uint8 s_char[GLYPH_MAX_CHARS];
	const GlyphFont *gf = font->planar;
	const uint16 height = font->height, rows = gf != NULL ? gf->rows : 0, values = gf != NULL ? gf->values : 0;
	const bool background = colours[0] != 0, overlap = g_fontCharOffset < 0;
	uint16 strips[GLYPH_MAX_VALUES][GLYPH_MAX_GROUPS], box[GLYPH_MAX_GROUPS], bgBits[GLYPH_MAX_GROUPS];
	uint16 count = 0, x = phase, extent = phase, textGroups = 0, groups, row, group, first, last;
	uint8 pen[GLYPH_MAX_VALUES], bgPen = 0, visible[GLYPH_MAX_VALUES], isVisible[GLYPH_MAX_VALUES], visibleCount = 0;
	uint16 j, plane;
	const char *s;

	*stride = 0;
	if (!GUI_Glyph_Usable(font) || maxGroups > GLYPH_MAX_GROUPS || phase > 15) return 0;
	for (s = string; *s != '\0'; s++) {
		const FontChar *fc = &font->chars[(unsigned char)*s];

		if ((int)fc->width + g_fontCharOffset < 0) return 0;
		/* As GUI_DrawChar(): a glyph that does not fit entirely is skipped. */
		if (fc->data != NULL && count < GLYPH_MAX_CHARS && x + fc->width <= maxGroups * 16) {
			s_char[count] = (unsigned char)*s;
			s_x[count] = x;
			s_box[count] = fc->width == 16 ? 0xffffu : (uint16)(0xffffu << (16 - fc->width));
			count++;
			if (x + fc->width > extent) extent = x + fc->width;
		}
		x += fc->width + g_fontCharOffset;
	}
	if (count != 0) textGroups = (extent + 15) >> 4;

	/* The fill only pads with the background colour, so it needs one. */
	groups = textGroups;
	if (background && fillGroups != 0) {
		if (fillGroups > maxGroups) fillGroups = maxGroups;
		if (fillGroups > groups) groups = fillGroups;
	} else {
		fillGroups = 0;
	}
	if (groups == 0) return 0;
	*stride = groups;

	if (background) bgPen = Video_Atari_GetPalettePen(colours[0]);
	for (j = 0; j < values; j++) {
		pen[j] = Video_Atari_GetPalettePen(colours[gf->value[j]]);
		isVisible[j] = colours[gf->value[j]] != 0;
		if (isVisible[j]) visible[visibleCount++] = j;
	}

	first = background ? 0 : gf->firstRow;
	last = background ? height : gf->firstRow + rows;
	for (row = 0; row < height; row++) {
		if (row < first || row >= last) {
			memset(masks + row * groups, 0, (size_t)groups * sizeof(uint16));
			continue;
		}
		memset(strips, 0, sizeof(strips[0]) * values);
		memset(box, fillGroups != 0 ? 0xff : 0, (size_t)groups * sizeof(uint16));
		memset(bgBits, 0, (size_t)groups * sizeof(uint16));
		{
			const int span = row - gf->firstRow;
			const bool inSpan = span >= 0 && span < (int)rows;

			for (group = 0; group < count; group++) {
				const uint16 px = s_x[group], g = px >> 4, shift = px & 15;
				const bool spill = shift != 0 && g + 1 < groups;

				if (background && fillGroups == 0) {
					box[g] |= s_box[group] >> shift;
					if (spill) box[g + 1] |= (uint16)(s_box[group] << (16 - shift));
				}
				if (overlap) {
					/* A later glyph overwrites what it draws over earlier ones. */
					uint16 all = 0, vis = 0, own, drawn;

					if (inSpan) {
						for (j = 0; j < values; j++) {
							const uint16 m = gf->masks[((size_t)s_char[group] * values + j) * rows + span];

							all |= m;
							if (isVisible[j]) vis |= m;
						}
					}
					own = background ? (uint16)(s_box[group] & ~all) : 0;

					drawn = vis | own;
					bgBits[g] = (uint16)((bgBits[g] & ~(vis >> shift)) | (own >> shift));
					if (spill) bgBits[g + 1] = (uint16)((bgBits[g + 1] & ~(uint16)(vis << (16 - shift))) | (uint16)(own << (16 - shift)));
					if (drawn != 0) {
						for (j = 0; j < values; j++) {
							strips[j][g] &= (uint16)~(drawn >> shift);
							if (spill) strips[j][g + 1] &= (uint16)~(uint16)(drawn << (16 - shift));
						}
					}
				}
				if (!inSpan) continue;
				for (j = 0; j < values; j++) {
					const uint16 m = gf->masks[((size_t)s_char[group] * values + j) * rows + span];

					if (m == 0) continue;
					strips[j][g] |= m >> shift;
					if (spill) strips[j][g + 1] |= (uint16)(m << (16 - shift));
				}
			}
		}
		for (group = 0; group < groups; group++) {
			uint16 under = 0, mask = 0, out[4] = { 0, 0, 0, 0 };

			if (background) {
				if (fillGroups != 0) {
					for (j = 0; j < visibleCount; j++) under |= strips[visible[j]][group];
					under = ~under;
				} else if (overlap) {
					under = bgBits[group];
				} else {
					for (j = 0; j < values; j++) under |= strips[j][group];
					under = box[group] & ~under;
				}
				mask = under;
				for (plane = 0; plane < 4; plane++) if (bgPen & (1 << plane)) out[plane] = under;
			}
			for (j = 0; j < visibleCount; j++) {
				const uint8 v = visible[j];
				const uint16 m = strips[v][group];

				mask |= m;
				for (plane = 0; plane < 4; plane++) if (pen[v] & (1 << plane)) out[plane] |= m;
			}
			masks[row * groups + group] = mask;
			memcpy(planes + (row * groups + group) * 4, out, sizeof(out));
		}
	}
	return textGroups;
}
