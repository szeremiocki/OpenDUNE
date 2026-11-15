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
    def test_widget_event_bookkeeping_equivalence(self):
        video = (ROOT / "src/gui/widget.c").read_text()
        handler = function(video, "GUI_Widget_HandleEvents")
        start = handler.index("\t\t/* Store the previous button state */")
        end = handler.index("\t\t/* Check if the mouse is inside the widget */", start)
        reference = handler[:start] + r"""
        w->state.selectedLast = w->state.selected;
        w->state.hover1Last = w->state.hover1;
        positionX = w->offsetX;
        if (w->offsetX < 0) positionX += g_widgetProperties[w->parentID].width << 3;
        positionX += g_widgetProperties[w->parentID].xBase << 3;
        positionY = w->offsetY;
        if (w->offsetY < 0) positionY += g_widgetProperties[w->parentID].height;
        positionY += g_widgetProperties[w->parentID].yBase;
        widgetHover = false;
        w->state.keySelected = false;
""" + handler[end:]
        reference = reference.replace(
            "/* Update the hover state */",
            "/* Update the hover state */\n"
            "        w->state.hover1 = false;\n        w->state.hover2 = false;", 1)
        reference = reference.replace("GUI_Widget_HandleEvents(", "reference_events(", 1)
        reference = reference.replace("s_widgetReset", "reference_reset")
        harness = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#include "src/gui/widget.h"
