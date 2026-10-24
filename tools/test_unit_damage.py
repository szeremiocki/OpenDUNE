"""Exercise unit damage and experimental native registration reductions."""

import unittest

from tools.test_unit_smoke_damage import ROOT, run_harness
from tools.test_viewport_sprite_cache import function


class UnitDamageTest(unittest.TestCase):
    def test_damage_modes_and_registration(self):
        unit = (ROOT / "src/unit.c").read_text()
        map_source = (ROOT / "src/map.c").read_text()
        tile = (ROOT / "src/tile.c").read_text()
        production = "\n".join([
            function(tile, "Tile_AddTileDiff"),
            function(map_source, "Map_Update"),
            function(map_source, "Map_UpdateAround").replace(
                "void Map_UpdateAround(", "static void Real_Map_UpdateAround(", 1),
            function(unit, "Unit_UpdateMap"),
        ])
        harness = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#include "src/unit.h"
#include "src/map.h"
#include "src/tile.h"
#include "src/house.h"
#include "src/table/tilediff.c"
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
static bool direct, visible, unveiled;
static unsigned added, removed, fog, occupancyAdd, occupancyRemove;
typedef struct {
    uint16 radius;
    tile32 position;
    uint8 callback;
} Around;
static Around around[3];
static unsigned aroundCount;
bool Video_Atari_CursorDirect(void) { return direct; }
#ifdef TOS
void Unit_PrepareSpriteChange(Unit *unit, uint16 parts) { (void)unit; (void)parts; }
#endif
static bool Map_IsTileVisible(uint16 packed) { assert(packed < 4096); return visible; }
void Unit_HouseUnitCount_Add(Unit *unit, uint8 houseID) {
    assert(unit && houseID == g_playerHouseID); added++;
}
void Unit_HouseUnitCount_Remove(Unit *unit) { assert(unit); removed++; }
bool House_AreAllied(uint8 a, uint8 b) { return a == b; }
uint8 Unit_GetHouseID(Unit *unit) { return unit->o.houseID; }
bool Map_IsPositionUnveiled(uint16 packed) { (void)packed; return unveiled; }
void Tile_RemoveFogInRadius(tile32 position, uint16 radius) {
    (void)position; assert(radius == 1); fog++;
}
Object *Object_GetByPackedTile(uint16 packed) { (void)packed; return NULL; }
void Unit_AddToTile(Unit *unit, uint16 packed) {
    assert(unit && BitArray_Test(g_dirtyViewport,packed)); occupancyAdd++;
}
void Unit_RemoveFromTile(Unit *unit, uint16 packed) {
    assert(unit); occupancyRemove++;
#ifdef TOS
    if (direct) return;
#endif
    Map_Update(packed,0,false);
}
/* PRODUCTION */
void Map_UpdateAround(uint16 radius, tile32 position, Unit *unit, uint8 callback) {
    assert(aroundCount < 3);
    around[aroundCount].radius = radius;
    around[aroundCount].position = position;
    around[aroundCount++].callback = callback;
    Real_Map_UpdateAround(radius, position, unit, callback);
}
static void original(uint16 type, Unit *unit, bool history) {
    if (unit == NULL) return;
    Unit_ClearViewportKey(unit);
    if (unit->o.flags.s.isNotOnMap || !unit->o.flags.s.used) return;
    const UnitInfo *ui = &g_table_unitInfo[unit->o.type];
    if (ui->movementType == MOVEMENT_WINGER) {
        if (type != 0) { unit->o.flags.s.isDirty = true; g_dirtyAirUnitCount++; }
#ifdef TOS
        if (direct && (type == 0 || type == 2)) return;
#endif
        Map_UpdateAround(ui->dimension, unit->o.position, unit, g_functions[0][type]);
        return;
    }
    tile32 position = unit->o.position;
    uint16 packed = Tile_PackTile(position);
    Tile *t = &g_map[packed];
    if (t->isUnveiled || unit->o.houseID == g_playerHouseID)
        Unit_HouseUnitCount_Add(unit, g_playerHouseID);
    else
        Unit_HouseUnitCount_Remove(unit);
    if (type == 1) {
        if (House_AreAllied(Unit_GetHouseID(unit), g_playerHouseID) &&
            !Map_IsPositionUnveiled(packed) && unit->o.type != UNIT_SANDWORM)
            Tile_RemoveFogInRadius(position,1);
        if (Object_GetByPackedTile(packed) == NULL) {
            t->index = unit->o.index + 1; t->hasUnit = true;
        }
    }
    if (type != 0) { unit->o.flags.s.isDirty = true; g_dirtyUnitCount++; }
#ifdef TOS
    if (direct && type == 2) return;
#endif
    uint16 radius = ui->dimension + 3;
    if (unit->o.flags.s.bulletIsBig || unit->o.flags.s.isSmoking ||
        (unit->o.type == UNIT_HARVESTER && unit->actionID == ACTION_HARVEST)) radius = 33;
#ifdef TOS
    if (direct && unit->o.type == UNIT_HARVESTER && !unit->o.flags.s.bulletIsBig) radius = 27;
#endif
    Map_UpdateAround(radius,position,unit,g_functions[1][type]);
    if (unit->o.type == UNIT_HARVESTER && history) {
#ifdef TOS
        if (!direct || unit->o.flags.s.bulletIsBig)
#endif
        Map_UpdateAround(radius,unit->targetPreLast,unit,g_functions[1][type]);
        Map_UpdateAround(radius,unit->targetLast,unit,g_functions[1][type]);
    }
}
typedef struct {
    Unit unit;
    Tile centre;
    uint8 viewport[512], terrain[512];
    uint16 groundCount, airCount, viewportCount;
    unsigned added, removed, fog, occupancyAdd, occupancyRemove, aroundCount;
    Around around[3];
} Snapshot;
static void reset(Unit *u, bool pending) {
    memset(g_map,0,sizeof(g_map));
    memset(g_dirtyViewport,0,sizeof(g_dirtyViewport));
    memset(g_dirtyMinimap,0,sizeof(g_dirtyMinimap));
    memset(around,0,sizeof(around));
    added = removed = fog = occupancyAdd = occupancyRemove = aroundCount = 0;
    g_dirtyUnitCount = g_dirtyAirUnitCount = g_dirtyViewportCount = 0;
    g_map[Tile_PackTile(u->o.position)].isUnveiled = unveiled;
    if (pending) {
        BitArray_Set(g_dirtyViewport,100);
        BitArray_Set(g_dirtyMinimap,100);
        g_dirtyUnitCount = 7; g_dirtyAirUnitCount = 3; g_dirtyViewportCount = 2;
    }
}
static void snapshot(Snapshot *s, Unit *u) {
    memset(s,0,sizeof(*s));
    s->unit = *u; s->centre = g_map[Tile_PackTile(u->o.position)];
    memcpy(s->viewport,g_dirtyViewport,512); memcpy(s->terrain,g_dirtyMinimap,512);
    s->groundCount = g_dirtyUnitCount; s->airCount = g_dirtyAirUnitCount;
    s->viewportCount = g_dirtyViewportCount;
    s->added = added; s->removed = removed; s->fog = fog;
    s->occupancyAdd = occupancyAdd; s->occupancyRemove = occupancyRemove;
    s->aroundCount = aroundCount; memcpy(s->around,around,sizeof(around));
}
static unsigned terrainCount(void) {
    unsigned count = 0;
    for (unsigned i = 0; i < 4096; i++) count += !!BitArray_Test(g_dirtyMinimap,i);
    return count;
}
int main(void) {
    const unsigned types[] = {UNIT_HARVESTER, UNIT_TANK, UNIT_SOLDIER, UNIT_CARRYALL};
    g_table_unitInfo[UNIT_HARVESTER].dimension = 24;
    g_table_unitInfo[UNIT_TANK].dimension = 16;
    g_table_unitInfo[UNIT_SOLDIER].dimension = 16;
    g_table_unitInfo[UNIT_CARRYALL].dimension = 24;
    g_table_unitInfo[UNIT_CARRYALL].movementType = MOVEMENT_WINGER;
    for (unsigned native = 0; native < 2; native++)
    for (unsigned t = 0; t < 4; t++)
    for (unsigned flags = 0; flags < 256; flags++)
    for (unsigned mode = 0; mode <= UNIT_UPDATE_MAP_REMOVE_PREPARED; mode++) {
        direct = native; visible = true; unveiled = !!(flags & 1);
        Unit u = {0};
        u.o.type = types[t]; u.o.index = 25; u.o.houseID = !!(flags & 2);
        u.o.flags.s.used = !(flags & 4); u.o.flags.s.isNotOnMap = !!(flags & 8);
        u.o.flags.s.isSmoking = !!(flags & 16);
        u.o.flags.s.bulletIsBig = !!(flags & 32);
        u.o.flags.s.isDirty = !!(flags & 64);
        u.actionID = flags & 128 ? ACTION_HARVEST : ACTION_GUARD;
        u.o.position = (tile32){0x1480,0x1480};
        u.targetLast = (tile32){0x2080,0x2080};
        u.targetPreLast = (tile32){0x2880,0x2880};
#ifdef TOS
        u.viewportKey.main = 123;
        bool local = direct;
#else
        bool local = false;
#endif
        Unit reference = u;
        bool valid = u.o.flags.s.used && !u.o.flags.s.isNotOnMap;
        reset(&u,true);
        Unit_UpdateMap(mode,&u);
        Snapshot actual, expected;
        snapshot(&actual,&u);
        if (!local || mode <= UNIT_UPDATE_MAP_REDRAW || mode == UNIT_UPDATE_MAP_REMOVE_PREPARED || !valid) {
            reset(&reference,true);
            unsigned oldMode = mode == UNIT_UPDATE_MAP_REMOVE_PREPARED ? 0 :
                               mode >= UNIT_UPDATE_MAP_REPAINT ? 2 : mode;
            bool history = !(local && t == 0 && mode == UNIT_UPDATE_MAP_REDRAW);
            original(oldMode,&reference,history);
            snapshot(&expected,&reference);
            assert(!memcmp(&actual,&expected,sizeof(actual)));
        } else {
            assert(!aroundCount && !occupancyAdd && !occupancyRemove && !fog);
            assert(terrainCount() == 1 && BitArray_Test(g_dirtyMinimap,100));
            assert(BitArray_Test(g_dirtyViewport,100) && g_dirtyViewportCount == 2);
            assert(added + removed == (t == 3 ? 0u : 1u));
            if (t != 3) assert(added == (unsigned)(unveiled || !u.o.houseID));
            assert(u.o.flags.s.isDirty == (mode == UNIT_UPDATE_MAP_REPAINT || !!(flags & 64)));
            assert(g_dirtyUnitCount == 7 + (unsigned)(t != 3 && mode == UNIT_UPDATE_MAP_REPAINT));
            assert(g_dirtyAirUnitCount == 3 + (unsigned)(t == 3 && mode == UNIT_UPDATE_MAP_REPAINT));
#ifdef TOS
            assert(!u.viewportKey.main);
#endif
        }
    }
    /* Native presentation uses the geometry hook, not radius-based repairs. */
    Unit h = {0};
    h.o.type = UNIT_HARVESTER; h.o.flags.s.used = true; h.actionID = ACTION_HARVEST;
    h.o.position = (tile32){0x1480,0x1480};
    h.targetLast = (tile32){0x2080,0x2080}; h.targetPreLast = (tile32){0x2880,0x2880};
    direct = visible = unveiled = true;
    reset(&h,false);
    Unit_UpdateMap(2,&h);
#ifdef TOS
    assert(aroundCount == 0 && terrainCount() == 0);
    assert(!BitArray_Test(g_dirtyViewport,Tile_PackTile(h.targetLast)));
    assert(!BitArray_Test(g_dirtyViewport,Tile_PackTile(h.targetPreLast)));
#else
    assert(aroundCount == 3 && terrainCount() == 75);
#endif
    /* Native harvesters retain targetLast but omit targetPreLast outside forced cleanup. */
    for (unsigned native = 0; native < 2; native++)
    for (unsigned harvest = 0; harvest < 2; harvest++)
    for (unsigned smoking = 0; smoking < 2; smoking++)
    for (unsigned forced = 0; forced < 2; forced++)
    for (unsigned mode = 0; mode < 2; mode++) {
        direct = native;
        h.actionID = harvest ? ACTION_HARVEST : ACTION_GUARD;
        h.o.flags.s.isSmoking = smoking;
        h.o.flags.s.bulletIsBig = forced;
#ifdef TOS
        bool local = direct;
#else
        bool local = false;
#endif
        bool wide = forced || (!local && (harvest || smoking));
        unsigned radius = wide ? 33 : 27;
        unsigned regions = local && !forced ? 2 : 3;
        unsigned visits = regions * (wide ? 25 : 9);
        reset(&h,false);
        Unit_UpdateMap(mode,&h);
        assert(aroundCount == regions);
        for (unsigned i = 0; i < regions; i++) {
            assert(around[i].radius == radius);
            assert(around[i].callback == (mode == 0 ? 2 : 3));
        }
        assert(around[0].position.x == h.o.position.x && around[0].position.y == h.o.position.y);
        if (regions == 3)
            assert(around[1].position.x == h.targetPreLast.x && around[1].position.y == h.targetPreLast.y);
        assert(around[regions-1].position.x == h.targetLast.x &&
               around[regions-1].position.y == h.targetLast.y);
        assert(!!BitArray_Test(g_dirtyViewport,Tile_PackTile(h.targetPreLast)) == (regions == 3));
        assert(BitArray_Test(g_dirtyViewport,Tile_PackTile(h.targetLast)));
        assert(occupancyAdd == (mode == 1 ? visits : 0));
        assert(occupancyRemove == (mode == 0 ? visits : 0));
        if (local) {
            assert(terrainCount() == 0 && g_dirtyViewportCount == visits);
            unsigned candidates = 0;
            for (unsigned i = 0; i < 4096; i++) candidates += !!BitArray_Test(g_dirtyViewport,i);
            assert(candidates == visits);
        }
    }
    /* Zero/edge history positions and invisible terrain retain the selected policy. */
    direct = true; h.o.flags.s.bulletIsBig = false;
    h.actionID = ACTION_HARVEST; h.o.flags.s.isSmoking = true;
    h.targetPreLast = (tile32){0,0}; h.targetLast = (tile32){0xff80,0xff80};
    for (unsigned mode = 0; mode < 2; mode++) {
        Unit reference = h; Snapshot actual, expected;
        visible = false;
        reset(&h,false); Unit_UpdateMap(mode,&h); snapshot(&actual,&h);
        reset(&reference,false); original(mode,&reference,true); snapshot(&expected,&reference);
        assert(!memcmp(&actual,&expected,sizeof(actual)));
    }
    Unit_UpdateMap(UNIT_UPDATE_MAP_STATE,NULL);
    return 0;
}
"""
        for tos in (True, False):
            run_harness(harness.replace("/* PRODUCTION */", production), tos=tos)

    def test_registration_callbacks_do_not_repeat_candidate_updates(self):
        unit = (ROOT / "src/unit.c").read_text()
        map_source = (ROOT / "src/map.c").read_text()
        tile = (ROOT / "src/tile.c").read_text()
        production = "\n".join([
            function(tile, "Tile_AddTileDiff"),
            function(map_source, "Map_Update").replace(
                "void Map_Update(", "static void Real_Map_Update(", 1),
            function(map_source, "Map_UpdateAround"),
            function(unit, "Unit_RemoveFromTile"),
            function(unit, "Unit_AddToTile"),
        ])
        harness = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#include "src/unit.h"
#include "src/map.h"
#include "src/tile.h"
#include "src/table/tilediff.c"
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
#define BitArray_Set(a,n) ((a)[(n) >> 3] |= 1u << ((n) & 7))
#define BitArray_Test(a,n) (((a)[(n) >> 3] >> ((n) & 7)) & 1)
Tile g_map[4096];
uint8 g_dirtyViewport[512], g_dirtyMinimap[512], g_displayedViewport[512];
uint16 g_dirtyViewportCount;
bool g_selectionRectangleNeedRepaint;
static bool direct, visible;
static Unit *occupant;
static unsigned updates[5], marks, unveils;
static uint8 marked[512], revealed[512];
bool Video_Atari_CursorDirect(void) { return direct; }
static bool Map_IsTileVisible(uint16 packed) { assert(packed < 4096); return visible; }
Unit *Unit_Get_ByPackedTile(uint16 packed) { assert(packed < 4096); return occupant; }
uint8 Unit_GetHouseID(Unit *unit) { return unit->o.houseID; }
bool Map_UnveilTile(uint16 packed, uint8 house) {
    assert(packed < 4096 && house == 2 && BitArray_Test(g_dirtyViewport,packed));
    unveils++; BitArray_Set(revealed,packed); return false;
}
void Map_MarkTileDirty(uint16 packed) {
    assert(packed < 4096 && BitArray_Test(g_dirtyViewport,packed));
    marks++; BitArray_Set(marked,packed);
}
/* PRODUCTION */
void Map_Update(uint16 packed, uint16 type, bool ignoreInvisible) {
    assert(type < 5); updates[type]++; Real_Map_Update(packed,type,ignoreInvisible);
}
static void clear(void) {
    memset(g_map,0,sizeof(g_map));
    memset(g_dirtyViewport,0,sizeof(g_dirtyViewport));
    memset(g_dirtyMinimap,0,sizeof(g_dirtyMinimap));
    memset(g_displayedViewport,0,sizeof(g_displayedViewport));
    memset(marked,0,sizeof(marked)); memset(revealed,0,sizeof(revealed));
    memset(updates,0,sizeof(updates));
    marks = unveils = g_dirtyViewportCount = 0;
    g_selectionRectangleNeedRepaint = false;
}
int main(void) {
    const tile32 positions[] = {{0x1480,0x1480},{0x1400,0x1400},{0x80,0x80},
                                {0x3f80,0x3f80},{0,0},{0xff80,0xff80}};
    const uint16 radii[] = {0,19,27,33};
    for (unsigned native = 0; native < 2; native++)
    for (unsigned shown = 0; shown < 2; shown++)
    for (unsigned pos = 0; pos < sizeof(positions) / sizeof(*positions); pos++)
    for (unsigned radius = 0; radius < sizeof(radii) / sizeof(*radii); radius++) {
        direct = native; visible = shown;
#ifdef TOS
        bool local = direct;
#else
        bool local = false;
#endif
        clear();
        Map_UpdateAround(radii[radius],positions[pos],NULL,1);
        uint8 footprint[512]; memcpy(footprint,g_dirtyViewport,sizeof(footprint));
        unsigned visits = g_dirtyViewportCount, cells = 0;
        for (unsigned i = 0; i < 4096; i++) cells += !!BitArray_Test(footprint,i);
        assert(cells <= visits && !marks && !unveils);
        for (unsigned i = 0; i < 5; i++) assert(!updates[i]);
        assert(!g_selectionRectangleNeedRepaint);
        for (unsigned callback = 0; callback < 4; callback++)
        for (unsigned owned = 0; owned < 2; owned++)
        for (unsigned destination = 0; destination < 2; destination++)
        for (unsigned forced = 0; forced < 2; forced++) {
            clear();
            Unit u = {0}, other = {0};
            u.o.houseID = 2; u.o.flags.s.bulletIsBig = forced;
            u.currentDestination = destination ? positions[pos] : (tile32){0x2180,0x2180};
            occupant = owned ? &u : &other;
            unsigned packed = Tile_PackTile(positions[pos]);
            g_map[packed].hasUnit = true; g_map[packed].index = 17;
            memcpy(g_displayedViewport,footprint,sizeof(footprint));
            Map_UpdateAround(radii[radius],positions[pos],&u,callback);
            bool terrain = callback == 0 || (callback == 2 && !local);
            assert(updates[0] == (terrain ? visits : 0));
            for (unsigned i = 1; i < 5; i++) assert(!updates[i]);
            assert(marks == (callback >= 2 ? visits : 0));
            assert(unveils == (callback == 3 ? visits : 0));
            if (callback >= 2) assert(!memcmp(marked,footprint,sizeof(footprint)));
            if (callback == 3) assert(!memcmp(revealed,footprint,sizeof(footprint)));
            bool removed = callback == 2 && owned && BitArray_Test(footprint,packed) &&
                           (!destination || forced);
            assert(g_map[packed].hasUnit == !removed);
            assert(g_map[packed].index == (removed ? 0 : 17));
            if (terrain && visible) {
                assert(!memcmp(g_dirtyMinimap,footprint,sizeof(footprint)));
                assert(g_dirtyViewportCount == visits + cells);
                assert(g_selectionRectangleNeedRepaint == (visits != 0));
            } else {
                assert(!memcmp(g_dirtyViewport,footprint,sizeof(footprint)));
                assert(g_dirtyViewportCount == visits && !g_selectionRectangleNeedRepaint);
                for (unsigned i = 0; i < 512; i++) assert(!g_dirtyMinimap[i]);
            }
        }
    }
    return 0;
}
"""
        for tos in (True, False):
            run_harness(harness.replace("/* PRODUCTION */", production), tos=tos)

    def test_rotation_buckets_and_state(self):
        source = (ROOT / "src/unit.c").read_text()
        tile = (ROOT / "src/tile.c").read_text()
        production = "\n".join([
            function(tile, "Orientation_Orientation256ToOrientation8"),
            function(tile, "Orientation_Orientation256ToOrientation16"),
            function(source, "Unit_Rotate"),
        ])
        harness = r"""
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "types.h"
#include "src/unit.h"
UnitInfo g_table_unitInfo[UNIT_MAX];
static bool direct;
static unsigned calls;
bool Video_Atari_CursorDirect(void) { return direct; }
void Unit_UpdateMap(uint16 type, Unit *unit) { assert((type == 2 || type == UNIT_UPDATE_MAP_REPAINT) && unit); calls++; }
#ifdef TOS
void Unit_PrepareSpriteChange(Unit *unit, uint16 parts) { (void)unit; (void)parts; }
#endif
/* PRODUCTION */
static void original(Unit *unit, uint16 level) {
    if (unit->orientation[level].speed == 0) return;
    int8 current = unit->orientation[level].current;
    int8 target = unit->orientation[level].target;
    int16 diff = target - current;
    if (diff > 128) diff -= 256;
    if (diff < -128) diff += 256;
    diff = abs(diff);
    int8 next = current + unit->orientation[level].speed;
    if (abs(unit->orientation[level].speed) >= diff) {
        unit->orientation[level].speed = 0; next = target;
    }
    unit->orientation[level].current = next;
    if (Orientation_Orientation256ToOrientation8(next) != Orientation_Orientation256ToOrientation8(current) ||
        Orientation_Orientation256ToOrientation16(next) != Orientation_Orientation256ToOrientation16(current)) calls++;
}
int main(void) {
    for (unsigned native = 0; native < 2; native++)
    for (unsigned air = 0; air < 2; air++)
    for (unsigned level = 0; level < 2; level++)
    for (unsigned angle = 0; angle < 256; angle++)
    for (int speed = -16; speed <= 16; speed++)
    for (unsigned target = 0; target < 256; target += 31) {
        Unit u = {0};
        direct = native; u.o.type = UNIT_TANK;
        g_table_unitInfo[UNIT_TANK].movementType = air ? MOVEMENT_WINGER : MOVEMENT_TRACKED;
        u.orientation[level].current = angle;
        u.orientation[level].target = target;
        u.orientation[level].speed = speed;
        Unit reference = u;
        calls = 0; original(&reference,level); unsigned oldCalls = calls;
        calls = 0; Unit_Rotate(&u,level);
        assert(!memcmp(&u,&reference,sizeof(u)));
#ifdef TOS
        if (direct && !air) {
            assert(calls == (unsigned)(Orientation_Orientation256ToOrientation8(angle) !=
                Orientation_Orientation256ToOrientation8(u.orientation[level].current)));
        } else
#endif
        assert(calls == oldCalls);
    }
    return 0;
}
"""
        for tos in (True, False):
            run_harness(harness.replace("/* PRODUCTION */", production), tos=tos)

    def test_script_state_equivalence(self):
        source = (ROOT / "src/script/unit.c").read_text()
        names = ("Script_Unit_Stop", "Script_Unit_MoveToTarget", "Script_Unit_Harvest")
        production = "\n".join(function(source, name) for name in names)
        original = production.replace("UNIT_UPDATE_MAP_STATE", "2").replace("UNIT_UPDATE_MAP_REPAINT", "2")
        for name in names:
            original = original.replace(name + "(", "Original_" + name + "(")
        harness = r"""
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "types.h"
#include "src/unit.h"
#include "src/tile.h"
#include "src/map.h"
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
#define clamp(v,a,b) min(max(v,a),b)
Unit *g_scriptCurrentUnit;
static unsigned calls, mode, rngCalls, spiceCalls;
static uint8 randomValues[2];
static uint16 landscape, distance;
static tile32 destination;
void Unit_UpdateMap(uint16 type, Unit *u) { assert(u); calls++; mode = type; }
void Unit_PrepareSpriteChange(Unit *unit, uint16 parts) { (void)unit; (void)parts; }
void Unit_SetSpeed(Unit *u, uint16 speed) { u->speed = speed & 255; }
void Unit_SetOrientation(Unit *u, int8 orientation, bool instantly, uint16 level) {
    assert(!instantly); u->orientation[level].target = orientation;
}
tile32 Tools_Index_GetTile(uint16 target) { assert(target); return destination; }
uint16 Tile_GetDistance(tile32 a, tile32 b) { (void)a; (void)b; return distance; }
int8 Tile_GetDirection(tile32 a, tile32 b) { (void)a; (void)b; return 64; }
uint16 Map_GetLandscapeType(uint16 packed) { (void)packed; return landscape; }
uint8 Tools_Random_256(void) { assert(rngCalls < 2); return randomValues[rngCalls++]; }
void Map_ChangeSpiceAmount(uint16 packed, int16 amount) {
    assert(packed == Tile_PackTile(g_scriptCurrentUnit->o.position) && amount == -1);
    spiceCalls++;
}
/* PRODUCTION */
/* ORIGINAL */
static void reset(void) { calls = mode = rngCalls = spiceCalls = 0; }
int main(void) {
    uint16 code[8] = {0};
    for (unsigned which = 0; which < 3; which++)
    for (unsigned type = 0; type < 2; type++)
    for (unsigned amount = 0; amount < 103; amount++)
    for (unsigned near = 0; near < 4; near++)
    for (unsigned spice = 0; spice < 3; spice++)
    for (unsigned random = 0; random < 4; random++) {
        Unit u = {0};
        u.o.type = type ? UNIT_HARVESTER : UNIT_CARRYALL;
        u.o.position = (tile32){0x1480,0x1480}; u.targetMove = 123;
        u.amount = amount; u.speed = 19;
        u.orientation[0].current = -100;
        destination = (tile32){0x1400,0x1580};
        distance = near == 0 ? 16 : near == 1 ? 80 : near == 2 ? 128 : 4096;
        landscape = spice == 0 ? LST_NORMAL_SAND : spice == 1 ? LST_SPICE : LST_THICK_SPICE;
        randomValues[0] = random & 1; randomValues[1] = random & 2 ? 0 : 1;
        Unit reference = u;
        ScriptEngine script = {0}; script.script = &code[4]; script.delay = 17;
        ScriptEngine oldScript = script;
        uint16 result, oldResult;
        reset(); g_scriptCurrentUnit = &u;
        if (which == 0) result = Script_Unit_Stop(&script);
        else if (which == 1) result = Script_Unit_MoveToTarget(&script);
        else result = Script_Unit_Harvest(&script);
        unsigned newCalls = calls, newMode = mode, newRng = rngCalls, newSpice = spiceCalls;
        reset(); g_scriptCurrentUnit = &reference;
        if (which == 0) oldResult = Original_Script_Unit_Stop(&oldScript);
        else if (which == 1) oldResult = Original_Script_Unit_MoveToTarget(&oldScript);
        else oldResult = Original_Script_Unit_Harvest(&oldScript);
        assert(result == oldResult && !memcmp(&u,&reference,sizeof(u)));
        assert(!memcmp(&script,&oldScript,sizeof(script)));
        assert(newCalls == calls && newRng == rngCalls && newSpice == spiceCalls);
        if (calls) {
            assert(mode == 2);
            assert(newMode == (unsigned)(which == 1 && distance < 128 ? UNIT_UPDATE_MAP_REPAINT : UNIT_UPDATE_MAP_STATE));
        }
    }
    return 0;
}
"""
        run_harness(harness.replace("/* PRODUCTION */", production).replace("/* ORIGINAL */", original))

    def test_recolour_state_and_harvest_layer_removal(self):
        source = (ROOT / "src/unit.c").read_text()
        production = "\n".join(function(source, name) for name in
                               ("Unit_Deviate", "Unit_Deviation_Decrease"))
        original = production.replace(
            "unit->o.type == UNIT_HARVESTER && unit->actionID == ACTION_HARVEST ?\n"
            "\t               UNIT_UPDATE_MAP_REDRAW : UNIT_UPDATE_MAP_REPAINT", "2")
        for name in ("Unit_Deviate", "Unit_Deviation_Decrease"):
            original = original.replace(name + "(", "Original_" + name + "(")
        loop = function(source, "GameLoop_Unit")
        blink = loop[loop.index("if (tickBlinking"):loop.index("if (tickDeviation)")]
        harness = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#include "src/unit.h"
