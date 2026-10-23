/** @file src/gui/sidebar.c Cached, private planar composition for the ST sidebar. */

#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "types.h"
#include "gui.h"
#include "widget.h"
#include "sidebar.h"
#include "../config.h"
#include "../os/common.h"
#include "../os/error.h"
#include "../os/math.h"
#include "../os/endian.h"
#include "../sprites.h"
#include "../video/video.h"

enum { SIDEBAR_X = 256, SIDEBAR_Y = 42, SIDEBAR_WIDTH = 64, SIDEBAR_HEIGHT = 82,
       SIDEBAR_GROUPS = 4, SIDEBAR_WORDS = 16, SIDEBAR_SPRITES = 355,
       SIDEBAR_FRAGMENT_SETS = 32, SIDEBAR_FRAGMENT_WAYS = 4 };

typedef struct SidebarFragmentKey {
	const Font *font;
	int16 spacing, left, top, clipLeft, clipTop, clipRight, clipBottom;
	uint16 kind, width, height, state;
	uint8 colours[16];
} SidebarFragmentKey;

typedef struct SidebarFragment {
	SidebarFragmentKey key;
	char text[240];
	uint16 hash, left, top, groups, height;
	uint16 data[];
} SidebarFragment;

typedef struct SidebarCapture {
	SidebarFragmentKey key;
	char text[240];
	uint16 hash;
	uint16 masks[SIDEBAR_HEIGHT * SIDEBAR_GROUPS];
} SidebarCapture;

typedef struct SidebarCommand {
	const Font *font;
	uint16 language, colour;
	bool valid;
	uint16 pixels[SIDEBAR_HEIGHT * SIDEBAR_WORDS];
} SidebarCommand;

typedef struct SidebarGlyph {
	const Font *font;
	uint8 colours[16];
	uint16 pixels[16 * 4], masks[16];
} SidebarGlyph;

typedef struct SidebarSprite {
	uint16 width, height;
	uint16 data[];
} SidebarSprite;

static uint16 s_pixels[SIDEBAR_HEIGHT * SIDEBAR_WORDS];
static uint16 s_display[SIDEBAR_HEIGHT * SIDEBAR_WORDS];
static uint16 s_background[SIDEBAR_HEIGHT * SIDEBAR_WORDS];
static uint16 s_masks[SIDEBAR_HEIGHT * SIDEBAR_GROUPS];
static SidebarGlyph *s_glyphs[256][4];
static SidebarSprite *s_sprites[SIDEBAR_SPRITES][3];
static SidebarFragment *s_fragments[SIDEBAR_FRAGMENT_SETS][SIDEBAR_FRAGMENT_WAYS];
static SidebarCapture s_capture[2];
static uint16 s_captureDepth;
static SidebarCommand s_commands[3];
static bool s_active, s_valid, s_force, s_backgroundValid, s_complete;
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

	assert(!s_active && s_captureDepth == 0);
	for (i = 0; i < SIDEBAR_SPRITES; i++) {
		for (variant = 0; variant < 3; variant++) {
			free(s_sprites[i][variant]);
			s_sprites[i][variant] = NULL;
		}
	}
	for (i = 0; i < 256; i++) {
		for (variant = 0; variant < 4; variant++) {
			free(s_glyphs[i][variant]);
			s_glyphs[i][variant] = NULL;
		}
	}
	for (i = 0; i < SIDEBAR_FRAGMENT_SETS; i++) {
		for (variant = 0; variant < SIDEBAR_FRAGMENT_WAYS; variant++) {
			free(s_fragments[i][variant]);
			s_fragments[i][variant] = NULL;
		}
	}
	memset(s_commands, 0, sizeof(s_commands));
	s_valid = false;
	s_backgroundValid = false;
}

bool GUI_Sidebar_CommandRestore(uint16 actionType)
{
	SidebarCommand *entry = &s_commands[actionType - 4];

	assert(s_active && actionType >= 4 && actionType <= 6);
	if (!entry->valid || entry->font != g_fontNew6p ||
	    entry->language != g_config.language || entry->colour != g_curWidgetFGColourBlink) return false;
	memcpy(s_pixels, entry->pixels, sizeof(s_pixels));
	s_complete = true;
	return true;
}

