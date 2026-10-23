"""Exercise native structure-outline geometry and deferred tile repair."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class PlanarSelectionTest(unittest.TestCase):
    def test_selection_lifecycle_and_repair(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        state = viewport[viewport.index("static uint8 s_viewportSelectionTiles"):
                         viewport.index("\nstatic void GUI_Widget_Viewport_PrepareSelection")]
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int16_t int16;
typedef uint32_t uint32;
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
#define GFX_SELECTION_TOP 0x10
#define GFX_SELECTION_BOTTOM 0x20
#define GFX_SELECTION_LEFT 0x40
#define GFX_SELECTION_RIGHT 0x80
#define SELECTIONTYPE_PLACE 3
#define ICM_ICONGROUP_FOG_OF_WAR 1
typedef struct { uint16 groundTileID, overlayTileID; uint8 houseID; } Tile;
static Tile g_map[4096];
static uint8 g_dirtyMinimap[512], g_dirtyViewport[512], screen[160][240];
static uint16 g_viewportPosition, g_selectionRectanglePosition;
static uint16 g_selectionWidth = 1, g_selectionHeight = 1, g_selectionType;
static uint16 g_veiledTileID = 98, g_iconMap[32] = {[1] = 16, [31] = 99};
static bool g_debugScenario, s_viewportRepairActive = true, structure = true;
static void *g_unitSelected;
static uint8 currentPen = 15;
static unsigned updates, draws, selectedDraws, lastOverlay;
/* STATE */
static bool BitArray_Test(const uint8 *bits, uint16 p) { return (bits[p >> 3] >> (p & 7)) & 1; }
static void BitArray_Set(uint8 *bits, uint16 p) { assert(p < 4096); bits[p >> 3] |= 1u << (p & 7); }
static void BitArray_Clear(uint8 *bits, uint16 p) { bits[p >> 3] &= ~(1u << (p & 7)); }
static uint16 Tile_GetPackedX(uint16 p) { return p & 63; }
static uint16 Tile_GetPackedY(uint16 p) { return p >> 6; }
static void *Structure_Get_ByPackedTile(uint16 p) { (void)p; return structure ? g_map : NULL; }
static uint8 Video_Atari_GetPalettePen(uint8 index) { assert(index == 255); return currentPen; }
static void Map_Update(uint16 p, uint16 type, bool invisible) {
    assert(type == 0 && !invisible);
    updates++;
    BitArray_Set(g_dirtyMinimap, p);
    BitArray_Set(g_dirtyViewport, p);
}
static void paint(uint16 x, uint16 y, uint8 colour) {
    assert(x < 240 && y >= 40 && y < 200);
    uint16 p = g_viewportPosition + ((y - 40) >> 4) * 64 + (x >> 4);
    assert(!BitArray_Test(g_dirtyMinimap, p));
    for (unsigned row = 0; row < 16; row++) memset(screen[y - 40 + row] + x, colour, 16);
    draws++;
}
static void GFX_DrawPlanarTile(uint16 id, uint16 x, uint16 y, uint8 house) {
    (void)house; paint(x, y, id);
}
static void GFX_DrawPlanarTileFogged(uint16 id, uint16 fog, uint16 x, uint16 y, uint8 house) {
    (void)id; (void)fog; (void)house; paint(x, y, 12);
}
static void GFX_DrawPlanarFogTile(uint16 x, uint16 y) { paint(x, y, 12); }
static void GFX_DrawPlanarSelectionTile(uint16 id, uint16 overlay, uint16 x, uint16 y,
                                       uint8 house, uint8 token, uint8 pen) {
    assert(house == 2);
    selectedDraws++; lastOverlay = overlay;
    paint(x, y, overlay == 0xffff || overlay == 97 ? 12 : overlay ? overlay : id);
    for (unsigned row = 0; row < 16; row++) for (unsigned col = 0; col < 16; col++) {
        if ((!row && (token & GFX_SELECTION_TOP)) ||
            (row == 15 && (token & GFX_SELECTION_BOTTOM)) ||
            (!col && (token & GFX_SELECTION_LEFT)) ||
            (col == 15 && (token & GFX_SELECTION_RIGHT))) screen[y - 40 + row][x + col] = pen;
    }
}
/* FUNCTIONS */
static void repair(void) { GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200); }
static void check(int left, int top, unsigned w, unsigned h, bool active) {
    for (int y = 0; y < 160; y++) for (int x = 0; x < 240; x++) {
        bool edge = active && x >= left && x < left + (int)w * 16 &&
            y >= top && y < top + (int)h * 16 &&
            (x == left || x == left + (int)w * 16 - 1 || y == top || y == top + (int)h * 16 - 1);
        assert(screen[y][x] == (edge ? currentPen : 7));
    }
}
int main(void) {
    for (unsigned p = 0; p < 4096; p++) { g_map[p].groundTileID = 7; g_map[p].houseID = 2; }
    g_viewportPosition = 20 * 64 + 20;
    memset(screen, 7, sizeof(screen));
    for (unsigned w = 1; w <= 3; w++) for (unsigned h = 1; h <= 3; h++) {
        g_selectionWidth = w; g_selectionHeight = h;
        g_selectionRectanglePosition = g_viewportPosition + 2 * 64 + 2;
        GUI_Widget_Viewport_PrepareSelection();
        unsigned before = updates;
        GUI_Widget_Viewport_PrepareSelection();
        assert(updates == before && s_viewportSelectionActive);
        repair();
        check(32, 32, w, h, true);
        unsigned border = w * h - ((w == 3 && h == 3) ? 1 : 0);
        for (unsigned repeat = 0; repeat < 4; repeat++) {
            for (unsigned y = 0; y < h; y++) for (unsigned x = 0; x < w; x++)
                BitArray_Set(g_dirtyMinimap, g_selectionRectanglePosition + y * 64 + x);
            before = selectedDraws;
            unsigned d = draws;
            repair();
            assert(selectedDraws == before + border && draws == d + w * h);
            check(32, 32, w, h, true);
        }
        /* Unit selection removes every old edge, without new outline writes. */
        g_unitSelected = g_map;
        GUI_Widget_Viewport_PrepareSelection();
        before = selectedDraws;
        repair();
        assert(selectedDraws == before && !s_viewportSelectionActive);
        check(32, 32, w, h, false);
        g_unitSelected = NULL;
    }
    g_selectionWidth = g_selectionHeight = 3;
    /* Move, resize, destroy and reselect without retaining any old border. */
    GUI_Widget_Viewport_PrepareSelection(); repair();
    g_selectionRectanglePosition += 4 * 64 + 5;
    GUI_Widget_Viewport_PrepareSelection(); repair();
    check(112, 96, 3, 3, true);
    g_selectionWidth = g_selectionHeight = 1;
    GUI_Widget_Viewport_PrepareSelection(); repair();
    check(112, 96, 1, 1, true);
    structure = false;
    GUI_Widget_Viewport_PrepareSelection(); repair();
    check(112, 96, 1, 1, false);
    structure = true;
    GUI_Widget_Viewport_PrepareSelection(); repair();
    currentPen = 0;
    GUI_Widget_Viewport_PrepareSelection(); repair();
    check(112, 96, 1, 1, true);
    g_selectionType = SELECTIONTYPE_PLACE;
    GUI_Widget_Viewport_PrepareSelection(); repair();
    check(112, 96, 1, 1, false);
    g_selectionType = 0;
    /* A scrolled/clipped 3x3 structure keeps only its real outer edges. */
    g_selectionWidth = g_selectionHeight = 3;
    g_selectionRectanglePosition = g_viewportPosition - 65;
    GUI_Widget_Viewport_PrepareSelection(); repair();
    check(-16, -16, 3, 3, true);
    g_viewportPosition += 65;
    memset(screen, 7, sizeof(screen)); /* Newly exposed terrain; native scroll is tested separately. */
    GUI_Widget_Viewport_PrepareSelection(); repair();
    check(-32, -32, 3, 3, true);
    g_selectionRectanglePosition = g_viewportPosition + 9 * 64 + 14;
    GUI_Widget_Viewport_PrepareSelection(); repair();
    check(224, 144, 3, 3, true);
    /* Fog and debug use the same selected-tile publisher, exactly once. */
    g_selectionRectanglePosition = g_viewportPosition;
    g_selectionWidth = g_selectionHeight = 1;
    GUI_Widget_Viewport_PrepareSelection(); repair();
    const unsigned overlays[] = {0, 9, 97, 98, 99};
    for (unsigned debug = 0; debug < 2; debug++) for (unsigned i = 0; i < 5; i++) {
        g_debugScenario = debug != 0;
        g_map[g_viewportPosition].overlayTileID = overlays[i];
        BitArray_Set(g_dirtyMinimap, g_viewportPosition);
        unsigned d = draws, s = selectedDraws;
        repair();
        assert(draws == d + 1 && selectedDraws == s + 1);
        assert(lastOverlay == (debug ? 0 : overlays[i] >= 98 ? 0xffff : overlays[i]));
    }
    return 0;
}
"""
        harness = harness.replace("/* STATE */", state).replace(
            "/* FUNCTIONS */", "\n".join(function(viewport, name) for name in (
                "GUI_Widget_Viewport_ReadRow", "GUI_Widget_Viewport_PrepareSelection",
                "GUI_Widget_Viewport_RepairTiles")))
        with tempfile.TemporaryDirectory(prefix="planar-selection-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                            "-Werror", *flags, str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_native_outline_skips_separate_foreground_pass(self):
        draw = function((ROOT / "src/gui/viewport.c").read_text(), "GUI_Widget_Viewport_Draw")
        self.assertLess(draw.index("GUI_Widget_Viewport_PrepareSelection()"),
                        draw.index("GUI_Widget_Viewport_PrepareRows("))
        rectangle = draw[draw.index("if (g_unitSelected == NULL &&"):
                         draw.index("/* Draw ground units */")]
        self.assertIn("g_selectionType == SELECTIONTYPE_PLACE || s_viewportSelectionActive", rectangle)
        self.assertLess(rectangle.index("s_viewportSelectionActive"),
                        rectangle.index("GUI_Widget_Viewport_RepairTiles("))
        self.assertIn("GUI_DrawWiredRectangle", rectangle)
        self.assertIn("GUI_Widget_Viewport_SpriteDamageRect", rectangle)
