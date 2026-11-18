/** @file src/video/atari_planar.h Private native colour border kernels (TOS). */

#ifndef VIDEO_ATARI_PLANAR_H
#define VIDEO_ATARI_PLANAR_H

#ifdef TOS
/* Draws a filled bordered rectangle (as GUI_DrawBorder with fill) into a planar target.
 * dst points at the first rectangle row of a 16-pixel-aligned target (group 0 holds pixels 0..15,
 * 4 plane words per group, `stride` words per row); x is the pixel offset of the rectangle in it.
 * groups[16] are four 4-word groups in screen word order: fill, bottom/right edge, top/left edge
 * and corners (the border schema's four colours). Each plane word is 0 or 0xffff for a solid
 * colour; any 16-pixel-periodic pattern works, aligned to the 16-pixel groups of the target.
 * Needs width >= 2 and height >= 3.
 * Contract: the pixels of the edge groups outside the rectangle are read once per row type, from
 * its own first row, and written back unchanged on every row, so the caller must guarantee they
 * repeat vertically over the rectangle's rows. Every group is otherwise written, never read. */
extern void Planar_DrawBorder(uint16 *dst, uint16 stride, uint16 x, uint16 width, uint16 height,
                              const uint16 groups[16]);

/* The four plane words of a solid group in the 4-bit hardware pen `pen`. */
extern void Planar_SolidGroup(uint16 group[4], uint8 pen);
#endif

#endif
