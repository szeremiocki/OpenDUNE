/** @file src/gui/sidebar.c Planar drawing of the ST sidebar straight into the live screen. */

#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "types.h"
#include "gui.h"
#include "widget.h"
#include "sidebar.h"
#include "glyph.h"
#include "planar.h"
#include "../config.h"
#include "../os/common.h"
#include "../os/error.h"
#include "../os/math.h"
#include "../os/endian.h"
#include "../sprites.h"
#include "../video/video.h"

enum { SIDEBAR_X = 256, SIDEBAR_Y = 42, SIDEBAR_WIDTH = 64, SIDEBAR_HEIGHT = 82,
       SIDEBAR_GROUPS = 4, SIDEBAR_SPRITES = 355 };

typedef struct SidebarSprite {
	uint16 width, height;
	uint16 data[];
} SidebarSprite;

/* Pre-decoded planar sprites: pixels (4 words per group) followed by one mask word per group. */
static SidebarSprite *s_sprites[SIDEBAR_SPRITES][3];

/* Destination of the primitives: the sidebar's top-left group in a planar surface. */
static uint16 *s_dst;
static uint16 s_stride;
static bool s_active, s_valid, s_complete;
static uint16 s_generation;
static int16 s_clipLeft, s_clipTop, s_clipRight, s_clipBottom;

bool GUI_Sidebar_Active(void) { return s_active; }
bool GUI_Sidebar_Valid(void)
{
	return s_valid && s_generation == Video_Atari_GetPaletteGeneration();
}
void GUI_Sidebar_Invalidate(void) { s_valid = false; }

void GUI_Sidebar_Free(void)
{
	uint16 i, variant;

	assert(!s_active);
	for (i = 0; i < SIDEBAR_SPRITES; i++) {
		for (variant = 0; variant < 3; variant++) {
			free(s_sprites[i][variant]);
			s_sprites[i][variant] = NULL;
		}
	}
	s_valid = false;
}

void GUI_Sidebar_Begin(bool force)
{
	uint16 generation = Video_Atari_GetPaletteGeneration();

	VARIABLE_NOT_USED(force);
	assert(Video_Atari_CursorDirect() && !s_active);
	if (generation != s_generation) {
		GUI_Sidebar_Free();
		s_generation = generation;
	}
	s_dst = Video_Atari_LiveBegin(SIDEBAR_X, SIDEBAR_Y, SIDEBAR_WIDTH, SIDEBAR_HEIGHT);
	s_stride = VIDEO_ATARI_LIVE_STRIDE;
	s_active = true;
	s_complete = true;
	s_clipLeft = s_clipTop = 0;
	s_clipRight = SIDEBAR_WIDTH - 1;
	s_clipBottom = SIDEBAR_HEIGHT - 1;
}

void GUI_Sidebar_End(void)
{
	assert(s_active);
	s_active = false;
	Video_Atari_LiveEnd(SIDEBAR_X, SIDEBAR_Y, SIDEBAR_WIDTH, SIDEBAR_HEIGHT);
	/* A widget-only update cannot validate the rest of a replaced panel. */
	s_valid |= s_complete;
}

bool GUI_Sidebar_WidgetBegin(const Widget *w)
{
	if (s_active || !GFX_Screen_IsActive(SCREEN_0) ||
	    !Video_Atari_CursorDirect() || w->index < 3 || w->index > 11) return false;
	if (w->parentID != 0 || w->offsetX <= SIDEBAR_X || w->offsetY <= SIDEBAR_Y ||
	    w->offsetX + w->width >= SIDEBAR_X + SIDEBAR_WIDTH ||
	    w->offsetY + w->height >= SIDEBAR_Y + SIDEBAR_HEIGHT) return false;
	if (GUI_Widget_Get_ByIndex(g_widgetLinkedListHead, w->index) != w) return false;
	GUI_Sidebar_Begin(false);
	s_complete = false;
	return true;
}

/* Merges the pixels selected by `mask` of one 16-pixel row into `dst`, at column x of the
 * sidebar, inside the clip rectangle. */
static void GUI_Sidebar_Merge(uint16 *dst, uint16 stride, int16 x, int16 y, uint16 mask,
                              const uint16 pixels[4])
{
	uint16 group, shift, plane, clipped[4];
	int16 left = max(x, s_clipLeft), right = min(x + 15, s_clipRight);

	if (y < s_clipTop || y > s_clipBottom || left > right) return;
	mask &= (0xffffu >> (left - x)) & (0xffffu << (15 - (right - x)));
	if (x < 0) {
		if (x <= -16) return;
		mask <<= -x;
		for (plane = 0; plane < 4; plane++) clipped[plane] = pixels[plane] << -x;
		pixels = clipped;
		x = 0;
	}
	group = x >> 4;
	shift = x & 15;
	if (y < 0 || y >= SIDEBAR_HEIGHT || group >= SIDEBAR_GROUPS) return;
	dst += y * stride + group * 4;
	for (plane = 0; plane < 4; plane++) {
		uint16 part = mask >> shift;
		dst[plane] = (dst[plane] & ~part) | ((pixels[plane] >> shift) & part);
		if (shift != 0 && group + 1 < SIDEBAR_GROUPS) {
			part = mask << (16 - shift);
			dst[plane + 4] = (dst[plane + 4] & ~part) | ((pixels[plane] << (16 - shift)) & part);
		}
	}
}

