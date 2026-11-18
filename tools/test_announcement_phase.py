"""Check banner timing, literal messages and retained planar line pixels."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function
from tools.test_dither_preparation import surface_backend


ROOT = Path(__file__).resolve().parents[1]


class AnnouncementPhaseTest(unittest.TestCase):
    def test_phases_and_message_timing(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        config = (ROOT / "src/config.c").read_text()
        startup = (ROOT / "src/opendune.c").read_text()
        self.assertLess(startup.index("Load_IniFile();"),
                        startup.index("Config_LoadAnimationPhases();"))
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include "table/strings.h"
typedef uint8_t uint8;
typedef int8_t int8;
typedef uint16_t uint16;
typedef int16_t int16;
typedef uint32_t uint32;
typedef int Screen;
enum { SCREEN_0, SCREEN_1, SCREEN_WIDTH = 320 };
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
#define lengthof(a) (sizeof(a) / sizeof(*(a)))
typedef struct { uint16 height; } Font;
static Font font = { 11 }, otherFont = { 11 };
static Font *g_fontNew6p = &font, *g_fontNew8p = &font, *g_fontCurrent = &font;
static uint8 g_colours[16];
static int8 g_fontCharOffset;
static uint16 s_textFontFlags = -1, s_textStyleFlags = -1;
static uint16 g_announcementPhase = 1;
static uint16 g_creditsPhase = 1;
static uint16 g_blinkEffect, g_placementValidPlane, g_placementInvalidPlane;
static uint16 g_tileCursor, g_tileCursorPen, g_tileCursorTargetPen;
static bool g_enableCosmeticAnimations = true;
static int16 s_viewportFade = -1;
static uint32 g_timerGUI;
static bool g_textDisplayNeedsUpdate;
static uint16 g_curWidgetXBase = 1, g_curWidgetYBase = 21;
static uint16 g_curWidgetWidth = 38, g_curWidgetHeight = 14;
static uint8 g_curWidgetFGColourNormal = 116;
static Screen active;
static uint16 currentWidget = 6;
static unsigned frames, renders, hides, shows, warnings;
static unsigned offsets[64], heights[64];
static char prepared[80], displayed[80];
static unsigned formats;
static int counted_vsnprintf(char *dst, size_t size, const char *fmt, va_list ap) {
    formats++;
    return vsnprintf(dst, size, fmt, ap);
}
#define vsnprintf counted_vsnprintf
static const char *option, *creditsOption;
static char *IniFile_GetString(const char *key, const char *fallback, char *out, uint16 size) {
    assert(fallback == NULL);
    const char *value;
    if (!strcmp(key, "phase_announcement")) value = option;
    else if (!strcmp(key, "phase_credits")) {
        value = creditsOption;
    } else {
        assert(!strcmp(key, "viewport_fade") || !strcmp(key, "cosmetic_animations") ||
               !strcmp(key, "blink_effect") || !strcmp(key, "placement_valid_plane") ||
               !strcmp(key, "placement_invalid_plane") || !strcmp(key, "tile_cursor") ||
               !strcmp(key, "tile_cursor_pen") || !strcmp(key, "tile_cursor_target_pen"));
        value = NULL;
    }
    if (value == NULL) return NULL;
    snprintf(out, size, "%s", value);
    return out;
}
#define Warning(...) (warnings++)
/* OPTION */
static uint16 Widget_SetCurrentWidget(uint16 index) {
    uint16 old = currentWidget;
    currentWidget = index;
    return old;
}
static Screen GFX_Screen_SetActive(Screen screen) {
    Screen old = active;
    active = screen;
    return old;
}
static void GUI_DrawFilledRectangle(int x, int y, int right, int bottom, uint8 colour) {
    assert(x == 0 && y == 0 && right == 319 && bottom == 23 && colour == 116);
    assert(active == SCREEN_1 && currentWidget == 7);
    renders++;
}
static void Font_Select(Font *f) { g_fontCurrent = f; }
static unsigned Font_GetStringWidth(const char *s) { return strlen(s) * 6; }
static void GUI_InitColors(const uint8 *colours, unsigned first, unsigned last) {
    memcpy(g_colours + first, colours, last - first + 1);
}
void GUI_DrawText_Wrapper(const char *, int16, int16, uint8, uint8, int, ...);
static void GUI_Mouse_Hide_InWidget(unsigned widget) {
    assert(widget == 7);
    hides++;
}
static void GUI_Mouse_Show_InWidget(void) { shows++; }
static void present(unsigned offset, unsigned height) {
    assert(frames < 64 && offset <= 10 && height == 14);
    offsets[frames] = offset;
    heights[frames++] = height;
    if (offset == 0) snprintf(displayed, sizeof(displayed), "%s", prepared);
}
#ifndef TOS
static void GUI_Screen_Copy(int xs, int ys, int xd, int yd, int width, int height,
                           Screen src, Screen dst) {
    assert(xs == 1 && xd == 1 && yd == 21 && width == 38 && src == SCREEN_1 && dst == SCREEN_0);
    present(ys, height);
}
#else
#include "video/atari_mono.h"
#include "video/atari_mono_palette.h"
#ifdef BANNER_MONO
#define Video_Atari_Mono() true
#else
#define Video_Atari_Mono() false
#endif
#ifdef MONO_WHITE_IS_ZERO
static bool s_monoWhiteIsOne = false;
#else
static bool s_monoWhiteIsOne = true;
#endif
/* MONO PEN */
void *GFX_Screen_Get_ByIndex(Screen screenID) {
    (void)screenID; assert(false); return NULL;
}
void Video_Atari_EncodePlanar(const uint8 *src, uint16 *dst, uint16 w, uint16 h) {
    (void)src; (void)dst; (void)w; (void)h; assert(false);
}
static bool direct;
static uint16 *s_planarTarget;
static uint16 s_planarTargetStride, s_planarTargetRows, s_planarGroups;
static bool s_planarLineDone;
/* PLANAR BOX */
static uint16 *encoded, screen[200 * 80];
static uint16 paletteGeneration;
static uint8 paletteShift;
static unsigned glyphRenders[2];
static bool unsupported;
static bool Video_Atari_CursorDirect(void) { return direct; }
static uint8 Video_Atari_GetPalettePen(uint8 c) { return (c + paletteShift) & 15; }
static uint16 Video_Atari_GetPaletteGeneration(void) { return paletteGeneration; }
static bool GUI_Sidebar_DrawButtonCaption(int x, int y, uint8 fg, uint8 bg) {
    (void)x; (void)y; (void)fg; (void)bg;
    return false;
}
static void Video_Atari_PresentPlanarWindow(const uint16 *pixels, uint16 x, uint16 y,
                                           uint16 width, uint16 height) {
    assert(x >= g_curWidgetXBase * 8 && x + width <= (g_curWidgetXBase + g_curWidgetWidth) * 8);
    assert(y >= 21 && y + height <= 35 && height != 0);
    unsigned offset = (pixels - encoded) / 80 + g_curWidgetYBase - y;
    for (unsigned row = 0; row < height; row++)
        for (unsigned col = x; col < x + width; col++)
            if (Video_Atari_Mono()) {
                for (unsigned dy = 0; dy < 2; dy++) {
                    unsigned mask = 3u << (14 - (col & 7) * 2);
                    unsigned off = (y + row) * 80 + dy * 40 + col / 8;
                    unsigned src = row * 80 + dy * 40 + col / 8;
                    screen[off] = (screen[off] & ~mask) | (pixels[src] & mask);
                }
            } else for (unsigned p = 0; p < 4; p++) {
                uint16 mask = 0x8000u >> (col & 15);
                uint16 *dst = &screen[(y + row) * 80 + (col >> 4) * 4 + p];
                *dst = (*dst & (uint16)~mask) | (pixels[row * 80 + (col >> 4) * 4 + p] & mask);
            }
    present(offset, g_curWidgetHeight);
    uint32 hash = 2166136261u;
    for (unsigned i = 0; i < sizeof(screen) / sizeof(*screen); i++)
        hash = (hash ^ screen[i]) * 16777619u;
    printf("%u %u %u\n", offset, height, hash);
}
static void GUI_Screen_Copy(int xs, int ys, int xd, int yd, int width, int height,
                           Screen src, Screen dst) {
    assert(!direct && xs == 1 && xd == 1 && yd == 21 && width == 38);
    assert(src == SCREEN_1 && dst == SCREEN_0);
    present(ys, height);
}
#endif
void GUI_DrawText(const char *text, int16 x, int16 y, uint8 fg, uint8 bg) {
    assert((y == 2 || y == 13) && bg == 0);
    uint8 colours[] = { bg, fg };
    GUI_InitColors(colours, 0, 1);
#ifdef TOS
    if (s_planarTarget != NULL) {
        encoded = s_planarTarget;
        s_planarGroups = 0;
        s_planarLineDone = true;
    }
#endif
    if (*text == '\0') return;
    if (y == 2) snprintf(prepared, sizeof(prepared), "%s", text);
#ifdef TOS
    if (s_planarTarget != NULL) {
        unsigned line = y == 2 ? 0 : 1;
        glyphRenders[line]++;
        if (line == 0) renders++;
        unsigned right = min(320, x + strlen(text) * (unsigned)(6 + g_fontCharOffset));
        s_planarGroups = ((right + 15) >> 4) - (x >> 4);
        for (unsigned row = y; row < min(24u, (unsigned)y + g_fontCurrent->height); row++)
            for (unsigned col = x; col < right; col++) {
                unsigned ch = text[(col - x) / (6 + g_fontCharOffset)];
                if ((ch + col + row) % 3 == 0) continue;
                uint8 pen = Video_Atari_GetPalettePen(fg + g_colours[4] + (ch & 1));
                if (Video_Atari_Mono()) {
                    uint16 fill[4], words[4];
                    unsigned relative = (col - x) % (6 + g_fontCharOffset);
                    Video_Atari_MonoPenWords(pen, relative - (col & 15), row - y, fill);
                    Video_Atari_MonoReadGroup(s_planarTarget, 80, row, col / 16, words);
                    Video_Atari_MonoMergeWords(words, fill, 0x8000u >> (col & 15));
                    Video_Atari_MonoWriteGroup(s_planarTarget, 80, row, col / 16, words);
                } else for (unsigned p = 0; p < 4; p++) {
                    uint16 mask = 0x8000u >> (col & 15);
                    uint16 *dst = &s_planarTarget[row * 80 + (col >> 4) * 4 + p];
                    *dst = (*dst & (uint16)~mask) | ((pen & (1u << p)) ? mask : 0);
                }
            }
        PlanarBox box = { x & ~15, y, (right + 15) & ~15,
                          min(24, y + g_fontCurrent->height) };
        assert(s_planarTargetStride == 80 && s_planarTargetRows == 24);
        PlanarBox_Union(s_planarTouch, &box);
        s_planarLineDone = !unsupported;
    }
#else
    (void)x;
#endif
}
/* TEXT WRAPPER */
/* ANIMATOR */
enum { UNIT_TANK, UNIT_HARVESTER = 16, UNIT_SANDWORM = 25 };
enum { ACTION_MOVE, ACTION_HARVEST, ACTION_STOP };
enum { LST_ROCK, LST_SPICE, LST_THICK_SPICE, LANGUAGE_FRENCH = 1 };
typedef struct {
    struct { uint8 type; uint16 position; struct { uint16 variables[5]; } script; } o;
    uint8 amount, actionID, house;
    uint16 targetMove;
} Unit;
typedef struct { struct { uint16 stringID_abbrev; } o; } UnitInfo;
static const UnitInfo g_table_unitInfo[26] = {
    [UNIT_TANK] = {{1000}}, [UNIT_HARVESTER] = {{1001}}, [UNIT_SANDWORM] = {{1002}}
};
static const struct { const char *name; } g_table_houseInfo[] = {{"Atreides"}, {"Harkonnen"}};
static struct { unsigned language; } g_config;
static unsigned stringLookups, landscape;
static bool targetStructure;
static uint8 Unit_GetHouseID(Unit *unit) { return unit->house; }
static uint16 Tile_PackTile(uint16 position) { return position; }
static uint16 Map_GetLandscapeType(uint16 position) { (void)position; return landscape; }
static void *Tools_Index_GetStructure(uint16 target) {
    (void)target; return targetStructure ? &targetStructure : NULL;
}
static const char *String_Get_ByIndex(uint16 id) {
    stringLookups++;
    switch (id) {
        case 1000: return "tank";
        case 1001: return "harvester";
        case 1002: return "sandworm";
        case STR_IS_D_PERCENT_FULL: return " %u%% full";
        case STR_IS_D_PERCENT_FULL_AND_HARVESTING: return " %u%% harvesting";
        case STR_IS_D_PERCENT_FULL_AND_HEADING_BACK: return " %u%% returning";
        case STR_IS_D_PERCENT_FULL_AND_AWAITING_PICKUP: return " %u%% waiting";
        case STR_IS_D_PERCENT_FULL_AND_AWAITING_PICKUP + 4: return " empty waiting";
        default: assert(false); return NULL;
    }
}
/* UNIT STATUS */
static void reset(unsigned phase) {
    g_announcementPhase = phase;
    GUI_DisplayText(NULL, -1);
    g_timerGUI = 100;
    g_textDisplayNeedsUpdate = true;
    active = SCREEN_0;
    currentWidget = 6;
    frames = renders = hides = shows = 0;
    displayed[0] = '\0';
#ifdef TOS
    memset(screen, 0x39, sizeof(screen));
#else
    prepared[0] = '\0';
#endif
}
static void poll(void) {
    GUI_DisplayText(NULL, 0);
    assert(hides == shows && active == SCREEN_0 && currentWidget == 6);
}
static void finishFrames(unsigned phase) {
    unsigned count = phase == 0 ? 1 : (phase == 1 ? 11 : 6);
    for (unsigned i = 0; i < count; i++) {
        if (frames == i) poll();
        assert(frames == i + 1);
        assert(offsets[i] == (phase == 0 ? 0 : 10 - i * phase));
        g_timerGUI++;
    }
    assert(!strcmp(displayed, "alpha"));
}
static void finish(unsigned phase) {
    finishFrames(phase);
    assert(renders == 1);
}
int main(void) {
    const char *valid[] = {"0", "1", "2", " 2\t", "+1", "00"};
    const unsigned values[] = {0, 1, 2, 2, 1, 0};
    option = NULL;
    g_announcementPhase = 0;
    Config_LoadAnimationPhases();
    assert(g_announcementPhase == 1 && g_creditsPhase == 1 && warnings == 0);
    for (unsigned i = 0; i < sizeof(valid) / sizeof(*valid); i++) {
        option = valid[i];
        Config_LoadAnimationPhases();
        assert(g_announcementPhase == values[i] && warnings == 0);
    }
    const char *invalid[] = {"", "no", "-1", "3", "1x", "1.5", "999999999999999999999999999"};
    for (unsigned i = 0; i < sizeof(invalid) / sizeof(*invalid); i++) {
        option = invalid[i];
        Config_LoadAnimationPhases();
        assert(g_announcementPhase == 1 && warnings == i + 1);
    }
    option = "0";
    creditsOption = "2";
    Config_LoadAnimationPhases();
    assert(g_announcementPhase == 0 && g_creditsPhase == 2);
    creditsOption = "bad";
    unsigned beforeWarnings = warnings;
    Config_LoadAnimationPhases();
    assert(g_announcementPhase == 0 && g_creditsPhase == 1 && warnings == beforeWarnings + 1);
    /* Run both Atari backends, or the ordinary non-TOS renderer. */
    for (unsigned backend = 0; backend < 2; backend++) {
#ifdef TOS
#ifdef BANNER_MONO
        if (backend == 0) continue;
#endif
        direct = backend != 0;
#else
        (void)backend;
#endif
        for (unsigned phase = 0; phase <= 2; phase++) {
            reset(phase);
            GUI_DisplayText("alpha", 3);
            assert(frames == (phase == 0 ? 1u : 0u));
            finish(phase);
            uint32 completed = g_timerGUI - 1;
            unsigned oldFrames = frames;
            GUI_DisplayText("ALPHA", 9); /* Duplicates remain suppressed. */
            GUI_DisplayText("beta", 2);  /* Equal aged priority must wait. */
            assert(frames == oldFrames);
            g_timerGUI = completed + 900;
            poll();
            assert(frames == oldFrames);
            g_timerGUI++;
            poll();
            assert(frames == oldFrames + (phase == 0 ? 1u : 0u));
            if (phase != 0) {
                for (unsigned i = 0; i < (phase == 1 ? 11u : 6u); i++) {
                    poll();
                    g_timerGUI++;
                }
            }
            assert(!strcmp(displayed, "beta"));
            /* Resetting next messages preserves the current display and timeout. */
            GUI_DisplayText("gamma", 1);
            oldFrames = frames;
            GUI_DisplayText(NULL, -2);
            assert(frames == oldFrames);
            GUI_DisplayText(NULL, -1);
            g_timerGUI += 2000;
            poll();
            assert(frames == oldFrames);
            /* A higher-priority message bypasses the display hold. */
            reset(phase);
            GUI_DisplayText("alpha", 3);
            finish(phase);
            oldFrames = frames;
            GUI_DisplayText("urgent", 8);
            assert(frames == oldFrames + (phase == 0 ? 1u : 0u));
            if (phase != 0) {
                for (unsigned i = 0; i < (phase == 1 ? 11u : 6u); i++) {
                    poll();
                    g_timerGUI++;
                }
            }
            assert(!strcmp(displayed, "urgent"));
        }
    }
    for (unsigned backend = 0; backend < 2; backend++) {
#ifdef TOS
#ifdef BANNER_MONO
        if (backend == 0) continue;
#endif
        direct = backend != 0;
#else
        (void)backend;
#endif
        for (unsigned phase = 0; phase <= 2; phase++) {
            /* Periodic duplicate status is a keep-alive, without another frame. */
            reset(phase);
            GUI_DisplayTextLiteral("alpha", 3);
            finishFrames(phase);
            uint32 completed = g_timerGUI - 1;
            unsigned oldFrames = frames;
            unsigned oldRenders = renders;
            g_timerGUI = completed + 300;
            GUI_DisplayTextLiteral("ALPHA", 3);
            assert(frames == oldFrames && renders == oldRenders);
            g_timerGUI = completed + 901;
            poll();
            assert(frames == oldFrames && renders == oldRenders);
            /* Without further status updates, the renewed hold still expires. */
            g_timerGUI = completed + 1200;
            poll();
            assert(frames == oldFrames);
            g_timerGUI++;
            poll();
            assert(frames == oldFrames + (phase == 0 ? 1u : 0u));
            if (phase != 0) {
                poll();
                assert(frames == oldFrames + 1 && offsets[oldFrames] == 10);
            }
        }
    }
    /* A queued message must not be postponed by duplicate status keep-alives. */
    reset(0);
    GUI_DisplayTextLiteral("alpha", 3);
    uint32 statusCompleted = g_timerGUI;
    GUI_DisplayText("beta", 2);
    unsigned statusFrames = frames;
    g_timerGUI = statusCompleted + 300;
    GUI_DisplayTextLiteral("alpha", 3);
    assert(frames == statusFrames);
    g_timerGUI = statusCompleted + 901;
    poll();
    assert(frames == statusFrames + 1 && !strcmp(displayed, "beta"));
    /* A duplicate during scrolling must not restart the display hold. */
    reset(1);
    GUI_DisplayTextLiteral("alpha", 3);
    g_timerGUI += 300;
    GUI_DisplayTextLiteral("alpha", 3);
    assert(frames == 1 && offsets[0] == 10);
    g_timerGUI++;
    poll();
    assert(frames == 2 && offsets[1] == 9);
    /* Literal input is not interpreted as another format, including on rebuild. */
    reset(0);
    unsigned beforeFormats = formats;
    GUI_DisplayTextLiteral("load 50% %s %n", 3);
    assert(formats == beforeFormats && !strcmp(displayed, "load 50% %s %n"));
    reset(0);
    GUI_DisplayText("load %u%%", 3, 75u);
    assert(formats == beforeFormats + 1 && !strcmp(displayed, "load 75%"));
    char longText[100];
    memset(longText, 'x', sizeof(longText) - 1);
    longText[sizeof(longText) - 1] = '\0';
    reset(0);
    GUI_DisplayTextLiteral(longText, 3);
    assert(strlen(displayed) == 79 && formats == beforeFormats + 1);
#ifdef TOS
    /* Rebuild during scrolling: both visible lines and their moving bounds survive. */
    reset(1);
    GUI_DisplayTextLiteral("alpha", 3);
    finish(1);
    GUI_DisplayTextLiteral("beta long", 8);
    poll();
    g_timerGUI++;
    unsigned upper = glyphRenders[0], lower = glyphRenders[1];
    for (unsigned i = 0; i < 10; i++) {
        g_textDisplayNeedsUpdate = true;
        poll();
        g_timerGUI++;
    }
#ifndef BANNER_NO_RETENTION
    assert(glyphRenders[0] == upper && glyphRenders[1] == lower);
#endif
    /* Clearing the queue does not destroy the cached image of an identical upper line. */
    GUI_DisplayText(NULL, -1);
    g_announcementPhase = 0;
    g_textDisplayNeedsUpdate = true;
    GUI_DisplayTextLiteral("beta long", 3);
#ifndef BANNER_NO_RETENTION
    assert(glyphRenders[0] == upper && glyphRenders[1] == lower);
#endif
    assert(!strcmp(displayed, "beta long"));
    /* The former long upper line and old lower line must be erased completely. */
    GUI_DisplayText(NULL, -1);
    GUI_DisplayTextLiteral("B", 3);
    /* Keep a scroll open while invalidating palette, font, layout and text state. */
    g_announcementPhase = 1;
    GUI_DisplayTextLiteral("changed", 8);
    poll();
    for (unsigned i = 0; i < 9; i++) {
        if (i == 0) { paletteGeneration++; paletteShift++; }
        if (i == 1) g_fontNew8p = &otherFont;
        if (i == 2) otherFont.height = 9;
        if (i == 3) { g_curWidgetXBase = 2; g_curWidgetWidth = 37; }
        if (i == 4) g_colours[4] ^= 1;
        if (i == 5) g_fontCharOffset = -1;
        if (i == 6) { unsupported = true; otherFont.height = 14; }
        if (i == 7) unsupported = false;
        upper = glyphRenders[0]; lower = glyphRenders[1];
        g_textDisplayNeedsUpdate = true;
        g_timerGUI++;
        poll();
        assert(glyphRenders[0] > upper && glyphRenders[1] > lower);
    }
#else
    (void)otherFont;
#endif
    /* Unchanged status skips formatting, but still renews its display hold. */
#ifdef TOS
    g_fontNew8p = &font;
    g_curWidgetXBase = 1; g_curWidgetWidth = 38;
    unsupported = false;
#endif
    reset(0);
    Unit unit = {0};
    unit.o.type = UNIT_TANK;
    Unit_DisplayStatusText(&unit);
    assert(!strcmp(displayed, "Atreides tank."));
    unsigned lookups = stringLookups, oldFrames = frames;
    uint32 completed = g_timerGUI;
    g_timerGUI += 300;
    Unit_DisplayStatusText(&unit);
    assert(stringLookups == lookups && frames == oldFrames);
    g_timerGUI = completed + 901;
    poll();
    assert(frames == oldFrames); /* The fast path extended the hold. */
    unit.house = 1;
    Unit_DisplayStatusText(&unit);
    assert(stringLookups == lookups + 1 && !strcmp(displayed, "Harkonnen tank."));
    lookups = stringLookups;
    GUI_DisplayText(NULL, -1);
    Unit_DisplayStatusText(&unit);
    assert(stringLookups == lookups + 1 && !strcmp(displayed, "Harkonnen tank."));

    /* Queued and replacement messages must prevent the early-out. */
    reset(0);
    Unit_DisplayStatusText(&unit);
    completed = g_timerGUI;
    GUI_DisplayText("notice", 1);
    lookups = stringLookups; oldFrames = frames;
    g_timerGUI += 300;
    Unit_DisplayStatusText(&unit);
    assert(stringLookups == lookups + 1 && frames == oldFrames);
    g_timerGUI = completed + 901;
    poll();
    assert(!strcmp(displayed, "notice")); /* The queued message was not postponed. */
    lookups = stringLookups;
    Unit_DisplayStatusText(&unit);
    assert(stringLookups == lookups + 1 && !strcmp(displayed, "Harkonnen tank."));
    GUI_DisplayText("urgent", 8);
    lookups = stringLookups;
    Unit_DisplayStatusText(&unit);
    assert(stringLookups == lookups + 1 && !strcmp(displayed, "urgent"));
    assert(!strcmp(s_displayTextLine2, "Harkonnen tank."));

    /* A repeated submission during a scroll still follows normal processing. */
    reset(1);
    Unit_DisplayStatusText(&unit);
    lookups = stringLookups;
    Unit_DisplayStatusText(&unit);
    assert(stringLookups == lookups + 1 && frames == 1 && offsets[0] == 10);

    /* Harvester text depends on amount and the resolved state, not movement alone. */
    reset(0);
    unit.o.type = UNIT_HARVESTER; unit.amount = 50; unit.actionID = ACTION_STOP;
    Unit_DisplayStatusText(&unit);
    assert(!strcmp(displayed, "Harkonnen harvester 50% full."));
    lookups = stringLookups;
    unit.o.position++;
    Unit_DisplayStatusText(&unit);
    assert(stringLookups == lookups);
    unit.amount++;
    Unit_DisplayStatusText(&unit);
    assert(!strcmp(displayed, "Harkonnen harvester 51% full."));
    unit.actionID = ACTION_HARVEST; landscape = LST_SPICE;
    Unit_DisplayStatusText(&unit);
    assert(!strcmp(displayed, "Harkonnen harvester 51% harvesting."));
    landscape = LST_ROCK;
    Unit_DisplayStatusText(&unit);
    assert(!strcmp(displayed, "Harkonnen harvester 51% full."));
    unit.actionID = ACTION_MOVE; targetStructure = true;
    Unit_DisplayStatusText(&unit);
    assert(!strcmp(displayed, "Harkonnen harvester 51% returning."));
    unit.o.script.variables[4] = 1;
    lookups = stringLookups;
    Unit_DisplayStatusText(&unit);
    assert(stringLookups == lookups); /* Returning takes precedence over pickup. */
    targetStructure = false;
    Unit_DisplayStatusText(&unit);
    assert(!strcmp(displayed, "Harkonnen harvester 51% waiting."));
    unit.amount = 0;
    Unit_DisplayStatusText(&unit);
    assert(!strcmp(displayed, "Harkonnen harvester empty waiting."));
    reset(0);
    unit.o.type = UNIT_SANDWORM;
    Unit_DisplayStatusText(&unit);
    assert(!strcmp(displayed, "sandworm."));
    lookups = stringLookups;
    unit.house ^= 1;
    Unit_DisplayStatusText(&unit);
    Unit_DisplayStatusText(NULL);
    assert(stringLookups == lookups);
    /* A new gameplay session rebuilds text after the message bar was reset. */
    reset(0);
    unit.o.type = UNIT_TANK; g_config.language = LANGUAGE_FRENCH;
    Unit_DisplayStatusText(&unit);
    assert(!strcmp(displayed, "tank Atreides."));
    return 0;
}
"""
        harness = harness.replace("/* OPTION */", function(config, "Config_ReadAnimationOption")
                                  + function(config, "Config_ReadAnimationPhase")
                                  + function(config, "Config_LoadAnimationPhases"))
        box = gui[gui.index("typedef struct PlanarBox"):
                  gui.index("\n#endif", gui.index("typedef struct PlanarBox"))]
        harness = harness.replace("/* PLANAR BOX */", box)
        video = (ROOT / "src/video/video_atari.c").read_text()
        harness = harness.replace("/* MONO PEN */",
                                  function(video, "Video_Atari_MonoPenWords") + surface_backend(video))
        harness = harness.replace("/* TEXT WRAPPER */", function(gui, "GUI_DrawText_Wrapper"))
        state = gui[gui.index("static uint32 s_displayTextTimer;"):
                    gui.index("\nbool GUI_KeepDisplayTextLiteral")]
        harness = harness.replace("/* ANIMATOR */", state + "\n" + "\n".join(
            function(gui, name) for name in (
                "GUI_KeepDisplayTextLiteral", "GUI_DisplayTextBuffer",
                "GUI_DisplayText", "GUI_DisplayTextLiteral")))
        harness = harness.replace("/* UNIT STATUS */", function(
            (ROOT / "src/unit.c").read_text(), "Unit_DisplayStatusText"))
        with tempfile.TemporaryDirectory(prefix="announcement-phase-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            output = {}
            for platform in ([], ["-DTOS"], ["-DTOS", "-DBANNER_NO_RETENTION"],
                             ["-DTOS", "-DBANNER_MONO"],
                             ["-DTOS", "-DBANNER_MONO", "-DBANNER_NO_RETENTION"],
                             ["-DTOS", "-DBANNER_MONO", "-DMONO_WHITE_IS_ZERO"],
                             ["-DTOS", "-DBANNER_MONO", "-DMONO_WHITE_IS_ZERO", "-DBANNER_NO_RETENTION"]):
                source.write_text(harness.replace(
                    "retain = bannerLines", "retain = false && bannerLines"
                ) if "-DBANNER_NO_RETENTION" in platform else harness)
                subprocess.run(
                    [*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                     "-iquote", str(ROOT / "src"),
                     "-I", str(ROOT / "include"),
                     *flags, *platform, str(source), str(ROOT / "src/video/atari_mono.c"),
                     "-o", str(binary)],
                    check=True
                )
                run = subprocess.run([str(binary)], capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stderr)
                key = tuple(flag for flag in platform if flag != "-DBANNER_NO_RETENTION")
                if "-DBANNER_NO_RETENTION" in platform:
                    self.assertEqual(run.stdout, output[key])
                else:
                    output[key] = run.stdout


if __name__ == "__main__":
    unittest.main()
