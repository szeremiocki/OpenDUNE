"""Check ST/STE selection-transition state and redundant widget drawing."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class SelectionTransitionTest(unittest.TestCase):
    def test_state_and_drawing_policy(self):
        header = (ROOT / "src/gui/gui.h").read_text()
        selection_types = re.search(
            r"typedef enum SelectionType \{.*?\} SelectionType;", header, re.S
        ).group()
        selection_info = re.search(
            r"typedef struct SelectionTypeStruct \{.*?\} SelectionTypeStruct;",
            header, re.S
        ).group()
        table = (ROOT / "src/table/selectiontype.c").read_text()
        table = table[table.index("const SelectionTypeStruct"):]
        transition = function(
            (ROOT / "src/gui/gui.c").read_text(), "GUI_ChangeSelectionType"
        )
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
typedef uint16_t uint16;
typedef int8_t int8;
typedef int Screen;
enum { SCREEN_0, SCREEN_1, SCREEN_2, TIMER_GAME = 2 };
/* TYPES */
/* TABLE */
typedef struct Widget {
    struct Widget *next;
    uint16 index;
    struct { bool selected; } state;
    struct { bool invisible; } flags;
} Widget;
typedef struct { uint16 position; } Unit;
static Unit unit;
static Unit *g_unitSelected;
static Widget widgets[18], *g_widgetLinkedListHead;
static uint16 g_selectionType, g_selectionTypeNew, g_cursorDefaultSpriteID;
static uint16 g_cursorSpriteID, g_curWidgetIndex, g_structureActivePosition;
static uint16 g_selectionPosition, g_structureActiveType;
static struct { uint16 layout; } g_table_structureInfo[1];
static bool g_var_37B8, g_viewport_forceRedraw, g_viewport_fadein;
static bool g_textDisplayNeedsUpdate, direct, gameTimer;
static Screen active;
static uint8_t pixels[46];
static unsigned draws[46], fullPasses, panels, timerCalls, borders;
static unsigned interfaces, textClears, unitUpdates, mapSelections, spriteChanges;
static unsigned placementHides;
static Screen GFX_Screen_SetActive(Screen screen) {
    Screen old = active;
    active = screen;
    return old;
}
#ifdef TOS
static bool Video_Atari_CursorDirect(void) { return direct; }
static void Video_Atari_PlacementHide(void) { placementHides++; }
#endif
static void Timer_SetTimer(unsigned timer, bool enabled) {
    assert(timer == TIMER_GAME);
    timerCalls++;
    gameTimer = enabled;
}
static void Map_SetSelection(uint16 position) {
    assert(position == g_structureActivePosition);
    mapSelections++;
}
static void GUI_DisplayText(const char *text, int priority) {
    assert(text == NULL && priority == -1);
    textClears++;
}
static void Unit_UpdateMap(unsigned kind, Unit *u) {
    assert(kind == 2 && u == &unit);
    unitUpdates++;
}
static void GUI_DrawInterfaceAndRadar(Screen screen) {
    assert(screen == SCREEN_0);
    interfaces++;
}
static uint16 Widget_SetCurrentWidget(uint16 index) {
    uint16 old = g_curWidgetIndex;
    g_curWidgetIndex = index;
    return old;
}
static void GUI_Widget_DrawBorder(uint16 index, unsigned type, bool pressed) {
    assert(index == g_curWidgetIndex && type == 0 && !pressed);
    borders++;
}
static void GUI_Widget_Draw(Widget *w) {
    draws[w->index]++;
    /* Only header/panel widgets draw pixels; viewport widgets are hit regions. */
    if (!w->flags.invisible && w->index <= 11)
        pixels[w->index] = w->state.selected ? 2 : 1;
}
static Widget *GUI_Widget_GetNext(Widget *w) { return w->next; }
static void GUI_Widget_DrawAll(Widget *w) {
    fullPasses++;
    for (; w != NULL; w = w->next) GUI_Widget_Draw(w);
}
static void Sprites_SetMouseSprite(unsigned x, unsigned y, const void *sprite) {
    assert(x == 0 && y == 0 && sprite == &unit);
    spriteChanges++;
}
static const void *g_sprites[1] = { &unit };
static void GUI_Widget_ActionPanel_Draw(bool force) {
    assert(force);
    panels++;
    for (unsigned i = 2; i < 11; i++) {
        Widget *w = &widgets[i];
        w->flags.invisible = true;
        pixels[w->index] = 0;
        if (g_selectionType == SELECTIONTYPE_UNIT) {
            w->flags.invisible = !(w->index == 3 || w->index >= 8);
            w->state.selected = w->index == 9;
        } else if (g_selectionType == SELECTIONTYPE_TARGET
                   || g_selectionType == SELECTIONTYPE_PLACE) {
            w->flags.invisible = w->index != 7;
        }
        if (!w->flags.invisible) pixels[w->index] = w->state.selected ? 2 : 1;
    }
}
static void Unit_Select(Unit *u) { g_unitSelected = u; }
static void Map_SetSelectionSize(uint16 layout) { assert(layout == 0); }
/* TRANSITION */
typedef struct {
    uint16 selection, selectionNew, cursor, cursorDefault, widget, position;
    bool hasUnit, timer, changed, forceRedraw, fade, textUpdate;
    Screen screen;
    uint8_t pixels[46], selected[18], invisible[18];
    unsigned panels, timerCalls, borders, interfaces, textClears, unitUpdates;
    unsigned mapSelections, spriteChanges, placementHides;
} Snapshot;
static Snapshot snapshot(void) {
    Snapshot s = {0};
    s.selection = g_selectionType; s.selectionNew = g_selectionTypeNew;
    s.cursor = g_cursorSpriteID; s.cursorDefault = g_cursorDefaultSpriteID;
    s.widget = g_curWidgetIndex; s.position = g_structureActivePosition;
    s.hasUnit = g_unitSelected != NULL; s.timer = gameTimer;
    s.changed = g_var_37B8; s.forceRedraw = g_viewport_forceRedraw;
    s.fade = g_viewport_fadein; s.textUpdate = g_textDisplayNeedsUpdate;
    s.screen = active;
    memcpy(s.pixels, pixels, sizeof(pixels));
    for (unsigned i = 0; i < 18; i++) {
        s.selected[i] = widgets[i].state.selected;
        s.invisible[i] = widgets[i].flags.invisible;
    }
    s.panels = panels; s.timerCalls = timerCalls; s.borders = borders;
    s.interfaces = interfaces; s.textClears = textClears; s.unitUpdates = unitUpdates;
    s.mapSelections = mapSelections; s.spriteChanges = spriteChanges;
    s.placementHides = placementHides;
    return s;
}
static void init(unsigned old, unsigned variant, bool useDirect) {
    static const unsigned indices[18] = {
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 39, 40, 41, 42, 43, 44, 45
    };
    memset(widgets, 0, sizeof(widgets));
    memset(pixels, 0, sizeof(pixels));
    g_widgetLinkedListHead = widgets;
    for (unsigned i = 0; i < 18; i++) {
        Widget *w = &widgets[i];
        w->index = indices[i];
        w->next = i < 17 ? &widgets[i + 1] : NULL;
        w->flags.invisible = true;
        for (const int8 *s = g_table_selectionType[old].visibleWidgets; *s != -1; s++)
            if (*s == w->index) w->flags.invisible = false;
    }
    g_selectionType = g_selectionTypeNew = old;
    if (old == SELECTIONTYPE_UNIT || old == SELECTIONTYPE_TARGET)
        GUI_Widget_ActionPanel_Draw(true);
    /* Selected and unexpectedly hidden header controls still need repainting. */
    widgets[0].state.selected = variant == 1;
    if (variant == 2) widgets[1].flags.invisible = true;
    for (unsigned i = 0; i < 18; i++) GUI_Widget_Draw(&widgets[i]);
    g_unitSelected = variant == 3 ? NULL : &unit;
    g_cursorDefaultSpriteID = old == SELECTIONTYPE_TARGET ? 5 : 0;
    g_cursorSpriteID = 5; g_curWidgetIndex = 6;
    g_structureActivePosition = 12; g_selectionPosition = 34;
    g_structureActiveType = 0;
    g_var_37B8 = g_viewport_forceRedraw = g_viewport_fadein = false;
    g_textDisplayNeedsUpdate = false;
    gameTimer = true; active = SCREEN_2; direct = useDirect;
    memset(draws, 0, sizeof(draws));
    fullPasses = panels = timerCalls = borders = interfaces = textClears = 0;
    unitUpdates = mapSelections = spriteChanges = placementHides = 0;
}
int main(void) {
    assert(memcmp(g_table_selectionType[SELECTIONTYPE_UNIT].visibleWidgets,
                  g_table_selectionType[SELECTIONTYPE_TARGET].visibleWidgets,
                  sizeof(g_table_selectionType[0].visibleWidgets)) == 0);
    for (unsigned old = 0; old < SELECTIONTYPE_MAX; old++) {
        for (unsigned next = 0; next < SELECTIONTYPE_MAX; next++) {
            for (unsigned variant = 0; variant < 4; variant++) {
                init(old, variant, false);
                GUI_ChangeSelectionType(next);
                Snapshot expected = snapshot();
                unsigned expectedDraws[46], expectedPasses = fullPasses;
                memcpy(expectedDraws, draws, sizeof(draws));
                init(old, variant, true);
                GUI_ChangeSelectionType(next);
                Snapshot actual = snapshot();
                assert(memcmp(&actual, &expected, sizeof(actual)) == 0);
                bool fast = false;
#ifdef TOS
                fast = (old == SELECTIONTYPE_UNIT && next == SELECTIONTYPE_TARGET)
                    || (old == SELECTIONTYPE_TARGET && next == SELECTIONTYPE_UNIT
                        && variant != 3);
#endif
                if (fast) {
                    assert(fullPasses == 0 && expectedPasses == 1);
                    assert(draws[1] == (variant == 1 ? 1u : 0u));
                    assert(draws[2] == (variant == 2 ? 1u : 0u));
                    assert(panels == 1 && timerCalls == 2 && gameTimer);
                    assert(!g_viewport_forceRedraw && !g_viewport_fadein);
                } else {
                    assert(fullPasses == expectedPasses);
                    assert(memcmp(draws, expectedDraws, sizeof(draws)) == 0);
                }
                assert(active == SCREEN_2);
            }
        }
    }
    return 0;
}
"""
        harness = harness.replace("/* TYPES */", selection_types + selection_info)
        harness = harness.replace("/* TABLE */", table)
        harness = harness.replace("/* TRANSITION */", transition)
        with tempfile.TemporaryDirectory(prefix="selection-transition-") as directory:
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
