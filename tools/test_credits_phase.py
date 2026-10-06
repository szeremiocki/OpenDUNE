"""Verify counting, legacy MIDI cadence and publication-gated ST/STE clicks."""

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
        start = source.index("typedef struct GUI_CreditsDisplay")
        display = source[start:source.index("} GUI_CreditsDisplay;", start) + len("} GUI_CreditsDisplay;")]
        renderer = function(source, "GUI_DrawCredits")
        self.assertNotIn("g_creditsPhase", renderer)
        credits = "\n".join((display, function(source, "GUI_UpdateCreditsAnimation"), renderer))
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
static unsigned ymSounds;
static bool ymIncreasing;
static uint16 lastShown, lastSound;
static unsigned digits, rollingDigits;
static int drawnRows[6][9], expectedRows[6][9];
static void clear_rows(void) {
    for (unsigned pos = 0; pos < 6; pos++)
        for (unsigned row = 0; row < 9; row++) drawnRows[pos][row] = -1;
}
static void draw_rows(unsigned pos, unsigned glyph, int top, unsigned source, unsigned height) {
    assert(pos < 6 && glyph < 11 && source + height <= 8);
    for (unsigned row = 0; row < height; row++)
        if (top + (int)row >= 0 && top + (int)row < 9)
            drawnRows[pos][top + row] = glyph * 8 + source + row;
}
static void check_rows(void) { assert(!memcmp(drawnRows, expectedRows, sizeof(drawnRows))); }
#ifdef TOS
enum {
    CREDITS_CACHE_WIDTH = 64, CREDITS_CACHE_HEIGHT = 9,
    CREDITS_CACHE_GLYPH_SIZE = 8, CREDITS_CACHE_PADDING = 8,
    CREDITS_CACHE_BUFFER_HEIGHT = 24
};
static bool direct, s_creditsCacheReady = true, s_creditsPlanarReady;
static uint16 s_creditsPlanarPaletteGeneration, paletteGeneration;
static unsigned planarBytes;
static uint16 s_creditsPlanarBackground[64 * 9 / 4];
static uint16 s_creditsPlanarDisplay[64 * 9 / 4], s_creditsPlanarMasks[6][2];
static bool s_creditsPlanarDisplayReady, planarPublished;
static bool presentFailure;
static unsigned warnings;
static uint16 s_creditsPlanarDisplayX, s_creditsPlanarDisplayY;
static uint32 s_creditsBackground[64 * 9 / 4];
static struct { uint16 xBase, yBase, width, height; } g_widgetProperties[6];
static unsigned directQueries;
static bool Video_Atari_CursorDirect(void) { directQueries++; return direct; }
static uint16 Video_Atari_GetPaletteGeneration(void) { return paletteGeneration; }
static void GUI_BuildCreditsPlanarCache(uint16 generation) {
    s_creditsPlanarReady = true;
    s_creditsPlanarPaletteGeneration = generation;
    s_creditsPlanarDisplayReady = false;
    for (unsigned pos = 0; pos < 6; pos++) {
        unsigned shift = (pos * 10 + 4) & 15;
        s_creditsPlanarMasks[pos][0] = 0xff00u >> shift;
        s_creditsPlanarMasks[pos][1] = shift > 8 ? (uint16)(0xff00u << (16 - shift)) : 0;
    }
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
    if (direct) {
        digits = rollingDigits = 0;
        if (!s_creditsCacheReady || (g_widgetProperties[5].xBase & 1)) clear_rows();
        planarPublished = false;
        planarBytes = 0;
    }
#endif
    hides++;
}
static void GUI_Mouse_Show_InWidget(void) {
#ifdef TOS
    if (planarPublished) {
        renders++;
        publishes++;
        lastShown = g_playerCredits;
        planarPublished = false;
    }
#endif
    shows++;
}
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
        clear_rows();
    } else {
        assert(id >= 13 && id <= 23 && x >= 4 && x <= 54 && (x - 4) % 10 == 0);
        digits++;
        if (y != 1) rollingDigits++;
        if (g_creditsPhase == 0) assert(y == 1);
        draw_rows((x - 4) / 10, id - 13, y, 0, 8);
    }
}
static void GUI_Screen_Copy(int xs, int ys, int xd, int yd, int width, int height,
                           Screen src, Screen dst) {
    if (src == SCREEN_ACTIVE) src = active;
    assert(xs == 32 && xd == 32 && ys == 44 && yd == 4 && width == 8 && height == 9);
    assert(src == SCREEN_1 && dst == SCREEN_0 && digits >= 6);
    if (g_creditsPhase == 0) assert(digits == 6 && rollingDigits == 0);
    check_rows();
    publishes++;
    lastShown = g_playerCredits;
}
#ifdef TOS
#define lengthof(a) (sizeof(a) / sizeof((a)[0]))
/* FORMAT */
static void Driver_Sound_PlayCredits(bool increasing) {
    assert(direct);
    if (s_creditsCacheReady && !(g_widgetProperties[5].xBase & 1)) assert(planarPublished);
    ymSounds++;
    ymIncreasing = increasing;
}
static void GUI_DrawCreditsPlanarRows(uint16 *pixels, unsigned pos, unsigned glyph,
                                     unsigned sourceRow, unsigned top, unsigned height) {
    (void)pixels;
    assert(pos < 6 && glyph < 11 && height <= 8);
    digits++;
    if (sourceRow != 0 || top != 1 || height != 8) rollingDigits++;
    if (g_creditsPhase == 0) assert(sourceRow == 0 && top == 1 && height == 8);
    if (top == 1 && sourceRow == 0 && height == 8) drawnRows[pos][0] = -1;
    draw_rows(pos, glyph, top, sourceRow, height);
}
static void GUI_DrawCreditsGlyph(uint8 *buffer, unsigned glyph, unsigned left, int top) {
    (void)buffer;
    assert(glyph < 11 && left >= 4 && left <= 54);
    digits++;
    if (top != CREDITS_CACHE_PADDING + 1) rollingDigits++;
    if (g_creditsPhase == 0) assert(top == CREDITS_CACHE_PADDING + 1);
    draw_rows((left - 4) / 10, glyph, top - CREDITS_CACHE_PADDING, 0, 8);
}
static void GUI_DrawSprite_BeginOpaqueBatch(uint8 *buffer, unsigned x, unsigned y,
                                           unsigned width, unsigned height) {
    (void)buffer;
    assert(direct && x == g_widgetProperties[5].xBase * 8 && y == g_widgetProperties[5].yBase);
    assert(width == 64 && height == 9);
}
static void GUI_DrawSprite_EndBatch(void) {
    if (s_creditsCacheReady) renders++;
    publishes++;
    lastShown = g_playerCredits;
    if (g_creditsPhase == 0) assert(digits == 6 && rollingDigits == 0);
    check_rows();
}
static bool Video_Atari_PresentRestoreStrided(unsigned x, unsigned y, unsigned width, unsigned height,
                                             const uint8 *buffer, unsigned stride) {
    unsigned left = g_widgetProperties[5].xBase * 8;
    assert(direct && x >= left && x < left + 64 && !(x & 15) && y == g_widgetProperties[5].yBase);
    assert(width && !(width & 15) && x + width <= left + 64 && height == 9 && stride == 32);
    assert(buffer == (const uint8 *)(s_creditsPlanarDisplay + (x - left) / 4));
    if (presentFailure) return false;
    planarBytes += width * height / 2;
    planarPublished = true;
    if (g_creditsPhase == 0) assert(rollingDigits == 0);
    check_rows();
    return true;
}
#define Warning(...) (warnings++)
/* PLANAR */
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
static uint16 expectedAnimation;
static int16 expectedOffset;
static uint32 expectedTick;
static uint16 previousOld, previousNew;
static int previousScroll;
static bool previousValid;
static unsigned suppressed, negativeSteps, positiveSteps;
static uint16 expectedPublishedCredits;
static bool expectedPublishedValid;
static void step(uint16 mode) {
    unsigned beforeSounds = sounds, beforePublishes = publishes, beforeQueries = queries;
    unsigned beforeYM = ymSounds;
#ifdef TOS
    unsigned beforeDirect = directQueries;
#endif
    bool blocked = mode == 0 && expectedTick > g_timerGUI;
    bool eligible = false, sound = false;
    uint16 expected = expectedAnimation - (expectedOffset < 0 && expectedAnimation > 0);
    int16 diff = house.credits - expectedAnimation;
    if (!blocked) {
        expectedTick = g_timerGUI + 1;
        if (mode == 2) expectedAnimation = house.credits;
        eligible = mode != 0 || expectedAnimation != house.credits || expectedOffset != 0;
        if (eligible) expected = reference(&expectedAnimation, &expectedOffset, house.credits, &sound);
    }
    uint16 lower = expectedAnimation, higher = lower;
    int scroll = 0;
    if (g_creditsPhase == 0) {
        lower = higher = expected;
    } else {
        unsigned magnitude = expectedOffset < 0 ? -expectedOffset : expectedOffset;
        if (g_creditsPhase == 2) magnitude &= ~1u;
        if (magnitude != 0) {
            if (expectedOffset < 0) {
                if (lower > 0) lower--;
                scroll = -(int)magnitude;
            } else {
                higher++;
                scroll = magnitude;
            }
        }
    }
    bool settled = expectedAnimation == house.credits && expectedOffset == 0;
    bool publish = eligible && (mode != 0 || settled || !previousValid ||
        lower != previousOld || higher != previousNew || scroll != previousScroll);
    char oldText[7], newText[7];
    snprintf(oldText, sizeof(oldText), "%6hu", lower);
    snprintf(newText, sizeof(newText), "%6hu", higher);
    for (unsigned pos = 0; pos < 6; pos++)
        for (unsigned row = 0; row < 9; row++) {
            int sourceRow = (int)row - 1;
            char glyph = oldText[pos];
            expectedRows[pos][row] = -1;
            if (oldText[pos] != newText[pos]) {
                sourceRow = (int)row - (scroll < 0 ? -7 : 1) + scroll;
                assert(sourceRow >= 0 && sourceRow < 16);
                if (sourceRow >= 8) {
                    sourceRow -= 8;
                    glyph = newText[pos];
                }
            }
            if (sourceRow >= 0)
                expectedRows[pos][row] = (glyph == ' ' ? 0 : glyph - '0' + 1) * 8 + sourceRow;
        }
    bool screenPublish = publish;
    bool midiSound = sound, ymSound = false;
    uint16 anchor = scroll < 0 ? higher : lower;
#ifdef TOS
    midiSound = sound && !direct;
    if (direct && s_creditsCacheReady && !(g_widgetProperties[5].xBase & 1) && mode == 0)
        screenPublish = publish && memcmp(drawnRows, expectedRows, sizeof(drawnRows)) != 0;
    if (direct && s_creditsCacheReady && !(g_widgetProperties[5].xBase & 1) && presentFailure)
        screenPublish = false;
    ymSound = direct && screenPublish && mode == 0 && expectedPublishedValid &&
              anchor != expectedPublishedCredits;
#endif
    GUI_DrawCredits(1, mode);
    assert(g_playerCredits == expected && sounds == beforeSounds + midiSound);
    if (midiSound) assert(lastSound == (diff > 0 ? 52 : 53));
    assert(ymSounds == beforeYM + ymSound);
    if (ymSound) assert(ymIncreasing == (anchor > expectedPublishedCredits));
    assert(publishes == beforePublishes + screenPublish);
    assert(queries == beforeQueries + !blocked);
    assert(active == SCREEN_0 && currentWidget == 2 && hides == shows);
#ifdef TOS
    /* Original sound boundaries select MIDI/PSG; rendering selects only on publications. */
    assert(directQueries == beforeDirect + publish + sound);
    if (direct && screenPublish) {
        expectedPublishedCredits = anchor;
        expectedPublishedValid = true;
    }
#else
    (void)anchor;
    (void)expectedPublishedCredits;
    (void)expectedPublishedValid;
#endif
    if (publish) {
        previousOld = lower; previousNew = higher; previousScroll = scroll;
        previousValid = true;
        if (g_creditsPhase == 2) {
            assert(scroll % 2 == 0);
            negativeSteps += scroll < 0;
            positiveSteps += scroll > 0;
        }
    } else if (eligible) {
        suppressed++;
    }
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
        for (unsigned scenario = 0; scenario < 2; scenario++)
        for (unsigned pair = 0; pair < sizeof(pairs) / sizeof(*pairs); pair++) {
            house.credits = pairs[pair][0];
            g_timerGUI = s_tickCreditsAnimation = 0;
            expectedTick = 0; previousValid = false;
            active = SCREEN_0; currentWidget = 2;
            step(2);
            assert(g_playerCredits == house.credits && lastShown == house.credits);
            unsigned startPublishes = publishes;
            house.credits = pairs[pair][1];
            unsigned tick;
            for (tick = 0; tick < 4096; tick++) {
                if (scenario == 1) {
                    if (tick == 3) house.credits = pairs[pair][0];
                    if (tick == 10) house.credits = pairs[pair][1];
                    if (tick == 15) house.credits = pairs[pair][0];
                    if (tick == 20) house.credits = pairs[pair][1];
                }
                g_timerGUI++;
                step(0);
                /* Calls in the same GUI tick neither count nor draw again. */
                step(0);
                if (scenario == 1 && tick == 7) step(1);
                if ((scenario == 0 || tick >= 20) &&
                    expectedAnimation == house.credits && expectedOffset == 0) break;
            }
            assert(tick < 4096 && g_playerCredits == house.credits && lastShown == house.credits);
            if (scenario == 0 && (pair == 2 || pair == 3)) {
                /* A one-credit transition takes eight ticks, in either direction. */
                assert(tick == 7);
                if (phase == 1) assert(publishes - startPublishes == 8);
                if (phase == 2) assert(publishes - startPublishes == 4);
            }
            /* Forced redraws and resets bypass visual-state deduplication. */
            unsigned before = renders;
            step(1);
            assert(renders == before + 1 && lastShown == house.credits);
            step(2);
            assert(renders == before + 2 && lastShown == house.credits);
            /* Change policy mid-transition without changing numeric progress. */
            house.credits = pairs[pair][0];
            for (unsigned update = 0; update < 24; update++) {
                g_creditsPhase = update % 3;
                g_timerGUI++;
                step(0);
                if (update == 12) step(2);
            }
            g_creditsPhase = phase;
            step(2);
        }
    }
    }
