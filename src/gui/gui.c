/** @file src/gui/gui.c Generic GUI definitions. */

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include "types.h"
#include "../os/common.h"
#include "../os/math.h"
#include "../os/sleep.h"
#include "../os/strings.h"
#include "../os/endian.h"
#include "../os/error.h"

#include "gui.h"

#include "font.h"
#include "mentat.h"
#include "widget.h"
#include "../animation.h"
#include "../audio/driver.h"
#include "../audio/sound.h"
#include "../codec/format80.h"
#include "../config.h"
#include "../explosion.h"
#include "../file.h"
#include "../gfx.h"
#include "../house.h"
#include "../ini.h"
#include "../input/input.h"
#include "../input/mouse.h"
#include "../load.h"
#include "../map.h"
#include "../opendune.h"
#include "../pool/pool.h"
#include "../pool/house.h"
#include "../pool/structure.h"
#include "../pool/unit.h"
#include "../sprites.h"
#include "../string.h"
#include "../structure.h"
#include "../table/strings.h"
#include "../tile.h"
#include "../timer.h"
#include "../tools.h"
#include "../unit.h"
#include "../video/video.h"
#include "../wsa.h"

MSVC_PACKED_BEGIN
typedef struct ClippingArea {
	/* 0000(2)   */ PACK uint16 left;                       /*!< ?? */
	/* 0002(2)   */ PACK uint16 top;                        /*!< ?? */
	/* 0004(2)   */ PACK uint16 right;                      /*!< ?? */
	/* 0006(2)   */ PACK uint16 bottom;                     /*!< ?? */
} GCC_PACKED ClippingArea;
MSVC_PACKED_END
assert_compile(sizeof(ClippingArea) == 0x08);

MSVC_PACKED_BEGIN
typedef struct StrategicMapData {
	/* 0000(2)   */ PACK int16 index;      /*!< ?? */
	/* 0002(2)   */ PACK int16 arrow;      /*!< ?? */
	/* 0004(2)   */ PACK int16 offsetX;    /*!< ?? */
	/* 0006(2)   */ PACK int16 offsetY;    /*!< ?? */
} GCC_PACKED StrategicMapData;
MSVC_PACKED_END
assert_compile(sizeof(StrategicMapData) == 0x8);

/** Coupling between score and rank name. */
typedef struct RankScore {
	uint16 rankString; /*!< StringID of the name of the rank. */
	uint16 score;      /*!< Score needed to obtain the rank. */
} RankScore;

/** Mapping of scores to rank names. */
static const RankScore _rankScores[] = {
	{271,   25}, /* "Sand Flea" */
	{272,   50}, /* "Sand Snake" */
	{273,  100}, /* "Desert Mongoose" */
	{274,  150}, /* "Sand Warrior" */
	{275,  200}, /* "Dune Trooper" */
	{276,  300}, /* "Squad Leader" */
	{277,  400}, /* "Outpost Commander" */
	{278,  500}, /* "Base Commander" */
	{279,  700}, /* "Warlord" */
	{280, 1000}, /* "Chief Warlord" */
	{281, 1400}, /* "Ruler of Arrakis" */
	{282, 1800}  /* "Emperor" */
};

static uint8 g_colours[16];		/*!< Colors used for drawing chars */
static ClippingArea g_clipping = { 0, 0, SCREEN_WIDTH - 1, SCREEN_HEIGHT - 1 };
uint8 *g_palette_998A = NULL;
uint8 g_remap[256];
FactoryWindowItem g_factoryWindowItems[25];
uint16 g_factoryWindowOrdered = 0;
uint16 g_factoryWindowBase = 0;
uint16 g_factoryWindowTotal = 0;
uint16 g_factoryWindowSelected = 0;
uint16 g_factoryWindowUpgradeCost = 0;
bool g_factoryWindowConstructionYard = false;
FactoryResult g_factoryWindowResult = FACTORY_RESUME;
bool g_factoryWindowStarport = false;
static uint8 s_factoryWindowGraymapTbl[256];
static Widget s_factoryWindowWidgets[13];
static uint8 s_factoryWindowWsaBuffer[64000];
static uint8 *s_palette1_houseColour;
static uint32 s_tickCreditsAnimation = 0;                   /*!< Next tick when credits animation needs an update. */
static uint32 s_arrowAnimationTimeout = 0;                  /*!< Timeout value for the next palette change in the animation of the arrows. */
static uint16 s_arrowAnimationState = 0;                    /*!< State of the arrow animation. @see _arrowAnimationTimeout */
static uint16 s_temporaryColourBorderSchema[5][4];          /*!< Temporary storage for the #s_colourBorderSchema. */
uint16 g_productionStringID;                                /*!< Descriptive text of activity of the active structure. */
bool g_textDisplayNeedsUpdate;                              /*!< If set, text display needs to be updated. */
uint32 g_strategicRegionBits;                               /*!< Region bits at the map. */
static uint32 s_ticksPlayed;
bool g_doQuitHOF;
static uint8 s_strategicMapArrowColors[24];
static bool s_strategicMapFastForward;
static uint8 s_strategicMapTextBgColor;	/*!< Chrome parchment colour under the message
                                             *   strip, sampled once from SCREEN_2 right after
                                             *   MAPMACH.CPS loads. SCREEN_2 is later reused as a
                                             *   scratch heap by Sprites_CPS_LoadRegionClick()
                                             *   (RGNCLK.CPS pixels + REGION?.INI contents), so it
                                             *   can no longer be sampled directly once that has
                                             *   run; caching this single byte up front keeps
                                             *   GUI_StrategicMap_DrawText()'s background fill
                                             *   correct for every subsequent message. */

static uint16 s_mouseSpriteLeft;
static uint16 s_mouseSpriteTop;
static uint16 s_mouseSpriteWidth;
static uint16 s_mouseSpriteHeight;

uint16 g_mouseSpriteHotspotX;
uint16 g_mouseSpriteHotspotY;
uint16 g_mouseWidth;
uint16 g_mouseHeight;

uint16 g_cursorSpriteID;
uint16 g_cursorDefaultSpriteID;

bool g_structureHighHealth;                                 /*!< If false, the repair button will flash. */
bool g_var_37B8;

uint16 g_viewportMessageCounter;                            /*!< Countdown counter for displaying #g_viewportMessageText, bit 0 means 'display the text'. */
const char *g_viewportMessageText;                          /*!< If not \c NULL, message text displayed in the viewport. */

uint16 g_viewportPosition;                                  /*!< Top-left tile of the viewport. */
uint16 g_minimapPosition;                                   /*!< Top-left tile of the border in the minimap. */
uint16 g_selectionRectanglePosition;                        /*!< Position of the structure selection rectangle. */
uint16 g_selectionPosition;                                 /*!< Current selection position (packed). */
uint16 g_selectionWidth;                                    /*!< Width of the selection. */
uint16 g_selectionHeight;                                   /*!< Height of the selection. */
int16  g_selectionState = 1;                                /*!< State of the selection (\c 1 is valid, \c 0 is not valid, \c <0 valid but missing some slabs. */


/*!< Colours used for the border of widgets. */
static uint16 s_colourBorderSchema[5][4] = {
	{ 26,  29,  29,  29},
	{ 20,  26,  16,  20},
	{ 20,  16,  26,  20},
	{233, 235, 232, 233},
	{233, 232, 235, 233}
};

/** Colours used for the border of widgets in the hall of fame. */
static const uint16 s_HOF_ColourBorderSchema[5][4] = {
	{226, 228, 228, 228},
	{116, 226, 105, 116},
	{116, 105, 226, 116},
	{233, 235, 232, 233},
	{233, 232, 235, 233}
};

assert_compile(lengthof(s_colourBorderSchema) == lengthof(s_temporaryColourBorderSchema));
assert_compile(lengthof(s_colourBorderSchema) == lengthof(s_HOF_ColourBorderSchema));

/**
 * Draw a wired rectangle.
 * @param left The left position of the rectangle.
 * @param top The top position of the rectangle.
 * @param right The right position of the rectangle.
 * @param bottom The bottom position of the rectangle.
 * @param colour The colour of the rectangle.
 */
void GUI_DrawWiredRectangle(uint16 left, uint16 top, uint16 right, uint16 bottom, uint8 colour)
{
	GUI_DrawLine(left, top, right, top, colour);
	GUI_DrawLine(left, bottom, right, bottom, colour);
	GUI_DrawLine(left, top, left, bottom, colour);
	GUI_DrawLine(right, top, right, bottom, colour);

#ifndef TOS
	GFX_Screen_SetDirtySource(DIRTY_SRC_RECT);
	GFX_Screen_SetDirty(SCREEN_ACTIVE, left, top, right+1, bottom+1);
#endif
}

/**
 * Draw a filled rectangle.
 * @param left The left position of the rectangle.
 * @param top The top position of the rectangle.
 * @param right The right position of the rectangle.
 * @param bottom The bottom position of the rectangle.
 * @param colour The colour of the rectangle.
 */
void GUI_DrawFilledRectangle(int16 left, int16 top, int16 right, int16 bottom, uint8 colour)
{
	uint16 x;
	uint16 y;
	uint16 height;
	uint16 width;

	uint8 *screen = GFX_Screen_GetActive();

	if (left >= SCREEN_WIDTH) return;
	if (left < 0) left = 0;

	if (top >= SCREEN_HEIGHT) return;
	if (top < 0) top = 0;

	if (right >= SCREEN_WIDTH) right = SCREEN_WIDTH - 1;
	if (right < 0) right = 0;

	if (bottom >= SCREEN_HEIGHT) bottom = SCREEN_HEIGHT - 1;
	if (bottom < 0) bottom = 0;

	if (left > right) return;
	if (top > bottom) return;

	width = right - left + 1;
	height = bottom - top + 1;

#ifdef TOS
	/* EXPERIMENT: skip-write style barrier -- on ST/STE direct-cursor
	 * builds, skip the chunky memset entirely and fill the planar screen
	 * straight away instead (a solid colour fill has a direct planar
	 * equivalent, so there is no need to write SCREEN_0 at all here). */
	if (GFX_Screen_IsActive(SCREEN_0) && Video_Atari_CursorDirect()) {
		Video_Atari_PresentFill(left, top, width, height, colour);
		return;
	}
#endif

	screen += left + top * SCREEN_WIDTH;
	for (y = 0; y < height; y++) {
		/* TODO : use memset() */
		for (x = 0; x < width; x++) {
			*screen++ = colour;
		}
		screen += SCREEN_WIDTH - width;
	}

	GFX_Screen_SetDirtySource(DIRTY_SRC_RECT);
	GFX_Screen_SetDirty(SCREEN_ACTIVE, left, top, right + 1, bottom + 1);
}

/**
 * Display a text.
 * @param str The text to display. If \c NULL, update the text display (scroll text, and/or remove it on time out).
 * @param importance Importance of the new text. Value \c -1 means remove all text lines, \c -2 means drop all texts in buffer but not yet displayed.
 *                   Otherwise, it is the importance of the message (if supplied). Higher numbers mean displayed sooner.
 * @param ... The args for the text.
 */
void GUI_DisplayText(const char *str, int importance, ...)
{
	char buffer[80];                 /* Formatting buffer of new message. */
	static uint32 displayTimer = 0;  /* Timeout value for next update of the display. */
	static uint16 textOffset;        /* Vertical position of text being scrolled. */
	static bool scrollInProgress;    /* Text is being scrolled (and partly visible to the user). */

	static char displayLine1[80];    /* Current line being displayed. */
	static char displayLine2[80];    /* Next line (if scrollInProgress, it is scrolled up). */
	static char displayLine3[80];    /* Next message to display (after scrolling next line has finished). */
	static int16 line1Importance;    /* Importance of the displayed line of text. */
	static int16 line2Importance;    /* Importance of the next line of text. */
	static int16 line3Importance;    /* Importance of the next message. */
	static uint8 fgColour1;          /* Foreground colour current line. */
	static uint8 fgColour2;          /* Foreground colour next line. */
	static uint8 fgColour3;          /* Foreground colour next message. */
#ifdef TOS
	static uint16 bannerPlanar[24 * SCREEN_WIDTH / 4];
	static bool bannerPlanarReady;
#endif

	buffer[0] = '\0';

	if (str != NULL) {
		va_list ap;

		va_start(ap, importance);
		vsnprintf(buffer, sizeof(buffer), str, ap);
		va_end(ap);
	}

	if (importance == -1) { /* Remove all displayed lines. */
		line1Importance = -1;
		line2Importance = -1;
		line3Importance = -1;

		displayLine1[0] = '\0';
		displayLine2[0] = '\0';
		displayLine3[0] = '\0';

		scrollInProgress = false;
		displayTimer = 0;
#ifdef TOS
		bannerPlanarReady = false;
#endif
		return;
	}

	if (importance == -2) { /* Remove next line and next message. */
		if (!scrollInProgress) {
			line2Importance = -1;
			displayLine2[0] = '\0';
		}
		line3Importance = -1;
		displayLine3[0] = '\0';
	}

	if (!scrollInProgress) {
		if (buffer[0] != '\0') {
			/* Insert a new, distinct message according to its importance. */
			if (strcasecmp(buffer, displayLine1) != 0 && strcasecmp(buffer, displayLine2) != 0 && strcasecmp(buffer, displayLine3) != 0) {
				if (importance >= line2Importance) {
					strncpy(displayLine3, displayLine2, sizeof(displayLine3));
					fgColour3 = fgColour2;
					line3Importance = line2Importance;
					strncpy(displayLine2, buffer, sizeof(displayLine2));
					fgColour2 = 12;
					line2Importance = importance;
				} else if (importance >= line3Importance) {
					strncpy(displayLine3, buffer, sizeof(displayLine3));
					line3Importance = importance;
					fgColour3 = 12;
				}
			}
		} else {
			if (displayLine1[0] == '\0' && displayLine2[0] == '\0') return;
		}

		if (line2Importance <= line1Importance && displayTimer >= g_timerGUI) return;

		scrollInProgress = true;
#ifdef TOS
		bannerPlanarReady = false;
#endif
		textOffset = (g_announcementPhase == 0) ? 0 : 10;
		displayTimer = 0;
		if (g_announcementPhase != 0) return;
	}

	if (scrollInProgress) {
		uint16 oldWidgetId;
		uint16 height;

		if (buffer[0] != '\0') {
			if (strcasecmp(buffer, displayLine2) != 0 && importance >= line3Importance) {
				strncpy(displayLine3, buffer, sizeof(displayLine3));
				line3Importance = importance;
			}
		}
		if (displayTimer > g_timerGUI) return;

		oldWidgetId = Widget_SetCurrentWidget(7);

		if (g_textDisplayNeedsUpdate) {
			Screen oldScreenID = GFX_Screen_SetActive(SCREEN_1);

			GUI_DrawFilledRectangle(0, 0, SCREEN_WIDTH - 1, 23, g_curWidgetFGColourNormal);

			GUI_DrawText_Wrapper(displayLine2, g_curWidgetXBase << 3,  2, fgColour2, 0, 0x012);
			GUI_DrawText_Wrapper(displayLine1, g_curWidgetXBase << 3, 13, fgColour1, 0, 0x012);

			g_textDisplayNeedsUpdate = false;
#ifdef TOS
			bannerPlanarReady = false;
#endif

			GFX_Screen_SetActive(oldScreenID);
		}

		GUI_Mouse_Hide_InWidget(7);

		if (textOffset + g_curWidgetHeight > 24) {
			height = 24 - textOffset;
		} else {
			height = g_curWidgetHeight;
		}

#ifdef TOS
		if (Video_Atari_CursorDirect()) {
			if (!bannerPlanarReady) {
				Video_Atari_EncodePlanar(GFX_Screen_Get_ByIndex(SCREEN_1), bannerPlanar, SCREEN_WIDTH, 24);
				bannerPlanarReady = true;
			}
			Video_Atari_PresentPlanarWindow(bannerPlanar + textOffset * (SCREEN_WIDTH / 4),
			                               g_curWidgetXBase << 3, g_curWidgetYBase,
			                               g_curWidgetWidth << 3, height);
		} else
#endif
		GUI_Screen_Copy(g_curWidgetXBase, textOffset, g_curWidgetXBase, g_curWidgetYBase, g_curWidgetWidth, height, SCREEN_1, SCREEN_0);
		GUI_Mouse_Show_InWidget();

		Widget_SetCurrentWidget(oldWidgetId);

		if (textOffset != 0) {
			if (line3Importance <= line2Importance) {
				displayTimer = g_timerGUI + 1;
			}
			textOffset -= min(textOffset, g_announcementPhase);
			return;
		}

		/* Finished scrolling, move line 2 to line 1. */
		strncpy(displayLine1, displayLine2, sizeof(displayLine1));
		fgColour1 = fgColour2;
		line1Importance = (line2Importance != 0) ? line2Importance - 1 : 0;

		/* And move line 3 to line 2. */
		strncpy(displayLine2, displayLine3, sizeof(displayLine2));
		line2Importance = line3Importance;
		fgColour2 = fgColour3;
		displayLine3[0] = '\0';

		line3Importance = -1;
		g_textDisplayNeedsUpdate = true;
		displayTimer = g_timerGUI + (line2Importance <= line1Importance ? 900 : 1);
		scrollInProgress = false;
		return;
	}
}

/**
 * Draw a char on the screen.
 *
 * @param c The char to draw.
 * @param x The most left position where to draw the string.
 * @param y The most top position where to draw the string.
 */
static void GUI_DrawChar(unsigned char c, uint16 x, uint16 y)
{
	uint8 *screen;

	FontChar *fc;

	uint16 remainingWidth;
	uint8 i;
	uint8 j;
	const uint8 * fontData;
	uint16 startX = x;
	uint16 startY = y;
#ifdef TOS
	/* EXPERIMENT: sized generously above any font this codebase actually
	 * loads (6p/8p UI fonts, the larger intro font); guarded by the size
	 * check below regardless, so an unexpectedly large glyph just falls
	 * back to the old direct-SCREEN_0 path instead of overflowing this. */
	uint8 glyphBuf[32 * 32];
	bool toPlanar;
#endif

	if (g_fontCurrent == NULL) return;

	fc = &g_fontCurrent->chars[c];
	if (fc->data == NULL) return;

	if (x >= SCREEN_WIDTH || (x + fc->width) > SCREEN_WIDTH) return;
	if (y >= SCREEN_HEIGHT || (y + g_fontCurrent->height) > SCREEN_HEIGHT) return;

#ifdef TOS
	toPlanar = GFX_Screen_IsActive(SCREEN_0) && Video_Atari_CursorDirect() &&
	           fc->width <= 32 && g_fontCurrent->height <= 32;

	if (toPlanar) {
		/* Write into a small private scratch buffer instead of SCREEN_0.
		 * SCREEN_0 is not reliably maintained any more (most writers skip
		 * it entirely), so "leave this byte untouched" can no longer mean
		 * "transparent, background shows through" -- the byte could be
		 * stale garbage. A freshly zeroed private buffer restores that
		 * guarantee: 0 really does mean "not drawn here" for
		 * Video_Atari_PresentChunkyTransparent() below, which merges only
		 * the non-zero (opaque) pixels into the planar screen and leaves
		 * every other pixel alone -- no dirty mark needed either, since
		 * the merge already happened. */
		memset(glyphBuf, 0, (size_t)fc->width * g_fontCurrent->height);
		screen = glyphBuf;
		x = 0;
		remainingWidth = 0;
	} else {
		screen = GFX_Screen_GetActive();
		GFX_Screen_SetDirtySource(DIRTY_SRC_TEXT);
		GFX_Screen_SetDirty(SCREEN_ACTIVE, x, y, x + fc->width, y + g_fontCurrent->height);
		x += y * (uint16)SCREEN_WIDTH;
		remainingWidth = SCREEN_WIDTH - fc->width;
	}
#else
	screen = GFX_Screen_GetActive();
	GFX_Screen_SetDirtySource(DIRTY_SRC_TEXT);
	GFX_Screen_SetDirty(SCREEN_ACTIVE, x, y, x + fc->width, y + g_fontCurrent->height);
	x += y * (uint16)SCREEN_WIDTH;
	remainingWidth = SCREEN_WIDTH - fc->width;
#endif

	if (g_colours[0] != 0) {
		/* fill unused lines with g_colours[0] */
		for (j = 0; j < fc->unusedLines; j++) {
			for (i = 0; i < fc->width; i++) screen[x++] = g_colours[0];
			x += remainingWidth;
		}
	} else {
		/* unused lines are left untouched (transparent). Row stride is
		 * fc->width + remainingWidth either way (SCREEN_WIDTH normally,
		 * or the tightly packed glyphBuf width when writing to planar). */
		x += fc->unusedLines * (uint16)(fc->width + remainingWidth);
	}

	if (fc->usedLines == 0) goto l_present;

	fontData = fc->data;
	for (j = 0; j < fc->usedLines; j++) {
		for (i = 0; i < fc->width; i++) {
			uint8 c = g_colours[*fontData++ & 0xF];
			if (c != 0) screen[x] = c;
			x++;
		}
		x += remainingWidth;
	}

	if (g_colours[0] == 0) goto l_present;

	/* fill unused lines with g_colours[0] */
	for (j = fc->unusedLines + fc->usedLines; j < g_fontCurrent->height; j++) {
		for (i = 0; i < fc->width; i++) screen[x++] = g_colours[0];
		x += remainingWidth;
	}

l_present:
#ifdef TOS
	if (toPlanar) {
		Video_Atari_PresentChunkyTransparent(glyphBuf, fc->width,
		                                     startX, startY, fc->width, g_fontCurrent->height);
	}
#endif
	return;
}

/**
 * Draw a string to the screen.
 *
 * @param string The string to draw.
 * @param left The most left position where to draw the string.
 * @param top The most top position where to draw the string.
 * @param fgColour The foreground colour of the text.
 * @param bgColour The background colour of the text.
 */
void GUI_DrawText(const char *string, int16 left, int16 top, uint8 fgColour, uint8 bgColour)
{
	uint8 colours[2];
	uint16 x;
	uint16 y;
	const char *s;

	if (g_fontCurrent == NULL) return;

	if (left < 0) left = 0;
	if (top  < 0) top  = 0;
	if (left > SCREEN_WIDTH) return;
	if (top  > SCREEN_HEIGHT) return;

	colours[0] = bgColour;
	colours[1] = fgColour;

	GUI_InitColors(colours, 0, 1);

	s = string;
	x = left;
	y = top;
	while (*s != '\0') {
		uint16 width;

		if (*s == '\n' || *s == '\r') {
			x = left;
			y += g_fontCurrent->height;

			while (*s == '\n' || *s == '\r') s++;
		}

		width = Font_GetCharWidth(*s);

		if (x + width > SCREEN_WIDTH) {
			x = left;
			y += g_fontCurrent->height;
		}
		if (y > SCREEN_HEIGHT) break;

		GUI_DrawChar(*s, x, y);

		x += width;
		s++;
	}
}

/**
 * Draw a string to the screen, and so some magic.
 *
 * @param string The string to draw.
 * @param left The most left position where to draw the string.
 * @param top The most top position where to draw the string.
 * @param fgColour The foreground colour of the text.
 * @param bgColour The background colour of the text.
 * @param flags The flags of the string.
 *
 * flags :
 * 0x0001 : font 6p
 * 0x0002 : font 8p
 * 0x0010 : style ?
 * 0x0020 : style ?
 * 0x0030 : style ?
 * 0x0040 : style ?
 * 0x0100 : align center
 * 0x0200 : align right
 */
void GUI_DrawText_Wrapper(const char *string, int16 left, int16 top, uint8 fgColour, uint8 bgColour, int flags, ...)
{
	char textBuffer[240];
	static uint16 displayedarg12low = -1;
	static uint16 displayedarg2mid  = -1;

	uint8 arg12low = flags & 0x0F;	/* font : 1 => 6p, 2 => 8p */
	uint8 arg2mid  = flags & 0xF0;	/* style */

	if ((arg12low != displayedarg12low && arg12low != 0) || string == NULL) {
		switch (arg12low) {
			case 1:  Font_Select(g_fontNew6p); break;
			case 2:  Font_Select(g_fontNew8p); break;
			default: Font_Select(g_fontNew8p); break;
		}

		displayedarg12low = arg12low;
	}

	if ((arg2mid != displayedarg2mid && arg2mid != 0) || string == NULL) {
		uint8 colours[16];
		memset(colours, 0, sizeof(colours));

		switch (arg2mid) {
			case 0x0010:
				colours[2] = 0;
				colours[3] = 0;
				g_fontCharOffset = -2;
				break;

			case 0x0020:
				colours[2] = 12;
				colours[3] = 0;
				g_fontCharOffset = -1;
				break;

			case 0x0030:
				colours[2] = 12;
				colours[3] = 12;
				g_fontCharOffset = -1;
				break;

			case 0x0040:
				colours[2] = 232;
				colours[3] = 0;
				g_fontCharOffset = -1;
				break;
		}

		colours[0] = bgColour;
		colours[1] = fgColour;
		colours[4] = 6;

		GUI_InitColors(colours, 0, lengthof(colours) - 1);

		displayedarg2mid = arg2mid;
	}

	if (string == NULL) return;

	{
		va_list ap;

		va_start(ap, flags);
		vsnprintf(textBuffer, sizeof(textBuffer), string, ap);
		va_end(ap);
	}

	switch (flags & 0x0F00) {
		case 0x100:
			left -= Font_GetStringWidth(textBuffer) / 2;
			break;

		case 0x200:
			left -= Font_GetStringWidth(textBuffer);
			break;
	}

	GUI_DrawText(textBuffer, left, top, fgColour, bgColour);
}

/**
 * Shift the given colour toward the reference color.
 * Increment(or decrement) each component (R, G, B) until
 * they equal thoses of the reference color.
 *
 * @param palette The palette to work on.
 * @param colour The colour to modify.
 * @param reference The colour to use as reference.
 * @return true if the colour now equals the reference.
 */
#ifndef TOS
static bool GUI_Palette_ShiftColour(uint8 *palette, uint16 colour, uint16 reference)
{
	bool ret = false;
	uint16 i;

	colour *= 3;
	reference *= 3;

	for (i = 0; i < 3; i++) {
		if (palette[reference] != palette[colour]) {
			ret = true;
			palette[colour] += (palette[colour] > palette[reference]) ? -1 : 1;
		}
		colour++;
		reference++;
	}

	return ret;
}
#endif /* !TOS */

/**
 * Animate the palette. Only works for some colours or something
 */
void GUI_PaletteAnimate(void)
{
#ifndef TOS
	/* On Atari ST/STE, these small per-tick palette-index color-cycle
	 * animations (repair-button flash, selection-rectangle pulse, windtrap
	 * glow) are disabled entirely: the Amiga port of this game does not
	 * animate these UI colors either, and on ST/STE each such change -
	 * however small - forces a costly re-quantization + chunky-pixel pair-
	 * LUT patch (see ATARI_PROFILE_FINDINGS.md / c2p1x1_4_st palette
	 * pipeline). Skipping them altogether removes the single largest
	 * measured cycle cost in profiled play sessions, matching the visual
	 * behavior of another official port rather than introducing a
	 * platform-specific visual regression. */
	static uint32 timerAnimation = 0;
	static uint32 timerSelection = 0;
	static uint32 timerToggle = 0;
	bool shouldSetPalette = false;

	if (timerAnimation < g_timerGUI) {
		/* make the repair button flash */
		static bool animationToggle = false;

		uint16 colour;

		colour = (!g_structureHighHealth && animationToggle) ? 6 : 15;
		if (memcmp(g_palette1 + 3 * 239, g_palette1 + 3 * colour, 3) != 0) {
			memcpy(g_palette1 + 3 * 239, g_palette1 + 3 * colour, 3);
			shouldSetPalette = true;
		}

		animationToggle = !animationToggle;
		timerAnimation = g_timerGUI + 60;
	}

	if (timerSelection < g_timerGUI && g_selectionType != SELECTIONTYPE_MENTAT) {
		/* selection color */
		static uint16 selectionStateColour = 15;

		GUI_Palette_ShiftColour(g_palette1, 255, selectionStateColour);
		GUI_Palette_ShiftColour(g_palette1, 255, selectionStateColour);
		GUI_Palette_ShiftColour(g_palette1, 255, selectionStateColour);

		if (!GUI_Palette_ShiftColour(g_palette1, 255, selectionStateColour)) {
			if (selectionStateColour == 13) {
				selectionStateColour = 15;

				if (g_selectionType == SELECTIONTYPE_PLACE) {
					if (g_selectionState != 0) {
						selectionStateColour = (g_selectionState < 0) ? 5 : 15;
					} else {
						selectionStateColour = 6;
					}
				}
			} else {
				selectionStateColour = 13;
			}
		}

		shouldSetPalette = true;

		timerSelection = g_timerGUI + 3;
	}

	if (timerToggle < g_timerGUI) {
		/* windtrap color */
		static uint16 toggleColour = 12;

		GUI_Palette_ShiftColour(g_palette1, 223, toggleColour);

		if (!GUI_Palette_ShiftColour(g_palette1, 223, toggleColour)) {
			toggleColour = (toggleColour == 12) ? 10 : 12;
		}

		shouldSetPalette = true;

		timerToggle = g_timerGUI + 5;
	}

	if (shouldSetPalette) GFX_SetPalette(g_palette1);
#endif /* !TOS */

	Sound_StartSpeech();
}


/**
 * Sets the activity description to the correct string for the active structure.
 * @see g_productionStringID
 */
void GUI_UpdateProductionStringID(void)
{
	Structure *s = NULL;

	s = Structure_Get_ByPackedTile(g_selectionPosition);

	g_productionStringID = STR_NULL;

	if (s == NULL) return;

	if (!g_table_structureInfo[s->o.type].o.flags.factory) {
		if (s->o.type == STRUCTURE_PALACE) g_productionStringID = STR_LAUNCH + g_table_houseInfo[s->o.houseID].specialWeapon - 1;
		return;
	}

	if (s->o.flags.s.upgrading) {
		g_productionStringID = STR_UPGRADINGD_DONE;
		return;
	}

	if (s->o.linkedID == 0xFF) {
		g_productionStringID = STR_BUILD_IT;
		return;
	}

	if (s->o.flags.s.onHold) {
		g_productionStringID = STR_ON_HOLD;
		return;
	}

	if (s->countDown != 0) {
		g_productionStringID = STR_D_DONE;
		return;
	}

	if (s->o.type == STRUCTURE_CONSTRUCTION_YARD) {
		g_productionStringID = STR_PLACE_IT;
		return;
	}

	g_productionStringID = STR_COMPLETED;
}

