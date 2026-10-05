"""Exercise the production command-panel cache and publication branches."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class CommandPanelCacheTest(unittest.TestCase):
    def test_cache_and_widget_state(self):
        source = (ROOT / "src/gui/widget_draw.c").read_text()
        cache_start = source.index("#ifdef TOS\nenum {\n\tCOMMAND_PANEL_WIDTH")
        cache = source[cache_start:source.index("\n#endif", cache_start) + 7]
        draw = function(source, "GUI_Widget_ActionPanel_Draw")
        prepare = draw[draw.index("\n\tif (actionType != 0) {"):
                       draw.index("\n\tif (actionType > 1) {")]
        publish = draw[draw.rindex("\n\tif (actionType != 0) {"):draw.rindex("\n}")]
        self.assertLess(draw.index("GUI_Widget_ActionPanel_GetActionType(forceDraw)"),
                        draw.index("GUI_Widget_CommandPanelCache(actionType"))
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int Screen;
enum { SCREEN_0, SCREEN_1, SCREEN_WIDTH = 320 };
typedef struct Widget {
    uint16 index;
    struct { bool selected, hover2; } state;
    struct { bool invisible; } flags;
} Widget;
static Widget widgets[9], *g_widgetLinkedListHead = widgets;
static struct { uint16 language; } g_config;
static uint16 g_curWidgetXBase = 32, g_curWidgetYBase = 42;
static uint16 g_curWidgetWidth = 8, g_curWidgetHeight = 82;
static uint16 g_curWidgetFGColourBlink = 15, g_curWidgetIndex = 2;
static Screen active;
#define SCREEN_ACTIVE active
static uint8 screen1[320 * 200];
static unsigned renders, encodes, copies, hides, shows, fontUpdates;
#ifdef TOS
static bool direct = true, failPresent;
static uint16 generation;
static uint8 before[320 * 200];
static uint16 shown[64 * 82 / 4], expected[64 * 82 / 4];
static unsigned restores, warnings;
#endif
static unsigned gets;
#define Warning(...) (warnings++)
static Screen GFX_Screen_SetActive(Screen screen) {
    Screen old = active;
    active = screen;
    return old;
}
static uint16 Widget_SetCurrentWidget(uint16 index) {
    uint16 old = g_curWidgetIndex;
    g_curWidgetIndex = index;
    return old;
}
static Widget *GUI_Widget_Get_ByIndex(Widget *head, uint16 index) {
    assert(head == widgets && index >= 3 && index <= 11);
    gets++;
    return &widgets[index - 3];
}
static void GUI_Widget_MakeInvisible(Widget *w) { w->flags.invisible = true; }
static void GUI_Mouse_Hide_InWidget(uint16 index) {
    assert(index == 6);
    hides++;
}
static void GUI_Mouse_Show_InWidget(void) { shows++; }
static void GUI_Widget_DrawBorder(uint16 index, unsigned type, bool pressed) {
    assert(index == 6 && type == 0 && !pressed && active == SCREEN_1);
    renders++;
}
static void GUI_DrawText_Wrapper(const char *text, int x, int y, uint8 fg, uint8 bg, int flags) {
    assert(text == NULL && x == 0 && y == 0 && fg == 15 && bg == 0 && flags == 0x11);
    fontUpdates++;
}
static void GUI_Screen_Copy(uint16 xs, uint16 ys, uint16 xd, uint16 yd,
                           uint16 width, uint16 height, Screen src, Screen dst) {
    assert(xs == 32 && ys == 42 && xd == xs && yd == ys);
    assert(width == g_curWidgetWidth && height == 82 && src == SCREEN_1 && dst == SCREEN_0);
    copies++;
}
#ifdef TOS
static bool Video_Atari_CursorDirect(void) { return direct; }
static uint16 Video_Atari_GetPaletteGeneration(void) { return generation; }
static void Video_Atari_EncodePlanarStrided(const uint8 *src, uint16 stride,
                                           uint16 *pixels, uint16 width, uint16 height) {
    assert(src == screen1 + 42 * 320 + 256 && stride == 320 && width == 64 && height == 82);
    assert(pixels != shown);
    encodes++;
    memset(pixels, 0, sizeof(shown));
    for (unsigned y = 0; y < height; y++) for (unsigned x = 0; x < width; x++)
        for (unsigned p = 0; p < 4; p++) if ((src[y * stride + x] ^ generation) & (1u << p))
            pixels[y * 16 + (x >> 4) * 4 + p] |= 0x8000u >> (x & 15);
}
static const uint8 *GFX_Screen_Get_ByIndex(Screen screen) {
    assert(screen == SCREEN_1);
    return screen1;
}
static bool Video_Atari_PresentRestore(int x, int y, uint16 width, uint16 height, const uint8 *data) {
    assert(x == 256 && y == 42 && width == 64 && height == 82);
    restores++;
    if (failPresent) return false;
    memcpy(shown, data, sizeof(shown));
    return true;
}
#endif
/* CACHE */
static void panel(uint16 actionType) {
    Screen oldScreenID = SCREEN_ACTIVE;
    uint16 oldWidgetID = g_curWidgetIndex;
    Widget *buttons[4];
    Widget *widget24, *widget28, *widget2C, *widget30, *widget34;
#ifdef TOS
    CommandPanelCache *commandPanel = NULL;
#endif
    /* PREPARE */
    if (actionType > 1) {
        /* Model the original renderer's complete panel and Cancel appearance. */
        widget30->flags.invisible = false;
        unsigned state = widget30->state.selected + 2 * widget30->state.hover2;
        for (unsigned y = 0; y < 82; y++) for (unsigned x = 0; x < 64; x++)
            screen1[(42 + y) * 320 + 256 + x] = actionType + x + y + state + g_config.language;
        GUI_DrawText_Wrapper(NULL, 0, 0, g_curWidgetFGColourBlink, 0, 0x11);
    }
    /* PUBLISH */
}
static void reset_widgets(void) {
    for (unsigned i = 0; i < 9; i++) {
        widgets[i].index = i + 3;
        widgets[i].flags.invisible = false;
        widgets[i].state.selected = widgets[i].state.hover2 = false;
    }
    active = SCREEN_0;
    g_curWidgetIndex = 2;
}
static void check_state(void) {
    assert(active == SCREEN_0 && g_curWidgetIndex == 2 && hides == shows);
    for (unsigned i = 0; i < 9; i++) assert(widgets[i].flags.invisible == (i != 4));
}
int main(void) {
    for (unsigned command = 4; command <= 6; command++) {
        reset_widgets();
        unsigned r = renders, e = encodes, c = copies, g = gets, f = fontUpdates;
#ifdef TOS
        unsigned p = restores;
#endif
        panel(command);
        check_state();
        assert(renders == r + 1 && gets == g + 9 && fontUpdates == f + 1);
#ifdef TOS
        assert(encodes == e + 1 && copies == c && restores == p + 1);
        memcpy(expected, shown, sizeof(shown));
        /* Scratch may contain unrelated content between command-panel entries. */
        memset(screen1, 0xa5, sizeof(screen1));
        memcpy(before, screen1, sizeof(before));
        reset_widgets();
        panel(command);
        check_state();
        assert(renders == r + 1 && encodes == e + 1 && copies == c);
        assert(gets == g + 18 && fontUpdates == f + 2);
        assert(!memcmp(shown, expected, sizeof(shown)));
        assert(!memcmp(screen1, before, sizeof(screen1)));
        assert(restores == p + 2);
#else
        assert(encodes == e && copies == c + 1);
#endif
    }
#ifdef TOS
    /* Each visual Cancel state is a distinct cached image. */
    for (unsigned state = 1; state <= 3; state++) {
        reset_widgets();
        widgets[4].state.selected = (state & 1) != 0;
        widgets[4].state.hover2 = (state & 2) != 0;
        unsigned r = renders, e = encodes;
        panel(4);
        check_state();
        assert(renders == r + 1 && encodes == e + 1);
        memcpy(expected, shown, sizeof(shown));
        panel(4);
        check_state();
        assert(renders == r + 1 && encodes == e + 1);
        assert(!memcmp(shown, expected, sizeof(shown)));
    }
    /* A mapping or language change must not replay stale cached pixels. */
    reset_widgets();
    generation++;
    unsigned e = encodes, r = renders;
    panel(5);
    assert(encodes == e + 1 && renders == r + 1);
    panel(5);
    assert(encodes == e + 1 && renders == r + 1);
    g_config.language++;
    panel(5);
    assert(encodes == e + 2 && renders == r + 2);
    panel(5);
    assert(encodes == e + 2 && renders == r + 2);
    /* Failed publication reports the failure and reconstructs from scratch. */
    failPresent = true;
    unsigned c = copies, w = warnings;
    panel(5);
    assert(renders == r + 3 && encodes == e + 3 && copies == c + 1 && warnings == w + 2);
    check_state();
    failPresent = false;
    panel(5);
    assert(renders == r + 4 && encodes == e + 4 && copies == c + 1);
    /* Unsupported hardware/layouts retain the original publication path. */
    direct = false;
    panel(5);
    assert(encodes == e + 4 && copies == c + 2);
    direct = true;
    g_curWidgetWidth = 9;
    panel(5);
    assert(encodes == e + 4 && copies == c + 3);
    g_curWidgetWidth = 8;
    panel(2);
    assert(encodes == e + 4 && copies == c + 4);
    /* More unique images than slots exercise bounded round-robin replacement. */
    for (unsigned language = 10; language < 18; language++) {
        reset_widgets();
        g_config.language = language;
        unsigned beforeEncode = encodes;
        panel(4);
        panel(4);
        assert(encodes == beforeEncode + 1);
    }
    e = encodes;
    g_config.language = 10;
    panel(4);
    assert(encodes == e + 1);
#endif
    reset_widgets();
    unsigned r0 = renders, e0 = encodes, c0 = copies, g0 = gets;
    panel(0);
    assert(renders == r0 && encodes == e0 && copies == c0 && gets == g0);
    assert(hides == shows && active == SCREEN_0 && g_curWidgetIndex == 2);
    return 0;
}
"""
        harness = harness.replace("/* CACHE */", cache)
        harness = harness.replace("/* PREPARE */", prepare)
        harness = harness.replace("/* PUBLISH */", publish)
        with tempfile.TemporaryDirectory(prefix="command-panel-cache-") as directory:
            source_file = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source_file.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            for platform in ([], ["-DTOS"]):
                subprocess.run(
                    [*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                     *flags, *platform, str(source_file), "-o", str(binary)],
                    check=True
                )
                subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
