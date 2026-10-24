"""Exercise production feedback scheduling and retained message cleanup."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class ViewportMessagesTest(unittest.TestCase):
    def test_message_lifecycle(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        viewport = function(
            (ROOT / "src/gui/viewport.c").read_text(), "GUI_Widget_Viewport_Draw")
        start = viewport.index("\tif ((g_viewportMessageCounter & 1)")
        message = viewport[start:viewport.index(
            "\n\tif (updateDisplay && !drawToMainScreen", start)]
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int16_t int16;
typedef uint32_t uint32;
typedef int Screen;
#define SCREEN_0 0
#define SCREEN_1 1
#define SELECTIONTYPE_MENTAT 0
#define SELECTIONTYPE_DEBUG 5
#define SELECTIONTYPE_UNKNOWN6 6
#define SELECTIONTYPE_INTRO 7
#define SELECTIONTYPE_PLACE 2
#define LANGUAGE_ENGLISH 0
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
#define lengthof(a) (sizeof(a) / sizeof((a)[0]))
static uint8 g_dirtyMinimap[512], g_dirtyViewport[512], g_displayedViewport[512];
static uint16 g_dirtyViewportCount, g_viewportPosition, g_minimapPosition;
static uint16 g_viewportMessageCounter, g_selectionType = 4;
static uint16 g_selectionRectanglePosition, g_selectionPosition;
static uint16 g_selectionWidth = 1, g_selectionHeight = 1, g_curWidgetIndex;
static int16 g_selectionState;
static uint32 g_timerGUI;
static const char *g_viewportMessageText;
static bool g_viewport_forceRedraw, g_selectionRectangleNeedRepaint;
static unsigned terrain, candidates, fullDraws, messages, soundPlays, speechStarts;
static uint8 pixels[160][240], shifted[160][240];
static Screen activeScreen;
#ifdef TOS
static bool s_viewportMessageDrawn, direct;
static bool Video_Atari_CursorDirect(void) { return direct; }
static bool GUI_Widget_Viewport_IsPlanar(void) { return direct; }
static void Video_Atari_PlacementSet(int16 x, int16 y, uint16 w, uint16 h, bool valid) {
    (void)x; (void)y; (void)w; (void)h; (void)valid;
}
static void Video_Atari_PlacementHide(void) {}
static bool Video_Atari_ShiftPlanar(int16 x, int16 y, uint16 w, uint16 h,
                                  int16 dx, int16 dy) {
    if (!direct) return false;
    memcpy(shifted, pixels, sizeof(pixels));
    memset(pixels, 0, sizeof(pixels));
    for (unsigned row = 0; row < h; row++)
        for (unsigned col = 0; col < w; col++)
            pixels[y - 40 + dy + row][x + dx + col] = shifted[y - 40 + row][x + col];
    return true;
}
#endif
static uint16 Tile_GetPackedX(uint16 p) { return p & 63; }
static uint16 Tile_GetPackedY(uint16 p) { return p >> 6; }
static bool BitArray_Test(const uint8 *bits, uint16 p) {
    assert(p < 4096); return (bits[p >> 3] >> (p & 7)) & 1;
}
static void BitArray_Set(uint8 *bits, uint16 p) {
    assert(p < 4096); bits[p >> 3] |= 1u << (p & 7);
}
static bool Map_IsTileVisible(uint16 p) { return p < 4096; }
static unsigned count(const uint8 *bits) {
    unsigned n = 0;
    for (unsigned p = 0; p < 4096; p++) n += BitArray_Test(bits, p);
    return n;
}
/* UPDATE */
/* INVALIDATE */
static Screen GFX_Screen_SetActive(Screen screen) {
    Screen previous = activeScreen; activeScreen = screen; return previous;
}
static bool GFX_Screen_IsActive(Screen screen) { return activeScreen == screen; }
static void Explosion_Tick(void) {}
static void Animation_Tick(void) {}
static void Unit_Sort(void) {}
static uint16 Map_SetSelectionObjectPosition(uint16 p) { return p; }
static void Map_UpdateMinimapPosition(uint16 p, bool force) { (void)p; (void)force; }
static void GUI_Mouse_Hide_InWidget(uint16 w) { (void)w; }
static void GUI_Mouse_Show_InWidget(void) {}
static void GUI_Screen_CopyOverlap(int x, int y, int dx, int dy, int w, int h, Screen s) {
    (void)x; (void)y; (void)dx; (void)dy; (void)w; (void)h; (void)s;
}
static void GUI_DrawText_Wrapper(const char *text, int x, int y, int fg, int bg, int flags) {
    assert(text == g_viewportMessageText && x == 112 && y == 139);
    assert(fg == 15 && bg == 0 && flags == 0x132);
    unsigned width = strlen(text) * 4;
    assert(width <= 200);
    for (unsigned row = 99; row < 110; row++)
        memset(pixels[row] + 112 - width / 2, 15, width);
    messages++;
}
static void GUI_Widget_Viewport_Draw(bool force, bool hasScrolled, bool planarShifted,
                                     bool drawToMainScreen) {
    bool trackCopyDamage = false;
    int16 minX[10] = {0}, maxX[10] = {0};
    (void)minX; (void)maxX; (void)drawToMainScreen;
    terrain = count(g_dirtyMinimap);
    candidates = count(g_dirtyViewport);
    if (hasScrolled && !planarShifted) force = true;
    fullDraws += force;
    for (unsigned row = 0; row < 10; row++)
        for (unsigned col = 0; col < 15; col++) {
            uint16 p = g_viewportPosition + row * 64 + col;
            if (!force && !BitArray_Test(g_dirtyMinimap, p)) continue;
            for (unsigned y = row * 16; y < row * 16 + 16; y++)
                memset(pixels[y] + col * 16, 1, 16);
        }
    memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
    memset(g_dirtyViewport, 0, sizeof(g_dirtyViewport));
    g_dirtyViewportCount = 0;
    /* MESSAGE */
}
/* SCREEN */
static uint16 s_spokenWords[5], s_currentVoicePriority;
static unsigned g_enableVoices;
static struct { unsigned sounds; } g_gameConfig;
static struct { unsigned language; } g_config;
static struct { uint16 soundId, messageId, voiceId[5]; } g_feedback[2];
static uint16 g_translatedVoice[2][5];
static void Driver_Voice_Stop(void) {}
static void Driver_Sound_Play(uint16 s, uint16 volume) {
    (void)s; assert(volume == 255); soundPlays++;
}
static const char *String_Get_ByIndex(uint16 i) {
    return i == 0 ? "Long feedback message" : "Short";
}
static void Sound_StartSpeech(void) { speechStarts++; }
/* SOUND */
static void draw(void) { GUI_DrawScreen(SCREEN_0); }
static void reset(void) {
    memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
    memset(g_dirtyViewport, 0, sizeof(g_dirtyViewport));
    memset(g_displayedViewport, 0, sizeof(g_displayedViewport));
    memset(pixels, 1, sizeof(pixels));
    g_dirtyViewportCount = 0;
    g_viewportPosition = g_minimapPosition = 20 * 64 + 20;
    g_viewportMessageCounter = 0;
    g_viewportMessageText = NULL;
    g_viewport_forceRedraw = false;
    g_timerGUI = 0;
    activeScreen = SCREEN_0;
    terrain = candidates = fullDraws = messages = soundPlays = speechStarts = 0;
    g_enableVoices = g_gameConfig.sounds = 0;
    g_feedback[1].messageId = 1;
    for (unsigned i = 0; i < lengthof(s_spokenWords); i++) s_spokenWords[i] = 0xffff;
#ifdef TOS
    s_viewportMessageDrawn = false;
#endif
}
static void show(void) {
    g_viewportMessageText = String_Get_ByIndex(0);
    g_viewportMessageCounter = 3;
    draw();
    assert(messages == 1);
}
static void check_pixels(bool visible) {
    unsigned width = visible ? strlen(g_viewportMessageText) * 4 : 0;
    for (unsigned y = 0; y < 160; y++)
        for (unsigned x = 0; x < 240; x++) {
            bool text = visible && y >= 99 && y < 110 &&
                x >= 112 - width / 2 && x < 112 + (width + 1) / 2;
            assert(pixels[y][x] == (text ? 15 : 1));
        }
}
int main(void) {
#ifdef TOS
    direct = true;
    /* No message: only genuinely exposed terrain, for short click jumps too. */
    const int moves[][2] = {{1,0}, {-1,0}, {0,1}, {0,-1}, {1,1}, {4,3}};
    for (unsigned m = 0; m < lengthof(moves); m++) {
        reset();
        int dx = moves[m][0], dy = moves[m][1];
        g_viewportPosition += dx + dy * 64;
        draw();
        assert(terrain == 150u - (15 - abs(dx)) * (10 - abs(dy)));
        assert(!fullDraws && !messages);
        check_pixels(false);
    }
    /* An odd counter that was never rendered must not invent old coverage. */
    reset();
    g_viewportMessageCounter = 3;
    Sound_Output_Feedback(1);
    assert(!g_viewport_forceRedraw && !g_dirtyViewportCount);
    /* Visible replacements and cancellations repair 14 tiles, with the halo. */
    for (unsigned cancel = 0; cancel < 2; cancel++) {
        reset(); show();
        Sound_Output_Feedback(cancel ? 0xfffe : 1);
        assert(!g_viewport_forceRedraw && g_dirtyViewportCount == 14);
        draw();
        assert(terrain == 14 && candidates == 48 && !fullDraws);
        check_pixels(false);
        reset(); show();
        g_viewportPosition += 64; /* Target changed before feedback, old pixels not yet shifted. */
        Sound_Output_Feedback(cancel ? 0xfffe : 1);
        assert(!g_viewport_forceRedraw && g_dirtyViewportCount == 14);
        assert(count(g_dirtyMinimap) == 14 && count(g_dirtyViewport) == 48);
        assert(BitArray_Test(g_dirtyMinimap, g_minimapPosition + 6 * 64));
        assert(!BitArray_Test(g_dirtyMinimap, g_viewportPosition + 6 * 64));
        draw();
        assert(!fullDraws);
        check_pixels(false);
    }
    /* Scrolled old coverage and the fixed new text position are both correct. */
    for (unsigned m = 0; m < lengthof(moves); m++) {
        reset(); show();
        g_viewportPosition += moves[m][0] + moves[m][1] * 64;
        draw();
        assert(!fullDraws && messages == 2);
        check_pixels(true);
    }
    /* Replacement can become visible in the same frame it removes the old text. */
    reset(); show();
    draw();
    assert(messages == 2 && !terrain && !candidates);
    check_pixels(true);
    Sound_Output_Feedback(1);
    g_timerGUI = 1000;
    draw();
    assert(g_viewportMessageCounter == 3 && terrain == 14 && !fullDraws);
    check_pixels(true);
    /* Blink appearance and disappearance; publication still happens on every visible pass. */
    reset();
    g_viewportMessageText = String_Get_ByIndex(0);
    g_viewportMessageCounter = 4;
    for (unsigned next = 3;; next--) {
        g_timerGUI = 2000 + (3 - next) * 61;
        draw();
        assert(g_viewportMessageCounter == next && terrain == 14 && candidates == 48);
        assert(!fullDraws);
        check_pixels((next & 1) != 0);
        if (next == 0) break;
    }
    /* A NULL message counter can keep ticking, without any message-only damage. */
    reset();
    g_viewportMessageCounter = 4;
    for (unsigned next = 3;; next--) {
        g_timerGUI = 3000 + (3 - next) * 61;
        draw();
        assert(g_viewportMessageCounter == next && !terrain && !candidates);
        check_pixels(false);
        if (next == 0) break;
    }
    /* Expiry during scrolling clears the shifted old strip, not only the new row. */
    reset(); show();
    g_viewportPosition += 64;
    g_timerGUI = 3500;
    draw();
    assert(g_viewportMessageCounter == 2 && !fullDraws);
    check_pixels(false);
    /* A pre-existing full redraw request must survive message invalidation. */
    reset(); show();
    g_viewport_forceRedraw = true;
    Sound_Output_Feedback(0xfffe);
    assert(g_viewport_forceRedraw);
    draw(); assert(fullDraws == 1); check_pixels(false);
    /* Large jumps rebuild rather than scheduling displaced message strips. */
    reset(); show();
    g_viewportPosition += 15;
    draw();
    assert(fullDraws == 1 && terrain == 150);
    check_pixels(true);
    /* A hidden phase has no scroll strip; exposed-edge repairs remain. */
    reset(); show();
    g_timerGUI = 4000; draw();
    assert(g_viewportMessageCounter == 2);
    g_viewportPosition++;
    draw();
    assert(terrain == 10 && !fullDraws);
    check_pixels(false);
    Sound_Output_Feedback(0xfffe);
    assert(!g_viewport_forceRedraw && !g_dirtyViewportCount);
    draw();
    assert(!terrain && messages == 1);
    check_pixels(false);
    direct = false;
#endif
    /* Legacy rendering keeps its prior conservative scheduling/full redraws. */
    reset();
    g_viewportPosition++;
    draw();
    assert(terrain == 24);
    reset(); show();
    Sound_Output_Feedback(1);
    assert(g_viewport_forceRedraw && !g_dirtyViewportCount);
    reset(); show();
    Sound_Output_Feedback(0xfffe);
    assert(g_viewport_forceRedraw && g_viewportMessageText == NULL);
    reset();
    g_viewportMessageCounter = 3;
    Sound_Output_Feedback(0xffff);
    assert(g_viewportMessageCounter == 3 && !soundPlays && !g_viewport_forceRedraw);
    reset();
    g_enableVoices = g_gameConfig.sounds = 1;
    Sound_Output_Feedback(0);
    assert(speechStarts == 1 && !soundPlays && !g_viewport_forceRedraw);
    return 0;
}
"""
        harness = harness.replace("/* UPDATE */", function(
            (ROOT / "src/map.c").read_text(), "Map_Update"))
        harness = harness.replace(
            "/* INVALIDATE */", function(gui, "GUI_InvalidateViewportMessage"))
        harness = harness.replace("/* SCREEN */", function(gui, "GUI_DrawScreen"))
        harness = harness.replace("/* SOUND */", function(
            (ROOT / "src/audio/sound.c").read_text(), "Sound_Output_Feedback"))
        harness = harness.replace("/* MESSAGE */", message)
        with tempfile.TemporaryDirectory(prefix="viewport-messages-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            for platform in ([], ["-DTOS"]):
                # Existing scrolling shifts negative signed offsets.
                subprocess.run(
                    [*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                     "-Wno-unused-function", "-Wno-unused-variable", *flags,
                     "-fno-sanitize=shift-base",
                     *platform, str(source), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