static void GUI_Widget_SetProperties(uint16 index, uint16 xpos, uint16 ypos, uint16 width, uint16 height)
{
	g_widgetProperties[index].xBase  = xpos;
	g_widgetProperties[index].yBase  = ypos;
	g_widgetProperties[index].width  = width;
	g_widgetProperties[index].height = height;

	if (g_curWidgetIndex == index) Widget_SetCurrentWidget(index);
}

/**
 * Displays a message and waits for a user action.
 * @param str The text to display.
 * @param spriteID The sprite to draw (0xFFFF for none).
 * @param ... The args for the text.
 * @return ??
 */
uint16 GUI_DisplayModalMessage(const char *str, unsigned int spriteID, ...)
{
	static char textBuffer[768];

	va_list ap;
	uint16 oldWidgetId;
	uint16 ret;
	Screen oldScreenID;
	uint8 *screenBackup = NULL;

#ifdef TOS
	Video_Atari_PlacementHide();
#endif
	va_start(ap, spriteID);
	vsnprintf(textBuffer, sizeof(textBuffer), str, ap);
	va_end(ap);

	GUI_Mouse_Hide_Safe();

	oldScreenID = GFX_Screen_SetActive(SCREEN_0);

	GUI_DrawText_Wrapper(NULL, 0, 0, 0, 0, 0x22);

	oldWidgetId = Widget_SetCurrentWidget(1);

	g_widgetProperties[1].height = g_fontCurrent->height * max(GUI_SplitText(textBuffer, ((g_curWidgetWidth - ((spriteID == 0xFFFF) ? 2 : 7)) << 3) - 6, '\r'), 3) + 18;

	Widget_SetCurrentWidget(1);

	screenBackup = malloc(GFX_GetSize(g_curWidgetWidth * 8, g_curWidgetHeight));

	if (screenBackup != NULL) {
		GFX_CopyToBuffer(g_curWidgetXBase * 8, g_curWidgetYBase, g_curWidgetWidth * 8, g_curWidgetHeight, screenBackup);
	}

	GUI_Widget_DrawBorder(1, 1, 1);

	if (spriteID != 0xFFFF) {
		GUI_DrawSprite(SCREEN_ACTIVE, g_sprites[spriteID], spriteID, GUI_SPRITE_COLOUR_EMBEDDED, 7, 8, 1, DRAWSPRITE_FLAG_WIDGETPOS);
		GUI_Widget_SetProperties(1, g_curWidgetXBase + 5, g_curWidgetYBase + 8, g_curWidgetWidth - 7, g_curWidgetHeight - 16);
	} else {
		GUI_Widget_SetProperties(1, g_curWidgetXBase + 1, g_curWidgetYBase + 8, g_curWidgetWidth - 2, g_curWidgetHeight - 16);
	}

	g_curWidgetFGColourNormal = 0;

	GUI_DrawText(textBuffer, g_curWidgetXBase << 3, g_curWidgetYBase, g_curWidgetFGColourBlink, g_curWidgetFGColourNormal);

	GFX_SetPalette(g_palette1);

	GUI_Mouse_Show_Safe();

	for (g_timerTimeout = 30; g_timerTimeout != 0; sleepIdle()) {
		GUI_PaletteAnimate();
	}

	Input_History_Clear();

	do {
		GUI_PaletteAnimate();

		ret = Input_WaitForValidInput();
		sleepIdle();
	} while (ret == 0 || (ret & 0x800) != 0);

	Input_HandleInput(0x841);

	GUI_Mouse_Hide_Safe();

	if (spriteID != 0xFFFF) {
		GUI_Widget_SetProperties(1, g_curWidgetXBase - 5, g_curWidgetYBase - 8, g_curWidgetWidth + 7, g_curWidgetHeight + 16);
	} else {
		GUI_Widget_SetProperties(1, g_curWidgetXBase - 1, g_curWidgetYBase - 8, g_curWidgetWidth + 2, g_curWidgetHeight + 16);
	}

	if (screenBackup != NULL) {
		GFX_CopyFromBuffer(g_curWidgetXBase * 8, g_curWidgetYBase, g_curWidgetWidth * 8, g_curWidgetHeight, screenBackup);
	}

	Widget_SetCurrentWidget(oldWidgetId);

	if (screenBackup != NULL) {
		free(screenBackup);
	} else {
		g_viewport_forceRedraw = true;
	}

	GFX_Screen_SetActive(oldScreenID);

	GUI_Mouse_Show_Safe();

	return ret;
}

/**
 * Splits the given text in lines of maxwidth width using the given delimiter.
 * @param str The text to split.
 * @param maxwidth The maximum width the text will have.
 * @param delimiter The char used as delimiter.
 * @return The number of lines.
 */
uint16 GUI_SplitText(char *str, uint16 maxwidth, char delimiter)
{
	uint16 lines = 0;

	if (str == NULL) return 0;

	while (*str != '\0') {
		uint16 width = 0;

		lines++;

		while (width < maxwidth && *str != delimiter && *str != '\r' && *str != '\0') width += Font_GetCharWidth(*str++);

		if (width >= maxwidth) {
			while (*str != 0x20 && *str != delimiter && *str != '\r' && *str != '\0') width -= Font_GetCharWidth(*str--);
		}

		if (*str != '\0') *str++ = delimiter;
	}

	return lines;
}

/**
 * Draws a sprite.
 * @param screenID On which screen to draw the sprite.
 * @param sprite The sprite to draw.
 * @param posX position where to draw sprite.
 * @param posY position where to draw sprite.
 * @param windowID The ID of the window where the drawing is done.
 * @param flags The flags.
 * @param ... The extra args, flags dependant.
 *
 * flags :
 * 0x0001 reverse X (void)
 * 0x0002 reverse Y (void)
 * 0x0004 zoom (int zoom_factor_x, int zoomRatioY) UNUSED ?
 * 0x0100 Remap (uint8* remap, int remapCount)
 * 0x0200 blur - SandWorm effect (void)
 * 0x0400 sprite has house colors (set internally, no need to be set by caller)
 * 0x1000 set blur increment value (int) UNUSED ?
 * 0x2000 house colors argument (uint8 houseColors[16])
 * 0x4000 position relative to widget (void)
 * 0x8000 position posX,posY is relative to center of sprite
 *
 * sprite data format :
 * 00: 2 bytes = flags 0x01 = has House colors, 0x02 = NOT Format80 encoded
 * 02: 1 byte  = height
 * 03: 2 bytes = width
 * 05: 1 byte  = height - duplicated (ignored)
 * 06: 2 bytes = sprite data length, including header (ignored)
 * 08: 2 bytes = decoded data length
 * 0A: [16 bytes] = house colors (if flags & 0x01)
 * [1]A: xx bytes = data (depending on flags & 0x02 : 1 = raw, 0 = Format80 encoded)
 */
#ifdef GUI_SPRITE_PREDECODE_STATS
/* One-shot survey for the sprite pre-decode idea: how many distinct
 * sprite x remap-table pairs a real playthrough actually draws, and what
 * decoding them to byte-per-pixel would cost in RAM. Results go to
 * error.log. Build with -DGUI_SPRITE_PREDECODE_STATS_ENABLE. */
#define SPRSTAT_MAX 2048
static struct {
	const uint8 *sprite;
	const uint8 *remap;
	uint32 calls;
	uint32 pixels;
	uint16 decodedLength;
	uint16 spritePal;
} s_sprStat[SPRSTAT_MAX];
static uint16 s_sprStatCount = 0;
static uint32 s_sprStatCalls = 0;
static uint32 s_sprStatOverflow = 0;

static void GUI_Sprite_Stats_Record(const uint8 *sprite, int flags,
                                    const uint8 *remap, int16 w, int16 h,
                                    uint16 decodedLength)
{
	uint16 i;

	/* Only the remap table distinguishes one house from another; the flag
	 * itself is constant across them. */
	if ((flags & DRAWSPRITE_FLAG_REMAP) == 0) remap = NULL;

	s_sprStatCalls++;

	for (i = 0; i < s_sprStatCount; i++) {
		if (s_sprStat[i].sprite == sprite && s_sprStat[i].remap == remap) {
			s_sprStat[i].calls++;
			s_sprStat[i].pixels += (uint32)w * h;
			return;
		}
	}

	if (s_sprStatCount >= SPRSTAT_MAX) { s_sprStatOverflow++; return; }

	s_sprStat[s_sprStatCount].sprite = sprite;
	s_sprStat[s_sprStatCount].remap = remap;
	s_sprStat[s_sprStatCount].calls = 1;
	s_sprStat[s_sprStatCount].pixels = (uint32)w * h;
	s_sprStat[s_sprStatCount].decodedLength = decodedLength;
	s_sprStat[s_sprStatCount].spritePal =
		((flags & DRAWSPRITE_FLAG_SPRITEPAL) != 0) ? 1 : 0;
	s_sprStatCount++;
}

void GUI_Sprite_Stats_Report(void)
{
	uint16 i;
	uint16 distinctSprites = 0;
	uint32 bytesAll = 0, bytesPal = 0;
	uint32 callsPal = 0;
	uint16 pairsPal = 0;

	/* distinct sprite pointers, ignoring the remap dimension */
	for (i = 0; i < s_sprStatCount; i++) {
		uint16 j;
		bool seen = false;

		for (j = 0; j < i; j++) {
			if (s_sprStat[j].sprite == s_sprStat[i].sprite) { seen = true; break; }
		}
		if (!seen) {
			distinctSprites++;
			bytesAll += s_sprStat[i].decodedLength;
		}
		bytesPal += s_sprStat[i].decodedLength;	/* per pair: the pre-decode cost */
		if (s_sprStat[i].spritePal) {
			pairsPal++;
			callsPal += s_sprStat[i].calls;
		}
	}

	Error("SPRSTAT: calls=%lu pairs=%u distinct_sprites=%u overflow=%lu\n",
	      (unsigned long)s_sprStatCalls, (unsigned)s_sprStatCount,
	      (unsigned)distinctSprites, (unsigned long)s_sprStatOverflow);
	Error("SPRSTAT: housecol pairs=%u calls=%lu (%lu%% of calls)\n",
	      (unsigned)pairsPal, (unsigned long)callsPal,
	      (unsigned long)(s_sprStatCalls ? callsPal * 100 / s_sprStatCalls : 0));
	Error("SPRSTAT: decode all sprites once = %lu bytes (%lu KB)\n",
	      (unsigned long)bytesAll, (unsigned long)(bytesAll + 1023) / 1024);
	Error("SPRSTAT: decode per sprite x remap pair = %lu bytes (%lu KB)\n",
	      (unsigned long)bytesPal, (unsigned long)(bytesPal + 1023) / 1024);

	/* the pairs that actually carry the per-pixel palette cost */
	for (i = 0; i < s_sprStatCount; i++) {
		if (s_sprStat[i].spritePal && s_sprStat[i].calls > 20) {
			Error("SPRSTAT:  pair sprite=%p remap=%p calls=%lu px=%lu declen=%u\n",
			      (const void *)s_sprStat[i].sprite, (const void *)s_sprStat[i].remap,
			      (unsigned long)s_sprStat[i].calls,
			      (unsigned long)s_sprStat[i].pixels,
			      (unsigned)s_sprStat[i].decodedLength);
		}
	}
}
#endif /* GUI_SPRITE_PREDECODE_STATS */

#ifdef TOS
/* Shared-buffer batching for GUI_DrawSprite()'s direct-to-planar path.
 * Normally each call composites its own tightly-cropped private scratch
 * buffer straight to planar as soon as it finishes decoding, so drawing
 * several layers on top of each other (e.g. a background sprite plus a
 * handful of digit glyphs, as GUI_DrawCredits() does every animation
 * tick) produces that many separate, immediately-visible planar writes.
 * On real ST/STE hardware the display can be mid-scan between any two
 * of those writes, so a multi-layer update can flicker/tear.
 *
 * A caller that wants several GUI_DrawSprite() calls composited
 * off-screen and presented in one shot can bracket them with
 * GUI_DrawSprite_BeginBatch()/EndBatch(): while active, calls that
 * would otherwise use the private per-call scratch buffer write into
 * the caller-supplied buffer instead (still respecting the RLE
 * transparency of the sprite data, so later layers don't punch holes in
 * earlier ones), and no present happens until EndBatch(). */
static uint8 *s_spriteBatchBuf = NULL;
static uint16 s_spriteBatchStride = 0;
static int16  s_spriteBatchOriginX = 0;
static int16  s_spriteBatchOriginY = 0;
static int16  s_spriteBatchW = 0;
static int16  s_spriteBatchH = 0;
static bool s_spriteBatchOpaque = false;

void GUI_DrawSprite_BeginBatch(uint8 *buffer, int16 originX, int16 originY, int16 width, int16 height)
{
	s_spriteBatchBuf = buffer;
	s_spriteBatchStride = (uint16)width;
	s_spriteBatchOriginX = originX;
	s_spriteBatchOriginY = originY;
	s_spriteBatchW = width;
	s_spriteBatchH = height;
	s_spriteBatchOpaque = false;

	memset(buffer, 0, (size_t)width * height);
}

/* The caller must cover the entire batch, including its background. */
static void GUI_DrawSprite_BeginOpaqueBatch(uint8 *buffer, int16 originX, int16 originY, int16 width, int16 height)
{
	GUI_DrawSprite_BeginBatch(buffer, originX, originY, width, height);
	s_spriteBatchOpaque = true;
}

void GUI_DrawSprite_EndBatch(void)
{
	if (s_spriteBatchBuf != NULL) {
		bool presented;

		if (s_spriteBatchOpaque) {
			presented = Video_Atari_PresentChunky(s_spriteBatchBuf, s_spriteBatchStride,
			                                    s_spriteBatchOriginX, s_spriteBatchOriginY,
			                                    s_spriteBatchStride, s_spriteBatchH);
		} else {
			presented = Video_Atari_PresentChunkyTransparent(s_spriteBatchBuf, s_spriteBatchStride,
			                                               s_spriteBatchOriginX, s_spriteBatchOriginY,
			                                               s_spriteBatchStride, s_spriteBatchH);
		}
		if (!presented) Warning("GUI_DrawSprite_EndBatch: presentation failed\n");
	}

	s_spriteBatchBuf = NULL;
	s_spriteBatchOpaque = false;
}
#endif

static void GUI_DrawSpriteInternal(Screen screenID, const uint8 *sprite, int16 posX, int16 posY,
                                  uint16 windowID, int flags, va_list *ap,
                                  uint8 *target, uint16 targetWidth, uint16 targetHeight);

#ifdef TOS
static bool GUI_ViewportPlanarSprite(const uint8 *sprite, uint16 spriteID, uint8 colourHouse,
                                    int16 x, int16 y, int flags, va_list *ap,
                                    const GUI_SpriteLayers *layers);
#endif

void GUI_DrawSprite(Screen screenID, const uint8 *sprite, uint16 spriteID, uint8 colourHouse,
                    int16 posX, int16 posY, uint16 windowID, int flags, ...)
{
	va_list ap;
	const GUI_SpriteLayers *layers = NULL;
	uint16 i;

	va_start(ap, flags);
	if (flags & DRAWSPRITE_FLAG_LAYERS) {
		layers = va_arg(ap, const GUI_SpriteLayers *);
		assert(layers != NULL && layers->count <= 4);
		flags &= ~DRAWSPRITE_FLAG_LAYERS;
	}
#ifdef TOS
	if (windowID == 2 && GFX_Screen_Get_ByIndex(screenID) == GFX_Screen_Get_ByIndex(SCREEN_0)) {
		va_list cached;
		bool drawn;
		va_copy(cached, ap);
		drawn = GUI_ViewportPlanarSprite(sprite, spriteID, colourHouse, posX, posY, flags, &cached, layers);
		va_end(cached);
		if (drawn) {
			va_end(ap);
			return;
		}
	}
#endif
#ifndef TOS
	VARIABLE_NOT_USED(spriteID);
	VARIABLE_NOT_USED(colourHouse);
#endif
	GUI_DrawSpriteInternal(screenID, sprite, posX, posY, windowID, flags, &ap, NULL, 0, 0);
	va_end(ap);
	if (layers == NULL) return;
	for (i = 0; i < layers->count; i++) {
		const GUI_SpriteLayer *layer = &layers->layer[i];
		GUI_DrawSprite(screenID, g_sprites[layer->spriteID], layer->spriteID, layer->colourHouse,
		               posX + layer->offsetX, posY + layer->offsetY, windowID,
		               layer->flags | DRAWSPRITE_FLAG_CENTER | (flags & DRAWSPRITE_FLAG_WIDGETPOS),
		               layer->palette);
	}
}

#ifdef TOS
void GUI_DrawSpriteToBuffer(uint8 *buffer, uint16 width, uint16 height,
                           const uint8 *sprite, int16 x, int16 y)
{
	assert(buffer != NULL && width > 0 && width <= SCREEN_WIDTH && height > 0 && height <= SCREEN_HEIGHT);
	GUI_DrawSpriteInternal(SCREEN_0, sprite, x, y, 0, 0, NULL, buffer, width, height);
}

#define MINIMAP_ICON_FIRST 31
#define MINIMAP_ICON_COUNT 28

typedef struct MinimapIcon {
	uint8 pixels[9];
	uint8 size;
	uint16 mask;
} MinimapIcon;

static MinimapIcon s_minimapIcons[MINIMAP_ICON_COUNT];

void GUI_FreeMinimapIconCache(void)
{
	memset(s_minimapIcons, 0, sizeof(s_minimapIcons));
	GUI_Widget_Viewport_InvalidateMinimap();
}

void GUI_InitMinimapIconCache(void)
{
	uint16 i;

	GUI_FreeMinimapIconCache();
	if (!Video_Atari_CursorDirect()) return;
	for (i = 0; i < MINIMAP_ICON_COUNT; i++) {
		const uint8 *sprite = g_sprites[MINIMAP_ICON_FIRST + i];
		MinimapIcon *icon = &s_minimapIcons[i];
		uint8 alternate[9];
		uint16 pixel, size;

		if (sprite == NULL) {
			Warning("Minimap icon cache: missing sprite %u\n", MINIMAP_ICON_FIRST + i);
			continue;
		}
		size = sprite[2];
		if ((size != 2 && size != 3) || READ_LE_UINT16(sprite + 3) != size) {
			Warning("Minimap icon cache: unsupported sprite %u\n", MINIMAP_ICON_FIRST + i);
			continue;
		}
		memset(alternate, 0xff, sizeof(alternate));
		GUI_DrawSpriteToBuffer(icon->pixels, size, size, sprite, 0, 0);
		GUI_DrawSpriteToBuffer(alternate, size, size, sprite, 0, 0);
		/* Two backgrounds distinguish transparency from opaque colour 0. */
		for (pixel = 0; pixel < size * size; pixel++) {
			if (icon->pixels[pixel] == alternate[pixel]) icon->mask |= 1u << pixel;
		}
		icon->size = size;
	}
}

bool GUI_DrawMinimapIcon(uint16 spriteID, uint16 x, uint16 y)
{
	const MinimapIcon *icon;
	const WidgetProperties *widget = &g_widgetProperties[3];
	const uint8 *src;
	uint8 *dst;
	uint16 size;

	if (spriteID < MINIMAP_ICON_FIRST || spriteID >= MINIMAP_ICON_FIRST + MINIMAP_ICON_COUNT ||
	    !GFX_Screen_IsActive(SCREEN_1)) return false;
	icon = &s_minimapIcons[spriteID - MINIMAP_ICON_FIRST];
	size = icon->size;
	if (size == 0 || (uint32)x + size > (uint32)widget->width * 8 || (uint32)y + size > widget->height ||
	    (uint32)widget->xBase * 8 + x + size > SCREEN_WIDTH ||
	    (uint32)widget->yBase + y + size > SCREEN_HEIGHT) return false;
	src = icon->pixels;
	dst = (uint8 *)GFX_Screen_Get_ByIndex(SCREEN_1) +
	      (uint32)(widget->yBase + y) * SCREEN_WIDTH + widget->xBase * 8 + x;
	if (size == 2 && icon->mask == 0xf) {
		dst[0] = src[0];
		dst[1] = src[1];
		dst[SCREEN_WIDTH] = src[2];
		dst[SCREEN_WIDTH + 1] = src[3];
	} else if (size == 3 && icon->mask == 0x1ff) {
		dst[0] = src[0];
		dst[1] = src[1];
		dst[2] = src[2];
		dst[SCREEN_WIDTH] = src[3];
		dst[SCREEN_WIDTH + 1] = src[4];
		dst[SCREEN_WIDTH + 2] = src[5];
		dst[SCREEN_WIDTH * 2] = src[6];
		dst[SCREEN_WIDTH * 2 + 1] = src[7];
		dst[SCREEN_WIDTH * 2 + 2] = src[8];
	} else {
		uint16 row, col, mask = icon->mask;
		for (row = 0; row < size; row++, dst += SCREEN_WIDTH) {
			for (col = 0; col < size; col++, src++, mask >>= 1) {
				if ((mask & 1) != 0) dst[col] = *src;
			}
		}
	}
	return true;
}

typedef struct ViewportSpriteMask {
	const uint8 *sprite;
	uint16 *rows;
	uint16 width, height;
} ViewportSpriteMask;

static ViewportSpriteMask s_viewportSpriteCache[512];
static uint16 *s_viewportSpriteMasks;
static bool s_viewportSpriteReady, s_viewportPlanar;

enum { VIEWPORT_PLANAR_SPRITES = 64, VIEWPORT_PLANAR_COMPONENTS = 64 };
typedef struct ViewportPlanarComponent {
	uint32 key;
	uint16 used, width, height;
	uint16 pixels[32 * 32 / 4];
	uint16 masks[2 * 32];
} ViewportPlanarComponent;

typedef struct ViewportPlanarSprite {
	uint32 key;
	uint32 layerKeys[4];
	uint16 used;
	uint16 width, height;
	int16 offsetX, offsetY;
	uint16 pixels[80 * 64 / 4];
	uint16 masks[5 * 64];
} ViewportPlanarSprite;

static ViewportPlanarSprite *s_viewportPlanarSprites;
static ViewportPlanarComponent *s_viewportPlanarComponents;
static uint16 s_viewportPlanarClock, s_viewportComponentClock;

void GUI_FreeViewportSpriteCache(void)
{
	free(s_viewportPlanarSprites);
	s_viewportPlanarSprites = NULL;
	s_viewportPlanarClock = 0;
	free(s_viewportPlanarComponents);
	s_viewportPlanarComponents = NULL;
	s_viewportComponentClock = 0;
	free(s_viewportSpriteMasks);
	s_viewportSpriteMasks = NULL;
	memset(s_viewportSpriteCache, 0, sizeof(s_viewportSpriteCache));
	s_viewportSpriteReady = s_viewportPlanar = false;
}

bool GUI_ViewportSpriteCacheReady(void)
{
	return s_viewportSpriteReady;
}

void GUI_SetViewportPlanar(bool active)
{
	s_viewportPlanar = active;
}

static ViewportSpriteMask *GUI_ViewportSpriteMaskSlot(const uint8 *sprite)
{
	unsigned slot = ((size_t)sprite >> 2) & 511;
	while (s_viewportSpriteCache[slot].sprite != NULL && s_viewportSpriteCache[slot].sprite != sprite) {
		slot = (slot + 1) & 511;
	}
	return &s_viewportSpriteCache[slot];
}

static void GUI_DrawSpriteMask(uint8 *buffer, uint16 width, uint16 height,
                               const uint8 *sprite, int16 x, int16 y, int flags, ...)
{
	va_list ap;
	va_start(ap, flags);
	GUI_DrawSpriteInternal(SCREEN_0, sprite, x, y, 0, flags, &ap, buffer, width, height);
	va_end(ap);
}

void GUI_InitViewportSpriteCache(void)
{
	uint8 opaque[256], pixels[32 * 32];
	uint32 words = 0;
	uint16 id, mirror;
	uint16 *next;

	GUI_FreeViewportSpriteCache();
	if (!Video_Atari_CursorDirect()) return;
	for (id = 6; id <= 354; id = id == 6 ? 111 : id + 1) {
		const uint8 *sprite = g_sprites[id];
		uint16 width, height;
		if (sprite == NULL) continue;
		width = READ_LE_UINT16(sprite + 3);
		height = sprite[2];
		if (width == 0 || width > 32 || height == 0 || height > 32) {
			Warning("Planar viewport disabled: unsupported sprite %u (%ux%u)\n", id, width, height);
			return;
		}
		words += ((width + 15) >> 4) * height * 2;
	}
	s_viewportSpriteMasks = malloc(words * sizeof(*s_viewportSpriteMasks));
	if (s_viewportSpriteMasks == NULL) {
		Warning("Planar viewport disabled: out of memory for sprite masks\n");
		return;
	}
	memset(opaque, 1, sizeof(opaque));
	next = s_viewportSpriteMasks;
	for (id = 6; id <= 354; id = id == 6 ? 111 : id + 1) {
		const uint8 *sprite = g_sprites[id];
		ViewportSpriteMask *entry;
		uint16 stride, line, x;
		if (sprite == NULL) continue;
		entry = GUI_ViewportSpriteMaskSlot(sprite);
		entry->sprite = sprite;
		entry->width = READ_LE_UINT16(sprite + 3);
		entry->height = sprite[2];
		entry->rows = next;
		stride = (entry->width + 15) >> 4;
		for (mirror = 0; mirror < 2; mirror++) {
			memset(pixels, 0, sizeof(pixels));
			/* Remap every drawn pixel to 1: a real colour-0 pixel must not
			 * become a transparency hole after house/highlight remapping. */
			GUI_DrawSpriteMask(pixels, entry->width, entry->height, sprite, 0, 0,
			                   DRAWSPRITE_FLAG_REMAP | (mirror ? DRAWSPRITE_FLAG_RTL : 0), opaque, 1);
			memset(next, 0, (size_t)stride * entry->height * sizeof(*next));
			for (line = 0; line < entry->height; line++) {
				for (x = 0; x < entry->width; x++) {
					if (pixels[line * entry->width + x] != 0) next[line * stride + (x >> 4)] |= 0x8000u >> (x & 15);
				}
			}
			next += stride * entry->height;
		}
	}
	s_viewportSpriteReady = true;
	s_viewportPlanarSprites = calloc(VIEWPORT_PLANAR_SPRITES, sizeof(*s_viewportPlanarSprites));
	s_viewportPlanarComponents = calloc(VIEWPORT_PLANAR_COMPONENTS, sizeof(*s_viewportPlanarComponents));
	if (s_viewportPlanarSprites == NULL || s_viewportPlanarComponents == NULL) {
		Warning("Planar sprite image caches disabled: out of memory\n");
		free(s_viewportPlanarSprites);
		s_viewportPlanarSprites = NULL;
		free(s_viewportPlanarComponents);
		s_viewportPlanarComponents = NULL;
	}
}

static uint16 GUI_ViewportMaskWord(const uint16 *row, uint16 words, int16 col)
{
	int16 index = col < 0 ? -((15 - col) >> 4) : col >> 4;
	uint16 shift = col & 15;
	uint16 a = index >= 0 && index < words ? row[index] : 0;
	uint16 b = index + 1 >= 0 && index + 1 < words ? row[index + 1] : 0;
	if (shift == 0) return a;
	return (uint16)((a << shift) | (b >> (16 - shift)));
}

static void GUI_ViewportDecodeLayer(uint8 *chunky, uint16 width, uint16 height,
                                    const uint8 *sprite, int16 x, int16 y, int flags,
                                    const uint8 *palette, const uint8 *remap)
{
	if (READ_LE_UINT16(sprite) & 1) {
		uint8 colours[16];
		uint16 i;
		if (palette == NULL) palette = sprite + 10;
		for (i = 0; i < 16; i++) colours[i] = remap != NULL ? remap[palette[i]] : palette[i];
		GUI_DrawSpriteMask(chunky, width, height, sprite, x, y,
		                   DRAWSPRITE_FLAG_PAL | (flags & 3), colours);
	} else {
		GUI_DrawSpriteMask(chunky, width, height, sprite, x, y,
		                   (flags & 3) | (remap != NULL ? DRAWSPRITE_FLAG_REMAP : 0), remap, 1);
	}
}

static ViewportPlanarComponent *GUI_ViewportPlanarComponent(ViewportSpriteMask *mask,
                                                           uint16 spriteID, uint8 colourHouse,
                                                           int flags, const uint8 *palette,
                                                           const uint8 *remap)
{
	uint32 key = 0x80000000UL | spriteID |
	    ((uint32)(colourHouse == GUI_SPRITE_COLOUR_EMBEDDED ? 6 : colourHouse) << 9) |
	    ((uint32)(flags & 3) << 12) | ((uint32)(remap != NULL) << 14);
	ViewportPlanarComponent *entry = NULL, *victim = NULL;
	uint16 i;

	if (++s_viewportComponentClock == 0) {
		s_viewportComponentClock = 1;
		for (i = 0; i < VIEWPORT_PLANAR_COMPONENTS; i++) s_viewportPlanarComponents[i].used = 0;
	}
	for (i = 0; i < VIEWPORT_PLANAR_COMPONENTS; i++) {
		ViewportPlanarComponent *candidate = &s_viewportPlanarComponents[i];
		if (candidate->key == key) {
			entry = candidate;
			break;
		}
		if (victim == NULL || (victim->key != 0 &&
		    (candidate->key == 0 || candidate->used < victim->used))) victim = candidate;
	}
	if (entry == NULL) {
		union { uint32 aligned; uint8 bytes[32 * 32]; } scratch;
		uint16 stride = (mask->width + 15) & ~15;
		uint16 groups = stride >> 4, row;
		const uint16 *rows = mask->rows + ((flags & DRAWSPRITE_FLAG_RTL) ? groups * mask->height : 0);

		entry = victim;
		memset(scratch.bytes, 0, stride * mask->height);
		GUI_ViewportDecodeLayer(scratch.bytes, stride, mask->height, mask->sprite, 0, 0,
		                        flags, palette, remap);
		Video_Atari_EncodePlanar(scratch.bytes, entry->pixels, stride, mask->height);
		for (row = 0; row < mask->height; row++) {
			uint16 sourceRow = (flags & DRAWSPRITE_FLAG_BOTTOMUP) ? mask->height - 1 - row : row;
			uint16 group;
			for (group = 0; group < groups; group++) {
				entry->masks[row * groups + group] = rows[sourceRow * groups + group];
			}
		}
		entry->width = stride;
		entry->height = mask->height;
		entry->key = key;
	}
	entry->used = s_viewportComponentClock;
	return entry;
}

