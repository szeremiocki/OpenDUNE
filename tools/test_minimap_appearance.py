"""Exercise the production minimap classifier/cache with small rendering stubs."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    start = re.search(r"^(?:static )?(?:bool|void) " + name + r"\(", source, re.M).start()
    return source[start:source.index("\n}", start) + 2]


class MinimapAppearanceTest(unittest.TestCase):
    def test_rendering_and_invalidation(self):
        source = (ROOT / "src/gui/viewport.c").read_text()
        start = source.index("static uint8 s_minimapAppearance[")
        end = source.index("\nbool GUI_Widget_Viewport_IsPlanar(", start)
        cache = "#ifdef TOS\n" + source[start:end] + "\n#endif\n"
        renderer = "\n".join(function(source, name) for name in (
            "GUI_Widget_Viewport_DrawTileInternal", "GUI_Widget_Viewport_DrawTile",
            "GUI_Widget_Viewport_DrawTileForce"))
        bits = "\n".join(re.findall(
            r"^#define BitArray_(?:Test|Set|Clear)\(.*$",
            (ROOT / "src/tools.h").read_text(), re.M))
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
#define SCREEN_0 0
#define SCREEN_1 1
#define SCREEN_ACTIVE 2
#define DRAWSPRITE_FLAG_WIDGETPOS 1
#define UNIT_SANDWORM 3
#define LST_ENTIRELY_MOUNTAIN 2
#define Tile_GetPackedX(p) ((p) & 63)
#define Tile_GetPackedY(p) ((p) >> 6)
typedef struct { struct { uint16 type, houseID; } o; } Unit;
typedef struct { struct { uint16 houseID; } o; } Structure;
typedef struct {
    bool isUnveiled, hasUnit, hasStructure;
    uint16 houseID, type;
} Tile;
static Tile g_map[4096];
static uint8 g_displayedMinimap[512];
static struct { uint16 mapScale; } g_scenario;
static struct { uint16 minX, minY; } g_mapInfos[3];
static struct { struct { bool radarActivated; } flags; } house, *g_playerHouse = &house;
static uint16 g_playerHouseID;
static bool g_debugScenario, direct = true, iconsReady = true;
static struct { uint16 spriteID, radarColour; } g_table_landscapeInfo[] = {
    {40, 88}, {44, 0xffff}, {48, 12}
};
static struct { uint16 minimapColor; } g_table_houseInfo[] = {
    {144}, {160}, {176}, {192}, {208}, {224}
};
static Unit unit;
static Structure structure;
static uint8 spriteBytes[512], *g_sprites[512], screens[2][64000];
static unsigned writes;
static int active = SCREEN_1;
bool Tile_IsOutOfMap(uint16 p) { return p >= 4096; }
bool Map_IsValidPosition(uint16 p) {
    return Tile_GetPackedX(p) < 20 && Tile_GetPackedY(p) < 20;
}
uint16 Map_GetLandscapeType(uint16 p) { return g_map[p].type; }
Unit *Unit_Get_ByPackedTile(uint16 p) { return g_map[p].hasUnit ? &unit : 0; }
uint16 Unit_GetHouseID(Unit *u) { return u->o.houseID; }
Structure *Structure_Get_ByPackedTile(uint16 p) {
    return g_map[p].hasStructure ? &structure : 0;
}
bool Video_Atari_CursorDirect(void) { return direct; }
bool GFX_Screen_IsActive(int screen) { return active == screen; }
void GFX_PutPixel(uint16 x, uint16 y, uint8 c) {
    assert(x < 320 && y < 200);
    screens[active][y * 320 + x] = c;
    writes++;
}
void icon(uint16 id, uint16 x, uint16 y) {
    unsigned r, c, size = g_scenario.mapScale + 1;
    for (r = 0; r < size; r++)
        for (c = 0; c < size; c++)
            GFX_PutPixel(256 + x + c, 136 + y + r, id);
}
bool GUI_DrawMinimapIcon(uint16 id, uint16 x, uint16 y) {
    if (!iconsReady || active != SCREEN_1) return false;
    icon(id, x, y);
    return true;
}
#define GUI_SPRITE_COLOUR_EMBEDDED 0xfe
void GUI_DrawSprite(int screen, uint8 *sprite, uint16 id, uint8 house, uint16 x, uint16 y, int w, int f) {
    (void)screen; (void)id; (void)house; (void)w; (void)f;
    icon(*sprite, x, y);
}
/* BITS */
/* CACHE */
/* RENDERER */
static bool expectSkip(void) {
#ifdef TOS
    return true;
#else
    return false;
#endif
}
static void reset(void) {
    memset(g_map, 0, sizeof(g_map));
    memset(g_displayedMinimap, 0, sizeof(g_displayedMinimap));
    g_scenario.mapScale = 0;
    active = SCREEN_1;
    direct = iconsReady = true;
    g_playerHouse->flags.radarActivated = false;
    g_debugScenario = false;
    writes = 0;
#ifdef TOS
    GUI_Widget_Viewport_InvalidateMinimap();
#endif
}
static void repeated(uint16 p) {
    unsigned before = writes;
    assert(GUI_Widget_Viewport_DrawTile(p) == !expectSkip());
    if (expectSkip()) assert(writes == before);
}
int main(void) {
    const uint16 p = 3 * 64 + 3;
    unsigned scale, i;
    for (i = 0; i < 512; i++) {
        spriteBytes[i] = i;
        g_sprites[i] = &spriteBytes[i];
    }
    for (scale = 0; scale < 3; scale++) {
        reset();
        g_scenario.mapScale = scale;
        assert(GUI_Widget_Viewport_DrawTile(p));
        repeated(p);
        /* A concealed moving unit does not change the hidden icon. */
        g_map[p].isUnveiled = g_map[p].hasUnit = true;
        unit.o.houseID = 1; unit.o.type = 0;
        repeated(p);
        g_playerHouse->flags.radarActivated = true;
        assert(GUI_Widget_Viewport_DrawTile(p));
        repeated(p);
        unit.o.houseID = 2;
        assert(GUI_Widget_Viewport_DrawTile(p));
        repeated(p);
        unit.o.type = UNIT_SANDWORM;
        assert(GUI_Widget_Viewport_DrawTile(p));
        if (scale == 0) assert(screens[SCREEN_1][139 * 320 + 259] == 255);
        repeated(p); /* Includes opaque logical colour 255 at scale 0. */
        g_map[p].hasUnit = false;
        assert(GUI_Widget_Viewport_DrawTile(p));
        repeated(p);
        g_map[p].type = 1; g_map[p].houseID = 1;
        assert(GUI_Widget_Viewport_DrawTile(p));
        repeated(p);
        g_playerHouse->flags.radarActivated = false;
        g_map[p].hasStructure = true; structure.o.houseID = g_playerHouseID;
        assert(GUI_Widget_Viewport_DrawTile(p));
        repeated(p);
        structure.o.houseID = 1;
        assert(GUI_Widget_Viewport_DrawTile(p));
        repeated(p);
        g_debugScenario = true;
        assert(GUI_Widget_Viewport_DrawTile(p));
        repeated(p);
        /* The outline can overwrite an otherwise unchanged icon. */
        BitArray_Set(g_displayedMinimap, p);
        assert(!GUI_Widget_Viewport_DrawTile(p));
        BitArray_Clear(g_displayedMinimap, p);
        i = writes;
        assert(GUI_Widget_Viewport_DrawTileForce(p));
        assert(writes > i);
        repeated(p);
#ifdef TOS
        GUI_Widget_Viewport_InvalidateMinimap();
        assert(GUI_Widget_Viewport_DrawTile(p));
        repeated(p);
#endif
        active = SCREEN_0;
        assert(GUI_Widget_Viewport_DrawTile(p));
        assert(GUI_Widget_Viewport_DrawTile(p));
        active = SCREEN_1;
        repeated(p);
    }
    reset();
    assert(GUI_Widget_Viewport_DrawTile(p));
    g_scenario.mapScale = 1;
    assert(GUI_Widget_Viewport_DrawTile(p));
    repeated(p);
    g_scenario.mapScale = 0;
    assert(GUI_Widget_Viewport_DrawTile(p));
    repeated(p);
    reset();
    direct = false;
    assert(GUI_Widget_Viewport_DrawTile(p));
    assert(GUI_Widget_Viewport_DrawTile(p));
    reset();
    g_scenario.mapScale = 1; iconsReady = false;
    assert(GUI_Widget_Viewport_DrawTile(p));
    repeated(p);
    assert(!GUI_Widget_Viewport_DrawTile(4096));
    assert(!GUI_Widget_Viewport_DrawTile(63));
    reset();
    g_map[p].isUnveiled = g_playerHouse->flags.radarActivated = true;
    g_table_landscapeInfo[0].radarColour = 0;
    assert(GUI_Widget_Viewport_DrawTile(p));
    assert(screens[SCREEN_1][139 * 320 + 259] == 0);
    repeated(p);
    reset();
    g_scenario.mapScale = 1;
    g_map[p].isUnveiled = g_playerHouse->flags.radarActivated = true;
    assert(GUI_Widget_Viewport_DrawTile(p));
    g_table_landscapeInfo[0].spriteID = 300;
    assert(GUI_Widget_Viewport_DrawTile(p));
    assert(GUI_Widget_Viewport_DrawTile(p));
    g_table_landscapeInfo[0].spriteID = 40;
    assert(GUI_Widget_Viewport_DrawTile(p));
    repeated(p);
    return 0;
}
"""
        harness = harness.replace("/* BITS */", bits).replace("/* CACHE */", cache)
        harness = harness.replace("/* RENDERER */", renderer)
        with tempfile.TemporaryDirectory(prefix="minimap-appearance-") as directory:
            test = Path(directory) / "test.c"
            test.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            for tos in (False, True):
                with self.subTest(tos=tos):
                    binary = Path(directory) / ("atari" if tos else "generic")
                    subprocess.run([*compiler, "-std=c99", "-Wall", "-Wextra", "-Werror",
                                    *(["-DTOS"] if tos else []),
                                    str(test), "-o", str(binary)], check=True)
                    subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
