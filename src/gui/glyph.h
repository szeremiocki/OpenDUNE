/** @file src/gui/glyph.h Per-font planar glyph masks and the planar text line renderer (TOS). */

#ifndef GUI_GLYPH_H
#define GUI_GLYPH_H

#ifdef TOS
#include "font.h"

enum { GLYPH_MAX_GROUPS = 20 };

/* Builds f->planar: per glyph one 16-bit mask word per row of the font's used row span
 * and per pixel value the font uses. Leaves f->planar NULL for fonts that do not fit
 * (glyph wider than 16 pixels, taller than 16 rows, more than 8 pixel values). */
extern void GUI_Glyph_FontBuild(Font *f);
extern void GUI_Glyph_FontFree(Font *f);

/* Renders one line of text (no wrapping, no control characters) with colours indexed by
 * glyph pixel value, as GUI_DrawChar() would: colour 0 is transparent, colours[0] fills
 * the glyph box when not 0. The line starts at pixel `phase` (0..15) of the canvas.
 * Output, row-major with the returned number of 16-pixel groups per row and
 * font->height rows: planes[(row * groups + group) * 4 + plane] and masks[row * groups + group]
 * (bit 15 = leftmost pixel); plane words under a clear mask are undefined.
 * Returns 0 if nothing is drawn or the line does not fit maxGroups (<= GLYPH_MAX_GROUPS),
 * or if the font is unsupported or a character would advance backwards (see GUI_Glyph_Usable). */
extern uint16 GUI_Glyph_Line(const Font *font, const uint8 colours[16], const char *string,
                             uint16 phase, uint16 maxGroups, uint16 *planes, uint16 *masks);
/* As GUI_Glyph_Line(), and with fillGroups != 0 (needs colours[0] != 0) the output is padded
 * with colours[0] up to fillGroups groups, covering what an earlier, longer text left behind.
 * Returns the groups the text itself occupies (padding excluded); *stride receives the groups
 * per row of the output, max(text groups, fillGroups). Passing the returned value as the next
 * call's fillGroups therefore never grows the fill beyond the text drawn. */
extern uint16 GUI_Glyph_LineFill(const Font *font, const uint8 colours[16], const char *string,
                                 uint16 phase, uint16 maxGroups, uint16 fillGroups, uint16 *stride,
                                 uint16 *planes, uint16 *masks);
extern bool GUI_Glyph_Usable(const Font *font);
#endif

#endif