static bool GUI_ViewportPlanarSprite(const uint8 *sprite, uint16 spriteID, uint8 colourHouse,
                                    int16 x, int16 y, int flags, va_list *ap,
                                    const GUI_SpriteLayers *layers)
{
	ViewportSpriteMask *mask;
	ViewportPlanarSprite *entry = NULL, *victim = NULL;
	const uint8 *palette = NULL;
	uint8 *remap = NULL;
	uint16 i, phase, count = layers != NULL ? layers->count : 0;
	uint32 key, layerKeys[4] = {0, 0, 0, 0};
	int16 centreX = 0, centreY = 0;
	int16 remapCount = 0;

	if (!s_viewportPlanar || s_viewportPlanarSprites == NULL || s_viewportPlanarComponents == NULL || sprite == NULL ||
	    spriteID > 354 || g_sprites[spriteID] != sprite ||
	    (flags & ~(DRAWSPRITE_FLAG_RTL | DRAWSPRITE_FLAG_BOTTOMUP | DRAWSPRITE_FLAG_PAL |
	               DRAWSPRITE_FLAG_REMAP | DRAWSPRITE_FLAG_SPRITEPAL |
	               DRAWSPRITE_FLAG_CENTER | DRAWSPRITE_FLAG_WIDGETPOS)) != 0) return false;
	if (flags & DRAWSPRITE_FLAG_PAL) {
		if (colourHouse >= HOUSE_MAX || (READ_LE_UINT16(sprite) & 1) == 0) return false;
	} else if (colourHouse != GUI_SPRITE_COLOUR_EMBEDDED) return false;
	mask = GUI_ViewportSpriteMaskSlot(sprite);
	if (mask->sprite != sprite) return false;
	if (flags & DRAWSPRITE_FLAG_WIDGETPOS) {
		x += g_widgetProperties[2].xBase << 3;
		y += g_widgetProperties[2].yBase;
	}
	if (flags & DRAWSPRITE_FLAG_CENTER) {
		centreX = mask->width / 2;
		centreY = mask->height / 2;
		x -= centreX;
		y -= centreY;
	}
	if (flags & DRAWSPRITE_FLAG_PAL) palette = va_arg(*ap, uint8 *);
	if (flags & DRAWSPRITE_FLAG_REMAP) {
		remap = va_arg(*ap, uint8 *);
		remapCount = (int16)va_arg(*ap, int);
		if (remapCount != 0 && (remapCount != 1 || remap != g_paletteMapping2)) return false;
	}
	if (count > 4) return false;
	for (i = 0; i < count; i++) {
		const GUI_SpriteLayer *layer = &layers->layer[i];
		if (layer->spriteID > 354 || g_sprites[layer->spriteID] == NULL ||
		    (layer->flags & ~(DRAWSPRITE_FLAG_RTL | DRAWSPRITE_FLAG_BOTTOMUP | DRAWSPRITE_FLAG_PAL)) != 0 ||
		    layer->offsetX < -32 || layer->offsetX > 31 || layer->offsetY < -32 || layer->offsetY > 31) return false;
		if (layer->flags & DRAWSPRITE_FLAG_PAL) {
			if (layer->colourHouse >= HOUSE_MAX || (READ_LE_UINT16(g_sprites[layer->spriteID]) & 1) == 0) return false;
		} else if (layer->colourHouse != GUI_SPRITE_COLOUR_EMBEDDED) return false;
		/* Each ordered layer has a frame, colour variant, flips and two
		 * signed six-bit offsets. Zero means absent, including selection. */
		layerKeys[i] = 0x80000000UL | layer->spriteID |
		    ((uint32)(layer->colourHouse == GUI_SPRITE_COLOUR_EMBEDDED ? 6 : layer->colourHouse) << 9) |
		    ((uint32)(layer->flags & 3) << 12) |
		    ((uint32)(layer->offsetX & 63) << 14) | ((uint32)(layer->offsetY & 63) << 20);
	}
	phase = (uint16)x & 15;
	/* 9-bit frame, 3-bit colour variant (6 = embedded), two flips,
	 * highlight and four-bit X phase. Bit 31 distinguishes empty slots. */
	key = 0x80000000UL | spriteID |
	      ((uint32)(colourHouse == GUI_SPRITE_COLOUR_EMBEDDED ? 6 : colourHouse) << 9) |
	      ((uint32)(flags & 3) << 12) | ((uint32)(remapCount != 0) << 14) |
	      ((uint32)phase << 15) | ((uint32)((flags & DRAWSPRITE_FLAG_CENTER) != 0) << 19);
	if (++s_viewportPlanarClock == 0) {
		s_viewportPlanarClock = 1;
		for (i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) s_viewportPlanarSprites[i].used = 0;
	}
	for (i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) {
		ViewportPlanarSprite *candidate = &s_viewportPlanarSprites[i];
		if (candidate->key == key && candidate->layerKeys[0] == layerKeys[0] &&
		    candidate->layerKeys[1] == layerKeys[1] && candidate->layerKeys[2] == layerKeys[2] &&
		    candidate->layerKeys[3] == layerKeys[3]) {
			entry = candidate;
			break;
		}
		if (victim == NULL || (victim->key != 0 &&
		    (candidate->key == 0 || candidate->used < victim->used))) victim = candidate;
	}
	if (entry == NULL) {
		ViewportSpriteMask *masks[5];
		int16 left[5], top[5], minX = 0, minY = 0;
		int16 maxX = mask->width, maxY = mask->height;
		uint16 stride, height, groups;
		masks[0] = mask;
		left[0] = top[0] = 0;
		for (i = 0; i < count; i++) {
			const GUI_SpriteLayer *layer = &layers->layer[i];
			ViewportSpriteMask *m = GUI_ViewportSpriteMaskSlot(g_sprites[layer->spriteID]);
			if (m->sprite != g_sprites[layer->spriteID]) return false;
			masks[i + 1] = m;
			left[i + 1] = centreX + layer->offsetX - m->width / 2;
			top[i + 1] = centreY + layer->offsetY - m->height / 2;
			minX = min(minX, left[i + 1]);
			minY = min(minY, top[i + 1]);
			maxX = max(maxX, left[i + 1] + m->width);
			maxY = max(maxY, top[i + 1] + m->height);
		}
		minX -= (uint16)(x + minX) & 15;
		stride = (maxX - minX + 15) & ~15;
		height = maxY - minY;
		if (stride > 80 || height > 64) {
			Warning("Planar layered sprite exceeds cache bounds (%ux%u)\n", stride, height);
			return false;
		}
		if (x + minX >= 240 || x + maxX <= 0 || y + minY >= 200 || y + maxY <= 40) return true;
		groups = stride >> 4;
		entry = victim;
		memset(entry->pixels, 0, stride * height / 2);
		memset(entry->masks, 0, groups * height * sizeof(*entry->masks));
		for (i = 0; i <= count; i++) {
			ViewportSpriteMask *m = masks[i];
			int layerFlags = i == 0 ? flags : layers->layer[i - 1].flags;
			const uint8 *layerPalette = i == 0 ? palette :
			    (layerFlags & DRAWSPRITE_FLAG_PAL ? layers->layer[i - 1].palette : NULL);
			ViewportPlanarComponent *component = GUI_ViewportPlanarComponent(m,
			    i == 0 ? spriteID : layers->layer[i - 1].spriteID,
			    i == 0 ? colourHouse : layers->layer[i - 1].colourHouse,
			    layerFlags, layerPalette, i == 0 && remapCount != 0 ? remap : NULL);
			Video_Atari_ComposePlanarSprite(entry->pixels, entry->masks, stride, height,
			    component->pixels, component->masks, component->width, component->height,
			    left[i] - minX, top[i] - minY);
		}
		entry->width = stride;
		entry->height = height;
		entry->offsetX = minX;
		entry->offsetY = minY;
		memcpy(entry->layerKeys, layerKeys, sizeof(layerKeys));
		entry->key = key;
	}
	entry->used = s_viewportPlanarClock;
	GFX_Screen_SetDirtySource(DIRTY_SRC_SPRITE);
	Video_Atari_PresentPlanarSprite(entry->pixels, entry->masks,
	    entry->width, entry->height, x + entry->offsetX, y + entry->offsetY);
	return true;
}
#endif

static void GUI_DrawSpriteInternal(Screen screenID, const uint8 *sprite, int16 posX, int16 posY,
                                  uint16 windowID, int flags, va_list *ap,
                                  uint8 *target, uint16 targetWidth, uint16 targetHeight)
{
	/* variables for blur/sandworm effect */
	static const uint8 blurOffsets[8] = {1, 3, 2, 5, 4, 3, 2, 1};
	static uint16 s_blurIndex  = 0;	/* index into previous table */
	uint16 blurOffset = 1;
	uint16 blurRandomValueIncr = 0x8B55;
	uint16 blurRandomValue     = 0x51EC;

	int16  top;
	int16  bottom;
	uint16 width;
	uint16 spriteFlags;
	int16  spriteHeight;	/* number of sprite rows to draw */
	int16  tmpRowCountToDraw;
	int16  pixelCountPerRow;	/* count of pixel to draw per row */
	int16  spriteWidthZoomed;	/* spriteWidth * zoomRatioX */
	int16  spriteWidth;	/* original sprite Width */
	int16  pixelSkipStart;	/* pixel count to skip at start of row */
	int16  pixelSkipEnd;	/* pixel count to skip at end of row */
	uint8 *remap = NULL;
	int16  remapCount = 0;
	int16  distY;
	uint16 zoomRatioX = 0;	/* 8.8 fixed point, ie 0x0100 = 1x */
	uint16 zoomRatioY = 0x100;	/* 8.8 fixed point, ie 0x0100 = 1x */
	uint16 Ycounter = 0;	/* 8.8 fixed point, ie 0x0100 = 1 */
	const uint8 *spriteSave = NULL;
	int16  distX;
	const uint8 *palette = NULL;
	uint16 spriteDecodedLength; /* if encoded with Format80 */
	uint8 spriteBuffer[20000];	/* for sprites encoded with Format80 : maximum size for credits images is 19841, elsewere it is 3456 */
	uint16 rowStride = SCREEN_WIDTH;	/* per-row pointer advance; overridden below when writing into a tightly packed scratch buffer */
#ifdef TOS
	/* Private scratch rendering for direct planar UI and battlefield
	 * sprites. The battlefield uses cached opacity masks and row c2p;
	 * other small sprites retain transparent presentation.
	 * DRAWSPRITE_FLAG_BLUR is excluded: that mode
	 * reads already-drawn neighbouring pixels back out of the destination
	 * buffer (the sandworm blur effect), which only makes sense against
	 * the real screen, not a freshly zeroed private one.
	 * DRAWSPRITE_FLAG_NO_PLANAR_DIRECT is an explicit caller opt-out for
	 * callers that need the legacy chunky write path. Private buffer
	 * rendering bypasses planar presentation independently of this flag. */
	union {
		uint32 aligned;
		uint8 bytes[128 * 32];
	} spriteScratchStorage;
	uint8 *spriteScratch = spriteScratchStorage.bytes;
	ViewportSpriteMask *viewportMask = NULL;
	uint16 viewportMasks[32 * 3];
	int16 firstSpriteRow = 0;
	bool toPlanar = false;
	bool batched = false;
	int16 screenX = 0, screenY = 0;
	int16 spriteHeightDraw = 0;
#endif

	uint8 *buf = NULL;
	uint8 *b = NULL;
	uint8 spritePalRemap[16];	/* sprite palette composed with the house remap */
#ifdef GUI_SPRITE_PREDECODE_STATS
	const uint8 *spriteOrigin;
#endif
	int16  count;
	int16  buf_incr;

	if (sprite == NULL) return;

#ifdef TOS
	if (target == NULL && s_viewportPlanar && windowID == 2 &&
	    GFX_Screen_Get_ByIndex(screenID) == GFX_Screen_Get_ByIndex(SCREEN_0)) {
		viewportMask = GUI_ViewportSpriteMaskSlot(sprite);
		assert(viewportMask->sprite == sprite);
	}
#endif
#ifdef GUI_SPRITE_PREDECODE_STATS
	spriteOrigin = sprite;
#endif

	/* read additional arguments according to the flags */

	if ((flags & DRAWSPRITE_FLAG_PAL) != 0) palette = va_arg(*ap, uint8*);

	/* Remap */
	if ((flags & DRAWSPRITE_FLAG_REMAP) != 0) {
		remap = va_arg(*ap, uint8*);
		remapCount = (int16)va_arg(*ap, int);
		if (remapCount == 0) flags &= ~DRAWSPRITE_FLAG_REMAP;
	}

	if ((flags & DRAWSPRITE_FLAG_BLUR) != 0) {
		s_blurIndex = (s_blurIndex + 1) % 8;
		blurOffset = blurOffsets[s_blurIndex];
		blurRandomValue = 0x0;
		blurRandomValueIncr = 0x100;
	}

	if ((flags & DRAWSPRITE_FLAG_BLURINCR) != 0) blurRandomValueIncr = (uint16)va_arg(*ap, int);

	if ((flags & DRAWSPRITE_FLAG_ZOOM) != 0) {
		zoomRatioX = (uint16)va_arg(*ap, int);
		zoomRatioY = (uint16)va_arg(*ap, int);
	}

	if (target != NULL) {
		buf = target;
		rowStride = targetWidth;
		width = targetWidth;
		top = 0;
		bottom = targetHeight;
	} else {
		buf = GFX_Screen_Get_ByIndex(screenID);
		buf += g_widgetProperties[windowID].xBase << 3;

		width = g_widgetProperties[windowID].width << 3;
		top = g_widgetProperties[windowID].yBase;
		bottom = top + g_widgetProperties[windowID].height;

		if ((flags & DRAWSPRITE_FLAG_WIDGETPOS) != 0) {
			posY += g_widgetProperties[windowID].yBase;
		} else {
			posX -= g_widgetProperties[windowID].xBase << 3;
		}
	}

	spriteFlags = READ_LE_UINT16(sprite);
	sprite += 2;

	if ((spriteFlags & 0x1) != 0) flags |= DRAWSPRITE_FLAG_SPRITEPAL;

	spriteHeight = *sprite++;
	spriteWidth = READ_LE_UINT16(sprite);
	sprite += 5;
	spriteDecodedLength = READ_LE_UINT16(sprite);
	sprite += 2;

	spriteWidthZoomed = spriteWidth;

	if ((flags & DRAWSPRITE_FLAG_ZOOM) != 0) {
		spriteHeight = (int16)(((int32)spriteHeight * (int32)zoomRatioY) >> 8);
		if (spriteHeight == 0) return;
		spriteWidthZoomed = (int16)(((int32)spriteWidthZoomed * (int32)zoomRatioX) >> 8);
		if (spriteWidthZoomed == 0) return;
	}

	if ((flags & DRAWSPRITE_FLAG_CENTER) != 0) {
		posX -= spriteWidthZoomed / 2;	/* posX relative to center */
		posY -= spriteHeight / 2;		/* posY relative to center */
	}

	pixelCountPerRow = spriteWidthZoomed;

	if ((spriteFlags & 0x1) != 0) {
		if ((flags & DRAWSPRITE_FLAG_PAL) == 0) palette = sprite;
		sprite += 16;
	}

	if ((spriteFlags & 0x2) == 0) {
		Format80_Decode(spriteBuffer, sprite, spriteDecodedLength);

		sprite = spriteBuffer;
	}

	if ((flags & DRAWSPRITE_FLAG_BOTTOMUP) == 0) {
		/* distance between top of window and top of sprite */
		distY = posY - top;
	} else {
		/* distance between bottom of window and bottom of sprite */
		distY = bottom - posY - spriteHeight;
	}

	if (distY < 0) {
		/* means the sprite begins outside the window,
		 * need to skip a few rows before drawing */
		spriteHeight += distY;
		if (spriteHeight <= 0) return;

		distY = -distY;
#ifdef TOS
		firstSpriteRow = distY;
#endif

		while (distY > 0) {
			/* skip a row */
			spriteSave = sprite;
			count = spriteWidth;

			assert((flags & 0xFF) < 4);	/* means DRAWSPRITE_FLAG_ZOOM is forbidden */
			/* so (flags & 0xFD) equals (flags & DRAWSPRITE_FLAG_RTL) */

			while (count > 0) {
#if 1
					if (*sprite++ == 0) count -= *sprite++;
					else count--;
#else
				while (count != 0) {
					count--;
					if (*sprite++ == 0) break;
				}
				if (sprite[-1] != 0 && count == 0) break;

				count -= *sprite++ - 1;
#endif
			}

			/*buf += count * (((flags & 0xFF) == 0 || (flags & 0xFF) == 2) ? -1 : 1);*/
#if 0
			if ((flags & 0xFD) == 0) buf -= count;	/* 0xFD = 1111 1101b */
			else buf += count;
#else
			if ((flags & DRAWSPRITE_FLAG_RTL) != 0) buf += count;
			else buf -= count;
#endif

			Ycounter += zoomRatioY;
			if ((Ycounter & 0xFF00) != 0) {
				distY -= Ycounter >> 8;
				Ycounter &= 0xFF;	/* keep only fractional part */
			}
		}

		if (distY < 0) {
			sprite = spriteSave;

			Ycounter += (-distY) << 8;
		}

		if ((flags & DRAWSPRITE_FLAG_BOTTOMUP) == 0) posY = top;
	}

	if ((flags & DRAWSPRITE_FLAG_BOTTOMUP) == 0) {
		tmpRowCountToDraw = bottom - posY;	/* rows to draw */
	} else {
		tmpRowCountToDraw = posY + spriteHeight - top;	/* rows to draw */
	}

	if (tmpRowCountToDraw <= 0) return;	/* no row to draw */

	if (tmpRowCountToDraw < spriteHeight) {
		/* there are a few rows to skip at the end */
		spriteHeight = tmpRowCountToDraw;
		if ((flags & DRAWSPRITE_FLAG_BOTTOMUP) != 0) posY = top;
	}

	pixelSkipStart = 0;
	if (posX < 0) {
		/* skip pixels outside window */
		pixelCountPerRow += posX;
		pixelSkipStart = -posX;	/* pixel count to skip at row start */
		if (pixelSkipStart >= spriteWidthZoomed) return;	/* no pixel to draw */
		posX = 0;
	}

	pixelSkipEnd = 0;
	distX = width - posX;	/* distance between left of sprite and right of window */
	if (distX <= 0) return;	/* no pixel to draw */

	if (distX < pixelCountPerRow) {
		pixelCountPerRow = distX;
		pixelSkipEnd = spriteWidthZoomed - pixelSkipStart - pixelCountPerRow;	/* pixel count to skip at row end */
	}

	/* move pointer to 1st pixel of 1st row to draw */
#ifdef TOS
	/* Must check the actual write target (screenID, already resolved into
	 * buf above), not merely "is SCREEN_0 the currently active screen":
	 * callers such as GUI_FactoryWindow_PrepareScrollList() explicitly
	 * target SCREEN_1 without ever switching the active screen away from
	 * SCREEN_0, so GFX_Screen_IsActive(SCREEN_0) would be true even though
	 * this draw has nothing to do with SCREEN_0 -- wrongly hijacking a
	 * SCREEN_1 draw into a stray write straight onto the visible planar
	 * screen (seen as leftover sidebar/build-window graphics bleeding
	 * into other screens, e.g. the CONST. YARD build panel). */
	toPlanar = target == NULL && GFX_Screen_Get_ByIndex(screenID) == GFX_Screen_Get_ByIndex(SCREEN_0) && Video_Atari_CursorDirect() &&
	           (flags & (DRAWSPRITE_FLAG_BLUR | DRAWSPRITE_FLAG_NO_PLANAR_DIRECT)) == 0 &&
	           pixelCountPerRow > 0 && spriteHeight > 0 &&
	           (uint32)pixelCountPerRow * (uint32)spriteHeight <= sizeof(spriteScratchStorage.bytes);

	if (toPlanar) {
		screenX = (g_widgetProperties[windowID].xBase << 3) + posX;
		screenY = posY;
		spriteHeightDraw = spriteHeight;

		if (viewportMask != NULL) {
			uint16 pad = screenX & 15;
			rowStride = (pad + pixelCountPerRow + 15) & ~15;
			memset(spriteScratch, 0, (size_t)rowStride * spriteHeight);
			buf = spriteScratch + pad;
		} else if (s_spriteBatchBuf != NULL &&
		    screenX >= s_spriteBatchOriginX && screenY >= s_spriteBatchOriginY &&
		    screenX + pixelCountPerRow <= s_spriteBatchOriginX + s_spriteBatchW &&
		    screenY + spriteHeight <= s_spriteBatchOriginY + s_spriteBatchH) {
			/* Batch mode active (see GUI_DrawSprite_BeginBatch()) and this
			 * draw fits inside the batch rect: composite into the caller's
			 * shared buffer instead of the private per-call scratch buffer,
			 * and let the caller's EndBatch() do the one and only present. */
			rowStride = s_spriteBatchStride;
			buf = s_spriteBatchBuf + (uint32)(screenY - s_spriteBatchOriginY) * rowStride + (screenX - s_spriteBatchOriginX);
			batched = true;
		} else {
			/* Write into a small private scratch buffer instead of SCREEN_0,
			 * for the same reason as GUI_DrawChar(): SCREEN_0 is no longer
			 * reliably maintained, so a zeroed private buffer is needed to
			 * make "untouched byte" reliably mean "transparent" for
			 * Video_Atari_PresentChunkyTransparent() below. */
			memset(spriteScratch, 0, (size_t)pixelCountPerRow * spriteHeight);
			rowStride = pixelCountPerRow;
			buf = spriteScratch;
		}
		if ((flags & DRAWSPRITE_FLAG_BOTTOMUP) != 0) {
			buf += (uint32)(spriteHeightDraw - 1) * rowStride;
		}
	} else
#endif
	{
		buf += posY * rowStride + posX;
		if ((flags & DRAWSPRITE_FLAG_BOTTOMUP) != 0) {
			buf += (spriteHeight - 1) * rowStride;
		}
	}

	if ((flags & DRAWSPRITE_FLAG_RTL) != 0) {
		/* XCHG pixelSkipStart, pixelSkipEnd */
		uint16 tmp = pixelSkipStart;
		pixelSkipStart = pixelSkipEnd;
		pixelSkipEnd = tmp;
		buf += pixelCountPerRow - 1;
		buf_incr = -1;
	} else {
		buf_incr = 1;
	}

	b = buf;

	if ((flags & DRAWSPRITE_FLAG_ZOOM) != 0) {
		pixelSkipEnd = 0;
		pixelSkipStart = (pixelSkipStart << 8) / zoomRatioX;
	}

	assert((flags & 0xFF) < 4);

	/* ENHANCEMENT -- Compose the sprite palette with the house remap table.
	 *
	 * The REMAP|SPRITEPAL path cost 108.10 cycles per opaque pixel, its two
	 * dependent lookups (MOVE.B (A3,D2.L) 16, AND.L 16, MOVE.B (A2,D2.L) 20)
	 * converting a stored index into a screen colour. That conversion is
	 * constant for a given sprite and remap table, and the stored index is
	 * only 0..15 because a sprite palette is 16 bytes, so the whole of
	 * rm[pal[v]] collapses into one 16-byte table built once per call. The
	 * draw then takes the SPRITEPAL path, measured at 52.09 cycles/pixel.
	 *
	 * This deliberately leaves the RLE stream untouched. Pre-decoding
	 * sprites to byte-per-pixel was considered and rejected: `0` introduces
	 * a run of transparent pixels, unit sprites are small and sparse (64
	 * pixels in 50 bytes is typical), and flattening them would replace
	 * per-run skipping with a per-pixel test. The same mistake measured a
	 * real regression in GFX_DrawTile's transparent loop.
	 *
	 * 16 entries is cheap against the opaque pixels per call this path
	 * averages, and it cannot corrupt the stream because only the lookup
	 * changes, never the data. */
	if ((flags & (DRAWSPRITE_FLAG_REMAP | DRAWSPRITE_FLAG_SPRITEPAL))
	     == (DRAWSPRITE_FLAG_REMAP | DRAWSPRITE_FLAG_SPRITEPAL)
	    && (flags & DRAWSPRITE_FLAG_BLUR) == 0
	    && palette != NULL && remap != NULL) {
		int16 i;

		for (i = 0; i < 16; i++) {
			unsigned t = palette[i];
			int16 r;

			for (r = 0; r < remapCount; r++) t = remap[t];
			spritePalRemap[i] = (uint8)t;
		}
		palette = spritePalRemap;
		flags &= ~DRAWSPRITE_FLAG_REMAP;
	}

#ifdef GUI_SPRITE_PREDECODE_STATS
	GUI_Sprite_Stats_Record(spriteOrigin, flags, remap, spriteWidth, spriteHeight,
	                        spriteDecodedLength);
#endif

	if (target == NULL) {
		GFX_Screen_SetDirtySource(DIRTY_SRC_SPRITE);
#ifdef TOS
		if (!toPlanar)
#endif
		GFX_Screen_SetDirty(screenID,
		                   (g_widgetProperties[windowID].xBase << 3) + posX,
		                   posY,
		                   (g_widgetProperties[windowID].xBase << 3) + posX + pixelCountPerRow,
		                   posY + spriteHeight);
	}

	do {
		/* drawing loop */
		if ((Ycounter & 0xFF00) == 0) {
			while (true) {
				Ycounter += zoomRatioY;

				if ((Ycounter & 0xFF00) != 0) break;
				count = spriteWidth;

				while (count > 0) {
#if 1
					if (*sprite++ == 0) count -= *sprite++;
					else count--;
#else
					while (count != 0) {
						count--;
						if (*sprite++ == 0) break;
					}
					if (sprite[-1] != 0 && count == 0) break;

					count -= *sprite++ - 1;
#endif
				}

#if 0
				if ((flags & 0xFD) == 0) buf -= count;
				else buf += count;
#else
				if ((flags & DRAWSPRITE_FLAG_RTL) != 0) buf += count;
				else buf -= count;
#endif
			}
			spriteSave = sprite;
		}

		count = pixelSkipStart;

		while (count > 0) {
#if 1
			if (*sprite++ == 0) count -= *sprite++;
			else count--;
#else
			while (count != 0) {
				count--;
				if (*sprite++ == 0) break;
			}
			if (sprite[-1] != 0 && count == 0) break;

			count -= *sprite++ - 1;
#endif
		}

#if 0
		if ((flags & 0xFD) == 0) buf -= count;
		else buf += count;
#else
		if ((flags & DRAWSPRITE_FLAG_RTL) != 0) buf += count;
		else buf -= count;
#endif

		if (spriteWidth != 0) {
			count += pixelCountPerRow;

			assert((flags & 0xF00) < 0x800);
			switch (flags & 0xF00) {
				case 0:
					/* ENHANCEMENT -- This is by far the hottest sprite loop
					 * (35% of GUI_DrawSprite, 5% of all cycles in an m68000
					 * profile). GUI_DrawSprite is a large va_arg function and
					 * the compiler spills buf_incr to the stack, so the 68000
					 * reloaded the increment from (A7,d16) - an 18 cycle
					 * access - for every single opaque pixel. Hoisting the
					 * pointer and count into locals and specialising on the
					 * fixed direction lets both stay in registers. */
					if ((flags & DRAWSPRITE_FLAG_RTL) != 0) {
						uint8 *d = buf;
						int16 n = count;

						while (n > 0) {
							uint8 v = *sprite++;
							if (v == 0) {
								v = *sprite++; /* run length encoding of transparent pixels */
								d -= v;
								n -= v;
							} else {
								*d-- = v;
								n--;
							}
						}
						buf = d;
						count = n;
					} else {
						/* ENHANCEMENT -- Bound the loop by a pointer rather
						 * than a separate counter. GCC emitted 7 instructions
						 * (~60 cycles) per opaque pixel for the counter form:
						 * it kept a redundant TST.W after a SUBQ that had
						 * already set the flags, and used a BLE.W with a
						 * 16-bit displacement for a branch of a few bytes.
						 * Comparing against `end` folds the loop test into a
						 * single compare-and-branch.
						 *
						 * This must stay inline: the profile shows only ~9.2
						 * opaque pixels per execution, so an out-of-line
						 * helper cannot amortise even a minimal ~200 cycle
						 * call sequence. */
						const uint8 *s = sprite;
						uint8 *d = buf;
						uint8 *end = buf + count;

						/* Written as a rotated do/while so the loop-closing
						 * test is a single backward conditional branch. The
						 * equivalent while() form made GCC emit a forward
						 * Bcc.W out of the loop plus an unconditional BRA
						 * back, 22 cycles of branching per pixel. */
						if (d < end) {
							do {
								uint8 v = *s++;
								/* Opaque is the common case (~88% of bytes),
								 * so it is written first to keep it the
								 * fall-through path. */
								if (v != 0) {
									*d++ = v;
								} else {
									/* run length encoding of transparent pixels */
									d += *s++;
								}
							} while (d < end);
						}
						sprite = s;
						buf = d;
						count = (int16)(end - d);
					}
					break;

				case (DRAWSPRITE_FLAG_REMAP):	/* remap */
					while (count > 0) {
						uint8 v = *sprite++;
						if (v == 0) {
							v = *sprite++; /* run length encoding of transparent pixels */
							if ((flags & DRAWSPRITE_FLAG_RTL) != 0) buf -= v;
							else buf += v;
							count -= v;
						} else {
							int16 i;
							for(i = 0; i < remapCount; i++) v = remap[v];
							*buf = v;
							buf += buf_incr;
							count--;
						}
					}
					break;

				case (DRAWSPRITE_FLAG_BLUR):	/* blur/Sandworm effect */
					while (count > 0) {
						uint8 v = *sprite++;
						if (v == 0) {
							v = *sprite++; /* run length encoding of transparent pixels */
							if ((flags & DRAWSPRITE_FLAG_RTL) != 0) buf -= v;
							else buf += v;
							count -= v;
						} else {
							blurRandomValue += blurRandomValueIncr;

							if ((blurRandomValue & 0xFF00) == 0) {
								*buf = v;
							} else {
								blurRandomValue &= 0xFF;
								*buf = buf[blurOffset];
							}
							buf += buf_incr;
							count--;
						}
					}
					break;

				case (DRAWSPRITE_FLAG_REMAP | DRAWSPRITE_FLAG_BLUR):
				case (DRAWSPRITE_FLAG_REMAP | DRAWSPRITE_FLAG_BLUR | DRAWSPRITE_FLAG_SPRITEPAL):
					/* remap + blur ? (+ has house colors) */
					while (count > 0) {
						uint8 v = *sprite++;
						if (v == 0) {
							v = *sprite++; /* run length encoding of transparent pixels */
							if ((flags & DRAWSPRITE_FLAG_RTL) != 0) buf -= v;
							else buf += v;
							count -= v;
						} else {
							int16 i;
							v = *buf;
							for(i = 0; i < remapCount; i++) v = remap[v];
							*buf = v;
							buf += buf_incr;
							count--;
						}
					}
					break;

				case (DRAWSPRITE_FLAG_SPRITEPAL):	/* sprite has palette */
					while (count > 0) {
						uint8 v = *sprite++;
						if (v == 0) {
							v = *sprite++; /* run length encoding of transparent pixels */
							if ((flags & DRAWSPRITE_FLAG_RTL) != 0) buf -= v;
							else buf += v;
							count -= v;
						} else {
							*buf = palette[v];
							buf += buf_incr;
							count--;
						}
					}
					break;

				case (DRAWSPRITE_FLAG_REMAP | DRAWSPRITE_FLAG_SPRITEPAL):
					/* remap +  sprite has palette */
					/* ENHANCEMENT -- 176 cycles per opaque pixel on m68000,
					 * the most expensive sprite path and the one that grows
					 * late-game (house-coloured units). Four separate costs
					 * were measured in the profile, all removable:
					 *  - `v` is a uint8 promoted to int for the array index,
					 *    so GCC emitted AND.L #$ff twice (1.8M cycles each)
					 *    to re-zero-extend a value already known to be a byte
					 *  - remapCount is 1 in every observed call, yet the
					 *    generic for() paid TST/BLE/SUBA/ADDQ/CMP/BNE per
					 *    pixel (4.5M cycles) to run its body exactly once
					 *  - palette and buf_incr were re-read from the stack
					 *    every pixel (3.8M cycles); this function is a large
					 *    va_arg routine, so the register allocator spills
					 * Holding the pixel and the intermediate lookup in
					 * `unsigned` rather than `uint8` is what removes the
					 * masking: GCC then knows the upper bits are already
					 * clear and drops both AND.L instructions. */
					{
						const uint8 *s = sprite;
						const uint8 *pal = palette;
						const uint8 *rm = remap;
						uint8 *d = buf;
						int16 n = count;
						int16 incr = buf_incr;

						if (remapCount == 1) {
							unsigned t;

							while (n > 0) {
								unsigned v = *s++;
								if (v == 0) {
									v = *s++; /* run length encoding of transparent pixels */
									d += (int16)(incr * (int16)v);
									n -= v;
								} else {
									t = pal[v];
									*d = rm[t];
									d += incr;
									n--;
								}
							}
						} else {
							while (n > 0) {
								unsigned v = *s++;
								if (v == 0) {
									v = *s++; /* run length encoding of transparent pixels */
									d += (int16)(incr * (int16)v);
									n -= v;
								} else {
									int16 i;
									unsigned t = pal[v];
									for (i = 0; i < remapCount; i++) t = rm[t];
									*d = (uint8)t;
									d += incr;
									n--;
								}
							}
						}
						sprite = s;
						buf = d;
						count = n;
					}
					break;

				case (DRAWSPRITE_FLAG_BLUR | DRAWSPRITE_FLAG_SPRITEPAL):
					/* blur/sandworm effect + sprite has palette */
					while (count > 0) {
						uint8 v = *sprite++;
						if (v == 0) {
							v = *sprite++; /* run length encoding of transparent pixels */
							if ((flags & DRAWSPRITE_FLAG_RTL) != 0) buf -= v;
							else buf += v;
							count -= v;
						} else {
							blurRandomValue += blurRandomValueIncr;

							if ((blurRandomValue & 0xFF00) == 0) {
								*buf = palette[v];
							} else {
								blurRandomValue &= 0x00FF;
								*buf = buf[blurOffset];
							}
							buf += buf_incr;
							count--;
						}
					}
					break;
			}

			count += pixelSkipEnd;
			if (count != 0) {
				while (count > 0) {
#if 1
					if (*sprite++ == 0) count -= *sprite++;
					else count--;
#else
					while (count != 0) {
						count--;
						if (*sprite++ == 0) break;
					}
					if (sprite[-1] != 0 && count == 0) break;

					count -= *sprite++ - 1;
#endif
				}

#if 0
				if ((flags & 0xFD) == 0) buf -= count;
				else buf += count;
#else
				if ((flags & DRAWSPRITE_FLAG_RTL) != 0) buf += count;
				else buf -= count;
#endif
			}
		}

		if ((flags & DRAWSPRITE_FLAG_BOTTOMUP) != 0)	b -= rowStride;
		else b += rowStride;
		buf = b;

		Ycounter -= 0x100;
		if ((Ycounter & 0xFF00) != 0) sprite = spriteSave;
	} while (--spriteHeight > 0);
#ifdef TOS
	if (toPlanar && !batched) {
		if (viewportMask != NULL) {
			uint16 line, group, groups = rowStride >> 4;
			uint16 maskStride = (viewportMask->width + 15) >> 4;
			uint16 pad = screenX & 15;
			int16 col = (flags & DRAWSPRITE_FLAG_RTL)
				? viewportMask->width - pixelSkipStart - pixelCountPerRow : pixelSkipStart;
			const uint16 *maskBase = viewportMask->rows;
			if (flags & DRAWSPRITE_FLAG_RTL) maskBase += maskStride * viewportMask->height;
			assert(firstSpriteRow + spriteHeightDraw <= viewportMask->height);
			for (line = 0; line < spriteHeightDraw; line++) {
				uint16 row = firstSpriteRow + ((flags & DRAWSPRITE_FLAG_BOTTOMUP) ? spriteHeightDraw - 1 - line : line);
				for (group = 0; group < groups; group++) {
					uint16 begin = group == 0 ? pad : 0;
					uint16 end = min(16, pad + pixelCountPerRow - group * 16);
					uint16 edge = (0xffffu >> begin) & (0xffffu << (16 - end));
					viewportMasks[line * groups + group] =
						GUI_ViewportMaskWord(maskBase + row * maskStride, maskStride, col + group * 16 - pad) & edge;
				}
			}
			Video_Atari_PresentSprite(spriteScratch, rowStride, screenX & ~15, screenY,
			                          rowStride, spriteHeightDraw, viewportMasks);
		} else {
			Video_Atari_PresentChunkyTransparent(spriteScratch, rowStride,
			                                     screenX, screenY, rowStride, spriteHeightDraw);
		}
	}
#endif
}