/* 16-bit aligned access to two plane words at once; the 68000 only needs word alignment. */
typedef uint32 __attribute__((may_alias, aligned(2))) SidebarLong;

static void GUI_Sidebar_FillTo(uint16 *dst, uint16 stride, int16 left, int16 top, int16 right,
                               int16 bottom, uint8 colour)
{
	const uint16 pen = Video_Atari_GetPalettePen(colour);
	uint16 plane[4], leftMask, rightMask, row, group, firstGroup, lastGroup;
	uint32 pair01, pair23;

	left = max(left - SIDEBAR_X, s_clipLeft);
	right = min(right - SIDEBAR_X, s_clipRight);
	top = max(top - SIDEBAR_Y, s_clipTop);
	bottom = min(bottom - SIDEBAR_Y, s_clipBottom);
	if (left > right || top > bottom) return;

	for (group = 0; group < 4; group++) plane[group] = (pen & (1 << group)) ? 0xffff : 0;
	pair01 = *(const SidebarLong *)plane;
	pair23 = *(const SidebarLong *)(plane + 2);
	firstGroup = left >> 4;
	lastGroup = right >> 4;
	leftMask = 0xffffu >> (left & 15);
	rightMask = 0xffffu << (15 - (right & 15));
	dst += top * stride;

	if (firstGroup == lastGroup) {
		const uint16 mask = leftMask & rightMask, keep = ~mask;
		const uint16 set0 = plane[0] & mask, set1 = plane[1] & mask, set2 = plane[2] & mask, set3 = plane[3] & mask;
		uint16 *d = dst + firstGroup * 4;

		for (row = top; row <= bottom; row++, d += stride) {
			d[0] = (d[0] & keep) | set0;
			d[1] = (d[1] & keep) | set1;
			d[2] = (d[2] & keep) | set2;
			d[3] = (d[3] & keep) | set3;
		}
		return;
	}

	{
		const uint16 keepLeft = ~leftMask, keepRight = ~rightMask;
		const uint16 setLeft[4] = { plane[0] & leftMask, plane[1] & leftMask, plane[2] & leftMask, plane[3] & leftMask };
		const uint16 setRight[4] = { plane[0] & rightMask, plane[1] & rightMask, plane[2] & rightMask, plane[3] & rightMask };
		const uint16 middle = lastGroup - firstGroup - 1;
		uint16 *d = dst + firstGroup * 4;

		for (row = top; row <= bottom; row++, d += stride) {
			uint16 *g = d;
			SidebarLong *l;

			g[0] = (g[0] & keepLeft) | setLeft[0];
			g[1] = (g[1] & keepLeft) | setLeft[1];
			g[2] = (g[2] & keepLeft) | setLeft[2];
			g[3] = (g[3] & keepLeft) | setLeft[3];
			l = (SidebarLong *)(g + 4);
			for (group = 0; group < middle; group++) {
				*l++ = pair01;
				*l++ = pair23;
			}
			g = (uint16 *)l;
			g[0] = (g[0] & keepRight) | setRight[0];
			g[1] = (g[1] & keepRight) | setRight[1];
			g[2] = (g[2] & keepRight) | setRight[2];
			g[3] = (g[3] & keepRight) | setRight[3];
		}
	}
}

void GUI_Sidebar_Fill(int16 left, int16 top, int16 right, int16 bottom, uint8 colour)
{
	GUI_Sidebar_FillTo(s_dst, s_stride, left, top, right, bottom, colour);
}

bool GUI_Sidebar_Border(int16 left, int16 top, uint16 width, uint16 height, const uint8 colours[4], bool fill)
{
	int16 x0 = left - SIDEBAR_X, y0 = top - SIDEBAR_Y;
	uint8 pens[4];
	uint16 i;

	if (!s_active || !fill || width < 2 || height < 3) return false;
	if (x0 < s_clipLeft || x0 + (int16)width - 1 > s_clipRight || y0 < s_clipTop || y0 + (int16)height - 1 > s_clipBottom) return false;
	if (x0 < 0 || y0 < 0 || y0 + (int16)height > SIDEBAR_HEIGHT || x0 + (int16)width > SIDEBAR_GROUPS * 16) return false;
	for (i = 0; i < 4; i++) pens[i] = Video_Atari_GetPalettePen(colours[i]);
	SIDEBAR_TRACE("Border x=%d y=%d w=%u h=%u\n", (int)left, (int)top, (unsigned)width, (unsigned)height);
	Planar_DrawBorder(s_dst + y0 * s_stride, s_stride, x0, width, height, pens);
	return true;
}

