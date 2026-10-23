"""Check repair-on-first-touch and its viewport publication boundaries."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

from test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class ViewportPhaseReversalTest(unittest.TestCase):
    def test_interface_publication_precedes_native_full_redraw(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int Screen;
enum { SCREEN_ACTIVE = -1, SCREEN_0, SCREEN_1, SCREEN_2,
       SCREEN_WIDTH = 320, SCREEN_HEIGHT = 200, HOUSE_INVALID = 255,
       STRUCTURE_SLAB_1x1 = 1, STRUCTURE_SLAB_2x2, STRUCTURE_WALL,
       GUI_SPRITE_COLOUR_EMBEDDED = 254 };
typedef struct { uint16 houseID, index, type; } PoolFindStruct;
typedef struct { int unused; } Widget;
typedef struct { struct { uint16 type; } o; } Structure;
typedef struct { int unused; } Unit;
static Screen active;
static bool direct, g_viewport_forceRedraw, g_textDisplayNeedsUpdate;
static uint8 front[152], back[152], sprite, *g_sprites[12], g_remap[256], g_palette1[768];
static uint16 g_playerHouseID, g_playerCredits = 123;
static Widget widgets[2], *g_widgetLinkedListHead = widgets;
static unsigned draws, copies, hidden;
static Screen GFX_Screen_SetActive(Screen screen) {
    Screen old = active; active = screen; return old;
}
#ifdef TOS
static bool Video_Atari_CursorDirect(void) { return direct; }
static void GUI_Sidebar_Invalidate(void) {}
#endif
static void Sprites_LoadImage(const char *name, Screen screen, uint8 *palette) {
    assert(!strcmp(name, "SCREEN.CPS") && screen == SCREEN_1 && palette == NULL);
    memset(back, 0, sizeof(back)); back[150] = 42; back[151] = 43;
}
static void GUI_DrawSprite(Screen screen, const uint8 *asset, uint16 id, uint8 house,
                           int x, int y, uint16 window, int flags) {
    assert(screen == SCREEN_1 && asset == &sprite && id == 11);
    assert(house == GUI_SPRITE_COLOUR_EMBEDDED && x == 192 && !y && !window && !flags);
}
static void GUI_Palette_RemapScreen(int x, int y, int width, int height,
                                    Screen screen, const uint8 *mapping) {
    assert(!x && !y && width == 320 && height == 200 && screen == SCREEN_1 && mapping == g_remap);
}
static void GUI_Widget_Viewport_RedrawMap(Screen screen) {
    assert(screen == SCREEN_ACTIVE && active == SCREEN_1);
}
static void GUI_DrawScreen(Screen screen) {
    assert(g_viewport_forceRedraw);
    Screen target = screen == SCREEN_ACTIVE ? active : screen;
    assert(target == (direct ? SCREEN_0 : SCREEN_1));
    if (direct) assert(copies == 1 && hidden == 1);
    for (unsigned i = 0; i < 150; i++) (direct ? front : back)[i] = i % 15 + 1;
    g_viewport_forceRedraw = false;
    draws++;
}
static void GUI_Widget_ActionPanel_Draw(bool force) {
    assert(force && active == (direct ? SCREEN_0 : SCREEN_1));
    if (direct) {
        assert(copies == 1 && hidden == 1);
        front[151] = 44;
    }
}
static Widget *GUI_Widget_Get_ByIndex(Widget *head, uint16 index) {
    assert(head == widgets && (index == 1 || index == 2)); return widgets + index - 1;
}
static void GUI_Widget_Draw(Widget *widget) {
    assert((widget == widgets || widget == widgets + 1) && active == SCREEN_1);
}
static Structure *Structure_Find(PoolFindStruct *find) {
    assert(find->houseID == HOUSE_INVALID); return NULL;
}
static void Structure_UpdateMap(Structure *structure) { (void)structure; assert(false); }
static Unit *Unit_Find(PoolFindStruct *find) {
    assert(find->houseID == HOUSE_INVALID); return NULL;
}
static void Unit_UpdateMap(uint16 type, Unit *unit) { (void)type; (void)unit; assert(false); }
static void GUI_Mouse_Hide_Safe(void) { assert(active == SCREEN_0 && !hidden); hidden++; }
static void GUI_Screen_Copy(int xs, int ys, int xd, int yd, int width, int height,
                            Screen source, Screen target) {
    assert(!xs && !ys && !xd && !yd && width == 40 && height == 200);
    assert(source == SCREEN_1 && target == SCREEN_0 && hidden == 1);
    assert(draws == (direct ? 0 : 1));
    memcpy(front, back, sizeof(front)); copies++;
}
static void GUI_DrawCredits(uint16 house, uint16 mode) {
    assert(!house && (mode == 1 || mode == 2));
}
static void GUI_SetPaletteAnimated(uint8 *palette, int ticks) {
    assert(palette == g_palette1 && ticks == 15 && copies == 1);
}
static void GUI_Mouse_Show_Safe(void) {
    assert(hidden == 1 && draws == 1);
    for (unsigned i = 0; i < 150; i++) assert(front[i] == i % 15 + 1);
    assert(front[150] == 42 && front[151] == (direct ? 44 : 43));
    hidden--;
}
static void Input_History_Clear(void) {}
/* PRODUCTION */
int main(void) {
    g_sprites[11] = &sprite;
    for (unsigned machine = 0; machine < 2; machine++) {
#ifdef TOS
        direct = machine != 0;
#else
        (void)machine;
        direct = false;
#endif
        /* Both initial entry and return from a screen that replaced the battlefield.
         * No units exist to repair missing terrain after this function returns. */
        for (unsigned entry = 0; entry < 2; entry++) {
            memset(front, 99, sizeof(front));
            draws = copies = hidden = 0; active = SCREEN_2;
            GUI_DrawInterfaceAndRadar(SCREEN_0);
            assert(draws == 1 && copies == 1 && !hidden && active == SCREEN_2);
            assert(!g_viewport_forceRedraw && g_textDisplayNeedsUpdate);
        }
        if (!direct) {
            memset(front, 99, sizeof(front));
            draws = copies = hidden = 0; active = SCREEN_2;
            GUI_DrawInterfaceAndRadar(SCREEN_1);
            assert(draws == 1 && !copies && !hidden && active == SCREEN_2);
            for (unsigned i = 0; i < 150; i++) assert(back[i] == i % 15 + 1 && front[i] == 99);
        }
    }
    return 0;
}
"""
        harness = harness.replace("/* PRODUCTION */", function(gui, "GUI_DrawInterfaceAndRadar"))
        with tempfile.TemporaryDirectory(prefix="viewport-interface-redraw-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            for platform in ([], ["-DTOS"]):
                subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                                *platform, str(source), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)

    def test_row_preparation_matches_tile_scan(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        production = "\n".join(function(viewport, name) for name in (
            "GUI_Widget_Viewport_ReadRow", "GUI_Widget_Viewport_OrRow",
            "GUI_Widget_Viewport_PrepareRows"))
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
typedef struct { uint16 overlayTileID; } Tile;
static Tile g_map[4096];
static uint8 g_dirtyViewport[512], g_dirtyMinimap[512];
static uint16 g_viewportPosition, g_veiledTileID = 98;
static bool g_debugScenario;
/* PRODUCTION */
static uint32 randomState = 123;
static uint32 next(void) {
    randomState ^= randomState << 13;
    randomState ^= randomState >> 17;
    randomState ^= randomState << 5;
    return randomState;
}
static bool test(const uint8 *bits, unsigned packed) {
    return (bits[packed >> 3] & (1u << (packed & 7))) != 0;
}
static void set(uint8 *bits, unsigned packed, bool value) {
    if (value) bits[packed >> 3] |= 1u << (packed & 7);
    else bits[packed >> 3] &= ~(1u << (packed & 7));
}
static bool reference(uint8 *viewport, uint8 *terrain) {
    bool updated = false;
    for (unsigned y = 0; y < 10; y++) {
        for (unsigned x = 0; x < 15; x++) {
            unsigned packed = g_viewportPosition + y * 64 + x;
            bool v = test(viewport, packed), t = test(terrain, packed);
            uint16 overlay = g_map[packed].overlayTileID;
            if (v) updated = true;
            if (!t && (!v || g_debugScenario ||
                (overlay != g_veiledTileID && overlay != 99))) continue;
            set(viewport, packed, true);
            set(terrain, packed, true);
            updated = true;
        }
    }
    return updated;
}
int main(void) {
    /* Exhaust both row operations at every bitmap alignment, preserving neighbours. */
    for (unsigned shift = 0; shift < 8; shift++) {
        for (unsigned columns = 0; columns <= 0x7fff; columns++) {
            uint8 bits[3] = {0xa5, 0x5a, 0xc3};
            uint32 original = bits[0] | ((uint32)bits[1] << 8) | ((uint32)bits[2] << 16);
            uint16 expected = (original >> shift) & 0x7fff;
            assert(GUI_Widget_Viewport_ReadRow(bits, shift) == expected);
            GUI_Widget_Viewport_OrRow(bits, shift, columns);
            uint32 result = bits[0] | ((uint32)bits[1] << 8) | ((uint32)bits[2] << 16);
            assert(result == (original | ((uint32)columns << shift)));
            assert(GUI_Widget_Viewport_ReadRow(bits, shift) == (expected | columns));
        }
    }
    /* Includes all alignments, final map row, outside-viewport sentinels,
     * quiet/dense/sparse rows, both fog kinds, partial fog and debug mode. */
    for (unsigned origin = 0; origin <= 49; origin++)
        for (unsigned top = 0; top <= 54; top += 27)
            for (unsigned debug = 0; debug < 2; debug++)
                for (unsigned pattern = 0; pattern < 10; pattern++) {
                    uint8 expectedViewport[512], expectedTerrain[512];
                    static const uint16 overlays[] = {0, 97, 98, 99, 100};
                    for (unsigned i = 0; i < 512; i++) {
                        g_dirtyViewport[i] = next();
                        g_dirtyMinimap[i] = next();
                    }
                    for (unsigned i = 0; i < 4096; i++)
                        g_map[i].overlayTileID = overlays[next() % 5];
                    g_viewportPosition = top * 64 + origin;
                    g_debugScenario = debug != 0;
                    for (unsigned y = 0; y < 10; y++) {
                        for (unsigned x = 0; x < 15; x++) {
                            unsigned packed = g_viewportPosition + y * 64 + x;
                            bool v, t;
                            if (pattern < 4) {
                                v = (pattern & 1) != 0;
                                t = (pattern & 2) != 0;
                            } else if (pattern == 4) {
                                v = (x & 1) != 0; t = !v;
                            } else if (pattern == 5) {
                                v = x == 0; t = x == 14;
                            } else if (pattern == 6) {
                                v = x == 14; t = x == 0;
                            } else if (pattern == 7) {
                                v = y == 9; t = y == 0;
                            } else {
                                v = (next() & 7) == 0;
                                t = (next() & 7) == 0;
                            }
                            set(g_dirtyViewport, packed, v);
                            set(g_dirtyMinimap, packed, t);
                        }
                    }
                    memcpy(expectedViewport, g_dirtyViewport, 512);
                    memcpy(expectedTerrain, g_dirtyMinimap, 512);
                    bool expected = reference(expectedViewport, expectedTerrain);
                    assert(GUI_Widget_Viewport_PrepareRows(99) == expected);
                    assert(memcmp(g_dirtyViewport, expectedViewport, 512) == 0);
                    assert(memcmp(g_dirtyMinimap, expectedTerrain, 512) == 0);
                }
    return 0;
}
"""
        harness = harness.replace("/* PRODUCTION */", production)
        with tempfile.TemporaryDirectory(prefix="viewport-row-preparation-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                            "-Werror", *flags, str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_copy_bookkeeping_and_messages(self):
        viewport = function(
            (ROOT / "src/gui/viewport.c").read_text(), "GUI_Widget_Viewport_Draw")
        setup = viewport[viewport.index("\tbool updateDisplay;"):viewport.index(
            "\n#ifdef TOS\n\toldScreenID")]
        self.assertNotRegex(setup, r"dirtyColumns\[10\]\s*=")
        for declaration in ("static int16 minX[10];", "static int16 maxX[10];",
                            "static uint16 dirtyColumns[10];"):
            self.assertIn(declaration, setup)
        self.assertNotIn("g_viewport_fadein", setup)
        setup = setup.replace("\tupdateDisplay = forceRedraw;", """
    memset(minX, 0x5a, sizeof(minX));
    memset(maxX, 0x5a, sizeof(maxX));
#ifdef GFX_STORE_DIRTY_AREA_BLOCKS
    memset(dirtyColumns, 0x5a, sizeof(dirtyColumns));
#endif
    updateDisplay = forceRedraw;
""")
        first = viewport.index("\tif ((g_viewportMessageCounter & 1)")
        last = viewport.index("\n\tif (updateDisplay && !drawToMainScreen", first)
        message = viewport[first:last]
        publication = viewport[last:viewport.index("{", last) + 1]
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
typedef int16_t int16;
typedef uint16_t uint16;
typedef int Screen;
typedef struct { uint16 index, type, houseID; } PoolFindStruct;
static uint16 g_viewportMessageCounter;
static const char *g_viewportMessageText;
static bool g_viewport_fadein, ready, s_viewportWasPlanar;
static bool g_selectionRectangleNeedRepaint;
static unsigned draws;
#ifdef TOS
static bool Video_Atari_CursorDirect(void) { return ready; }
static bool GFX_PlanarTilesReady(void) { return true; }
static bool GUI_ViewportSpriteCacheReady(void) { return true; }
#endif
static void GUI_DrawText_Wrapper(const char *text, int x, int y, int fg, int bg, int flags) {
    assert(text == g_viewportMessageText && x == 112 && y == 139);
    assert(fg == 15 && bg == 0 && flags == 0x132);
    draws++;
}
static void check(bool drawToMainScreen, bool forceRedraw, bool hasScrolled, bool planarShifted) {
    bool expectedPlanar = false;
    (void)hasScrolled; (void)planarShifted;
#ifdef TOS
    expectedPlanar = ready;
    s_viewportWasPlanar = expectedPlanar;
#endif
    /* SETUP */
    assert(trackCopyDamage == !expectedPlanar);
    bool visible = (g_viewportMessageCounter & 1) && g_viewportMessageText != NULL;
    for (unsigned row = 0; row < 10; row++) {
        assert(minX[row] == (expectedPlanar ? 0x5a5a : 0x0f0f));
        assert(maxX[row] == (expectedPlanar ? 0x5a5a : 0));
#ifdef GFX_STORE_DIRTY_AREA_BLOCKS
        assert(dirtyColumns[row] == (expectedPlanar ? 0x5a5a : 0));
#endif
    }
    draws = 0;
    /* MESSAGE */
    assert(draws == visible);
    for (unsigned row = 0; row < 10; row++) {
        bool messageRow = visible && row == 6;
        assert(minX[row] == (expectedPlanar ? 0x5a5a : messageRow ? -1 : 0x0f0f));
        assert(maxX[row] == (expectedPlanar ? 0x5a5a : messageRow ? 14 : 0));
#ifdef GFX_STORE_DIRTY_AREA_BLOCKS
        assert(dirtyColumns[row] == (expectedPlanar ? 0x5a5a : messageRow ? 0x7fff : 0));
#endif
    }
    bool published = false;
    /* PUBLICATION */
        published = true;
    }
    assert(published == (forceRedraw && !drawToMainScreen && !expectedPlanar));
}
int main(void) {
    for (unsigned state = 0; state < 64; state++) {
        ready = (state & 1) != 0;
#ifdef TOS
        if (ready && (state & 4)) continue;
#endif
        g_viewport_fadein = (state & 2) != 0;
        for (unsigned counter = 0; counter <= 4; counter++)
            for (unsigned text = 0; text < 2; text++) {
                g_viewportMessageCounter = counter;
                g_viewportMessageText = text ? "Feedback" : NULL;
                check((state & 4) != 0, (state & 8) != 0,
                      (state & 16) != 0, (state & 32) != 0);
            }
    }
    return 0;
}
"""
        harness = harness.replace("/* SETUP */", setup)
        harness = harness.replace("/* MESSAGE */", message)
        harness = harness.replace("/* PUBLICATION */", publication)
        with tempfile.TemporaryDirectory(prefix="viewport-copy-bookkeeping-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            for platform in ([], ["-DTOS", "-DGFX_STORE_DIRTY_AREA_BLOCKS"]):
                subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                                "-Werror", "-Wno-unused-variable", *flags, *platform,
                                str(source), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)

    def test_sandworm_reserved_slots(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        start = viewport.index("\t/* Draw Sandworm */")
        worm = viewport[start:viewport.index("\n\tif (g_unitSelected == NULL", start)]
        pool = (ROOT / "src/pool/unit.c").read_text()
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef struct {
    struct {
        struct { struct { bool used, isNotOnMap, isDirty; } s; } flags;
        uint16 type, position, houseID;
    } o;
    uint16 targetLast, targetPreLast;
} Unit;
typedef struct { uint16 type, index, houseID; } PoolFindStruct;
#define UNIT_SANDWORM 25
#define UNIT_INDEX_INVALID 0xffff
#define HOUSE_INVALID 0xffff
#define SCREEN_ACTIVE 0
#define GUI_SPRITE_COLOUR_EMBEDDED 0
#define DRAWSPRITE_FLAG_BLUR 1
#define DRAWSPRITE_FLAG_WIDGETPOS 2
#define DRAWSPRITE_FLAG_CENTER 4
static Unit units[102], *g_unitSelected;
static struct { uint16 indexStart, indexEnd, groundSpriteID; } g_table_unitInfo[27] = {
    [UNIT_SANDWORM] = {16, 17, 111}
};
static struct { bool isUnveiled; } g_map[4096];
static uint8 pixels[112], *g_sprites[112];
static bool g_debugScenario, visible[4096];
static uint16 g_validateStrictIfZero;
static unsigned peeks, draws, checks;
static uint16 drawn[8], checked[8];
static Unit *Unit_Get_ByIndex(uint16 index) {
    assert(index == 16 || index == 17);
    peeks++;
    return &units[index];
}
static uint16 Unit_GetHouseID(Unit *u) { return u->o.houseID; }
#ifndef TOS
static Unit *g_unitFindArray[102];
static uint16 g_unitFindCount;
/* FIND */
#endif
static uint16 Tile_PackTile(uint16 position) { return position; }
static bool Map_IsPositionInViewport(uint16 position, uint16 *x, uint16 *y) {
    assert(checks < 8);
    checked[checks++] = position;
    *x = position; *y = 0;
    return visible[position];
}
static void GUI_DrawSprite(int screen, uint8 *sprite, uint16 id, int colour,
                           uint16 x, uint16 y, int widget, int flags) {
    assert(screen == 0 && sprite == g_sprites[id] && colour == 0 && y == 0 && widget == 2);
    assert(flags == (id == 6 ? 6 : 7));
    assert(draws < 8);
    drawn[draws++] = id == 6 ? 1000 + x : x;
}
static void draw(bool forceRedraw) {
    uint16 i = 0, x, y;
    PoolFindStruct find = {0};
    (void)i; (void)find;
    /* WORM */
}
static void reset(void) {
    memset(units, 0, sizeof(units));
    memset(g_map, 0, sizeof(g_map));
    memset(visible, 0, sizeof(visible));
    peeks = draws = checks = 0;
    g_debugScenario = false;
    g_validateStrictIfZero = 0;
    g_unitSelected = NULL;
    for (unsigned i = 0; i < 112; i++) g_sprites[i] = &pixels[i];
    for (unsigned i = 16; i <= 17; i++) {
        Unit *u = &units[i];
        u->o.type = UNIT_SANDWORM;
        u->o.position = i;
        u->targetLast = i + 100;
        u->targetPreLast = i + 200;
        g_map[i].isUnveiled = true;
        visible[i] = visible[i + 100] = visible[i + 200] = true;
    }
#ifndef TOS
    g_unitFindCount = 0;
#endif
}
static void activate(unsigned i) {
    units[i].o.flags.s.used = true;
    units[i].o.flags.s.isDirty = true;
#ifndef TOS
    g_unitFindArray[g_unitFindCount++] = &units[i];
#endif
}
int main(void) {
    reset();
    draw(true);
    assert(!draws && !checks);
#ifdef TOS
    assert(peeks == 2);
#else
    assert(!peeks);
#endif
    /* Empty/wrong-type/off-map slots must not consume dirty flags. */
    reset();
    activate(16); activate(17);
    units[16].o.type = 0;
    units[17].o.flags.s.isNotOnMap = true;
    draw(true);
    assert(!draws && !checks);
    assert(units[16].o.flags.s.isDirty && units[17].o.flags.s.isDirty);
    /* Both worms, three positions each, plus selection; stable slot order on TOS. */
    reset();
    activate(17); activate(16);
    g_unitSelected = &units[17];
    draw(false);
    assert(draws == 7 && checks == 7);
    assert(!units[16].o.flags.s.isDirty && !units[17].o.flags.s.isDirty);
#ifdef TOS
    assert(peeks == 2);
    assert(drawn[0] == 16 && drawn[1] == 116 && drawn[2] == 216);
    assert(drawn[3] == 17 && drawn[6] == 1017);
#else
    assert(!peeks);
    assert(drawn[0] == 17 && drawn[3] == 1017 && drawn[4] == 16);
#endif
    /* Clean worm, forced redraw, fog and debug fog override. */
    reset(); activate(16);
    units[16].o.flags.s.isDirty = false;
    draw(false);
    assert(!draws && !checks);
    draw(true);
    assert(draws == 3);
    reset(); activate(16);
    g_map[16].isUnveiled = false;
    draw(false);
    assert(!draws && !checks && !units[16].o.flags.s.isDirty);
    g_debugScenario = true;
    draw(true);
    assert(draws == 3);
    /* A trailing position can be visible while the current position is outside. */
    reset(); activate(16);
    visible[16] = visible[216] = false;
    draw(false);
    assert(draws == 1 && drawn[0] == 116 && checks == 3);
    /* Match Unit_Find's strict-validation exception for off-map units. */
    reset(); activate(17);
    units[17].o.flags.s.isNotOnMap = true;
    g_validateStrictIfZero = 1;
    draw(false);
    assert(draws == 3 && !units[17].o.flags.s.isDirty);
    return 0;
}
"""
        harness = harness.replace("/* WORM */", worm)
        harness = harness.replace("/* FIND */", function(pool, "Unit_Find"))
        with tempfile.TemporaryDirectory(prefix="viewport-worm-slots-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            for platform in ([], ["-DTOS"]):
                subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                                "-Werror", "-Wno-unused-function", *flags, *platform,
                                str(source), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)

    def test_hidden_tile_damage_gate(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        start = viewport.index("\tif (g_dirtyViewportCount != 0 || forceRedraw) {")
        terrain = viewport[start:viewport.index(
            "\n#ifdef TOS\n\tGUI_Widget_Viewport_BeginSpriteDamage", start)]
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
typedef int16_t int16;
typedef struct { uint16 groundTileID, overlayTileID; uint8 houseID; } Tile;
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
#define ICM_ICONGROUP_FOG_OF_WAR 1
static Tile g_map[4096];
static uint8 g_dirtyViewport[512], g_dirtyMinimap[512], screen[200][320];
static uint16 g_dirtyViewportCount, g_viewportPosition, g_veiledTileID = 98;
static uint16 g_iconMap[32] = {[1] = 16, [31] = 99};
static bool g_debugScenario, s_viewportRepairActive;
static uint8 s_viewportSelectionTiles[10][15], s_viewportSelectionPen;
static void GFX_DrawPlanarSelectionTile(uint16 id, uint16 overlay, uint16 x, uint16 y,
                                        uint8 house, uint8 selection, uint8 pen) {
    (void)id; (void)overlay; (void)x; (void)y; (void)house; (void)selection; (void)pen;
    assert(false);
}
static unsigned fogDraws, groundDraws, partialDraws, filledDraws;
static bool BitArray_Test(const uint8 *a, uint16 i) { return (a[i >> 3] >> (i & 7)) & 1; }
static void BitArray_Set(uint8 *a, uint16 i) { a[i >> 3] |= 1u << (i & 7); }
static void BitArray_Clear(uint8 *a, uint16 i) { a[i >> 3] &= ~(1u << (i & 7)); }
static uint16 Tile_PackXY(uint16 x, uint16 y) { return y * 64 + x; }
static void paint(uint16 x, uint16 y, uint8 c) {
    for (unsigned row = y; row < y + 16; row++) memset(screen[row] + x, c, 16);
}
static void GFX_DrawTile(uint16 tile, uint16 x, uint16 y, uint8 house) {
    (void)house; groundDraws++; paint(x, y, tile);
}
static void GFX_DrawPlanarTile(uint16 tile, uint16 x, uint16 y, uint8 house) {
    assert(!BitArray_Test(g_dirtyMinimap, g_viewportPosition + Tile_PackXY(x >> 4, (y - 40) >> 4)));
    GFX_DrawTile(tile, x, y, house);
}
static void GFX_DrawPlanarTileFogged(uint16 tile, uint16 fog, uint16 x, uint16 y, uint8 house) {
    assert(fog == 97);
    (void)house; partialDraws++;
    for (unsigned row = y; row < y + 16; row++)
        for (unsigned col = x; col < x + 16; col++) screen[row][col] = col & 1 ? 12 : tile;
}
static void GFX_DrawPlanarFogTile(uint16 x, uint16 y) {
    assert(!BitArray_Test(g_dirtyMinimap, g_viewportPosition + Tile_PackXY(x >> 4, (y - 40) >> 4)));
    fogDraws++; paint(x, y, 12);
}
static void GUI_DrawFilledRectangle(uint16 l, uint16 t, uint16 r, uint16 b, uint8 c) {
    assert(r == l + 15 && b == t + 15 && c == 12);
    filledDraws++; paint(l, t, c);
}
/* REPAIR */
static bool scan(bool planarViewport, bool forceRedraw) {
    bool drawToMainScreen = true, updateDisplay = forceRedraw;
    bool trackCopyDamage = !planarViewport;
    uint16 x, y, curPos, fullyFoggedTileID = 99;
    int16 minX[10], maxX[10];
    uint16 dirtyColumns[10];
    for (y = 0; y < 10; y++) {
        minX[y] = planarViewport ? 0x5a5a : 15;
        maxX[y] = planarViewport ? 0x5a5a : 0;
        dirtyColumns[y] = planarViewport ? 0x5a5a : 0;
    }
    s_viewportRepairActive = planarViewport;
    /* TERRAIN */
    for (y = 0; y < 10; y++) {
        if (planarViewport) {
            assert(minX[y] == 0x5a5a && maxX[y] == 0x5a5a);
            assert(dirtyColumns[y] == 0x5a5a);
        } else {
            bool dirty = forceRedraw || (y == 0 && updateDisplay);
            assert(minX[y] == (dirty ? 0 : 15));
            assert(maxX[y] == (forceRedraw ? 14 : 0));
            assert(dirtyColumns[y] == (forceRedraw ? 0x7fff : dirty ? 1 : 0));
        }
    }
    return updateDisplay;
}
static void reset(void) {
    memset(g_dirtyViewport, 0, sizeof(g_dirtyViewport));
    memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
    memset(g_map, 0, sizeof(g_map));
    memset(screen, 88, sizeof(screen));
    g_dirtyViewportCount = 1;
    fogDraws = groundDraws = partialDraws = filledDraws = 0;
}
int main(void) {
    for (unsigned planar = 0; planar < 2; planar++)
        for (unsigned dirty = 0; dirty < 4; dirty++)
            for (unsigned tile = 0; tile < 4; tile++)
                for (unsigned debug = 0; debug < 2; debug++) {
                    reset();
                    g_map[0].groundTileID = 7;
                    g_map[0].overlayTileID = tile == 0 ? 0 : tile == 1 ? 97 : tile == 2 ? 98 : 99;
                    g_debugScenario = debug != 0;
                    if (dirty & 1) BitArray_Set(g_dirtyViewport, 0);
                    if (dirty & 2) BitArray_Set(g_dirtyMinimap, 0);
                    bool updated = scan(planar != 0, false);
                    bool hidden = tile >= 2 && !debug;
                    bool restored = (dirty & 2) || (planar && hidden && (dirty & 1));
                    assert(updated == (dirty != 0));
                    if (planar) {
                        assert(!fogDraws && !groundDraws && !partialDraws && !filledDraws);
                        assert(BitArray_Test(g_dirtyMinimap, 0) == restored);
                        GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
                    }
                    assert(fogDraws == (restored && hidden && planar));
                    assert(filledDraws == (restored && hidden && !planar));
                    assert(partialDraws == (restored && planar && tile == 1 && !debug));
                    assert(groundDraws == (restored && !hidden && !partialDraws ?
                        1u + (tile != 0 && !debug) : 0u));
                    assert(BitArray_Test(g_dirtyViewport, 0) == ((dirty & 1) != 0 || restored));
                    assert(!g_dirtyViewportCount);
                }
    reset();
    g_debugScenario = false;
    g_map[0].overlayTileID = 98;
    BitArray_Set(g_dirtyViewport, 0);
    g_dirtyViewportCount = 0;
    assert(!scan(true, false));
    assert(!BitArray_Test(g_dirtyMinimap, 0));
    assert(BitArray_Test(g_dirtyViewport, 0));
    assert(scan(true, true));
    GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
    assert(fogDraws == 1 && groundDraws == 149 && !filledDraws);
    /* Old sprite pixels in both hidden tiles; only viewport footprint damage. */
    reset();
    g_map[0].overlayTileID = 98;
    g_map[1].overlayTileID = 99;
    BitArray_Set(g_dirtyViewport, 0);
    BitArray_Set(g_dirtyViewport, 1);
    assert(scan(true, false));
    GUI_Widget_Viewport_RepairTiles(0, 40, 16, 56);
    screen[45][3] = 5; /* Current foreground after its background repair. */
    GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
    assert(fogDraws == 2 && screen[45][3] == 5 && screen[45][20] == 12);
    assert(screen[45][35] == 88); /* Undamaged hidden/visible neighbours stay untouched. */
    GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
    assert(fogDraws == 2 && screen[45][3] == 5);
    /* A moving unit crosses hidden, dithered and unveiled terrain. */
    reset();
    g_map[0].overlayTileID = 98;
    g_map[1].groundTileID = g_map[2].groundTileID = 7;
    g_map[1].overlayTileID = 97;
    BitArray_Set(g_dirtyViewport, 0);
    BitArray_Set(g_dirtyMinimap, 1);
    BitArray_Set(g_dirtyMinimap, 2);
    assert(scan(true, false));
    GUI_Widget_Viewport_RepairTiles(20, 45, 38, 46);
    memset(screen[45] + 20, 5, 18);
    GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
    assert(fogDraws == 1 && partialDraws == 1 && groundDraws == 1);
    assert(screen[45][3] == 12 && screen[45][16] == 7 && screen[45][17] == 12);
    assert(screen[45][20] == 5 && screen[45][37] == 5 && screen[45][38] == 7);
    GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
    assert(fogDraws == 1 && partialDraws == 1 && groundDraws == 1 && screen[45][20] == 5);
    return 0;
}
"""
        harness = harness.replace("/* TERRAIN */", terrain)
        harness = harness.replace("/* REPAIR */", "\n".join(
            function(viewport, name) for name in (
                "GUI_Widget_Viewport_ReadRow", "GUI_Widget_Viewport_OrRow",
                "GUI_Widget_Viewport_PrepareRows", "GUI_Widget_Viewport_RepairTiles")))
        with tempfile.TemporaryDirectory(prefix="viewport-fog-damage-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            subprocess.run([*compiler, "-std=c99", "-O2", "-DTOS",
                            "-DGFX_STORE_DIRTY_AREA_BLOCKS", *flags,
                            str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_aircraft_shadow_and_mandatory_planar_policy(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        self.assertNotIn("CanDrawPlanar", viewport)
        draw = function(viewport, "GUI_Widget_Viewport_Draw")
        self.assertIn("bool planarViewport = directViewport;", draw)
        self.assertIn("assert(!planarViewport ||", draw)
        shadow_gate = re.search(r"if \(ui->o.flags.hasShadow.*?\) \{", viewport, re.S).group()
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
typedef uint16_t uint16;
typedef struct {
    struct { struct { bool blurTile, hasShadow; } flags; } o;
    uint16 groundSpriteID, destroyedSpriteID, turretSpriteID;
} UnitInfo;
static bool draws_shadow(bool shadow, bool directViewport) {
    UnitInfo info = {0};
    const UnitInfo *ui = &info;
    info.o.flags.hasShadow = shadow;
    (void)directViewport;
    /* SHADOW GATE */
        return true;
    }
    return false;
}
int main(void) {
    assert(!draws_shadow(false, false));
    assert(!draws_shadow(false, true));
    assert(draws_shadow(true, false));
#ifdef TOS
    assert(!draws_shadow(true, true));
#else
    assert(draws_shadow(true, true));
#endif
    return 0;
}
"""
        harness = harness.replace("/* SHADOW GATE */", shadow_gate)
        with tempfile.TemporaryDirectory(prefix="viewport-aircraft-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            for platform in ([], ["-DTOS"]):
                subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                                "-Werror", *flags, *platform, str(source), "-o", str(binary)],
                               check=True)
                subprocess.run([str(binary)], check=True)

    def test_stock_actor_sprite_cache_coverage(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        cache = function(gui, "GUI_InitViewportSpriteCache")
        bounds = re.search(
            r"for \(id = (\d+); id <= (\d+); id = id == (\d+) \? (\d+) : id \+ 1\)",
            cache,
        )
        self.assertIsNotNone(bounds)
        special, last, selector, first = map(int, bounds.groups())
        self.assertEqual(special, selector)
        prepared = {special, *range(first, last + 1)}
        units = (ROOT / "src/table/unitinfo.c").read_text()
        entries = re.findall(
            r'/\* name\s+\*/ "([^"]+)",.*?'
            r'/\* groundSpriteID\s+\*/ (\d+),\s*'
            r'/\* turretSpriteID\s+\*/ (-?\d+),.*?'
            r'/\* displayMode\s+\*/ (\w+),\s*'
            r'/\* destroyedSpriteID\s+\*/ (\d+)', units, re.S,
        )
        self.assertEqual(len(entries), len(re.findall(r"/\* name\s+\*/", units)))
        self.assertGreater(len(entries), 0)
        for name, body, turret, mode, destroyed in entries:
            with self.subTest(unit=name):
                body, turret, destroyed = map(int, (body, turret, destroyed))
                if mode == "DISPLAYMODE_INFANTRY_4_FRAMES":
                    offsets = range(12)
                elif mode == "DISPLAYMODE_INFANTRY_3_FRAMES":
                    offsets = range(9)
                elif mode == "DISPLAYMODE_ORNITHOPTER":
                    offsets = range(9)
                elif mode == "DISPLAYMODE_ROCKET":
                    offsets = range(10)
                elif mode == "DISPLAYMODE_UNIT":
                    offsets = range(6)
                else:
                    offsets = range(2)
                self.assertTrue({body + i for i in offsets} <= prepared)
                if turret != -1:
                    self.assertTrue({turret + i for i in range(5)} <= prepared)
                if destroyed:
                    # spriteOffset is signed 8-bit; cover every negative value.
                    self.assertTrue({destroyed - i - 1 for i in range(-128, 0)} <= prepared)
        explosions = (ROOT / "src/table/explosion.c").read_text()
        frames = set(map(int, re.findall(
            r"\{\s*EXPLOSION_SET_SPRITE\s*,\s*(\d+)\s*\}", explosions,
        )))
        self.assertGreater(len(frames), 0)
        self.assertTrue(frames <= prepared)

    def test_pending_tile_repair(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int16_t int16;
typedef uint32_t uint32;
typedef struct { uint16 groundTileID, overlayTileID; uint8 houseID; } Tile;
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
#define ICM_ICONGROUP_FOG_OF_WAR 1
static bool s_viewportRepairActive, g_debugScenario;
static uint8 s_viewportSelectionTiles[10][15], s_viewportSelectionPen;
static void GFX_DrawPlanarSelectionTile(uint16 id, uint16 overlay, uint16 x, uint16 y,
                                        uint8 house, uint8 selection, uint8 pen) {
    (void)id; (void)overlay; (void)x; (void)y; (void)house; (void)selection; (void)pen;
    assert(false);
}
static uint16 g_viewportPosition, g_veiledTileID = 98, g_iconMap[32];
static uint8 g_dirtyMinimap[512], g_dirtyViewport[512];
static Tile g_map[4096];
static uint8 screen[200][320], expected[200][320];
static unsigned repaired[150], fogged, filled, draws;
static bool BitArray_Test(const uint8 *bits, uint16 p) { return (bits[p >> 3] >> (p & 7)) & 1; }
static void BitArray_Set(uint8 *bits, uint16 p) { bits[p >> 3] |= 1u << (p & 7); }
static void BitArray_Clear(uint8 *bits, uint16 p) { bits[p >> 3] &= ~(1u << (p & 7)); }
static uint16 Tile_PackXY(uint16 x, uint16 y) { return x + 64 * y; }
static void tile(uint16 x, uint16 y, uint8 colour) {
    assert(!(x & 15) && x < 240 && y >= 40 && !((y - 40) & 15) && y < 200);
    uint16 packed = g_viewportPosition + Tile_PackXY(x >> 4, (y - 40) >> 4);
    assert(!BitArray_Test(g_dirtyMinimap, packed));
    for (uint16 row = y; row < y + 16; row++) memset(screen[row] + x, colour, 16);
    draws++;
}
static void GFX_DrawPlanarTile(uint16 id, uint16 x, uint16 y, uint8 house) {
    assert(house == 0);
    if (id == 7) assert(++repaired[(y - 40) / 16 * 15 + x / 16] == 1);
    tile(x, y, id);
}
static void GFX_DrawPlanarTileFogged(uint16 id, uint16 overlay, uint16 x, uint16 y, uint8 house) {
    assert(id == 7 && (overlay == 97 || overlay == 9) && house == 0);
    fogged++;
    tile(x, y, overlay);
}
static void GFX_DrawPlanarFogTile(uint16 x, uint16 y) {
    filled++;
    tile(x, y, 12);
}
/* REPAIR */
static void reset(void) {
    memset(screen, 88, sizeof(screen));
    memset(expected, 7, sizeof(expected));
    memset(repaired, 0, sizeof(repaired));
    memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
    memset(g_dirtyViewport, 0xff, sizeof(g_dirtyViewport));
    memset(g_map, 0, sizeof(g_map));
    g_viewportPosition = Tile_PackXY(19, 23);
    g_iconMap[1] = 16; g_iconMap[31] = 99;
    s_viewportRepairActive = true;
    g_debugScenario = false;
    fogged = filled = draws = 0;
    for (unsigned y = 0; y < 10; y++) for (unsigned x = 0; x < 15; x++) {
        uint16 p = g_viewportPosition + Tile_PackXY(x, y);
        g_map[p].groundTileID = 7;
        BitArray_Set(g_dirtyMinimap, p);
    }
}
static void sprite(int16 l, int16 t, int16 r, int16 b, uint8 colour) {
    GUI_Widget_Viewport_RepairTiles(l, t, r, b);
    for (int y = max(t, 40); y < min(b, 200); y++)
        for (int x = max(l, 0); x < min(r, 240); x++)
            if ((x + y + colour) % 3) screen[y][x] = expected[y][x] = colour;
}
static void compare(void) {
    GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
    assert(draws == 150);
    for (unsigned y = 0; y < 200; y++) for (unsigned x = 0; x < 320; x++) {
        if (y >= 40 && x < 240) assert(screen[y][x] == expected[y][x]);
        else assert(screen[y][x] == 88);
    }
    for (unsigned i = 0; i < 512; i++) assert(g_dirtyViewport[i] == 0xff);
    GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
    assert(draws == 150);
}
int main(void) {
    reset();
    s_viewportRepairActive = false;
    GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
    assert(draws == 0);
    s_viewportRepairActive = true;
    GUI_Widget_Viewport_RepairTiles(-32, -32, 0, 40);
    GUI_Widget_Viewport_RepairTiles(240, 200, 300, 220);
    GUI_Widget_Viewport_RepairTiles(20, 60, 20, 80);
    assert(draws == 0);
    /* Clipped sprites, overlapping painter layers and selection bounds. */
    sprite(-17, 25, 17, 57, 2);
    assert(draws == 4);
    sprite(15, 40, 49, 73, 3);
    assert(draws == 12);
    sprite(25, 51, 71, 93, 4);
    sprite(0, 39, 241, 41, 15);
    sprite(231, 187, 265, 218, 5);
    compare();
    /* Every viewport edge and tile boundary, with transparent sprite holes. */
    for (int y = 24; y <= 200; y += 16) for (int x = -16; x <= 240; x += 16) {
        reset();
        sprite(x - 1, y - 1, x + 17, y + 17, 2);
        sprite(x + 3, y + 3, x + 20, y + 20, 3);
        compare();
    }
    reset();
    uint16 p = g_viewportPosition;
    memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
    BitArray_Set(g_dirtyMinimap, p);
    g_map[p].overlayTileID = 97;
    GUI_Widget_Viewport_RepairTiles(0, 40, 16, 56);
    assert(fogged == 1 && screen[40][0] == 97);
    BitArray_Set(g_dirtyMinimap, p);
    g_map[p].overlayTileID = 98;
    GUI_Widget_Viewport_RepairTiles(0, 40, 16, 56);
    assert(filled == 1 && screen[40][0] == 12 && !BitArray_Test(g_dirtyMinimap, p));
    for (unsigned id = 98; id <= 99; id++) {
        BitArray_Set(g_dirtyMinimap, p);
        g_map[p].overlayTileID = id;
        GUI_Widget_Viewport_RepairTiles(0, 40, 16, 56);
        assert(screen[40][0] == 12);
    }
    assert(filled == 3);
    reset();
    memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
    BitArray_Set(g_dirtyMinimap, g_viewportPosition);
    g_map[g_viewportPosition].overlayTileID = 9;
    GUI_Widget_Viewport_RepairTiles(0, 40, 16, 56);
    assert(draws == 1 && fogged == 1 && screen[40][0] == 9);
    reset();
    g_debugScenario = true;
    g_map[g_viewportPosition].overlayTileID = 98;
    GUI_Widget_Viewport_RepairTiles(0, 40, 16, 56);
    assert(draws == 1 && screen[40][0] == 7);
    /* Every byte alignment, including the bottom-right two-byte range. */
    for (unsigned origin = 0; origin <= 49; origin++) {
        reset();
        g_viewportPosition = Tile_PackXY(origin, 54);
        memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
        for (unsigned row = 0; row < 10; row++) for (unsigned col = 0; col < 15; col++)
            g_map[g_viewportPosition + Tile_PackXY(col, row)].groundTileID = 7;
        GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
        assert(draws == 0);
        uint16 rowBase = g_viewportPosition + Tile_PackXY(0, 9);
        BitArray_Set(g_dirtyMinimap, rowBase + 2);
        BitArray_Set(g_dirtyMinimap, rowBase + 7);
        BitArray_Set(g_dirtyMinimap, rowBase + 14);
        if (origin != 0) BitArray_Set(g_dirtyMinimap, rowBase - 1);
        if (origin < 49) BitArray_Set(g_dirtyMinimap, rowBase + 15);
        /* Restrict repair to columns 1-3; leave the other set bits intact. */
        GUI_Widget_Viewport_RepairTiles(16, 184, 64, 200);
        assert(draws == 1 && screen[184][32] == 7);
        assert(!BitArray_Test(g_dirtyMinimap, rowBase + 2));
        assert(BitArray_Test(g_dirtyMinimap, rowBase + 7));
        assert(BitArray_Test(g_dirtyMinimap, rowBase + 14));
        GUI_Widget_Viewport_RepairTiles(16, 184, 64, 200);
        assert(draws == 1);
        GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
        assert(draws == 3 && screen[184][112] == 7 && screen[184][224] == 7);
        if (origin != 0) assert(BitArray_Test(g_dirtyMinimap, rowBase - 1));
        if (origin < 49) assert(BitArray_Test(g_dirtyMinimap, rowBase + 15));
        GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
        assert(draws == 3);
    }
    return 0;
}
"""
        harness = harness.replace(
            "/* REPAIR */", "\n".join(function(viewport, name) for name in (
                "GUI_Widget_Viewport_ReadRow", "GUI_Widget_Viewport_RepairTiles")))
        with tempfile.TemporaryDirectory(prefix="viewport-phase-reversal-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                            "-Werror", str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_publication_order(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        gui = (ROOT / "src/gui/gui.c").read_text()
        gfx = (ROOT / "src/gfx.c").read_text()
        video = (ROOT / "src/video/video_atari.c").read_text()
        self.assertNotIn("GFX_QueueViewportTile", gfx)
        self.assertNotIn("GFX_ViewportSpriteMasks", gfx)
        self.assertNotIn("Video_Atari_RestorePlanarTile", video)
        draw = function(viewport, "GUI_Widget_Viewport_Draw")
        deferred = draw.index("BitArray_Set(g_dirtyMinimap, curPos);")
        self.assertIn("if (planarViewport)", draw[deferred - 40:deferred])
        self.assertIn("continue;", draw[deferred:deferred + 90])
        self.assertLess(deferred, draw.index("/* Draw Sandworm */"))
        self.assertLess(draw.index("GUI_Widget_Viewport_RepairTiles((int16)x1"),
                        draw.index("GUI_DrawWiredRectangle"))
        finish = draw.index("GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);")
        self.assertLess(draw.index("/* draw explosions */"), finish)
        self.assertLess(finish, draw.index("s_viewportRepairActive = false;"))
        self.assertLess(finish, draw.index("/* draw air units */"))
        self.assertLess(draw.index("/* draw air units */"),
                        draw.index("memset(g_dirtyViewport"))
        cached = function(gui, "GUI_ViewportPlanarSprite")
        repair = cached.index("GUI_Widget_Viewport_RepairTiles",
                              cached.index("for (i = 0; i < entry->width; i += 16)"))
        self.assertIn("column, row, column + 16, end", cached[repair:repair + 100])
        self.assertLess(cached.index("for (i = 0; i < entry->width; i += 16)"), repair)
        self.assertLess(cached.index("for (row = firstRow; row < bottom; )"), repair)
        self.assertLess(repair, cached.index("Video_Atari_PresentPlanarSpriteStrided"))
        self.assertIn("entry->masks + offset, 16, end - row, column, row, entry->width", cached)
        fallback = function(gui, "GUI_DrawSpriteInternal")
        self.assertNotIn("GUI_Widget_Viewport_RepairTiles", fallback)
        self.assertNotIn("Video_Atari_PresentSprite(", fallback)
        self.assertIn("assert(target != NULL || windowID != 2 || !Video_Atari_CursorDirect())", fallback)


if __name__ == "__main__":
    unittest.main()