/**
 * Updates the score.
 * @param score The base score.
 * @param harvestedAllied Pointer to the total amount of spice harvested by allies.
 * @param harvestedEnemy Pointer to the total amount of spice harvested by enemies.
 * @param houseID The houseID of the player.
 */
static uint16 Update_Score(int16 score, uint16 *harvestedAllied, uint16 *harvestedEnemy, uint8 houseID)
{
	PoolFindStruct find;
	uint16 targetTime;
	uint16 sumHarvestedAllied = 0;
	uint16 sumHarvestedEnnemy = 0;
	uint32 tmp;

	if (score < 0) score = 0;

	find.houseID = houseID;
	find.type    = 0xFFFF;
	find.index   = 0xFFFF;

	while (true) {
		Structure *s;

		s = Structure_Find(&find);
		if (s == NULL) break;
		if (s->o.type == STRUCTURE_SLAB_1x1 || s->o.type == STRUCTURE_SLAB_2x2 || s->o.type == STRUCTURE_WALL) continue;

		score += g_table_structureInfo[s->o.type].o.buildCredits / 100;
	}

	g_validateStrictIfZero++;

	find.houseID = HOUSE_INVALID;
	find.type    = UNIT_HARVESTER;
	find.index   = 0xFFFF;

	while (true) {
		Unit *u;

		u = Unit_Find(&find);
		if (u == NULL) break;

		if (House_AreAllied(Unit_GetHouseID(u), g_playerHouseID)) {
			sumHarvestedAllied += u->amount * 7;
		} else {
			sumHarvestedEnnemy += u->amount * 7;
		}
	}

	g_validateStrictIfZero--;

	tmp = *harvestedEnemy + sumHarvestedEnnemy;
	*harvestedEnemy = (tmp > 65000) ? 65000 : (tmp & 0xFFFF);

	tmp = *harvestedAllied + sumHarvestedAllied;
	*harvestedAllied = (tmp > 65000) ? 65000 : (tmp & 0xFFFF);

	score += House_Get_ByIndex(houseID)->credits / 100;

	if (score < 0) score = 0;

	targetTime = g_campaignID * 45;

	if (s_ticksPlayed < targetTime) {
		score += targetTime - s_ticksPlayed;
	}

	return score;
}

/**
 * Draws a string on a filled rectangle.
 * @param string The string to draw.
 * @param top The most top position where to draw the string.
 */
static void GUI_DrawTextOnFilledRectangle(const char *string, uint16 top)
{
	uint16 halfWidth;

	GUI_DrawText_Wrapper(NULL, 0, 0, 0, 0, 0x121);

	halfWidth = (Font_GetStringWidth(string) / 2) + 4;

	GUI_DrawFilledRectangle(SCREEN_WIDTH / 2 - halfWidth, top, SCREEN_WIDTH / 2 + halfWidth, top + 6, 116);
	GUI_DrawText_Wrapper(string, SCREEN_WIDTH / 2, top, 0xF, 0, 0x121);
}

static uint16 GUI_HallOfFame_GetRank(uint16 score)
{
	uint8 i;

	for (i = 0; i < lengthof(_rankScores); i++) {
		if (_rankScores[i].score > score) break;
	}

	return min(i, lengthof(_rankScores) - 1);
}

static void GUI_HallOfFame_DrawRank(uint16 score, bool fadeIn)
{
	GUI_DrawText_Wrapper(String_Get_ByIndex(_rankScores[GUI_HallOfFame_GetRank(score)].rankString), SCREEN_WIDTH / 2, 49, 6, 0, 0x122);

	if (!fadeIn) return;

	GUI_Screen_FadeIn(10, 49, 10, 49, 20, 12, SCREEN_1, SCREEN_0);
}

static void GUI_HallOfFame_DrawBackground(uint16 score, bool hallOfFame)
{
	Screen oldScreenID;
	uint16 xSrc;
	uint16 colour;
	uint16 offset;

	oldScreenID = GFX_Screen_SetActive(SCREEN_1);

	Sprites_LoadImage("FAME.CPS", SCREEN_1, g_palette_998A);

	xSrc = 1;
	if (g_playerHouseID <= HOUSE_ORDOS) {
		xSrc = (g_playerHouseID * 56 + 8) / 8;
	}

	GUI_Screen_Copy(xSrc, 136, 0, 8, 7, 56, SCREEN_1, SCREEN_1);

	if (g_playerHouseID > HOUSE_ORDOS) {
		xSrc += 7;
	}

	GUI_Screen_Copy(xSrc, 136, 33, 8, 7, 56, SCREEN_1, SCREEN_1);

	GUI_DrawFilledRectangle(8, 136, 175, 191, 116);

	if (hallOfFame) {
		GUI_DrawFilledRectangle(8, 80, 311, 191, 116);
		if (score != 0xFFFF) GUI_HallOfFame_DrawRank(score, false);
	} else {
		GFX_Screen_Copy2(8, 80, 8, 116, 304, 36, SCREEN_1, SCREEN_1, false);
		if (g_scenarioID != 1) GFX_Screen_Copy2(8, 80, 8, 152, 304, 36, SCREEN_1, SCREEN_1, false);
	}

	if (score != 0xFFFF) {
		char buffer[64];
		snprintf(buffer, sizeof(buffer), String_Get_ByIndex(STR_TIME_DH_DM), s_ticksPlayed / 60, s_ticksPlayed % 60);

		if (s_ticksPlayed < 60) {
			char *hours = strchr(buffer, '0');
			while (*hours != ' ') memmove(hours, hours + 1, strlen(hours));
		}

		/* "Score: %d" */
		GUI_DrawText_Wrapper(String_Get_ByIndex(STR_SCORE_D), 72, 15, 15, 0, 0x22, score);
		GUI_DrawText_Wrapper(buffer, 248, 15, 15, 0, 0x222);
		/* "You have attained the rank of" */
		GUI_DrawText_Wrapper(String_Get_ByIndex(STR_YOU_HAVE_ATTAINED_THE_RANK_OF), SCREEN_WIDTH / 2, 38, 15, 0, 0x122);
	} else {
		/* "Hall of Fame" */
		GUI_DrawText_Wrapper(String_Get_ByIndex(STR_HALL_OF_FAME2), SCREEN_WIDTH / 2, 15, 15, 0, 0x122);
	}

	switch (g_playerHouseID) {
		case HOUSE_HARKONNEN:
			colour = 149;
			offset = 0;
			break;

		default:
			colour = 165;
			offset = 2;
			break;

		case HOUSE_ORDOS:
			colour = 181;
			offset = 1;
			break;
	}

	s_palette1_houseColour = g_palette1 + 255 * 3;
	memcpy(s_palette1_houseColour, g_palette1 + colour * 3, 3);
	s_palette1_houseColour += offset;

	if (!hallOfFame) GUI_HallOfFame_Tick();

	GFX_Screen_SetActive(oldScreenID);
}

static void GUI_EndStats_Sleep(uint16 delay)
{
	for (g_timerTimeout = delay; g_timerTimeout != 0; sleepIdle()) {
		GUI_HallOfFame_Tick();
	}
}

/**
 * Shows the stats at end of scenario.
 * @param killedAllied The amount of destroyed allied units.
 * @param killedEnemy The amount of destroyed enemy units.
 * @param destroyedAllied The amount of destroyed allied structures.
 * @param destroyedEnemy The amount of destroyed enemy structures.
 * @param harvestedAllied The amount of spice harvested by allies.
 * @param harvestedEnemy The amount of spice harvested by enemies.
 * @param score The base score.
 * @param houseID The houseID of the player.
 */
void GUI_EndStats_Show(uint16 killedAllied, uint16 killedEnemy, uint16 destroyedAllied, uint16 destroyedEnemy, uint16 harvestedAllied, uint16 harvestedEnemy, int16 score, uint8 houseID)
{
	Screen oldScreenID;
	uint16 statsBoxCount;
	uint16 textLeft;	/* text left position */
	uint16 statsBarWidth;	/* available width to draw the score bars */
	struct { uint16 value; uint16 increment; } scores[3][2];
	uint16 i;

	s_ticksPlayed = ((g_timerGame - g_tickScenarioStart) / 3600) + 1;

	score = Update_Score(score, &harvestedAllied, &harvestedEnemy, houseID);

	/* 1st scenario doesn't have the "Building destroyed" stats */
	statsBoxCount = (g_scenarioID == 1) ? 2 : 3;

	GUI_Mouse_Hide_Safe();

	GUI_ChangeSelectionType(SELECTIONTYPE_MENTAT);

	oldScreenID = GFX_Screen_SetActive(SCREEN_1);

	GUI_HallOfFame_DrawBackground(score, false);

	GUI_DrawTextOnFilledRectangle(String_Get_ByIndex(STR_SPICE_HARVESTED_BY), 83);
	GUI_DrawTextOnFilledRectangle(String_Get_ByIndex(STR_UNITS_DESTROYED_BY), 119);
	if (g_scenarioID != 1) GUI_DrawTextOnFilledRectangle(String_Get_ByIndex(STR_BUILDINGS_DESTROYED_BY), 155);

	textLeft = 19 + max(Font_GetStringWidth(String_Get_ByIndex(STR_YOU)), Font_GetStringWidth(String_Get_ByIndex(STR_ENEMY)));
	statsBarWidth = 261 - textLeft;

	for (i = 0; i < statsBoxCount; i++) {
		GUI_DrawText_Wrapper(String_Get_ByIndex(STR_YOU), textLeft - 4,  92 + (i * 36), 0xF, 0, 0x221);
		GUI_DrawText_Wrapper(String_Get_ByIndex(STR_ENEMY), textLeft - 4, 101 + (i * 36), 0xF, 0, 0x221);
	}

	Music_Play(17 + Tools_RandomLCG_Range(0, 5));

	GUI_Screen_Copy(0, 0, 0, 0, SCREEN_WIDTH / 8, SCREEN_HEIGHT, SCREEN_1, SCREEN_0);

	Input_History_Clear();

	scores[0][0].value = harvestedAllied;
	scores[0][1].value = harvestedEnemy;
	scores[1][0].value = killedEnemy;
	scores[1][1].value = killedAllied;
	scores[2][0].value = destroyedEnemy;
	scores[2][1].value = destroyedAllied;

	for (i = 0; i < statsBoxCount; i++) {
		uint16 scoreIncrement;

		/* You */
		if (scores[i][0].value > 65000) scores[i][0].value = 65000;
		/* Enemy */
		if (scores[i][1].value > 65000) scores[i][1].value = 65000;

		scoreIncrement = 1 + (max(scores[i][0].value, scores[i][1].value) / statsBarWidth);

		scores[i][0].increment = scoreIncrement;
		scores[i][1].increment = scoreIncrement;
	}

	GUI_EndStats_Sleep(45);
	GUI_HallOfFame_DrawRank(score, true);
	GUI_EndStats_Sleep(45);

	for (i = 0; i < statsBoxCount; i++) {
		uint16 j;

		GUI_HallOfFame_Tick();

		for (j = 0; j < 2; j++) {	/* 0 : You, 1 : Enemy */
			uint8 colour;
			uint16 posX;
			uint16 posY;
			uint16 score;

			GUI_HallOfFame_Tick();

			colour = (j == 0) ? 255 : 209;
			posX = textLeft;
			posY = 93 + (i * 36) + (j * 9);

			for (score = 0; score < scores[i][j].value; score += scores[i][j].increment) {
				GUI_DrawFilledRectangle(271, posY, 303, posY + 5, 226);
				GUI_DrawText_Wrapper("%u", 287, posY - 1, 0x14, 0, 0x121, score);

				GUI_HallOfFame_Tick();

				g_timerTimeout = 1;

				GUI_DrawLine(posX, posY, posX, posY + 5, colour);

				posX++;

				GUI_DrawLine(posX, posY + 1, posX, posY + 6, 12);	/* shadow */

				GFX_Screen_Copy2(textLeft, posY, textLeft, posY, 304, 7, SCREEN_1, SCREEN_0, false);

				Driver_Sound_Play(52, 0xFF);

				GUI_EndStats_Sleep(g_timerTimeout);
			}

			GUI_DrawFilledRectangle(271, posY, 303, posY + 5, 226);
			GUI_DrawText_Wrapper("%u", 287, posY - 1, 0xF, 0, 0x121, scores[i][j].value);

			GFX_Screen_Copy2(textLeft, posY, textLeft, posY, 304, 7, SCREEN_1, SCREEN_0, false);

			Driver_Sound_Play(38, 0xFF);

			GUI_EndStats_Sleep(12);
		}

		GUI_EndStats_Sleep(60);
	}

	GUI_Mouse_Show_Safe();

	Input_History_Clear();

	for (;; sleepIdle()) {
		GUI_HallOfFame_Tick();
		if (Input_Keyboard_NextKey() != 0) break;
	}

	Input_History_Clear();

	GUI_HallOfFame_Show(score);

	memset(g_palette1 + 255 * 3, 0, 3);

	GFX_Screen_SetActive(oldScreenID);

	Driver_Music_FadeOut();
}

/**
 * Show pick house screen.
 */
uint8 GUI_PickHouse(void)
{
	Screen oldScreenID;
	Widget *w = NULL;
	uint8 palette[3 * 256];
	uint16 i;
	HouseType houseID;

	houseID = HOUSE_MERCENARY;

	memset(palette, 0, 256 * 3);

	Driver_Voice_Play(NULL, 0xFF);

	Voice_LoadVoices(5);

	for (;; sleepIdle()) {
		uint16 yes_no;

		for (i = 0; i < 3; i++) {
			static const uint8 l_houses[3][3] = {
				/* x, y, shortcut */
				{ 16, 56, 31 }, /* A */
				{ 112, 56, 25 }, /* O */
				{ 208, 56, 36 }, /* H */
			};
			Widget *w2;

			w2 = GUI_Widget_Allocate(i + 1, l_houses[i][2], l_houses[i][0], l_houses[i][1], 0xFFFF, 0);

			memset(&w2->flags, 0, sizeof(w2->flags));
			w2->flags.loseSelect = true;
			w2->flags.buttonFilterLeft = 1;
			w2->flags.buttonFilterRight = 1;
			w2->width  = 96;
			w2->height = 104;

			w = GUI_Widget_Link(w, w2);
		}

		if (File_Exists("HERALD.CPS")) Sprites_LoadImage("HERALD.CPS", SCREEN_1, NULL);
		else Sprites_LoadImage(String_GenerateFilename("HERALD"), SCREEN_1, NULL);

		GUI_Mouse_Hide_Safe();
		GUI_Screen_Copy(0, 0, 0, 0, SCREEN_WIDTH / 8, SCREEN_HEIGHT, SCREEN_1, SCREEN_0);
		GUI_SetPaletteAnimated(g_palette1, 15);
		GUI_Mouse_Show_Safe();

		for (houseID = HOUSE_INVALID; houseID == HOUSE_INVALID; sleepIdle()) {
			uint16 key = GUI_Widget_HandleEvents(w);

			GUI_PaletteAnimate();

			if ((key & 0x800) != 0) key = 0;

			switch (key) {
				case 0x8001: houseID = HOUSE_ATREIDES; break;
				case 0x8002: houseID = HOUSE_ORDOS; break;
				case 0x8003: houseID = HOUSE_HARKONNEN; break;
				default: break;
			}
		}

		GUI_Mouse_Hide_Safe();

		if (g_enableVoices != 0) {
			Sound_Output_Feedback(houseID + 62);

			while (Sound_StartSpeech()) sleepIdle();
		}

		while (w != NULL) {
			Widget *next = w->next;

			free(w);

			w = next;
		}

		GUI_SetPaletteAnimated(palette, 15);

		if (g_debugSkipDialogs || g_debugScenario) {
			Debug("Skipping House selection confirmation.\n");
			break;
		}

		w = GUI_Widget_Link(w, GUI_Widget_Allocate(1, GUI_Widget_GetShortcut(String_Get_ByIndex(STR_YES)[0]), 168, 168, 373, 0));
		w = GUI_Widget_Link(w, GUI_Widget_Allocate(2, GUI_Widget_GetShortcut(String_Get_ByIndex(STR_NO)[0]), 240, 168, 375, 0));

		g_playerHouseID = HOUSE_MERCENARY;

		oldScreenID = GFX_Screen_SetActive(SCREEN_0);

		GUI_Mouse_Show_Safe();

		strncpy(g_readBuffer, String_Get_ByIndex(STR_HOUSE_HARKONNENFROM_THE_DARK_WORLD_OF_GIEDI_PRIME_THE_SAVAGE_HOUSE_HARKONNEN_HAS_SPREAD_ACROSS_THE_UNIVERSE_A_CRUEL_PEOPLE_THE_HARKONNEN_ARE_RUTHLESS_TOWARDS_BOTH_FRIEND_AND_FOE_IN_THEIR_FANATICAL_PURSUIT_OF_POWER + houseID * 40), g_readBufferSize);
		GUI_Mentat_Show(g_readBuffer, House_GetWSAHouseFilename(houseID), NULL);

		if (File_Exists("MISC.CPS")) Sprites_LoadImage("MISC.CPS", SCREEN_1, g_palette1);
		else Sprites_LoadImage(String_GenerateFilename("MISC"), SCREEN_1, g_palette1);

		GUI_Mouse_Hide_Safe();

		GUI_Screen_Copy(0, 0, 0, 0, 26, 24, SCREEN_1, SCREEN_0);

		GUI_Screen_Copy(0, 24 * (houseID + 1), 26, 0, 13, 24, SCREEN_1, SCREEN_0);

		GUI_Widget_DrawAll(w);

		GUI_Mouse_Show_Safe();

		for (;; sleepIdle()) {
			yes_no = GUI_Mentat_Loop(House_GetWSAHouseFilename(houseID), NULL, NULL, true, w);

			if ((yes_no & 0x8000) != 0) break;
		}

		if (yes_no == 0x8001) {
			Driver_Music_FadeOut();
		} else {
			GUI_SetPaletteAnimated(palette, 15);
		}

		while (w != NULL) {
			Widget *next = w->next;

			free(w);

			w = next;
		}

		Load_Palette_Mercenaries();
		Sprites_LoadTiles();

		GFX_Screen_SetActive(oldScreenID);

		while (Driver_Voice_IsPlaying()) sleepIdle();

		if (yes_no == 0x8001) break;
	}

	Music_Play(0);

	GUI_Palette_CreateRemap(houseID);

	Input_History_Clear();

	GUI_Mouse_Show_Safe();

	GUI_SetPaletteAnimated(palette, 15);

	return houseID;
}

/**
 * Creates a palette mapping: colour -> colour + reference * intensity.
 *
 * @param palette The palette to create the mapping for.
 * @param colours The resulting mapping.
 * @param reference The colour to use as reference.
 * @param intensity The intensity to use.
 */
void GUI_Palette_CreateMapping(const uint8 *palette, uint8 *colours, uint8 reference, uint8 intensity)
{
	uint16 index;

	if (palette == NULL || colours == NULL) return;

	colours[0] = 0;

	for (index = 1; index < 256; index++) {
		uint16 i;
		uint8 red   = palette[3 * index + 0] - (((palette[3 * index + 0] - palette[3 * reference + 0]) * (intensity / 2)) >> 7);
		uint8 blue  = palette[3 * index + 1] - (((palette[3 * index + 1] - palette[3 * reference + 1]) * (intensity / 2)) >> 7);
		uint8 green = palette[3 * index + 2] - (((palette[3 * index + 2] - palette[3 * reference + 2]) * (intensity / 2)) >> 7);
		uint8 colour = reference;
		uint16 sumMin = 0xFFFF;

		for (i = 1; i < 256; i++) {
			uint16 sum = 0;

			sum += (palette[3 * i + 0] - red)   * (palette[3 * i + 0] - red);
			sum += (palette[3 * i + 1] - blue)  * (palette[3 * i + 1] - blue);
			sum += (palette[3 * i + 2] - green) * (palette[3 * i + 2] - green);

			if (sum > sumMin) continue;
			if ((i != reference) && (i == index)) continue;

			sumMin = sum;
			colour = i & 0xFF;
		}

		colours[index] = colour;
	}
}

/**
 * Draw a border.
 *
 * @param left Left position of the border.
 * @param top Top position of the border.
 * @param width Width of the border.
 * @param height Height of the border.
 * @param colourSchemaIndex Index of the colourSchema used.
 * @param fill True if you want the border to be filled.
 */
void GUI_DrawBorder(uint16 left, uint16 top, uint16 width, uint16 height, uint16 colourSchemaIndex, bool fill)
{
	uint16 *colourSchema;

	/* ENHANCEMENT -- On ST/STE, GUI_DrawFilledRectangle()/GUI_DrawLine()
	 * below already present straight to planar and need no dirty mark of
	 * their own. This explicit mark predates that conversion; left as-is
	 * it becomes a stale dirty rect that nothing ever clears, later
	 * reprocessed by the old c2p sweep from SCREEN_1 and overwriting the
	 * just-drawn planar content (e.g. a menu box border+text). Skip it
	 * for the direct-planar case, same as those two functions do. */
	if (!fill && !(GFX_Screen_IsActive(SCREEN_0) && Video_Atari_CursorDirect())) {
		GFX_Screen_SetDirtySource(DIRTY_SRC_RECT);
		GFX_Screen_SetDirty(SCREEN_ACTIVE, left, top, left + width, top + height);
	}

	width  -= 1;
	height -= 1;

	colourSchema = s_colourBorderSchema[colourSchemaIndex];

	if (fill) GUI_DrawFilledRectangle(left, top, left + width, top + height, colourSchema[0] & 0xFF);

	GUI_DrawLine(left, top + height, left + width, top + height, colourSchema[1] & 0xFF);
	GUI_DrawLine(left + width, top, left + width, top + height, colourSchema[1] & 0xFF);
	GUI_DrawLine(left, top, left + width, top, colourSchema[2] & 0xFF);
	GUI_DrawLine(left, top, left, top + height, colourSchema[2] & 0xFF);

	GFX_PutPixel(left, top + height, colourSchema[3] & 0xFF);
	GFX_PutPixel(left + width, top, colourSchema[3] & 0xFF);
}

/**
 * Display a hint to the user. Only show each hint exactly once.
 *
 * @param stringID The string of the hint to show.
 * @param spriteID The sprite to show with the hint.
 * @return Zero or the return value of GUI_DisplayModalMessage.
 */
uint16 GUI_DisplayHint(uint16 stringID, uint16 spriteID)
{
	uint32 *hintsShown;
	uint32 mask;
	uint16 hint;

	if (g_debugGame || stringID == STR_NULL || !g_gameConfig.hints || g_selectionType == SELECTIONTYPE_MENTAT) return 0;

	hint = stringID - STR_YOU_MUST_BUILD_A_WINDTRAP_TO_PROVIDE_POWER_TO_YOUR_BASE_WITHOUT_POWER_YOUR_STRUCTURES_WILL_DECAY;

	assert(hint < 64);

	if (hint < 32) {
		mask = (1 << hint);
		hintsShown = &g_hintsShown1;
	} else {
		mask = (1 << (hint - 32));
		hintsShown = &g_hintsShown2;
	}

	if ((*hintsShown & mask) != 0) return 0;
	*hintsShown |= mask;

	return GUI_DisplayModalMessage(String_Get_ByIndex(stringID), spriteID);
}

