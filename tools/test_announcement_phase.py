"""Check engine banner phases, message timing and INI option validation."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


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
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int16_t int16;
typedef uint32_t uint32;
typedef int Screen;
enum { SCREEN_0, SCREEN_1, SCREEN_WIDTH = 320 };
#define min(a,b) ((a) < (b) ? (a) : (b))
static uint16 g_announcementPhase = 1;
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
static const char *option;
static char *IniFile_GetString(const char *key, const char *fallback, char *out, uint16 size) {
    assert(!strcmp(key, "phase_announcement") && fallback == NULL);
    if (option == NULL) return NULL;
    snprintf(out, size, "%s", option);
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
static void GUI_DrawText_Wrapper(const char *text, int x, int y, uint8 fg, uint8 bg, int flags) {
    (void)fg;
    assert(x == 8 && (y == 2 || y == 13) && bg == 0 && flags == 0x12);
    if (y == 2) snprintf(prepared, sizeof(prepared), "%s", text);
}
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
static bool direct;
static uint8 scratch[320 * 24];
static uint16 *encoded;
static unsigned encodes;
static bool Video_Atari_CursorDirect(void) { return direct; }
static uint8 *GFX_Screen_Get_ByIndex(Screen screen) {
    assert(screen == SCREEN_1);
    return scratch;
}
static void Video_Atari_EncodePlanar(const uint8 *src, uint16 *pixels, uint16 width, uint16 height) {
    assert(src == scratch && width == 320 && height == 24);
    encoded = pixels;
    encodes++;
}
static void Video_Atari_PresentPlanarWindow(const uint16 *pixels, uint16 x, uint16 y,
                                           uint16 width, uint16 height) {
    assert(x == 8 && y == 21 && width == 304);
    present((pixels - encoded) / 80, height);
}
static void GUI_Screen_Copy(int xs, int ys, int xd, int yd, int width, int height,
                           Screen src, Screen dst) {
    assert(!direct && xs == 1 && xd == 1 && yd == 21 && width == 38);
    assert(src == SCREEN_1 && dst == SCREEN_0);
    present(ys, height);
}
#endif
/* ANIMATOR */
static void reset(unsigned phase) {
    g_announcementPhase = phase;
    GUI_DisplayText(NULL, -1);
    g_timerGUI = 100;
    g_textDisplayNeedsUpdate = true;
    active = SCREEN_0;
    currentWidget = 6;
    frames = renders = hides = shows = 0;
    prepared[0] = displayed[0] = '\0';
#ifdef TOS
    encodes = 0;
#endif
}
static void poll(void) {
    GUI_DisplayText(NULL, 0);
    assert(hides == shows && active == SCREEN_0 && currentWidget == 6);
}
static void finish(unsigned phase) {
    unsigned count = phase == 0 ? 1 : (phase == 1 ? 11 : 6);
    for (unsigned i = 0; i < count; i++) {
        if (frames == i) poll();
        assert(frames == i + 1);
        assert(offsets[i] == (phase == 0 ? 0 : 10 - i * phase));
        g_timerGUI++;
    }
    assert(renders == 1 && !strcmp(displayed, "alpha"));
#ifdef TOS
    assert(encodes == (direct ? 1u : 0u));
#endif
}
int main(void) {
    const char *valid[] = {"0", "1", "2", " 2\t", "+1", "00"};
    const unsigned values[] = {0, 1, 2, 2, 1, 0};
    option = NULL;
    g_announcementPhase = 0;
    Config_LoadAnimationPhases();
    assert(g_announcementPhase == 1 && warnings == 0);
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
    /* Run both Atari backends, or the ordinary non-TOS renderer. */
    for (unsigned backend = 0; backend < 2; backend++) {
#ifdef TOS
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
    return 0;
}
"""
        harness = harness.replace("/* OPTION */", function(config, "Config_ReadAnimationPhase")
                                  + function(config, "Config_LoadAnimationPhases"))
        harness = harness.replace("/* ANIMATOR */", function(gui, "GUI_DisplayText"))
        with tempfile.TemporaryDirectory(prefix="announcement-phase-") as directory:
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