#include "src/house.h"
UnitInfo g_table_unitInfo[UNIT_MAX];
const HouseInfo g_table_houseInfo[HOUSE_MAX] = {{.toughness = 64}, {.toughness = 80}};
HouseType g_playerHouseID;
static unsigned calls, mode, untargetCalls, actionCalls, rngCalls;
static uint8 randomValue;
void Unit_UpdateMap(uint16 type, Unit *u) { assert(u); calls++; mode = type; }
void Unit_SetAction(Unit *u, ActionType action) { actionCalls++; u->actionID = action; }
void Unit_UntargetMe(Unit *u) { assert(u); untargetCalls++; }
uint8 Tools_Random_256(void) { rngCalls++; return randomValue; }
/* PRODUCTION */
/* ORIGINAL */
static void blink(Unit *u, bool tickBlinking) { /* BLINK */ }
static void reset(void) { calls = mode = untargetCalls = actionCalls = rngCalls = 0; }
int main(void) {
    const unsigned types[] = {UNIT_TANK, UNIT_HARVESTER, UNIT_CARRYALL};
    for (unsigned t = 0; t < 3; t++)
    for (unsigned flags = 0; flags < 16; flags++)
    for (unsigned expired = 0; expired < 4; expired++)
    for (unsigned amount = 0; amount < 3; amount++)
    for (unsigned random = 0; random < 2; random++)
    for (unsigned decreasing = 0; decreasing < 2; decreasing++) {
        Unit u = {0}; u.o.type = types[t]; u.o.houseID = flags & 1;
        u.actionID = flags & 2 ? ACTION_HARVEST : ACTION_GUARD;
        u.deviated = expired == 0 ? 0 : expired == 1 ? 1 : expired == 2 ? 65 : 120;
        u.deviatedHouse = HOUSE_ORDOS; u.targetAttack = 50; u.targetMove = 60;
        Unit reference = u;
        g_playerHouseID = flags & 4 ? HOUSE_ORDOS : HOUSE_HARKONNEN;
        g_table_unitInfo[types[t]].flags.isNormalUnit = !(flags & 8);
        g_table_unitInfo[types[t]].flags.isNotDeviatable = !!(flags & 8);
        g_table_unitInfo[types[t]].actionAI = ACTION_GUARD;
        g_table_unitInfo[types[t]].o.actionsPlayer[3] = ACTION_STOP;
        uint16 value = amount == 0 ? 0 : amount == 1 ? 1 : 120;
        randomValue = random ? 255 : 0;
        reset();
        bool result = decreasing ? Unit_Deviation_Decrease(&u,value) :
                                   Unit_Deviate(&u,value,HOUSE_ORDOS);
        unsigned newCalls = calls, newMode = mode, newActions = actionCalls;
        unsigned newUntarget = untargetCalls, newRng = rngCalls;
        reset();
        bool oldResult = decreasing ? Original_Unit_Deviation_Decrease(&reference,value) :
                                      Original_Unit_Deviate(&reference,value,HOUSE_ORDOS);
        assert(result == oldResult && !memcmp(&u,&reference,sizeof(u)));
        assert(newCalls == calls && newActions == actionCalls && newUntarget == untargetCalls);
        assert(newRng == rngCalls);
        if (calls) {
            assert(mode == 2);
            bool removesHarvest = types[t] == UNIT_HARVESTER && (flags & 2);
            assert(newMode == (unsigned)(removesHarvest ? UNIT_UPDATE_MAP_REDRAW : UNIT_UPDATE_MAP_REPAINT));
        }
    }
    for (unsigned counter = 0; counter < 10; counter++)
    for (unsigned tick = 0; tick < 2; tick++) {
        Unit u = {0}; u.blinkCounter = counter;
        reset(); blink(&u,tick);
        assert(calls == (unsigned)(tick && counter));
        assert(u.blinkCounter == counter - (tick && counter));
        if (calls) {
            assert(mode == UNIT_UPDATE_MAP_REPAINT);
            assert(u.o.flags.s.isHighlighted == (u.blinkCounter % 2 != 0));
        }
    }
    return 0;
}
"""
        run_harness(harness.replace("/* PRODUCTION */", production)
                    .replace("/* ORIGINAL */", original).replace("/* BLINK */", blink))
