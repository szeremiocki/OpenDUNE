/** @file src/gui/glyph.h Per-font planar glyph masks and the planar text line renderer (TOS). */

#ifndef GUI_GLYPH_H
#define GUI_GLYPH_H

#ifdef TOS
#include "font.h"

enum { GLYPH_MAX_GROUPS = 20, GLYPH_LINE_UNSUPPORTED = 0xFFFF };

/* Builds f->planar: per glyph one 16-bit mask word per row of the font's used row span
 * and per pixel value the font uses. Leaves f->planar NULL for fonts that do not fit
 * (glyph wider than 16 pixels, taller than 16 rows, more than 8 pixel values). */
extern void GUI_Glyph_FontBuild(Font *f);
extern void GUI_Glyph_FontFree(Font *f);

/* Draws one line of transparent text (no wrapping, no control characters) straight into a
 * planar destination, as GUI_DrawChar() would with colours[0] == 0: colours are indexed by glyph
 * pixel value, colour 0 is transparent, and a later glyph overwrites the pixels it draws (so
 * negative character spacing overlaps). The line starts at pixel `phase` (0..15) of group 0.
 * Destination: planes[row * planeStride + group * 4 + plane] for `rows` rows at most (bit 15 =
 * leftmost pixel); only drawn pixels are changed. masks (may be NULL) gets the drawn pixels
 * OR-ed in at masks[row * maskStride + group]; the caller clears it beforehand.
 * A glyph that does not fit entirely within maxGroups (<= GLYPH_MAX_GROUPS) groups is skipped,
 * as GUI_DrawChar() does at the screen edge. Returns the groups the text spans, 0 if nothing is
 * drawn, or GLYPH_LINE_UNSUPPORTED (nothing written) if the font cannot be used (see
 * GUI_Glyph_Usable), a character would advance backwards, or colours[0] is not 0. */
extern uint16 GUI_Glyph_Line(const Font *font, const uint8 colours[16], const char *string, uint16 phase,
                             uint16 maxGroups, uint16 rows, uint16 *planes, uint16 planeStride,
                             uint16 *masks, uint16 maskStride);
extern bool GUI_Glyph_Usable(const Font *font);
#endif

#endif
