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
#include "../string.h"
#include "../unit.h"
#include "../structure.h"
#include "../table/strings.h"
#include "../video/video.h"
#include "../video/atari_sidebar.h"

enum { SIDEBAR_X = 256, SIDEBAR_Y = 42, SIDEBAR_WIDTH = 64, SIDEBAR_HEIGHT = 82,
       SIDEBAR_GROUPS = 4, SIDEBAR_SPRITE_FIRST = 24, SIDEBAR_SPRITE_LAST = 105,
       SIDEBAR_SPRITES = SIDEBAR_SPRITE_LAST - SIDEBAR_SPRITE_FIRST + 1, SIDEBAR_STATS_Y = 88,
       SIDEBAR_STATS_HEIGHT = SIDEBAR_Y + SIDEBAR_HEIGHT - SIDEBAR_STATS_Y,
       SIDEBAR_OPAQUE_CODE_BYTES = 82 };

typedef struct SidebarSprite {
	uint16 width, height;
	VideoAtariSidebarBlit *blits[16];
	uint16 blitWidths[16];
	uint16 *masks;
	uint16 data[];
} SidebarSprite;

/* Solid 32x24 portraits share this buffer for both compact CPU and replicated BLITTER masks. */
static uint16 s_opaqueSpriteMasks[2 * 24 * 4];

/* Pixels (4 words per group); only transparent/padded sprites also own compact and replicated masks. */
static SidebarSprite *s_sprites[SIDEBAR_SPRITES];

/* Destination of the primitives: the sidebar's top-left group in a planar surface. */
static uint16 *s_dst;
static uint16 s_stride;
static bool s_active, s_valid, s_complete;
static uint16 s_generation;
static int16 s_clipLeft, s_clipTop, s_clipRight, s_clipBottom;

struct SidebarCaptions g_sidebarCaptions;
static struct SidebarAssets {
	SidebarAsset background, productionFace[2];
	SidebarAsset portraitFrame[2], damageGauge, separator;
} s_sidebar;
static struct {
	uint16 index, type, house, objectType, mode;
	bool down, valid;
} s_production;
static uint16 *s_assetBank;
static const uint16 *s_statsBackgroundCode, *s_repairBackgroundCode, *s_titleBackgroundCode;
static size_t s_assetBytes, s_assetUsed;
static SidebarAsset *s_caption;
static const Widget *s_captionWidget;
static bool s_batch, s_capturing, s_preparing;
typedef struct SidebarPrepared {
	struct SidebarPrepared *next;
	SidebarAsset *asset;
	size_t pixelBytes, codeBytes;
	bool masked;
	uint16 data[];
} SidebarPrepared;
static SidebarPrepared *s_prepared, **s_preparedTail;
static uint8 *s_chrome, *s_buttonTemplate;
static struct {
	int16 top, bottom, x, y;
	uint16 width, height;
	bool ready;
} s_template;
static Screen s_captureScreen;

static bool GUI_Sidebar_Assets(void)
{
	return s_active && s_batch && !s_capturing;
}

static void GUI_Sidebar_CaptureBegin(void)
{
	assert(s_preparing && !s_capturing);
	s_captureScreen = GFX_Screen_SetActive(SCREEN_1);
	s_active = false;
	s_capturing = true;
}

static void GUI_Sidebar_CaptureEnd(void)
{
	GFX_Screen_SetActive(s_captureScreen);
	s_active = true;
	s_capturing = false;
}

static void GUI_Sidebar_RestoreChrome(int16 top, int16 bottom)
{
	uint8 *screen = GFX_Screen_Get_ByIndex(SCREEN_1);

	for (int16 row = top; row <= bottom; row++)
		memcpy(screen + row * SCREEN_WIDTH + SIDEBAR_X,
		    s_chrome + (row - SIDEBAR_Y) * SIDEBAR_WIDTH, SIDEBAR_WIDTH);
}

static void GUI_Sidebar_RestoreButton(const Widget *w, int16 top, int16 bottom)
{
	uint8 *screen = GFX_Screen_Get_ByIndex(SCREEN_1);
	bool same = s_template.ready && s_template.top == top && s_template.bottom == bottom &&
	    s_template.x == w->offsetX && s_template.y == w->offsetY &&
	    s_template.width == w->width && s_template.height == w->height;

	if (!same) {
		GUI_Sidebar_RestoreChrome(top, bottom);
		GUI_DrawWiredRectangle(w->offsetX - 1, w->offsetY - 1,
		    w->offsetX + w->width, w->offsetY + w->height, 12);
		GUI_DrawBorderRepeating(w->offsetX, w->offsetY, w->width, w->height, 1);
		s_template.top = top; s_template.bottom = bottom;
		s_template.x = w->offsetX; s_template.y = w->offsetY;
		s_template.width = w->width; s_template.height = w->height;
		s_template.ready = true;
	}
	for (int16 row = top; row <= bottom; row++) {
		uint8 *dst = screen + row * SCREEN_WIDTH + SIDEBAR_X;
		uint8 *cached = s_buttonTemplate + (row - top) * SIDEBAR_WIDTH;
		if (same) memcpy(dst, cached, SIDEBAR_WIDTH);
		else memcpy(cached, dst, SIDEBAR_WIDTH);
	}
}

