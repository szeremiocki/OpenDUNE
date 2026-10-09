"""Check changed-tile animation damage with conservative foreground selection."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_script_budget import function


ROOT = Path(__file__).resolve().parents[1]


class AnimationDamageTest(unittest.TestCase):
    def test_changed_tiles_and_foreground_halo(self):
        animation = (ROOT / "src/animation.c").read_text()
        map_source = (ROOT / "src/map.c").read_text()
        start = animation.index("typedef struct Animation {")
        structure = animation[start:animation.index("} Animation;", start) + len("} Animation;")]
        production = "\n".join((
            structure,
            function(map_source, "Map_Update"),
            function(map_source, "Map_MarkTileDirty"),
            function(animation, "Animation_Func_SetGroundTile"),
        ))
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
typedef int16_t int16;
typedef struct { uint16 x, y; } tile32;
typedef struct { unsigned command; int16 parameter; } AnimationCommandStruct;
typedef struct { uint16 groundTileID, overlayTileID; uint8 houseID; } Tile;
typedef struct { uint16 rotationSpriteDiff; } Structure;
#define ICM_ICONGROUP_BASE_DEFENSE_TURRET 19
#define ICM_ICONGROUP_BASE_ROCKET_TURRET 20
#define lengthof(a) (sizeof(a) / sizeof((a)[0]))
static Tile g_map[4096];
static uint8 g_dirtyViewport[512], g_dirtyMinimap[512], g_displayedViewport[512];
static uint8 g_changedTilesMap[512], g_displayedMinimap[512];
static uint16 g_dirtyViewportCount, g_changedTilesCount, g_changedTiles[64];
static bool g_selectionRectangleNeedRepaint, visible = true, unveiled = true;
static struct { int mapScale; } g_scenario;
static uint16 g_iconMap[128];
static const uint16 single[] = {0}, square[] = {0, 1, 64, 65};
static const uint16 *g_table_structure_layoutTiles[] = {single, square};
static const uint16 g_table_structure_layoutTileCount[] = {1, 4};
static Structure turret = {4};
static bool BitArray_Test(const uint8 *bits, uint16 i) {
    return (bits[i >> 3] >> (i & 7)) & 1;
}
static void BitArray_Set(uint8 *bits, uint16 i) {
    bits[i >> 3] |= 1u << (i & 7);
}
static uint16 Tile_PackTile(tile32 tile) { return (tile.y >> 8) * 64 + (tile.x >> 8); }
static bool Map_IsTileVisible(uint16 packed) { assert(packed < 4096); return visible; }
static bool Map_IsPositionUnveiled(uint16 packed) { assert(packed < 4096); return unveiled; }
static Structure *Structure_Get_ByPackedTile(uint16 packed) {
    assert(packed < 4096); return &turret;
}
/* PRODUCTION */
static void clear_damage(void) {
    memset(g_dirtyViewport, 0, sizeof(g_dirtyViewport));
    memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
    memset(g_displayedViewport, 0, sizeof(g_displayedViewport));
    memset(g_changedTilesMap, 0, sizeof(g_changedTilesMap));
    g_dirtyViewportCount = g_changedTilesCount = 0;
    g_selectionRectangleNeedRepaint = false;
}
int main(void) {
    Animation animation = {.tileLayout = 1, .houseID = 2, .iconGroup = 17,
                           .tile = {3 << 8, 3 << 8}};
    uint16 packed = Tile_PackTile(animation.tile);
    const uint16 frame2[] = {292, 293, 297, 298};
    const uint16 frame3[] = {294, 293, 297, 298};
    g_iconMap[17] = 32;
    for (unsigned i = 0; i < 4; i++) {
        g_iconMap[32 + 8 + i] = frame2[i];
        g_iconMap[32 + 12 + i] = frame3[i];
        g_map[packed + square[i]] = (Tile){frame2[i], 7, 1};
    }
    /* Identical frames do not invalidate or queue anything. */
    Animation_Func_SetGroundTile(&animation, 2);
    assert(!g_dirtyViewportCount && !g_changedTilesCount);
    for (unsigned i = 0; i < 4; i++) assert(g_map[packed + square[i]].houseID == 1);
    /* A flag change keeps just one terrain tile dirty, with all nine
     * center tiles available for overlapping foreground selection. */
    BitArray_Set(g_displayedViewport, packed + 1);
    Animation_Func_SetGroundTile(&animation, 3);
    assert(g_dirtyViewportCount == 1 && g_changedTilesCount == 1);
    assert(g_changedTiles[0] == packed && g_selectionRectangleNeedRepaint);
    for (unsigned i = 0; i < 4096; i++) {
        int dx = (int)(i & 63) - 3, dy = (int)(i >> 6) - 3;
        assert(BitArray_Test(g_dirtyViewport, i) ==
               (dx >= -1 && dx <= 1 && dy >= -1 && dy <= 1));
        assert(BitArray_Test(g_dirtyMinimap, i) == (i == packed));
        assert(BitArray_Test(g_changedTilesMap, i) == (i == packed));
    }
    assert(g_map[packed].houseID == 2 && g_map[packed].overlayTileID == 0);
    for (unsigned i = 1; i < 4; i++) {
        assert(g_map[packed + square[i]].groundTileID == frame3[i]);
        assert(g_map[packed + square[i]].houseID == 1);
        assert(g_map[packed + square[i]].overlayTileID == 7);
    }
    Animation_Func_SetGroundTile(&animation, 3);
    Animation_Func_SetGroundTile(&animation, 2);
    assert(g_dirtyViewportCount == 1 && g_changedTilesCount == 1);
    clear_damage();
    unveiled = false;
    g_map[packed].overlayTileID = 7;
    Animation_Func_SetGroundTile(&animation, 3);
    assert(g_map[packed].overlayTileID == 7 && g_dirtyViewportCount == 1);
    clear_damage();
    visible = false;
    Animation_Func_SetGroundTile(&animation, 2);
    assert(!g_dirtyViewportCount && g_changedTilesCount == 1);
    assert(g_map[packed].groundTileID == 292);
    clear_damage();
    visible = unveiled = true;
    animation.tileLayout = 0;
    animation.iconGroup = ICM_ICONGROUP_BASE_DEFENSE_TURRET;
    g_iconMap[animation.iconGroup] = 32;
    g_iconMap[32] = 200;
    Animation_Func_SetGroundTile(&animation, 2);
    assert(g_map[packed].groundTileID == 206 && g_dirtyViewportCount == 1);
    return 0;
}
"""
        harness = harness.replace("/* PRODUCTION */", production)
        with tempfile.TemporaryDirectory(prefix="animation-damage-") as directory:
            source = Path(directory) / "test.c"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            for tos in (False, True):
                with self.subTest(tos=tos):
                    binary = Path(directory) / ("tos" if tos else "generic")
                    flags = ["-DTOS"] if tos else []
                    subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                                    "-Werror", *flags, str(source), "-o", str(binary)], check=True)
                    subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
