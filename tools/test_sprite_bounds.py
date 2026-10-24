"""Check renderer-derived old-image damage without previous-draw records."""

import unittest

from tools.test_unit_smoke_damage import ROOT, run_harness
from tools.test_viewport_sprite_cache import function


COMMON = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#include "src/unit.h"
#include "src/map.h"
#include "src/tile.h"
#include "src/house.h"
#include "src/gui/gui.h"
#include "src/explosion.h"
#include "src/table/tilediff.c"
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
#define BitArray_Set(a,n) ((a)[(n) >> 3] |= 1u << ((n) & 7))
#define BitArray_Test(a,n) (((a)[(n) >> 3] >> ((n) & 7)) & 1)
UnitInfo g_table_unitInfo[UNIT_MAX];
Tile g_map[4096];
uint16 g_mapTileID[4096];
uint8 g_dirtyViewport[512], g_dirtyMinimap[512], g_displayedViewport[512];
uint16 g_dirtyViewportCount, g_dirtyUnitCount, g_dirtyAirUnitCount;
bool g_selectionRectangleNeedRepaint;
HouseType g_playerHouseID;
Unit *g_unitSelected;
static uint8 images[355][10], *sprites[355];
uint8 **g_sprites = sprites;
static bool direct = true, visible = true;
bool Video_Atari_CursorDirect(void) { return direct; }
static bool Map_IsTileVisible(uint16 packed) { assert(packed < 4096); return visible; }
static void clearDamage(void) {
    memset(g_dirtyViewport,0,512); memset(g_dirtyMinimap,0,512);
    g_dirtyViewportCount = 0;
}
static void initSprites(void) {
    for (unsigned i = 0; i < 355; i++) {
        sprites[i] = images[i]; images[i][2] = images[i][3] = 16;
    }
}
static void expectedSprite(uint8 *expected, uint16 id, tile32 position, int dx, int dy) {
    if (!id || (!position.x && !position.y)) return;
    int width = images[id][3], height = images[id][2];
    int left = (position.x >> 4) + dx - width / 2;
    int top = (position.y >> 4) + dy - height / 2;
    for (unsigned y = 0; y < 64; y++)
    for (unsigned x = 0; x < 64; x++)
        if ((int)x * 16 < left + width && (int)(x + 1) * 16 > left &&
            (int)y * 16 < top + height && (int)(y + 1) * 16 > top)
            BitArray_Set(expected,Tile_PackXY(x,y));
}
"""


def map_production():
    source = (ROOT / "src/map.c").read_text()
    sprites = (ROOT / "src/sprites.c").read_text()
    return "\n".join(function(text, name) for text, name in [
        (sprites, "Sprite_GetWidth"), (sprites, "Sprite_GetHeight"),
        (source, "Map_Update"), (source, "Map_UpdateSprite"),
    ])


class SpriteBoundsTest(unittest.TestCase):
    def test_shared_unit_layout_and_exact_repair_tiles(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        unit = (ROOT / "src/unit.c").read_text()
        tile = (ROOT / "src/tile.c").read_text()
        loop = function(unit, "GameLoop_Unit")
        animation = loop[loop.index("if (tickUnknown5)"):loop.index("if (tickScript)")]
        production = map_production() + "\n" + "\n".join([
            function(tile, "Orientation_Orientation256ToOrientation8"),
            function(tile, "Orientation_Orientation256ToOrientation16"),
            function(viewport, "GUI_Widget_Viewport_GroundSprites"),
            function(viewport, "GUI_Widget_Viewport_AirSprite"),
            function(viewport, "GUI_Widget_Viewport_DamageUnit"),
            function(unit, "Unit_PrepareSpriteChange"),
            function(unit, "Unit_Rotate"),
            function(unit, "Unit_SetOrientation"),
            function((ROOT / "src/script/unit.c").read_text(), "Script_Unit_SetSprite"),
        ])
        production += "\nstatic void advanceAnimation(Unit *u) {\n" + \
            "const UnitInfo *ui = &g_table_unitInfo[u->o.type]; bool tickUnknown5 = true;\n" + \
            animation + "\n}"
        harness = COMMON + r"""