void GUI_DrawProgressbar(uint16 current, uint16 max)
{
	static uint16 l_info[11] = { 293, 52, 24, 7, 1, 0, 0, 0, 4, 5, 8 };

	uint16 width;
	uint16 height;
	uint16 colour;

	l_info[7] = max;
	l_info[6] = current;

	if (current > max) current = max;
	if (max < 1) max = 1;

	width  = l_info[2];
	height = l_info[3];

	/* 0 = Horizontal, 1 = Vertial */
	if (l_info[5] == 0) {
		width = current * width / max;
		if (width < 1) width = 1;
	} else {
		height = current * height / max;
		if (height < 1) height = 1;
	}

	colour = l_info[8];
	if (current <= max / 2) colour = l_info[9];
	if (current <= max / 4) colour = l_info[10];

	if (current != 0 && width  == 0) width = 1;
	if (current != 0 && height == 0) height = 1;

	if (height != 0) {
		GUI_DrawBorder(l_info[0] - 1, l_info[1] - 1, l_info[2] + 2, l_info[3] + 2, 1, true);
	}

	if (width != 0) {
		GUI_DrawFilledRectangle(l_info[0], l_info[1] + l_info[3] - height, l_info[0] + width - 1, l_info[1] + l_info[3] - 1, (uint8)colour);
	}
}

/**
 * Draw the interface (borders etc etc) and radar on the screen.
 * @param screenID The screen to draw the radar on. if SCREEN_0, SCREEN_1 is used as back buffer
 */
void GUI_DrawInterfaceAndRadar(Screen screenID)
{
	PoolFindStruct find;
	Screen oldScreenID;
	Widget *w;

	oldScreenID = GFX_Screen_SetActive((screenID == SCREEN_0) ? SCREEN_1 : screenID);

	g_viewport_forceRedraw = true;

	Sprites_LoadImage("SCREEN.CPS", SCREEN_1, NULL);
	GUI_DrawSprite(SCREEN_1, g_sprites[11], 11, GUI_SPRITE_COLOUR_EMBEDDED, 192, 0, 0, 0); /* "Credits" */

	GUI_Palette_RemapScreen(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_1, g_remap);


	g_textDisplayNeedsUpdate = true;

	GUI_Widget_Viewport_RedrawMap(SCREEN_ACTIVE);

	GUI_DrawScreen(SCREEN_ACTIVE);

	GUI_Widget_ActionPanel_Draw(true);

	w = GUI_Widget_Get_ByIndex(g_widgetLinkedListHead, 1);
	GUI_Widget_Draw(w);

	w = GUI_Widget_Get_ByIndex(g_widgetLinkedListHead, 2);
	GUI_Widget_Draw(w);

	find.houseID = HOUSE_INVALID;
	find.index   = 0xFFFF;
	find.type    = 0xFFFF;

	while (true) {
		Structure *s;

		s = Structure_Find(&find);
		if (s == NULL) break;
		if (s->o.type == STRUCTURE_SLAB_1x1 || s->o.type == STRUCTURE_SLAB_2x2 || s->o.type == STRUCTURE_WALL) continue;

		Structure_UpdateMap(s);
	}

	find.houseID = HOUSE_INVALID;
	find.index   = 0xFFFF;
	find.type    = 0xFFFF;

	while (true) {
		Unit *u;

		u = Unit_Find(&find);
		if (u == NULL) break;

		Unit_UpdateMap(1, u);
	}

	if (screenID == SCREEN_0) {
		GFX_Screen_SetActive(SCREEN_0);

		GUI_Mouse_Hide_Safe();

		GUI_Screen_Copy(0, 0, 0, 0, SCREEN_WIDTH / 8, SCREEN_HEIGHT, SCREEN_1, SCREEN_0);
		GUI_DrawCredits(g_playerHouseID, (g_playerCredits == 0xFFFF) ? 2 : 1);
		GUI_SetPaletteAnimated(g_palette1, 15);

		GUI_Mouse_Show_Safe();
	}

	GFX_Screen_SetActive(oldScreenID);

	GUI_DrawCredits(g_playerHouseID, 2);

	Input_History_Clear();
}

#ifdef TOS
enum {
	CREDITS_CACHE_WIDTH = 64,
	CREDITS_CACHE_HEIGHT = 9,
	CREDITS_CACHE_GLYPH_SIZE = 8,
	CREDITS_CACHE_PADDING = 8,
	CREDITS_CACHE_BUFFER_HEIGHT = 24
};

static uint32 s_creditsBackground[CREDITS_CACHE_WIDTH * CREDITS_CACHE_HEIGHT / sizeof(uint32)];
static uint32 s_creditsGlyphs[11][CREDITS_CACHE_GLYPH_SIZE * CREDITS_CACHE_GLYPH_SIZE / sizeof(uint32)];
static bool s_creditsCacheReady = false;
static uint16 s_creditsPlanarBackground[CREDITS_CACHE_WIDTH * CREDITS_CACHE_HEIGHT / 4];
static uint16 s_creditsPlanarGlyphs[6][11][CREDITS_CACHE_GLYPH_SIZE][8];
static uint16 s_creditsPlanarMasks[6][2];
static uint16 s_creditsPlanarPaletteGeneration;
static bool s_creditsPlanarReady = false;

void GUI_InitCreditsCache(void)
{
	uint16 i;

	s_creditsCacheReady = false;
	s_creditsPlanarReady = false;
	if (!Video_Atari_CursorDirect()) return;

	if (g_sprites == NULL || g_sprites[12] == NULL ||
	    READ_LE_UINT16(g_sprites[12] + 3) < CREDITS_CACHE_WIDTH ||
	    g_sprites[12][2] < CREDITS_CACHE_HEIGHT) {
		Warning("Credits cache: missing or undersized background sprite\n");
		return;
	}
	for (i = 0; i < lengthof(s_creditsGlyphs); i++) {
		const uint8 *sprite = g_sprites[13 + i];

		if (sprite == NULL || READ_LE_UINT16(sprite + 3) != CREDITS_CACHE_GLYPH_SIZE ||
		    sprite[2] != CREDITS_CACHE_GLYPH_SIZE) {
			Warning("Credits cache: missing or unsupported glyph %u\n", i);
			return;
		}
	}

	memset(s_creditsBackground, 0, sizeof(s_creditsBackground));
	GUI_DrawSpriteToBuffer((uint8 *)s_creditsBackground, CREDITS_CACHE_WIDTH, CREDITS_CACHE_HEIGHT,
	                       g_sprites[12], 0, 0);
	memset(s_creditsGlyphs, 0, sizeof(s_creditsGlyphs));
	for (i = 0; i < lengthof(s_creditsGlyphs); i++) {
		GUI_DrawSpriteToBuffer((uint8 *)s_creditsGlyphs[i], CREDITS_CACHE_GLYPH_SIZE, CREDITS_CACHE_GLYPH_SIZE,
		                       g_sprites[13 + i], 0, 0);
	}
	for (i = 0; i < sizeof(s_creditsBackground); i++) {
		if (((const uint8 *)s_creditsBackground)[i] == 0) {
			Warning("Credits cache: background contains transparent pixels\n");
			return;
		}
	}
	for (i = 0; i < sizeof(s_creditsGlyphs); i++) {
		if (((const uint8 *)s_creditsGlyphs)[i] == 0) {
			Warning("Credits cache: glyphs contain transparent pixels\n");
			return;
		}
	}
	s_creditsCacheReady = true;
}

static void GUI_DrawCreditsGlyph(uint8 *buffer, uint16 glyph, uint16 x, int16 y)
{
	const uint8 *src;
	uint8 *dst;
	uint16 line;

	assert(glyph < lengthof(s_creditsGlyphs));
	assert(x + CREDITS_CACHE_GLYPH_SIZE <= CREDITS_CACHE_WIDTH);
	assert(y >= 0 && y + CREDITS_CACHE_GLYPH_SIZE <= CREDITS_CACHE_BUFFER_HEIGHT);
	src = (const uint8 *)s_creditsGlyphs[glyph];
	dst = buffer + (uint32)y * CREDITS_CACHE_WIDTH + x;
	for (line = 0; line < CREDITS_CACHE_GLYPH_SIZE; line++) {
		memcpy(dst, src, CREDITS_CACHE_GLYPH_SIZE);
		src += CREDITS_CACHE_GLYPH_SIZE;
		dst += CREDITS_CACHE_WIDTH;
	}
}

static void GUI_BuildCreditsPlanarCache(uint16 paletteGeneration)
{
	uint32 chunkyWords[16 * CREDITS_CACHE_GLYPH_SIZE / sizeof(uint32)] = {0};
	uint8 *chunky = (uint8 *)chunkyWords;
	uint16 pixels[CREDITS_CACHE_GLYPH_SIZE * 4];
	uint16 glyph, position, line, plane;

	Video_Atari_EncodePlanar((const uint8 *)s_creditsBackground, s_creditsPlanarBackground,
	                         CREDITS_CACHE_WIDTH, CREDITS_CACHE_HEIGHT);
	for (glyph = 0; glyph < lengthof(s_creditsGlyphs); glyph++) {
		for (line = 0; line < CREDITS_CACHE_GLYPH_SIZE; line++) {
			memcpy(chunky + line * 16, (const uint8 *)s_creditsGlyphs[glyph] + line * 8, 8);
		}
		Video_Atari_EncodePlanar(chunky, pixels, 16, CREDITS_CACHE_GLYPH_SIZE);
		for (position = 0; position < 6; position++) {
			uint16 shift = (position * 10 + 4) & 15;

			s_creditsPlanarMasks[position][0] = 0xff00u >> shift;
			s_creditsPlanarMasks[position][1] = shift > 8 ? (uint16)(0xff00u << (16 - shift)) : 0;
			for (line = 0; line < CREDITS_CACHE_GLYPH_SIZE; line++) {
				uint16 *row = s_creditsPlanarGlyphs[position][glyph][line];
				for (plane = 0; plane < 4; plane++) {
					uint16 bits = pixels[line * 4 + plane] & 0xff00u;
					row[plane] = bits >> shift;
					row[plane + 4] = shift > 8 ? (uint16)(bits << (16 - shift)) : 0;
				}
			}
		}
	}
	s_creditsPlanarPaletteGeneration = paletteGeneration;
	s_creditsPlanarReady = true;
}

static void GUI_DrawCreditsPlanarRows(uint16 *buffer, uint16 position, uint16 glyph,
                                     uint16 sourceRow, uint16 top, uint16 height)
{
	const uint16 (*rows)[8];
	uint16 *dst;
	uint16 keepFirst, keepSecond;

	assert(position < 6 && glyph < lengthof(s_creditsGlyphs));
	assert(sourceRow + height <= CREDITS_CACHE_GLYPH_SIZE && top + height <= CREDITS_CACHE_HEIGHT);
	rows = &s_creditsPlanarGlyphs[position][glyph][sourceRow];
	dst = buffer + top * (CREDITS_CACHE_WIDTH / 4) + ((position * 10 + 4) >> 4) * 4;
	keepFirst = (uint16)~s_creditsPlanarMasks[position][0];
	keepSecond = (uint16)~s_creditsPlanarMasks[position][1];
	while (height-- != 0) {
		const uint16 *src = *rows++;
		uint16 plane;
		for (plane = 0; plane < 4; plane++) dst[plane] = (dst[plane] & keepFirst) | src[plane];
		if (keepSecond != 0xffff) {
			for (plane = 0; plane < 4; plane++) dst[plane + 4] = (dst[plane + 4] & keepSecond) | src[plane + 4];
		}
		dst += CREDITS_CACHE_WIDTH / 4;
	}
}

static void GUI_FormatCredits(uint16 value, char buffer[7])
{
	static const uint16 places[] = {10000, 1000, 100, 10, 1};
	bool leading = true;
	uint16 i;

	buffer[0] = ' ';
	buffer[6] = '\0';
	for (i = 0; i < lengthof(places); i++) {
		uint16 digit = 0;

		while (value >= places[i]) {
			value -= places[i];
			digit++;
		}
		if (digit != 0 || i == lengthof(places) - 1) leading = false;
		buffer[i + 1] = leading ? ' ' : '0' + digit;
	}
}
#endif

/**
 * Draw the credits on the screen, and animate it when the value is changing.
 * @param houseID The house to display the credits from.
 * @param mode The mode of displaying. 0 = animate, 1 = force draw, 2 = reset.
 */
void GUI_DrawCredits(uint8 houseID, uint16 mode)
{
	static uint16 creditsAnimation = 0;           /* How many credits are shown in current animation of credits. */
	static int16  creditsAnimationOffset = 0;     /* Offset of the credits for the animation of credits. */
	static bool creditsSkipFrame;
	static uint16 creditsLastDrawn;
	static bool creditsLastDrawWasPlain;

	Screen oldScreenID = SCREEN_ACTIVE;
	uint16 oldWidgetId = 0;
	House *h;
	char charCreditsOld[7];
	char charCreditsNew[7];
	const char *creditsNewText;
	int i;
	int16 creditsDiff;
	uint16 creditsNew;
	uint16 creditsOld;
	int16 offset;
	int16 displayOffset;
#ifdef TOS
	bool direct = Video_Atari_CursorDirect();
	bool cached = direct && s_creditsCacheReady &&
	              g_widgetProperties[5].width * 8 == CREDITS_CACHE_WIDTH &&
	              g_widgetProperties[5].height == CREDITS_CACHE_HEIGHT;
	bool planar = cached && (g_widgetProperties[5].xBase & 1) == 0 &&
	              g_widgetProperties[5].xBase * 8 + CREDITS_CACHE_WIDTH <= SCREEN_WIDTH &&
	              g_widgetProperties[5].yBase + CREDITS_CACHE_HEIGHT <= SCREEN_HEIGHT;
#else
	bool direct = false;
#endif
	/* ENHANCEMENT: on ST/STE, draw straight into widget 5 -- the real
	 * on-screen credits position -- instead of widget 4, an off-screen
	 * SCREEN_1 scratch slot 40 pixels below it that gets copied up
	 * afterwards. That scratch slot sits inside the sidebar's
	 * structure-info panel (widget 6, y=42-124): during the digit
	 * scroll animation, sprites are drawn well outside their nominal
	 * 9px row (see the offset math below, which ranges roughly -14..+16
	 * relative to the row), so the scratch write corrupts whatever the
	 * info panel had just drawn there -- SCREEN_1 is shared, unlike the
	 * planar screen it eventually gets composited to.
	 *
	 * The planar cache composes only visible glyph rows in a private buffer.
	 * Unaligned widgets retain the padded chunky cache; unsupported assets
	 * or widget geometry retain the clipped GUI_DrawSprite() batch path.
	 * Neither direct path writes the shared SCREEN_1 workspace. */
	uint16 windowID = direct ? 5 : 4;
	Screen drawScreenID = direct ? SCREEN_0 : SCREEN_ACTIVE;
#ifdef TOS
	/* Cached glyphs extend beyond the visible slice, without clipping.
	 * Only the nine rows starting at the top padding are presented. */
	uint32 creditsBatchWords[CREDITS_CACHE_WIDTH * CREDITS_CACHE_BUFFER_HEIGHT / sizeof(uint32)];
	uint8 *creditsBatchBuf = (uint8 *)creditsBatchWords;
	uint8 *creditsBatchData = creditsBatchBuf + (cached ? CREDITS_CACHE_PADDING * CREDITS_CACHE_WIDTH : 0);
	uint16 creditsPlanar[CREDITS_CACHE_WIDTH * CREDITS_CACHE_HEIGHT / 4];
#endif

	if (s_tickCreditsAnimation > g_timerGUI && mode == 0) return;
	s_tickCreditsAnimation = g_timerGUI + 1;

	h = House_Get_ByIndex(houseID);

	if (mode == 2) {
		g_playerCredits = h->credits;
		creditsAnimation = h->credits;
	}

	if (mode == 0 && h->credits == creditsAnimation && creditsAnimationOffset == 0) return;

	creditsDiff = h->credits - creditsAnimation;
	if (creditsDiff != 0) {
		int16 diff = creditsDiff / 4;
		if (diff == 0)   diff = (creditsDiff < 0) ? -1 : 1;
		if (diff > 128)  diff = 128;
		if (diff < -128) diff = -128;
		creditsAnimationOffset += diff;
	} else {
		creditsAnimationOffset = 0;
	}

	if (creditsDiff != 0 && (creditsAnimationOffset < -7 || creditsAnimationOffset > 7)) {
		Driver_Sound_Play(creditsDiff > 0 ? 52 : 53, 0xFF);
	}

	if (creditsAnimationOffset < 0 && creditsAnimation == 0) creditsAnimationOffset = 0;

	creditsAnimation += creditsAnimationOffset / 8;

	if (creditsAnimationOffset > 0) creditsAnimationOffset &= 7;
	if (creditsAnimationOffset < 0) creditsAnimationOffset = -((-creditsAnimationOffset) & 7);

	creditsOld = creditsAnimation;
	creditsNew = creditsAnimation;
	offset = 1;

	if (creditsAnimationOffset < 0) {
		if (creditsOld > 0) creditsOld--;

		offset -= 8;
	}

	if (creditsAnimationOffset > 0) {
		creditsNew += 1;
	}

	/* Preserve counting and sound updates even when presentation is skipped. */
	g_playerCredits = creditsOld;
	if (mode == 0 && g_creditsPhase == 0 && creditsLastDrawWasPlain
		&& creditsOld == creditsLastDrawn) return;
	if (mode != 0 || g_creditsPhase != 2
		|| (creditsAnimation == h->credits && creditsAnimationOffset == 0)) {
		creditsSkipFrame = false;
	} else {
		bool skip = creditsSkipFrame;
		creditsSkipFrame = !creditsSkipFrame;
		if (skip) return;
	}

	displayOffset = creditsAnimationOffset;
	if (g_creditsPhase == 0) {
		creditsNew = creditsOld;
		displayOffset = 0;
		offset = 1;
	}

	if (direct) {
		GUI_Mouse_Hide_InWidget(5);
#ifdef TOS
		/* The clipped counter background covers all 64x9 batch pixels. */
		if (!planar) {
			GUI_DrawSprite_BeginOpaqueBatch(creditsBatchData,
			                                g_widgetProperties[windowID].xBase << 3,
			                                g_widgetProperties[windowID].yBase,
			                                g_widgetProperties[windowID].width << 3,
			                                g_widgetProperties[windowID].height);
		}
#endif
	} else {
		oldScreenID = GFX_Screen_SetActive(SCREEN_1);
		oldWidgetId = Widget_SetCurrentWidget(4);
	}

#ifdef TOS
	if (planar) {
		uint16 paletteGeneration = Video_Atari_GetPaletteGeneration();
		if (!s_creditsPlanarReady || paletteGeneration != s_creditsPlanarPaletteGeneration) {
			GUI_BuildCreditsPlanarCache(paletteGeneration);
		}
		memcpy(creditsPlanar, s_creditsPlanarBackground, sizeof(creditsPlanar));
	} else if (cached) {
		memcpy(creditsBatchData, s_creditsBackground, sizeof(s_creditsBackground));
	} else
#endif
	{
		GUI_DrawSprite(drawScreenID, g_sprites[12], 12, GUI_SPRITE_COLOUR_EMBEDDED, 0, 0, windowID, DRAWSPRITE_FLAG_WIDGETPOS);
	}

#ifdef TOS
	GUI_FormatCredits(creditsOld, charCreditsOld);
	if (creditsNew == creditsOld) {
		creditsNewText = charCreditsOld;
	} else {
		GUI_FormatCredits(creditsNew, charCreditsNew);
		creditsNewText = charCreditsNew;
	}
#else
	snprintf(charCreditsOld, sizeof(charCreditsOld), "%6hu", creditsOld);
	snprintf(charCreditsNew, sizeof(charCreditsNew), "%6hu", creditsNew);
	creditsNewText = charCreditsNew;
#endif

	for (i = 0; i < 6; i++) {
		uint16 left = i * 10 + 4;
		uint16 spriteID;

		spriteID = (charCreditsOld[i] == ' ') ? 13 : charCreditsOld[i] - 34;

#ifdef TOS
		if (planar) {
			if (charCreditsOld[i] != creditsNewText[i]) {
				uint16 firstRow = (displayOffset + 7) & 7;
				uint16 lowerRows = CREDITS_CACHE_GLYPH_SIZE - firstRow;

				GUI_DrawCreditsPlanarRows(creditsPlanar, i, spriteID - 13, firstRow, 0, lowerRows);
				spriteID = (creditsNewText[i] == ' ') ? 13 : creditsNewText[i] - 34;
				GUI_DrawCreditsPlanarRows(creditsPlanar, i, spriteID - 13, 0, lowerRows,
				                         CREDITS_CACHE_HEIGHT - lowerRows);
			} else {
				GUI_DrawCreditsPlanarRows(creditsPlanar, i, spriteID - 13, 0, 1, CREDITS_CACHE_GLYPH_SIZE);
			}
			continue;
		}
		if (cached) {
			if (charCreditsOld[i] != creditsNewText[i]) {
				GUI_DrawCreditsGlyph(creditsBatchBuf, spriteID - 13, left,
				                     CREDITS_CACHE_PADDING + offset - displayOffset);
				if (displayOffset != 0) {
					spriteID = (creditsNewText[i] == ' ') ? 13 : creditsNewText[i] - 34;
					GUI_DrawCreditsGlyph(creditsBatchBuf, spriteID - 13, left,
					                     CREDITS_CACHE_PADDING + offset + 8 - displayOffset);
				}
			} else {
				GUI_DrawCreditsGlyph(creditsBatchBuf, spriteID - 13, left, CREDITS_CACHE_PADDING + 1);
			}
			continue;
		}
#endif
		if (charCreditsOld[i] != creditsNewText[i]) {
			GUI_DrawSprite(drawScreenID, g_sprites[spriteID], spriteID, GUI_SPRITE_COLOUR_EMBEDDED, left, offset - displayOffset, windowID, DRAWSPRITE_FLAG_WIDGETPOS);
			if (displayOffset == 0) continue;

			spriteID = (creditsNewText[i] == ' ') ? 13 : creditsNewText[i] - 34;

			GUI_DrawSprite(drawScreenID, g_sprites[spriteID], spriteID, GUI_SPRITE_COLOUR_EMBEDDED, left, offset + 8 - displayOffset, windowID, DRAWSPRITE_FLAG_WIDGETPOS);
		} else {
			GUI_DrawSprite(drawScreenID, g_sprites[spriteID], spriteID, GUI_SPRITE_COLOUR_EMBEDDED, left, 1, windowID, DRAWSPRITE_FLAG_WIDGETPOS);
		}
	}

	creditsLastDrawn = creditsOld;
	creditsLastDrawWasPlain = g_creditsPhase == 0 || creditsAnimationOffset == 0;

	if (direct) {
#ifdef TOS
		if (planar) {
			if (!Video_Atari_PresentRestore(g_widgetProperties[windowID].xBase << 3,
			                              g_widgetProperties[windowID].yBase,
			                              CREDITS_CACHE_WIDTH, CREDITS_CACHE_HEIGHT,
			                              (const uint8 *)creditsPlanar)) {
				Warning("Credits planar presentation failed\n");
			}
		} else {
			GUI_DrawSprite_EndBatch();
		}
#endif
		GUI_Mouse_Show_InWidget();
		return;
	}

	if (!GFX_Screen_IsActive(oldScreenID)) {
		GUI_Mouse_Hide_InWidget(5);
		GUI_Screen_Copy(g_curWidgetXBase, g_curWidgetYBase, g_curWidgetXBase, g_curWidgetYBase - 40, g_curWidgetWidth, g_curWidgetHeight, SCREEN_ACTIVE, oldScreenID);
		GUI_Mouse_Show_InWidget();
	}

	GFX_Screen_SetActive(oldScreenID);

	Widget_SetCurrentWidget(oldWidgetId);
}

/**
 * Change the selection type.
 * @param selectionType The new selection type.
 */
void GUI_ChangeSelectionType(uint16 selectionType)
{
	Screen oldScreenID;

	if (selectionType == SELECTIONTYPE_UNIT && g_unitSelected == NULL) {
		selectionType = SELECTIONTYPE_STRUCTURE;
	}

	if (selectionType == SELECTIONTYPE_STRUCTURE && g_unitSelected != NULL) {
		g_unitSelected = NULL;
	}

	oldScreenID = GFX_Screen_SetActive(SCREEN_1);

	if (g_selectionType != selectionType) {
		uint16 oldSelectionType = g_selectionType;
		bool redrawAllWidgets = true;

#ifdef TOS
		/* Unit/target share the base widgets; the panel redraw handles their differences. */
		redrawAllWidgets = !(Video_Atari_CursorDirect()
			&& ((oldSelectionType == SELECTIONTYPE_UNIT && selectionType == SELECTIONTYPE_TARGET)
				|| (oldSelectionType == SELECTIONTYPE_TARGET && selectionType == SELECTIONTYPE_UNIT)));
		Video_Atari_PlacementHide();
#endif
		Timer_SetTimer(TIMER_GAME, false);

		g_selectionType = selectionType;
		g_selectionTypeNew = selectionType;
		g_var_37B8 = true;

		switch (oldSelectionType) {
			case SELECTIONTYPE_PLACE:
				Map_SetSelection(g_structureActivePosition);
				/* Fall-through */
			case SELECTIONTYPE_TARGET:
			case SELECTIONTYPE_STRUCTURE:
				g_cursorDefaultSpriteID = 0;
				GUI_DisplayText(NULL, -1);
				break;

			case SELECTIONTYPE_UNIT:
				if (g_unitSelected != NULL && selectionType != SELECTIONTYPE_TARGET && selectionType != SELECTIONTYPE_UNIT) {
					Unit_UpdateMap(2, g_unitSelected);
					g_unitSelected = NULL;
				}
				break;

			default:
				break;
		}

		if (g_table_selectionType[oldSelectionType].variable_04 && g_table_selectionType[selectionType].variable_06) {
			g_viewport_forceRedraw = true;
			g_viewport_fadein = true;

			GUI_DrawInterfaceAndRadar(SCREEN_0);
		}

		Widget_SetCurrentWidget(g_table_selectionType[selectionType].defaultWidget);

		if (g_curWidgetIndex != 0) {
			GUI_Widget_DrawBorder(g_curWidgetIndex, 0, false);
		}

		if (selectionType != SELECTIONTYPE_MENTAT) {
			Widget *w = g_widgetLinkedListHead;

			while (w != NULL) {
				const int8 *s = g_table_selectionType[selectionType].visibleWidgets;
				bool wasInvisible = w->flags.invisible;
				bool redrawWidget = redrawAllWidgets || w->state.selected;

				w->state.selected = false;
				w->flags.invisible = true;

				for (; *s != -1; s++) {
					if (*s == w->index) {
						w->flags.invisible = false;
						break;
					}
				}

				if (redrawWidget || wasInvisible != w->flags.invisible) GUI_Widget_Draw(w);
				w = GUI_Widget_GetNext(w);
			}

			if (redrawAllWidgets) GUI_Widget_DrawAll(g_widgetLinkedListHead);
			g_textDisplayNeedsUpdate = true;
		}

		switch (g_selectionType) {
			case SELECTIONTYPE_MENTAT:
				if (oldSelectionType != SELECTIONTYPE_INTRO) {
					g_cursorSpriteID = 0;

					Sprites_SetMouseSprite(0, 0, g_sprites[0]);
				}

				Widget_SetCurrentWidget(g_table_selectionType[selectionType].defaultWidget);
				break;

			case SELECTIONTYPE_TARGET:
				g_structureActivePosition = g_selectionPosition;
				GUI_Widget_ActionPanel_Draw(true);

				g_cursorDefaultSpriteID = 5;

				Timer_SetTimer(TIMER_GAME, true);
				break;

			case SELECTIONTYPE_PLACE:
				Unit_Select(NULL);
				GUI_Widget_ActionPanel_Draw(true);

				Map_SetSelectionSize(g_table_structureInfo[g_structureActiveType].layout);

				Timer_SetTimer(TIMER_GAME, true);
				break;

			case SELECTIONTYPE_UNIT:
				GUI_Widget_ActionPanel_Draw(true);

				Timer_SetTimer(TIMER_GAME, true);
				break;

			case SELECTIONTYPE_STRUCTURE:
				GUI_Widget_ActionPanel_Draw(true);

				Timer_SetTimer(TIMER_GAME, true);
				break;

			default: break;
		}
	}

	GFX_Screen_SetActive(oldScreenID);
}

/**
 * Sets the colours to be used when drawing chars.
 * @param colours The colours to use.
 * @param min The index of the first colour to set.
 * @param max The index of the last colour to set.
 */
void GUI_InitColors(const uint8 *colours, uint8 first, uint8 last)
{
	uint8 i;

	first &= 0xF;
	last &= 0xF;

	if (last < first || colours == NULL) return;

	for (i = first; i < last + 1; i++) g_colours[i] = *colours++;
}

/**
 * Get how the given point must be clipped.
 * @param x The X-coordinate of the point.
 * @param y The Y-coordinate of the point.
 * @return A bitset.
 */
static uint16 GetNeededClipping(int16 x, int16 y)
{
	uint16 flags = 0;

	if (y < g_clipping.top)    flags |= 0x1;
	if (y > g_clipping.bottom) flags |= 0x2;
	if (x < g_clipping.left)   flags |= 0x4;
	if (x > g_clipping.right)  flags |= 0x8;

	return flags;
}

/**
 * Applies top clipping to a line.
 * @param x1 Pointer to the X-coordinate of the begin of the line.
 * @param y1 Pointer to the Y-coordinate of the begin of the line.
 * @param x2 The X-coordinate of the end of the line.
 * @param y2 The Y-coordinate of the end of the line.
 */
static void ClipTop(int16 *x1, int16 *y1, int16 x2, int16 y2)
{
	*x1 += (x2 - *x1) * (g_clipping.top - *y1) / (y2 - *y1);
	*y1 = g_clipping.top;
}

/**
 * Applies bottom clipping to a line.
 * @param x1 Pointer to the X-coordinate of the begin of the line.
 * @param y1 Pointer to the Y-coordinate of the begin of the line.
 * @param x2 The X-coordinate of the end of the line.
 * @param y2 The Y-coordinate of the end of the line.
 */
static void ClipBottom(int16 *x1, int16 *y1, int16 x2, int16 y2)
{
	*x1 += (x2 - *x1) * (*y1 - g_clipping.bottom) / (*y1 - y2);
	*y1 = g_clipping.bottom;
}

/**
 * Applies left clipping to a line.
 * @param x1 Pointer to the X-coordinate of the begin of the line.
 * @param y1 Pointer to the Y-coordinate of the begin of the line.
 * @param x2 The X-coordinate of the end of the line.
 * @param y2 The Y-coordinate of the end of the line.
 */
static void ClipLeft(int16 *x1, int16 *y1, int16 x2, int16 y2)
{
	*y1 += (y2 - *y1) * (g_clipping.left - *x1) / (x2 - *x1);
	*x1 = g_clipping.left;
}