void GUI_Sidebar_CommandCache(uint16 actionType)
{
	SidebarCommand *entry = &s_commands[actionType - 4];

	assert(s_active && s_complete && actionType >= 4 && actionType <= 6);
	entry->font = g_fontNew6p;
	entry->language = g_config.language;
	entry->colour = g_curWidgetFGColourBlink;
	memcpy(entry->pixels, s_pixels, sizeof(s_pixels));
	entry->valid = true;
}

static void GUI_Sidebar_Record(uint16 row, uint16 group, uint16 mask)
{
	uint16 i;
	/* Capture writes, not differences: equal pixels and opaque pen zero must replay. */
	for (i = 0; i < s_captureDepth; i++) s_capture[i].masks[row * SIDEBAR_GROUPS + group] |= mask;
}

bool GUI_Sidebar_FragmentBegin(uint16 kind, const char *text, int16 left, int16 top,
                              uint16 width, uint16 height, uint16 state, const uint8 *colours)
{
	SidebarCapture *capture = &s_capture[s_captureDepth];
	SidebarFragmentKey *key = &capture->key;
	SidebarFragment **set;
	uint16 hash = 0, i;
	const uint8 *bytes;

	assert(s_active && s_captureDepth < lengthof(s_capture));
	if (strlen(text) >= sizeof(capture->text)) {
		Error("Sidebar fragment text exceeds cache limit\n");
		exit(1);
	}
	memset(key, 0, sizeof(*key));
	key->kind = kind;
	key->left = left;
	key->top = top;
	key->width = width;
	key->height = height;
	key->state = state;
	key->clipLeft = s_clipLeft;
	key->clipTop = s_clipTop;
	key->clipRight = s_clipRight;
	key->clipBottom = s_clipBottom;
	if (kind == SIDEBAR_FRAGMENT_TEXT || kind == SIDEBAR_FRAGMENT_BUTTON) {
		key->font = g_fontCurrent;
		key->spacing = g_fontCharOffset;
	}
	if (colours != NULL) memcpy(key->colours, colours, sizeof(key->colours));
	strcpy(capture->text, text);
	bytes = (const uint8 *)key;
	for (i = 0; i < sizeof(*key); i++) hash = (hash << 5) - hash + bytes[i];
	for (i = 0; text[i] != '\0'; i++) hash = (hash << 5) - hash + (uint8)text[i];
	capture->hash = hash;
	set = s_fragments[hash & (SIDEBAR_FRAGMENT_SETS - 1)];
	for (i = 0; i < SIDEBAR_FRAGMENT_WAYS; i++) {
		SidebarFragment *entry = set[i];
		uint16 row, group;
		if (entry == NULL || entry->hash != hash || memcmp(&entry->key, key, sizeof(*key)) != 0 ||
		    strcmp(entry->text, text) != 0) continue;
		for (; i != 0; i--) set[i] = set[i - 1];
		set[0] = entry;
		for (row = 0; row < entry->height; row++) {
			for (group = 0; group < entry->groups; group++) {
				const uint16 *src = entry->data + (row * entry->groups + group) * 5;
				uint16 mask = src[4], plane;
				uint16 *dst = s_pixels + (entry->top + row) * SIDEBAR_WORDS + (entry->left + group) * 4;
				if (mask == 0) continue;
				if (mask == 0xffff) memcpy(dst, src, 8);
				else for (plane = 0; plane < 4; plane++) dst[plane] = (dst[plane] & ~mask) | (src[plane] & mask);
				GUI_Sidebar_Record(entry->top + row, entry->left + group, mask);
			}
		}
		return true;
	}
	memset(capture->masks, 0, sizeof(capture->masks));
	s_captureDepth++;
	return false;
}

