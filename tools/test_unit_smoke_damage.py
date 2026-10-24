"""Exercise smoke-local terrain damage and unchanged animation timing."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


def run_harness(harness, tos=True):
    with tempfile.TemporaryDirectory(prefix="unit-smoke-") as directory:
        source = Path(directory) / "test.c"
        binary = Path(directory) / "test"
        source.write_text(harness)
        compiler = shlex.split(os.environ.get("CC", "cc"))
        flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
        subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                        *(["-DTOS"] if tos else []), *flags,
                        "-I" + str(ROOT), "-iquote", str(ROOT / "src"),
                        "-I" + str(ROOT / "include"), str(source), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


class UnitSmokeDamageTest(unittest.TestCase):
    def test_damage_bounds_and_legacy_path(self):
        unit = (ROOT / "src/unit.c").read_text()
        map_source = (ROOT / "src/map.c").read_text()
        sprites = (ROOT / "src/sprites.c").read_text()
        tile = (ROOT / "src/tile.c").read_text()
        production = "\n".join([
            function(tile, "Tile_AddTileDiff"),
            function(sprites, "Sprite_GetWidth"),
            function(sprites, "Sprite_GetHeight"),
            function(map_source, "Map_Update"),
            function(map_source, "Map_UpdateAround"),
            function(unit, "Unit_UpdateMap"),
            function(unit, "Unit_UpdateSmokeDamage"),
        ])
        harness = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#include "src/unit.h"
#include "src/map.h"
#include "src/tile.h"
#include "src/house.h"
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
#define BitArray_Set(a,n) ((a)[(n) >> 3] |= 1u << ((n) & 7))
#define BitArray_Test(a,n) (((a)[(n) >> 3] >> ((n) & 7)) & 1)
UnitInfo g_table_unitInfo[UNIT_MAX];
Tile g_map[4096];
uint8 g_functions[3][3] = {{0,1,0},{2,3,0},{0,1,0}};
uint8 g_dirtyViewport[512], g_dirtyMinimap[512], g_displayedViewport[512];
uint16 g_dirtyUnitCount, g_dirtyAirUnitCount, g_dirtyViewportCount;
bool g_selectionRectangleNeedRepaint;
HouseType g_playerHouseID;
static uint8 *sprites[183];
static uint8 smoke[3][10];
uint8 **g_sprites = sprites;
const tile32 g_table_tilediff[34][8] = {
    [0] = {{0,0},{1,1},{65535,65535},{1,65535}}
};
static bool direct = true, visible = true;
static unsigned added, removed, occupancy;
static bool Video_Atari_CursorDirect(void) { return direct; }
void Unit_PrepareSpriteChange(Unit *unit, uint16 parts) { (void)unit; (void)parts; }
static bool Map_IsTileVisible(uint16 packed) { assert(packed < 4096); return visible; }
void Unit_HouseUnitCount_Add(Unit *unit, uint8 houseID) {
    assert(unit && houseID == g_playerHouseID); added++;
}
void Unit_HouseUnitCount_Remove(Unit *unit) { assert(unit); removed++; }
bool House_AreAllied(uint8 a, uint8 b) { return a == b; }
uint8 Unit_GetHouseID(Unit *unit) { return unit->o.houseID; }
bool Map_IsPositionUnveiled(uint16 packed) { (void)packed; return true; }
void Tile_RemoveFogInRadius(tile32 position, uint16 radius) { (void)position; (void)radius; }
Object *Object_GetByPackedTile(uint16 packed) { (void)packed; return NULL; }
void Unit_AddToTile(Unit *unit, uint16 packed) { (void)unit; (void)packed; occupancy++; }
void Unit_RemoveFromTile(Unit *unit, uint16 packed) { (void)unit; (void)packed; occupancy++; }
/* PRODUCTION */
static void clear(void) {
    memset(g_dirtyViewport, 0, sizeof(g_dirtyViewport));
    memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
    g_dirtyUnitCount = g_dirtyViewportCount = 0;
    g_selectionRectangleNeedRepaint = false;
}
static void check(Unit *u, unsigned width, unsigned height) {
    clear();
    u->viewportKey.main = 123;
    u->o.flags.s.isDirty = false;
    Unit_UpdateSmokeDamage(u);
    assert(!u->viewportKey.main && u->o.flags.s.isDirty && g_dirtyUnitCount == 1);
    assert(!occupancy);
    int cx = (u->o.position.x >> 4) + (int16)g_table_tilediff[0][u->wobbleIndex].x;
    int cy = (u->o.position.y >> 4) + (int16)g_table_tilediff[0][u->wobbleIndex].y - 14;
    int left = cx - (int)width / 2, top = cy - (int)height / 2;
    int right = left + width, bottom = top + height;
    unsigned count = 0;
    for (unsigned y = 0; y < 64; y++) {
        for (unsigned x = 0; x < 64; x++) {
            bool expected = (int)x * 16 < right && (int)(x + 1) * 16 > left &&
                            (int)y * 16 < bottom && (int)(y + 1) * 16 > top;
            assert(!!BitArray_Test(g_dirtyMinimap, Tile_PackXY(x,y)) == expected);
            assert(!!BitArray_Test(g_dirtyViewport, Tile_PackXY(x,y)) == expected);
            count += expected;
        }
    }
    assert(count <= 9);
}
int main(void) {
    Unit u = {0};
    u.o.flags.s.used = true;
    u.o.flags.s.isSmoking = true;
    u.o.type = UNIT_TANK;
    g_table_unitInfo[UNIT_TANK].movementType = MOVEMENT_TRACKED;
    g_table_unitInfo[UNIT_TANK].dimension = 16;
    for (unsigned i = 0; i < 3; i++) sprites[180 + i] = smoke[i];
    /* Different and odd frame dimensions: union must cover every old frame. */
    smoke[0][3] = 16; smoke[0][2] = 17;
    smoke[1][3] = 19; smoke[1][2] = 16;
    smoke[2][3] = 17; smoke[2][2] = 23;
    for (unsigned wobble = 0; wobble < 4; wobble++) {
        u.wobbleIndex = wobble;
        for (unsigned y = 0; y < 16; y++)
            for (unsigned x = 0; x < 16; x++) {
                u.o.position.x = (320 + x) << 4;
                u.o.position.y = (320 + y) << 4;
                check(&u, 19, 23);
            }
    }
    assert(added == 1024);
    for (unsigned i = 0; i < 3; i++) smoke[i][3] = smoke[i][2] = 32;
    for (unsigned edge = 0; edge < 4; edge++) {
        u.o.position.x = (edge & 1 ? 1023 : 1) << 4;
        u.o.position.y = (edge & 2 ? 1023 : 1) << 4;
        check(&u, 32, 32);
    }
    /* No explicit or implicit neighbour halo is added to smoke damage. */
    u.o.position.x = u.o.position.y = 0x1480;
    u.wobbleIndex = 0;
    clear();
    Unit_UpdateSmokeDamage(&u);
    assert(!memcmp(g_dirtyViewport, g_dirtyMinimap, sizeof(g_dirtyViewport)));
    assert(!BitArray_Test(g_dirtyViewport, Tile_PackXY(20,23)));
    assert(!BitArray_Test(g_dirtyMinimap, Tile_PackXY(20,22)));
    /* Fog/counter side effects survive; no occupancy changes are introduced. */
    u.o.houseID = 1;
    Unit_UpdateSmokeDamage(&u);
    assert(removed == 1 && !occupancy);
    u.o.flags.s.isNotOnMap = true;
    clear();
    Unit_UpdateSmokeDamage(&u);
    assert(!g_dirtyUnitCount && !g_dirtyViewportCount);
    u.o.flags.s.isNotOnMap = false;
    u.o.flags.s.used = false;
    Unit_UpdateSmokeDamage(&u);
    assert(!g_dirtyUnitCount && !g_dirtyViewportCount);
    u.o.flags.s.used = true;
    visible = false;
    clear();
    Unit_UpdateSmokeDamage(&u);
    assert(!g_dirtyViewportCount);
    for (unsigned i = 0; i < sizeof(g_dirtyMinimap); i++)
        assert(!g_dirtyMinimap[i] && !g_dirtyViewport[i]);
    visible = true;
    direct = false;
    clear();
    Unit_UpdateSmokeDamage(&u);
    unsigned count = 0;
    for (unsigned n = 0; n < 4096; n++) count += !!BitArray_Test(g_dirtyMinimap,n);
    assert(count == 25 && g_dirtyUnitCount == 1);
    return 0;
}
"""
        run_harness(harness.replace("/* PRODUCTION */", production))

    def test_animation_cadence(self):
        source = (ROOT / "src/unit.c").read_text()
        loop = function(source, "GameLoop_Unit")
        block = loop[loop.index("if (tickUnknown5)"):loop.index("if (tickScript)")]
        harness = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#include "src/unit.h"