/**
 * Applies right clipping to a line.
 * @param x1 Pointer to the X-coordinate of the begin of the line.
 * @param y1 Pointer to the Y-coordinate of the begin of the line.
 * @param x2 The X-coordinate of the end of the line.
 * @param y2 The Y-coordinate of the end of the line.
 */
static void ClipRight(int16 *x1, int16 *y1, int16 x2, int16 y2)
{
	*y1 += (y2 - *y1) * (*x1 - g_clipping.right) / (*x1 - x2);
	*x1 = g_clipping.right;
}

/**
 * Draws a line from (x1, y1) to (x2, y2) using given colour.
 * @param x1 The X-coordinate of the begin of the line.
 * @param y1 The Y-coordinate of the begin of the line.
 * @param x2 The X-coordinate of the end of the line.
 * @param y2 The Y-coordinate of the end of the line.
 * @param colour The colour to use to draw the line.
 */
void GUI_DrawLine(int16 x1, int16 y1, int16 x2, int16 y2, uint8 colour)
{
	uint8 *screen = GFX_Screen_GetActive();
	int16 increment = 1;

	if (x1 < g_clipping.left || x1 > g_clipping.right || y1 < g_clipping.top || y1 > g_clipping.bottom || x2 < g_clipping.left || x2 > g_clipping.right || y2 < g_clipping.top || y2 > g_clipping.bottom) {
		while (true) {
			uint16 clip1 = GetNeededClipping(x1, y1);
			uint16 clip2 = GetNeededClipping(x2, y2);

			if (clip1 == 0 && clip2 == 0) break;
			if ((clip1 & clip2) != 0) return;

			switch (clip1) {
				case 1: case 9:  ClipTop(&x1, &y1, x2, y2); break;
				case 2: case 6:  ClipBottom(&x1, &y1, x2, y2); break;
				case 4: case 5:  ClipLeft(&x1, &y1, x2, y2); break;
				case 8: case 10: ClipRight(&x1, &y1, x2, y2); break;
				default:
					switch (clip2) {
						case 1: case 9:  ClipTop(&x2, &y2, x1, y1); break;
						case 2: case 6:  ClipBottom(&x2, &y2, x1, y1); break;
						case 4: case 5:  ClipLeft(&x2, &y2, x1, y1); break;
						case 8: case 10: ClipRight(&x2, &y2, x1, y1); break;
						default: break;
					}
			}
		}
	}

	y2 -= y1;

	if (y2 == 0) {
		if (x1 >= x2) {
			int16 x = x1;
			x1 = x2;
			x2 = x;
		}

		x2 -= x1 - 1;

#ifdef TOS
		/* EXPERIMENT: skip-write style barrier -- horizontal segment has
		 * a direct planar fill equivalent, so skip the chunky memset
		 * entirely on ST/STE direct-cursor builds (this is the fast path
		 * GUI_DrawBorder's top/bottom edges always take). */
		if (GFX_Screen_IsActive(SCREEN_0) && Video_Atari_CursorDirect()) {
			Video_Atari_PresentFill(x1, y1, (uint16)x2, 1, colour);
			return;
		}
#endif

		screen += y1 * SCREEN_WIDTH + x1;

		memset(screen, colour, x2);
		return;
	}

	if (y2 < 0) {
		int16 x = x1;
		x1 = x2;
		x2 = x;
		y2 = -y2;
		y1 -= y2;
	}

	screen += y1 * SCREEN_WIDTH;

	x2 -= x1;
	if (x2 == 0) {
#ifdef TOS
		/* EXPERIMENT: same skip-write barrier as the horizontal case above,
		 * for vertical segments (GUI_DrawBorder's left/right edges). */
		if (GFX_Screen_IsActive(SCREEN_0) && Video_Atari_CursorDirect()) {
			Video_Atari_PresentFill(x1, y1, 1, (uint16)y2, colour);
			return;
		}
#endif

		screen += x1;

		while (y2-- != 0) {
			*screen = colour;
			screen += SCREEN_WIDTH;
		}

		return;
	}

	if (x2 < 0) {
		x2 = -x2;
		increment = -1;
	}

	if (x2 < y2) {
		int16 full = y2;
		int16 half = y2 / 2;
		screen += x1;
		while (true) {
			*screen = colour;
			if (y2-- == 0) return;
			screen += SCREEN_WIDTH;
			half -= x2;
			if (half < 0) {
				half += full;
				screen += increment;
			}
		}
	} else {
		int16 full = x2;
		int16 half = x2 / 2;
		screen += x1;
		while (true) {
			*screen = colour;
			if (x2-- == 0) return;
			screen += increment;
			half -= y2;
			if (half < 0) {
				half += full;
				screen += SCREEN_WIDTH;
			}
		}
	}
}

/**
 * Sets the clipping area.
 * @param left The left clipping.
 * @param top The top clipping.
 * @param right The right clipping.
 * @param bottom The bottom clipping.
 */
void GUI_SetClippingArea(uint16 left, uint16 top, uint16 right, uint16 bottom)
{
	g_clipping.left   = left;
	g_clipping.top    = top;
	g_clipping.right  = right;
	g_clipping.bottom = bottom;
}

/**
 * Wrapper around GFX_Screen_Copy. Protects against wrong input values.
 * @param xSrc The X-coordinate on the source divided by 8.
 * @param ySrc The Y-coordinate on the source.
 * @param xDst The X-coordinate on the destination divided by 8.
 * @param yDst The Y-coordinate on the destination.
 * @param width The width divided by 8.
 * @param height The height.
 * @param screenSrc The ID of the source screen.
 * @param screenDst The ID of the destination screen.
 */
void GUI_Screen_Copy(int16 xSrc, int16 ySrc, int16 xDst, int16 yDst, int16 width, int16 height, Screen screenSrc, Screen screenDst)
{
	if (width  > SCREEN_WIDTH / 8) width  = SCREEN_WIDTH / 8;
	if (height > SCREEN_HEIGHT)    height = SCREEN_HEIGHT;

	if (xSrc < 0) {
		xDst -= xSrc;
		width += xSrc;
		xSrc = 0;
	}

	if (xSrc >= SCREEN_WIDTH / 8 || xDst >= SCREEN_WIDTH / 8) return;

	if (xDst < 0) {
		xSrc -= xDst;
		width += xDst;
		xDst = 0;
	}

	if (ySrc < 0) {
		yDst -= ySrc;
		height += ySrc;
		ySrc = 0;
	}

	if (yDst < 0) {
		ySrc -= yDst;
		height += yDst;
		yDst = 0;
	}

	GFX_Screen_Copy(xSrc * 8, ySrc, xDst * 8, yDst, width * 8, height, screenSrc, screenDst);
}

/**
 * Like GUI_Screen_Copy(), but source and destination are the same screen and
 * may overlap (used to shift the viewport buffer in place while scrolling).
 * See GFX_Screen_CopyOverlap() for the overlap-safety rationale.
 */
void GUI_Screen_CopyOverlap(int16 xSrc, int16 ySrc, int16 xDst, int16 yDst, int16 width, int16 height, Screen screen)
{
	if (width  > SCREEN_WIDTH / 8) width  = SCREEN_WIDTH / 8;
	if (height > SCREEN_HEIGHT)    height = SCREEN_HEIGHT;

	if (xSrc < 0) {
		xDst -= xSrc;
		width += xSrc;
		xSrc = 0;
	}

	if (xSrc >= SCREEN_WIDTH / 8 || xDst >= SCREEN_WIDTH / 8) return;

	if (xDst < 0) {
		xSrc -= xDst;
		width += xDst;
		xDst = 0;
	}

	if (ySrc < 0) {
		yDst -= ySrc;
		height += ySrc;
		ySrc = 0;
	}

	if (yDst < 0) {
		ySrc -= yDst;
		height += yDst;
		yDst = 0;
	}

	GFX_Screen_CopyOverlap(xSrc * 8, ySrc, xDst * 8, yDst, width * 8, height, screen);
}

static uint32 GUI_FactoryWindow_CreateWidgets(void)
{
	uint16 i;
	uint16 count = 0;
	WidgetInfo *wi = g_table_factoryWidgetInfo;
	Widget *w = s_factoryWindowWidgets;

	memset(w, 0, 13 * sizeof(Widget));

	for (i = 0; i < 13; i++, wi++) {
		if ((i == 8 || i == 9 || i == 10 || i == 12) && !g_factoryWindowStarport) continue;
		if (i == 11 && g_factoryWindowStarport) continue;
		if (i == 7 && g_factoryWindowUpgradeCost == 0) continue;

		count++;

		w->index     = i + 46;
		memset(&w->state, 0, sizeof(w->state));
		w->offsetX   = wi->offsetX;
		w->offsetY   = wi->offsetY;
		w->flags.requiresClick = (wi->flags & 0x0001) ? true : false;
		w->flags.notused1 = (wi->flags & 0x0002) ? true : false;
		w->flags.clickAsHover = (wi->flags & 0x0004) ? true : false;
		w->flags.invisible = (wi->flags & 0x0008) ? true : false;
		w->flags.greyWhenInvisible = (wi->flags & 0x0010) ? true : false;
		w->flags.noClickCascade = (wi->flags & 0x0020) ? true : false;
		w->flags.loseSelect = (wi->flags & 0x0040) ? true : false;
		w->flags.notused2 = (wi->flags & 0x0080) ? true : false;
		w->flags.buttonFilterLeft = (wi->flags >> 8) & 0x0f;
		w->flags.buttonFilterRight = (wi->flags >> 12) & 0x0f;
		w->shortcut  = (wi->shortcut < 0) ? abs(wi->shortcut) : GUI_Widget_GetShortcut(*String_Get_ByIndex(wi->shortcut));
		w->clickProc = wi->clickProc;
		w->width     = wi->width;
		w->height    = wi->height;

		if (wi->spriteID < 0) {
			w->drawModeNormal   = DRAW_MODE_NONE;
			w->drawModeSelected = DRAW_MODE_NONE;
			w->drawModeDown     = DRAW_MODE_NONE;
		} else {
			w->drawModeNormal   = DRAW_MODE_SPRITE;
			w->drawModeSelected = DRAW_MODE_SPRITE;
			w->drawModeDown     = DRAW_MODE_SPRITE;
			w->drawParameterNormal.sprite   = g_sprites[wi->spriteID];
			w->drawParameterSelected.sprite = g_sprites[wi->spriteID + 1];
			w->drawParameterDown.sprite     = g_sprites[wi->spriteID + 1];
		}

		if (i != 0) {
			g_widgetInvoiceTail = GUI_Widget_Link(g_widgetInvoiceTail, w);
		} else {
			g_widgetInvoiceTail = w;
		}

		w++;
	}

	GUI_Widget_DrawAll(g_widgetInvoiceTail);

	return count * sizeof(Widget);
}

static uint32 GUI_FactoryWindow_LoadGraymapTbl(void)
{
	uint8 fileID;

	fileID = File_Open("GRAYRMAP.TBL", FILE_MODE_READ);
	File_Read(fileID, s_factoryWindowGraymapTbl, 256);
	File_Close(fileID);

	return 256;
}

static uint16 GUI_FactoryWindow_CalculateStarportPrice(uint16 credits)
{
	credits = (credits / 10) * 4 + (credits / 10) * (Tools_RandomLCG_Range(0, 6) + Tools_RandomLCG_Range(0, 6));

	return min(credits, 999);
}

static int GUI_FactoryWindow_Sorter(const void *a, const void *b)
{
	const FactoryWindowItem *pa = a;
	const FactoryWindowItem *pb = b;

	return pb->sortPriority - pa->sortPriority;
}

static void GUI_FactoryWindow_InitItems(void)
{
	g_factoryWindowTotal = 0;
	g_factoryWindowSelected = 0;
	g_factoryWindowBase = 0;

	memset(g_factoryWindowItems, 0, 25 * sizeof(FactoryWindowItem));

	if (g_factoryWindowStarport) {
		uint16 seconds = (g_timerGame - g_tickScenarioStart) / 60;
		uint16 seed = (seconds / 60) + g_scenarioID + g_playerHouseID;
		seed *= seed;

		Tools_RandomLCG_Seed(seed);
	}

	if (!g_factoryWindowConstructionYard) {
		uint16 i;

		for (i = 0; i < UNIT_MAX; i++) {
			ObjectInfo *oi = &g_table_unitInfo[i].o;

			if (oi->available == 0) continue;

			g_factoryWindowItems[g_factoryWindowTotal].objectInfo = oi;
			g_factoryWindowItems[g_factoryWindowTotal].objectType = i;

			if (g_factoryWindowStarport) {
				g_factoryWindowItems[g_factoryWindowTotal].credits = GUI_FactoryWindow_CalculateStarportPrice(oi->buildCredits);
			} else {
				g_factoryWindowItems[g_factoryWindowTotal].credits = oi->buildCredits;
			}

			g_factoryWindowItems[g_factoryWindowTotal].sortPriority = oi->sortPriority;

			g_factoryWindowTotal++;
		}
	} else {
		uint16 i;

		for (i = 0; i < STRUCTURE_MAX; i++) {
			ObjectInfo *oi = &g_table_structureInfo[i].o;

			if (oi->available == 0) continue;

			g_factoryWindowItems[g_factoryWindowTotal].objectInfo    = oi;
			g_factoryWindowItems[g_factoryWindowTotal].objectType    = i;
			g_factoryWindowItems[g_factoryWindowTotal].credits       = oi->buildCredits;
			g_factoryWindowItems[g_factoryWindowTotal].sortPriority  = oi->sortPriority;

			if (i == 0 || i == 1) g_factoryWindowItems[g_factoryWindowTotal].sortPriority = 0x64;

			g_factoryWindowTotal++;
		}
	}

	if (g_factoryWindowTotal == 0) {
		GUI_DisplayModalMessage("ERROR: No items in construction list!", 0xFFFF);
		PrepareEnd();
		exit(0);
	}

	qsort(g_factoryWindowItems, g_factoryWindowTotal, sizeof(FactoryWindowItem), GUI_FactoryWindow_Sorter);
}

static void GUI_FactoryWindow_Init(void)
{
	static const uint8 xSrc[HOUSE_MAX] = { 0, 0, 16, 0, 0, 0 };
	static const uint8 ySrc[HOUSE_MAX] = { 8, 152, 48, 0, 0, 0 };
	Screen oldScreenID;
	void *wsa;
	int16 i;
	ObjectInfo *oi;

	oldScreenID = GFX_Screen_SetActive(SCREEN_1);

	Sprites_LoadImage("CHOAM.CPS", SCREEN_1, NULL);
	GUI_DrawSprite(SCREEN_1, g_sprites[11], 11, GUI_SPRITE_COLOUR_EMBEDDED, 192, 0, 0, 0); /* "Credits" */

	GUI_Palette_RemapScreen(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_1, g_remap);

	GUI_Screen_Copy(xSrc[g_playerHouseID], ySrc[g_playerHouseID], 0, 8, 7, 40, SCREEN_1, SCREEN_1);
	GUI_Screen_Copy(xSrc[g_playerHouseID], ySrc[g_playerHouseID], 0, 152, 7, 40, SCREEN_1, SCREEN_1);

	GUI_FactoryWindow_CreateWidgets();
	GUI_FactoryWindow_LoadGraymapTbl();
	GUI_FactoryWindow_InitItems();

	for (i = g_factoryWindowTotal; i < 4; i++) GUI_Widget_MakeInvisible(GUI_Widget_Get_ByIndex(g_widgetInvoiceTail, i + 46));

	for (i = 0; i < 4; i++) {
		FactoryWindowItem *item = GUI_FactoryWindow_GetItem(i);

		if (item == NULL) continue;

		oi = item->objectInfo;
		if (oi->available == -1) {
			GUI_DrawSprite(SCREEN_1, g_sprites[oi->spriteID], oi->spriteID, GUI_SPRITE_COLOUR_EMBEDDED, 72, 24 + i * 32, 0, DRAWSPRITE_FLAG_REMAP, s_factoryWindowGraymapTbl, 1);
		} else {
			GUI_DrawSprite(SCREEN_1, g_sprites[oi->spriteID], oi->spriteID, GUI_SPRITE_COLOUR_EMBEDDED, 72, 24 + i * 32, 0, 0);
		}
	}

	g_factoryWindowBase = 0;
	g_factoryWindowSelected = 0;

	oi = g_factoryWindowItems[0].objectInfo;

	wsa = WSA_LoadFile(oi->wsa, s_factoryWindowWsaBuffer, sizeof(s_factoryWindowWsaBuffer), false);
	WSA_DisplayFrame(wsa, 0, 128, 48, SCREEN_1);
	WSA_Unload(wsa);

	GUI_Mouse_Hide_Safe();
	GUI_Screen_Copy(0, 0, 0, 0, SCREEN_WIDTH / 8, SCREEN_HEIGHT, SCREEN_1, SCREEN_0);
	GUI_Mouse_Show_Safe();

	GUI_DrawFilledRectangle(64, 0, 112, SCREEN_HEIGHT - 1, GFX_GetPixel(72, 23));

	GUI_FactoryWindow_PrepareScrollList();

	GFX_Screen_SetActive(SCREEN_0);

	GUI_FactoryWindow_DrawDetails();

	GUI_DrawCredits(g_playerHouseID, 1);

	GFX_Screen_SetActive(oldScreenID);
}

/**
 * Display the window where you can order/build stuff for a structure.
 * @param isConstructionYard True if this is for a construction yard.
 * @param isStarPort True if this is for a starport.
 * @param upgradeCost Cost of upgrading the structure.
 * @return Unknown value.
 */
FactoryResult GUI_DisplayFactoryWindow(bool isConstructionYard, bool isStarPort, uint16 upgradeCost)
{
	Screen oldScreenID;
	uint8 backup[3];

	oldScreenID = GFX_Screen_SetActive(SCREEN_0);

	memcpy(backup, g_palette1 + 255 * 3, 3);

	g_factoryWindowConstructionYard = isConstructionYard; /* always same value as g_factoryWindowConstructionYard */
	g_factoryWindowStarport = isStarPort;
	g_factoryWindowUpgradeCost = upgradeCost;
	g_factoryWindowOrdered = 0;

	GUI_FactoryWindow_Init();

	GUI_FactoryWindow_UpdateSelection(true);

	for (g_factoryWindowResult = FACTORY_CONTINUE; g_factoryWindowResult == FACTORY_CONTINUE; sleepIdle()) {
		uint16 event;

		GUI_DrawCredits(g_playerHouseID, 0);

		GUI_FactoryWindow_UpdateSelection(false);

		event = GUI_Widget_HandleEvents(g_widgetInvoiceTail);

		if (event == 0x6E) GUI_Production_ResumeGame_Click(NULL);

		GUI_PaletteAnimate();
	}

	GUI_DrawCredits(g_playerHouseID, 1);

	GFX_Screen_SetActive(oldScreenID);

	GUI_FactoryWindow_B495_0F30();

	memcpy(g_palette1 + 255 * 3, backup, 3);

	GFX_SetPalette(g_palette1);

	/* Visible credits have to be reset, as it might not be the real value */
	g_playerCredits = 0xFFFF;

	return g_factoryWindowResult;
}

char *GUI_String_Get_ByIndex(int16 stringID)
{
	extern char g_savegameDesc[5][51];

	switch (stringID) {
		case -5: case -4: case -3: case -2: case -1: {
			char *s = g_savegameDesc[abs((int16)stringID + 1)];
			if (*s == '\0') return NULL;
			return s;
		}

		case -10:
			stringID = (g_gameConfig.music != 0) ? STR_ON : STR_OFF;
			break;

		case -11:
			stringID = (g_gameConfig.sounds != 0) ? STR_ON : STR_OFF;
			break;

		case -12: {
			static const uint16 gameSpeedStrings[] = {
				STR_SLOWEST,
				STR_SLOW,
				STR_NORMAL,
				STR_FAST,
				STR_FASTEST
			};

			stringID = gameSpeedStrings[g_gameConfig.gameSpeed];
		} break;

		case -13:
			stringID = (g_gameConfig.hints != 0) ? STR_ON : STR_OFF;
			break;

		case -14:
			stringID = (g_gameConfig.autoScroll != 0) ? STR_ON : STR_OFF;
			break;

		default: break;
	}

	return String_Get_ByIndex(stringID);
}

static void GUI_StrategicMap_AnimateArrows(void)
{
	if (s_arrowAnimationTimeout >= g_timerGUI) return;
	s_arrowAnimationTimeout = g_timerGUI + 7;

	s_arrowAnimationState = (s_arrowAnimationState + 1) % 4;

	memcpy(g_palette1 + 251 * 3, s_strategicMapArrowColors + s_arrowAnimationState * 3, 4 * 3);

	GFX_SetPalette(g_palette1);
}

static void GUI_StrategicMap_AnimateSelected(uint16 selected, StrategicMapData *data)
{
	char key[4];
	char buffer[81];
	int16 x;
	int16 y;
	uint8 *sprite;
	uint16 width;
	uint16 height;
	uint16 i;

	GUI_Palette_CreateRemap(g_playerHouseID);

	for (i = 0; i < 20; i++) {
		GUI_StrategicMap_AnimateArrows();

		if (data[i].index == 0 || data[i].index == selected) continue;

		GUI_Mouse_Hide_Safe();
		GFX_Screen_Copy2(i * 16, 0, data[i].offsetX, data[i].offsetY, 16, 16, SCREEN_1, SCREEN_0, false);
		GUI_Mouse_Show_Safe();
	}

	sprintf(key, "%d", selected);

	Ini_GetString("PIECES", key, NULL, buffer, sizeof(buffer) - 1, g_fileRegionINI);
	sscanf(buffer, "%hd,%hd", &x, &y);

	sprite = g_sprites[477 + selected];
	width  = Sprite_GetWidth(sprite);
	height = Sprite_GetHeight(sprite);

	x += 8;
	y += 24;

	GUI_Mouse_Hide_Safe();
	/* Sample the region sprite from SCREEN_1, not SCREEN_0: SCREEN_0's
	 * chunky buffer is deliberately left unmaintained by the TOS
	 * direct-to-planar bypass (see the "EXPERIMENT" comment in
	 * GFX_Screen_Copy()), so it holds stale/garbage data here. SCREEN_1
	 * still holds the exact chunky pixels GUI_StrategicMap_DrawRegion()
	 * drew at this same (x, y) position, unmodified since -- use the
	 * overlap-safe same-buffer copy since (x, y) can legitimately land
	 * close to the (16, 16) destination for regions near the top-left
	 * of the viewport. */
	GFX_Screen_CopyOverlap(x, y, 16, 16, width, height, SCREEN_1);
	GUI_Mouse_Show_Safe();

	GFX_Screen_Copy2(16, 16, 176, 16, width, height, SCREEN_1, SCREEN_1, false);

	GUI_DrawSprite(SCREEN_1, sprite, GUI_SPRITE_ID_UNKNOWN, GUI_SPRITE_COLOUR_EMBEDDED, 16, 16, 0, DRAWSPRITE_FLAG_REMAP, g_remap, 1);

	for (i = 0; i < 20; i++) {
		GUI_StrategicMap_AnimateArrows();

		if (data[i].index != selected) continue;

		GUI_DrawSprite(SCREEN_1, g_sprites[505 + data[i].arrow], 505 + data[i].arrow, GUI_SPRITE_COLOUR_EMBEDDED, data[i].offsetX + 16 - x, data[i].offsetY + 16 - y, 0, DRAWSPRITE_FLAG_REMAP, g_remap, 1);
	}

	for (i = 0; i < 4; i++) {
		GUI_Mouse_Hide_Safe();
		GFX_Screen_Copy2((i % 2 == 0) ? 16 : 176, 16, x, y, width, height, SCREEN_1, SCREEN_0, false);
		GUI_Mouse_Show_Safe();

		for (g_timerTimeout = 20; g_timerTimeout != 0; sleepIdle()) {
			GUI_StrategicMap_AnimateArrows();
		}
	}
}

/**
 * Return if a region has already been done.
 * @param region Region to obtain.
 * @return True if and only if the region has already been done.
 */
static bool GUI_StrategicMap_IsRegionDone(uint16 region)
{
	return (g_strategicRegionBits & (1 << region)) != 0;
}

/**
 * Set or reset if a region of the strategic map is already done.
 * @param region Region to change.
 * @param set Region must be set or reset.
 */
static void GUI_StrategicMap_SetRegionDone(uint16 region, bool set)
{
	if (set) {
		g_strategicRegionBits |= (1 << region);
	} else {
		g_strategicRegionBits &= ~(1 << region);
	}
}

static int16 GUI_StrategicMap_ClickedRegion(void)
{
	uint16 key;

	GUI_StrategicMap_AnimateArrows();

	if (Input_Keyboard_NextKey() == 0) return 0;

	key = Input_WaitForValidInput();
	if (key != 0xC6 && key != 0xC7) return 0;

	return g_fileRgnclkCPS[(g_mouseClickY - 24) * 304 + g_mouseClickX - 8];
}

static bool GUI_StrategicMap_FastForwardToggleWithESC(void)
{
	if (Input_Keyboard_NextKey() == 0) return s_strategicMapFastForward;

	if (Input_WaitForValidInput() != 0x1B) return s_strategicMapFastForward;

	s_strategicMapFastForward = !s_strategicMapFastForward;

	Input_History_Clear();

	return s_strategicMapFastForward;
}

static void GUI_StrategicMap_DrawText(const char *string)
{
	static uint32 l_timerNext = 0;
	Screen oldScreenID;
	uint16 y;

	oldScreenID = GFX_Screen_SetActive(SCREEN_1);

	/* Fill the message strip with the cached chrome parchment colour (see
	 * s_strategicMapTextBgColor): SCREEN_2, which originally held this
	 * colour after MAPMACH.CPS loaded, gets reused as a scratch heap by
	 * Sprites_CPS_LoadRegionClick() shortly after the first message is
	 * shown, so it can't be re-sampled here for later calls. The fill
	 * must cover rows 172-198 (not just the visible 172-185 message
	 * rows): the scroll-reveal loop below reads SCREEN_1 rows up to
	 * y+13, i.e. as far down as row 198 (when y=185), sliding that whole
	 * window up into SCREEN_0 -- the "stash" rows beyond 185 need the
	 * matching background colour too, or the reveal animation slides in
	 * over stale/black leftovers instead of a gold background. */
	GUI_DrawFilledRectangle(64, 172, 255, 198, s_strategicMapTextBgColor);

	GUI_DrawText_Wrapper(string, 64, 175, 12, 0, 0x12);

	while (g_timerGUI + 90 < l_timerNext) sleepIdle();

	for (y = 185; y > 172; y--) {
		GUI_Screen_Copy(8, y, 8, 165, 24, 14, SCREEN_1, SCREEN_0);

		for (g_timerTimeout = 3; g_timerTimeout != 0; sleepIdle()) {
			if (GUI_StrategicMap_FastForwardToggleWithESC()) break;
		}
	}

	l_timerNext = g_timerGUI + 90;

	GFX_Screen_SetActive(oldScreenID);
}

static uint16 GUI_StrategicMap_ScenarioSelection(uint16 campaignID)
{
	uint16 count;
	char key[6];
	bool loop;
	bool hasRegions = false;
	char category[16];
	StrategicMapData data[20];
	uint16 scenarioID;
	uint16 region;
	uint16 i;

	GUI_Palette_CreateRemap(g_playerHouseID);

	snprintf(category, sizeof(category), "GROUP%hu", campaignID);

	memset(data, 0, 20 * sizeof(StrategicMapData));

	for (i = 0; i < 20; i++) {
		char buffer[81];

		sprintf(key, "REG%hu", (uint16)(i + 1));

		if (Ini_GetString(category, key, NULL, buffer, sizeof(buffer) - 1, g_fileRegionINI) == NULL) break;

		sscanf(buffer, "%hd,%hd,%hd,%hd", &data[i].index, &data[i].arrow, &data[i].offsetX, &data[i].offsetY);

		if (!GUI_StrategicMap_IsRegionDone(data[i].index)) hasRegions = true;

		GFX_Screen_Copy2(data[i].offsetX, data[i].offsetY, i * 16, 152, 16, 16, SCREEN_1, SCREEN_1, false);
		GFX_Screen_Copy2(data[i].offsetX, data[i].offsetY, i * 16, 0, 16, 16, SCREEN_1, SCREEN_1, false);
		GUI_DrawSprite(SCREEN_1, g_sprites[505 + data[i].arrow], 505 + data[i].arrow, GUI_SPRITE_COLOUR_EMBEDDED, i * 16, 152, 0, DRAWSPRITE_FLAG_REMAP, g_remap, 1);
	}

	count = i;

	if (!hasRegions) {
		/* This campaign has no available regions left; reset all regions for this campaign */
		for (i = 0; i < count; i++) {
			GUI_StrategicMap_SetRegionDone(data[i].index, false);
		}
	} else {
		/* Mark all regions that are already done as not-selectable */
		for (i = 0; i < count; i++) {
			if (GUI_StrategicMap_IsRegionDone(data[i].index)) data[i].index = 0;
		}
	}

	GUI_Mouse_Hide_Safe();

	for (i = 0; i < count; i++) {
		if (data[i].index == 0) continue;

		GFX_Screen_Copy2(i * 16, 152, data[i].offsetX, data[i].offsetY, 16, 16, SCREEN_1, SCREEN_0, false);
	}

	GUI_Mouse_Show_Safe();
	Input_History_Clear();

	for (loop = true; loop; sleepIdle()) {
		region = GUI_StrategicMap_ClickedRegion();

		if (region == 0) continue;

		for (i = 0; i < count; i++) {
			GUI_StrategicMap_AnimateArrows();

			if (data[i].index == region) {
				loop = false;
				scenarioID = i;
				break;
			}
		}
	}

	GUI_StrategicMap_SetRegionDone(region, true);

	GUI_StrategicMap_DrawText("");

	GUI_StrategicMap_AnimateSelected(region, data);

	scenarioID += (campaignID - 1) * 3 + 2;

	if (campaignID > 7) scenarioID--;
	if (campaignID > 8) scenarioID--;

	return scenarioID;
}

