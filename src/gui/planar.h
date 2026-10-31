/** @file src/gui/planar.h Write-only planar drawing primitives (TOS). */

#ifndef GUI_PLANAR_H
#define GUI_PLANAR_H

#ifdef TOS
/* Draws a filled bordered rectangle (as GUI_DrawBorder with fill) into a planar target.
 * dst points at the first rectangle row of a 16-pixel-aligned target (group 0 holds pixels 0..15,
 * 4 plane words per group, `stride` words per row); x is the pixel offset of the rectangle in it.
 * pens[0..3] are the 4-bit hardware pens of the border schema (fill, bottom/right, top/left, corners).
 * Needs width >= 2 and height >= 3.
 * Contract: the pixels of the edge groups outside the rectangle are read once, from the second
 * row, and written back unchanged on every row, so the caller must guarantee they repeat
 * vertically over the rectangle's rows. Every group is otherwise written, never read. */
extern void Planar_DrawBorder(uint16 *dst, uint16 stride, uint16 x, uint16 width, uint16 height,
                              const uint8 pens[4]);
#endif

#endif
