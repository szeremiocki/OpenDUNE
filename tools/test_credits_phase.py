"""Verify redraw policies without changing the original credits counting pace."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class CreditsPhaseTest(unittest.TestCase):
    def test_counting_sound_and_redraws(self):
        source = (ROOT / "src/gui/gui.c").read_text()
        credits = function(source, "GUI_DrawCredits")
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int16_t int16;
typedef uint32_t uint32;
typedef int Screen;
enum { SCREEN_0, SCREEN_1, SCREEN_ACTIVE, GUI_SPRITE_COLOUR_EMBEDDED, DRAWSPRITE_FLAG_WIDGETPOS };
enum { SCREEN_WIDTH = 320, SCREEN_HEIGHT = 200 };
static uint16 g_creditsPhase = 1, g_playerCredits;
static uint32 g_timerGUI, s_tickCreditsAnimation;
static Screen active;
typedef struct { uint16 credits; } House;
static House house;
static uint16 currentWidget = 2;
static uint16 g_curWidgetXBase = 32, g_curWidgetYBase = 44;
static uint16 g_curWidgetWidth = 8, g_curWidgetHeight = 9;
static uint8 sprites[24], *g_sprites[24];
static unsigned renders, publishes, hides, shows, sounds, queries;
static uint16 lastShown, lastSound;
static unsigned digits, rollingDigits;
#ifdef TOS
enum {
    CREDITS_CACHE_WIDTH = 64, CREDITS_CACHE_HEIGHT = 9,
    CREDITS_CACHE_GLYPH_SIZE = 8, CREDITS_CACHE_PADDING = 8,
    CREDITS_CACHE_BUFFER_HEIGHT = 24
};
static bool direct, s_creditsCacheReady = true, s_creditsPlanarReady;
static uint16 s_creditsPlanarPaletteGeneration;
static uint16 s_creditsPlanarBackground[64 * 9 / 4];
static uint32 s_creditsBackground[64 * 9 / 4];
static struct { uint16 xBase, yBase, width, height; } g_widgetProperties[6];
static bool Video_Atari_CursorDirect(void) { return direct; }
static uint16 Video_Atari_GetPaletteGeneration(void) { return 0; }
static void GUI_BuildCreditsPlanarCache(uint16 generation) {
    s_creditsPlanarReady = true;
    s_creditsPlanarPaletteGeneration = generation;
}
#endif
static House *House_Get_ByIndex(uint8 id) {
    assert(id == 1);
    queries++;
    return &house;
}
static Screen GFX_Screen_SetActive(Screen screen) {
    Screen old = active;
    active = screen;
    return old;
}
static bool GFX_Screen_IsActive(Screen screen) { return active == screen; }
static uint16 Widget_SetCurrentWidget(uint16 index) {
    uint16 old = currentWidget;
    currentWidget = index;
    return old;
}
static void GUI_Mouse_Hide_InWidget(unsigned index) {
    assert(index == 5);
#ifdef TOS
    if (direct) digits = rollingDigits = 0;
#endif
    hides++;
}
static void GUI_Mouse_Show_InWidget(void) { shows++; }
static void Driver_Sound_Play(uint16 sample, uint16 volume) {
    assert((sample == 52 || sample == 53) && volume == 255);
    sounds++;
    lastSound = sample;
}
static void GUI_DrawSprite(Screen screen, const uint8 *sprite, uint16 id, unsigned colour,
                           int x, int y, uint16 window, unsigned flags) {
    if (screen == SCREEN_ACTIVE) screen = active;
#ifdef TOS
    assert(screen == (direct ? SCREEN_0 : SCREEN_1));
    assert(window == (direct ? 5 : 4));
#else
    assert(screen == SCREEN_1 && window == 4);
#endif
    assert(sprite == g_sprites[id]);
    assert(colour == GUI_SPRITE_COLOUR_EMBEDDED && flags == DRAWSPRITE_FLAG_WIDGETPOS);
    if (id == 12) {
        assert(x == 0 && y == 0);
        renders++;
        digits = rollingDigits = 0;
    } else {
        assert(id >= 13 && id <= 23 && x >= 4 && x <= 54 && (x - 4) % 10 == 0);
        digits++;
        if (y != 1) rollingDigits++;
        if (g_creditsPhase == 0) assert(y == 1);
    }
}
static void GUI_Screen_Copy(int xs, int ys, int xd, int yd, int width, int height,
                           Screen src, Screen dst) {
    if (src == SCREEN_ACTIVE) src = active;
    assert(xs == 32 && xd == 32 && ys == 44 && yd == 4 && width == 8 && height == 9);
    assert(src == SCREEN_1 && dst == SCREEN_0 && digits >= 6);
    if (g_creditsPhase == 0) assert(digits == 6 && rollingDigits == 0);
    publishes++;
    lastShown = g_playerCredits;
}
#ifdef TOS
#define lengthof(a) (sizeof(a) / sizeof((a)[0]))
/* FORMAT */
static void GUI_DrawCreditsPlanarRows(uint16 *pixels, unsigned pos, unsigned glyph,
                                     unsigned sourceRow, unsigned top, unsigned height) {
    (void)pixels;
    assert(pos < 6 && glyph < 11 && height <= 8);
    digits++;
    if (sourceRow != 0 || top != 1 || height != 8) rollingDigits++;
    if (g_creditsPhase == 0) assert(sourceRow == 0 && top == 1 && height == 8);
}
static void GUI_DrawCreditsGlyph(uint8 *buffer, unsigned glyph, unsigned left, int top) {
    (void)buffer;
    assert(glyph < 11 && left >= 4 && left <= 54);
    digits++;
    if (top != CREDITS_CACHE_PADDING + 1) rollingDigits++;
    if (g_creditsPhase == 0) assert(top == CREDITS_CACHE_PADDING + 1);
}
static void GUI_DrawSprite_BeginOpaqueBatch(uint8 *buffer, unsigned x, unsigned y,
                                           unsigned width, unsigned height) {
    (void)buffer;
    assert(direct && x == g_widgetProperties[5].xBase * 8 && y == 4);
    assert(width == 64 && height == 9);
}
static void GUI_DrawSprite_EndBatch(void) {
    if (s_creditsCacheReady) renders++;
    publishes++;
    lastShown = g_playerCredits;
    if (g_creditsPhase == 0) assert(digits == 6 && rollingDigits == 0);
}
static bool Video_Atari_PresentRestore(unsigned x, unsigned y, unsigned width, unsigned height,
                                      const uint8 *buffer) {
    (void)buffer;
    assert(direct && x == 256 && y == 4 && width == 64 && height == 9);
    renders++;
    publishes++;
    lastShown = g_playerCredits;
    if (g_creditsPhase == 0) assert(digits == 6 && rollingDigits == 0);
    return true;
}
#define Warning(...) assert(false)
#endif
/* CREDITS */
/* Independent reference for the original numeric accumulator and sound gate. */
static uint16 reference(uint16 *animation, int16 *offset, uint16 target, bool *sound) {
    int16 diff = target - *animation;
    *sound = false;
    if (diff != 0) {
        int16 step = diff / 4;
        if (step == 0) step = diff < 0 ? -1 : 1;
        if (step > 128) step = 128;
        if (step < -128) step = -128;
        *offset += step;
    } else {
        *offset = 0;
    }
    if (diff != 0 && (*offset < -7 || *offset > 7)) *sound = true;
    if (*offset < 0 && *animation == 0) *offset = 0;
    *animation += *offset / 8;
    if (*offset > 0) *offset &= 7;
    if (*offset < 0) *offset = -((-*offset) & 7);
    return *animation - (*offset < 0 && *animation > 0 ? 1 : 0);
}
int main(void) {
    for (unsigned i = 0; i < 24; i++) g_sprites[i] = &sprites[i];
    const uint16 pairs[][2] = {
        {100, 132}, {132, 100}, {0, 1}, {1, 0},
        {999, 1000}, {1000, 999}, {100, 3000}, {3000, 100},
        {65534, 65535}, {65535, 65534}
    };
    for (unsigned backend = 0; backend < 4; backend++) {
#ifdef TOS
        direct = backend != 0;
        s_creditsCacheReady = backend != 3;
        g_widgetProperties[5].xBase = backend == 2 ? 33 : 32;
        g_widgetProperties[5].yBase = 4;
        g_widgetProperties[5].width = 8;
        g_widgetProperties[5].height = 9;
#else
        (void)backend;
#endif
    for (unsigned phase = 0; phase <= 2; phase++) {
        g_creditsPhase = phase;
        for (unsigned pair = 0; pair < sizeof(pairs) / sizeof(*pairs); pair++) {
            house.credits = pairs[pair][0];
            g_timerGUI = s_tickCreditsAnimation = 0;
            active = SCREEN_0; currentWidget = 2;
            GUI_DrawCredits(1, 2);
            assert(g_playerCredits == house.credits && lastShown == house.credits);
            uint16 expectedAnimation = house.credits, previousShown = house.credits;
            int16 expectedOffset = 0;
            unsigned startRenders = renders, eligible = 0, requiredPlain = 0;
            unsigned skipped = 0, pendingSkips = 0;
            house.credits = pairs[pair][1];
            unsigned tick;
            for (tick = 0; tick < 4096; tick++) {
                bool sound;
                bool settledBefore = expectedAnimation == house.credits && expectedOffset == 0;
                uint16 expected = reference(&expectedAnimation, &expectedOffset, house.credits, &sound);
                unsigned beforeSounds = sounds, beforePublishes = publishes, beforeQueries = queries;
                g_timerGUI++;
                GUI_DrawCredits(1, 0);
                assert(g_playerCredits == expected);
                assert(sounds == beforeSounds + sound);
                if (sound) assert(lastSound == (pairs[pair][1] > pairs[pair][0] ? 52 : 53));
                assert(queries == beforeQueries + 1);
                assert(active == SCREEN_0 && currentWidget == 2 && hides == shows);
                if (!settledBefore) eligible++;
                if (expected != previousShown) requiredPlain++;
                if (phase == 0) {
                    assert(publishes == beforePublishes + (expected != previousShown));
                } else if (phase == 1) {
                    assert(publishes == beforePublishes + !settledBefore);
                } else if (!settledBefore) {
                    bool settled = expectedAnimation == house.credits && expectedOffset == 0;
                    if (settled) assert(publishes == beforePublishes + 1);
                    else if (pendingSkips == 0) {
                        assert(publishes == beforePublishes + 1);
                        pendingSkips = 1;
                    } else {
                        assert(publishes == beforePublishes);
                        pendingSkips = 0;
                        skipped++;
                    }
                }
                previousShown = expected;
                /* Calls in the same GUI tick neither count nor draw again. */
                beforeSounds = sounds; beforePublishes = publishes; beforeQueries = queries;
                GUI_DrawCredits(1, 0);
                assert(g_playerCredits == expected && sounds == beforeSounds);
                assert(publishes == beforePublishes && queries == beforeQueries);
                if (expectedAnimation == house.credits && expectedOffset == 0) break;
            }
            assert(tick < 4096 && g_playerCredits == house.credits && lastShown == house.credits);
            if (phase == 0) assert(renders - startRenders == requiredPlain);
            if (phase == 1) assert(renders - startRenders == eligible);
            if (phase == 2) assert(renders - startRenders == eligible - skipped);
            /* Forced redraws are never lost to the alternate-frame policy. */
            unsigned before = renders;
            GUI_DrawCredits(1, 1);
            assert(renders == before + 1 && lastShown == house.credits);
            GUI_DrawCredits(1, 2);
            assert(renders == before + 2 && lastShown == house.credits);
        }
    }
    }
    return 0;
}
"""
        harness = harness.replace("/* CREDITS */", credits)
        harness = harness.replace("/* FORMAT */", function(source, "GUI_FormatCredits"))
        with tempfile.TemporaryDirectory(prefix="credits-phase-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            for platform in ([], ["-DTOS"]):
                subprocess.run(
                    [*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                     *flags, *platform, str(source), "-o", str(binary)],
                    check=True
                )
                subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
