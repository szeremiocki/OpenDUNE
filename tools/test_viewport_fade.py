"""Check viewport dissolve defaults and the gameplay transition policy."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class ViewportFadeTest(unittest.TestCase):
    def test_defaults_overrides_and_transitions(self):
        config = (ROOT / "src/config.c").read_text()
        gui = (ROOT / "src/gui/gui.c").read_text()
        header = (ROOT / "src/gui/gui.h").read_text()
        selection = (ROOT / "src/table/selectiontype.c").read_text()
        enum = header[header.index("typedef enum SelectionType"):
                      header.index("} SelectionType;") + len("} SelectionType;")]
        table_type = header[header.index("typedef struct SelectionTypeStruct"):
                            header.index("} SelectionTypeStruct;") + len("} SelectionTypeStruct;")]
        table = selection[selection.index("const SelectionTypeStruct"):]
        # The setting must not change the shared dissolve used by other screens.
        self.assertNotIn("Config_ViewportFadeEnabled", function(gui, "GUI_Screen_FadeIn"))
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t uint8;
typedef int8_t int8;
typedef uint16_t uint16;
typedef int16_t int16;
typedef int Screen;
enum { SCREEN_0, SCREEN_1, TIMER_GAME };
/* SELECTION */
static int16 s_viewportFade = -1;
static uint16 g_announcementPhase, g_creditsPhase;
static const char *option;
static unsigned warnings;
static char *IniFile_GetString(const char *key, const char *fallback, char *out, uint16 size) {
    assert(fallback == NULL);
    if (strcmp(key, "viewport_fade")) {
        assert(!strcmp(key, "phase_announcement") || !strcmp(key, "phase_credits"));
        return NULL;
    }
    if (option == NULL) return NULL;
    snprintf(out, size, "%s", option);
    return out;
}
#define Warning(...) (warnings++)
#ifdef TOS
static bool direct;
static bool Video_Atari_CursorDirect(void) { return direct; }
static void Video_Atari_PlacementHide(void) {}
#endif
/* CONFIG */
typedef struct { int unused; } Unit;
typedef struct Widget {
    uint16 index;
    struct { bool invisible; } flags;
    struct { bool selected; } state;
    struct Widget *next;
} Widget;
static Unit unit, *g_unitSelected;
static Widget *g_widgetLinkedListHead;
static Screen active;
static uint16 g_selectionType, g_selectionTypeNew, g_curWidgetIndex, g_selectionPosition = 12;
static uint16 g_structureActivePosition, g_structureActiveType;
static uint16 g_cursorDefaultSpriteID, g_cursorSpriteID;
static uint8 sprite, *g_sprites[] = { &sprite };
static bool g_var_37B8, g_viewport_forceRedraw, g_viewport_fadein, g_textDisplayNeedsUpdate;
static struct { uint16 layout; } g_table_structureInfo[1];
static unsigned interfaces, panels, timerStops, timerStarts;
static bool expectedFade;
static Screen GFX_Screen_SetActive(Screen screen) {
    Screen old = active;
    active = screen;
    return old;
}
static void Map_SetSelection(uint16 position) { assert(position == g_selectionPosition); }
static void Map_SetSelectionSize(uint16 layout) { assert(layout == 0); }
static void Unit_UpdateMap(uint16 mode, Unit *u) { assert(mode == 2 && u == &unit); }
static void Unit_Select(Unit *u) { assert(u == NULL); g_unitSelected = u; }
static void Timer_SetTimer(unsigned timer, bool enabled) {
    assert(timer == TIMER_GAME);
    if (enabled) timerStarts++; else timerStops++;
}
static void GUI_DisplayText(const char *text, int importance) {
    assert(text == NULL && importance == -1);
}
static void GUI_DrawInterfaceAndRadar(Screen screen) {
    assert(screen == SCREEN_0 && active == SCREEN_1);
    assert(g_viewport_forceRedraw && g_viewport_fadein == expectedFade);
    interfaces++;
}
static uint16 Widget_SetCurrentWidget(uint16 index) {
    uint16 old = g_curWidgetIndex;
    g_curWidgetIndex = index;
    return old;
}
static void GUI_Widget_DrawBorder(uint16 index, unsigned border, bool pressed) {
    assert(index == g_curWidgetIndex && border == 0 && !pressed);
}
static void GUI_Widget_Draw(Widget *w) { (void)w; }
static Widget *GUI_Widget_GetNext(Widget *w) { return w->next; }
static void GUI_Widget_DrawAll(Widget *w) { assert(w == g_widgetLinkedListHead); }
static void GUI_Widget_ActionPanel_Draw(bool force) { assert(force); panels++; }
static void Sprites_SetMouseSprite(unsigned x, unsigned y, const uint8 *pixels) {
    assert(x == 0 && y == 0 && pixels == &sprite);
}
/* TRANSITION */
static void transition(uint16 from, uint16 to, bool rebuild) {
    g_selectionType = from;
    g_unitSelected = (to == SELECTIONTYPE_UNIT || to == SELECTIONTYPE_TARGET) ? &unit : NULL;
    active = SCREEN_0;
    g_viewport_forceRedraw = g_viewport_fadein = false;
    interfaces = panels = timerStops = timerStarts = 0;
    expectedFade = Config_ViewportFadeEnabled();
    GUI_ChangeSelectionType(to);
    assert(active == SCREEN_0 && g_selectionType == to);
    assert(interfaces == rebuild && g_viewport_forceRedraw == rebuild);
    assert(g_viewport_fadein == (rebuild && expectedFade));
    assert(timerStops == 1);
    if (to == SELECTIONTYPE_STRUCTURE || to == SELECTIONTYPE_UNIT ||
        to == SELECTIONTYPE_PLACE || to == SELECTIONTYPE_TARGET) {
        assert(panels == 1 && timerStarts == 1);
    }
}
static void transitions(void) {
    /* New scenario / Mentat / Factory return share this gameplay re-entry. */
    transition(SELECTIONTYPE_MENTAT, SELECTIONTYPE_STRUCTURE, true);
    transition(SELECTIONTYPE_MENTAT, SELECTIONTYPE_UNIT, true);
    transition(SELECTIONTYPE_INTRO, SELECTIONTYPE_STRUCTURE, true);
    transition(SELECTIONTYPE_UNIT, SELECTIONTYPE_TARGET, false);
    transition(SELECTIONTYPE_STRUCTURE, SELECTIONTYPE_PLACE, false);
    /* Entering Mentat must not acquire a gameplay viewport dissolve. */
    transition(SELECTIONTYPE_STRUCTURE, SELECTIONTYPE_MENTAT, false);
}
int main(void) {
#ifdef TOS
    /* Configuration is read before video/machine initialization. */
    direct = false;
    option = NULL;
    Config_LoadAnimationPhases();
    assert(Config_ViewportFadeEnabled());
    direct = true;
    assert(!Config_ViewportFadeEnabled());
#endif
    for (unsigned backend = 0; backend < 2; backend++) {
        bool defaultFade = true;
#ifdef TOS
        direct = backend != 0;
        defaultFade = !direct;
#else
        (void)backend;
#endif
        option = NULL;
        Config_LoadAnimationPhases();
        assert(Config_ViewportFadeEnabled() == defaultFade);
        assert(g_announcementPhase == 1 && g_creditsPhase == 1);
        transitions();
        const char *valid[] = {"0", "1", " 1\t", "+0", "00"};
        const bool values[] = {false, true, true, false, false};
        for (unsigned i = 0; i < sizeof(valid) / sizeof(*valid); i++) {
            unsigned before = warnings;
            option = valid[i];
            Config_LoadAnimationPhases();
            assert(Config_ViewportFadeEnabled() == values[i] && warnings == before);
            transitions();
        }
        const char *invalid[] = {"", "2", "-1", "no", "1x", "1.5",
                                 "999999999999999999999999999"};
        for (unsigned i = 0; i < sizeof(invalid) / sizeof(*invalid); i++) {
            unsigned before = warnings;
            option = invalid[i];
            Config_LoadAnimationPhases();
            assert(Config_ViewportFadeEnabled() == defaultFade && warnings == before + 1);
            transitions();
        }
    }
    return 0;
}
"""
        harness = harness.replace("/* SELECTION */", "\n".join((enum, table_type, table)))
        names = ("Config_ReadAnimationOption", "Config_ReadAnimationPhase",
                 "Config_LoadAnimationPhases", "Config_ViewportFadeEnabled")
        harness = harness.replace("/* CONFIG */", "\n".join(function(config, name) for name in names))
        harness = harness.replace("/* TRANSITION */", function(gui, "GUI_ChangeSelectionType"))
        with tempfile.TemporaryDirectory(prefix="viewport-fade-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            for platform in ([], ["-DTOS"]):
                subprocess.run(
                    [*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                     *flags, *platform, str(source), "-o", str(binary)], check=True
                )
                subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