#include <stdlib.h>
static uint16 landscape = LST_SPICE;
static unsigned paints, states, observedAngle;
Unit *g_scriptCurrentUnit;
uint16 Script_Stack_Peek(ScriptEngine *script, int position) {
    (void)script; (void)position; assert(false); return 0;
}
uint16 Map_GetLandscapeType(uint16 packed) { (void)packed; return landscape; }
static void GUI_Widget_Viewport_AddSpriteLayer(GUI_SpriteLayers *layers, uint16 spriteID,
                                               uint8 house, int16 x, int16 y, int flags) {
    assert(layers->count < 3);
    GUI_SpriteLayer *layer = &layers->layer[layers->count++];
    memset(layer,0,sizeof(*layer));
    layer->spriteID = spriteID; layer->offsetX = x; layer->offsetY = y;
    layer->colourHouse = house; layer->flags = flags;
}
uint8 Unit_GetHouseID(Unit *unit) { return unit->o.houseID; }
static void Unit_UpdateSmokeDamage(Unit *unit) { (void)unit; assert(false); }
void Unit_UpdateMap(uint16 mode, Unit *unit) {
    if (mode == UNIT_UPDATE_MAP_STATE) { states++; return; }
    assert(mode == UNIT_UPDATE_MAP_REPAINT); paints++;
    observedAngle = (uint8)unit->orientation[0].current;
}
/* PRODUCTION */
static void check(Unit *u, uint16 parts, uint16 id, int dx, int dy) {
    uint8 expected[512] = {0};
    if (parts == UNIT_SPRITE_BODY) {
        int flags;
        GUI_SpriteLayers layers;
        uint16 actual = g_table_unitInfo[u->o.type].movementType == MOVEMENT_WINGER ?
            GUI_Widget_Viewport_AirSprite(u,&flags) :
            GUI_Widget_Viewport_GroundSprites(u,&flags,&layers,parts);
        assert(actual == id);
    }
    expectedSprite(expected,id,u->o.position,dx,dy);
    clearDamage(); Unit_PrepareSpriteChange(u,parts);
    assert(!memcmp(expected,g_dirtyMinimap,512));
    /* Existing Map_Update(0) halo remains, separately from terrain repair. */
    for (unsigned i = 0; i < 4096; i++) if (BitArray_Test(expected,i)) {
        static const int offsets[9] = {-65,-64,-63,-1,0,1,63,64,65};
        for (unsigned n = 0; n < 9; n++)
            assert(BitArray_Test(g_dirtyViewport,(i + offsets[n]) & 4095));
    }
}
int main(void) {
    initSprites();
    Unit u = {0}; u.o.flags.s.used = true; u.o.type = UNIT_HARVESTER;
    u.o.position = (tile32){0x1480,0x1480};
    u.actionID = ACTION_HARVEST; u.o.flags.s.isSmoking = true; g_unitSelected = &u;
    UnitInfo *ui = &g_table_unitInfo[UNIT_HARVESTER];
    ui->groundSpriteID = 100; ui->turretSpriteID = 0xffff; ui->displayMode = DISPLAYMODE_UNIT;
    static const int direction[] = {0,1,2,3,4,3,2,1};
    static const int hx[] = {0,-7,-14,-9,0,9,14,7}, hy[] = {7,6,1,-6,-9,-6,1,6};
    static const unsigned phases[] = {0,1,8,15};
    for (unsigned angle = 0; angle < 8; angle++)
    for (unsigned frame = 0; frame < 3; frame++)
    for (unsigned wobble = 0; wobble < 8; wobble++)
    for (unsigned x = 0; x < 4; x++)
    for (unsigned y = 0; y < 4; y++) {
        u.orientation[0].current = angle * 32; u.spriteOffset = frame; u.wobbleIndex = wobble;
        u.o.position.x = (320 + phases[x]) << 4; u.o.position.y = (320 + phases[y]) << 4;
        int wx = (int16)g_table_tilediff[0][wobble].x, wy = (int16)g_table_tilediff[0][wobble].y;
        uint16 harvest = 223 + direction[angle] * 3 + frame;
        images[harvest][3] = 17 + frame * 3; images[harvest][2] = 19 - frame;
        check(&u,UNIT_SPRITE_HARVEST,harvest,wx + hx[angle],wy + hy[angle]);
        check(&u,UNIT_SPRITE_SELECTION,6,wx,wy);
        GUI_SpriteLayers layers; int flags;
        unsigned body = GUI_Widget_Viewport_GroundSprites(&u,&flags,&layers,UNIT_SPRITE_ALL);
        assert(body == 100u + (unsigned)direction[angle] && layers.count == 3);
        assert(layers.layer[0].spriteID == harvest);
        assert(layers.layer[1].spriteID == 180 + frame && layers.layer[2].spriteID == 6);
    }
    /* Old turret offsets, not body or unchanged smoke/selection bounds. */
    u.o.type = UNIT_TANK; u.o.position = (tile32){0x1480,0x1480}; u.wobbleIndex = 0;
    ui = &g_table_unitInfo[UNIT_TANK];
    ui->groundSpriteID = 100; ui->displayMode = DISPLAYMODE_UNIT;
    ui->turretSpriteID = 0x7e; ui->o.flags.hasTurret = true;
    u.spriteOffset = 0; u.orientation[0].current = u.orientation[1].current = 0;
    check(&u,UNIT_SPRITE_TURRET,126,0,-5);
    check(&u,UNIT_SPRITE_BODY,100,0,0);
    assert(BitArray_Test(g_dirtyMinimap,Tile_PackXY(20,20)));
    assert(!BitArray_Test(g_dirtyMinimap,Tile_PackXY(20,19)));
    /* Rotation repairs old angle before assigning the new current angle. */
    u.orientation[0].target = 32; u.orientation[0].speed = 32;
    clearDamage(); paints = 0; Unit_Rotate(&u,0);
    assert(paints == 1 && observedAngle == 32);
    assert(BitArray_Test(g_dirtyMinimap,Tile_PackXY(20,20)));
    assert(!BitArray_Test(g_dirtyMinimap,Tile_PackXY(20,19)));
    clearDamage(); paints = 0;
    Unit_SetOrientation(&u,64,true,0);
    assert(paints == 1 && observedAngle == 32 && u.orientation[0].current == 64);
    assert(BitArray_Test(g_dirtyMinimap,Tile_PackXY(20,20)));
    clearDamage(); Unit_SetOrientation(&u,65,true,0);
    assert(paints == 1 && !g_dirtyViewportCount);
    /* Infantry frames and death sprites share the draw selector. */
    u.o.type = UNIT_SOLDIER; ui = &g_table_unitInfo[UNIT_SOLDIER];
    ui->groundSpriteID = 50; ui->turretSpriteID = 0xffff;
    ui->displayMode = DISPLAYMODE_INFANTRY_3_FRAMES; ui->destroyedSpriteID = 90;
    static const unsigned frames[] = {0,1,0,2};
    static const unsigned infantry[] = {0,1,1,1,2,1,1,1};
    for (unsigned a = 0; a < 8; a++) for (int f = -3; f < 8; f++) {
        u.orientation[0].current = a * 32; u.spriteOffset = f;
        unsigned id = f < 0 ? (unsigned)(90 - f - 1) : 50 + infantry[a] * 3 + frames[f & 3];
        check(&u,UNIT_SPRITE_BODY,id,0,0);
    }
    /* Frame advancement repairs the old, larger frame before shrinking it. */
    u.orientation[0].current = 0; u.spriteOffset = 1; u.speed = 1;
    u.o.flags.s.isSmoking = false; ui->movementType = MOVEMENT_FOOT;
    images[51][3] = 31; images[51][2] = 31;
    uint8 expected[512] = {0};
    expectedSprite(expected,51,u.o.position,0,0);
    clearDamage(); advanceAnimation(&u);
    assert(u.spriteOffset == 2 && !memcmp(expected,g_dirtyMinimap,512));
    /* Explicit death-frame changes cover old pixels; identical requests do not. */
    u.spriteOffset = -2; images[91][3] = images[91][2] = 31;
    memset(expected,0,512); expectedSprite(expected,91,u.o.position,0,0);
    expectedSprite(expected,6,u.o.position,0,0);
    g_scriptCurrentUnit = &u;
    ScriptEngine script = {0}; script.stack[0] = 3;
    clearDamage(); assert(!Script_Unit_SetSprite(&script));
    assert(u.spriteOffset == -3 && !memcmp(expected,g_dirtyMinimap,512));
    clearDamage(); states = 0; assert(!Script_Unit_SetSprite(&script));
    assert(states == 1 && !g_dirtyViewportCount);
    u.o.type = UNIT_HARVESTER; u.actionID = ACTION_HARVEST;
    u.speed = 0; u.timer = 0; u.spriteOffset = 2;
    images[225][3] = 31; images[225][2] = 29;
    memset(expected,0,512); expectedSprite(expected,225,u.o.position,0,7);
    clearDamage(); advanceAnimation(&u);
    assert(u.spriteOffset == 3 && !memcmp(expected,g_dirtyMinimap,512));
    /* Loaded carryalls and 16-direction air rockets use the same selectors. */
    u.o.type = UNIT_CARRYALL; ui = &g_table_unitInfo[UNIT_CARRYALL];
    ui->movementType = MOVEMENT_WINGER; ui->groundSpriteID = 50; ui->displayMode = DISPLAYMODE_UNIT;
    static const unsigned air[] = {0,1,2,1,0,1,2,1};
    for (unsigned a = 0; a < 8; a++) for (unsigned load = 0; load < 2; load++) {
        u.orientation[0].current = a * 32; u.o.flags.s.inTransport = load;
        check(&u,UNIT_SPRITE_BODY,50 + air[a] + load * 3,0,0);
    }
    ui->displayMode = DISPLAYMODE_ROCKET;
    static const unsigned rocket[] = {0,1,2,3,4,3,2,1,0,3,2,3,4,3,2,1};
    u.o.flags.s.inTransport = false;
    for (unsigned a = 0; a < 16; a++) {
        u.orientation[0].current = a * 16;
        check(&u,UNIT_SPRITE_BODY,50 + rocket[a],0,0);
    }
    /* Odd dimensions, clipping and no-op positions/backends. */
    images[50][3] = 31; images[50][2] = 23;
    u.orientation[0].current = 0;
    for (unsigned edge = 0; edge < 4; edge++) {
        u.o.position = (tile32){edge & 1 ? 0x3fff : 1, edge & 2 ? 0x3fff : 1};
        check(&u,UNIT_SPRITE_BODY,50,0,0);
    }
    u.o.position = (tile32){0,0}; clearDamage();
    Unit_PrepareSpriteChange(&u,UNIT_SPRITE_ALL); assert(!g_dirtyViewportCount);
    paints = 0; Unit_SetOrientation(&u,32,true,0);
    assert(!paints && !g_dirtyViewportCount);
    u.o.position = (tile32){0x1480,0x1480}; direct = false;
    Unit_PrepareSpriteChange(&u,UNIT_SPRITE_ALL); assert(!g_dirtyViewportCount);
    direct = true; u.o.flags.s.isNotOnMap = true;
    Unit_PrepareSpriteChange(&u,UNIT_SPRITE_ALL); assert(!g_dirtyViewportCount);
    return 0;
}
"""
        run_harness(harness.replace("/* PRODUCTION */", production))

    def test_registration_removal_keeps_occupancy_and_minimap_rules(self):
        unit = (ROOT / "src/unit.c").read_text()
        production = map_production() + "\n" + function(unit, "Unit_RemoveFromTile")
        harness = COMMON + r"""