static void GUI_StrategicMap_ReadHouseRegions(uint8 houseID, uint16 campaignID)
{
	char key[4];
	char buffer[100];
	char groupText[16];
	char *s = buffer;

	strncpy(key, g_table_houseInfo[houseID].name, 3);
	key[3] = '\0';

	snprintf(groupText, sizeof(groupText), "GROUP%d", campaignID);

	if (Ini_GetString(groupText, key, NULL, buffer, sizeof(buffer) - 1, g_fileRegionINI) == NULL) return;

	while (*s != '\0') {
		uint16 region = atoi(s);

		if (region != 0) g_regions[region] = houseID;

		while (*s != '\0') {
			if (*s++ == ',') break;
		}
	}
}

static void GUI_StrategicMap_DrawRegion(uint8 houseId, uint16 region, bool progressive)
{
	char key[4];
	char buffer[81];
	int16 x;
	int16 y;
	uint8 *sprite;

	GUI_Palette_CreateRemap(houseId);

	sprintf(key, "%hu", region);

	Ini_GetString("PIECES", key, NULL, buffer, sizeof(buffer), g_fileRegionINI);
	sscanf(buffer, "%hd,%hd", &x, &y);

	sprite = g_sprites[477 + region];

	GUI_DrawSprite(SCREEN_1, sprite, GUI_SPRITE_ID_UNKNOWN, GUI_SPRITE_COLOUR_EMBEDDED, x + 8, y + 24, 0, DRAWSPRITE_FLAG_REMAP, g_remap, 1);

	if (!progressive) return;

	GUI_Screen_FadeIn2(x + 8, y + 24, Sprite_GetWidth(sprite), Sprite_GetHeight(sprite), SCREEN_1, SCREEN_0, GUI_StrategicMap_FastForwardToggleWithESC() ? 0 : 1, false);
}

static void GUI_StrategicMap_PrepareRegions(uint16 campaignID)
{
	uint16 i;

	for (i = 0; i < campaignID; i++) {
		GUI_StrategicMap_ReadHouseRegions(HOUSE_HARKONNEN, i + 1);
		GUI_StrategicMap_ReadHouseRegions(HOUSE_ATREIDES, i + 1);
		GUI_StrategicMap_ReadHouseRegions(HOUSE_ORDOS, i + 1);
		GUI_StrategicMap_ReadHouseRegions(HOUSE_SARDAUKAR, i + 1);
	}

	for (i = 0; i < g_regions[0]; i++) {
		if (g_regions[i + 1] == 0xFFFF) continue;

		GUI_StrategicMap_DrawRegion((uint8)g_regions[i + 1], i + 1, false);
	}
}

static void GUI_StrategicMap_ShowProgression(uint16 campaignID)
{
	char key[10];
	char category[10];
	char buf[100];
	uint16 i;

	snprintf(category, sizeof(category), "GROUP%hu", campaignID);

	for (i = 0; i < 6; i++) {
		uint8 houseID = (g_playerHouseID + i) % 6;
		const char *s = buf;

		strncpy(key, g_table_houseInfo[houseID].name, 3);
		key[3] = '\0';

		if (Ini_GetString(category, key, NULL, buf, 99, g_fileRegionINI) == NULL) continue;

		while (*s != '\0') {
			uint16 region = atoi(s);

			if (region != 0) {
				char buffer[81];

				sprintf(key, "%sTXT%d", g_languageSuffixes[g_config.language], region);

				if (Ini_GetString(category, key, NULL, buffer, sizeof(buffer), g_fileRegionINI) != NULL) {
					GUI_StrategicMap_DrawText(buffer);
				}

				GUI_StrategicMap_DrawRegion(houseID, region, true);
			}

			while (*s != '\0') {
				if (*s++ == ',') break;
			}
		}
	}

	GUI_StrategicMap_DrawText("");
}

uint16 GUI_StrategicMap_Show(uint16 campaignID, bool win)
{
	uint16 scenarioID;
	uint16 previousCampaignID;
	uint16 x;
	uint16 y;
	Screen oldScreenID;
	uint8 palette[3 * 256];
	uint8 loc316[12];

	if (campaignID == 0) return 1;

	Timer_Sleep(10);
	Music_Play(0x1D);

	memset(palette, 0, 256 * 3);

	previousCampaignID = campaignID - (win ? 1 : 0);
	oldScreenID = GFX_Screen_SetActive(SCREEN_2);

	GUI_SetPaletteAnimated(palette, 15);

	Mouse_SetRegion(8, 24, 311, 143);

	GUI_Mouse_SetPosition(160, 84);

	Sprites_LoadImage("MAPMACH.CPS", SCREEN_2, g_palette_998A);

	GUI_Palette_RemapScreen(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_2, g_remap);

	/* Cache the message-strip parchment colour now, while SCREEN_2 still
	 * holds the just-loaded/remapped MAPMACH.CPS chrome: SCREEN_2 gets
	 * reused as a scratch heap by Sprites_CPS_LoadRegionClick() (called
	 * below), so this is the last point at which sampling it directly is
	 * safe. GUI_StrategicMap_DrawText() reads this cached value instead. */
	s_strategicMapTextBgColor = GFX_GetPixel(64, 165);

	x = 0;
	y = 0;

	switch (g_playerHouseID) {
		case HOUSE_HARKONNEN:
			x = 0;
			y = 152;
			break;

		default:
			x = 33;
			y = 152;
			break;

		case HOUSE_ORDOS:
			x = 1;
			y = 24;
			break;
	}

	memcpy(loc316, g_palette1 + 251 * 3, 12);
	memcpy(s_strategicMapArrowColors, g_palette1 + (144 + (g_playerHouseID * 16)) * 3, 4 * 3);
	memcpy(s_strategicMapArrowColors + 4 * 3, s_strategicMapArrowColors, 4 * 3);

	GUI_Screen_Copy(x, y, 0, 152, 7, 40, SCREEN_2, SCREEN_2);
	GUI_Screen_Copy(x, y, 33, 152, 7, 40, SCREEN_2, SCREEN_2);

	switch (g_config.language) {
		case LANGUAGE_GERMAN:
			GUI_Screen_Copy(1, 120, 1, 0, 38, 24, SCREEN_2, SCREEN_2);
			break;

		case LANGUAGE_FRENCH:
			GUI_Screen_Copy(1, 96, 1, 0, 38, 24, SCREEN_2, SCREEN_2);
			break;

		default: break;
	}

	GUI_DrawFilledRectangle(8, 24, 311, 143, 12);

	GUI_Mouse_Hide_Safe();
	GUI_SetPaletteAnimated(g_palette1, 15);
	GUI_Screen_Copy(0, 0, 0, 0, SCREEN_WIDTH / 8, SCREEN_HEIGHT, SCREEN_2, SCREEN_0);
	GUI_Mouse_Show_Safe();

	s_strategicMapFastForward = false;

	if (win && campaignID == 1) {
		Sprites_LoadImage("PLANET.CPS", SCREEN_1, g_palette_998A);

		GUI_StrategicMap_DrawText(String_Get_ByIndex(STR_THREE_HOUSES_HAVE_COME_TO_DUNE));

		GUI_Screen_FadeIn2(8, 24, 304, 120, SCREEN_1, SCREEN_0, 0, false);

		Input_History_Clear();

		Sprites_CPS_LoadRegionClick();

		for (g_timerTimeout = 120; g_timerTimeout != 0; sleepIdle()) {
			if (GUI_StrategicMap_FastForwardToggleWithESC()) break;
		}

		Sprites_LoadImage("DUNEMAP.CPS", SCREEN_1 , g_palette_998A);

		GUI_StrategicMap_DrawText(String_Get_ByIndex(STR_TO_TAKE_CONTROL_OF_THE_LAND));

		GUI_Screen_FadeIn2(8, 24, 304, 120, SCREEN_1, SCREEN_0, GUI_StrategicMap_FastForwardToggleWithESC() ? 0 : 1, false);

		for (g_timerTimeout = 60; g_timerTimeout != 0; sleepIdle()) {
			if (GUI_StrategicMap_FastForwardToggleWithESC()) break;
		}

		GUI_StrategicMap_DrawText(String_Get_ByIndex(STR_THAT_HAS_BECOME_DIVIDED));
	} else {
		Sprites_CPS_LoadRegionClick();
	}

	Sprites_LoadImage("DUNERGN.CPS", SCREEN_1, g_palette_998A);

	GFX_Screen_SetActive(SCREEN_1);

	GUI_StrategicMap_PrepareRegions(previousCampaignID);

	if (GUI_StrategicMap_FastForwardToggleWithESC()) {
		GUI_Screen_Copy(1, 24, 1, 24, 38, 120, SCREEN_1, SCREEN_0);
	} else {
		GUI_Screen_FadeIn2(8, 24, 304, 120, SCREEN_1, SCREEN_0, 0, false);
	}

#ifndef TOS
	/* On non-TOS backends SCREEN_0 is the real composited/displayed buffer,
	 * so the preceding GUI_Screen_Copy()/GUI_Screen_FadeIn2() calls (which
	 * only ever write INTO SCREEN_0) need to be mirrored back into SCREEN_1
	 * before further SCREEN_1-based drawing continues. On TOS, SCREEN_0 is
	 * deliberately left unmaintained (direct-to-planar bypass) -- SCREEN_1
	 * was never touched by the calls above and remains the authoritative,
	 * up-to-date map image, so pulling stale/garbage SCREEN_0 data back
	 * into it would corrupt it instead. */
	GUI_Screen_Copy(0, 0, 0, 0, SCREEN_WIDTH / 8, SCREEN_HEIGHT, SCREEN_0, SCREEN_1);
#endif /* TOS */

	if (campaignID != previousCampaignID) GUI_StrategicMap_ShowProgression(campaignID);

	GUI_Mouse_Show_Safe();

	if (*g_regions >= campaignID) {
		GUI_StrategicMap_DrawText(String_Get_ByIndex(STR_SELECT_YOUR_NEXT_REGION));

		scenarioID = GUI_StrategicMap_ScenarioSelection(campaignID);
	} else {
		scenarioID = 0;
	}

	Driver_Music_FadeOut();

	GFX_Screen_SetActive(oldScreenID);

	Mouse_SetRegion(0, 0, SCREEN_WIDTH - 1, SCREEN_HEIGHT - 1);

	Input_History_Clear();

	memcpy(g_palette1 + 251 * 3, loc316, 12);

	GUI_SetPaletteAnimated(palette, 15);

	GUI_Mouse_Hide_Safe();
	GUI_ClearScreen(SCREEN_0);
	GUI_Mouse_Show_Safe();

	GFX_SetPalette(g_palette1);

	return scenarioID;
}

/**
 * Draw a string to the screen using a fixed width for each char.
 *
 * @param string The string to draw.
 * @param left The most left position where to draw the string.
 * @param top The most top position where to draw the string.
 * @param fgColour The foreground colour of the text.
 * @param bgColour The background colour of the text.
 * @param charWidth The width of a char.
 */
void GUI_DrawText_Monospace(char *string, uint16 left, uint16 top, uint8 fgColour, uint8 bgColour, uint16 charWidth)
{
	char s[2] = " ";

	while (*string != '\0') {
		*s = *string++;
		GUI_DrawText(s, left, top, fgColour, bgColour);
		left += charWidth;
	}
}

void GUI_FactoryWindow_B495_0F30(void)
{
	GUI_Mouse_Hide_Safe();
	uint16 y = g_factoryWindowSelected * 32 + 24;
	GUI_DrawWiredRectangle(71, y - 1, 104, y + 24,  GFX_GetPixel(72, 23));
/* this was factory item sprite restored without selection rectangle;
 * pulled from private buffer in screen_1; maybe it should be private scratch buffer,
 * beacuse hiding stuff in screen_1 ends badly (see credits scroll rendering buffer,
 * which I was tracking for better part of the day
 *
	GFX_Screen_Copy2(69, ((g_factoryWindowSelected + 1) * 32) + 5, 69, (g_factoryWindowSelected * 32) + 21, 38, 30, SCREEN_1, SCREEN_0, false);
*/
	GUI_Mouse_Show_Safe();
}

FactoryWindowItem *GUI_FactoryWindow_GetItem(int16 offset)
{
	offset += g_factoryWindowBase;

	if (offset < 0 || offset >= g_factoryWindowTotal) return NULL;

	return &g_factoryWindowItems[offset];
}

void GUI_FactoryWindow_DrawDetails(void)
{
	Screen oldScreenID;
	FactoryWindowItem *item = GUI_FactoryWindow_GetItem(g_factoryWindowSelected);
	ObjectInfo *oi = item->objectInfo;
	void *wsa;

	oldScreenID = GFX_Screen_SetActive(SCREEN_1);

	wsa = WSA_LoadFile(oi->wsa, s_factoryWindowWsaBuffer, sizeof(s_factoryWindowWsaBuffer), false);
	WSA_DisplayFrame(wsa, 0, 128, 48, SCREEN_1);
	WSA_Unload(wsa);

	if (g_factoryWindowConstructionYard) {
		const StructureInfo *si;
		int16 x = 288;
		int16 y = 136;
		uint8 *sprite;
		uint16 width;
		uint16 i;
		uint16 j;

		GUI_DrawSprite(SCREEN_1, g_sprites[64], 64, GUI_SPRITE_COLOUR_EMBEDDED, x, y, 0, 0);
		x++;
		y++;

		sprite = g_sprites[24];
		width = Sprite_GetWidth(sprite) + 1;
		si = &g_table_structureInfo[item->objectType];

		for (j = 0; j < g_table_structure_layoutSize[si->layout].height; j++) {
			for (i = 0; i < g_table_structure_layoutSize[si->layout].width; i++) {
				GUI_DrawSprite(SCREEN_1, sprite, GUI_SPRITE_ID_UNKNOWN, GUI_SPRITE_COLOUR_EMBEDDED, x + i * width, y + j * width, 0, 0);
			}
		}
	}

	if (oi->available == -1) {
		GUI_Palette_RemapScreen(128, 48, 184, 112, SCREEN_1, s_factoryWindowGraymapTbl);

		if (g_factoryWindowStarport) {
			GUI_DrawText_Wrapper(String_Get_ByIndex(STR_OUT_OF_STOCK), 220, 99, 6, 0, 0x132);
		} else {
			GUI_DrawText_Wrapper(String_Get_ByIndex(STR_NEED_STRUCTURE_UPGRADE), 220, 94, 6, 0, 0x132);

			if (g_factoryWindowUpgradeCost != 0) {
				GUI_DrawText_Wrapper(String_Get_ByIndex(STR_UPGRADE_COST_D), 220, 104, 6, 0, 0x132, g_factoryWindowUpgradeCost);
			} else {
				GUI_DrawText_Wrapper(String_Get_ByIndex(STR_REPAIR_STRUCTURE_FIRST), 220, 104, 6, 0, 0x132);
			}
		}
	} else {
		if (g_factoryWindowStarport) {
			GUI_Screen_Copy(16, 99, 16, 160, 23, 9, SCREEN_1, SCREEN_1);
			GUI_Screen_Copy(16, 99, 16, 169, 23, 9, SCREEN_1, SCREEN_1);
			GUI_DrawText_Wrapper(String_Get_ByIndex(STR_OUT_OF_STOCK), 220, 169, 6, 0, 0x132);
			GUI_Screen_Copy(16, 99, 16, 178, 23, 9, SCREEN_1, SCREEN_1);
			GUI_DrawText_Wrapper(String_Get_ByIndex(STR_UNABLE_TO_CREATE_MORE), 220, 178, 6, 0, 0x132);

			GUI_FactoryWindow_UpdateDetails(item);
		}
	}

	GUI_Mouse_Hide_Safe();
	GUI_Screen_Copy(16, 48, 16, 48, 23, 112, SCREEN_1, oldScreenID);
	GUI_Mouse_Show_Safe();

	GFX_Screen_SetActive(oldScreenID);

	GUI_FactoryWindow_DrawCaption(NULL);
}

void GUI_FactoryWindow_DrawCaption(const char *caption)
{
	Screen oldScreenID;

	oldScreenID = GFX_Screen_SetActive(SCREEN_1);

	GUI_DrawFilledRectangle(128, 21, 310, 35, 116);

	if (caption != NULL && *caption != '\0') {
		GUI_DrawText_Wrapper(caption, 128, 23, 12, 0, 0x12);
	} else {
		FactoryWindowItem *item = GUI_FactoryWindow_GetItem(g_factoryWindowSelected);
		ObjectInfo *oi = item->objectInfo;
		uint16 width;

		GUI_DrawText_Wrapper(String_Get_ByIndex(oi->stringID_full), 128, 23, 12, 0, 0x12);

		width = Font_GetStringWidth(String_Get_ByIndex(STR_COST_999));
		GUI_DrawText_Wrapper(String_Get_ByIndex(STR_COST_3D), 310 - width, 23, 12, 0, 0x12, item->credits);

		if (g_factoryWindowStarport) {
			width += Font_GetStringWidth(String_Get_ByIndex(STR_QTY_99)) + 2;
			GUI_DrawText_Wrapper(String_Get_ByIndex(STR_QTY_2D), 310 - width, 23, 12, 0, 0x12, item->amount);
		}
	}

	GUI_Mouse_Hide_Safe();
	if (oldScreenID == SCREEN_0) GFX_Screen_Copy2(128, 21, 128, 21, 182, 14, SCREEN_1, oldScreenID, false);
	GUI_Mouse_Show_Safe();

	GFX_Screen_SetActive(oldScreenID);
}

void GUI_FactoryWindow_UpdateDetails(const FactoryWindowItem *item)
{
	int16 y;
	const ObjectInfo *oi = item->objectInfo;
	uint16 type = item->objectType;

	/* check the available units and unit count limit */
	if (oi->available == -1) return;

	y = 160;
	if (oi->available <= item->amount) y = 169;
	else if (g_starPortEnforceUnitLimit && g_table_unitInfo[type].movementType != MOVEMENT_WINGER && g_table_unitInfo[type].movementType != MOVEMENT_SLITHER) {
		House *h = g_playerHouse;
		if (h->unitCount >= h->unitCountMax) y = 178;
	}
	GUI_Mouse_Hide_Safe();
	GUI_Screen_Copy(16, y, 16, 99, 23, 9, SCREEN_1, SCREEN_ACTIVE);
	GUI_Mouse_Show_Safe();
}

/**
 * Update the selection in the factory window.
 * If \a selectionChanged, it draws the rectangle around the new entry.
 * In addition, the palette colour of the rectangle is slowly changed back and
 * forth between white and the house colour by palette changes, thus giving it
 * the appearance of glowing. On TOS the outline stays white to avoid
 * recurring palette remapping and planar cursor-cache rebuilds.
 * @param selectionChanged User has selected a new thing to build.
 */
void GUI_FactoryWindow_UpdateSelection(bool selectionChanged)
{
#ifndef TOS
	static uint32 paletteChangeTimer;
	static int8 paletteColour;
	static int8 paletteChange;
#else
	if (!selectionChanged) return;
#endif

	if (selectionChanged) {
		uint16 y;

		memset(g_palette1 + 255 * 3, 0x3F, 3);

#ifndef TOS
		paletteChangeTimer = 0;
		paletteColour = 0;
		paletteChange = 8;
#endif

		y = g_factoryWindowSelected * 32 + 24;

		GUI_Mouse_Hide_Safe();
		GUI_DrawWiredRectangle(71, y - 1, 104, y + 24, 255);
//		GUI_DrawWiredRectangle(72, y, 103, y + 23, 255);
		GUI_Mouse_Show_Safe();
	}
#ifndef TOS
	else {
		if (paletteChangeTimer > g_timerGUI) return;
	}

	paletteChangeTimer = g_timerGUI + 3;
	paletteColour += paletteChange;

	if (paletteColour < 0 || paletteColour > 63) {
		paletteChange = -paletteChange;
		paletteColour += paletteChange;
		return;
	}

	switch (g_playerHouseID) {
		case HOUSE_HARKONNEN:
			*(g_palette1 + 255 * 3 + 1) = paletteColour;
			*(g_palette1 + 255 * 3 + 2) = paletteColour;
			break;

		case HOUSE_ATREIDES:
			*(g_palette1 + 255 * 3 + 0) = paletteColour;
			*(g_palette1 + 255 * 3 + 1) = paletteColour;
			break;

		case HOUSE_ORDOS:
			*(g_palette1 + 255 * 3 + 0) = paletteColour;
			*(g_palette1 + 255 * 3 + 2) = paletteColour;
			break;

		default: break;
	}
#endif

	GFX_SetPalette(g_palette1);
}

/**
 * Fade in parts of the screen from one screenbuffer to the other screenbuffer.
 * @param xSrc The X-position to start in the source screenbuffer divided by 8.
 * @param ySrc The Y-position to start in the source screenbuffer.
 * @param xDst The X-position to start in the destination screenbuffer divided by 8.
 * @param yDst The Y-position to start in the destination screenbuffer.
 * @param width The width of the screen to copy divided by 8.
 * @param height The height of the screen to copy.
 * @param screenSrc The ID of the source screen.
 * @param screenDst The ID of the destination screen.
 */
void GUI_Screen_FadeIn(uint16 xSrc, uint16 ySrc, uint16 xDst, uint16 yDst, uint16 width, uint16 height, Screen screenSrc, Screen screenDst)
{
	uint16 offsetsY[100];
	uint16 offsetsX[40];
	int x, y;

	if (screenDst == SCREEN_0) {
		GUI_Mouse_Hide_InRegion(xDst << 3, yDst, (xDst + width) << 3, yDst + height);
	}

	height /= 2;

	for (x = 0; x < width;  x++) offsetsX[x] = x;
	for (y = 0; y < height; y++) offsetsY[y] = y;

	for (x = 0; x < width; x++) {
		uint16 index;
		uint16 temp;

		index = Tools_RandomLCG_Range(0, width - 1);

		temp = offsetsX[index];
		offsetsX[index] = offsetsX[x];
		offsetsX[x] = temp;
	}

	for (y = 0; y < height; y++) {
		uint16 index;
		uint16 temp;

		index = Tools_RandomLCG_Range(0, height - 1);

		temp = offsetsY[index];
		offsetsY[index] = offsetsY[y];
		offsetsY[y] = temp;
	}

	for (y = 0; y < height; y++) {
		uint16 y2 = y;
		for (x = 0; x < width; x++) {
			uint16 offsetX, offsetY;

			offsetX = offsetsX[x];
			offsetY = offsetsY[y2];

			GUI_Screen_Copy(xSrc + offsetX, ySrc + offsetY * 2, xDst + offsetX, yDst + offsetY * 2, 1, 2, screenSrc, screenDst);

			y2++;
			if (y2 == height) y2 = 0;
		}

		/* XXX -- This delays the system so you can in fact see the animation */
		if ((y % 2) == 0) Timer_Sleep(1);
	}

	if (screenDst == SCREEN_0) {
		GUI_Mouse_Show_InRegion();
	}
}

void GUI_FactoryWindow_PrepareScrollList(void)
{
	FactoryWindowItem *item;

/*
 * this is the screen_1 buffer which stores drawed sprites;
 * for now I see that it is mainly used to remove
 * selection rectangle after switching to other
 * factory item; later it will probably be used also
 * for scroling...
 * For now I am removing it because it breaks screen_1
 * authoritativeness -- maybe it should be explitic
 * scratch buffer for loaded factory item sprites
 *
	GUI_Mouse_Hide_Safe();
	GUI_Screen_Copy(9, 24, 9, 40, 4, 128, SCREEN_0, SCREEN_1);
	GUI_Mouse_Show_Safe();
*/
	item = GUI_FactoryWindow_GetItem(-1);

	if (item != NULL) {
		ObjectInfo *oi = item->objectInfo;

		if (oi->available == -1) {
			GUI_DrawSprite(SCREEN_1, g_sprites[oi->spriteID], oi->spriteID, GUI_SPRITE_COLOUR_EMBEDDED, 72, 8, 0, DRAWSPRITE_FLAG_REMAP, s_factoryWindowGraymapTbl, 1);
		} else {
			GUI_DrawSprite(SCREEN_1, g_sprites[oi->spriteID], oi->spriteID, GUI_SPRITE_COLOUR_EMBEDDED, 72, 8, 0, 0);
		}
	} else {
		GUI_Screen_Copy(9, 32, 9, 24, 4, 8, SCREEN_1, SCREEN_1);
	}

	item = GUI_FactoryWindow_GetItem(4);

	if (item != NULL) {
		ObjectInfo *oi = item->objectInfo;

		if (oi->available == -1) {
			GUI_DrawSprite(SCREEN_1, g_sprites[oi->spriteID], oi->spriteID, GUI_SPRITE_COLOUR_EMBEDDED, 72, 168, 0, DRAWSPRITE_FLAG_REMAP, s_factoryWindowGraymapTbl, 1);
		} else {
			GUI_DrawSprite(SCREEN_1, g_sprites[oi->spriteID], oi->spriteID, GUI_SPRITE_COLOUR_EMBEDDED, 72, 168, 0, 0);
		}
	} else {
		GUI_Screen_Copy(9, 0, 9, 168, 4, 8, SCREEN_1, SCREEN_1);
	}
}

/**
 * Fade in parts of the screen from one screenbuffer to the other screenbuffer.
 * @param x The X-position in the source and destination screenbuffers.
 * @param y The Y-position in the source and destination screenbuffers.
 * @param width The width of the screen to copy.
 * @param height The height of the screen to copy.
 * @param screenSrc The ID of the source screen.
 * @param screenDst The ID of the destination screen.
 * @param delay The delay.
 * @param skipNull Wether to copy pixels with colour 0.
 */
void GUI_Screen_FadeIn2(int16 x, int16 y, int16 width, int16 height, Screen screenSrc, Screen screenDst, uint16 delay, bool skipNull)
{
#ifdef TOS
	GUI_Screen_FadeIn(x>>3, y, x>>3, y, width>>3, height, screenSrc, screenDst);
	return;
#endif
	Screen oldScreenID;
	uint16 i;
	uint16 j;

	uint16 columns[SCREEN_WIDTH];
	uint16 rows[SCREEN_HEIGHT];

	assert(width <= SCREEN_WIDTH);
	assert(height <= SCREEN_HEIGHT);

	if (screenDst == 0) {
		GUI_Mouse_Hide_InRegion(x, y, x + width, y + height);
	}

	for (i = 0; i < width; i++)  columns[i] = i;
	for (i = 0; i < height; i++) rows[i] = i;

	for (i = 0; i < width; i++) {
		uint16 tmp;

		j = Tools_RandomLCG_Range(0, width - 1);

		tmp = columns[j];
		columns[j] = columns[i];
		columns[i] = tmp;
	}

	for (i = 0; i < height; i++) {
		uint16 tmp;

		j = Tools_RandomLCG_Range(0, height - 1);

		tmp = rows[j];
		rows[j] = rows[i];
		rows[i] = tmp;
	}

	oldScreenID = GFX_Screen_SetActive(screenDst);

	for (j = 0; j < height; j++) {
		uint16 j2 = j;

		for (i = 0; i < width; i++) {
			uint8 colour;
			uint16 curX = x + columns[i];
			uint16 curY = y + rows[j2];

			if (++j2 >= height) j2 = 0;

			GFX_Screen_SetActive(screenSrc);

			colour = GFX_GetPixel(curX, curY);

			GFX_Screen_SetActive(screenDst);

			if (skipNull && colour == 0) continue;

			GFX_PutPixel(curX, curY, colour);
		}
		GFX_Screen_SetDirtySource(DIRTY_SRC_SPRITE);
		GFX_Screen_SetDirty(screenDst, x, y, x + width, y + height);

		Timer_Sleep(delay);
	}

	if (screenDst == 0) {
		GUI_Mouse_Show_InRegion();
	}

	GFX_Screen_SetActive(oldScreenID);
}

/**
 * Show the mouse on the screen. Copy the screen behind the mouse in a safe
 *  buffer.
 */
void GUI_Mouse_Show(void)
{
	int left, top;

	if (g_mouseDisabled == 1) return;
	if (g_mouseHiddenDepth == 0 || --g_mouseHiddenDepth != 0) return;

	left = g_mouseX - g_mouseSpriteHotspotX;
	top  = g_mouseY - g_mouseSpriteHotspotY;

	s_mouseSpriteLeft = (left < 0) ? 0 : (left >> 3);
	s_mouseSpriteTop = (top < 0) ? 0 : top;

	s_mouseSpriteWidth = g_mouseWidth;
	if ((left >> 3) + g_mouseWidth >= SCREEN_WIDTH / 8) s_mouseSpriteWidth -= (left >> 3) + g_mouseWidth - SCREEN_WIDTH / 8;

	s_mouseSpriteHeight = g_mouseHeight;
	if (top + g_mouseHeight >= SCREEN_HEIGHT) s_mouseSpriteHeight -= top + g_mouseHeight - SCREEN_HEIGHT;

#ifdef TOS
	/* Cached planar cursors save/restore their background in the video
	 * driver. Try them before making a chunky backup for the fallback.
	 * CursorUseIcon handles edge clipping using the raw hotspot position. */
	if (Video_Atari_CursorDirect() && g_mouseSpriteIconIndex != 0xffff) {
		if (Video_Atari_CursorUseIcon(g_mouseSpriteIconIndex, (int16)left, (int16)top)) return;
	}
#endif

#ifdef TOS
	if (g_mouseSpriteBuffer != NULL && Video_Atari_CursorDirect()
	 && s_mouseSpriteWidth != 0 && s_mouseSpriteHeight != 0
	 && s_mouseSpriteWidth * 8 <= SCREEN_WIDTH && s_mouseSpriteHeight <= SCREEN_HEIGHT) {
		uint16 boxLeft = s_mouseSpriteLeft * 8;
		uint16 boxWidth = s_mouseSpriteWidth * 8;
		uint16 boxHeight = s_mouseSpriteHeight;
		uint8 *box;

		if (boxWidth > VIDEO_ATARI_CURSOR_MAX_WIDTH) boxWidth = VIDEO_ATARI_CURSOR_MAX_WIDTH;
		if (boxHeight > VIDEO_ATARI_CURSOR_MAX_HEIGHT) boxHeight = VIDEO_ATARI_CURSOR_MAX_HEIGHT;

		/* Allocate before Prepare updates its cache key, so allocation
		 * failure cannot leave an unbuilt cursor marked as cached. */
		box = (uint8 *)calloc((size_t)boxWidth, boxHeight);
		if (box == NULL) {
			Warning("Unable to allocate cursor scratch buffer\n");
			Video_Atari_CursorHide();
			return;
		}
		if (Video_Atari_CursorPrepare(g_mouseSprite, boxLeft, s_mouseSpriteTop,
		                              boxWidth, boxHeight,
		                              (int16)(left - boxLeft),
		                              (int16)(top - s_mouseSpriteTop))) {
			GUI_DrawSpriteToBuffer(box, boxWidth, boxHeight, g_mouseSprite,
			                       (int16)(left - boxLeft), (int16)(top - s_mouseSpriteTop));
			Video_Atari_CursorBuild(box, boxWidth);
		}
		free(box);
		return;
	}
#endif /* TOS */

	if (g_mouseSpriteBuffer != NULL) {
		GFX_CopyToBuffer(s_mouseSpriteLeft * 8, s_mouseSpriteTop, s_mouseSpriteWidth * 8, s_mouseSpriteHeight, g_mouseSpriteBuffer);
	}

	GUI_DrawSprite(SCREEN_0, g_mouseSprite, GUI_SPRITE_ID_UNKNOWN, GUI_SPRITE_COLOUR_EMBEDDED, left, top, 0,
#ifdef TOS
	               DRAWSPRITE_FLAG_NO_PLANAR_DIRECT
#else
	               0
#endif
	              );
}

