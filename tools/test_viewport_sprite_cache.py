"""Check the isolated planar image cache and direct-screen sprite alignment."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    match = re.search(r"^(?:static )?(?:inline )?[^\n]*\b" + name + r"\([^;]*?\n\{", source, re.M)
    if match is None:
        raise ValueError("Missing function: " + name)
    return source[match.start():source.index("\n}\n", match.end()) + 3]


def blit_plan_type():
    header = (ROOT / "src/video/video.h").read_text()
    start = header.index("typedef struct Video_Atari_SpriteBlitPlan {")
    end = header.index("} Video_Atari_SpriteBlitPlan;", start) + len("} Video_Atari_SpriteBlitPlan;")
    return "#ifndef TEST_BLIT_PLAN_TYPE\n#define TEST_BLIT_PLAN_TYPE\n" + header[start:end] + "\n#endif\n"


def blitter_model(video, tiles=False):
    """Execute production register setup against a persistent 32-bit latch."""
    model = r"""
#define ST_PLANAR_LINE_BYTES 160
#define Atari_SupervisorExec(callback) callback()
static bool s_viewportBlitter;
static bool s_blitterTileSetup;
static int16 reg_src_x, reg_src_y, reg_dst_x, reg_dst_y;
static uintptr_t reg_src, reg_dst;
static uint16 reg_mask1, reg_mask2, reg_mask3, reg_x, reg_y;
static uint8 reg_hop, reg_op, reg_ctrl, reg_skew;
#define BLITTER_SRC_XINC (&reg_src_x)
#define BLITTER_SRC_YINC (&reg_src_y)
#define BLITTER_SRC_ADDR (&reg_src)
#define BLITTER_ENDMASK1 (&reg_mask1)
#define BLITTER_ENDMASK2 (&reg_mask2)
#define BLITTER_ENDMASK3 (&reg_mask3)
#define BLITTER_DST_XINC (&reg_dst_x)
#define BLITTER_DST_YINC (&reg_dst_y)
#define BLITTER_DST_ADDR (&reg_dst)
#define BLITTER_XCOUNT (&reg_x)
#define BLITTER_YCOUNT (&reg_y)
#define BLITTER_HOP (&reg_hop)
#define BLITTER_OP (&reg_op)
#define BLITTER_CTRL (&reg_ctrl)
#define BLITTER_SKEW (&reg_skew)
static unsigned blitterLaunches, blitterLocks, blitterSetups, blitterPlanBuilds, cachedPlanDraws;
static uintptr_t blitterPixels, blitterMasks;
static uint16 blitterReadStride;
static void Video_Atari_BlitterStart(void) {
    static uint32 latch = 0xa39fbc71;
    unsigned words = reg_x, rows = reg_y;
    uintptr_t src = reg_src, dst = reg_dst;
    assert(!blitterLocks && reg_hop == 2 && words && rows);
    assert(reg_op == 3 || reg_op == 4 || reg_op == 7);
    assert(words != 1 || !(reg_skew & 0x40));
    blitterLaunches++;
    for (unsigned row = 0; row < rows; row++) {
        uintptr_t rowBase = (reg_op == 4 ? blitterMasks : blitterPixels) + row * blitterReadStride;
        if (reg_skew & 0x80) {
            assert(reg_op == 3 || (src >= rowBase && src + 2 <= rowBase + blitterReadStride));
            uint16 value = *(const uint16 *)src;
            latch = reg_src_x < 0 ? (latch >> 16) | ((uint32)value << 16) :
                                   (latch << 16) | value;
            src += reg_src_x;
        }
        for (unsigned word = 0; word < words; word++) {
            bool suppress = (reg_skew & 0x40) && word + 1 == words;
            uint16 old = *(uint16 *)dst;
            assert(suppress || reg_op == 3 ||
                   (src >= rowBase && src + 2 <= rowBase + blitterReadStride));
            uint16 value = suppress ? old : *(const uint16 *)src;
            latch = reg_src_x < 0 ? (latch >> 16) | ((uint32)value << 16) :
                                   (latch << 16) | value;
            uint16 shifted = latch >> (reg_skew & 15);
            uint16 result = reg_op == 3 ? shifted :
                            reg_op == 4 ? old & (uint16)~shifted : old | shifted;
            uint16 mask = word == 0 ? reg_mask1 :
                          word + 1 == words ? reg_mask3 : reg_mask2;
            *(uint16 *)dst = (old & (uint16)~mask) | (result & mask);
            if (suppress) {
                value = *(uint16 *)dst;
                latch = reg_src_x < 0 ? (latch >> 16) | ((uint32)value << 16) :
                                       (latch << 16) | value;
            } else {
                src += word + 1 == words || ((reg_skew & 0x40) && word + 2 == words) ?
                       reg_src_y : reg_src_x;
            }
            dst += word + 1 == words ? reg_dst_y : reg_dst_x;
        }
    }
    reg_src = src; reg_dst = dst; reg_y = 0; reg_ctrl = 0;
}
"""
    block = video[video.index("typedef struct PlanarBlit {"):
                  video.index("static PlanarBlit s_planarBlit;") + len("static PlanarBlit s_planarBlit;")]
    setup = function(video, "Video_Atari_BlitterSetup")
    setup = setup.replace("\n{\n", "\n{\n    blitterSetups++;\n", 1)
    builder = function(video, "Video_Atari_BuildSpriteBlitPlan")
    builder = builder.replace("\n{\n", "\n{\n    blitterPlanBuilds++;\n", 1)
    production = function(video, "Video_Atari_ViewportBlitter") + "\n" + setup + "\n" + block
    production += "\n" + builder + "\n" + function(video, "Video_Atari_BuildSpriteBlitPlans")
    if tiles:
        production += "\n" + function(video, "Video_Atari_BlitOpaque")
        production += "\n" + function(video, "Video_Atari_BlitTile")
    else:
        production += r"""