void GUI_Sidebar_FragmentEnd(void)
{
	SidebarCapture *capture;
	SidebarFragment *entry, **set;
	uint16 top = SIDEBAR_HEIGHT, bottom = 0, left = SIDEBAR_GROUPS, right = 0;
	uint16 row, group, i;

	assert(s_active && s_captureDepth != 0);
	capture = &s_capture[--s_captureDepth];
	for (row = 0; row < SIDEBAR_HEIGHT; row++) {
		for (group = 0; group < SIDEBAR_GROUPS; group++) {
			if (capture->masks[row * SIDEBAR_GROUPS + group] == 0) continue;
			top = min(top, row);
			bottom = max(bottom, row);
			left = min(left, group);
			right = max(right, group);
		}
	}
	entry = malloc(sizeof(*entry) + (top == SIDEBAR_HEIGHT ? 0 :
	               (bottom - top + 1) * (right - left + 1) * 5 * sizeof(uint16)));
	if (entry == NULL) {
		Error("Out of memory for sidebar fragment\n");
		exit(1);
	}
	entry->key = capture->key;
	strcpy(entry->text, capture->text);
	entry->hash = capture->hash;
	entry->left = left;
	entry->top = top;
	entry->groups = top == SIDEBAR_HEIGHT ? 0 : right - left + 1;
	entry->height = top == SIDEBAR_HEIGHT ? 0 : bottom - top + 1;
	for (row = 0; row < entry->height; row++) {
		for (group = 0; group < entry->groups; group++) {
			uint16 *dst = entry->data + (row * entry->groups + group) * 5;
			memcpy(dst, s_pixels + (top + row) * SIDEBAR_WORDS + (left + group) * 4, 8);
			dst[4] = capture->masks[(top + row) * SIDEBAR_GROUPS + left + group];
		}
	}
	set = s_fragments[entry->hash & (SIDEBAR_FRAGMENT_SETS - 1)];
	free(set[SIDEBAR_FRAGMENT_WAYS - 1]);
	for (i = SIDEBAR_FRAGMENT_WAYS - 1; i != 0; i--) set[i] = set[i - 1];
	set[0] = entry;
}

bool GUI_Sidebar_Background(void)
{
	s_complete = true;
	if (!s_backgroundValid) return false;
	memcpy(s_pixels, s_background, sizeof(s_pixels));
	return true;
}

void GUI_Sidebar_CacheBackground(void)
{
	memcpy(s_background, s_pixels, sizeof(s_background));
	s_backgroundValid = true;
}

void GUI_Sidebar_Begin(bool force)
{
	uint16 generation = Video_Atari_GetPaletteGeneration();

	assert(Video_Atari_CursorDirect() && !s_active);
	if (generation != s_generation) {
		GUI_Sidebar_Free();
		s_generation = generation;
	}
	s_active = true;
	s_complete = false;
	s_force = force;
	s_clipLeft = s_clipTop = 0;
	s_clipRight = SIDEBAR_WIDTH - 1;
	s_clipBottom = SIDEBAR_HEIGHT - 1;
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
	s_clipLeft = w->offsetX - 1 - SIDEBAR_X;
	s_clipTop = w->offsetY - 1 - SIDEBAR_Y;
	s_clipRight = w->offsetX + w->width - SIDEBAR_X;
	s_clipBottom = w->offsetY + w->height - SIDEBAR_Y;
	return true;
}

static uint8 GUI_Sidebar_Damage(uint16 row)
{
	uint8 result = 0;
	uint16 group;

	for (group = 0; group < SIDEBAR_GROUPS; group++) {
		uint16 offset = row * SIDEBAR_WORDS + group * 4;
		if (s_force || memcmp(s_pixels + offset, s_display + offset, 8) != 0) result |= 1 << group;
	}
	return result;
}