static unsigned marks;
static Unit *occupant;
Unit *Unit_Get_ByPackedTile(uint16 packed) {
    assert(packed < 4096); return occupant;
}
void Map_MarkTileDirty(uint16 packed) { assert(packed < 4096); marks++; }
/* PRODUCTION */
int main(void) {
    initSprites(); (void)expectedSprite;
    unsigned packed = Tile_PackXY(20,20);
    Unit u = {0}, other = {0};
    for (unsigned native = 0; native < 2; native++)
    for (unsigned destination = 0; destination < 2; destination++)
    for (unsigned forced = 0; forced < 2; forced++)
    for (unsigned owned = 0; owned < 2; owned++) {
        direct = native; clearDamage(); marks = 0;
        u.currentDestination = (tile32){destination ? 0x1480 : 0x1580,0x1480};
        u.o.flags.s.bulletIsBig = forced;
        occupant = owned ? &u : &other;
        g_map[packed].hasUnit = true; g_map[packed].index = 17;
        Unit_RemoveFromTile(&u,packed);
        bool removed = owned && (!destination || forced);
        assert(g_map[packed].hasUnit == !removed);
        assert(g_map[packed].index == (removed ? 0 : 17));
        assert(marks == 1 && BitArray_Test(g_dirtyViewport,packed));
#ifdef TOS
        assert(BitArray_Test(g_dirtyMinimap,packed) == !native);
#else
        assert(BitArray_Test(g_dirtyMinimap,packed));
#endif
    }
    return 0;
}
"""
        for tos in (True, False):
            run_harness(harness.replace("/* PRODUCTION */", production), tos=tos)

    def test_movement_keeps_old_wobble_through_departure_and_rng_order(self):
        source = (ROOT / "src/unit.c").read_text()
        move = function(source, "Unit_Move")
        end = move.index("unit->wobbleIndex = nextWobble;") + len("unit->wobbleIndex = nextWobble;")
        prefix = move[:end] + "\n(void)ret; (void)currentDestination; (void)isSpiceBloom; (void)isSpecialBloom;\nreturn false;\n}"
        tile = (ROOT / "src/tile.c").read_text()
        production = function(tile, "Orientation_Orientation256ToOrientation8") + "\n" + prefix
        harness = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#include "src/unit.h"
#include "src/map.h"
#include "src/tile.h"
#include "src/animation.h"
UnitInfo g_table_unitInfo[UNIT_MAX];
const AnimationCommandStruct g_table_animation_unitMove[8][8] = {{{0,0}}};
Unit *g_unitSelected;
Tile g_map[4096];
static unsigned rngCalls, calls, oldWobble, randomValue, trackCalls, wobbleEnabled;
uint8 Tools_Random_256(void) {
    assert(rngCalls < 2); return rngCalls++ == 0 ? randomValue : 123;
}
tile32 Tile_MoveByDirection(tile32 p, int16 angle, uint16 distance) {
    assert(angle == 0); p.y -= distance; return p;
}
uint16 Tile_GetDistance(tile32 a, tile32 b) { (void)a; (void)b; return 16; }
Unit *Unit_Get_ByPackedTile(uint16 packed) { assert(packed < 4096); return NULL; }
uint16 Map_GetLandscapeType(uint16 packed) { assert(packed < 4096); return LST_NORMAL_SAND; }
void Unit_Remove(Unit *u) { (void)u; assert(false); }
void Unit_Select(Unit *u) { (void)u; assert(false); }
void Unit_UntargetMe(Unit *u) { (void)u; assert(false); }
void Unit_SetAction(Unit *u, ActionType a) { (void)u; (void)a; assert(false); }
void Unit_SetOrientation(Unit *u, int8 a, bool instant, uint16 level) {
    (void)u; (void)a; (void)instant; (void)level; assert(false);
}
void Animation_Start(const AnimationCommandStruct *commands, tile32 tile,
                     uint16 layout, uint8 house, uint8 icons) {
    assert(commands == g_table_animation_unitMove[0]);
    assert(tile.x == 0x1480 && tile.y == 0x1480 && !layout && !house && icons == 5);
    assert(rngCalls == wobbleEnabled);
    (void)Tools_Random_256(); trackCalls++;
}
void Unit_UpdateMap(uint16 mode, Unit *u) {
    assert(mode == 0 && u->wobbleIndex == oldWobble);
    assert(u->o.position.x == 0x1480 && u->o.position.y == 0x1480);
    assert(rngCalls == wobbleEnabled + trackCalls); calls++;
}
/* PRODUCTION */
int main(void) {
    UnitInfo *ui = &g_table_unitInfo[UNIT_TANK];
    for (oldWobble = 0; oldWobble < 8; oldWobble++)
    for (randomValue = 0; randomValue < 256; randomValue++)
    for (wobbleEnabled = 0; wobbleEnabled < 2; wobbleEnabled++)
    for (unsigned tracks = 0; tracks < 2; tracks++) {
        Unit u = {0}; u.o.type = UNIT_TANK; u.o.flags.s.used = true;
        u.o.position = (tile32){0x1480,0x1480}; u.wobbleIndex = oldWobble;
        u.o.flags.s.isWobbling = wobbleEnabled; ui->flags.canWobble = true;
        ui->flags.isTracked = tracks;
        rngCalls = calls = trackCalls = 0;
        assert(!Unit_Move(&u,16));
        assert(calls == 1 && trackCalls == tracks);
        assert(rngCalls == wobbleEnabled + tracks);
        assert(u.wobbleIndex == (wobbleEnabled ? randomValue & 7 : 0));
    }
    return 0;
}
"""
        for tos in (True, False):
            run_harness(harness.replace("/* PRODUCTION */", production), tos=tos)

    def test_explosion_frame_shrink_move_stop_and_legacy(self):
        source = (ROOT / "src/explosion.c").read_text()
        production = map_production() + "\n" + "\n".join(
            function(source, name) for name in (
                "Explosion_Update", "Explosion_Func_MoveYPosition",
                "Explosion_Func_SetSpriteID", "Explosion_Func_Stop"))
        harness = COMMON + r"""
uint8 g_functions[3][3] = {{0,1,0},{2,3,0},{0,1,0}};
static unsigned legacyCalls;
void Map_UpdateAround(uint16 radius, tile32 position, Unit *unit, uint8 fn) {
    assert(radius == 24 && unit == NULL && fn <= 1); (void)position; legacyCalls++;
}
/* PRODUCTION */
int main(void) {
    initSprites(); images[10][3] = 32; images[10][2] = 31;
    images[11][3] = 8; images[11][2] = 9;
    static const ExplosionCommandStruct commands[] = {{EXPLOSION_STOP,0}};
    Explosion e = {0}; e.commands = commands; e.position = (tile32){0x1400,0x1480};
    e.timeOut = 123; e.current = 7;
    clearDamage(); Explosion_Func_SetSpriteID(&e,10);
#ifdef TOS
    assert(!g_dirtyViewportCount && e.isDirty);
#else
    assert(legacyCalls == 1);
#endif
    uint8 expected[512] = {0};
    expectedSprite(expected,10,e.position,0,0);
    clearDamage(); Explosion_Func_SetSpriteID(&e,11);
#ifdef TOS
    assert(!memcmp(expected,g_dirtyMinimap,512) && e.isDirty);
    clearDamage(); Explosion_Func_SetSpriteID(&e,11);
    assert(!g_dirtyViewportCount && e.isDirty);
    memset(expected,0,512); expectedSprite(expected,11,e.position,0,0);
    Explosion_Func_MoveYPosition(&e,32 * 16);
    assert(!memcmp(expected,g_dirtyMinimap,512) && e.position.y == 0x1680 && e.isDirty);
    clearDamage(); memset(expected,0,512); expectedSprite(expected,11,e.position,0,0);
    Explosion_Func_Stop(&e,0);
    assert(!memcmp(expected,g_dirtyMinimap,512) && !e.commands && !e.isDirty);
    assert(e.timeOut == 123 && e.current == 7);
#endif
    direct = false; legacyCalls = 0; e.isDirty = false;
    Explosion_Func_SetSpriteID(&e,10); Explosion_Func_MoveYPosition(&e,16);
    Explosion_Func_Stop(&e,0); assert(legacyCalls == 2);
    clearDamage(); Map_UpdateSprite(0,e.position,0,0); assert(!g_dirtyViewportCount);
    return 0;
}
"""
        for tos in (True, False):
            run_harness(harness.replace("/* PRODUCTION */", production), tos=tos)

    def test_spice_edges_only_invalidate_changed_final_graphics(self):
        source = (ROOT / "src/map.c").read_text()
        production = "\n".join(function(source, name) for name in
                               ("Map_FixupSpiceEdges", "Map_ChangeSpiceAmount"))
        harness = COMMON + r"""
#include "src/sprites.h"
static uint16 icons[256];
uint16 *g_iconMap = icons;
static unsigned updates[4096], total, prepared;
uint16 Map_GetLandscapeType(uint16 packed) {
    unsigned id = g_map[packed].groundTileID;
    return id >= 65 && id < 81 ? LST_THICK_SPICE : id >= 49 && id < 65 ? LST_SPICE : LST_NORMAL_SAND;
}
void Map_Update(uint16 packed, uint16 type, bool ignoreInvisible) {
    assert(packed < 4096 && type == 0 && !ignoreInvisible); updates[packed]++; total++;
}
Unit *Unit_Get_ByPackedTile(uint16 packed) { (void)packed; return g_unitSelected; }
void Unit_PrepareSpriteChange(Unit *unit, uint16 parts) {
    assert(unit == g_unitSelected && parts == UNIT_SPRITE_HARVEST);
    assert(Map_GetLandscapeType(Tile_PackTile(unit->o.position)) == LST_SPICE); prepared++;
}
void Unit_UpdateMap(uint16 mode, Unit *unit) { assert(mode == UNIT_UPDATE_MAP_REPAINT && unit); }
/* PRODUCTION */
int main(void) {
    initSprites(); clearDamage();
    (void)expectedSprite;
    (void)Map_IsTileVisible;
    for (unsigned i = 0; i < 81; i++) icons[100 + i] = i;
    icons[ICM_ICONGROUP_LANDSCAPE] = 100;
    unsigned centre = Tile_PackXY(20,20);
    /* A pre-existing final edge graphic and all non-spice neighbours stay clean. */
    g_map[centre].groundTileID = 49;
    Map_FixupSpiceEdges(centre,49); assert(!total);
    assert(g_mapTileID[centre] == (0x8000 | 49));
    Map_FixupSpiceEdges(centre + 1,0); assert(!total);
    /* Grade change remains dirty even when fixup's computed edge equals the
       intermediate base tile written by Map_ChangeSpiceAmount. */
    Map_ChangeSpiceAmount(centre,1);
    assert(total == 1 && updates[centre] == 1 && g_map[centre].groundTileID == 65);
    Map_ChangeSpiceAmount(centre,1); assert(total == 1);
    Map_ChangeSpiceAmount(centre,-1); assert(total == 2 && g_map[centre].groundTileID == 49);
    Unit h = {0}; h.o.type = UNIT_HARVESTER; h.actionID = ACTION_HARVEST;
    h.o.position = (tile32){0x1480,0x1480}; g_unitSelected = &h;
    Map_ChangeSpiceAmount(centre,-1);
    assert(total == 3 && g_map[centre].groundTileID == 0 && prepared == 1);
    Map_ChangeSpiceAmount(centre,-1); assert(total == 3);
    g_unitSelected = NULL;
    /* Neighbour visual changes are still updated, unchanged ones are not. */
    Map_ChangeSpiceAmount(centre,1);
    g_map[centre + 1].groundTileID = 49;
    unsigned before = total;
    Map_FixupSpiceEdges(centre,49);
    assert(total == before + 1 && g_map[centre].groundTileID == 51);
    before = total; Map_FixupSpiceEdges(centre,51); assert(total == before);
    /* Packed wraparound and world edges remain valid. */
    for (unsigned edge = 0; edge < 4096; edge += 4095) {
        g_map[edge].groundTileID = 0;
        Map_ChangeSpiceAmount(edge,1); assert(g_map[edge].groundTileID >= 49);
    }
    return 0;
}
"""
        run_harness(harness.replace("/* PRODUCTION */", production))