static bool Video_Atari_CursorRectOverlap(uint8 *base, uint16 first, uint16 end,
                                          uint16 y, uint16 height) {
    (void)base; (void)first; (void)end; (void)y; (void)height; return false;
}
#define Video_Atari_RefreshViewportCursorUnshifted(...) assert(false)
"""
    for name in ("Video_Atari_BlitMasked", "Video_Atari_ShiftSpriteWord",
                 "Video_Atari_RefreshViewportCursorUnshifted",
                 "Video_Atari_PresentPlanarSpriteUnshifted"):
        if name == "Video_Atari_RefreshViewportCursorUnshifted" and not tiles:
            continue
        body = function(video, name)
        if name == "Video_Atari_PresentPlanarSpriteUnshifted":
            body = body.replace("\n{\n", "\n{\n"
                "    if (plan != NULL) cachedPlanDraws++;\n"
                "    blitterPixels = (uintptr_t)pixels; blitterMasks = (uintptr_t)masks;\n"
                "    blitterReadStride = sourceWidth / 2;\n", 1)
        production += "\n" + body
    return blit_plan_type() + model + production.replace("(uint32)(size_t)", "(uintptr_t)")


class ViewportSpriteCacheTest(unittest.TestCase):
    def test_canonical_layer_order(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        draw = function(viewport, "GUI_Widget_Viewport_GroundSprites")
        additions = re.findall(r"GUI_Widget_Viewport_AddSpriteLayer\(layers,\s*([^,]+)", draw)
        self.assertEqual(additions, ["spriteID", "ui->turretSpriteID + directions[orientation][0]", "spriteID", "6"])
        self.assertLess(draw.index("UNIT_SPRITE_HARVEST"), draw.index("ui->turretSpriteID != 0xFFFF"))
        self.assertLess(draw.index("ui->turretSpriteID != 0xFFFF"), draw.index("u->o.flags.s.isSmoking"))
        self.assertLess(draw.index("u->o.flags.s.isSmoking"),
                        draw.index("GUI_Widget_Viewport_AddSpriteLayer(layers, 6"))
        self.assertNotRegex(function(viewport, "GUI_Widget_Viewport_AddSpriteLayer"),
                            r"count\s*[<>]")
        self.assertNotRegex(function((ROOT / "src/gui/gui.c").read_text(), "GUI_ViewportPlanarSprite"),
                            r"count\s*[<>]")
        units = (ROOT / "src/table/unitinfo.c").read_text()
        harvester = units[units.index('/* name                 */ "Harvester"'):]
        harvester = harvester[:harvester.index("/* name", 10)]
        self.assertIn("/* turretSpriteID       */ -1", harvester)

    def test_mandatory_cache_initialization(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        cache = gui[gui.index("enum { VIEWPORT_PLANAR_SPRITES"):gui.index("\nvoid GUI_FreeViewportSpriteCache")]
        flags = "\n".join(line for line in (ROOT / "src/gui/gui.h").read_text().splitlines()
                          if line.startswith("#define DRAWSPRITE_FLAG_"))
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int16_t int16;
typedef uint32_t uint32;
#define READ_LE_UINT16(p) ((uint16)((p)[0] | ((uint16)(p)[1] << 8)))
/* TYPES */
typedef struct ViewportSpriteMask {
    const uint8 *sprite;
    uint16 *rows;
    uint16 width, height;
} ViewportSpriteMask;
static ViewportSpriteMask s_viewportSpriteCache[355];
static uint16 *s_viewportSpriteMasks;
static bool s_viewportSpriteReady, s_viewportPlanar, direct = true;
static uint8 *g_sprites[355];
static unsigned allocations, failAt;
/* CACHE */
static void GUI_FreeViewportSpriteCache(void) {
    free(s_viewportSpriteMasks); s_viewportSpriteMasks = NULL;
    free(s_viewportPlanarSprites); s_viewportPlanarSprites = NULL;
    free(s_viewportPlanarMasks); s_viewportPlanarMasks = NULL;
    free(s_viewportPlanarComponents); s_viewportPlanarComponents = NULL;
    memset(s_viewportSpriteCache, 0, sizeof(s_viewportSpriteCache));
    memset(s_viewportPlanarKeys, 0, sizeof(s_viewportPlanarKeys));
    s_viewportPlanarLastHitPosition = VIEWPORT_PLANAR_SPRITES;
    s_viewportPlanarClock = s_viewportComponentClock = 0;
    s_viewportSpriteReady = s_viewportPlanar = false;
}
static bool Video_Atari_CursorDirect(void) { return direct; }
static bool Video_Atari_ViewportBlitter(void) { return false; }
static void Error(const char *format, ...) {
    va_list ap; va_start(ap, format); vfprintf(stderr, format, ap); va_end(ap);
}
static void *test_malloc(size_t size) {
    assert(!s_viewportSpriteReady);
    return ++allocations == failAt ? NULL : malloc(size);
}
static void *test_calloc(size_t count, size_t size) {
    assert(!s_viewportSpriteReady);
    return ++allocations == failAt ? NULL : calloc(count, size);
}
#define malloc test_malloc
#define calloc test_calloc
static void GUI_DrawSpriteMask(uint8 *pixels, uint16 width, uint16 height,
                               const uint8 *sprite, int16 x, int16 y, int flags, ...) {
    (void)sprite; (void)x; (void)y; (void)flags;
    memset(pixels, 1, width * height);
}
/* PRODUCTION */
int main(int argc, char **argv) {
    uint8 selection[10] = {2, 0, 1, 1}, unit[10] = {2, 0, 1, 1};
    g_sprites[6] = selection; g_sprites[111] = unit;
    if (argc > 1) {
        if (!strcmp(argv[1], "width")) unit[3] = 33;
        else if (!strcmp(argv[1], "height")) unit[2] = 65;
        else if (!strcmp(argv[1], "other-machine")) direct = false;
        else failAt = atoi(argv[1]);
    }
    GUI_InitViewportSpriteCache();
    if (!direct) {
        assert(!s_viewportSpriteReady && !allocations);
        return 0;
    }
    assert(!failAt && s_viewportSpriteReady && allocations == 4);
    assert(GUI_ViewportSpriteMaskSlot(6)->sprite == selection);
    assert(GUI_ViewportSpriteMaskSlot(111)->sprite == unit);
    assert(GUI_ViewportSpriteMaskSlot(6) != GUI_ViewportSpriteMaskSlot(111));
    assert(s_viewportPlanarSprites && s_viewportPlanarMasks && s_viewportPlanarComponents);
    GUI_FreeViewportSpriteCache();
    return 0;
}
"""
        types = (ROOT / "src/gui/viewport_key.h").read_text() + "\n" + blit_plan_type()
        harness = harness.replace("/* TYPES */", types + "\n" + flags)
        harness = harness.replace("/* CACHE */", cache)
        harness = harness.replace("/* PRODUCTION */",
                                  function(gui, "GUI_ViewportSpriteMaskSlot") + "\n" +
                                  function(gui, "GUI_InitViewportSpriteCache"))
        with tempfile.TemporaryDirectory(prefix="viewport-cache-init-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                            str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
            subprocess.run([str(binary), "other-machine"], check=True)
            for mode in ["width", "height", "1", "2", "3", "4"]:
                result = subprocess.run([str(binary), mode], capture_output=True, text=True)
                self.assertEqual(result.returncode, 1, mode)
                self.assertIn("planar viewport", result.stderr)

    def test_unit_identity_mutation_and_lifecycle(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        unit = (ROOT / "src/unit.c").read_text()
        pool = (ROOT / "src/pool/unit.c").read_text()
        script = (ROOT / "src/script/unit.c").read_text()
        save = (ROOT / "src/saveload/unit.c").read_text()
        for name in ("Unit_SetOrientation", "Unit_SetAction", "Unit_Damage", "Unit_EnterStructure"):
            self.assertIn("Unit_ClearViewportKey(", function(unit, name), name)
        self.assertIn("Unit_ClearViewportKey(", function(unit, "Unit_UpdateMap"))
        for name in ("GameLoop_Unit", "Unit_Rotate", "Unit_SetPosition", "Unit_StartMovement",
                     "Unit_Deviate", "Unit_Deviation_Decrease"):
            self.assertIn("Unit_UpdateMap(", function(unit, name), name)
        for name in ("Unit_Load", "UnitNew_Load"):
            self.assertIn("Unit_ClearViewportKey(u)", function(save, name))
        for name in ("Script_Unit_SetSprite", "Script_Unit_IdleAction"):
            self.assertIn("Unit_PrepareSpriteChange(", function(script, name))
            self.assertIn("Unit_UpdateMap(update, u)", function(script, name))
        harness = r"""
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "types.h"
#include "src/unit.h"
#include "src/house.h"
#include "src/map.h"
#include "src/tile.h"
#include "src/pool/unit.h"
#include "src/pool/house.h"
#include "src/gui/gui.h"
UnitInfo g_table_unitInfo[UNIT_MAX];
const ActionInfo g_table_actionInfo[ACTION_MAX] = {
    [ACTION_GUARD] = {.switchType = 1},
    [ACTION_HARVEST] = {.switchType = 1},
    [ACTION_MOVE] = {.switchType = 0}
};
Unit *g_unitSelected, *g_scriptCurrentUnit;
ScriptInfo *g_scriptUnit;
static Unit g_unitArray[UNIT_INDEX_MAX];
Unit *g_unitFindArray[UNIT_INDEX_MAX];
uint16 g_unitFindCount;
static House house;
static unsigned mapUpdates;
static uint16 g_validateStrictIfZero;
static bool g_debugGame;
HouseType g_playerHouseID;
Tile g_map[64 * 64];
uint8 g_functions[3][3];
uint16 g_dirtyUnitCount, g_dirtyAirUnitCount;
bool Video_Atari_CursorDirect(void) { return true; }
void Unit_PrepareSpriteChange(Unit *unit, uint16 parts) {
    assert(unit && parts); mapUpdates++;
}
House *House_Get_ByIndex(uint8 index) { assert(index == 0); return &house; }
uint8 Unit_GetHouseID(Unit *unit) { return unit->o.houseID; }
void Unit_DisplayStatusText(Unit *unit) { assert(unit != NULL); }
void GUI_Widget_ActionPanel_Draw(bool force) { assert(force); }
void Sound_StartSound(uint16 index) { (void)index; }
uint16 GUI_DisplayHint(uint16 stringID, uint16 spriteID) {
    (void)stringID; (void)spriteID; return 0;
}
void GUI_ChangeSelectionType(uint16 type) { (void)type; }
uint16 Map_SetSelectionObjectPosition(uint16 packed) { assert(packed == 0xffff); return 0; }
void Script_Reset(ScriptEngine *script, ScriptInfo *info) { (void)script; (void)info; }
void Script_Load(ScriptEngine *script, uint8 type) { (void)script; (void)type; }
void Script_LoadAsSubroutine(ScriptEngine *script, uint8 type) { (void)script; (void)type; }
uint16 Script_Stack_Peek(ScriptEngine *script, int position) {
    (void)script; assert(position == 1); return 7;
}
void Unit_HouseUnitCount_Add(Unit *unit, uint8 houseID) { (void)unit; (void)houseID; }
void Unit_HouseUnitCount_Remove(Unit *unit) { (void)unit; }
bool House_AreAllied(uint8 a, uint8 b) { return a == b; }
bool Map_IsPositionUnveiled(uint16 packed) { (void)packed; return true; }
Object *Object_GetByPackedTile(uint16 packed) { (void)packed; return NULL; }
void Tile_RemoveFogInRadius(tile32 tile, uint16 radius) { (void)tile; (void)radius; }
void Map_UpdateAround(uint16 radius, tile32 position, Unit *unit, uint8 operation) {
    (void)radius; (void)position; (void)operation;
    assert(unit != NULL); mapUpdates++;
}
/* PRODUCTION */
static void warm(Unit *unit) {
    assert(unit->o.index < UNIT_INDEX_MAX);
    unit->viewportKey.main = 111;
}
static bool valid(Unit *unit) { return unit->viewportKey.main != 0; }
int main(void) {
    g_table_unitInfo[UNIT_TANK].indexStart = 20;
    g_table_unitInfo[UNIT_TANK].indexEnd = 101;
    g_table_unitInfo[UNIT_TANK].turningSpeed = 2;
    house.unitCountMax = 100;
    Unit_Init();
    Unit *u = Unit_Allocate(20, UNIT_TANK, 0);
    assert(u && !valid(u) && house.unitCount == 1 && g_unitFindCount == 1);
    u->orientation[0].speed = 8;
    u->orientation[0].target = 32;
    warm(u);
    Unit_Rotate(u, 0);
    assert(valid(u) && u->orientation[0].current == 8 && mapUpdates == 0);
    Unit_Rotate(u, 0);
    assert(!valid(u) && u->orientation[0].current == 16 && mapUpdates == 1);
    warm(u);
    Unit_Rotate(u, 0);
    assert(valid(u) && u->orientation[0].current == 24 && mapUpdates == 1);
    Unit_SetOrientation(u, 25, true, 0);
    assert(!valid(u));
    Unit_SetOrientation(u, 64, true, 0);
    assert(!valid(u));
    warm(u);
    Unit_SetOrientation(u, 96, false, 1);
    assert(valid(u) && u->orientation[1].current == 0);
    Unit_Rotate(u, 1);
    assert(valid(u));
    Unit_Rotate(u, 1);
    assert(!valid(u) && u->orientation[1].current == 16);
    warm(u);
    g_scriptCurrentUnit = u;
    u->o.script.stackPointer = 14;
    u->o.script.stack[14] = 7;
    Script_Unit_SetSprite(&u->o.script);
    assert(!valid(u) && u->spriteOffset == -7);
    warm(u);
    Unit_SetAction(u, ACTION_GUARD);
    assert(!valid(u));
    u->o.type = UNIT_HARVESTER;
    Unit_SetAction(u, ACTION_HARVEST);
    assert(!valid(u) && u->actionID == ACTION_HARVEST);
    warm(u);
    Unit_SetAction(u, ACTION_HARVEST);
    assert(!valid(u));
    warm(u);
    u->currentDestination.x = 1;
    Unit_SetAction(u, ACTION_MOVE);
    assert(!valid(u) && u->actionID == ACTION_HARVEST && u->nextActionID == ACTION_MOVE);
    u->currentDestination.x = 0;
    Unit_SetAction(u, ACTION_MOVE);
    assert(!valid(u) && u->actionID == ACTION_MOVE);
    warm(u);
    u->o.position.x += 256;
    Unit_UpdateMap(1, u);
    assert(!valid(u));
    warm(u);
    u->o.flags.s.isNotOnMap = true;
    unsigned before = mapUpdates;
    Unit_UpdateMap(2, u);
    assert(!valid(u) && mapUpdates == before);
    u->o.flags.s.isNotOnMap = false;
    Unit_UpdateMap(2, NULL);
    warm(u);
    Unit_Free(u);
    assert(!valid(u) && house.unitCount == 0 && g_unitFindCount == 0);
    warm(u);
    u = Unit_Allocate(20, UNIT_TANK, 0);
    assert(u && !valid(u));
    warm(u);
    Unit *other = Unit_Allocate(21, UNIT_TANK, 0);
    assert(other && valid(u) && !valid(other));
    u->o.seenByHouses = other->o.seenByHouses = 1;
    warm(other);
    Unit_Select(u);
    assert(g_unitSelected == u && !valid(u) && valid(other));
    warm(u);
    Unit_Select(other);
    assert(g_unitSelected == other && !valid(u) && !valid(other));
    warm(other);
    Unit_Select(NULL);
    assert(g_unitSelected == NULL && !valid(other));
    warm(u);
    warm(other);
    SaveLoad_UnitSelected(NULL, 20, true);
    assert(g_unitSelected == u && !valid(u) && valid(other));
    warm(u);
    SaveLoad_UnitSelected(NULL, 21, true);
    assert(g_unitSelected == other && !valid(u) && !valid(other));
    warm(other);
    SaveLoad_UnitSelected(NULL, 0xffff, true);
    assert(g_unitSelected == NULL && !valid(other));
    warm(u);
    warm(other);
    Unit_Init();
    assert(!valid(u) && !valid(other) && g_unitFindCount == 0);
    return 0;
}
"""
        tile = (ROOT / "src/tile.c").read_text()
        implementations = [
            function(pool, "Unit_Get_ByIndex"), function(pool, "Unit_Init"),
            function(pool, "Unit_Allocate"), function(pool, "Unit_Free"),
            function(tile, "Orientation_Orientation256ToOrientation8"),
            function(tile, "Orientation_Orientation256ToOrientation16"),
            function(unit, "Unit_UpdateMap"),
            function(unit, "Unit_Rotate"), function(unit, "Unit_SetOrientation"),
            function(unit, "Unit_SetAction"), function(script, "Script_Unit_SetSprite"),
            function(unit, "Unit_Select"),
            function((ROOT / "src/saveload/info.c").read_text(), "SaveLoad_UnitSelected"),
        ]
        harness = harness.replace("/* PRODUCTION */", "\n".join(implementations))
        with tempfile.TemporaryDirectory(prefix="unit-sprite-identity-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                            "-DTOS", "-I", str(ROOT), "-I", str(ROOT / "include"),
                            str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_map_updates_without_unit_key_lookup(self):
        source_map = (ROOT / "src/map.c").read_text()
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int16_t int16;
typedef uint32_t uint32;
static bool visible;
static uint8 g_dirtyMinimap[4096], g_dirtyViewport[4096], g_displayedViewport[4096];
static uint16 g_dirtyViewportCount;
static bool g_selectionRectangleNeedRepaint;
static bool Map_IsTileVisible(uint16 packed) { return packed < 4096 && visible; }
static bool BitArray_Test(const uint8 *bits, uint16 packed) { assert(packed < 4096); return bits[packed]; }
static void BitArray_Set(uint8 *bits, uint16 packed) { assert(packed < 4096); bits[packed] = 1; }
/* MAP UPDATE */
int main(void) {
    Map_Update(200, 0, false);
    assert(!g_dirtyViewportCount);
    visible = true;
    g_dirtyMinimap[200] = 1;
    Map_Update(200, 0, false);
    assert(!g_dirtyViewportCount);
    Map_Update(200, 1, false);
    assert(g_dirtyViewport[200]);
    Map_Update(201, 0, false);
    assert(g_dirtyViewportCount == 1 && g_dirtyMinimap[201]);
    assert(g_dirtyViewport[137] && g_dirtyViewport[201] && g_dirtyViewport[266]);
    assert(!g_selectionRectangleNeedRepaint);
    Map_Update(0xffff, 0, false);
    return 0;
}
"""
        harness = harness.replace("/* MAP UPDATE */", function(source_map, "Map_Update"))
        with tempfile.TemporaryDirectory(prefix="viewport-terrain-identity-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                            "-DTOS", str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_viewport_bypasses_harvester_keys(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        start = viewport.index("\t\t\tspriteFlags |= DRAWSPRITE_FLAG_LAYERS;")
        end = viewport.index("\n\t\t}\n\n\t\tg_dirtyUnitCount", start)
        flags = "\n".join(line for line in (ROOT / "src/gui/gui.h").read_text().splitlines()
                          if line.startswith("#define DRAWSPRITE_FLAG_"))
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdarg.h>
typedef uint32_t uint32;
/* KEY TYPE */
/* FLAGS */
enum { UNIT_HARVESTER = 16, SCREEN_ACTIVE = 0 };
typedef struct { struct { unsigned type; } o; ViewportCompositeKey viewportKey; } Unit;
static uint8_t sprite, *g_sprites[] = {&sprite}, paletteHouse[16], g_paletteMapping2[256];
static ViewportCompositeKey *expectedKey;
static unsigned calls;
static void GUI_DrawSprite(int screen, const uint8_t *body, unsigned index, unsigned house,
                           int x, int y, int window, int flags, ...) {
    assert(screen == SCREEN_ACTIVE && body == &sprite && !index && !house);
    assert(x == 64 && y == 60 && window == 2);
    assert(flags & DRAWSPRITE_FLAG_LAYERS);
    va_list ap;
    va_start(ap, flags);
    assert(va_arg(ap, const unsigned *) != NULL);
#ifdef TOS
    assert(flags & DRAWSPRITE_FLAG_VIEWPORT_KEY);
    assert(va_arg(ap, ViewportCompositeKey *) == expectedKey);
#endif
    if (flags & DRAWSPRITE_FLAG_PAL) assert(va_arg(ap, uint8_t *) == paletteHouse);
    assert(va_arg(ap, uint8_t *) == g_paletteMapping2);
    assert(va_arg(ap, int) == 1);
    va_end(ap);
    calls++;
}
static void submit(Unit *u, int spriteFlags) {
    unsigned index = 0, bodyHouse = 0, layers = 0;
    int x = 64, y = 60;
    (void)u;
    /* SUBMISSION */
}
int main(void) {
    Unit unit = {0};
    for (unsigned type = 0; type < 2; type++) {
        unit.o.type = type ? UNIT_HARVESTER : 9;
        unit.viewportKey.main = 111;
        expectedKey = type ? NULL : &unit.viewportKey;
        submit(&unit, 0);
        submit(&unit, DRAWSPRITE_FLAG_PAL);
        assert(unit.viewportKey.main == 111);
    }
    assert(calls == 4);
    return 0;
}
"""
        harness = harness.replace("/* KEY TYPE */", (ROOT / "src/gui/viewport_key.h").read_text())
        harness = harness.replace("/* FLAGS */", flags)
        harness = harness.replace("/* SUBMISSION */", viewport[start:end])
        with tempfile.TemporaryDirectory(prefix="viewport-harvester-key-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            for defines in ([], ["-DTOS"]):
                subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                                *defines, str(source), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)

    def test_house_palette_preparation(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        header = (ROOT / "src/gui/gui.h").read_text()
        flags = "\n".join(line for line in header.splitlines()
                          if line.startswith(("#define DRAWSPRITE_FLAG_", "#define GUI_SPRITE_")))
        layer_types = header[header.index("typedef struct GUI_SpriteLayer"):header.index("/* colourHouse identifies")]
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int16_t int16;
/* FLAGS */
/* LAYERS */
static uint8 assets[2]={0,1}, *g_sprites[3]={assets,assets+1,NULL};
static bool direct;
static unsigned lookups;
#ifdef TOS
static bool Video_Atari_CursorDirect(void) { return direct; }
#endif
static bool GUI_GetSpriteHousePalette(uint16 id,uint8 house,uint8 *palette) {
    lookups++;
    if(g_sprites[id]==NULL || !(g_sprites[id][0]&1)) return false;
    for(unsigned i=0;i<16;i++) palette[i]=house*16+i;
    return true;
}
/* PRODUCTION */
int main(void) {
    for(unsigned mode=0;mode<2;mode++) {
        direct=mode!=0;
        uint8 palette[16]; memset(palette,0xa5,sizeof(palette));
        unsigned before=lookups;
        int flags=GUI_Widget_Viewport_HousePaletteFlags(1,5,palette);
        bool deferred=false;
#ifdef TOS
        deferred=direct;
#endif
        assert(flags==(DRAWSPRITE_FLAG_PAL | (deferred?DRAWSPRITE_FLAG_PAL_DEFERRED:0)));
        assert(lookups==before+!deferred);
        for(unsigned i=0;i<16;i++) assert(palette[i]==(deferred?0xa5:80+i));
        assert(!GUI_Widget_Viewport_HousePaletteFlags(0,5,palette));
        assert(!GUI_Widget_Viewport_HousePaletteFlags(2,5,palette));
        GUI_SpriteLayers layers; memset(&layers,0xa5,sizeof(layers)); layers.count=0;
        before=lookups;
        GUI_Widget_Viewport_AddSpriteLayer(&layers,1,5,-4,3,DRAWSPRITE_FLAG_RTL);
        assert(layers.count==1 && layers.layer[0].colourHouse==5);
        assert(layers.layer[0].flags==(flags|DRAWSPRITE_FLAG_RTL));
        assert(layers.layer[0].offsetX==-4 && layers.layer[0].offsetY==3);
        assert(lookups==before+!deferred);
        for(unsigned i=0;i<16;i++) assert(layers.layer[0].palette[i]==(deferred?0xa5:80+i));
        before=lookups;
        GUI_Widget_Viewport_AddSpriteLayer(&layers,1,GUI_SPRITE_COLOUR_EMBEDDED,0,0,0);
        assert(lookups==before && layers.layer[1].colourHouse==GUI_SPRITE_COLOUR_EMBEDDED);
        assert(layers.layer[1].flags==0);
    }
    return 0;
}
"""
        harness = harness.replace("/* FLAGS */", flags).replace("/* LAYERS */", layer_types)
        harness = harness.replace("/* PRODUCTION */",
            function(viewport, "GUI_Widget_Viewport_HousePaletteFlags") + "\n" +
            function(viewport, "GUI_Widget_Viewport_AddSpriteLayer"))
        with tempfile.TemporaryDirectory(prefix="viewport-house-palettes-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            for defines in ([], ["-DTOS"]):
                subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                                *defines, str(source), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)

    def test_cache_and_direct_blits(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        video = (ROOT / "src/video/video_atari.c").read_text()
        cache = gui[gui.index("enum { VIEWPORT_PLANAR_SPRITES"):gui.index("\nvoid GUI_FreeViewportSpriteCache")]
        flags = "\n".join(line for line in (ROOT / "src/gui/gui.h").read_text().splitlines()
                          if line.startswith(("#define DRAWSPRITE_FLAG_", "#define GUI_SPRITE_")))
        header = (ROOT / "src/gui/gui.h").read_text()
        layer_types = header[header.index("typedef struct GUI_SpriteLayer"):header.index("/* colourHouse identifies")]
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdlib.h>
#include <signal.h>
#include <string.h>
typedef uint8_t uint8;
typedef int8_t int8;
typedef uint16_t uint16;
typedef int16_t int16;
typedef uint32_t uint32;
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
#define READ_LE_UINT16(p) ((uint16)((p)[0] | ((uint16)(p)[1] << 8)))
#define DIRTY_SRC_SPRITE 1
#define HOUSE_MAX 6
#define VARIABLE_NOT_USED(x) ((void)(x))
enum { UNIT_INDEX_MAX = 102, UNIT_HARVESTER = 1, ACTION_HARVEST = 5,
       LST_SPICE = 8, LST_THICK_SPICE = 9 };
/* KEY TYPE */
typedef struct { uint16 x, y; } tile32;
typedef struct {
    struct { uint16 index, type; tile32 position; } o;
    uint8 actionID;
    int8 spriteOffset;
    struct { int8 speed, target, current; } orientation[2];
    ViewportCompositeKey viewportKey;
} Unit;
static Unit *g_unitSelected, *drawUnit;
static Unit pool[UNIT_INDEX_MAX];
static Unit *Unit_Get_ByIndex(uint16 index) {
    assert(index < UNIT_INDEX_MAX); return &pool[index];
}
static void Unit_ClearViewportKey(Unit *unit) {
    ViewportCompositeKey_Clear(&unit->viewportKey);
}
/* FLAGS */
/* LAYER TYPES */
typedef struct { uint16 xBase, yBase, width, height; } WidgetProperties;
typedef struct { const uint8 *sprite; uint16 *rows; uint16 width, height; } ViewportSpriteMask;
static WidgetProperties g_widgetProperties[3] = {{0}, {0}, {0, 40, 30, 160}};
static uint8 sprites[70][26 + 23 * 27], palette[16], remap[256];
static uint8 *g_sprites[355], *g_paletteMapping2 = remap;
static ViewportSpriteMask slots[70];
static uint16 maskStorage[70][2 * 2 * 27];
static uint16 visible[16000], expected[16000];
static bool s_viewportPlanar = true, s_viewportSpriteReady = true, overlays, batchRepairs;
static ViewportSpriteMask s_viewportSpriteCache[512];
static uint16 *s_viewportSpriteMasks;
static unsigned decodes, encodes, overlayWrites, dirtyClears;
static unsigned compositions;
static unsigned houseLookups;
static unsigned evictionCandidates;
static unsigned lookupCandidates;
static unsigned lastHitMatches;
static unsigned layerComparisons;
static unsigned keyBuilds;
static unsigned firstBinaryPosition;
static bool rejectSprite;
static int16 boundsLeft, boundsTop, boundsRight, boundsBottom;
static bool pendingRepair;
static int16 repairLeft, repairTop, repairRight, repairBottom;
#define Warning(...) assert(false)
#define Error(...) assert(false)
static void GUI_Sidebar_Free(void) {}
/* HOUSE PALETTE */
/* CACHE */
static int compare_directory_keys(const void *left, const void *right) {
    const ViewportPlanarSpriteKey *a = left, *b = right;
    if (a->key.main != b->key.main) return a->key.main < b->key.main ? -1 : 1;
    if (!(a->key.main >> 21)) return 0;
    for (unsigned i = 0; i < 2; i++)
        if (a->key.tail[i] != b->key.tail[i])
            return a->key.tail[i] < b->key.tail[i] ? -1 : 1;
    return 0;
}
static void assert_directory(void) {
    unsigned count = 0, live = 0;
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++)
        if (s_viewportPlanarSprites[i].key.main) count++;
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) {
        const ViewportPlanarSpriteKey *key = s_viewportPlanarKeys + i;
        assert(key->sprite >= s_viewportPlanarSprites &&
               key->sprite < s_viewportPlanarSprites + VIEWPORT_PLANAR_SPRITES);
        assert(key->key.main == key->sprite->key.main);
        if (key->key.main) {
            live++;
            assert(i >= VIEWPORT_PLANAR_SPRITES - count);
            assert(!memcmp(key->key.tail, key->sprite->key.tail, sizeof(key->key.tail)));
            if (!(key->key.main >> 21))
                assert(!key->key.tail[0] && !key->key.tail[1]);
        } else {
            assert(i < VIEWPORT_PLANAR_SPRITES - count);
            const uint32 zeros[2] = {0};
            assert(!memcmp(key->key.tail, zeros, sizeof(zeros)));
        }
        assert(key->sprite->masks == s_viewportPlanarMasks +
               (key->sprite - s_viewportPlanarSprites) * 320 * (batchRepairs ? 4 : 1));
        if (i) assert(compare_directory_keys(key - 1, key) <= (key->key.main ? -1 : 0));
        for (unsigned j = 0; j < i; j++) assert(s_viewportPlanarKeys[j].sprite != key->sprite);
    }
    assert(count == live);
    assert(s_viewportPlanarLastHitPosition == VIEWPORT_PLANAR_SPRITES ||
           s_viewportPlanarKeys[s_viewportPlanarLastHitPosition].key.main != 0);
}
static void rebuild_directory(void) {
    s_viewportPlanarLastHitPosition = VIEWPORT_PLANAR_SPRITES;
    memset(s_viewportPlanarKeys, 0, sizeof(s_viewportPlanarKeys));
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) {
        ViewportPlanarSprite *entry = s_viewportPlanarSprites + i;
        ViewportPlanarSpriteKey *key = s_viewportPlanarKeys + i;
        key->key.main = entry->key.main;
        if (entry->key.main) memcpy(key->key.tail, entry->key.tail, sizeof(key->key.tail));
        key->sprite = entry;
    }
    qsort(s_viewportPlanarKeys, VIEWPORT_PLANAR_SPRITES,
          sizeof(*s_viewportPlanarKeys), compare_directory_keys);
    assert_directory();
}
static ViewportPlanarSprite *expected_sprite_victim(void) {
    ViewportPlanarSprite *oldest = s_viewportPlanarSprites;
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) {
        ViewportPlanarSprite *candidate = s_viewportPlanarSprites + i;
        if (!candidate->key.main) return candidate;
        if (candidate->used < oldest->used) oldest = candidate;
    }
    return oldest;
}
static ViewportPlanarComponent *expected_component_victim(void) {
    ViewportPlanarComponent *oldest = s_viewportPlanarComponents;
    for (unsigned i = 0; i < VIEWPORT_PLANAR_COMPONENTS; i++) {
        ViewportPlanarComponent *candidate = s_viewportPlanarComponents + i;
        if (!candidate->key) return candidate;
        if (candidate->used < oldest->used) oldest = candidate;
    }
    return oldest;
}
/* FREE */
static void GFX_Screen_SetViewportPlanar(bool active) { (void)active; }
/* PLANAR SCOPE */
static ViewportSpriteMask *GUI_ViewportSpriteMaskSlot(uint16 id) {
    return slots + (id == 111 ? 0 : id);
}
static void GUI_Widget_Viewport_RepairTiles(int16 left, int16 top, int16 right, int16 bottom) {
    assert(!pendingRepair && !(left & 15) && !(right & 15) && right > left);
    assert(left >= 0 && right <= 240 && top >= 40 && top < bottom && bottom <= 200);
    if (!batchRepairs) {
        assert(right - left == 16);
        assert((top - 40) / 16 == (bottom - 1 - 40) / 16);
    }
    pendingRepair = true;
    repairLeft = left; repairTop = top; repairRight = right; repairBottom = bottom;
}
static bool GUI_Widget_Viewport_ShouldDrawSprite(int16 left, int16 top, int16 right, int16 bottom) {
    boundsLeft = left; boundsTop = top; boundsRight = right; boundsBottom = bottom;
    return !rejectSprite;
}
static void GFX_Screen_SetDirtySource(unsigned source) { assert(source == DIRTY_SRC_SPRITE); }
static void GFX_Screen_ClearDirtyRect(uint16 l, uint16 t, uint16 r, uint16 b) {
    assert(!(l & 15) && !(r & 15) && l < r && r <= 240 && t >= 40 && t < b && b <= 200);
    assert(pendingRepair && l == repairLeft && t == repairTop &&
           r == repairRight && b == repairBottom);
    pendingRepair = false;
    dirtyClears++;
}
static uint8 *Video_Atari_PlanarBase(void) { return (uint8 *)visible; }
static bool Video_Atari_PlanarOverlaysOverlap(uint8 *base, uint16 x, uint16 y, uint16 w, uint16 h) {
    assert(base == (uint8 *)visible && !(x & 15) && !(w & 15) && y >= 40 && y + h <= 200);
    return overlays;
}
static bool Video_Atari_PlacementRectOverlap(uint8 *base, uint16 l, uint16 r, uint16 y, uint16 h) {
    assert(base == (uint8 *)visible && l < r && y >= 40 && y + h <= 200);
    return overlays;
}
static void Video_Atari_RefreshViewportCursor(uint8 *base, uint16 first, uint16 end,
                                             uint16 top, uint16 bottom,
                                             const uint16 *masks, uint16 stride) {
    (void)base; (void)first; (void)end; (void)top; (void)bottom; (void)masks; (void)stride;
    assert(false); /* This harness models placement overlaps, not a drawn cursor. */
}
/* MERGE */
static void Video_Atari_PlanarMergeGroup(uint8 *base, uint16 y, uint16 group,
                                       uint16 mask, const uint16 words[4]) {
    assert(base == (uint8 *)visible && overlays);
    overlayWrites++;
    Video_Atari_PlanarMergePlain(visible + y * 80 + group * 4, mask, words);
}
static void GUI_DrawSpriteMask(uint8 *buffer, uint16 width, uint16 height,
                               const uint8 *sprite, int16 left, int16 top, int flags, ...) {
    va_list ap;
    const uint8 *colours = NULL, *mapping = NULL;
    va_start(ap, flags);
    if (flags & DRAWSPRITE_FLAG_PAL) colours = va_arg(ap, uint8 *);
    if (flags & DRAWSPRITE_FLAG_REMAP) {
        mapping = va_arg(ap, const uint8 *);
        assert(va_arg(ap, int) == 1);
    }
    va_end(ap);
    assert(left >= 0 && top >= 0 && left + 23 <= width && top + 27 <= height);
    decodes++;
    for (unsigned y = 0; y < 27; y++) for (unsigned x = 0; x < 23; x++) {
        unsigned sx = flags & DRAWSPRITE_FLAG_RTL ? 22 - x : x;
        unsigned sy = flags & DRAWSPRITE_FLAG_BOTTOMUP ? 26 - y : y;
        uint8 index = sprite[((sprite[0] & 1) ? 26 : 10) + sy * 23 + sx];
        if (index) {
            uint8 colour = sprite[0] & 1 ? colours[index] : index;
            buffer[(y + top) * width + x + left] = mapping ? mapping[colour] : colour;
        }
    }
}
static void Video_Atari_EncodePlanar(const uint8 *src, uint16 *dst, uint16 width, uint16 height) {
    encodes++;
    memset(dst, 0, width * height / 2);
    for (unsigned y = 0; y < height; y++) for (unsigned x = 0; x < width; x++)
        for (unsigned p = 0; p < 4; p++)
            if (src[y * width + x] & (1u << p))
                dst[y * (width / 4) + (x >> 4) * 4 + p] |= 0x8000u >> (x & 15);
}
/* BLITTER */
/* LOOKUP */
static ViewportCompositeKey *draw_key(void) {
    if (drawUnit == NULL) return NULL;
    Unit *u = drawUnit;
    /* KEY POLICY */
    return viewportKey;
}
static bool draw(const uint8 *sprite, int16 x, int16 y, int flags, ...) {
    va_list ap;
    uint16 id = (sprite - sprites[0]) / sizeof(sprites[0]);
    if (id == 0) id = 111;
    va_start(ap, flags);
    GUI_ViewportPlanarSprite(sprite, id,
        flags & DRAWSPRITE_FLAG_PAL ? 0 : GUI_SPRITE_COLOUR_EMBEDDED, x, y, flags, &ap, NULL,
        draw_key());
    va_end(ap);
    return true;
}
static bool draw_identity(uint16 id, uint8 house, int flags, ...) {
    va_list ap;
    va_start(ap, flags);
    GUI_ViewportPlanarSprite(sprites[0], id, house, 64, 60, flags, &ap, NULL,
                                    draw_key());
    va_end(ap);
    return true;
}
static void draw_house(uint16 id, uint8 house, const GUI_SpriteLayers *layers,
                       int16 x, int16 y, int flags, ...) {
    va_list ap;
    va_start(ap, flags);
    GUI_ViewportPlanarSprite(g_sprites[id], id, house, x, y, flags, &ap, layers, NULL);
    va_end(ap);
}
static unsigned tile_count(int left, int top, int right, int bottom) {
    left = max(0, left & ~15); right = min(240, (right + 15) & ~15);
    top = max(40, top); bottom = min(200, bottom);
    if (left >= right || top >= bottom) return 0;
    return (right - left) / 16 * ((bottom - 40 + 15) / 16 - (top - 40) / 16);
}
static void check(unsigned id, int x, int y, int flags, bool recolour) {
    int ox = x, oy = y;
    unsigned before = dirtyClears;
    unsigned launches = blitterLaunches, setups = blitterSetups;
    if (flags & DRAWSPRITE_FLAG_WIDGETPOS) oy += 40;
    if (flags & DRAWSPRITE_FLAG_CENTER) { ox -= 11; oy -= 13; }
    for (unsigned i = 0; i < 16000; i++) visible[i] = expected[i] = i * 137 + 41;
    for (unsigned row = 0; row < 27; row++) for (unsigned col = 0; col < 23; col++) {
        int dx = ox + col, dy = oy + row;
        unsigned sx = flags & DRAWSPRITE_FLAG_RTL ? 22 - col : col;
        unsigned sy = flags & DRAWSPRITE_FLAG_BOTTOMUP ? 26 - row : row;
        uint8 index = sprites[id][((sprites[id][0] & 1) ? 26 : 10) + sy * 23 + sx], colour;
        if (!index || dx < 0 || dx >= 240 || dy < 40 || dy >= 200) continue;
        colour = !(sprites[id][0] & 1) ? index :
            (flags & DRAWSPRITE_FLAG_PAL ? palette[index] : sprites[id][10 + index]);
        if (recolour) colour = remap[colour];
        for (unsigned p = 0; p < 4; p++) {
            uint16 bit = 0x8000u >> (dx & 15);
            uint16 *dst = expected + dy * 80 + (dx >> 4) * 4 + p;
            *dst = (*dst & (uint16)~bit) | ((colour & (1u << p)) ? bit : 0);
        }
    }
    if (recolour) assert(draw(sprites[id], x, y, flags, palette, remap, 1));
    else if (flags & DRAWSPRITE_FLAG_PAL) assert(draw(sprites[id], x, y, flags, palette));
    else assert(draw(sprites[id], x, y, flags));
    unsigned portions = tile_count(ox, oy, ox + 23, oy + 27);
    if (portions) {
        assert(boundsLeft == ox && boundsTop == oy && boundsRight == ox + 23 && boundsBottom == oy + 27);
        rejectSprite = true;
        if (recolour) assert(draw(sprites[id], x, y, flags, palette, remap, 1));
        else if (flags & DRAWSPRITE_FLAG_PAL) assert(draw(sprites[id], x, y, flags, palette));
        else assert(draw(sprites[id], x, y, flags));
        rejectSprite = false;
    }
    assert(!pendingRepair && dirtyClears == before + (s_viewportBlitter ? !!portions : portions));
    assert(blitterLaunches == launches + (s_viewportBlitter && portions && !overlays ? 8 : 0));
    assert(blitterSetups == setups + (s_viewportBlitter && portions && !overlays ? 1 : 0));
    assert(!memcmp(visible, expected, sizeof(visible)));
}
static bool draw_layers(const GUI_SpriteLayers *layers, int16 x, int16 y, int flags, ...) {
    va_list ap;
    va_start(ap, flags);
    GUI_ViewportPlanarSprite(sprites[0], 111, 0, x, y, flags, &ap, layers,
                                    draw_key());
    va_end(ap);
    return true;
}
static void reference_layer(unsigned id, int x, int y, int flags,
                            const uint8 *colours, const uint8 *mapping) {
    for (unsigned row = 0; row < 27; row++) for (unsigned col = 0; col < 23; col++) {
        int dx = x - 11 + col, dy = y - 13 + row;
        unsigned sx = flags & DRAWSPRITE_FLAG_RTL ? 22 - col : col;
        unsigned sy = flags & DRAWSPRITE_FLAG_BOTTOMUP ? 26 - row : row;
        uint8 index = sprites[id][((sprites[id][0] & 1) ? 26 : 10) + sy * 23 + sx];
        if (!index || dx < 0 || dx >= 240 || dy < 40 || dy >= 200) continue;
        uint8 colour = sprites[id][0] & 1 ? (colours ? colours[index] : sprites[id][10 + index]) : index;
        colour = mapping ? mapping[colour] : colour;
        for (unsigned p = 0; p < 4; p++) {
            uint16 bit = 0x8000u >> (dx & 15);
            uint16 *dst = expected + dy * 80 + (dx >> 4) * 4 + p;
            *dst = (*dst & (uint16)~bit) | ((colour & (1u << p)) ? bit : 0);
        }
    }
}
static void check_layers(const GUI_SpriteLayers *layers, int x, int y, int flags) {
    for (unsigned i = 0; i < 16000; i++) visible[i] = expected[i] = i * 137 + 41;
    reference_layer(0, x, y + 40, flags, palette, remap);
    for (unsigned i = 0; i < layers->count; i++) {
        const GUI_SpriteLayer *layer = &layers->layer[i];
        reference_layer(layer->spriteID, x + layer->offsetX, y + 40 + layer->offsetY,
                        layer->flags, layer->flags & DRAWSPRITE_FLAG_PAL ? layer->palette : NULL, NULL);
    }
    unsigned before = dirtyClears;
    unsigned launches = blitterLaunches, setups = blitterSetups;
    int left = 0, top = 0, right = 23, bottom = 27;
    for (unsigned i = 0; i < layers->count; i++) {
        left = min(left, layers->layer[i].offsetX);
        top = min(top, layers->layer[i].offsetY);
        right = max(right, layers->layer[i].offsetX + 23);
        bottom = max(bottom, layers->layer[i].offsetY + 27);
    }
    assert(draw_layers(layers, x, y, flags | DRAWSPRITE_FLAG_CENTER | DRAWSPRITE_FLAG_WIDGETPOS |
                       DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_REMAP, palette, remap, 1));
    unsigned portions = tile_count(x - 11 + left, y + 40 - 13 + top,
                                  x - 11 + right, y + 40 - 13 + bottom);
    if (portions) {
        assert(boundsLeft == x - 11 + left && boundsTop == y + 40 - 13 + top &&
               boundsRight == x - 11 + right && boundsBottom == y + 40 - 13 + bottom);
        rejectSprite = true;
        assert(draw_layers(layers, x, y, flags | DRAWSPRITE_FLAG_CENTER | DRAWSPRITE_FLAG_WIDGETPOS |
                           DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_REMAP, palette, remap, 1));
        rejectSprite = false;
    }
    assert(!pendingRepair && dirtyClears == before + (s_viewportBlitter ? !!portions : portions));
    assert(blitterLaunches == launches + (s_viewportBlitter && portions && !overlays ? 8 : 0));
    assert(blitterSetups == setups + (s_viewportBlitter && portions && !overlays ? 1 : 0));
    assert(!memcmp(visible, expected, sizeof(visible)));
}
static void append_key_field(uint32 words[3], unsigned *position,
                             uint32 value, unsigned width) {
    for (unsigned bit = 0; bit < width; bit++, (*position)++)
        if ((value >> bit) & 1)
            words[*position / 32] |= (uint32)1 << (*position % 32);
}
static void check_compact_key_inputs(uint16 spriteID, uint8 colourHouse, int flags,
                                     bool highlighted, int16 x, bool blitter,
                                     const GUI_SpriteLayers *layers) {
    ViewportCompositeKey actual;
    uint32 reference[3] = {0};
    unsigned position = 0;
    memset(&actual, 0xa5, sizeof(actual));
    GUI_ViewportBuildCompositeKey(&actual, spriteID, colourHouse, flags,
                                  highlighted, x, blitter, layers);
    append_key_field(reference, &position, spriteID, 9);
    append_key_field(reference, &position,
                     colourHouse == GUI_SPRITE_COLOUR_EMBEDDED ? 6 : colourHouse, 3);
    append_key_field(reference, &position, flags & 3, 2);
    append_key_field(reference, &position, highlighted, 1);
    append_key_field(reference, &position, blitter ? 0 : (uint16)x % 16, 4);
    append_key_field(reference, &position, !!(flags & DRAWSPRITE_FLAG_CENTER), 1);
    unsigned count = layers ? layers->count : 0;
    bool selected = count && layers->layer[count - 1].spriteID == 6;
    append_key_field(reference, &position, selected, 1);
    count -= selected;
    for (unsigned i = 0; i < 2; i++) {
        if (i >= count) {
            append_key_field(reference, &position, 0, 26);
            continue;
        }
        const GUI_SpriteLayer *layer = &layers->layer[i];
        append_key_field(reference, &position, layer->spriteID, 9);
        append_key_field(reference, &position,
                         layer->colourHouse == GUI_SPRITE_COLOUR_EMBEDDED ? 6 : layer->colourHouse, 3);
        append_key_field(reference, &position, layer->flags & 3, 2);
        append_key_field(reference, &position, layer->offsetX & 63, 6);
        append_key_field(reference, &position, layer->offsetY & 63, 6);
    }
    assert(position == 73 && actual.main == reference[0] && actual.main);
    if (count) {
        assert(!memcmp(actual.tail, reference + 1, sizeof(actual.tail)));
        assert((actual.tail[1] & 0xfffffe00UL) == 0);
    } else {
        for (unsigned i = 0; i < 2; i++) assert(actual.tail[i] == 0xa5a5a5a5UL);
    }
}
static void check_compact_key(uint32 base, const GUI_SpriteLayers *layers) {
    unsigned colour = (base >> 9) & 7;
    int flags = (base >> 12) & 3;
    if (base & 0x80000u) flags |= DRAWSPRITE_FLAG_CENTER;
    check_compact_key_inputs(base & 511,
                            colour == 6 ? GUI_SPRITE_COLOUR_EMBEDDED : colour,
                            flags, !!(base & 0x4000u), (base >> 15) & 15,
                            false, layers);
}
static uint32 next_key_random(uint32 *state) {
    *state = *state * 1664525u + 1013904223u;
    return *state;
}
static void check_compact_keys(void) {
    assert(sizeof(ViewportCompositeKey) == 12);
    assert(sizeof(s_viewportPlanarSprites[0].key.tail) == 8);
    assert(sizeof(s_viewportPlanarKeys[0].key.tail) == 8);
    assert(offsetof(ViewportPlanarSprite, key) == 0);
    assert(offsetof(ViewportPlanarSprite, used) == 12);
    assert(offsetof(ViewportPlanarSpriteKey, sprite) == 16); /* Host pointer alignment. */
    GUI_SpriteLayers full = {0}, empty = {0};
    ViewportCompositeKey reused;
    full.count = 2;
    for (unsigned i = 0; i < full.count; i++) {
        full.layer[i].spriteID = 354;
        full.layer[i].colourHouse = GUI_SPRITE_COLOUR_EMBEDDED;
        full.layer[i].flags = 3;
        full.layer[i].offsetX = -32;
        full.layer[i].offsetY = 31;
    }
    for (unsigned i = 0; i < 2; i++) {
        GUI_ViewportBuildCompositeKey(&reused, 354, 0, 0, false, 0, true, &full);
        assert(reused.main >> 21);
        assert(reused.tail[0] && reused.tail[1]);
        uint32 tails[2];
        memcpy(tails, reused.tail, sizeof(tails));
        GUI_ViewportBuildCompositeKey(&reused, 354, 0, 0, false, 0, true, i ? &empty : NULL);
        assert(reused.main == 354);
        assert(!memcmp(reused.tail, tails, sizeof(tails)));
    }
    check_compact_key(1, NULL);
    for (unsigned id = 1; id <= 354; id++) {
        check_compact_key(id, NULL);
        check_compact_key(id | 0xffc00u, NULL);
    }
    for (unsigned colour = 0; colour <= 6; colour++)
        for (unsigned flips = 0; flips < 4; flips++)
            for (unsigned highlighted = 0; highlighted < 2; highlighted++)
                for (unsigned centered = 0; centered < 2; centered++)
                    for (unsigned blitter = 0; blitter < 2; blitter++)
                        for (int x = -17; x <= 31; x++) {
                            int flags = flips | DRAWSPRITE_FLAG_WIDGETPOS |
                                        DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_REMAP;
                            if (centered) flags |= DRAWSPRITE_FLAG_CENTER;
                            check_compact_key_inputs(354,
                                colour == 6 ? GUI_SPRITE_COLOUR_EMBEDDED : colour,
                                flags, highlighted, x, blitter, NULL);
                        }
    for (unsigned count = 0; count <= 2; count++) {
        GUI_SpriteLayers layers = {0};
        layers.count = count;
        for (unsigned i = 0; i < count; i++) {
            layers.layer[i].spriteID = 354;
            layers.layer[i].colourHouse = GUI_SPRITE_COLOUR_EMBEDDED;
            layers.layer[i].flags = 3;
            layers.layer[i].offsetX = -32;
            layers.layer[i].offsetY = 31;
        }
        check_compact_key(0xffd62u, &layers);
        for (unsigned i = 0; i < count; i++) {
            GUI_SpriteLayer saved = layers.layer[i];
            GUI_SpriteLayer *layer = &layers.layer[i];
            for (unsigned id = 1; id <= 354; id++) {
                if (id == 6) continue;
                layer->spriteID = id;
                check_compact_key(0xffd62u, &layers);
            }
            *layer = saved;
            for (unsigned colour = 0; colour <= 6; colour++) {
                layer->colourHouse = colour == 6 ? GUI_SPRITE_COLOUR_EMBEDDED : colour;
                check_compact_key(0xffd62u, &layers);
            }
            *layer = saved;
            for (unsigned flags = 0; flags < 4; flags++) {
                layer->flags = flags;
                check_compact_key(0xffd62u, &layers);
            }
            *layer = saved;
            for (int offset = -32; offset <= 31; offset++) {
                layer->offsetX = offset;
                check_compact_key(0xffd62u, &layers);
                layer->offsetX = saved.offsetX;
                layer->offsetY = offset;
                check_compact_key(0xffd62u, &layers);
                layer->offsetY = saved.offsetY;
            }
        }
        layers.layer[count] = (GUI_SpriteLayer){6, GUI_SPRITE_COLOUR_EMBEDDED, 0, 0, 0, {0}};
        layers.count++;
        check_compact_key(0xffd62u, &layers);
    }
    uint32 state = 0x98765432u;
    for (unsigned trial = 0; trial < 4096; trial++) {
        GUI_SpriteLayers layers = {0};
        layers.count = next_key_random(&state) % 3;
        uint32 base = (next_key_random(&state) & 0xff000u) |
                      ((next_key_random(&state) % 7) << 9) |
                      (next_key_random(&state) % 354 + 1);
        for (unsigned i = 0; i < layers.count; i++) {
            GUI_SpriteLayer *layer = &layers.layer[i];
            layer->spriteID = next_key_random(&state) % 354 + 1;
            if (layer->spriteID == 6) layer->spriteID = 7;
            unsigned colour = next_key_random(&state) % 7;
            layer->colourHouse = colour == 6 ? GUI_SPRITE_COLOUR_EMBEDDED : colour;
            layer->flags = next_key_random(&state) & 3;
            layer->offsetX = (int)(next_key_random(&state) & 63) - 32;
            layer->offsetY = (int)(next_key_random(&state) & 63) - 32;
        }
        if (trial & 1)
            layers.layer[layers.count++] = (GUI_SpriteLayer){6, GUI_SPRITE_COLOUR_EMBEDDED, 0, 0, 0, {0}};
        check_compact_key(base, &layers);
    }
}
static void check_unit_key(Unit *unit, uint16 id, uint8 house, int flags,
                            bool highlighted, int x, bool blitter,
                            const GUI_SpriteLayers *layers, unsigned rebuilds) {
    ViewportCompositeKey reference;
    ViewportCompositeKey *actual = &unit->viewportKey;
    GUI_ViewportBuildCompositeKey(&reference, id, house, flags, highlighted, x, blitter, layers);
    uint32 oldTail[2];
    memcpy(oldTail, actual->tail, sizeof(oldTail));
    unsigned before = keyBuilds;
    if (blitter) GUI_ViewportBuildCompositeKeyBlitter(actual, id, house, flags, highlighted, layers);
    else GUI_ViewportBuildCompositeKeyCPU(actual, id, house, flags, highlighted, x, layers);
    assert(keyBuilds == before + rebuilds);
    assert(actual->main == reference.main);
    if (actual->main >> 21) assert(!memcmp(actual->tail, reference.tail, sizeof(actual->tail)));
    else assert(!memcmp(actual->tail, oldTail, sizeof(oldTail)));
}
static void check_unit_keys(void) {
    Unit unit = {0}, other = {0};
    unit.o.index = 20;
    other.o.index = 21;
    int flags = DRAWSPRITE_FLAG_CENTER | DRAWSPRITE_FLAG_WIDGETPOS;
    Unit_ClearViewportKey(&unit);
    check_unit_key(&unit, 111, 0, flags, false, 0, false, NULL, 1);
    for (unsigned blitter = 0; blitter < 2; blitter++)
        for (int x = -48; x < 48; x++) {
            unit.o.position.x = (x + 48) * 16;
            check_unit_key(&unit, 111, 0, flags, false, x, blitter, NULL, 0);
        }
    GUI_SpriteLayers layers = {0};
    layers.count = 2;
    for (unsigned i = 0; i < 2; i++) {
        layers.layer[i].spriteID = i + 1;
        layers.layer[i].colourHouse = i;
        layers.layer[i].flags = i & 3;
        layers.layer[i].offsetX = -14 + i;
        layers.layer[i].offsetY = 7 - i;
    }
    Unit_ClearViewportKey(&unit);
    check_unit_key(&unit, 112, 2, flags | 3, true, -17, false, &layers, 1);
    for (unsigned blitter = 0; blitter < 2; blitter++)
        for (int x = -32; x < 32; x++)
            check_unit_key(&unit, 112, 2, flags | 3, true, x, blitter, &layers, 0);
    for (unsigned i = 0; i < 2; i++) {
        layers.layer[i].spriteID++;
        layers.layer[i].colourHouse = GUI_SPRITE_COLOUR_EMBEDDED;
        layers.layer[i].flags ^= 3;
        layers.layer[i].offsetX++;
        layers.layer[i].offsetY--;
        Unit_ClearViewportKey(&unit);
        check_unit_key(&unit, 112, 2, flags | 3, true, 10, false, &layers, 1);
    }
    /* External appearance events clear keys; preparation does not rediscover them. */
    layers.count = 0;
    Unit_ClearViewportKey(&unit);
    check_unit_key(&unit, 111, 0, flags, false, 1, false, &layers, 1);
    layers.count = 1;
    layers.layer[0].spriteID = 6;
    layers.layer[0].colourHouse = GUI_SPRITE_COLOUR_EMBEDDED;
    layers.layer[0].flags = 0;
    layers.layer[0].offsetX = layers.layer[0].offsetY = 0;
    g_unitSelected = &unit;
    Unit_ClearViewportKey(&unit);
    check_unit_key(&unit, 111, 0, flags, false, 1, false, &layers, 1);
    check_unit_key(&unit, 111, 0, flags, false, 2, false, &layers, 0);
    g_unitSelected = &other;
    Unit_ClearViewportKey(&unit);
    Unit_ClearViewportKey(&other);
    check_unit_key(&other, 111, 0, flags, false, 1, false, &layers, 1);
    layers.count = 0;
    check_unit_key(&unit, 111, 0, flags, false, 1, false, &layers, 1);
    g_unitSelected = NULL;
    Unit_ClearViewportKey(&other);
    check_unit_key(&other, 111, 0, flags, false, 1, false, &layers, 1);
    assert(unit.viewportKey.main == other.viewportKey.main);
    /* Explicit invalidation rebuilds changed layer identities. */
    unit.actionID = ACTION_HARVEST;
    unit.o.position.x = unit.o.position.y = 0;
    Unit_ClearViewportKey(&unit);
    check_unit_key(&unit, 111, 0, flags, false, 1, false, &layers, 1);
    Unit_ClearViewportKey(&unit);
    layers.count = 1;
    layers.layer[0].spriteID = 223;
    check_unit_key(&unit, 111, 0, flags, false, 1, false, &layers, 1);
    Unit_ClearViewportKey(&unit);
    check_unit_key(&unit, 111, 0, flags, false, 1, false, &layers, 1);
    unit.o.position.x = 256;
    Unit_ClearViewportKey(&unit);
    check_unit_key(&unit, 111, 0, flags, false, 1, false, &layers, 1);
    Unit_ClearViewportKey(&unit);
    layers.count = 0;
    check_unit_key(&unit, 111, 0, flags, false, 1, false, &layers, 1);
    unit.spriteOffset = -1;
    Unit_ClearViewportKey(&unit);
    check_unit_key(&unit, 111, 0, flags, false, 1, false, &layers, 1);
    /* Switching render paths patches phase without rebuilding or moving tails. */
    for (unsigned i = 0; i < 32; i++) {
        check_unit_key(&unit, 111, 0, flags, false, i, false, &layers, 0);
        check_unit_key(&unit, 111, 0, flags, false, i, true, &layers, 0);
    }
}
static void assertion_failed(int signum) { _Exit(signum == SIGABRT ? 90 : 91); }
int main(int argc, char **argv) {
    unsigned before;
    check_compact_keys();
    check_unit_keys();
    s_viewportBlitter = argc > 1;
    batchRepairs = s_viewportBlitter;
    for (unsigned id = 0; id < 70; id++) {
        uint8 *sprite = sprites[id];
        g_sprites[id] = sprite;
        sprite[0] = id == 6 ? 2 : 3; sprite[2] = 27; sprite[3] = 23;
        for (unsigned x = 0; x < 16; x++) sprite[10 + x] = x;
        if(id>=68) {
            sprite[11]=0;
            for(unsigned x=2;x<=10;x++) sprite[10+x]=0x90+x-2;
        }
        for (unsigned y = 0; y < 27; y++) for (unsigned x = 0; x < 23; x++)
            sprite[(id == 6 ? 10 : 26) + y * 23 + x] =
                (x + y) % 5 == 0 ? 0 : (id == 6 ? 200 : 1) + (x + y) % 15;
        slots[id].sprite = sprite; slots[id].width = 23; slots[id].height = 27;
        slots[id].rows = maskStorage[id];
        for (unsigned mirror = 0; mirror < 2; mirror++)
            for (unsigned y = 0; y < 27; y++) for (unsigned x = 0; x < 23; x++)
                if (sprite[(id == 6 ? 10 : 26) + y * 23 + (mirror ? 22 - x : x)])
                    maskStorage[id][mirror * 54 + y * 2 + (x >> 4)] |= 0x8000u >> (x & 15);
    }
    g_sprites[111] = sprites[0];
    for (unsigned x = 0; x < 16; x++) palette[x] = x + 16;
    for (unsigned x = 0; x < 256; x++) remap[x] = x;
    for (unsigned x = 0x90; x <= 0xe8; x++) remap[x] = (x >> 4) ^ (x & 15);
    remap[17] = 0; remap[0] = 2;
    s_viewportPlanarSprites = calloc(VIEWPORT_PLANAR_SPRITES, sizeof(*s_viewportPlanarSprites));
    s_viewportPlanarMasks = calloc(VIEWPORT_PLANAR_SPRITES * 320 * (s_viewportBlitter ? 4 : 1),
                                  sizeof(*s_viewportPlanarMasks));
    s_viewportPlanarComponents = calloc(VIEWPORT_PLANAR_COMPONENTS, sizeof(*s_viewportPlanarComponents));
    assert(s_viewportPlanarSprites && s_viewportPlanarMasks && s_viewportPlanarComponents);
    assert(g_paletteMapping2 == remap);
    assert(expected_sprite_victim() == s_viewportPlanarSprites);
    assert(expected_component_victim() == s_viewportPlanarComponents);
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++)
        s_viewportPlanarSprites[i].masks = s_viewportPlanarMasks + i * 320 * (s_viewportBlitter ? 4 : 1);
    rebuild_directory();
    uint16 emptyPosition = 99;
    const uint32 emptyLayers[2] = {0};
    if (argc > 2) {
        signal(SIGABRT, assertion_failed);
        GUI_SpriteLayers invalid = {1, {{0, GUI_SPRITE_COLOUR_EMBEDDED, 0, 0, 0, {0}}}};
        switch (atoi(argv[2])) {
            case 0: draw_identity(0, GUI_SPRITE_COLOUR_EMBEDDED, 0); break;
            case 1: draw_identity(GUI_SPRITE_ID_UNKNOWN, GUI_SPRITE_COLOUR_EMBEDDED, 0); break;
            case 2: draw_identity(1, GUI_SPRITE_COLOUR_EMBEDDED, 0); break;
            case 3: draw_identity(111, GUI_SPRITE_COLOUR_UNKNOWN, DRAWSPRITE_FLAG_PAL, palette); break;
            case 4: draw_identity(111, 0, 0); break;
            case 5: draw(sprites[0], 64, 60, DRAWSPRITE_FLAG_ZOOM); break;
            case 6: draw(sprites[0], 64, 60, DRAWSPRITE_FLAG_BLUR); break;
            case 7: draw(sprites[0], 64, 60, DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_REMAP,
                         palette, remap, 2); break;
            case 8: draw_layers(&invalid, 64, 60, DRAWSPRITE_FLAG_PAL, palette); break;
            case 9:
                invalid.layer[0] = (GUI_SpriteLayer){6, GUI_SPRITE_COLOUR_EMBEDDED, 1, 0, 0, {0}};
                draw_layers(&invalid, 64, 60, DRAWSPRITE_FLAG_PAL, palette);
                break;
            case 10:
                invalid.count = 2;
                invalid.layer[0] = (GUI_SpriteLayer){6, GUI_SPRITE_COLOUR_EMBEDDED, 0, 0, 0, {0}};
                invalid.layer[1] = (GUI_SpriteLayer){3, GUI_SPRITE_COLOUR_EMBEDDED, 0, 0, 0, {0}};
                draw_layers(&invalid, 64, 60, DRAWSPRITE_FLAG_PAL, palette);
                break;
            case 11:
                s_viewportPlanar = false;
                draw(sprites[0], 64, 60, 0);
                break;
            case 12:
                invalid.count = 2;
                invalid.layer[0] = (GUI_SpriteLayer){2, GUI_SPRITE_COLOUR_EMBEDDED, 0, -32, 0, {0}};
                invalid.layer[1] = (GUI_SpriteLayer){3, GUI_SPRITE_COLOUR_EMBEDDED, 0, 31, 0, {0}};
                draw_layers(&invalid, 64, 60, DRAWSPRITE_FLAG_PAL, palette);
                break;
            case 13:
                draw_identity(111, GUI_SPRITE_COLOUR_EMBEDDED, DRAWSPRITE_FLAG_PAL_DEFERRED);
                break;
            case 14:
                invalid.layer[0] = (GUI_SpriteLayer){2, GUI_SPRITE_COLOUR_EMBEDDED, 0, 0,
                    DRAWSPRITE_FLAG_PAL_DEFERRED, {0}};
                draw_layers(&invalid, 64, 60, DRAWSPRITE_FLAG_PAL, palette);
                break;
            default: return 3;
        }
        return 2;
    }
    assert(!s_viewportPlanarClock && !s_viewportComponentClock && !decodes && !encodes);
    assert_directory();
    assert(!GUI_ViewportFindPlanarSprite(0x80000000UL, emptyLayers, &emptyPosition));
    assert(emptyPosition == 64 && lookupCandidates == 6 && firstBinaryPosition == 32);
    for (unsigned flags = 0; flags < 4; flags++) for (unsigned phase = 0; phase < 16; phase++) {
        check(0, 64 + phase, 60, flags, false);
        before = decodes;
        unsigned plans = blitterPlanBuilds, cached = cachedPlanDraws;
        unsigned scans = evictionCandidates;
        unsigned probes = lookupCandidates;
        check(0, 64 + phase, 60, flags, false);
        assert(evictionCandidates == scans);
        assert(lookupCandidates > probes && lookupCandidates <= probes + 14);
        assert_directory();
        assert(decodes == before);
        assert(blitterPlanBuilds == plans);
        assert(cachedPlanDraws == cached + (s_viewportBlitter ? 1 : 0));
    }
    assert(decodes == 4 && encodes == 4);
    assert(compositions == (s_viewportBlitter ? 4 : 64));
    assert(blitterPlanBuilds == (s_viewportBlitter ? 4 * 16 : 0));
    if (s_viewportBlitter) assert(blitterLaunches && !(blitterLaunches % 8));
    for (unsigned flags = 0; flags < 4; flags++) {
        unsigned plans = blitterPlanBuilds;
        check(0, 64, 33, flags, false);
        check(0, 64, 191, flags, false);
        assert(blitterPlanBuilds == plans);
        check(0, -13, 33, flags, false);
        assert(blitterPlanBuilds == plans + (s_viewportBlitter ? 1 : 0));
        check(0, 231, 191, flags, false);
        assert(blitterPlanBuilds == plans + (s_viewportBlitter ? 2 : 0));
        check(0, 4, 45, flags | DRAWSPRITE_FLAG_CENTER, false);
        check(0, 64, 20, flags | DRAWSPRITE_FLAG_WIDGETPOS, false);
    }
    overlays = true;
    check(0, 65, 60, DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_REMAP, true);
    assert(overlayWrites);
    overlays = false;
    check(0, 64, 60, DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_REMAP, true);
    before = decodes;
    check(0, 64, 60, DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_REMAP, true);
    assert(decodes == before);
    assert(decodes == before);
    /* Explicit house 0, embedded palette, and another house are separate keys. */
    assert(draw_identity(111, 0, DRAWSPRITE_FLAG_PAL, palette));
    assert(draw_identity(111, 1, DRAWSPRITE_FLAG_PAL, palette));
    before = decodes;
    assert(draw_identity(111, 0, DRAWSPRITE_FLAG_PAL, palette));
    assert(draw_identity(111, 1, DRAWSPRITE_FLAG_PAL, palette));
    assert(decodes == before);
    for (unsigned id = 1; id < 70; id++) check(id, 64, 60, 0, false);
    before = decodes;
    check(69, 64, 60, 0, false);
    assert(decodes == before);
    check(0, 64, 60, 0, false);
    assert(decodes == before + 1);
    s_viewportPlanarClock = 65535;
    check(0, 64, 60, 0, false);
    assert(s_viewportPlanarClock == 2 && decodes == before + 1);
    before = decodes;
    ViewportPlanarSpriteKey savedDirectory[64];
    memcpy(savedDirectory, s_viewportPlanarKeys, sizeof(savedDirectory));
    assert(draw(sprites[0], -100, -100, 0) && decodes == before);
    assert(!memcmp(savedDirectory, s_viewportPlanarKeys, sizeof(savedDirectory)));
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) s_viewportPlanarSprites[i].key.main = 0;
    rebuild_directory();
    memset(s_viewportPlanarComponents, 0, VIEWPORT_PLANAR_COMPONENTS * sizeof(*s_viewportPlanarComponents));
    /* Native body and attachment palettes are resolved only on component misses. */
    for(unsigned house=0;house<HOUSE_MAX;house++) {
        GUI_SpriteLayers lazy={1,{{69,house,2,-5,
            DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_PAL_DEFERRED | DRAWSPRITE_FLAG_BOTTOMUP,{0}}}};
        uint8 bodyColours[16], turretColours[16];
        memset(lazy.layer[0].palette,0xa5,sizeof(lazy.layer[0].palette));
        for(unsigned i=0;i<16;i++) {
            uint8 b=sprites[68][10+i], t=sprites[69][10+i];
            bodyColours[i]=b>=0x90 && b<=0x98 ? b+(house<<4) : b;
            turretColours[i]=t>=0x90 && t<=0x98 ? t+(house<<4) : t;
        }
        for(unsigned pass=0;pass<3;pass++) {
            if(pass==2) {
                for(unsigned i=0;i<VIEWPORT_PLANAR_SPRITES;i++) s_viewportPlanarSprites[i].key.main=0;
                rebuild_directory();
            }
            unsigned lookups=houseLookups, decoded=decodes, encoded=encodes;
            int x=80+pass, y=80;
            for(unsigned i=0;i<16000;i++) visible[i]=expected[i]=i*137+41;
            reference_layer(68,x,y,0,bodyColours,remap);
            reference_layer(69,x+2,y-5,DRAWSPRITE_FLAG_BOTTOMUP,turretColours,NULL);
            draw_house(68,house,&lazy,x,y,
                DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_PAL_DEFERRED |
                DRAWSPRITE_FLAG_REMAP | DRAWSPRITE_FLAG_CENTER,
                (uint8 *)NULL,remap,1);
            assert(houseLookups==lookups+(pass==0?2:0));
            assert(decodes==decoded+(pass==0?2:0) && encodes==encoded+(pass==0?2:0));
            assert(!memcmp(visible,expected,sizeof(visible)) && !pendingRepair);
        }
    }
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) s_viewportPlanarSprites[i].key.main = 0;
    rebuild_directory();
    memset(s_viewportPlanarComponents, 0, VIEWPORT_PLANAR_COMPONENTS * sizeof(*s_viewportPlanarComponents));
    /* Complete unit: turret/attachment, smoke, fixed selection.
     * Overlap, opaque colour 0, wide negative offsets and taller bounds matter. */
    GUI_SpriteLayers layers = {3, {
        {2, 2, 2, -5, DRAWSPRITE_FLAG_BOTTOMUP | DRAWSPRITE_FLAG_PAL, {0}},
        {3, GUI_SPRITE_COLOUR_EMBEDDED, 0, -14, 0, {0}},
        {6, GUI_SPRITE_COLOUR_EMBEDDED, 0, 0, 0, {0}}
    }};
    for (unsigned i = 0; i < 16; i++) layers.layer[0].palette[i] = i == 1 ? 0 : i + 32;
    before = decodes;
    unsigned encoded = encodes;
    check_layers(&layers, 65, 50, DRAWSPRITE_FLAG_RTL);
    assert(decodes == before + 4 && encodes == encoded + 4);
    before = decodes;
    encoded = encodes;
    unsigned composed = compositions;
    overlays = true;
    check_layers(&layers, 81, 66, DRAWSPRITE_FLAG_RTL);
    assert(decodes == before && encodes == encoded && compositions == composed);
    overlays = false;
    layers.count = 2;
    check_layers(&layers, 65, 50, DRAWSPRITE_FLAG_RTL);
    assert(decodes == before && encodes == encoded && compositions == composed + 3);
    before = decodes;
    layers.count = 3;
    check_layers(&layers, 65, 50, DRAWSPRITE_FLAG_RTL);
    assert(decodes == before);
    layers.layer[0].offsetX--;
    check_layers(&layers, 65, 50, DRAWSPRITE_FLAG_RTL);
    assert(decodes == before && encodes == encoded);
    before = decodes;
    layers.layer[0].colourHouse++;
    layers.layer[0].palette[1] = 7;
    check_layers(&layers, 65, 50, DRAWSPRITE_FLAG_RTL);
    assert(decodes == before + 1 && encodes == encoded + 1);
    layers.layer[0].spriteID++;
    layers.layer[0].flags ^= DRAWSPRITE_FLAG_RTL;
    check_layers(&layers, -5, 0, DRAWSPRITE_FLAG_BOTTOMUP);
    check_layers(&layers, 239, 159, DRAWSPRITE_FLAG_BOTTOMUP);
    before = decodes;
    check_layers(&layers, 65, 50, DRAWSPRITE_FLAG_RTL);
    assert(decodes == before);
    /* A composite eviction must not discard its independently cached parts. */
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) s_viewportPlanarSprites[i].key.main = 0;
    rebuild_directory();
    encoded = encodes;
    composed = compositions;
    check_layers(&layers, 65, 50, DRAWSPRITE_FLAG_RTL);
    assert(decodes == before && encodes == encoded && compositions == composed + 4);
    /* Composite alignment is determined by the union, not just the body.
     * Exercise every phase/flip at both viewport edges and on cache hits. */
    for (unsigned flags = 0; flags < 4; flags++) {
        for (unsigned phase = 0; phase < 16; phase++) {
            check_layers(&layers, 64 + phase, 50, flags);
            before = decodes;
            encoded = encodes;
            check_layers(&layers, 80 + phase, 66, flags);
            assert(decodes == before && encodes == encoded);
            check_layers(&layers, -5 + phase, 0, flags);
            check_layers(&layers, 224 + phase, 159, flags);
        }
    }
    /* Phase changes/rebuilt composites do not generate more component variants. */
    before = decodes;
    encoded = encodes;
    composed = compositions;
    for (unsigned phase = 0; phase < 16; phase++) check_layers(&layers, 64 + phase, 50, 0);
    assert(decodes == before && encodes == encoded);
    if (s_viewportBlitter) assert(compositions == composed);
    /* A new smoke frame decodes only itself, not the body/turret/selection. */
    layers.layer[1].spriteID = 4;
    check_layers(&layers, 79, 50, 0);
    assert(decodes == before + 1 && encodes == encoded + 1);
    before = decodes;
    encoded = encodes;
    layers.layer[1].spriteID = 3;
    check_layers(&layers, 79, 50, 0);
    assert(decodes == before && encodes == encoded);
    s_viewportComponentClock = 65535;
    ViewportPlanarComponent *component = GUI_ViewportPlanarComponent(slots, 111, 0, 0, palette, remap);
    assert(s_viewportComponentClock == 1 && decodes == before && component->used == 1);
    /* Component evictions cannot invalidate a completed composite. */
    for (unsigned id = 7; id < 70; id++)
        GUI_ViewportPlanarComponent(slots + id, id, GUI_SPRITE_COLOUR_EMBEDDED, 0, NULL, NULL);
    before = decodes;
    check_layers(&layers, 79, 50, 0);
    assert(decodes == before);
    {
        uint16 dst[1280], want[1280], opacity[320], wantOpacity[320];
        uint16 src[256], srcMasks[64];
        unsigned widths[] = {1, 16, 17, 32};
        for (unsigned w = 0; w < 4; w++) for (unsigned height = 1; height <= 32; height += 31) {
            unsigned width = widths[w], stride = (width + 15) & ~15, groups = stride / 16;
            for (unsigned x = 0; x + width <= 80; x++) {
                unsigned top = 64 - height;
                for (unsigned i = 0; i < 1280; i++) dst[i] = want[i] = i * 137 + 41;
                for (unsigned i = 0; i < 320; i++) opacity[i] = wantOpacity[i] = i * 113 + 13;
                memset(src, 0, sizeof(src));
                memset(srcMasks, 0, sizeof(srcMasks));
                for (unsigned y = 0; y < height; y++) for (unsigned col = 0; col < width; col++) {
                    if ((x & 1) && (col + y) % 5 == 0) continue;
                    uint16 colour = (col * 3 + y) & 15;
                    uint16 sb = 0x8000u >> (col & 15), db = 0x8000u >> ((x + col) & 15);
                    unsigned si = y * groups + col / 16, di = (top + y) * 5 + (x + col) / 16;
                    srcMasks[si] |= sb;
                    wantOpacity[di] |= db;
                    for (unsigned p = 0; p < 4; p++) {
                        if (colour & (1u << p)) src[si * 4 + p] |= sb;
                        want[di * 4 + p] = (want[di * 4 + p] & (uint16)~db) |
                            ((colour & (1u << p)) ? db : 0);
                    }
                }
                Video_Atari_ComposePlanarSprite(dst, opacity, 80, 64,
                    src, srcMasks, stride, height, x, top);
                assert(!memcmp(dst, want, sizeof(dst)));
                assert(!memcmp(opacity, wantOpacity, sizeof(opacity)));
            }
        }
    }
    if (s_viewportBlitter) {
        uint16 image[1280], masks[1280];
        overlays = false;
        for (unsigned stride = 16; stride <= 80; stride += 16) {
            unsigned groups = stride / 16;
            for (unsigned row = 0; row < 64; row++) for (unsigned group = 0; group < groups; group++) {
                uint16 mask = 0xa39f ^ (row * 131 + group * 911);
                for (unsigned p = 0; p < 4; p++) {
                    unsigned i = row * groups * 4 + group * 4 + p;
                    masks[i] = mask;
                    image[i] = (i * 137 + 41) & mask;
                }
            }
            for (unsigned edge = 0; edge < (groups == 1 ? 1u : 2u); edge++)
                for (unsigned phase = 0; phase < 16; phase++)
                    for (unsigned sourcePhase = 0; sourcePhase < 16; sourcePhase++) {
                        unsigned sourceX = (edge ? stride - 16 : 0) + sourcePhase;
                        unsigned remaining = stride - sourceX;
                        unsigned widths[] = {1, min(remaining, 16 - sourcePhase),
                                             min(remaining, 17 - sourcePhase), remaining};
                        unsigned heights[] = {1, 16, 64};
                        for (unsigned wi = 0; wi < 4; wi++) for (unsigned hi = 0; hi < 3; hi++) {
                            unsigned width = widths[wi], height = heights[hi], x = 64 + phase, y = 136;
                            for (unsigned i = 0; i < 16000; i++) visible[i] = expected[i] = i * 113 + 17;
                            for (unsigned row = 0; row < height; row++) for (unsigned col = 0; col < width; col++) {
                                unsigned source = row * groups * 4 + ((sourceX + col) / 16) * 4;
                                uint16 sb = 0x8000u >> ((sourceX + col) & 15);
                                uint16 db = 0x8000u >> ((x + col) & 15);
                                if (!(masks[source] & sb)) continue;
                                for (unsigned p = 0; p < 4; p++) {
                                    unsigned dest = (y + row) * 80 + ((x + col) / 16) * 4 + p;
                                    expected[dest] = (expected[dest] & (uint16)~db) |
                                        (image[source + p] & sb ? db : 0);
                                }
                            }
                            unsigned launches = blitterLaunches, setups = blitterSetups;
                            GUI_Widget_Viewport_RepairTiles(x & ~15, y, (x + width + 15) & ~15, y + height);
                            Video_Atari_PresentPlanarSpriteUnshifted(image, masks, stride, sourceX,
                                                                    width, height, x, y, NULL);
                            assert(!pendingRepair && blitterLaunches == launches + 8);
                            assert(blitterSetups == setups + 1);
                            assert(!memcmp(visible, expected, sizeof(visible)));
                        }
                    }
            /* Compare every full-image width/phase plan with calculated
             * geometry, including retained source padding and vertical clips. */
            for (unsigned width = 1; width <= stride; width++) {
                Video_Atari_SpriteBlitPlan plans[16];
                unsigned builds = blitterPlanBuilds;
                Video_Atari_BuildSpriteBlitPlans(plans, stride, width);
                assert(blitterPlanBuilds == builds + 16);
                for (unsigned phase = 0; phase < 16; phase++) {
                    Video_Atari_SpriteBlitPlan calculated;
                    Video_Atari_BuildSpriteBlitPlan(&calculated, stride, 0, width, phase);
                    assert(plans[phase].words == calculated.words);
                    assert(plans[phase].firstMask == calculated.firstMask);
                    assert(plans[phase].lastMask == calculated.lastMask);
                    assert(plans[phase].sourceXinc == calculated.sourceXinc);
                    assert(plans[phase].sourceYinc == calculated.sourceYinc);
                    assert(plans[phase].destinationYinc == calculated.destinationYinc);
                    assert(plans[phase].skew == calculated.skew);
                    for (unsigned top = 0; top < 2; top++) {
                        uint16 reference[16000];
                        unsigned offset = top * groups * 4;
                        for (unsigned i = 0; i < 16000; i++) visible[i] = i * 113 + 17;
                        GUI_Widget_Viewport_RepairTiles(64, 136, (64 + phase + width + 15) & ~15, 152);
                        Video_Atari_PresentPlanarSpriteUnshifted(image + offset, masks + offset,
                            stride, 0, width, 16, 64 + phase, 136, NULL);
                        memcpy(reference, visible, sizeof(reference));
                        for (unsigned i = 0; i < 16000; i++) visible[i] = i * 113 + 17;
                        builds = blitterPlanBuilds;
                        GUI_Widget_Viewport_RepairTiles(64, 136, (64 + phase + width + 15) & ~15, 152);
                        Video_Atari_PresentPlanarSpriteUnshifted(image + offset, masks + offset,
                            stride, 0, width, 16, 64 + phase, 136, &plans[phase]);
                        assert(blitterPlanBuilds == builds && !pendingRepair);
                        assert(!memcmp(reference, visible, sizeof(reference)));
                    }
                }
            }
        }
    }
    assert(dirtyClears);
    /* A late hit must not select earlier empty slots for eviction. */
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) s_viewportPlanarSprites[i].key.main = 0;
    rebuild_directory();
    memset(s_viewportPlanarComponents, 0, VIEWPORT_PLANAR_COMPONENTS * sizeof(*s_viewportPlanarComponents));
    check(0, 64, 60, 0, false);
    uint16 *lateMasks = s_viewportPlanarSprites[63].masks;
    memcpy(lateMasks, s_viewportPlanarSprites[0].masks,
           320 * (s_viewportBlitter ? 4 : 1) * sizeof(*lateMasks));
    s_viewportPlanarSprites[63] = s_viewportPlanarSprites[0];
    s_viewportPlanarSprites[63].masks = lateMasks;
    s_viewportPlanarSprites[0].key.main = 0;
    s_viewportPlanarComponents[63] = s_viewportPlanarComponents[0];
    s_viewportPlanarComponents[0].key = 0;
    rebuild_directory();
    unsigned scans = evictionCandidates;
    unsigned probes = lookupCandidates;
    s_viewportPlanarClock = 65535;
    check(0, 64, 60, 0, false);
    assert(evictionCandidates == scans && s_viewportPlanarClock == 2);
    assert(lookupCandidates == probes + 7);
    assert(s_viewportPlanarSprites[63].used == 2 && !s_viewportPlanarSprites[0].key.main);
    /* Physical slot order is independent of directory order. */
    s_viewportPlanarSprites[0].key.main = s_viewportPlanarSprites[63].key.main;
    s_viewportPlanarSprites[63].key.main = 0;
    rebuild_directory();
    probes = lookupCandidates;
    check(0, 64, 60, 0, false);
    assert(lookupCandidates == probes + 7);
    assert(evictionCandidates == scans && s_viewportPlanarSprites[0].used == 4);
    /* Same body with and without a layer must remain distinct. */
    s_viewportPlanarSprites[1].key.main = s_viewportPlanarSprites[0].key.main | (0xc06u << 20);
    s_viewportPlanarSprites[1].key.tail[0] = 1;
    rebuild_directory();
    probes = lookupCandidates;
    check(0, 64, 60, 0, false);
    assert(lookupCandidates == probes + 6);
    assert(evictionCandidates == scans);
    s_viewportComponentClock = 65535;
    component = GUI_ViewportPlanarComponent(slots, 111, GUI_SPRITE_COLOUR_EMBEDDED, 0, NULL, NULL);
    assert(component == s_viewportPlanarComponents + 63 && component->used == 1);
    assert(evictionCandidates == scans && !s_viewportPlanarComponents[0].key);
    for (unsigned empty = 0; empty < 2; empty++) {
        for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) {
            s_viewportPlanarSprites[i].key.main = 0xdead0000UL | i;
            s_viewportPlanarSprites[i].used = 9;
        }
        for (unsigned i = 0; i < VIEWPORT_PLANAR_COMPONENTS; i++) {
            s_viewportPlanarComponents[i].key = 0xdead0000UL | i;
            s_viewportPlanarComponents[i].used = 9;
        }
        s_viewportPlanarSprites[7].used = s_viewportPlanarSprites[19].used = 3;
        s_viewportPlanarComponents[7].used = s_viewportPlanarComponents[19].used = 3;
        if (empty) {
            s_viewportPlanarSprites[11].key.main = s_viewportPlanarSprites[23].key.main = 0;
            s_viewportPlanarComponents[11].key = s_viewportPlanarComponents[23].key = 0;
        }
        rebuild_directory();
        scans = evictionCandidates;
        probes = lookupCandidates;
        check(0, 64, 60, 0, false);
        assert(evictionCandidates == scans + VIEWPORT_PLANAR_SPRITES + VIEWPORT_PLANAR_COMPONENTS);
        unsigned victim = empty ? 11 : 7;
        assert(lookupCandidates > probes && lookupCandidates <= probes + 14);
        assert_directory();
        assert(s_viewportPlanarSprites[victim].key.main == 0x00000c6fUL);
        assert(s_viewportPlanarComponents[victim].key == 0x80000c6fUL);
        assert(s_viewportPlanarSprites[19].key.main == 0xdead0013UL);
        assert(s_viewportPlanarComponents[19].key == 0xdead0013UL);
        if (empty) {
            assert(!s_viewportPlanarSprites[23].key.main && !s_viewportPlanarComponents[23].key);
        }
    }
    /* Exercise insertion at both ends and every packed word comparison, including
     * unsigned values and absent layers, independently of sprite decoding. */
    for (unsigned differing = 0; differing < 3; differing++) {
        for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) s_viewportPlanarSprites[i].key.main = 0;
        rebuild_directory();
        for (unsigned n = 0; n < 64; n++) {
            unsigned slot = (n * 37) & 63;
            uint32 words[3] = {0x80000001UL, 0, 0};
            words[differing] = 0x80000000UL + slot * 2;
            uint16 position;
            probes = lookupCandidates;
            assert(!GUI_ViewportFindPlanarSprite(words[0], words + 1, &position));
            assert(lookupCandidates <= probes + 8);
            assert(firstBinaryPosition == 32);
            ViewportPlanarSprite *previousHit =
                s_viewportPlanarLastHitPosition < VIEWPORT_PLANAR_SPRITES ?
                s_viewportPlanarKeys[s_viewportPlanarLastHitPosition].sprite : NULL;
            ViewportPlanarSprite *entry = s_viewportPlanarSprites + slot;
            entry->key.main = words[0];
            memcpy(entry->key.tail, words + 1, sizeof(entry->key.tail));
            GUI_ViewportIndexPlanarSprite(entry, position);
            assert_directory();
            if (previousHit)
                assert(s_viewportPlanarKeys[s_viewportPlanarLastHitPosition].sprite == previousHit);
            /* Check every occupancy from one through 64, including searches
             * on either side of the live suffix and hints shifted by insertion. */
            for (unsigned index = 64 - n - 1; index < 64; index++) {
                const ViewportPlanarSpriteKey *key = s_viewportPlanarKeys + index;
                probes = lookupCandidates;
                assert(GUI_ViewportFindPlanarSprite(key->key.main, key->key.tail, &position) == key->sprite);
                assert(position == index && lookupCandidates <= probes + 8);
            }
            uint16 last = s_viewportPlanarLastHitPosition;
            unsigned comparisons = layerComparisons;
            assert(!GUI_ViewportFindPlanarSprite(1, emptyLayers, &position));
            assert(position == 64 - n - 1 && firstBinaryPosition == 32);
            assert(s_viewportPlanarLastHitPosition == last);
            assert(!GUI_ViewportFindPlanarSprite(0xffffffffUL, emptyLayers, &position));
            assert(position == 64 && firstBinaryPosition == 32);
            assert(s_viewportPlanarLastHitPosition == last);
            assert(layerComparisons == comparisons);
        }
        for (unsigned slot = 0; slot < 64; slot++) {
            ViewportPlanarSprite *entry = s_viewportPlanarSprites + slot;
            uint16 position;
            probes = lookupCandidates;
            assert(GUI_ViewportFindPlanarSprite(entry->key.main, entry->key.tail, &position) == entry);
            assert(lookupCandidates > probes && lookupCandidates <= probes + 8);
            assert(position == slot);
            unsigned matches = lastHitMatches;
            unsigned comparisons = layerComparisons;
            probes = lookupCandidates;
            assert(GUI_ViewportFindPlanarSprite(entry->key.main, entry->key.tail, &position) == entry);
            assert(position == slot && lookupCandidates == probes + 1);
            assert(lastHitMatches == matches + 1);
            assert(layerComparisons == comparisons);
            uint32 words[3];
            words[0] = entry->key.main;
            memcpy(words + 1, entry->key.tail, sizeof(entry->key.tail));
            words[differing]++;
            probes = lookupCandidates;
            assert(!GUI_ViewportFindPlanarSprite(words[0], words + 1, &position));
            assert(position == slot + 1 && lookupCandidates <= probes + 8);
            assert(s_viewportPlanarLastHitPosition == slot);
            assert(firstBinaryPosition == 32);
        }
        /* Replace a high key with a low key and then a low key with a high
         * key: removal must adjust the saved insertion position correctly. */
        for (unsigned pass = 0; pass < 4; pass++) {
            ViewportPlanarSprite *entry = s_viewportPlanarSprites + (pass ? 0 : 63);
            uint32 words[3] = {0x80000001UL, 0, 0};
            words[differing] = pass & 1 ? 0xffffffffUL : pass == 0 ? 1 : 2;
            uint16 position;
            if (pass >= 2) {
                ViewportPlanarSprite *middle = s_viewportPlanarSprites + 32;
                assert(GUI_ViewportFindPlanarSprite(middle->key.main, middle->key.tail, &position) == middle);
            }
            assert(!GUI_ViewportFindPlanarSprite(words[0], words + 1, &position));
            ViewportPlanarSprite *previousHit =
                s_viewportPlanarKeys[s_viewportPlanarLastHitPosition].sprite;
            uint32 oldKey = entry->key.main, oldLayers[2];
            memcpy(oldLayers, entry->key.tail, sizeof(oldLayers));
            entry->key.main = words[0];
            memcpy(entry->key.tail, words + 1, sizeof(entry->key.tail));
            GUI_ViewportIndexPlanarSprite(entry, position);
            assert_directory();
            if (entry == previousHit) {
                assert(s_viewportPlanarLastHitPosition == VIEWPORT_PLANAR_SPRITES);
            } else {
                assert(s_viewportPlanarKeys[s_viewportPlanarLastHitPosition].sprite == previousHit);
                probes = lookupCandidates;
                assert(GUI_ViewportFindPlanarSprite(previousHit->key.main, previousHit->key.tail,
                                                   &position) == previousHit);
                assert(lookupCandidates == probes + 1);
            }
            assert(!GUI_ViewportFindPlanarSprite(oldKey, oldLayers, &position));
            assert(GUI_ViewportFindPlanarSprite(words[0], words + 1, &position) == entry);
            assert(position == (pass & 1 ? 63 : pass == 0 ? 0 : 1));
        }
    }
    /* Every layerless hit/miss accepts an unreadable requested tail, including
     * the hint shortcut and every directory occupancy. */
    for (unsigned count = 0; count <= 64; count++) {
        for (unsigned slot = 0; slot < 64; slot++) {
            ViewportPlanarSprite *entry = s_viewportPlanarSprites + slot;
            entry->key.main = slot < count ? slot * 2 + 1 : 0;
            memset(entry->key.tail, 0, sizeof(entry->key.tail));
        }
        rebuild_directory();
        for (unsigned key = 1; key <= 129; key++) {
            uint16 position;
            unsigned comparisons = layerComparisons;
            ViewportPlanarSprite *entry = GUI_ViewportFindPlanarSprite(key, NULL, &position);
            bool found = (key & 1) && key / 2 < count;
            assert(entry == (found ? s_viewportPlanarSprites + key / 2 : NULL));
            assert(position == 64 - count + min(count, key / 2));
            assert(layerComparisons == comparisons);
            if (entry) {
                unsigned matches = lastHitMatches;
                assert(GUI_ViewportFindPlanarSprite(key, NULL, &position) == entry);
                assert(lastHitMatches == matches + 1 && layerComparisons == comparisons);
            }
        }
    }
    /* Real insertions/evictions and layered hits retain fixed image slots. */
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) s_viewportPlanarSprites[i].key.main = 0;
    rebuild_directory();
    for (unsigned id = 0; id < 70; id++) {
        check(id, 64, 60, 0, false);
        assert_directory();
    }
    check_layers(&layers, 64, 50, 0);
    assert_directory();
    ViewportPlanarSprite images[64];
    memcpy(images, s_viewportPlanarSprites, sizeof(images));
    before = decodes; encoded = encodes; composed = compositions;
    GUI_SetViewportPlanar(false);
    GUI_SetViewportPlanar(true);
    check_layers(&layers, 64, 50, 0);
    assert(decodes == before && encodes == encoded && compositions == composed);
    for (unsigned i = 0; i < 64; i++) {
        ViewportPlanarSprite actual = s_viewportPlanarSprites[i];
        actual.used = images[i].used;
        assert(!memcmp(&actual, images + i, sizeof(actual)));
    }
    assert_directory();
    /* Unit identity reuse still performs shared-image lookup after eviction. */
    Unit unit = {0}, twin = {0};
    unit.o.index = 20;
    twin.o.index = 21;
    drawUnit = &unit;
    Unit_ClearViewportKey(drawUnit);
    before = keyBuilds;
    for (int phase = 0; phase < 16; phase++)
        check(1, 64 + phase, 60, DRAWSPRITE_FLAG_CENTER | DRAWSPRITE_FLAG_WIDGETPOS, false);
    assert(keyBuilds == before + 1);
    Unit_ClearViewportKey(drawUnit);
    layers.count = 1;
    layers.layer[0].spriteID = 6;
    layers.layer[0].colourHouse = GUI_SPRITE_COLOUR_EMBEDDED;
    layers.layer[0].flags = 0;
    layers.layer[0].offsetX = layers.layer[0].offsetY = 0;
    g_unitSelected = &unit;
    Unit_ClearViewportKey(&unit);
    check_layers(&layers, 64, 50, 0);
    before = keyBuilds;
    for (int phase = 0; phase < 16; phase++) check_layers(&layers, 64 + phase, 50, 0);
    assert(keyBuilds == before);
    /* A second unit shares the same image: its index is not part of the key. */
    drawUnit = &twin;
    g_unitSelected = &twin;
    unsigned oldCompositions = compositions;
    check_layers(&layers, 79, 50, 0);
    assert(compositions == oldCompositions);
    drawUnit = NULL;
    for (unsigned id = 0; id < 70; id++) check(id, 64, 60, 0, false);
    drawUnit = &twin;
    before = keyBuilds;
    oldCompositions = compositions;
    check_layers(&layers, 79, 50, 0);
    assert(keyBuilds == before && compositions == oldCompositions + 1 + layers.count);
    /* Terrain-dependent layers rebuild harvester keys, not cached images. */
    unit.o.type = UNIT_HARVESTER;
    drawUnit = &unit;
    ViewportCompositeKey unusedKey = unit.viewportKey;
    for (unsigned state = 0; state < 4; state++) {
        layers.count = state & 1;
        check_layers(&layers, 64, 50, 0);
        assert(!memcmp(&unit.viewportKey, &unusedKey, sizeof(unusedKey)));
        before = keyBuilds;
        oldCompositions = compositions;
        check_layers(&layers, 64, 50, 0);
        assert(keyBuilds == before + 2 && compositions == oldCompositions);
        assert(!memcmp(&unit.viewportKey, &unusedKey, sizeof(unusedKey)));
    }
    drawUnit = NULL;
    g_unitSelected = NULL;
    for (unsigned i = 0; i < UNIT_INDEX_MAX; i++) pool[i].viewportKey.main = i + 1;
    GUI_FreeViewportSpriteCache();
    for (unsigned i = 0; i < UNIT_INDEX_MAX; i++) assert(!pool[i].viewportKey.main);
    assert(!s_viewportPlanarSprites && !s_viewportPlanar && !s_viewportSpriteReady && !s_viewportPlanarClock);
    assert(!s_viewportPlanarComponents && !s_viewportComponentClock);
    assert(!s_viewportPlanarMasks && !blitterLocks);
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) {
        assert(!s_viewportPlanarKeys[i].key.main && !s_viewportPlanarKeys[i].sprite);
        for (unsigned word = 0; word < 2; word++) assert(!s_viewportPlanarKeys[i].key.tail[word]);
    }
    assert(s_viewportPlanarLastHitPosition == VIEWPORT_PLANAR_SPRITES);
    return 0;
}
"""
        harness = harness.replace("/* FLAGS */", flags).replace("/* LAYER TYPES */", layer_types)
        harness = harness.replace("/* KEY TYPE */", (ROOT / "src/gui/viewport_key.h").read_text())
        key_policy = next(line.strip() for line in (ROOT / "src/gui/viewport.c").read_text().splitlines()
                          if "ViewportCompositeKey *viewportKey =" in line)
        harness = harness.replace("/* KEY POLICY */", key_policy)
        harness = harness.replace("/* CACHE */", blit_plan_type() + cache)
        harness = harness.replace("/* FREE */", function(gui, "GUI_FreeViewportSpriteCache"))
        harness = harness.replace("/* PLANAR SCOPE */", function(gui, "GUI_SetViewportPlanar"))
        harness = harness.replace("/* MERGE */", function(video, "Video_Atari_PlanarMergePlain"))
        house_cache = viewport[viewport.index("#define PALETTE_HOUSE_CACHE_SIZE"):
                               viewport.index("/* ENHANCEMENT -- newlib")]
        house_getter = function(viewport, "GUI_GetSpriteHousePalette")
        house_getter = house_getter.replace("\n{\n", "\n{\n    houseLookups++;\n", 1)
        harness = harness.replace("/* HOUSE PALETTE */", house_cache + "\n" +
                                  function(viewport, "PaletteHouseCache_Copy16") + "\n" + house_getter)
        composer = function(video, "Video_Atari_ComposePlanarSprite")
        composer = composer.replace("\n{\n", "\n{\n    compositions++;\n", 1)
        harness = harness.replace("/* BLITTER */", composer + "\n" +
                                  function(video, "Video_Atari_PlanarCopyGroup") + "\n" +
                                  function(video, "Video_Atari_PublishViewportCursorRect") + "\n" +
                                  function(video, "Video_Atari_PresentPlanarSpriteOverlays") + "\n" +
                                  function(video, "Video_Atari_PublishPlanarSpritePlain") + "\n" +
                                  function(video, "Video_Atari_PresentPlanarSpriteStrided") + "\n" +
                                  function(video, "Video_Atari_PresentPlanarSprite") + "\n" +
                                  blitter_model(video))
        finder = function(gui, "GUI_ViewportFindPlanarSprite")
        finder = finder.replace("\n{\n", "\n{\n    assert_directory();\n", 1)
        finder = finder.replace("if (s_viewportPlanarLastHitPosition < VIEWPORT_PLANAR_SPRITES) {",
                                "if (s_viewportPlanarLastHitPosition < VIEWPORT_PLANAR_SPRITES) {\n"
                                "        lookupCandidates++;")
        finder = finder.replace("*position = s_viewportPlanarLastHitPosition;",
                                "lastHitMatches++;\n"
                                "            *position = s_viewportPlanarLastHitPosition;")
        nodes = re.findall(r"^\s*VIEWPORT_SEARCH_NODE\((\d+),", finder, re.M)
        self.assertEqual(sorted(map(int, nodes)), list(range(64)))
        self.assertNotRegex(finder, r"\b(?:while|for)\s*\(")
        finder = finder.replace("\n{\n", "\n{\n    bool firstBinary = true;\n", 1)
        node_probe = "const ViewportPlanarSpriteKey *candidate = &s_viewportPlanarKeys[slot];"
        self.assertEqual(finder.count(node_probe), 1)
        finder = finder.replace(node_probe, node_probe + " \\\n"
                                "        lookupCandidates++; \\\n"
                                "        if (firstBinary) firstBinaryPosition = (slot); \\\n"
                                "        firstBinary = false;")
        indexer = function(gui, "GUI_ViewportIndexPlanarSprite")
        indexer = indexer[:-2] + "    assert_directory();\n}\n"
        comparator = function(gui, "GUI_ViewportCompareLayerKeys")
        comparator = comparator.replace("\n{\n", "\n{\n    layerComparisons++;\n", 1)
        builder = function(gui, "GUI_ViewportBuildCompositeKey")
        builder = builder.replace("\n{\n", "\n{\n    keyBuilds++;\n", 1)
        lookup = builder + "\n" + function(gui, "GUI_ViewportBuildCompositeKeyBlitter") + "\n"
        lookup += function(gui, "GUI_ViewportBuildCompositeKeyCPU") + "\n"
        lookup += comparator + "\n" + finder + "\n" + indexer
        lookup += "\n" + function(gui, "GUI_ViewportDecodeLayer")
        for name, victim_check in (("GUI_ViewportPlanarComponent", "expected_component_victim"),
                                   ("GUI_ViewportPlanarSprite", "expected_sprite_victim")):
            body = function(gui, name)
            self.assertEqual(body.count("if (victim == NULL"), 1)
            self.assertEqual(body.count("entry = victim;"), 1)
            body = body.replace("if (victim == NULL", "evictionCandidates++;\n\t\t\tif (victim == NULL")
            body = body.replace("entry = victim;",
                                "assert(victim == " + victim_check + "());\n\t\tentry = victim;")
            lookup += "\n" + body
        harness = harness.replace("/* LOOKUP */", lookup)
        with tempfile.TemporaryDirectory(prefix="viewport-sprite-cache-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                            str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
            subprocess.run([str(binary), "blitter"], check=True)
            for invalid in range(15):
                result = subprocess.run([str(binary), "blitter", str(invalid)],
                                        stderr=subprocess.DEVNULL)
                self.assertEqual(result.returncode, 90, invalid)
            release = harness.replace(lookup,
                "#define NDEBUG\n#include <assert.h>\n" + lookup +
                "\n#undef NDEBUG\n#include <assert.h>\n")
            source.write_text(release)
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                            str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
            subprocess.run([str(binary), "blitter"], check=True)

    def test_layered_dispatch_and_mandatory_planar(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        viewport_flags = re.search(r"(?:int|uint16) spriteFlags = 0;", viewport).group()
        header = (ROOT / "src/gui/gui.h").read_text()
        flags = "\n".join(line for line in header.splitlines()
                          if line.startswith(("#define DRAWSPRITE_FLAG_", "#define GUI_SPRITE_")))
        layer_types = header[header.index("typedef struct GUI_SpriteLayer"):header.index("/* colourHouse identifies")]
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>
#include <stddef.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int16_t int16;
typedef uint32_t uint32;
typedef int Screen;
/* KEY TYPE */
typedef struct { uint16 index; ViewportCompositeKey viewportKey; } Unit;
#define SCREEN_0 0
#define VARIABLE_NOT_USED(x) ((void)(x))
/* FLAGS */
/* LAYER TYPES */
static uint8 assets[4], *g_sprites[4], screen[2], bodyPalette[16], remap[256];
static GUI_SpriteLayers layers;
static bool cached;
static unsigned attempts, draws;
static Unit unit;
static bool withUnit, withKeyArg;
static void GUI_Widget_Viewport_InvalidateSpriteDamage(void) {}
static uint8 *GFX_Screen_Get_ByIndex(Screen id) { return screen + id; }
static bool Video_Atari_CursorDirect(void) { return cached; }
#ifdef TOS
static bool GUI_Sidebar_Active(void) { return false; }
static void GUI_Sidebar_Sprite(const uint8 *sprite, uint16 id, int16 x, int16 y,
                                int flags, const uint8 *mapping, uint16 count) {
    (void)sprite; (void)id; (void)x; (void)y;
    (void)flags; (void)mapping; (void)count;
    assert(false);
}
#endif
static void GUI_ViewportPlanarSprite(const uint8 *sprite, uint16 id, uint8 house,
                                    int16 x, int16 y, int flags, va_list *ap,
                                    const GUI_SpriteLayers *composition, ViewportCompositeKey *key) {
    attempts++;
    assert(sprite == g_sprites[0] && id == 0 && house == 1);
    assert(x == 50 && y == 60 && !(flags & DRAWSPRITE_FLAG_LAYERS));
    assert(composition == &layers);
    assert(key == (withUnit ? &unit.viewportKey : NULL));
    assert(!(flags & DRAWSPRITE_FLAG_VIEWPORT_KEY));
    assert(va_arg(*ap, uint8 *) == bodyPalette);
    assert(va_arg(*ap, uint8 *) == remap && va_arg(*ap, int) == 1);
}
static void GUI_DrawSpriteInternal(Screen screenID, const uint8 *sprite, int16 x, int16 y,
                                  uint16 windowID, int flags, va_list *ap,
                                  uint8 *target, uint16 width, uint16 height) {
    unsigned id = draws++;
    assert(id < 4 && sprite == g_sprites[id] && windowID == 2);
    assert(screenID == 0 || screenID == 1);
    assert(!target && !width && !height &&
           !(flags & (DRAWSPRITE_FLAG_LAYERS | DRAWSPRITE_FLAG_VIEWPORT_KEY)));
    if (id == 0) {
        assert(x == 50 && y == 60);
        assert(va_arg(*ap, uint8 *) == bodyPalette);
        assert(va_arg(*ap, uint8 *) == remap && va_arg(*ap, int) == 1);
    } else {
        const GUI_SpriteLayer *layer = &layers.layer[id - 1];
        assert(x == 50 + layer->offsetX && y == 60 + layer->offsetY);
        assert(flags == (layer->flags | DRAWSPRITE_FLAG_CENTER | DRAWSPRITE_FLAG_WIDGETPOS));
        if (flags & DRAWSPRITE_FLAG_PAL) assert(va_arg(*ap, const uint8 *) == layer->palette);
    }
}
/* DRAW */
static void draw_body(Screen screenID, int flags) {
#ifdef TOS
    if (withKeyArg) {
        GUI_DrawSprite(screenID, g_sprites[0], 0, 1, 50, 60, 2,
                       flags | DRAWSPRITE_FLAG_VIEWPORT_KEY, &layers,
                       withUnit ? &unit.viewportKey : (ViewportCompositeKey *)NULL,
                       bodyPalette, remap, 1);
        return;
    }
#endif
    GUI_DrawSprite(screenID, g_sprites[0], 0, 1, 50, 60, 2,
                   flags, &layers, bodyPalette, remap, 1);
}
int main(void) {
    for (unsigned i = 0; i < 4; i++) g_sprites[i] = assets + i;
    layers.count = 3;
    for (unsigned i = 0; i < 3; i++) {
        layers.layer[i].spriteID = i + 1;
        layers.layer[i].colourHouse = GUI_SPRITE_COLOUR_EMBEDDED;
        layers.layer[i].offsetX = (int)i - 2;
        layers.layer[i].offsetY = -14 + i * 3;
        layers.layer[i].flags = i == 1 ? DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_RTL : 0;
    }
    /* VIEWPORT FLAGS */
    spriteFlags |= DRAWSPRITE_FLAG_CENTER | DRAWSPRITE_FLAG_WIDGETPOS |
                   DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_REMAP;
    spriteFlags |= DRAWSPRITE_FLAG_LAYERS;
    assert(spriteFlags & DRAWSPRITE_FLAG_LAYERS);
    int flags = spriteFlags;
    for (unsigned variant = 0; variant < 3; variant++) {
        withUnit = variant == 1;
        withKeyArg = variant != 0;
        draws = attempts = 0;
        cached = true;
        draw_body(0, flags);
#ifdef TOS
        assert(attempts == 1 && draws == 0);
#else
        assert(attempts == 0 && draws == 4);
#endif
        draws = attempts = 0;
        cached = false;
        draw_body(0, flags);
        assert(draws == 4);
        draws = attempts = 0;
        draw_body(1, flags);
        assert(attempts == 0 && draws == 4);
    }
    return 0;
}
"""
        harness = harness.replace("/* FLAGS */", flags).replace("/* LAYER TYPES */", layer_types)
        harness = harness.replace("/* VIEWPORT FLAGS */", viewport_flags)
        harness = harness.replace("/* KEY TYPE */", (ROOT / "src/gui/viewport_key.h").read_text())
        harness = harness.replace("/* DRAW */", function(gui, "GUI_DrawSprite"))
        with tempfile.TemporaryDirectory(prefix="viewport-layer-dispatch-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            for defines in ([], ["-DTOS"]):
                subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                                "-Werror", "-Wno-unused-function", *defines,
                                str(source), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)