void GUI_Sidebar_End(void)
{
	uint16 row = 0;

	assert(s_active && s_captureDepth == 0);
	s_active = false;
	s_force |= s_complete && !s_valid;
	while (row < SIDEBAR_HEIGHT) {
		uint8 damage = GUI_Sidebar_Damage(row);
		uint16 end = row + 1, first = 0;
		if (damage == 0) {
			row++;
			continue;
		}
		while (end < SIDEBAR_HEIGHT && GUI_Sidebar_Damage(end) == damage) end++;
		while (first < SIDEBAR_GROUPS) {
			uint16 last, offset;
			if ((damage & (1 << first)) == 0) {
				first++;
				continue;
			}
			last = first + 1;
			while (last < SIDEBAR_GROUPS && (damage & (1 << last)) != 0) last++;
			offset = row * SIDEBAR_WORDS + first * 4;
			if (!Video_Atari_PresentRestoreStrided(SIDEBAR_X + first * 16, SIDEBAR_Y + row,
			    (last - first) * 16, end - row, (const uint8 *)(s_pixels + offset), SIDEBAR_WIDTH / 2)) {
				Error("Unable to publish native sidebar fragment\n");
				exit(1);
			}
			first = last;
		}
		row = end;
	}
	memcpy(s_display, s_pixels, sizeof(s_display));
	/* A widget-only update cannot validate the rest of a replaced panel. */
	s_valid |= s_complete;
}

static void GUI_Sidebar_Merge(int16 x, int16 y, uint16 mask, const uint16 pixels[4])
{
	uint16 group, shift, plane, clipped[4];
	uint16 *dst;
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
	dst = s_pixels + y * SIDEBAR_WORDS + group * 4;
	GUI_Sidebar_Record(y, group, mask >> shift);
	if (shift != 0 && group + 1 < SIDEBAR_GROUPS)
		GUI_Sidebar_Record(y, group + 1, mask << (16 - shift));
	for (plane = 0; plane < 4; plane++) {
		uint16 part = mask >> shift;
		dst[plane] = (dst[plane] & ~part) | ((pixels[plane] >> shift) & part);
		if (shift != 0 && group + 1 < SIDEBAR_GROUPS) {
			part = mask << (16 - shift);
			dst[plane + 4] = (dst[plane + 4] & ~part) | ((pixels[plane] << (16 - shift)) & part);
		}
	}
}

void GUI_Sidebar_Fill(int16 left, int16 top, int16 right, int16 bottom, uint8 colour)
{
	uint16 group, row, plane, pen = Video_Atari_GetPalettePen(colour);

	left = max(left - SIDEBAR_X, s_clipLeft);
	right = min(right - SIDEBAR_X, s_clipRight);
	top = max(top - SIDEBAR_Y, s_clipTop);
	bottom = min(bottom - SIDEBAR_Y, s_clipBottom);
	if (left > right || top > bottom) return;
	for (row = top; row <= bottom; row++) {
		for (group = left >> 4; group <= (right >> 4); group++) {
			uint16 mask = (0xffffu >> max(0, left - group * 16)) &
			              (0xffffu << max(0, group * 16 + 15 - right));
			uint16 *dst = s_pixels + row * SIDEBAR_WORDS + group * 4;
			GUI_Sidebar_Record(row, group, mask);
			for (plane = 0; plane < 4; plane++) {
				if (pen & (1 << plane)) dst[plane] |= mask;
				else dst[plane] &= ~mask;
			}
		}
	}
}