#ifdef TOS
    /* Geometry, palette and fallback changes force complete retained-image rebuilds. */
    direct = s_creditsCacheReady = true;
    g_widgetProperties[5].xBase = 32;
    g_creditsPhase = 1;
    house.credits = 12345;
    step(2);
    assert(planarBytes == 288);
    house.credits += 1000;
    g_widgetProperties[5].xBase = 30;
    g_widgetProperties[5].yBase = 6;
    g_timerGUI++;
    step(0);
    assert(planarBytes == 288 && digits >= 6);
    paletteGeneration++;
    g_timerGUI++;
    step(0);
    assert(planarBytes == 288 && digits >= 6 && s_creditsPlanarPaletteGeneration == paletteGeneration);
    s_creditsCacheReady = false;
    g_timerGUI++;
    step(0);
    assert(!s_creditsPlanarDisplayReady);
    s_creditsCacheReady = true;
    g_timerGUI++;
    step(0);
    assert(planarBytes == 288 && digits >= 6);
    presentFailure = true;
    g_timerGUI++;
    step(0);
    assert(warnings == 1 && !s_creditsPlanarDisplayReady);
    presentFailure = false;
    g_timerGUI++;
    step(0);
    assert(planarBytes == 288 && digits >= 6);
#endif
    assert(suppressed > 0 && positiveSteps > 0 && negativeSteps > 0);
    return 0;
}
"""
        harness = harness.replace("/* CREDITS */", credits)
        harness = harness.replace("/* FORMAT */", function(source, "GUI_FormatCredits"))
        harness = harness.replace("/* PLANAR */", "\n".join(
            function(source, name) for name in ("GUI_ComposeCreditsPlanar", "GUI_PresentCreditsPlanar",
                                               "GUI_CreditsSoundPublished")))
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