WidgetProperties g_widgetProperties[22];
static bool s_widgetReset, reference_reset, direct;
static uint16 g_mouseX, g_mouseY, g_mouseClickX, g_mouseClickY, g_mouseDisabled;
static uint16 inputKey;
static unsigned mode, eventCount;
static Widget current[8], reference[8], *activeWidgets;
static uint16 events[128][4], savedEvents[128][4];
static uint32 randomState = 0x73a195df;
static uint32 random_next(void) {
    randomState ^= randomState << 13;
    randomState ^= randomState >> 17;
    randomState ^= randomState << 5;
    return randomState;
}
static void record(Widget *w, uint16 kind) {
    assert(eventCount < 128);
    events[eventCount][0] = kind;
    events[eventCount][1] = w->index;
    events[eventCount][2] = w->state.selected | (w->state.hover1 << 1) |
        (w->state.hover2 << 2) | (w->state.selectedLast << 3) |
        (w->state.hover1Last << 4) | (w->state.hover2Last << 5) |
        (w->state.keySelected << 6);
    events[eventCount++][3] = w->state.buttonState;
}
Widget *GUI_Widget_GetNext(Widget *w) { return w->next; }
void GUI_Widget_Draw(Widget *w) {
    record(w, 1);
    if (mode & 1) w->state.selected = !w->state.selected;
    if ((mode & 2) && w->next != NULL) {
        w->next->offsetX = -16;
        g_widgetProperties[w->next->parentID].width = 31;
    }
}
static bool click(Widget *w) {
    record(w, 2);
    if (mode & 4) {
        w->state.hover1 = !w->state.hover1;
        activeWidgets[7].flags.invisible = !activeWidgets[7].flags.invisible;
        g_widgetProperties[1].yBase += 1;
    }
    return (mode & 8) != 0;
}
static uint16 Input_IsInputAvailable(void) { return inputKey != 0; }
static uint16 Input_Wait(void) { uint16 key = inputKey; inputKey = 0; return key; }
static uint16 Input_Test(uint16 key) { (void)key; return 0; }
static bool Video_Atari_CursorDirect(void) { return direct; }
bool GUI_Widget_TextButton_OpensTarget(const Widget *w) { return w->index == 1; }
/* HANDLERS */
int main(void) {
    for (unsigned i = 0; i < 8; i++) {
        current[i].index = i + 1;
        current[i].next = i == 7 ? NULL : &current[i + 1];
        current[i].parentID = i & 3;
        current[i].offsetX = i & 1 ? -16 : 0;
        current[i].offsetY = i & 1 ? -8 : 0;
        current[i].width = 40; current[i].height = 40;
        current[i].shortcut = 1 + i; current[i].shortcut2 = 9 + i;
        current[i].clickProc = click;
        current[i].flags.buttonFilterLeft = 15;
        current[i].flags.buttonFilterRight = 15;
        reference[i] = current[i];
        reference[i].next = i == 7 ? NULL : &reference[i + 1];
    }
    const uint16 keys[] = {0,1,9,0x41,0x841,0x42,0x842,0x80c6,
                          0x88c6,0x80c7,0x88c7,2,10,0x77,0,0};
    for (unsigned step = 0; step < 4096; step++) {
        unsigned changed = random_next() & 7;
        Widget *w = &current[changed];
        uint32 bits = random_next();
        w->flags.invisible = (bits & 1) != 0;
        w->flags.requiresClick = (bits & 2) != 0;
        w->flags.clickAsHover = (bits & 4) != 0;
        w->flags.loseSelect = (bits & 8) != 0;
        w->flags.noClickCascade = (bits & 16) != 0;
        w->flags.buttonFilterLeft = (bits >> 5) & 15;
        w->flags.buttonFilterRight = (bits >> 9) & 15;
        w->state.hover2Last = (bits >> 13) & 1;
        w->offsetX = step & 1 ? -16 : 16;
        w->offsetY = step & 2 ? -8 : 8;
        w->parentID = (bits >> 14) & 3;
        Widget *next = reference[changed].next;
        reference[changed] = *w; reference[changed].next = next;
        g_widgetProperties[0].xBase = step & 1 ? 0 : 2;
        g_widgetProperties[0].yBase = step & 2 ? 0 : 8;
        for (unsigned i = 0; i < 4; i++) {
            g_widgetProperties[i].width = 40;
            g_widgetProperties[i].height = 100;
        }
        uint16 key = keys[random_next() & 15];
        g_mouseX = random_next() % 321;
        g_mouseY = random_next() % 201;
        g_mouseClickX = random_next() % 321;
        g_mouseClickY = random_next() % 201;
        g_mouseDisabled = (random_next() & 31) == 0;
        mode = random_next() & 15; direct = (step & 1) != 0;
        unsigned head = step % 19 == 0 ? 2 : 0;
        bool reset = step % 29 == 0;
        if (step < 2) {
            current[0].flags.invisible = false;
            current[0].flags.requiresClick = false;
            current[0].flags.clickAsHover = true;
            current[0].flags.buttonFilterLeft = 8;
            current[0].flags.noClickCascade = true;
            current[0].offsetX = current[0].offsetY = 0;
            current[0].parentID = 0;
            current[0].state.selected = current[0].state.hover1 = false;
            next = reference[0].next; reference[0] = current[0]; reference[0].next = next;
            g_widgetProperties[0].xBase = g_widgetProperties[0].yBase = 0;
            g_mouseX = g_mouseY = 10; g_mouseDisabled = 0;
            key = 0; mode = 8; head = 0; reset = step == 0;
        }
        bool nullHead = step > 1 && step % 17 == 0;
        WidgetProperties before[22], after[22];
        memcpy(before, g_widgetProperties, sizeof(before));
        activeWidgets = current; s_widgetReset = reset; inputKey = key; eventCount = 0;
        uint16 result = GUI_Widget_HandleEvents(nullHead ? NULL : &current[head]);
        unsigned savedCount = eventCount;
        memcpy(savedEvents, events, sizeof(events));
        memcpy(after, g_widgetProperties, sizeof(after));
        memcpy(g_widgetProperties, before, sizeof(before));
        activeWidgets = reference; reference_reset = reset; inputKey = key; eventCount = 0;
        assert(reference_events(nullHead ? NULL : &reference[head]) == result);
        assert(reference_reset == s_widgetReset);
        assert(eventCount == savedCount);
        assert(!memcmp(savedEvents, events, eventCount * sizeof(events[0])));
        assert(!memcmp(after, g_widgetProperties, sizeof(after)));
        for (unsigned i = 0; i < 8; i++) {
            Widget a = current[i], b = reference[i];
            a.next = b.next = NULL;
            assert(!memcmp(&a, &b, sizeof(a)));
        }
        if (step < 2) {
            unsigned callbacks = 0;
            for (unsigned i = 0; i < eventCount; i++) callbacks += events[i][0] == 2;
            assert(callbacks == 1); /* stationary, released-button callbacks still run */
        }
    }
    return 0;
}
"""
        harness = harness.replace("/* HANDLERS */", reference + "\n" + handler)
        with tempfile.TemporaryDirectory(prefix="widget-events-") as directory:
            cfile, binary = Path(directory) / "test.c", Path(directory) / "test"
            cfile.write_text(harness)
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            subprocess.run(["cc", "-std=gnu17", "-O2", "-Wall", "-Wextra", "-Werror",
                            "-DTOS", "-I", str(ROOT), "-I", str(ROOT / "include"),
                            *flags, str(cfile), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

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
enum { UNIT_UPDATE_MAP_REPAINT = 2, UNIT_SPRITE_SELECTION = 1 };
/* TYPES */
/* TABLE */
typedef struct Widget {
    struct Widget *next;
    uint16 index;
    struct { bool selected; } state;
    struct { bool invisible; } flags;
} Widget;
typedef struct { uint16 position; bool keyValid; } Unit;
static void Unit_ClearViewportKey(Unit *u) { assert(u != NULL); u->keyValid = false; }
static Unit unit;
static Unit *g_unitSelected;
static void Unit_PrepareSpriteChange(Unit *u, unsigned kind) {
    assert(u == &unit && kind == UNIT_SPRITE_SELECTION);
    Unit_ClearViewportKey(u);
}
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
static bool tileCursorOwns, cursorSuppressed;
static unsigned classicCursorDraws;
static bool Config_ViewportFadeEnabled(void) { return true; }
static Screen GFX_Screen_SetActive(Screen screen) {
    Screen old = active;
    active = screen;
    return old;
}
#ifdef TOS
static bool Video_Atari_CursorDirect(void) { return direct; }
static void Video_Atari_PlacementHide(void) {
    placementHides++;
    cursorSuppressed = false;
}
static bool GUI_Widget_Viewport_TileCursorActive(void) { return tileCursorOwns; }
static void Video_Atari_PlacementCursor(bool hidden) { cursorSuppressed = hidden; }
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
    assert(kind == UNIT_UPDATE_MAP_REPAINT && u == &unit);
    Unit_ClearViewportKey(u);
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
    if (direct && tileCursorOwns && !cursorSuppressed) classicCursorDraws++;
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
    if (direct && tileCursorOwns && !cursorSuppressed) classicCursorDraws++;
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
    unit.keyValid = true;
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
    tileCursorOwns = cursorSuppressed = false;
    classicCursorDraws = 0;
}
int main(void) {
    init(SELECTIONTYPE_UNIT, 0, false);
    GUI_ChangeSelectionType(SELECTIONTYPE_STRUCTURE);
    assert(!g_unitSelected && !unit.keyValid);
    init(SELECTIONTYPE_UNIT, 0, false);
    GUI_ChangeSelectionType(SELECTIONTYPE_MENTAT);
    assert(!g_unitSelected && !unit.keyValid);
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
#ifdef TOS
    for (unsigned targeting = 0; targeting < 2; targeting++) {
        unsigned old = targeting ? SELECTIONTYPE_TARGET : SELECTIONTYPE_UNIT;
        unsigned next = targeting ? SELECTIONTYPE_UNIT : SELECTIONTYPE_TARGET;
        for (unsigned owns = 0; owns < 2; owns++) {
            init(old, 0, true);
            tileCursorOwns = cursorSuppressed = owns != 0;
            GUI_ChangeSelectionType(next);
            assert(cursorSuppressed == (owns != 0));
            assert(classicCursorDraws == 0);
            assert(placementHides == 1 && panels == 1);
        }
        init(old, 0, true);
        tileCursorOwns = cursorSuppressed = true;
        GUI_ChangeSelectionType(SELECTIONTYPE_MENTAT);
        assert(!cursorSuppressed);
    }
#endif
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
