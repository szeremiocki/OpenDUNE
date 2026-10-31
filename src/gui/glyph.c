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
	enum { SLACK = GLYPH_MAX_GROUPS + 1 };
	static uint16 s_x[GLYPH_MAX_CHARS], s_box[GLYPH_MAX_CHARS];
	static const uint16 *s_mask[GLYPH_MAX_CHARS];
	const GlyphFont *gf = font->planar;
	const uint16 height = font->height, rows = gf != NULL ? gf->rows : 0, values = gf != NULL ? gf->values : 0;
	const bool background = colours[0] != 0, overlap = g_fontCharOffset < 0;
	uint16 pl[4][SLACK], mk[SLACK], cov[SLACK], box[SLACK], written[SLACK];
	uint16 vOff[GLYPH_MAX_VALUES], vBits[GLYPH_MAX_VALUES];
	uint16 count = 0, x = phase, extent = phase, groups, row, group, first, last, listed = 0;
	uint8 pen[GLYPH_MAX_VALUES], bgPen = 0;
	uint16 j, i;
	const char *s;

	if (!GUI_Glyph_Usable(font) || maxGroups > GLYPH_MAX_GROUPS || phase > 15) return GLYPH_LINE_UNSUPPORTED;
	for (s = string; *s != '\0'; s++) {
		const FontChar *fc = &font->chars[(unsigned char)*s];

		if ((int)fc->width + g_fontCharOffset < 0) return GLYPH_LINE_UNSUPPORTED;
		/* As GUI_DrawChar(): a glyph that does not fit entirely is skipped. */
		if (fc->data != NULL && count < GLYPH_MAX_CHARS && x + fc->width <= maxGroups * 16) {
			s_mask[count] = gf->masks + (size_t)(unsigned char)*s * values * rows;
			s_x[count] = x;
			s_box[count] = fc->width == 16 ? 0xffffu : (uint16)(0xffffu << (16 - fc->width));
			count++;
			if (x + fc->width > extent) extent = x + fc->width;
		}
		x += fc->width + g_fontCharOffset;
	}
	if (count == 0) return 0;
	/* Overlapping glyphs are only resolved for transparent text. */
	if (background && overlap && count > 1) return GLYPH_LINE_UNSUPPORTED;
	groups = (extent + 15) >> 4;

	if (background) bgPen = Video_Atari_GetPalettePen(colours[0]);
	/* Transparent text only walks the visible values; a background also needs the others to
	 * know which pixels the glyphs cover. */
	for (j = 0; j < values; j++) {
		const uint8 c = colours[gf->value[j]];

		if (c == 0 && !background) continue;
		pen[listed] = Video_Atari_GetPalettePen(c);
		vOff[listed] = j * rows;
		vBits[listed] = c != 0 ? pen[listed] : 0;
		listed++;
	}

	first = background ? 0 : gf->firstRow;
	last = background ? height : gf->firstRow + rows;
	for (row = 0; row < height; row++) {
		const bool inSpan = row >= gf->firstRow && row < gf->firstRow + rows;
		uint16 *pw;

		if (row < first || row >= last) {
			memset(masks + row * groups, 0, (size_t)groups * sizeof(uint16));
			continue;
		}
		memset(pl, 0, sizeof(pl));
		memset(mk, 0, (size_t)(groups + 1) * sizeof(uint16));
		if (background) {
			memset(cov, 0, (size_t)(groups + 1) * sizeof(uint16));
			memset(box, 0, (size_t)(groups + 1) * sizeof(uint16));
		}
		if (overlap) memset(written, 0, (size_t)(groups + 1) * sizeof(uint16));

		for (i = 0; i < count; i++) {
			const uint16 px = s_x[i], g = px >> 4, sh = 16 - (px & 15);
			const uint16 *src = s_mask[i] + (row - gf->firstRow);

			if (background) {
				const uint32 v = (uint32)s_box[i] << sh;

				box[g] |= (uint16)(v >> 16);
				box[g + 1] |= (uint16)v;
			}
			if (!inSpan) continue;

			if (overlap) {
				/* Later glyphs overwrite earlier pixels; only a real collision costs anything. */
				uint16 drawn = 0;
				uint32 v;
				uint16 hi, lo;

				for (j = 0; j < listed; j++) drawn |= src[vOff[j]];
				if (drawn == 0) continue;
				v = (uint32)drawn << sh;
				hi = (uint16)(v >> 16);
				lo = (uint16)v;
				if (((hi & written[g]) | (lo & written[g + 1])) != 0) {
					for (j = 0; j < 4; j++) { pl[j][g] &= ~hi; pl[j][g + 1] &= ~lo; }
					mk[g] &= ~hi;
					mk[g + 1] &= ~lo;
				}
				written[g] |= hi;
				written[g + 1] |= lo;
			}
			for (j = 0; j < listed; j++) {
				const uint16 m = src[vOff[j]];
				uint32 v;
				uint16 hi, lo, bits;

				if (m == 0) continue;
				v = (uint32)m << sh;
				hi = (uint16)(v >> 16);
				lo = (uint16)v;
				if (background) {
					cov[g] |= hi;
					cov[g + 1] |= lo;
				}
				bits = vBits[j];
				if (bits == 0) continue;
				mk[g] |= hi;
				mk[g + 1] |= lo;
				if (bits & 1) { pl[0][g] |= hi; pl[0][g + 1] |= lo; }
				if (bits & 2) { pl[1][g] |= hi; pl[1][g + 1] |= lo; }
				if (bits & 4) { pl[2][g] |= hi; pl[2][g + 1] |= lo; }
				if (bits & 8) { pl[3][g] |= hi; pl[3][g + 1] |= lo; }
			}
		}

		pw = planes + row * groups * 4;
		for (group = 0; group < groups; group++) {
			uint16 m = mk[group], p0 = pl[0][group], p1 = pl[1][group], p2 = pl[2][group], p3 = pl[3][group];

			if (background) {
				const uint16 under = box[group] & ~cov[group];

				m |= under;
				if (bgPen & 1) p0 |= under;
				if (bgPen & 2) p1 |= under;
				if (bgPen & 4) p2 |= under;
				if (bgPen & 8) p3 |= under;
			}
			masks[row * groups + group] = m;
			*pw++ = p0;
			*pw++ = p1;
			*pw++ = p2;
			*pw++ = p3;
		}
	}
	return groups;
}