/* Geometry owns opacity: palette index zero may be an opaque black pixel. */
static void GUI_Sidebar_AssetLoad(SidebarAsset *entry, int16 x, int16 y,
                                int16 left, int16 top, uint16 width, uint16 height,
                                const uint16 *masks)
{
	uint16 count = width / 16 * height;
	size_t pixelsBytes = count * (masks == NULL ? 4 : 8) * sizeof(uint16);
	SidebarPrepared *prepared = malloc(sizeof(*prepared) + pixelsBytes);

	if (prepared == NULL) {
		Error("Out of memory preparing sidebar asset\n");
		exit(1);
	}
	assert(left >= SIDEBAR_X && left + width <= SCREEN_WIDTH && (left & 15) == 0);
	assert(top >= SIDEBAR_Y && top + height <= SIDEBAR_Y + SIDEBAR_HEIGHT);
	entry->width = width; entry->height = height;
	entry->dx = left - x; entry->dy = top - y;
	prepared->asset = entry;
	prepared->pixelBytes = pixelsBytes;
	prepared->masked = masks != NULL;
	prepared->codeBytes = 82;
	prepared->next = NULL;
	Video_Atari_EncodePlanarStrided((uint8 *)GFX_Screen_Get_ByIndex(SCREEN_1) +
	    top * SCREEN_WIDTH + left, SCREEN_WIDTH, prepared->data, width, height);
	if (masks != NULL) {
		uint16 set = 0, clear = 0;
		for (uint16 group = 0; group < count; group++) {
			for (uint16 plane = 0; plane < 4; plane++) {
				uint16 mask = masks[group];
				uint16 *pixel = &prepared->data[group * 4 + plane];
				set |= *pixel & mask;
				clear |= (uint16)~*pixel & mask;
				*pixel &= mask;
				prepared->data[count * 4 + group * 4 + plane] = mask;
			}
		}
		/* Aligned masked commands have a 50-byte header/return and 32 bytes per pass. */
		prepared->codeBytes = 50 + (set != 0 ? 32 : 0) + (clear != 0 ? 32 : 0);
	}
	*s_preparedTail = prepared;
	s_preparedTail = &prepared->next;
	s_assetBytes += pixelsBytes + prepared->codeBytes;
	entry->ready = true;
}

static void GUI_Sidebar_AssetDraw(const SidebarAsset *entry, int16 x, int16 y)
{
	if (entry->width == 0) return;
	if (s_preparing) return;
	x += entry->dx; y += entry->dy;
	Video_Atari_QueueSidebarBlit(entry->code,
	    s_dst + (y - SIDEBAR_Y) * s_stride + ((x - SIDEBAR_X) >> 4) * 4);
}

bool GUI_Sidebar_Active(void) { return s_active; }
bool GUI_Sidebar_FlatButtons(const Widget *w)
{
	return Video_Atari_CursorDirect() && w->parentID == 0 && w->index >= 4 && w->index <= 11 &&
	    w->offsetX > SIDEBAR_X && w->offsetY > SIDEBAR_Y &&
	    w->offsetX + w->width < SIDEBAR_X + SIDEBAR_WIDTH &&
	    w->offsetY + w->height < SIDEBAR_Y + SIDEBAR_HEIGHT;
}
bool GUI_Sidebar_Valid(void)
{
	return s_valid && s_generation == Video_Atari_GetPaletteGeneration();
}
void GUI_Sidebar_Invalidate(void) { s_valid = false; s_production.valid = false; }

void GUI_Sidebar_Free(void)
{
	uint16 i;

	assert(!s_active);
	Video_Atari_DisplayListFlush();
	memset(&s_sidebar, 0, sizeof(s_sidebar));
	memset(&g_sidebarCaptions, 0, sizeof(g_sidebarCaptions));
	free(s_assetBank);
	s_assetBank = NULL;
	s_statsBackgroundCode = NULL;
	s_repairBackgroundCode = NULL;
	s_titleBackgroundCode = NULL;
	s_assetBytes = s_assetUsed = 0;
	s_caption = NULL;
	s_captionWidget = NULL;
	for (i = 0; i < SIDEBAR_SPRITES; i++) {
		uint16 phase;
		if (s_sprites[i] != NULL)
			for (phase = 0; phase < 16; phase++) free(s_sprites[i]->blits[phase]);
		free(s_sprites[i]);
		s_sprites[i] = NULL;
	}
	s_valid = false;
	s_production.valid = false;
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
	if (s_assetBank == NULL && Video_Atari_ViewportBlitter())
		GUI_Sidebar_Preload();
	s_dst = Video_Atari_LiveBegin(SIDEBAR_X, SIDEBAR_Y, SIDEBAR_WIDTH, SIDEBAR_HEIGHT);
	s_stride = VIDEO_ATARI_LIVE_STRIDE;
	s_active = true;
	s_complete = true;
	s_clipLeft = s_clipTop = 0;
	s_clipRight = SIDEBAR_WIDTH - 1;
	s_clipBottom = SIDEBAR_HEIGHT - 1;
	s_batch = Video_Atari_ViewportBlitter();
	if (s_batch) Video_Atari_DisplayListBegin();
}

void GUI_Sidebar_End(void)
{
	assert(s_active);
	if (s_batch) Video_Atari_DisplayListEnd();
	s_active = false;
	Video_Atari_LiveEnd(SIDEBAR_X, SIDEBAR_Y, SIDEBAR_WIDTH, SIDEBAR_HEIGHT);
	/* A widget-only update cannot validate the rest of a replaced panel. */
	s_valid |= s_complete;
}

static void GUI_Sidebar_RestoreBand(const uint16 *code, int16 top, int16 bottom)
{
	if (GUI_Sidebar_Assets()) {
		Video_Atari_QueueSidebarBlit(code, s_dst + (top - SIDEBAR_Y) * s_stride);
	} else {
		int16 oldTop = s_clipTop, oldBottom = s_clipBottom;

		s_clipTop = top - SIDEBAR_Y;
		s_clipBottom = bottom - SIDEBAR_Y;
		GUI_Widget_DrawBorder(6, 0, false);
		s_clipTop = oldTop;
		s_clipBottom = oldBottom;
	}
}

void GUI_Sidebar_RestoreStats(void)
{
	GUI_Sidebar_RestoreBand(s_statsBackgroundCode, SIDEBAR_STATS_Y, SIDEBAR_Y + SIDEBAR_HEIGHT - 1);
}

void GUI_Sidebar_RestoreTitle(void)
{
	GUI_Sidebar_RestoreBand(s_titleBackgroundCode, SIDEBAR_Y, 50);
}