void GUI_Sidebar_Char(unsigned char c, uint16 x, uint16 y, const uint8 colours[16])
{
	const FontChar *fc = &g_fontCurrent->chars[c];
	SidebarGlyph *glyph = NULL;
	uint16 row, variant;

	assert(g_fontCurrent->height <= 16 && fc->width <= 16);
	for (variant = 0; variant < 4; variant++) {
		glyph = s_glyphs[c][variant];
		if (glyph != NULL && glyph->font == g_fontCurrent &&
		    memcmp(glyph->colours, colours, sizeof(glyph->colours)) == 0) break;
	}
	if (variant == 4) {
		union { uint32 align; uint8 bytes[16 * 16]; } chunky;
		variant = 3;
		glyph = s_glyphs[c][variant];
		if (glyph == NULL) {
			glyph = malloc(sizeof(*glyph));
			if (glyph == NULL) {
				Error("Out of memory for sidebar glyph %u\n", c);
				exit(1);
			}
			s_glyphs[c][variant] = glyph;
		}
		glyph->font = g_fontCurrent;
		memcpy(glyph->colours, colours, sizeof(glyph->colours));
		memset(chunky.bytes, 0, sizeof(chunky.bytes));
		memset(glyph->masks, 0, sizeof(glyph->masks));
		for (row = 0; row < g_fontCurrent->height; row++) {
			uint16 column;
			for (column = 0; column < fc->width; column++) {
				uint8 colour = colours[0];
				if (row >= fc->unusedLines && row < fc->unusedLines + fc->usedLines)
					colour = colours[fc->data[(row - fc->unusedLines) * fc->width + column] & 15];
				chunky.bytes[row * 16 + column] = colour;
				if (colour != 0) glyph->masks[row] |= 0x8000u >> column;
			}
		}
		Video_Atari_EncodePlanar(chunky.bytes, glyph->pixels, 16, g_fontCurrent->height);
	}
	for (; variant != 0; variant--) s_glyphs[c][variant] = s_glyphs[c][variant - 1];
	s_glyphs[c][0] = glyph;
	for (row = 0; row < g_fontCurrent->height; row++)
		GUI_Sidebar_Merge(x - SIDEBAR_X, y + row - SIDEBAR_Y, glyph->masks[row], glyph->pixels + row * 4);
}

void GUI_Sidebar_Sprite(const uint8 *sprite, uint16 spriteID, int16 x, int16 y,
                        int flags, const uint8 *remap, uint16 remapCount)
{
	SidebarSprite *entry;
	uint16 groups, words;
	const uint16 *masks, *pixels;
	uint16 clipped[64 * 48 / 16], height;
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
	if (GUI_Sidebar_FragmentBegin(SIDEBAR_FRAGMENT_SPRITE, "", x, y,
	    entry->width, entry->height, spriteID * 3 + remapCount, NULL)) return;
	groups = entry->width >> 4;
	words = groups * entry->height;
	masks = entry->data + words * 4;
	pixels = entry->data;
	height = entry->height;
	assert(x >= SIDEBAR_X && y >= SIDEBAR_Y && y + entry->height <= SIDEBAR_Y + SIDEBAR_HEIGHT);
	if (localY > s_clipBottom || localX > s_clipRight) {
		GUI_Sidebar_FragmentEnd();
		return;
	}
	if (localY < s_clipTop) {
		uint16 skip = s_clipTop - localY;
		if (skip >= height) {
			GUI_Sidebar_FragmentEnd();
			return;
		}
		pixels += skip * groups * 4;
		masks += skip * groups;
		height -= skip;
		localY += skip;
	}
	height = min(height, s_clipBottom - localY + 1);
	if (localX < s_clipLeft || localX + entry->width - 1 > s_clipRight) {
		uint16 group, row;
		for (group = 0; group < groups; group++) {
			int16 start = localX + group * 16;
			int16 left = max(0, s_clipLeft - start), right = min(15, s_clipRight - start);
			uint16 mask = left > right ? 0 : (0xffffu >> left) & (0xffffu << (15 - right));
			for (row = 0; row < height; row++) clipped[row * groups + group] = masks[row * groups + group] & mask;
		}
		masks = clipped;
	}
	Video_Atari_ComposePlanarSprite(s_pixels, s_masks, SIDEBAR_WIDTH, SIDEBAR_HEIGHT,
	    pixels, masks, entry->width, height, localX, localY);
	if (s_captureDepth != 0) {
		uint16 row, group, shift = localX & 15;
		for (row = 0; row < height; row++) {
			for (group = 0; group < groups; group++) {
				uint16 dstGroup = (localX >> 4) + group, mask = masks[row * groups + group];
				if (dstGroup < SIDEBAR_GROUPS) GUI_Sidebar_Record(localY + row, dstGroup, mask >> shift);
				if (shift != 0 && dstGroup + 1 < SIDEBAR_GROUPS)
					GUI_Sidebar_Record(localY + row, dstGroup + 1, mask << (16 - shift));
			}
		}
		GUI_Sidebar_FragmentEnd();
	}
}