void GUI_Sidebar_Char(unsigned char c, uint16 x, uint16 y, const uint8 colours[16])
{
	uint16 planes[16 * 4], masks[16] = { 0 }, row;
	const char text[2] = { (char)c, '\0' };
	const uint16 groups = GUI_Glyph_Line(g_fontCurrent, colours, text, 0, 1, 16, planes, 4, masks, 1);

	if (groups != 1) return;
	for (row = 0; row < g_fontCurrent->height; row++)
		if (masks[row] != 0)
			GUI_Sidebar_Merge(s_dst, s_stride, x - SIDEBAR_X, y + row - SIDEBAR_Y, masks[row], planes + row * 4);
}

bool GUI_Sidebar_Text(const char *string, int16 left, int16 top, const uint8 colours[16])
{
	uint16 px, group, height;

	if (g_fontCurrent == NULL) return false;
	height = g_fontCurrent->height;
	if (left < SIDEBAR_X || top < SIDEBAR_Y || top + height > SIDEBAR_Y + SIDEBAR_HEIGHT) return false;
	px = left - SIDEBAR_X;
	group = px >> 4;
	if (group >= SIDEBAR_GROUPS) return false;
	/* Glyphs that do not fit before the screen edge are skipped, not clipped. Each line break
	 * restarts at the same left edge one font line lower; the caller provides the room. */
	if (GUI_Glyph_Line(g_fontCurrent, colours, string, px & 15, SIDEBAR_GROUPS - group, height,
	    s_dst + (top - SIDEBAR_Y) * s_stride + group * 4, s_stride, NULL, 0) == GLYPH_LINE_UNSUPPORTED) return false;
	for (string += strcspn(string, "\n\r"); *string != '\0'; string += strcspn(string, "\n\r")) {
		while (*string == '\n' || *string == '\r') string++;
		top += height;
		GUI_Glyph_Line(g_fontCurrent, colours, string, px & 15, SIDEBAR_GROUPS - group, height,
		    s_dst + (top - SIDEBAR_Y) * s_stride + group * 4, s_stride, NULL, 0);
	}
	return true;
}

void GUI_Sidebar_Sprite(const uint8 *sprite, uint16 spriteID, int16 x, int16 y,
                        int flags, const uint8 *remap, uint16 remapCount)
{
	SidebarSprite *entry;
	uint16 groups, words;
	const uint16 *masks, *pixels;
	uint16 height;
	int16 localX = x - SIDEBAR_X, localY = y - SIDEBAR_Y;

	assert(spriteID < SIDEBAR_SPRITES && g_sprites[spriteID] == sprite);
	assert((flags & ~DRAWSPRITE_FLAG_REMAP) == 0 && remapCount <= 2);
	assert(remapCount == 0 || remap == g_paletteMapping1);
	VARIABLE_NOT_USED(flags);
	entry = s_sprites[spriteID][remapCount];
	if (entry == NULL) {
		uint16 width = (READ_LE_UINT16(sprite + 3) + 15) & ~15;
		uint16 height = sprite[2];
		uint16 row, column;
		union { uint32 align; uint8 bytes[64 * 48]; } chunky;
		if (width == 0 || width > 64 || height == 0 || height > 48) {
			Error("Unsupported sidebar sprite %u (%ux%u)\n", spriteID, width, height);
			exit(1);
		}
		groups = width >> 4;
		words = groups * height;
		entry = malloc(sizeof(*entry) + words * 5 * sizeof(uint16));
		if (entry == NULL) {
			Error("Out of memory for sidebar sprite %u\n", spriteID);
			exit(1);
		}
		entry->width = width;
		entry->height = height;
		memset(chunky.bytes, 0, width * height);
		GUI_DrawSpriteOpacity(chunky.bytes, width, height, sprite, 0, 0);
		memset(entry->data + words * 4, 0, words * sizeof(uint16));
		for (row = 0; row < height; row++) {
			for (column = 0; column < width; column++) {
				if (chunky.bytes[row * width + column] != 0)
					entry->data[words * 4 + row * groups + (column >> 4)] |= 0x8000u >> (column & 15);
			}
		}
		memset(chunky.bytes, 0, width * height);
		GUI_DrawSpriteToBuffer(chunky.bytes, width, height, sprite, 0, 0);
		for (row = 0; row < height; row++) {
			for (column = 0; column < width; column++) {
				uint8 *pixel = &chunky.bytes[row * width + column];
				uint16 count;
				if ((entry->data[words * 4 + row * groups + (column >> 4)] &
				     (0x8000u >> (column & 15))) == 0) continue;
				for (count = 0; count < remapCount; count++) *pixel = remap[*pixel];
			}
		}
		Video_Atari_EncodePlanar(chunky.bytes, entry->data, width, height);
		s_sprites[spriteID][remapCount] = entry;
	}
	groups = entry->width >> 4;
	words = groups * entry->height;
	masks = entry->data + words * 4;
	pixels = entry->data;
	height = entry->height;
	assert(localX >= 0 && localY >= 0 && localY + height <= SIDEBAR_HEIGHT);
	Video_Atari_BlitPlanarSprite(s_dst + localY * s_stride, s_stride, SIDEBAR_GROUPS,
	    pixels, masks, entry->width, height, localX);
}
