#ifndef GUI_GLYPH_H
#define GUI_GLYPH_H

#ifdef TOS
#include "font.h"

/* One font glyph rendered through a colour table: a 16-pixel-wide planar cell
 * (4 words per row) plus a per-row opacity mask, bit 15 = leftmost pixel. */
typedef struct GlyphCell {
	const Font *font;
	uint8 colours[16];
	uint8 simple;     /*!< Every plane is the mask or empty under the mask (single pen). */
	uint8 orPlanes;   /*!< With simple: planes (bit n) that equal the mask. */
	uint16 pixels[16 * 4], masks[16];
} GlyphCell;

/* Cell of g_fontCurrent for c under colours (indexed by glyph pixel value). Cached per
 * (font, colours); the cache is dropped when the palette generation changes. */
extern const GlyphCell *GUI_Glyph_Get(unsigned char c, const uint8 colours[16]);
extern void GUI_Glyph_Free(void);

/* Merges the cell at pixel x into a planar buffer; dst addresses row 0, stride is in words
 * per row, groups is the number of 16-pixel groups per row. Rows beyond `rows` are dropped.
 * If masks is not NULL (groups words per row) the cell's opacity is ORed into it. */
extern void GUI_Glyph_Merge(const GlyphCell *cell, uint16 *dst, uint16 stride,
                            uint16 groups, uint16 rows, uint16 x, uint16 *masks);
#endif

#endif
