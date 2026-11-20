"""Exercise factory scrolling without a maintained chunky SCREEN_0."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class FactoryScrollTest(unittest.TestCase):
    def test_scroll_source_and_arrow_navigation(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        clicks = (ROOT / "src/gui/widget_click.c").read_text()
        init = function(gui, "GUI_FactoryWindow_Init")
        capture = init.index("s_factoryWindowBackgroundColour = GFX_GetPixel(72, 23)")
        self.assertLess(init.index("GFX_Screen_SetActive(SCREEN_1)"), capture)
        self.assertLess(capture, init.index("GUI_FactoryWindow_PrepareScrollList()"))
        production = "\n".join([
            function(gui, "GUI_FactoryWindow_GetItem"),
            function(gui, "GUI_FactoryWindow_PrepareScrollList"),
            function(gui, "GUI_FactoryWindow_PresentScrollFrame"),
            function(gui, "GUI_FactoryWindow_B495_0F30"),
            function(clicks, "GUI_FactoryWindow_ScrollList"),
            function(clicks, "GUI_Production_FinishNavigation"),
            function(clicks, "GUI_Production_Down_Click"),
            function(clicks, "GUI_Production_Up_Click"),
        ])
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int16_t int16;
#ifdef TOS
typedef uint32_t uint32;
#endif
enum { SCREEN_WIDTH = 320, SCREEN_HEIGHT = 200 };
typedef enum { SCREEN_0, SCREEN_1 } Screen;
enum { GUI_SPRITE_COLOUR_EMBEDDED = 0, DRAWSPRITE_FLAG_REMAP = 1 };
typedef struct { int available; uint16 spriteID; } ObjectInfo;
typedef struct { ObjectInfo *objectInfo; } FactoryWindowItem;
typedef struct { int unused; } Widget;
static uint8 screens[2][320 * 200], visible[320 * 200];
static uint8 before[320 * 200], spriteData[10][32 * 24];
static uint8 *g_sprites[10];
static ObjectInfo objects[10];
static FactoryWindowItem g_factoryWindowItems[10];
static uint16 g_factoryWindowBase, g_factoryWindowSelected, g_factoryWindowTotal;
static uint16 g_timerTimeout;
static uint8 s_factoryWindowGraymapTbl[256], s_factoryWindowBackgroundColour;
static Screen active;
static unsigned mouseHides, frames, detailsDraws;
static uint16 detailsTimeout;
static int animationStep, animationBase;
static bool native;

static uint8 *display(void) { return native ? visible : screens[SCREEN_0]; }
#ifdef TOS
static bool s_factoryScrollPlanarReady;
static uint32 g_timerSleep;
static uint16 paletteGeneration;
static unsigned encodes;
static const uint16 *planarBase;
static uint8 planarSource[200][48];
static bool Video_Atari_CursorDirect(void) { return native; }
static uint16 Video_Atari_GetPaletteGeneration(void) { return paletteGeneration; }
static void *GFX_Screen_Get_ByIndex(Screen screen) { return screens[screen]; }
static void Video_Atari_EncodePlanarStrided(const uint8 *src, uint16 stride, uint16 *pixels,
                                           uint16 width, uint16 height) {
    assert(native && src == screens[SCREEN_1] + 64);
    assert(width == 48 && height == 200 && stride == 320);
    encodes++;
    planarBase = pixels;
    for (unsigned y = 0; y < height; y++) memcpy(planarSource[y], src + y * stride, width);
}
#endif
static Screen GFX_Screen_SetActive(Screen screen) {
    Screen old = active; active = screen; return old;
}
static void GUI_Mouse_Hide_Safe(void) { mouseHides++; }
static void GUI_Mouse_Show_Safe(void) { assert(mouseHides); mouseHides--; }
static void GUI_DrawFilledRectangle(int left, int top, int right, int bottom, uint8 colour) {
    assert(active == SCREEN_1);
    assert(left == 72 && right == 103);
    assert(top == 0 && bottom == 199);
    for (int y = top; y <= bottom; y++)
        memset(screens[active] + y * 320 + left, colour, right - left + 1);
}
static void GUI_DrawSprite(Screen screen, const uint8 *sprite, uint16 spriteID,
                           int house, int x, int y, int window, int flags, ...) {
    assert(active == SCREEN_1 && screen == SCREEN_1 && sprite == g_sprites[spriteID]);
    assert(house == GUI_SPRITE_COLOUR_EMBEDDED && window == 0 && x == 72);
    assert(y >= 8 && y + 24 <= 192);
    const uint8 *remap = NULL;
    if (flags) {
        va_list args;
        va_start(args, flags);
        remap = va_arg(args, const uint8 *);
        assert(remap == s_factoryWindowGraymapTbl && va_arg(args, int) == 1);
        va_end(args);
    }
    assert((objects[spriteID].available == -1) == (flags == DRAWSPRITE_FLAG_REMAP));
    for (int row = 0; row < 24; row++)
        for (int col = 0; col < 32; col++) {
            uint8 value = sprite[row * 32 + col];
            if (value)
                screens[screen][(y + row) * 320 + x + col] = remap ? remap[value] : value;
        }
}
static uint8 icon_pixel(int item, int x, int y) {
    if (item < 0 || item >= g_factoryWindowTotal)
        return s_factoryWindowBackgroundColour;
    uint8 value = spriteData[item][y * 32 + x];
    if (!value) return s_factoryWindowBackgroundColour;
    return objects[item].available == -1 ? s_factoryWindowGraymapTbl[value] : value;
}
static uint8 strip_pixel(int base, int x, int y) {
    for (int slot = -1; slot <= 4; slot++) {
        int top = (slot + 1) * 32 + 8;
        if (y >= top && y < top + 24) return icon_pixel(base + slot, x, y - top);
    }
    return s_factoryWindowBackgroundColour;
}
#ifdef TOS
static bool Video_Atari_PresentPlanarSubRect(const uint16 *pixels, uint16 stride, uint16 srcX,
                                           uint16 x, uint16 y, uint16 width, uint16 height) {
    assert(native && stride == 24 && srcX == 8 && x == 72 && y == 16);
    assert(width == 32 && height == 136);
    assert((pixels - planarBase) % 12 == 0);
    unsigned sourceY = (pixels - planarBase) / 12;
    assert(sourceY <= 64);
    if (animationStep) {
        frames++;
        assert((int)sourceY == 32 + animationStep * 2 * (int)frames);
    }
    for (unsigned row = 0; row < height; row++) {
        for (unsigned col = 0; col < width; col++) {
            uint8 pixel = planarSource[sourceY + row][srcX + col];
            uint8 expected = strip_pixel(animationStep ? animationBase : g_factoryWindowBase,
                                          col, sourceY + row);
            assert(pixel == expected);
            display()[(y + row) * 320 + x + col] = pixel;
        }
    }
    return true;
}
static void Warning(const char *msg) { (void)msg; assert(false); }
#endif
static void GFX_Screen_Copy2(int xs, int ys, int xd, int yd, int w, int h,
                             Screen source, Screen destination, bool skipNull) {
    assert(!native);
    assert(source == SCREEN_1 && destination == SCREEN_0 && !skipNull);
    assert(xs == 72 && xd == 72 && yd == 16 && w == 32 && h == 136);
    if (animationStep) {
        frames++;
        assert(ys == 32 + animationStep * (native ? 2 : 1) * (int)frames);
        for (int y = 0; y < h; y++)
            for (int x = 0; x < w; x++)
                assert(screens[source][(ys + y) * 320 + xs + x] ==
                       strip_pixel(animationBase, x, ys + y));
    }
    for (int y = 0; y < h; y++)
        memcpy(display() + (yd + y) * 320 + xd,
               screens[source] + (ys + y) * 320 + xs, w);
}
static void GUI_DrawWiredRectangle(int left, int top, int right, int bottom, uint8 colour) {
    assert(active == SCREEN_0 && left == 71 && right == 104);
    for (int x = left; x <= right; x++)
        display()[top * 320 + x] = display()[bottom * 320 + x] = colour;
    for (int y = top; y <= bottom; y++)
        display()[y * 320 + left] = display()[y * 320 + right] = colour;
}
static void GUI_FactoryWindow_UpdateSelection(bool changed) {
    if (changed) {
        int y = g_factoryWindowSelected * 32 + 24;
        GUI_DrawWiredRectangle(71, y - 1, 104, y + 24, 255);
    }
}
static void GUI_FactoryWindow_DrawDetails(void) {
    assert(g_factoryWindowBase + g_factoryWindowSelected < g_factoryWindowTotal);
    detailsDraws++;
    detailsTimeout = g_timerTimeout;
}
static void GUI_Widget_MakeNormal(Widget *widget, bool draw) {
    assert(widget && !draw);
}
static void sleepIdle(void) {
#ifdef TOS
    g_timerSleep++;
#endif
    if (g_timerTimeout) g_timerTimeout--;
}
/* PRODUCTION */
static void check_source(void) {
    assert(active == SCREEN_0 && mouseHides == 0);
    for (int y = 0; y < 200; y++)
        for (int x = 0; x < 320; x++)
            if (x >= 72 && x <= 103)
                assert(screens[SCREEN_1][y * 320 + x] == strip_pixel(g_factoryWindowBase, x - 72, y));
            else
                assert(screens[SCREEN_1][y * 320 + x] == before[y * 320 + x]);
    if (native)
        for (unsigned i = 0; i < sizeof(screens[SCREEN_0]); i++)
            assert(screens[SCREEN_0][i] == 0xa5);
}
static void check_display(void) {
    int top = g_factoryWindowSelected * 32 + 23;
    int bottom = top + 25;
    int left = 71, right = 104;
    for (int y = 16; y < 152; y++) {
        assert(display()[y * 320 + left - 1] == 0x5a);
        assert(display()[y * 320 + right + 1] == 0x5a);
        for (int x = left; x <= right; x++) {
            uint8 expected = s_factoryWindowBackgroundColour;
            if (x >= 72 && x <= 103)
                expected = strip_pixel(g_factoryWindowBase, x - 72, y + 16);
            if (x >= 71 && x <= 104 &&
                ((y == top || y == bottom) ||
                 ((x == 71 || x == 104) && y >= top && y <= bottom)))
                expected = 255;
            assert(display()[y * 320 + x] == expected);
        }
    }
    assert(display()[0] == 0x5a && display()[320 * 200 - 1] == 0x5a);
}
static void click(bool down) {
    Widget widget = {0};
    int oldBase = g_factoryWindowBase;
    int oldSelected = g_factoryWindowSelected;
    animationBase = oldBase;
    animationStep = 0;
    if (down && oldSelected == 3 && oldBase + 4 < g_factoryWindowTotal)
        animationStep = 1;
    if (!down && oldSelected == 0 && oldBase != 0)
        animationStep = -1;
    frames = 0;
    detailsDraws = 0;
#ifdef TOS
    unsigned beforeEncodes = encodes;
#endif
    assert(down ? GUI_Production_Down_Click(&widget) : GUI_Production_Up_Click(&widget));
#ifdef TOS
    assert(encodes == beforeEncodes + (native && animationStep != 0));
#endif
    assert(frames == (animationStep ? (native ? 16u : 32u) : 0u));
    assert((int)g_factoryWindowBase == oldBase + animationStep);
    int expected = oldSelected;
    if (!animationStep) {
        if (down && oldSelected < 3 && oldBase + oldSelected + 1 < g_factoryWindowTotal)
            expected++;
        if (!down && oldSelected > 0) expected--;
    }
    assert(g_factoryWindowSelected == expected);
    assert(detailsDraws == 1);
    if (!animationStep && expected != oldSelected)
        assert(native ? detailsTimeout > 0 : detailsTimeout == 0);
    assert(g_timerTimeout == 0);
    check_source();
    check_display();
}
int main(void) {
#if defined(TOS) && !defined(NO_DIRECT)
    native = true;
#endif
    s_factoryWindowBackgroundColour = 17;
    for (int i = 0; i < 256; i++) s_factoryWindowGraymapTbl[i] = 255 - i;
    for (int item = 0; item < 10; item++) {
        objects[item] = (ObjectInfo){ item % 3 == 1 ? -1 : 1, item };
        g_factoryWindowItems[item].objectInfo = &objects[item];
        g_sprites[item] = spriteData[item];
        for (int y = 0; y < 24; y++)
            for (int x = 0; x < 32; x++)
                spriteData[item][y * 32 + x] =
                    (x == 0 || x == 31 || (x + y + item) % 7 == 0) ? 0 :
                    20 + (item * 13 + x + y * 2) % 200;
    }
    const unsigned totals[] = {1, 4, 5, 9};
    for (unsigned test = 0; test < sizeof(totals) / sizeof(totals[0]); test++) {
        g_factoryWindowTotal = totals[test];
        g_factoryWindowBase = g_factoryWindowSelected = 0;
        active = SCREEN_0;
        memset(screens[SCREEN_0], 0xa5, sizeof(screens[SCREEN_0]));
        memset(screens[SCREEN_1], 0x6b, sizeof(screens[SCREEN_1]));
        memcpy(before, screens[SCREEN_1], sizeof(before));
        memset(display(), 0x5a, sizeof(visible));
        for (int y = 16; y < 152; y++)
            memset(display() + y * 320 + 71, s_factoryWindowBackgroundColour, 34);
        animationStep = 0;
        GUI_FactoryWindow_PrepareScrollList();
        GUI_FactoryWindow_PresentScrollFrame(32);
#ifdef TOS
        if (native) {
            unsigned beforeEncodes = encodes;
            GUI_FactoryWindow_PresentScrollFrame(32);
            assert(encodes == beforeEncodes);
            paletteGeneration++;
            GUI_FactoryWindow_PresentScrollFrame(32);
            assert(encodes == beforeEncodes + 1);
            GUI_FactoryWindow_PrepareScrollList();
        }
#endif
        GUI_FactoryWindow_UpdateSelection(true);
        check_source();
        check_display();
        for (unsigned i = 0; i < g_factoryWindowTotal + 3u; i++) click(true);
        for (unsigned i = 0; i < g_factoryWindowTotal + 3u; i++) click(false);
        assert(g_factoryWindowBase == 0 && g_factoryWindowSelected == 0);
    }
    return 0;
}
"""
        harness = harness.replace("/* PRODUCTION */", production)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "factory.c"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("HOST_CC", "cc"))
            for name, flags in (
                ("factory", []),
                ("factory-tos", ["-DTOS"]),
                ("factory-tos-chunky", ["-DTOS", "-DNO_DIRECT"]),
            ):
                binary = Path(directory) / name
                subprocess.run(
                    compiler + ["-std=c17", "-O1", "-g", "-Wall", "-Wextra",
                                "-Werror", "-fsanitize=address,undefined",
                                "-fno-pie", "-no-pie"] +
                    flags + [str(source), "-o", str(binary)],
                    check=True,
                )
                subprocess.run([str(binary)], check=True)
