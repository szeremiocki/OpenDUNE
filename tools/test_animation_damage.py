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
        sprites = (ROOT / "src/sprites.h").read_text()
        start = sprites.index("typedef enum IconMapEntries")
        icons = sprites[start:sprites.index("} IconMapEntries;", start) + len("} IconMapEntries;")]
        production = "\n".join((
            icons,
            structure,
            "#ifdef TOS\n#define TEST_TOS\n#undef TOS\n#endif",
            function(map_source, "Map_Update"),
            "#ifdef TEST_TOS\n#define TOS\n#endif",
            function(map_source, "Map_IsGroundVisibleUnderFog"),
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
static bool g_enableCosmeticAnimations = true;
#define lengthof(a) (sizeof(a) / sizeof((a)[0]))
#define VARIABLE_NOT_USED(x) ((void)(x))
static Tile g_map[4096];
static uint8 g_dirtyViewport[512], g_dirtyMinimap[512], g_displayedViewport[512];
static uint8 g_changedTilesMap[512], g_displayedMinimap[512];
static uint16 g_dirtyViewportCount, g_changedTilesCount, g_changedTiles[64];
static bool g_selectionRectangleNeedRepaint, visible = true, unveiled = true;
static struct { int mapScale; } g_scenario;
static uint16 g_iconMap[128];
#ifdef TOS
static bool g_debugScenario;
static uint16 g_veiledTileID = 127;
static bool Video_Atari_CursorDirect(void) { return false; }
#endif
static void Map_Update(uint16 packed, uint16 type, bool ignoreInvisible);
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

    def test_native_opaque_fog_animation_and_structure_state(self):
        animation = (ROOT / "src/animation.c").read_text()
        map_source = (ROOT / "src/map.c").read_text()
        structure_source = (ROOT / "src/structure.c").read_text()
        sprites = (ROOT / "src/sprites.h").read_text()
        icons = sprites[sprites.index("typedef enum IconMapEntries"):
                        sprites.index("} IconMapEntries;") + len("} IconMapEntries;")]
        start = animation.index("typedef struct Animation {")
        record = animation[start:animation.index("} Animation;", start) + len("} Animation;")]
        production = "\n".join((
            icons, record,
            function(map_source, "Map_IsGroundVisibleUnderFog"),
            function(animation, "Animation_Func_SetGroundTile"),
            function(animation, "Animation_Func_Stop"),
            function(animation, "Animation_Func_Abort"),
            function(structure_source, "Structure_UpdateMap"),
        ))
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
typedef int16_t int16;
typedef struct { uint16 x, y; } tile32;
typedef struct { unsigned command; int16 parameter; } AnimationCommandStruct;
typedef struct {
    uint16 groundTileID, overlayTileID, index;
    uint8 houseID;
    bool hasAnimation, hasStructure;
} Tile;
typedef struct {
    struct {
        tile32 position;
        struct { struct { bool used, isNotOnMap, isDirty; } s; } flags;
        uint16 type, index;
        uint8 houseID;
    } o;
    uint16 rotationSpriteDiff;
    int16 state;
} Structure;
typedef struct { uint16 layout, iconGroup; uint8 animationIndex[3]; } StructureInfo;
#define VARIABLE_NOT_USED(x) ((void)(x))
#define STRUCTURE_STATE_IDLE 0
#define STRUCTURE_STATE_READY 2
static Tile g_map[4096];
static uint16 g_iconMap[8192], g_mapTileID[4096], g_veiledTileID = 127;
static bool g_enableCosmeticAnimations = true, g_debugScenario, native = true;
static bool unveiled, visible = true;
static unsigned updates, minimapUpdates, starts;
static const uint16 single[] = {0}, square[] = {0,1,64,65};
static const uint16 *g_table_structure_layoutTiles[] = {single, square};
static const uint16 g_table_structure_layoutTileCount[] = {1,4};
static Structure turret;
static StructureInfo g_table_structureInfo[32];
static AnimationCommandStruct g_table_animation_structure[32][1];
static bool Video_Atari_CursorDirect(void) { return native; }
static bool Tile_IsUnveiled(uint16 id) { return id == 0; }
static bool Map_IsPositionUnveiled(uint16 packed) {
    assert(packed < 4096);
    return g_debugScenario || unveiled;
}
static uint16 Tile_PackTile(tile32 t) { return (t.y >> 8) * 64 + (t.x >> 8); }
static void Map_Update(uint16 packed, uint16 type, bool ignoreInvisible) {
    assert(packed < 4096 && type == 0 && !ignoreInvisible);
    if (visible) updates++;
}
static void Map_MarkTileDirty(uint16 packed) {
    assert(packed < 4096); minimapUpdates++;
}
static Structure *Structure_Get_ByPackedTile(uint16 packed) {
    assert(packed < 4096); return &turret;
}
static void Animation_Start(const AnimationCommandStruct *commands, tile32 tile,
                            uint16 layout, uint8 house, uint8 group) {
    assert(commands != NULL && Tile_PackTile(tile) < 4096);
    assert(layout <= 1 && house == 2 && group < 32); starts++;
}
/* PRODUCTION */
int main(void) {
    uint16 packed = 3 + 3 * 64;
    g_iconMap[ICM_ICONGROUP_FOG_OF_WAR] = 8000;
    g_iconMap[8015] = 126;
    /* Exercise every structure icon group, not a refinery exception. */
    for (unsigned group = ICM_ICONGROUP_HOUSE_PALACE;
         group < ICM_ICONGROUP_EOF; group++) {
        bool isTurret = group == ICM_ICONGROUP_BASE_DEFENSE_TURRET ||
                        group == ICM_ICONGROUP_BASE_ROCKET_TURRET;
        unsigned count = isTurret ? 1 : 4;
        unsigned layout = isTurret ? 0 : 1;
        Animation a = {.tileLayout = layout, .houseID = 2, .iconGroup = group,
                       .tile = {3 << 8, 3 << 8}};
        Structure s = {.o = {.position = a.tile, .type = group, .index = 3,
                             .houseID = 2, .flags = {.s = {.used = true}}},
                       .state = 1};
        g_table_structureInfo[group] = (StructureInfo){layout, group, {0,1,2}};
        g_iconMap[group] = group * 100;
        g_iconMap[group * 100] = 198;
        for (unsigned i = 0; i < count; i++) {
            g_iconMap[group * 100 + count * 2 + i] = 100 + i;
            g_iconMap[group * 100 + count * 3 + i] = 200 + i;
            g_mapTileID[packed + square[i]] = 50 + i;
        }
        for (unsigned mode = 0; mode < 6; mode++) {
            uint16 fog = mode == 1 ? 126 : mode == 2 ? 7 : 127;
            g_debugScenario = mode == 3;
            unveiled = mode == 4;
            native = mode != 5;
            updates = minimapUpdates = starts = 0;
            for (unsigned i = 0; i < count; i++)
                g_map[packed + square[i]] = (Tile){.overlayTileID = fog};
            Animation_Func_SetGroundTile(&a, 3);
            assert(updates == (mode < 2 ? 0 : count));
            assert(minimapUpdates == count);
            for (unsigned i = 0; i < count; i++) {
                Tile *t = &g_map[packed + square[i]];
                assert(t->groundTileID == 200 + i && t->houseID == 2);
                assert(t->overlayTileID == (mode == 3 || mode == 4 ? 0 : fog));
            }
            /* A subsequent reveal draws the frame already reached while hidden. */
            if (mode < 2) {
                g_debugScenario = true;
                if (Map_IsGroundVisibleUnderFog(packed)) Map_Update(packed, 0, false);
                assert(updates == 1 && g_map[packed].groundTileID == 200);
                g_debugScenario = false;
                updates = 0;
            }
            Structure_UpdateMap(&s);
            assert(updates == (mode < 2 ? 0 : count * 2));
            assert(starts == 1 && s.o.flags.s.isDirty);
            for (unsigned i = 0; i < count; i++)
                assert(g_map[packed + square[i]].hasStructure &&
                       g_map[packed + square[i]].groundTileID == 100 + i);
            updates = 0;
            a.commands = g_table_animation_structure[1];
            g_map[packed].hasAnimation = true;
            Animation_Func_Stop(&a, 0);
            assert(updates == (mode < 2 ? 0 : count));
            assert(a.commands == NULL && !g_map[packed].hasAnimation);
            for (unsigned i = 0; i < count; i++)
                assert(g_map[packed + square[i]].groundTileID ==
                       (isTurret ? 100 : 50 + i));
            updates = 0;
            a.commands = g_table_animation_structure[1];
            g_map[packed].hasAnimation = true;
            Animation_Func_Abort(&a, 0);
            assert(updates == (mode < 2 ? 0 : 1));
            assert(a.commands == NULL && !g_map[packed].hasAnimation);
        }
        native = true; unveiled = true; visible = false;
        updates = minimapUpdates = 0;
        g_map[packed].groundTileID = 0;
        Animation_Func_SetGroundTile(&a, 3);
        assert(updates == 0 && minimapUpdates == count);
        visible = true;
    }
    /* Ground suppression is opt-in; genuine fog/cursor repairs still queue. */
    native = true; unveiled = g_debugScenario = false;
    g_map[packed].overlayTileID = 127;
    updates = 0;
    Map_Update(packed, 0, false);
    assert(updates == 1);
    return 0;
}
"""
        harness = harness.replace("/* PRODUCTION */", production)
        with tempfile.TemporaryDirectory(prefix="animation-fog-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                            "-Werror", "-DTOS", *flags, str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
