"""Check flag-only suppression without changing animation timing or lifecycle."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

from tools.test_script_budget import function


ROOT = Path(__file__).resolve().parents[1]


class CosmeticAnimationsTest(unittest.TestCase):
    def test_config_frames_timing_and_cleanup(self):
        config = (ROOT / "src/config.c").read_text()
        animation = (ROOT / "src/animation.c").read_text()
        header = (ROOT / "src/animation.h").read_text()
        sprites = (ROOT / "src/sprites.h").read_text()
        table = (ROOT / "src/table/animation.c").read_text()
        structures = (ROOT / "src/table/structureinfo.c").read_text()
        indices = re.findall(
            r"/\* iconGroup\s+\*/ (ICM_ICONGROUP_\w+),\s*"
            r"\{ /\* animationIndex \*/\s*"
            r"/\* \[0\]\s+\*/ (\w+),\s*"
            r"/\* \[1\]\s+\*/ (\w+),\s*"
            r"/\* \[2\]\s+\*/ (\w+)", structures,
        )
        self.assertEqual(len(indices), 19)
        grouped = {}
        for group, a, b, c in indices:
            if group in grouped:
                self.assertEqual(grouped[group], (a, b, c))
            grouped[group] = (a, b, c)
        mappings = "\n".join(f"[{group}] = {{{a}, {b}, {c}}},"
                             for group, (a, b, c) in grouped.items())
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
typedef int16_t int16;
typedef struct { uint16 x, y; } tile32;
#define VARIABLE_NOT_USED(x) ((void)(x))
/* ENUMS */
typedef struct {
    uint16 groundTileID, overlayTileID;
    uint8 houseID;
    bool hasAnimation;
} Tile;
typedef struct { uint16 rotationSpriteDiff; } Structure;
static Tile g_map[4096];
static uint16 g_mapTileID[4096], g_iconMap[8192];
static uint32 g_timerGUI;
static const uint16 layouts[7][9] = {
    {0}, {0,1}, {0,64}, {0,1,64,65}, {0,1,64,65,128,129},
    {0,1,2,64,65,66}, {0,1,2,64,65,66,128,129,130}
};
static const uint16 *g_table_structure_layoutTiles[] = {
    layouts[0], layouts[1], layouts[2], layouts[3], layouts[4], layouts[5], layouts[6]
};
static const uint16 g_table_structure_layoutTileCount[] = {1,2,2,4,6,6,9};
static const uint8 structureLayouts[16] = {6,3,5,5,3,3,3,3,3,6,5,5,0,0,3,3};
/* Independent expected flag cells, including the two-tile WOR flag and
 * the Outpost flag separate from its rotating radar. */
static const uint8 expectedMasks[16] = {1,2,1,8,8,5,1,8,8,1,2,2,0,0,2,4};
static const uint8 structureAnimations[ICM_ICONGROUP_EOF][3] = {
/* MAPPINGS */
};
static bool g_enableCosmeticAnimations = true;
static uint16 g_announcementPhase, g_creditsPhase;
static int16 s_viewportFade = -1;
static const char *option;
static unsigned warnings, updates, terrainUpdates, flagUpdates, voices, randomCalls;
static uint32 randomState;
static uint16 watchedPacked, watchedLayout, watchedMask;
static Structure turret = {4};
static char *IniFile_GetString(const char *key, const char *fallback, char *out, uint16 size) {
    assert(fallback == NULL);
    if (strcmp(key, "cosmetic_animations")) {
        assert(!strcmp(key, "phase_announcement") || !strcmp(key, "phase_credits") ||
               !strcmp(key, "viewport_fade"));
        return NULL;
    }
    if (option == NULL) return NULL;
    snprintf(out, size, "%s", option);
    return out;
}
#define Warning(...) (warnings++)
/* CONFIG */
static uint16 Tile_PackTile(tile32 tile) { return (tile.y >> 8) * 64 + (tile.x >> 8); }
static bool Map_IsPositionUnveiled(uint16 packed) { assert(packed < 4096); return true; }
static void Map_Update(uint16 packed, unsigned mode, bool ignore) {
    assert(packed < 4096 && mode == 0 && !ignore);
    updates++;
    for (unsigned i = 0; i < g_table_structure_layoutTileCount[watchedLayout]; i++)
        if ((watchedMask & (1u << i)) && packed == watchedPacked + layouts[watchedLayout][i])
            flagUpdates++;
}
static void Map_MarkTileDirty(uint16 packed) { assert(packed < 4096); terrainUpdates++; }
static uint8 Tools_Random_256(void) {
    randomCalls++;
    randomState = randomState * 1664525u + 1013904223u;
    return randomState >> 24;
}
static void Voice_PlayAtTile(int16 parameter, tile32 tile) {
    (void)parameter; (void)tile; voices++;
}
static Structure *Structure_Get_ByPackedTile(uint16 packed) {
    assert(packed < 4096); return &turret;
}
/* TABLE */
/* ANIMATION */
static tile32 tile = {10 << 8, 10 << 8};
static void reset(uint8 group, uint16 layout, uint16 mask, bool enabled) {
    Animation_Init();
    memset(g_map, 0, sizeof(g_map));
    g_timerGUI = s_animationTimer = 0;
    g_enableCosmeticAnimations = enabled;
    watchedPacked = Tile_PackTile(tile); watchedLayout = layout; watchedMask = mask;
    updates = terrainUpdates = flagUpdates = voices = randomCalls = 0;
    randomState = 123456789;
    unsigned count = g_table_structure_layoutTileCount[layout];
    for (unsigned i = 0; i < count; i++) {
        uint16 packed = watchedPacked + layouts[layout][i];
        g_mapTileID[packed] = 77 + i;
        g_map[packed].groundTileID = g_iconMap[g_iconMap[group] + count * 2 + i];
        g_map[packed].houseID = 2;
    }
}
static void test_option(void) {
    option = NULL; g_enableCosmeticAnimations = false;
    Config_LoadAnimationPhases();
    assert(g_enableCosmeticAnimations && warnings == 0);
    const char *valid[] = {"0", "1", " 1\t", "+0", "00"};
    const bool values[] = {false, true, true, false, false};
    for (unsigned i = 0; i < sizeof(valid) / sizeof(*valid); i++) {
        option = valid[i]; Config_LoadAnimationPhases();
        assert(g_enableCosmeticAnimations == values[i] && warnings == 0);
        assert(g_announcementPhase == 1 && g_creditsPhase == 1 && s_viewportFade == -1);
    }
    const char *invalid[] = {"", "2", "-1", "no", "1x", "1.5",
                             "999999999999999999999999999"};
    for (unsigned i = 0; i < sizeof(invalid) / sizeof(*invalid); i++) {
        option = invalid[i]; Config_LoadAnimationPhases();
        assert(g_enableCosmeticAnimations && warnings == i + 1);
    }
}
static void initialize_frames(void) {
    /* Synthetic frames isolate flags from all other activity cells. */
    for (unsigned group = 0; group < ICM_ICONGROUP_EOF; group++) {
        unsigned layout = group >= 11 ? structureLayouts[group - 11] : 0;
        unsigned count = g_table_structure_layoutTileCount[layout];
        unsigned mask = group >= 11 ? expectedMasks[group - 11] : 0;
        g_iconMap[group] = 1024 + group * 128;
        for (unsigned frame = 0; frame < 10; frame++)
            for (unsigned i = 0; i < count; i++) {
                uint16 base = 1000 + group * 64 + i;
                uint16 value = base;
                if (frame < 2 || frame >= 4) value += (frame + 1) * 9;
                if (frame >= 2 && (mask & (1u << i))) value = base + (frame & 1) * 9;
                if (group == ICM_ICONGROUP_RADAR_OUTPOST && frame >= 2 && i == 1)
                    value = base + (frame - 2) * 9;
                g_iconMap[g_iconMap[group] + frame * count + i] = value;
            }
    }
}
static void test_sequences(void) {
    enum { TICKS = 900 };
    uint16 original[TICKS][9];
    uint8 currents[TICKS];
    uint32 deadlines[TICKS], rngStates[TICKS];
    for (unsigned group = 11; group < ICM_ICONGROUP_EOF; group++) {
        unsigned layout = structureLayouts[group - 11];
        unsigned count = g_table_structure_layoutTileCount[layout];
        unsigned mask = expectedMasks[group - 11];
        if (!mask) continue;
        for (unsigned state = 0; state < 3; state++) {
            const AnimationCommandStruct *commands =
                g_table_animation_structure[structureAnimations[group][state]];
            unsigned originalUpdates = 0, originalRandomCalls = 0;
            for (unsigned mode = 0; mode < 2; mode++) {
                reset(group, layout, mask, mode == 0);
                Animation_Start(commands, tile, layout, 2, group);
                assert(g_map[watchedPacked].hasAnimation && g_animations[0].commands == commands);
                for (unsigned tick = 0; tick < TICKS; tick++) {
                    g_timerGUI = tick; Animation_Tick();
                    assert(g_animations[0].commands == commands && g_map[watchedPacked].hasAnimation);
                    for (unsigned i = 0; i < count; i++) {
                        uint16 value = g_map[watchedPacked + layouts[layout][i]].groundTileID;
                        if (mode == 0) original[tick][i] = value;
                        else assert(value == ((mask & (1u << i)) ?
                            g_iconMap[g_iconMap[group] + count * 2 + i] : original[tick][i]));
                    }
                    if (mode == 0) {
                        currents[tick] = g_animations[0].current;
                        deadlines[tick] = g_animations[0].tickNext;
                        rngStates[tick] = randomState;
                    } else {
                        assert(g_animations[0].current == currents[tick]);
                        assert(g_animations[0].tickNext == deadlines[tick]);
                        assert(randomState == rngStates[tick]);
                    }
                }
                assert(randomCalls > 0 && voices == 0);
                if (mode == 0) {
                    assert(flagUpdates > 0);
                    originalUpdates = updates; originalRandomCalls = randomCalls;
                } else {
                    assert(flagUpdates == 0 && updates < originalUpdates);
                    assert(randomCalls == originalRandomCalls);
                    if (group == ICM_ICONGROUP_RADAR_OUTPOST) assert(terrainUpdates > 0);
                    if (group == ICM_ICONGROUP_CONSTRUCTION_YARD) assert(updates == 0);
                }
            }
        }
    }
}
static void test_other_frames_and_lifecycle(void) {
    for (unsigned group = 0; group < ICM_ICONGROUP_EOF; group++) {
        unsigned layout = group >= 11 ? structureLayouts[group - 11] : 0;
        unsigned count = g_table_structure_layoutTileCount[layout];
        for (unsigned frame = 0; frame < 2; frame++) {
            reset(group, layout, 0, false);
            Animation animation = {.tileLayout = layout, .houseID = 3, .iconGroup = group, .tile = tile};
            Animation_Func_SetGroundTile(&animation, frame);
            for (unsigned i = 0; i < count; i++) {
                Tile *t = &g_map[watchedPacked + layouts[layout][i]];
                assert(t->groundTileID == g_iconMap[g_iconMap[group] + count * frame + i]);
                assert(t->houseID == 3 && t->overlayTileID == 0);
            }
        }
    }
    reset(ICM_ICONGROUP_BASE_DEFENSE_TURRET, 0, 0, false);
    Animation turretAnimation = {.tileLayout = 0, .houseID = 2,
                                .iconGroup = ICM_ICONGROUP_BASE_DEFENSE_TURRET, .tile = tile};
    Animation_Func_SetGroundTile(&turretAnimation, 3);
    assert(g_map[watchedPacked].groundTileID ==
           g_iconMap[g_iconMap[ICM_ICONGROUP_BASE_DEFENSE_TURRET]] + 6);
    reset(ICM_ICONGROUP_SAND_TRACKS, 0, 0, false);
    Animation tracks = {.tileLayout = 0, .houseID = 2,
                        .iconGroup = ICM_ICONGROUP_SAND_TRACKS, .tile = tile};
    Animation_Func_SetGroundTile(&tracks, 3);
    assert(g_map[watchedPacked].groundTileID ==
           g_iconMap[g_iconMap[ICM_ICONGROUP_SAND_TRACKS] + 3]);
    reset(ICM_ICONGROUP_CONSTRUCTION_YARD, 3, 1, false);
    Animation_Start(g_table_animation_structure[22], tile, 3, 2, ICM_ICONGROUP_CONSTRUCTION_YARD);
    Animation_Tick();
    assert(updates == 0 && g_map[watchedPacked].hasAnimation);
    Animation_Start(g_table_animation_structure[1], tile, 3, 3, ICM_ICONGROUP_CONSTRUCTION_YARD);
    assert(g_animations[0].commands == g_table_animation_structure[1]);
    for (unsigned i = 0; i < 4; i++)
        assert(g_map[watchedPacked + layouts[3][i]].groundTileID ==
               g_mapTileID[watchedPacked + layouts[3][i]]);
    Animation_Tick();
    g_timerGUI++; Animation_Tick();
    assert(!g_map[watchedPacked].hasAnimation && g_animations[0].commands == NULL);
    Animation_Start(g_table_animation_structure[22], tile, 3, 3, ICM_ICONGROUP_CONSTRUCTION_YARD);
    Animation_Tick();
    assert(g_map[watchedPacked].houseID == 3 && g_map[watchedPacked].hasAnimation);
    Animation_Stop_ByTile(watchedPacked);
    assert(!g_map[watchedPacked].hasAnimation && g_animations[0].commands == NULL);
    for (unsigned i = 0; i < 4; i++)
        assert(g_map[watchedPacked + layouts[3][i]].groundTileID ==
               g_mapTileID[watchedPacked + layouts[3][i]]);
}
int main(void) {
    test_option(); initialize_frames(); test_sequences(); test_other_frames_and_lifecycle();
    return 0;
}
"""
        enums = sprites[sprites.index("typedef enum IconMapEntries"):
                        sprites.index("} IconMapEntries;") + len("} IconMapEntries;")]
        enums += header[header.index("typedef enum AnimationCommand"):
                        header.index("#endif")]
        harness = harness.replace("/* ENUMS */", enums)
        harness = harness.replace("/* MAPPINGS */", mappings)
        harness = harness.replace("/* CONFIG */", "\n".join(
            function(config, name) for name in (
                "Config_ReadAnimationOption", "Config_ReadAnimationPhase",
                "Config_LoadAnimationPhases")))
        harness = harness.replace("/* TABLE */", table[table.index("const AnimationCommandStruct"):])
        harness = harness.replace("/* ANIMATION */", animation[animation.index("enum {"):])
        with tempfile.TemporaryDirectory(prefix="cosmetic-animations-") as directory:
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