UnitInfo g_table_unitInfo[UNIT_MAX];
static unsigned broadCalls, smokeCalls;
static void Unit_UpdateSmokeDamage(Unit *unit) { (void)unit; smokeCalls++; }
void Unit_UpdateMap(uint16 type, Unit *unit) { assert((type == 2 || type == UNIT_UPDATE_MAP_REPAINT) && unit); broadCalls++; }
#ifdef TOS
void Unit_PrepareSpriteChange(Unit *unit, uint16 parts) { (void)unit; (void)parts; }
#endif
static void advance(Unit *u, bool tickUnknown5) {
    const UnitInfo *ui = &g_table_unitInfo[u->o.type];
    /* BLOCK */
}
static void original(Unit *u, bool tick) {
    const UnitInfo *ui = &g_table_unitInfo[u->o.type];
    if (!tick) return;
    if (u->timer != 0) { u->timer--; return; }
    if ((ui->movementType == MOVEMENT_FOOT && u->speed != 0) || u->o.flags.s.isSmoking) {
        if (u->spriteOffset >= 0) {
            u->spriteOffset &= 0x3f;
            u->spriteOffset++;
            Unit_UpdateMap(2,u);
            u->timer = ui->animationSpeed / 5;
            if (u->o.flags.s.isSmoking) {
                u->timer = 3;
                if (u->spriteOffset > 32) { u->o.flags.s.isSmoking = false; u->spriteOffset = 0; }
            }
        }
    }
    if (u->o.type == UNIT_ORNITHOPTER && u->o.flags.s.allocated && u->spriteOffset >= 0) {
        u->spriteOffset &= 0x3f; u->spriteOffset++;
        Unit_UpdateMap(2,u); u->timer = 1;
    }
    if (u->o.type == UNIT_HARVESTER) {
        if (u->actionID == ACTION_HARVEST || u->o.flags.s.isSmoking) {
            u->spriteOffset &= 0x3f; u->spriteOffset++;
            Unit_UpdateMap(2,u); u->timer = 4;
        } else if (u->spriteOffset != 0) {
            Unit_UpdateMap(2,u); u->spriteOffset = 0;
        }
    }
}
int main(void) {
    unsigned types[] = {UNIT_TANK, UNIT_SOLDIER, UNIT_ORNITHOPTER, UNIT_HARVESTER};
    for (unsigned t = 0; t < 4; t++) {
        g_table_unitInfo[types[t]].movementType = t == 1 ? MOVEMENT_FOOT : MOVEMENT_TRACKED;
        g_table_unitInfo[types[t]].animationSpeed = 10;
        for (unsigned smoking = 0; smoking < 2; smoking++)
        for (unsigned moving = 0; moving < 2; moving++)
        for (unsigned harvest = 0; harvest < 2; harvest++)
        for (int offset = -2; offset < 65; offset++) {
            Unit u = {0};
            u.o.type = types[t]; u.o.flags.s.isSmoking = smoking;
            u.o.flags.s.allocated = true;
            u.speed = moving; u.actionID = harvest ? ACTION_HARVEST : ACTION_GUARD;
            u.spriteOffset = offset;
            Unit reference = u;
            for (unsigned tick = 0; tick < 180; tick++) {
                broadCalls = smokeCalls = 0;
                advance(&u, tick % 3 != 0);
                unsigned actual = broadCalls + smokeCalls;
                if (t == 1 && !smoking) assert(!smokeCalls);
                if (t == 0 && smoking && tick % 3 && reference.timer == 0 &&
                    reference.o.flags.s.isSmoking && reference.spriteOffset >= 0)
                    assert(smokeCalls == 1 && broadCalls == 0);
                broadCalls = smokeCalls = 0;
                original(&reference, tick % 3 != 0);
                assert(broadCalls == actual);
                assert(!memcmp(&u, &reference, sizeof(u)));
            }
        }
    }
    return 0;
}
"""
        for tos in (True, False):
            run_harness(harness.replace("/* BLOCK */", block), tos=tos)