/**
 * Hide the mouse from the screen. Do this by copying the mouse buffer back to
 *  the screen.
 */
void GUI_Mouse_Hide(void)
{
	if (g_mouseDisabled == 1) return;

	if (g_mouseHiddenDepth == 0 && s_mouseSpriteWidth != 0) {
#ifdef TOS
		/* the cursor never made it into SCREEN_0, see GUI_Mouse_Show() */
		if (g_mouseSpriteBuffer != NULL && Video_Atari_CursorDirect()) {
			Video_Atari_CursorHide();
			s_mouseSpriteWidth = 0;
			g_mouseHiddenDepth++;
			return;
		}
#endif /* TOS */
		if (g_mouseSpriteBuffer != NULL) {
			GFX_CopyFromBuffer(s_mouseSpriteLeft * 8, s_mouseSpriteTop, s_mouseSpriteWidth * 8, s_mouseSpriteHeight, g_mouseSpriteBuffer);
		}

		s_mouseSpriteWidth = 0;
	}

	g_mouseHiddenDepth++;
}

/**
 * The safe version of GUI_Mouse_Hide(). It waits for a mouselock before doing
 *  anything.
 */
void GUI_Mouse_Hide_Safe(void)
{
	while (g_mouseLock != 0) sleepIdle();
	if (g_mouseDisabled == 1) return;
	g_mouseLock++;

	GUI_Mouse_Hide();

	g_mouseLock--;
}

/**
 * The safe version of GUI_Mouse_Show(). It waits for a mouselock before doing
 *  anything.
 */
void GUI_Mouse_Show_Safe(void)
{
	while (g_mouseLock != 0) sleepIdle();
	if (g_mouseDisabled == 1) return;
	g_mouseLock++;

	GUI_Mouse_Show();

	g_mouseLock--;
}

/**
 * Show the mouse if needed. Should be used in combination with
 *  #GUI_Mouse_Hide_InRegion().
 */
void GUI_Mouse_Show_InRegion(void)
{
	uint8 counter;

	while (g_mouseLock != 0) sleepIdle();
	g_mouseLock++;

	counter = g_regionFlags & 0xFF;
	if (counter == 0 || --counter != 0) {
		g_regionFlags = (g_regionFlags & 0xFF00) | (counter & 0xFF);
		g_mouseLock--;
		return;
	}

	if ((g_regionFlags & 0x4000) != 0) {
		GUI_Mouse_Show();
	}

	g_regionFlags = 0;
	g_mouseLock--;
}

/**
 * Hide the mouse when it is inside the specified region. Works with
 *  #GUI_Mouse_Show_InRegion(), which only calls #GUI_Mouse_Show() when
 *  mouse was really hidden.
 */
void GUI_Mouse_Hide_InRegion(uint16 left, uint16 top, uint16 right, uint16 bottom)
{
	int minx, miny;
	int maxx, maxy;

	minx = left - ((g_mouseWidth - 1) << 3) + g_mouseSpriteHotspotX;
	if (minx < 0) minx = 0;

	miny = top - g_mouseHeight + g_mouseSpriteHotspotY;
	if (miny < 0) miny = 0;

	maxx = right + g_mouseSpriteHotspotX;
	if (maxx > SCREEN_WIDTH - 1) maxx = SCREEN_WIDTH - 1;

	maxy = bottom + g_mouseSpriteHotspotY;
	if (maxy > SCREEN_HEIGHT - 1) maxy = SCREEN_HEIGHT - 1;

	while (g_mouseLock != 0) sleepIdle();
	g_mouseLock++;

	if (g_regionFlags == 0) {
		g_regionMinX = minx;
		g_regionMinY = miny;
		g_regionMaxX = maxx;
		g_regionMaxY = maxy;
	}

	if (minx > g_regionMinX) g_regionMinX = minx;
	if (miny > g_regionMinY) g_regionMinY = miny;
	if (maxx < g_regionMaxX) g_regionMaxX = maxx;
	if (maxy < g_regionMaxY) g_regionMaxY = maxy;

	if ((g_regionFlags & 0x4000) == 0 &&
	     g_mouseX >= g_regionMinX &&
	     g_mouseX <= g_regionMaxX &&
	     g_mouseY >= g_regionMinY &&
	     g_mouseY <= g_regionMaxY) {
		GUI_Mouse_Hide();

		g_regionFlags |= 0x4000;
	}

	g_regionFlags |= 0x8000;
	g_regionFlags = (g_regionFlags & 0xFF00) | (((g_regionFlags & 0x00FF) + 1) & 0xFF);

	g_mouseLock--;
}

/**
 * Show the mouse if needed. Should be used in combination with
 *  GUI_Mouse_Hide_InWidget().
 */
void GUI_Mouse_Show_InWidget(void)
{
	GUI_Mouse_Show_InRegion();
}

/**
 * Hide the mouse when it is inside the specified widget. Works with
 *  #GUI_Mouse_Show_InWidget(), which only calls #GUI_Mouse_Show() when
 *  mouse was really hidden.
 * @param widgetIndex The index of the widget to check on.
 */
void GUI_Mouse_Hide_InWidget(uint16 widgetIndex)
{
	uint16 left, top;
	uint16 width, height;

	left   = g_widgetProperties[widgetIndex].xBase << 3;
	top    = g_widgetProperties[widgetIndex].yBase;
	width  = g_widgetProperties[widgetIndex].width << 3;
	height = g_widgetProperties[widgetIndex].height;

	GUI_Mouse_Hide_InRegion(left, top, left + width - 1, top + height - 1);
}

/**
 * Draws a chess-pattern filled rectangle.
 * @param left The X-position of the rectangle.
 * @param top The Y-position of the rectangle.
 * @param width The width of the rectangle.
 * @param height The height of the rectangle.
 * @param colour The colour of the rectangle.
 */
void GUI_DrawBlockedRectangle(int16 left, int16 top, int16 width, int16 height, uint8 colour)
{
	uint8 *screen;

	if (width <= 0) return;
	if (height <= 0) return;
	if (left >= SCREEN_WIDTH) return;
	if (top >= SCREEN_HEIGHT) return;

	if (left < 0) {
		if (left + width <= 0) return;
		width += left;
		left = 0;
	}
	if (top < 0) {
		if (top + height <= 0) return;
		height += top;
		top = 0;
	}

	if (left + width >= SCREEN_WIDTH) {
		width = SCREEN_WIDTH - left;
	}
	if (top + height >= SCREEN_HEIGHT) {
		height = SCREEN_HEIGHT - top;
	}

	screen = GFX_Screen_GetActive();
	screen += top * SCREEN_WIDTH + left;

	for (; height > 0; height--) {
		int i = width;

		if ((height & 1) != (width & 1)) {
			screen++;
			i--;
		}

		for (; i > 0; i -= 2) {
			*screen = colour;
			screen += 2;
		}

		screen += SCREEN_WIDTH - width - (height & 1);
	}
}

/**
 * Set the mouse to the given position on the screen.
 *
 * @param x The new X-position of the mouse.
 * @param y The new Y-position of the mouse.
 */
void GUI_Mouse_SetPosition(uint16 x, uint16 y)
{
	while (g_mouseLock != 0) sleepIdle();
	g_mouseLock++;

	if (x < g_mouseRegionLeft)   x = g_mouseRegionLeft;
	if (x > g_mouseRegionRight)  x = g_mouseRegionRight;
	if (y < g_mouseRegionTop)    y = g_mouseRegionTop;
	if (y > g_mouseRegionBottom) y = g_mouseRegionBottom;

	g_mouseX = x;
	g_mouseY = y;

	Video_Mouse_SetPosition(x, y);

	if (g_mouseX != g_mousePrevX || g_mouseY != g_mousePrevY) {
		GUI_Mouse_Hide();
		GUI_Mouse_Show();
	}

	g_mouseLock--;
}

/**
 * Remap all the colours in the region with the ones indicated by the remap palette.
 * @param left The left of the region to remap.
 * @param top The top of the region to remap.
 * @param width The width of the region to remap.
 * @param height The height of the region to remap.
 * @param screenID The screen to do the remapping on.
 * @param remap The pointer to the remap palette.
 */
void GUI_Palette_RemapScreen(uint16 left, uint16 top, uint16 width, uint16 height, Screen screenID, const uint8 *remap)
{
	uint8 *screen = GFX_Screen_Get_ByIndex(screenID);

	screen += top * SCREEN_WIDTH + left;
	for (; height > 0; height--) {
		int i;
		for (i = width; i > 0; i--) {
			uint8 pixel = *screen;
			*screen++ = remap[pixel];
		}
		screen += SCREEN_WIDTH - width;
	}
}

uint16 GUI_HallOfFame_Tick(void)
{
	static uint32 l_timerNext = 0;
	static int16 colouringDirection = 1;

	if (l_timerNext >= g_timerGUI) return 0;
	l_timerNext = g_timerGUI + 2;

	if (*s_palette1_houseColour >= 63) {
		colouringDirection = -1;
	} else if (*s_palette1_houseColour <= 35) {
		colouringDirection = 1;
	}

	*s_palette1_houseColour += colouringDirection;

	GFX_SetPalette(g_palette1);

	return 0;
}

static Widget *GUI_HallOfFame_CreateButtons(HallOfFameStruct *data)
{
	const char *resumeString;
	const char *clearString;
	Widget *wClear;
	Widget *wResume;
	uint16 width;

	memcpy(s_temporaryColourBorderSchema, s_colourBorderSchema, sizeof(s_colourBorderSchema));
	memcpy(s_colourBorderSchema, s_HOF_ColourBorderSchema, sizeof(s_colourBorderSchema));

	resumeString = String_Get_ByIndex(STR_RESUME_GAME2);
	clearString  = String_Get_ByIndex(STR_CLEAR_LIST);

	width = max(Font_GetStringWidth(resumeString), Font_GetStringWidth(clearString)) + 6;

	/* "Clear List" */
	wClear = GUI_Widget_Allocate(100, *clearString, 160 - width - 18, 180, 0xFFFE, STR_CLEAR_LIST);
	wClear->width     = width;
	wClear->height    = 10;
	wClear->clickProc = &GUI_Widget_HOF_ClearList_Click;
	memset(&wClear->flags, 0, sizeof(wClear->flags));
	wClear->flags.requiresClick = true;
	wClear->flags.clickAsHover = true;
	wClear->flags.loseSelect = true;
	wClear->flags.notused2 = true;
	wClear->flags.buttonFilterLeft = 4;
	wClear->flags.buttonFilterRight = 4;
	wClear->data      = data;

	/* "Resume Game" */
	wResume = GUI_Widget_Allocate(101, *resumeString, 178, 180, 0xFFFE, STR_RESUME_GAME2);
	wResume->width     = width;
	wResume->height    = 10;
	wResume->clickProc = &GUI_Widget_HOF_Resume_Click;
	memset(&wResume->flags, 0, sizeof(wResume->flags));
	wResume->flags.requiresClick = true;
	wResume->flags.clickAsHover = true;
	wResume->flags.loseSelect = true;
	wResume->flags.notused2 = true;
	wResume->flags.buttonFilterLeft = 4;
	wResume->flags.buttonFilterRight = 4;
	wResume->data      = data;

	return GUI_Widget_Insert(wClear, wResume);
}

static void GUI_HallOfFame_DeleteButtons(Widget *w)
{
	while (w != NULL) {
		Widget *next = w->next;

		free(w);

		w = next;
	}

	memcpy(s_colourBorderSchema, s_temporaryColourBorderSchema, sizeof(s_temporaryColourBorderSchema));
}

static void GUI_HallOfFame_Encode(HallOfFameStruct *data)
{
	uint8 i;
	uint8 *d;

	for (d = (uint8 *)data, i = 0; i < 128; i++, d++) *d = (*d + i) ^ 0xA7;
}

static void GUI_HallOfFame_Decode(HallOfFameStruct *data)
{
	uint8 i;
	uint8 *d;

	for (d = (uint8 *)data, i = 0; i < 128; i++, d++) *d = (*d ^ 0xA7) - i;
}

static uint16 GUI_HallOfFame_InsertScore(HallOfFameStruct *data, uint16 score)
{
	uint16 i;
	for (i = 0; i < 8; i++, data++) {
		if (data->score >= score) continue;

		memmove(data + 1, data, 128);
		memset(data->name, 0, 6);
		data->score = score;
		data->houseID = g_playerHouseID;
		data->rank = GUI_HallOfFame_GetRank(score);
		data->campaignID = g_campaignID;

		return i + 1;
	}

	return 0;
}

void GUI_HallOfFame_Show(uint16 score)
{
	uint16 width;
	uint16 editLine;
	Widget *w;
	uint8 fileID;
	HallOfFameStruct *data;

	GUI_Mouse_Hide_Safe();

	if (score == 0xFFFF) {
		if (!File_Exists_Personal("SAVEFAME.DAT")) {
			GUI_Mouse_Show_Safe();
			return;
		}
		s_ticksPlayed = 0;
	}

	data = (HallOfFameStruct *)GFX_Screen_Get_ByIndex(SCREEN_2);

	if (!File_Exists_Personal("SAVEFAME.DAT")) {
		uint16 written;

		memset(data, 0, 128);

		GUI_HallOfFame_Encode(data);

		fileID = File_Open_Personal("SAVEFAME.DAT", FILE_MODE_WRITE);
		written = File_Write(fileID, data, 128);
		File_Close(fileID);

		if (written != 128) return;
	}

	File_ReadBlockFile_Personal("SAVEFAME.DAT", data, 128);

	GUI_HallOfFame_Decode(data);

	GUI_HallOfFame_DrawBackground(score, true);

	if (score == 0xFFFF) {
		editLine = 0;
	} else {
		editLine = GUI_HallOfFame_InsertScore(data, score);
	}

	width = GUI_HallOfFame_DrawData(data, false);

	GUI_Screen_Copy(0, 0, 0, 0, SCREEN_WIDTH / 8, SCREEN_HEIGHT, SCREEN_1, SCREEN_0);

	if (editLine != 0) {
		WidgetProperties backupProperties;
		char *name;

		name = data[editLine - 1].name;

		memcpy(&backupProperties, &g_widgetProperties[19], sizeof(WidgetProperties));

		g_widgetProperties[19].xBase = 4;
		g_widgetProperties[19].yBase = (editLine - 1) * 11 + 90;
		g_widgetProperties[19].width = width / 8;
		g_widgetProperties[19].height = 11;
		g_widgetProperties[19].fgColourBlink = 6;
		g_widgetProperties[19].fgColourNormal = 116;

		GUI_DrawText_Wrapper(NULL, 0, 0, 0, 0, 0x22);

		while (*name == '\0') {
			char *nameEnd;
			Screen oldScreenID;

			oldScreenID = GFX_Screen_SetActive(SCREEN_0);
			Widget_SetAndPaintCurrentWidget(19);
			GFX_Screen_SetActive(oldScreenID);

			GUI_EditBox(name, 5, 19, NULL, &GUI_HallOfFame_Tick, false);

			if (*name == '\0') continue;

			nameEnd = name + strlen(name) - 1;

			while (*nameEnd <= ' ' && nameEnd >= name) *nameEnd-- = '\0';
		}

		memcpy(&g_widgetProperties[19], &backupProperties, sizeof(WidgetProperties));

		GUI_HallOfFame_DrawData(data, true);

		GUI_HallOfFame_Encode(data);

		fileID = File_Open_Personal("SAVEFAME.DAT", FILE_MODE_WRITE);
		File_Write(fileID, data, 128);
		File_Close(fileID);
	}

	GUI_Mouse_Show_Safe();

	w = GUI_HallOfFame_CreateButtons(data);

	Input_History_Clear();

	GFX_Screen_SetActive(SCREEN_0);

	for (g_doQuitHOF = false; !g_doQuitHOF; sleepIdle()) {
		GUI_Widget_HandleEvents(w);
	}

	GUI_HallOfFame_DeleteButtons(w);

	Input_History_Clear();

	if (score == 0xFFFF) return;

	memset(g_palette1 + 255 * 3, 0, 3);
}

uint16 GUI_HallOfFame_DrawData(HallOfFameStruct *data, bool show)
{
	Screen oldScreenID;
	const char *scoreString;
	const char *battleString;
	uint16 width = 0;
	uint16 offsetY;
	uint16 scoreX;
	uint16 battleX;
	uint8 i;

	oldScreenID = GFX_Screen_SetActive(SCREEN_1);
	GUI_DrawFilledRectangle(8, 80, 311, 178, 116);
	GUI_DrawText_Wrapper(NULL, 0, 0, 0, 0, 0x22);

	battleString = String_Get_ByIndex(STR_BATTLE);
	scoreString = String_Get_ByIndex(STR_SCORE);

	scoreX = 320 - Font_GetStringWidth(scoreString) / 2 - 12;
	battleX = scoreX - Font_GetStringWidth(scoreString) / 2 - 8 - Font_GetStringWidth(battleString) / 2;
	offsetY = 80;

	GUI_DrawText_Wrapper(String_Get_ByIndex(STR_NAME_AND_RANK), 32, offsetY, 8, 0, 0x22);
	GUI_DrawText_Wrapper(battleString, battleX, offsetY, 8, 0, 0x122);
	GUI_DrawText_Wrapper(scoreString, scoreX, offsetY, 8, 0, 0x122);

	offsetY = 90;
	for (i = 0; i < 8; i++, offsetY += 11) {
		char buffer[81];
		const char *p1, *p2;

		if (data[i].score == 0) break;

		if (g_config.language == LANGUAGE_FRENCH) {
			p1 = String_Get_ByIndex(_rankScores[data[i].rank].rankString);
			p2 = g_table_houseInfo[data[i].houseID].name;
		} else {
			p1 = g_table_houseInfo[data[i].houseID].name;
			p2 = String_Get_ByIndex(_rankScores[data[i].rank].rankString);
		}
		snprintf(buffer, sizeof(buffer), "%s, %s %s", data[i].name, p1, p2);

		if (*data[i].name == '\0') {
			width = battleX - 36 - Font_GetStringWidth(buffer);
		} else {
			GUI_DrawText_Wrapper(buffer, 32, offsetY, 15, 0, 0x22);
		}

		GUI_DrawText_Wrapper("%u.", 24, offsetY, 15, 0, 0x222, i + 1);
		GUI_DrawText_Wrapper("%u", battleX, offsetY, 15, 0, 0x122, data[i].campaignID);
		GUI_DrawText_Wrapper("%u", scoreX, offsetY, 15, 0, 0x122, data[i].score);
	}

	if (show) {
		GUI_Mouse_Hide_Safe();
		GUI_Screen_Copy(1, 80, 1, 80, 38, 100, SCREEN_1, SCREEN_0);
		GUI_Mouse_Show_Safe();
	}

	GFX_Screen_SetActive(oldScreenID);

	return width;
}

/**
 * Draw a filled rectangle using xor.
 * @param left The left position of the rectangle.
 * @param top The top position of the rectangle.
 * @param right The right position of the rectangle.
 * @param bottom The bottom position of the rectangle.
 * @param colour The colour of the rectangle.
 */
void GUI_DrawXorFilledRectangle(int16 left, int16 top, int16 right, int16 bottom, uint8 colour)
{
	uint16 x;
	uint16 y;
	uint16 height;
	uint16 width;

	uint8 *screen = GFX_Screen_GetActive();

	if (left >= SCREEN_WIDTH) return;
	if (left < 0) left = 0;

	if (top >= SCREEN_HEIGHT) return;
	if (top < 0) top = 0;

	if (right >= SCREEN_WIDTH) right = SCREEN_WIDTH - 1;
	if (right < 0) right = 0;

	if (bottom >= SCREEN_HEIGHT) bottom = SCREEN_HEIGHT - 1;
	if (bottom < 0) bottom = 0;

	if (left > right) return;
	if (top > bottom) return;

	screen += left + top * SCREEN_WIDTH;
	width = right - left + 1;
	height = bottom - top + 1;
	for (y = 0; y < height; y++) {
		for (x = 0; x < width; x++) {
			*screen++ ^= colour;
		}
		screen += SCREEN_WIDTH - width;
	}
}

/**
 * Create the remap palette for the givern house.
 * @param houseID The house ID.
 */
void GUI_Palette_CreateRemap(uint8 houseID)
{
	int16 i;
	int16 loc4;
	int16 loc6;
	uint8 *remap;

	remap = g_remap;
	for (i = 0; i < 0x100; i++, remap++) {
		*remap = i & 0xFF;

		loc6 = i / 16;
		loc4 = i % 16;
		if (loc6 == 9 && loc4 <= 6) {
			*remap = (houseID << 4) + 0x90 + loc4;
		}
	}
}

/**
 * Draw the screen.
 * This also handles animation tick and other viewport related activity.
 * @param screenID The screen to draw on.
 */
void GUI_DrawScreen(Screen screenID)
{
	static uint32 s_timerViewportMessage = 0;
	bool hasScrolled = false;
	bool viewportPlanarShifted = false;
	Screen oldScreenID;
	uint16 xpos;

	if (g_selectionType == SELECTIONTYPE_MENTAT) return;
	if (g_selectionType == SELECTIONTYPE_DEBUG) return;
	if (g_selectionType == SELECTIONTYPE_UNKNOWN6) return;
	if (g_selectionType == SELECTIONTYPE_INTRO) return;

	oldScreenID = GFX_Screen_SetActive(screenID);

	if (!GFX_Screen_IsActive(SCREEN_0)) g_viewport_forceRedraw = true;

	Explosion_Tick();
	Animation_Tick();
	Unit_Sort();

	if (!g_viewport_forceRedraw && g_viewportPosition != g_minimapPosition) {
		uint16 viewportX = Tile_GetPackedX(g_viewportPosition);
		uint16 viewportY = Tile_GetPackedY(g_viewportPosition);
		int16 xOffset = Tile_GetPackedX(g_minimapPosition) - viewportX; /* Horizontal offset between viewport and minimap. */
		int16 yOffset = Tile_GetPackedY(g_minimapPosition) - viewportY; /* Vertical offset between viewport and minmap. */

		/* Overlap remaining in tiles. */
		int16 xOverlap = 15 - abs(xOffset);
		int16 yOverlap = 10 - abs(yOffset);

		int16 x, y;

		if (xOverlap < 1 || yOverlap < 1) {
			g_viewport_forceRedraw = true;
		} else if (!g_viewport_forceRedraw && (xOverlap != 15 || yOverlap != 10)) {
			Map_SetSelectionObjectPosition(0xFFFF);
			hasScrolled = true;

			GUI_Mouse_Hide_InWidget(2);

			/* Legacy composition keeps SCREEN_1 authoritative. A direct
			 * planar scene has no logical shadow to shift; a later switch
			 * back to legacy reconstructs it from the map and actors. */
#ifdef TOS
			if (!GUI_Widget_Viewport_IsPlanar())
#endif
			GUI_Screen_CopyOverlap(max(-xOffset << 1, 0), 40 + max(-yOffset << 4, 0), max(0, xOffset << 1), 40 + max(0, yOffset << 4), xOverlap << 1, yOverlap << 4, SCREEN_1);

#ifdef TOS
			/* Mirror the same shift directly in the planar screen: those
			 * pixels are already converted and on screen, only moved, so
			 * this avoids re-running c2p on them. The rectangle is always
			 * whole 16px tiles (viewport scrolling never happens at any
			 * other granularity), so it is always c2p-group aligned. If
			 * this declines (TT/Falcon, or the geometry is not aligned
			 * after all), viewportPlanarShifted stays false and
			 * GUI_Widget_Viewport_Draw() falls back to presenting the
			 * whole row on scroll, exactly as it always did before this. */
			viewportPlanarShifted = Video_Atari_ShiftPlanar(
				(int16)max(-xOffset << 4, 0), (int16)(40 + max(-yOffset << 4, 0)),
				(uint16)(xOverlap << 4), (uint16)(yOverlap << 4),
				(int16)(xOffset << 4), (int16)(yOffset << 4));
#endif
		} else {
			g_viewport_forceRedraw = true;
		}

		xOffset = max(0, xOffset);
		yOffset = max(0, yOffset);

		for (y = 0; y < 10; y++) {
			uint16 mapYBase = (y + viewportY) << 6;

			for (x = 0; x < 15; x++) {
				if (x >= xOffset && (xOffset + xOverlap) > x && y >= yOffset && (yOffset + yOverlap) > y && !g_viewport_forceRedraw) continue;

				/* This tile is the vacated edge: Video_Atari_ShiftPlanar()
				 * above already blanked it (proper move semantics), so no
				 * separate clear is needed here -- just redraw it. Once
				 * the planar shift has already moved every other visible
				 * tile to its correct new position, use the narrow update
				 * (type 4) so marking this one tile dirty does not also
				 * widen the SCREEN_1->SCREEN_0 copy range into the still-
				 * correct neighbouring column via type 0's 8-neighbour
				 * spread; without a planar shift, the neighbour spread is
				 * harmless noise next to the full-row fallback anyway. */
				Map_Update(x + viewportX + mapYBase, viewportPlanarShifted ? 4 : 0, true);
			}
		}
	}

	if (hasScrolled) {
		Map_SetSelectionObjectPosition(0xFFFF);

		for (xpos = 0; xpos < 14; xpos++) {
			uint16 v = g_minimapPosition + xpos + 6*64;

			BitArray_Set(g_dirtyViewport, v);
			BitArray_Set(g_dirtyMinimap, v);

			g_dirtyViewportCount++;
		}
	}

	g_minimapPosition = g_viewportPosition;
	g_selectionRectanglePosition = g_selectionPosition;

	if (g_viewportMessageCounter != 0 && s_timerViewportMessage < g_timerGUI) {
		g_viewportMessageCounter--;
		s_timerViewportMessage = g_timerGUI + 60;

		for (xpos = 0; xpos < 14; xpos++) {
			Map_Update(g_viewportPosition + xpos + 6 * 64, 0, true);
		}
	}

	GUI_Widget_Viewport_Draw(g_viewport_forceRedraw, hasScrolled, viewportPlanarShifted, !GFX_Screen_IsActive(SCREEN_0));

	g_viewport_forceRedraw = false;

	GFX_Screen_SetActive(oldScreenID);

	Map_SetSelectionObjectPosition(g_selectionRectanglePosition);
	Map_UpdateMinimapPosition(g_minimapPosition, false);

#ifdef TOS
	if (Video_Atari_CursorDirect() && g_selectionType == SELECTIONTYPE_PLACE && screenID == SCREEN_0) {
		int16 x = ((int16)Tile_GetPackedX(g_selectionRectanglePosition) - (int16)Tile_GetPackedX(g_minimapPosition)) * 16;
		int16 y = ((int16)Tile_GetPackedY(g_selectionRectanglePosition) - (int16)Tile_GetPackedY(g_minimapPosition)) * 16 + 40;
		Video_Atari_PlacementSet(x, y, g_selectionWidth * 16, g_selectionHeight * 16, g_selectionState == 0);
	} else {
		Video_Atari_PlacementHide();
	}
#endif
	GUI_Mouse_Show_InWidget();
}

/**
 * Set a new palette, but animate it in slowly.
 * @param palette The new palette.
 * @param ticksOfAnimation The amount of ticks it should take.
 */
void GUI_SetPaletteAnimated(uint8 *palette, int16 ticksOfAnimation)
{
	bool progress;
	int16 diffPerTick;
	int16 tickSlice;
	uint32 timerCurrent;
	int16 highestDiff;
	int16 ticks;
	uint16 tickCurrent;
	uint8 data[256 * 3];
	int i;

	if (palette == NULL) return;

	memcpy(data, g_paletteActive, 256 * 3);

#ifdef TOS
	/* Fast path: full-screen fades to/from a uniform palette (all-black,
	 * or the intro's all-white flash) never need to re-quantize/rebuild
	 * anything, see Video_Atari_TryPaletteFadeUniform() in video_atari.c.
	 * Every other animation - e.g. in-game palette cycling effects, or a
	 * cross-fade between two unrelated pictures - falls through to the
	 * normal path below unchanged. */
	if (Video_Atari_TryPaletteFadeUniform(data, palette, ticksOfAnimation)) {
		memcpy(g_paletteActive, data, 256 * 3);
		return;
	}
#endif

	highestDiff = 0;
	for (i = 0; i < 256 * 3; i++) {
		int16 diff = (int16)palette[i] - (int16)data[i];
		highestDiff = max(highestDiff, abs(diff));
	}

	ticks = ticksOfAnimation << 8;
	if (highestDiff != 0) ticks /= highestDiff;

	/* Find a nice value to change every timeslice */
	tickSlice = ticks;
	diffPerTick = 1;
	while (diffPerTick <= highestDiff && ticks < (2 << 8)) {
		ticks += tickSlice;
		diffPerTick++;
	}

	tickCurrent = 0;
	timerCurrent = g_timerSleep;

	for (;;) {
		progress = false;	/* will be set true if any color is changed */

		tickCurrent  += (uint16)ticks;
		timerCurrent += (uint32)(tickCurrent >> 8);
		tickCurrent  &= 0xFF;

		for (i = 0; i < 256 * 3; i++) {
			int16 goal = palette[i];
			int16 current = data[i];

			if (goal == current) continue;

			progress = true;
			if (goal > current) {
				current += diffPerTick;
				if (current > goal) current = goal;
			} else {
				current -= diffPerTick;
				if (current < goal) current = goal;
			}
			data[i] = (uint8)current;
		}

		/* if no color was changed, the target palette has been reached */
		if (!progress) break;

		GFX_SetPalette(data);

		while (g_timerSleep < timerCurrent) sleepIdle();
	}
}