void GUI_Sidebar_RestoreRepair(const Widget *w)
{
	const Widget *portrait = GUI_Widget_Get_ByIndex(g_widgetLinkedListHead, 6);
	const Widget *production = GUI_Widget_Get_ByIndex(g_widgetLinkedListHead, 5);
	int16 top = w->offsetY - 1, bottom = w->offsetY + w->height;

	GUI_Sidebar_RestoreBand(s_repairBackgroundCode, top, bottom);
	/* Preserve the neighboring outlines that share the button's first/last rows. */
	if (portrait != NULL && !portrait->flags.invisible &&
	    portrait->offsetY + portrait->height >= top && portrait->offsetY + portrait->height <= bottom)
		GUI_DrawLine(portrait->offsetX - 1, portrait->offsetY + portrait->height,
		    portrait->offsetX + portrait->width, portrait->offsetY + portrait->height, 12);
	if (production != NULL && !production->flags.invisible &&
	    production->offsetY - 1 >= top && production->offsetY - 1 <= bottom)
		GUI_DrawLine(production->offsetX - 1, production->offsetY - 1,
		    production->offsetX + production->width, production->offsetY - 1, 12);
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

typedef struct SidebarFill {
	int16 left, top, right, bottom;
	uint8 colour;
} SidebarFill;

static void GUI_Sidebar_RunFill(const void *data)
{
	const SidebarFill *fill = data;
	GUI_Sidebar_FillTo(s_dst, s_stride, fill->left, fill->top, fill->right, fill->bottom, fill->colour);
}

void GUI_Sidebar_Fill(int16 left, int16 top, int16 right, int16 bottom, uint8 colour)
{
	if (GUI_Sidebar_Assets()) {
		SidebarFill *fill;
		if (s_preparing) return;
		fill = Video_Atari_QueueSidebarCPU(GUI_Sidebar_RunFill, sizeof(*fill));
		*fill = (SidebarFill){ left, top, right, bottom, colour };
		return;
	}
	GUI_Sidebar_FillTo(s_dst, s_stride, left, top, right, bottom, colour);
}

bool GUI_Sidebar_WidgetBorder(uint16 widgetIndex, uint16 borderType, bool pressed)
{
	const WidgetProperties *w = &g_widgetProperties[widgetIndex];
	int16 x = w->xBase * 8, y = w->yBase;

	if (!GUI_Sidebar_Assets() || widgetIndex != 6 || borderType != 0 || pressed) return false;
	s_production.valid = false;
	if (!s_sidebar.background.ready) {
		GUI_Sidebar_CaptureBegin();
		GUI_Widget_DrawBorder(widgetIndex, borderType, pressed);
		GUI_Sidebar_CaptureEnd();
		for (uint16 row = 0; row < SIDEBAR_HEIGHT; row++)
			memcpy(s_chrome + row * SIDEBAR_WIDTH,
			    (uint8 *)GFX_Screen_Get_ByIndex(SCREEN_1) +
			    (SIDEBAR_Y + row) * SCREEN_WIDTH + SIDEBAR_X, SIDEBAR_WIDTH);
		GUI_Sidebar_AssetLoad(&s_sidebar.background, x, y, SIDEBAR_X, SIDEBAR_Y,
		    SIDEBAR_WIDTH, SIDEBAR_HEIGHT, NULL);
	}
	GUI_Sidebar_AssetDraw(&s_sidebar.background, x, y);
	return true;
}

static bool GUI_Sidebar_ButtonAsset(const Widget *w, bool flat)
{
	SidebarAsset *entry;
	int16 left = w->offsetX, top = w->offsetY;
	uint16 width = w->width, height = w->height;

	if (!GUI_Sidebar_Assets() || w->index != 5) return false;
	entry = &s_sidebar.productionFace[flat];
	if (!entry->ready) {
		GUI_Sidebar_CaptureBegin();
		GUI_Sidebar_RestoreButton(w, top - 1, top + height);
		if (flat) GUI_DrawWiredRectangle(left, top, left + width - 1, top + height - 1, 20);
		GUI_Sidebar_CaptureEnd();
		GUI_Sidebar_AssetLoad(entry, left, top, SIDEBAR_X, top - 1,
		    SIDEBAR_WIDTH, height + 2, NULL);
	}
	GUI_Sidebar_AssetDraw(entry, left, top);
	return true;
}

bool GUI_Sidebar_ButtonFrame(const Widget *w, bool down)
{
	return GUI_Sidebar_ButtonAsset(w, down);
}

bool GUI_Sidebar_ProductionImage(const Widget *w, const Structure *s)
{
	uint16 mode = g_productionStringID;
	bool redraw;

	if (!GUI_Sidebar_Assets() || !GUI_Sidebar_FlatButtons(w)) return true;
	switch (mode) {
		case STR_PLACE_IT: case STR_COMPLETED: case STR_ON_HOLD:
		case STR_BUILD_IT: case STR_D_DONE:
			mode = STR_BUILD_IT;
			break;
		default: break;
	}
	redraw = !s_production.valid || s_production.index != s->o.index ||
	    s_production.type != s->o.type || s_production.house != s->o.houseID ||
	    s_production.objectType != s->objectType || s_production.mode != mode ||
	    s_production.down != w->state.hover2;
	s_production.index = s->o.index;
	s_production.type = s->o.type;
	s_production.house = s->o.houseID;
	s_production.objectType = s->objectType;
	s_production.mode = mode;
	s_production.down = w->state.hover2;
	s_production.valid = true;
	return redraw;
}

void GUI_Sidebar_ProductionPercent(const Widget *w, bool upgrading)
{
	if (!GUI_Sidebar_Assets()) return;
	GUI_Sidebar_AssetDraw(upgrading ? &g_sidebarCaptions.productionUpgradePercent[w->state.hover2] :
	    &g_sidebarCaptions.productionPercent[w->state.hover2],
	    w->offsetX + w->width / 2, w->offsetY + w->height - (upgrading ? 19 : 9));
}

static void GUI_Sidebar_MaskRect(uint16 *masks, uint16 width, int16 left, int16 top,
                                int16 x1, int16 y1, int16 x2, int16 y2)
{
	for (int16 y = y1; y <= y2; y++)
		for (int16 x = x1; x <= x2; x++)
			masks[(y - top) * (width / 16) + ((x - left) >> 4)] |=
			    0x8000u >> ((x - left) & 15);
}

static void GUI_Sidebar_MaskBorder(uint16 *masks, uint16 width, int16 left, int16 top,
                                  int16 x1, int16 y1, int16 x2, int16 y2)
{
	GUI_Sidebar_MaskRect(masks, width, left, top, x1, y1, x2, y1);
	GUI_Sidebar_MaskRect(masks, width, left, top, x1, y2, x2, y2);
	GUI_Sidebar_MaskRect(masks, width, left, top, x1, y1, x1, y2);
	GUI_Sidebar_MaskRect(masks, width, left, top, x2, y1, x2, y2);
}

bool GUI_Sidebar_DamageGauge(void)
{
	if (!GUI_Sidebar_Assets()) return false;
	if (!s_sidebar.damageGauge.ready) {
		uint16 masks[SIDEBAR_HEIGHT * 2] = {0}, glyphs[16 * 8] = {0};
		uint8 opacity[32 * SIDEBAR_HEIGHT] = {0};
		GUITextState text;
		const char *label = String_Get_ByIndex(STR_DMG);
		uint16 height;
		GUI_Sidebar_CaptureBegin();
		GUI_DrawBorder(292, 51, 26, 9, 1, false);
		GUI_DrawSprite(SCREEN_ACTIVE, g_sprites[27], 27, GUI_SPRITE_COLOUR_EMBEDDED, 292, 60, 0, 0);
		GUI_DrawText_Wrapper(label, 296, 65, 29, 0, 0x11);
		GUI_TextState_Get(&text);
		height = 65 + text.font->height - 51;
		GUI_Sidebar_MaskBorder(masks, 32, 288, 51, 292, 51, 317, 59);
		GUI_DrawSpriteOpacity(opacity, 32, height, g_sprites[27], 4, 9);
		for (uint16 y = 0; y < height; y++)
			for (uint16 x = 0; x < 32; x++)
				if (opacity[y * 32 + x] != 0)
					masks[y * 2 + (x >> 4)] |= 0x8000u >> (x & 15);
		assert(text.font->height <= 16);
		GUI_Glyph_Line(text.font, text.colours, label, 8, 2, text.font->height,
		    glyphs, 8, masks + (65 - 51) * 2, 2);
		GUI_Sidebar_CaptureEnd();
		GUI_Sidebar_AssetLoad(&s_sidebar.damageGauge, 292, 51, 288, 51, 32, height, masks);
	} else {
		/* Preserve the legacy caption's font/style side effects without redrawing its glyphs. */
		GUI_DrawText_Wrapper("", 296, 65, 29, 0, 0x11);
	}
	GUI_Sidebar_AssetDraw(&s_sidebar.damageGauge, 292, 51);
	return true;
}

bool GUI_Sidebar_Progressbar(uint16 width, uint8 colour, uint8 background)
{
	if (!GUI_Sidebar_Assets()) return false;
	if (!s_preparing)
		Video_Atari_QueueSidebarHealth(s_dst + (52 - SIDEBAR_Y) * s_stride + ((288 - SIDEBAR_X) >> 4) * 4,
		    width, Video_Atari_GetPalettePen(colour), Video_Atari_GetPalettePen(background));
	return true;
}

bool GUI_Sidebar_PortraitFrame(const Widget *w, bool down)
{
	if (!GUI_Sidebar_Assets()) return false;
	if (!s_sidebar.portraitFrame[down].ready) {
		uint16 masks[SIDEBAR_HEIGHT * SIDEBAR_GROUPS] = {0};
		int16 left = (w->offsetX - 1) & ~15, top = w->offsetY - 1;
		uint16 width = ((w->offsetX + w->width + 16) & ~15) - left;
		uint16 height = w->height + 2;
		GUI_Sidebar_CaptureBegin();
		GUI_DrawWiredRectangle(w->offsetX - 1, w->offsetY - 1,
		    w->offsetX + w->width, w->offsetY + w->height, 12);
		if (down) {
			GUI_DrawWiredRectangle(w->offsetX, w->offsetY,
			    w->offsetX + w->width - 1, w->offsetY + w->height - 1, 20);
		} else {
			GUI_DrawBorder(w->offsetX, w->offsetY, w->width, w->height, 1, false);
		}
		GUI_Sidebar_MaskBorder(masks, width, left, top, w->offsetX - 1, top,
		    w->offsetX + w->width, w->offsetY + w->height);
		GUI_Sidebar_MaskBorder(masks, width, left, top, w->offsetX, w->offsetY,
		    w->offsetX + w->width - 1, w->offsetY + w->height - 1);
		GUI_Sidebar_CaptureEnd();
		GUI_Sidebar_AssetLoad(&s_sidebar.portraitFrame[down], w->offsetX, w->offsetY,
		    left, top, width, height, masks);
	}
	GUI_Sidebar_AssetDraw(&s_sidebar.portraitFrame[down], w->offsetX, w->offsetY);
	return true;
}

bool GUI_Sidebar_Separator(void)
{
	if (!GUI_Sidebar_Assets()) return false;
	if (!s_sidebar.separator.ready) {
		uint16 masks[SIDEBAR_GROUPS] = {0};
		GUI_Sidebar_CaptureBegin();
		GUI_DrawLine(261, 95, 312, 95, 16);
		GUI_Sidebar_CaptureEnd();
		GUI_Sidebar_MaskRect(masks, SIDEBAR_WIDTH, SIDEBAR_X, 95, 261, 95, 312, 95);
		GUI_Sidebar_AssetLoad(&s_sidebar.separator, 261, 95, SIDEBAR_X, 95,
		    SIDEBAR_WIDTH, 1, masks);
	}
	GUI_Sidebar_AssetDraw(&s_sidebar.separator, 261, 95);
	return true;
}

void GUI_Sidebar_CaptionBegin(SidebarAsset *image, const Widget *w)
{
	assert(s_caption == NULL);
	if (GUI_Sidebar_Assets()) {
		s_caption = image;
		s_captionWidget = w;
	}
}

void GUI_Sidebar_CaptionEnd(void)
{
	s_caption = NULL;
	s_captionWidget = NULL;
}

bool GUI_Sidebar_DrawButtonCaption(int16 centre, int16 top, uint8 foreground, uint8 background)
{
	const Widget *w = s_captionWidget;
	uint8 colours[2] = { background, foreground };

	if (s_caption == NULL || !s_caption->ready || w == NULL || w->index == 5 ||
	    !GUI_Sidebar_Assets() || background != 0 || !GUI_Glyph_Usable(g_fontCurrent)) return false;
	if (!GUI_Sidebar_FlatButtons(w) || centre != w->offsetX + w->width / 2 || top != w->offsetY + 1 ||
	    s_caption->width != SIDEBAR_WIDTH || s_caption->height != w->height + 2 ||
	    top + g_fontCurrent->height > SIDEBAR_Y + SIDEBAR_HEIGHT) return false;
	GUI_InitColors(colours, 0, 1);
	GUI_Sidebar_AssetDraw(s_caption, centre, top);
	return true;
}

bool GUI_Sidebar_Border(int16 left, int16 top, uint16 width, uint16 height, const uint8 colours[4], bool fill)
{
	int16 x0 = left - SIDEBAR_X, y0 = top - SIDEBAR_Y;
	uint16 groups[16], i;

	if (!s_active || !fill || width < 2 || height < 3) return false;
	if (x0 < s_clipLeft || x0 + (int16)width - 1 > s_clipRight || y0 < s_clipTop || y0 + (int16)height - 1 > s_clipBottom) return false;
	if (x0 < 0 || y0 < 0 || y0 + (int16)height > SIDEBAR_HEIGHT || x0 + (int16)width > SIDEBAR_GROUPS * 16) return false;
	if (GUI_Sidebar_Assets()) {
		return false;
	}
	for (i = 0; i < 4; i++) Planar_SolidGroup(groups + i * 4, Video_Atari_GetPalettePen(colours[i]));
	Planar_DrawBorder(s_dst + y0 * s_stride, s_stride, x0, width, height, groups);
	return true;
}

typedef struct SidebarText {
	Font *font;
	int16 spacing, x, y;
	uint8 colours[16];
	bool character;
	char string[];
} SidebarText;

static void GUI_Sidebar_RunText(const void *data)
{
	const SidebarText *text = data;
	Font *font = g_fontCurrent;
	int16 spacing = g_fontCharOffset;
	bool batch = s_batch;

	s_batch = false;
	g_fontCurrent = text->font;
	g_fontCharOffset = text->spacing;
	if (text->character) {
		GUI_Sidebar_Char((unsigned char)text->string[0], text->x, text->y, text->colours);
	} else if (!GUI_Sidebar_Text(text->string, text->x, text->y, text->colours)) {
		Error("Unsupported sidebar text at playback\n");
		exit(1);
	}
	g_fontCurrent = font;
	g_fontCharOffset = spacing;
	s_batch = batch;
}

static void GUI_Sidebar_QueueText(const char *string, int16 x, int16 y, const uint8 colours[16], bool character)
{
	size_t bytes = strlen(string) + 1;
	SidebarText *text;

	if (s_preparing) return;
	text = Video_Atari_QueueSidebarCPU(GUI_Sidebar_RunText, sizeof(*text) + bytes);
	text->font = g_fontCurrent;
	text->spacing = g_fontCharOffset;
	text->x = x; text->y = y;
	memcpy(text->colours, colours, sizeof(text->colours));
	text->character = character;
	memcpy(text->string, string, bytes);
}

void GUI_Sidebar_Char(unsigned char c, uint16 x, uint16 y, const uint8 colours[16])
{
	uint16 planes[16 * 4], masks[16] = { 0 }, row;
	const char text[2] = { (char)c, '\0' };
	if (GUI_Sidebar_Assets()) {
		GUI_Sidebar_QueueText(text, x, y, colours, true);
		return;
	}
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
	if ((left < SIDEBAR_X && s_caption == NULL) || top < SIDEBAR_Y ||
	    top + height > SIDEBAR_Y + SIDEBAR_HEIGHT) return false;
	px = max(left - SIDEBAR_X, 0);
	group = px >> 4;
	if (group >= SIDEBAR_GROUPS) return false;
	if (GUI_Sidebar_Assets()) {
		if (!GUI_Glyph_Usable(g_fontCurrent) || colours[0] != 0) return false;
		if (s_caption != NULL) {
			/* Text-button images do not need a measured text edge as their drawing anchor. */
			int16 anchor = s_captionWidget != NULL && s_captionWidget->index != 5 ?
			    s_captionWidget->offsetX + s_captionWidget->width / 2 : left;
			if (!s_caption->ready) {
				int16 bandTop = top, bandBottom;
				uint16 lines = 1;
				const char *line = string + strcspn(string, "\n\r");

				while (*line != '\0') {
					while (*line == '\n' || *line == '\r') line++;
					if (*line == '\0') break;
					lines++;
					line += strcspn(line, "\n\r");
				}
				bandBottom = min(top + lines * height - 1, SIDEBAR_Y + SIDEBAR_HEIGHT - 1);
				if (s_captionWidget != NULL) {
					const Widget *w = s_captionWidget;
					bandTop = w->index == 5 ? top : w->offsetY - 1;
					bandBottom = w->offsetY + w->height;
				}
				GUI_Sidebar_CaptureBegin();
				if (s_captionWidget != NULL) {
					GUI_Sidebar_RestoreButton(s_captionWidget, bandTop, bandBottom);
				} else GUI_Sidebar_RestoreChrome(bandTop, bandBottom);
				if (s_caption == &g_sidebarCaptions.power) GUI_DrawLine(261, 95, 312, 95, 16);
				/* Native captions skip edge-crossing glyphs instead of wrapping them.
				 * Draw the same cells with the original chunky text primitive. */
				{
					int16 x = left, y = top;
					for (const char *c = string; *c != '\0'; c++) {
						char cell[2] = {*c, '\0'};
						if (*c == '\n' || *c == '\r') {
							while (*c == '\n' || *c == '\r') c++;
							if (*c == '\0') break;
							x = left; y += height;
							cell[0] = *c;
						}
						if (y >= SIDEBAR_Y + SIDEBAR_HEIGHT) break;
						if (x >= 0 && x + Font_GetCharWidth((unsigned char)*c) <= SCREEN_WIDTH)
							GUI_DrawText(cell, x, y, colours[1], colours[0]);
						x += Font_GetCharWidth((unsigned char)*c);
					}
				}
				if (s_captionWidget != NULL && s_captionWidget->state.hover2) {
					const Widget *w = s_captionWidget;
					GUI_DrawWiredRectangle(w->offsetX, w->offsetY,
					    w->offsetX + w->width - 1, w->offsetY + w->height - 1, 20);
				}
				GUI_Sidebar_CaptureEnd();
				GUI_Sidebar_AssetLoad(s_caption, anchor, top, SIDEBAR_X, bandTop,
				    SIDEBAR_WIDTH, bandBottom - bandTop + 1, NULL);
			}
			GUI_Sidebar_AssetDraw(s_caption, anchor, top);
		} else {
			GUI_Sidebar_QueueText(string, left, top, colours, false);
		}
		return true;
	}
	if (left < SIDEBAR_X) {
		int16 x = left, y = top;
		for (const char *c = string; *c != '\0'; c++) {
			uint16 advance;
			if (*c == '\n' || *c == '\r') {
				while (*c == '\n' || *c == '\r') c++;
				if (*c == '\0') break;
				x = left; y += height;
			}
			if (y >= SIDEBAR_Y + SIDEBAR_HEIGHT) break;
			advance = Font_GetCharWidth((unsigned char)*c);
			if (x + advance <= SCREEN_WIDTH)
				GUI_Sidebar_Char((unsigned char)*c, x, y, colours);
			x += advance;
		}
		return true;
	}
	/* Glyphs that do not fit before the screen edge are skipped, not clipped. Each line break
	 * restarts at the same left edge one font line lower; the caller provides the room. */
	if (GUI_Glyph_Line(g_fontCurrent, colours, string, px & 15, SIDEBAR_GROUPS - group, height,
	    s_dst + (top - SIDEBAR_Y) * s_stride + group * 4, s_stride,
	    NULL, SIDEBAR_GROUPS) == GLYPH_LINE_UNSUPPORTED) return false;
	for (string += strcspn(string, "\n\r"); *string != '\0'; string += strcspn(string, "\n\r")) {
		while (*string == '\n' || *string == '\r') string++;
		top += height;
		if (top >= SIDEBAR_Y + SIDEBAR_HEIGHT) break;
		GUI_Glyph_Line(g_fontCurrent, colours, string, px & 15, SIDEBAR_GROUPS - group,
		    min(height, SIDEBAR_Y + SIDEBAR_HEIGHT - top),
		    s_dst + (top - SIDEBAR_Y) * s_stride + group * 4, s_stride,
		    NULL, SIDEBAR_GROUPS);
	}
	return true;
}

static bool GUI_Sidebar_SpriteOpaque(uint16 spriteID, uint16 width, uint16 height)
{
	/* Stock SHAPES.SHP rectangles; changed geometry keeps the generic opacity decoder. */
	if (spriteID >= 24 && spriteID <= 26) {
		uint16 size = spriteID == 24 ? 5 : 8;
		return width == size && height == size;
	}
	return ((spriteID >= 28 && spriteID <= 30) || (spriteID >= 65 && spriteID <= 105)) &&
	    width == 32 && height == 24;
}

bool GUI_Sidebar_PortraitOpaque(uint16 spriteID)
{
	const uint8 *sprite = g_sprites[spriteID];
	uint16 width = READ_LE_UINT16(sprite + 3);

	return width == 32 && GUI_Sidebar_SpriteOpaque(spriteID, width, sprite[2]);
}

static void GUI_Sidebar_DecodeSprite(const uint8 *sprite, uint16 width, uint16 height,
                                    uint16 *pixels, uint16 *masks, bool opaque)
{
	union { uint32 align; uint8 bytes[64 * 48]; } chunky;
	uint16 row, col, groups = width >> 4;

	if (!opaque) {
		assert(masks != NULL);
		memset(masks, 0, groups * height * sizeof(*masks));
		memset(chunky.bytes, 0, width * height);
		GUI_DrawSpriteOpacity(chunky.bytes, width, height, sprite, 0, 0);
		for (row = 0; row < height; row++)
			for (col = 0; col < width; col++)
				if (chunky.bytes[row * width + col] != 0)
					masks[row * groups + (col >> 4)] |= 0x8000u >> (col & 15);
	} else if (masks != NULL) {
		uint16 mask = 0xffffu << (16 - READ_LE_UINT16(sprite + 3));
		assert(groups == 1);
		for (row = 0; row < height; row++) masks[row] = mask;
	}
	if (masks != NULL) memset(chunky.bytes, 0, width * height);
	GUI_DrawSpriteToBuffer(chunky.bytes, width, height, sprite, 0, 0);
	Video_Atari_EncodePlanar(chunky.bytes, pixels, width, height);
	if (masks != NULL)
		for (row = 0; row < groups * height; row++)
			for (col = 0; col < 4; col++) pixels[row * 4 + col] &= masks[row];
}

void GUI_Sidebar_Sprite(const uint8 *sprite, uint16 spriteID, int16 x, int16 y,
                        int flags, const uint8 *remap, uint16 remapCount)
{
	SidebarSprite *entry;
	uint16 groups, words;
	const uint16 *masks, *pixels;
	uint16 height;
	int16 localX = x - SIDEBAR_X, localY = y - SIDEBAR_Y;

	if (spriteID < SIDEBAR_SPRITE_FIRST || spriteID > SIDEBAR_SPRITE_LAST ||
	    (flags & ~DRAWSPRITE_FLAG_REMAP) != 0 || remapCount != 0) {
		Error("Unsupported sidebar sprite request %u (flags %04x, remap %u)\n",
		    spriteID, (unsigned int)flags, remapCount);
		exit(1);
	}
	assert(g_sprites[spriteID] == sprite);
	VARIABLE_NOT_USED(remap);
	entry = s_sprites[spriteID - SIDEBAR_SPRITE_FIRST];
	if (entry == NULL) {
		uint16 sourceWidth = READ_LE_UINT16(sprite + 3);
		uint16 width = (sourceWidth + 15) & ~15;
		uint16 height = sprite[2];
		uint16 row, column;
		bool opaque = GUI_Sidebar_SpriteOpaque(spriteID, sourceWidth, height);
		bool sharedMasks = opaque && sourceWidth == width;
		if (width == 0 || width > 64 || height == 0 || height > 48) {
			Error("Unsupported sidebar sprite %u (%ux%u)\n", spriteID, width, height);
			exit(1);
		}
		groups = width >> 4;
		words = groups * height;
		entry = calloc(1, sizeof(*entry) + words * (sharedMasks ? 4 : 9) * sizeof(uint16));
		if (entry == NULL) {
			Error("Out of memory for sidebar sprite %u\n", spriteID);
			exit(1);
		}
		entry->width = width;
		entry->height = height;
		entry->masks = sharedMasks ? s_opaqueSpriteMasks : entry->data + words * 4;
		if (sharedMasks && s_opaqueSpriteMasks[0] == 0)
			memset(s_opaqueSpriteMasks, 0xff, sizeof(s_opaqueSpriteMasks));
		GUI_Sidebar_DecodeSprite(sprite, width, height, entry->data,
		    sharedMasks ? NULL : entry->masks, opaque);
		if (!sharedMasks)
			for (row = 0; row < words; row++)
				for (column = 0; column < 4; column++)
					entry->masks[words + row * 4 + column] = entry->masks[row];
		s_sprites[spriteID - SIDEBAR_SPRITE_FIRST] = entry;
	}
	groups = entry->width >> 4;
	words = groups * entry->height;
	masks = entry->masks;
	pixels = entry->data;
	height = entry->height;
	assert(localX >= 0 && localY >= 0 && localY + height <= SIDEBAR_HEIGHT);
	if (GUI_Sidebar_Assets()) {
		uint16 phase = localX & 15;
		uint16 visibleWidth = min(entry->width, SIDEBAR_WIDTH - localX);
		VideoAtariSidebarBlit *code = entry->blits[phase];
		if (code != NULL && entry->blitWidths[phase] != visibleWidth) {
			Video_Atari_DisplayListFlush();
			free(code);
			code = NULL;
		}
		if (code == NULL) {
			code = malloc(sizeof(*code));
			if (code == NULL) {
				Error("Out of memory for sidebar sprite command\n");
				exit(1);
			}
			Video_Atari_CompileSidebarBlit(code, pixels,
			    masks == s_opaqueSpriteMasks ? NULL : masks + words,
			    entry->width, visibleWidth, height, phase);
			entry->blits[phase] = code;
			entry->blitWidths[phase] = visibleWidth;
		}
		if (!s_preparing)
			Video_Atari_QueueSidebarBlit(code->words, s_dst + localY * s_stride + (localX >> 4) * 4);
		return;
	}
	Video_Atari_BlitPlanarSprite(s_dst + localY * s_stride, s_stride, SIDEBAR_GROUPS,
	    pixels, masks, entry->width, height, localX);
}

static void GUI_Sidebar_PrepareCaption(SidebarAsset *caption, const Widget *w,
                                      uint16 stringID, int16 x, int16 y, uint8 colour)
{
	if (stringID == STR_NULL) return;
	GUI_Sidebar_UseButtonCaption(*caption, w);
	GUI_DrawText_Wrapper(String_Get_ByIndex(stringID), x, y, colour, 0, 0x121);
	GUI_Sidebar_CaptionEnd();
}

static void GUI_Sidebar_PrepareBlank(SidebarAsset *caption, const Widget *w, int16 y)
{
	GUITextState text;

	GUI_DrawText_Wrapper(NULL, 0, 0, 15, 0, 0x121);
	GUI_TextState_Get(&text);
	GUI_Sidebar_UseButtonCaption(*caption, w);
	if (!GUI_Sidebar_Text("", w->offsetX + w->width / 2, y, text.colours)) {
		Error("Unsupported sidebar percentage background\n");
		exit(1);
	}
	GUI_Sidebar_CaptionEnd();
}

static void GUI_Sidebar_PrepareAssets(void)
{
	Widget *command, *repair, *cancel, *production, *portrait;
	uint16 i, state;

	command = GUI_Widget_Get_ByIndex(g_widgetLinkedListHead, 8);
	repair = GUI_Widget_Get_ByIndex(g_widgetLinkedListHead, 4);
	cancel = GUI_Widget_Get_ByIndex(g_widgetLinkedListHead, 7);
	production = GUI_Widget_Get_ByIndex(g_widgetLinkedListHead, 5);
	portrait = GUI_Widget_Get_ByIndex(g_widgetLinkedListHead, 6);
	GUI_Sidebar_WidgetBorder(6, 0, false);
	GUI_Sidebar_DamageGauge();
	GUI_Sidebar_Separator();
	GUI_Sidebar_UseCaption(g_sidebarCaptions.power);
	GUI_DrawText_Wrapper(String_Get_ByIndex(STR_POWER_INFONEEDEDOUTPUT), 258, 88, 29, 0, 0x11);
	GUI_Sidebar_CaptionEnd();
	GUI_Sidebar_UseCaption(g_sidebarCaptions.starport);
	GUI_DrawText_Wrapper(String_Get_ByIndex(STR_FRIGATE_INORBIT_ANDAWAITINGORDER), 258, 88, 29, 0, 0x11);
	GUI_Sidebar_CaptionEnd();
	for (i = 0; i < 3; i++) {
		static const uint16 titles[] = { STR_TARGET, STR_MOVEMENT, STR_HARVEST };
		GUI_Sidebar_UseCaption(g_sidebarCaptions.title[i]);
		GUI_DrawText_Wrapper(String_Get_ByIndex(titles[i]), 288, 43, 29, 0, 0x111);
		GUI_Sidebar_CaptionEnd();
	}
	for (state = 0; state < 2; state++) {
		if (portrait != NULL) GUI_Sidebar_PortraitFrame(portrait, state);
		if (production != NULL) {
			Widget w = *production;
			w.state.hover2 = state;
			GUI_Sidebar_ButtonAsset(production, state);
			for (i = STR_PLACE_IT; i <= STR_SABOTEUR; i++)
				GUI_Sidebar_PrepareCaption(&g_sidebarCaptions.production[i - STR_PLACE_IT][state], &w, i,
				    w.offsetX + w.width / 2, w.offsetY + w.height - 9, i == STR_PLACE_IT ? 239 : 15);
			GUI_Sidebar_PrepareBlank(&g_sidebarCaptions.productionPercent[state], &w,
			    w.offsetY + w.height - 9);
			GUI_Sidebar_PrepareBlank(&g_sidebarCaptions.productionUpgradePercent[state], &w,
			    w.offsetY + w.height - 19);
		}
		if (repair != NULL) {
			Widget w = *repair;
			w.state.hover2 = state;
			GUI_Sidebar_PrepareCaption(&g_sidebarCaptions.repair[state], &w, STR_REPAIR,
			    w.offsetX + w.width / 2, w.offsetY + 1, 239);
		}
	}
	for (state = 0; state < 3; state++) {
		Widget w = *command;
		uint8 colour = state == 1 ? 6 : 15;
		int16 x = command->offsetX + command->width / 2, y = command->offsetY + 1;
		w.state.hover2 = state == 2;
		for (i = 0; i < ACTION_MAX; i++)
			GUI_Sidebar_PrepareCaption(&g_sidebarCaptions.action[i][state], &w,
			    g_table_actionInfo[i].stringID, x, y, colour);
		if (repair != NULL) {
			w = *repair; w.state.hover2 = state == 2;
			x = repair->offsetX + repair->width / 2; y = repair->offsetY + 1;
			GUI_Sidebar_PrepareCaption(&g_sidebarCaptions.repairing[state], &w, STR_REPAIRING, x, y, colour);
			GUI_Sidebar_PrepareCaption(&g_sidebarCaptions.upgrade[state], &w, STR_UPGRADE, x, y, colour);
			GUI_Sidebar_PrepareCaption(&g_sidebarCaptions.upgrading[state], &w, STR_UPGRADING, x, y, colour);
		}
		if (cancel != NULL) {
			w = *cancel; w.state.hover2 = state == 2;
			GUI_Sidebar_PrepareCaption(&g_sidebarCaptions.cancel[state], &w, STR_CANCEL,
			    cancel->offsetX + cancel->width / 2, cancel->offsetY + 1, colour);
		}
	}
}

void GUI_Sidebar_Preload(void)
{
	GUITextState text, chunky;
	Screen screen;
	uint8 *saved;
	const uint16 *backgroundPixels = NULL;
	const Widget *repair = GUI_Widget_Get_ByIndex(g_widgetLinkedListHead, 4);

	if (!Video_Atari_CursorDirect() || !Video_Atari_ViewportBlitter() ||
	    GUI_Widget_Get_ByIndex(g_widgetLinkedListHead, 8) == NULL) return;
	GUI_TextState_Get(&text);
	chunky = text;
	chunky.planarTarget = NULL;
	chunky.planarAllowed = false;
	GUI_TextState_Set(&chunky);
	GUI_Sidebar_Free();
	saved = malloc(SCREEN_WIDTH * SCREEN_HEIGHT + 2 * SIDEBAR_WIDTH * SIDEBAR_HEIGHT);
	if (saved == NULL) {
		Error("Out of memory for sidebar chunky workspace\n");
		exit(1);
	}
	memcpy(saved, GFX_Screen_Get_ByIndex(SCREEN_1), SCREEN_WIDTH * SCREEN_HEIGHT);
	s_chrome = saved + SCREEN_WIDTH * SCREEN_HEIGHT;
	s_buttonTemplate = s_chrome + SIDEBAR_WIDTH * SIDEBAR_HEIGHT;
	s_template.ready = false;
	screen = GFX_Screen_SetActive(SCREEN_1);
	s_generation = Video_Atari_GetPaletteGeneration();
	s_prepared = NULL;
	s_preparedTail = &s_prepared;
	/* Setup selects asset interception only; it never opens a live screen/list batch. */
	s_active = s_batch = s_preparing = true;
	GUI_DrawText_Wrapper(NULL, 0, 0, 15, 0, 0x11);
	GUI_Sidebar_PrepareAssets();
	s_active = s_batch = s_preparing = false;
	s_assetBytes += SIDEBAR_OPAQUE_CODE_BYTES * (repair != NULL ? 3 : 2);
	s_assetBank = malloc(s_assetBytes);
	if (s_assetBank == NULL) {
		Error("Out of memory for sidebar assets (%lu bytes)\n", (unsigned long)s_assetBytes);
		exit(1);
	}
	while (s_prepared != NULL) {
		SidebarPrepared *prepared = s_prepared;
		SidebarAsset *asset = prepared->asset;
		VideoAtariSidebarBlit code;
		uint16 *pixels = s_assetBank + s_assetUsed / sizeof(uint16);
		uint16 *compiled = pixels + prepared->pixelBytes / sizeof(uint16);
		size_t bytes;
		memcpy(pixels, prepared->data, prepared->pixelBytes);
		bytes = Video_Atari_CompileSidebarBlit(&code, pixels,
		    prepared->masked ? pixels + asset->width / 16 * asset->height * 4 : NULL,
		    asset->width, asset->width, asset->height, 0);
		if (bytes != prepared->codeBytes) {
			Error("Sidebar command geometry changed (%lu/%lu bytes)\n",
			    (unsigned long)bytes, (unsigned long)prepared->codeBytes);
			exit(1);
		}
		memcpy(compiled, code.words, bytes);
		asset->code = compiled;
		if (asset == &s_sidebar.background) backgroundPixels = pixels;
		s_assetUsed += prepared->pixelBytes + bytes;
		s_prepared = prepared->next;
		free(prepared);
	}
	for (uint16 band = 0; band < (repair != NULL ? 3 : 2); band++) {
		VideoAtariSidebarBlit code;
		uint16 *compiled = s_assetBank + s_assetUsed / sizeof(uint16);
		uint16 top = band == 0 ? SIDEBAR_STATS_Y : band == 1 ? SIDEBAR_Y : repair->offsetY - 1;
		uint16 height = band == 0 ? SIDEBAR_STATS_HEIGHT : band == 1 ? 51 - SIDEBAR_Y : repair->height + 2;
		size_t bytes;

		assert(backgroundPixels != NULL);
		/* Borrow the background's pixels; only the clipped copy command is new. */
		bytes = Video_Atari_CompileSidebarBlit(&code,
		    backgroundPixels + (top - SIDEBAR_Y) * SIDEBAR_GROUPS * 4,
		    NULL, SIDEBAR_WIDTH, SIDEBAR_WIDTH, height, 0);
		if (bytes != SIDEBAR_OPAQUE_CODE_BYTES) {
			Error("Sidebar background command size changed (%lu bytes)\n", (unsigned long)bytes);
			exit(1);
		}
		memcpy(compiled, code.words, bytes);
		if (band == 0) s_statsBackgroundCode = compiled;
		else if (band == 1) s_titleBackgroundCode = compiled;
		else s_repairBackgroundCode = compiled;
		s_assetUsed += bytes;
	}
	if (s_assetUsed != s_assetBytes) {
		Error("Sidebar asset bank size changed during preparation (%lu/%lu bytes)\n",
		    (unsigned long)s_assetUsed, (unsigned long)s_assetBytes);
		exit(1);
	}
	memcpy(GFX_Screen_Get_ByIndex(SCREEN_1), saved, SCREEN_WIDTH * SCREEN_HEIGHT);
	free(saved);
	s_chrome = NULL;
	s_buttonTemplate = NULL;
	s_template.ready = false;
	GFX_Screen_SetActive(screen);
	GUI_TextState_Set(&text);
	/* Preparation has not replaced any pixels of the visible panel. */
	s_valid = false;
}
