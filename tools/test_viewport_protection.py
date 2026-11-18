"""Check fog metadata and compact native effect damage against production code."""

import unittest

from tools.test_sprite_bounds import COMMON
from tools.test_unit_smoke_damage import ROOT, run_harness
from tools.test_viewport_sprite_cache import function, rocket_directions


class ViewportProtectionTest(unittest.TestCase):
    def test_opaque_footprints_preserve_canvas_anchors_and_flips(self):
        source = (ROOT / "src/map.c").read_text()
        sprites = (ROOT / "src/sprites.c").read_text()
        production = "\n".join(function(text, name) for text, name in (
            (sprites, "Sprite_GetWidth"), (sprites, "Sprite_GetHeight"),
            (source, "Map_UpdateViewportCandidateColumns"), (source, "Map_ClearViewportDamage"),
            (source, "Map_RebaseViewportDamage"), (source, "Map_Update"),
            (source, "Map_UpdateSprite"),
        ))
        harness = COMMON + r"""
uint16 g_viewportPosition, g_minimapPosition;
uint16 g_viewportDamagePosition = 0xffff, g_viewportTerrainDamage[10], g_viewportCandidateTop;
uint32 g_viewportCandidateDamage[13], g_viewportCandidateColumns[64];
bool g_viewportNoHaloDamage;
/* PRODUCTION */
int main(void) {
    initSprites(); (void)expectedSprite;
    g_minimapPosition = g_viewportPosition = Tile_PackXY(16,16);
    unsigned shapes[][6] = {{24,24,4,1,19,22}, {24,24,2,4,23,22}, {17,15,1,2,16,12}};
    for (unsigned shape = 0; shape < 3; shape++)
    for (unsigned flags = 0; flags < 4; flags++)
    for (unsigned px = 0; px < 16; px++)
    for (unsigned py = 0; py < 16; py++) {
        unsigned *s = shapes[shape], width = s[0], height = s[1];
        images[248][3] = width; images[248][2] = height;
        GUI_SpriteBounds b = {
            flags & DRAWSPRITE_FLAG_RTL ? width - s[4] : s[2],
            flags & DRAWSPRITE_FLAG_BOTTOMUP ? height - s[5] : s[3],
            flags & DRAWSPRITE_FLAG_RTL ? width - s[2] : s[4],
            flags & DRAWSPRITE_FLAG_BOTTOMUP ? height - s[3] : s[5]};
        g_viewportSpriteBounds[248][flags] = b;
        tile32 pos = {(20*16+px)*16, (20*16+py)*16};
        int l = 20*16+px-width/2+b.left, t = 20*16+py-height/2+b.top;
        int r = 20*16+px-width/2+b.right, bottom = 20*16+py-height/2+b.bottom;
        uint16 expected[10] = {0};
        for (int y = t; y < bottom; y++) for (int x = l; x < r; x++)
            expected[y/16-16] |= 1u << (x/16-16);
        uint8 header[10]; memcpy(header,images[248],sizeof(header));
        clearDamage(); Map_ClearViewportDamage();
        Map_UpdateSprite(248,pos,0,0,flags,MAP_SPRITE_DAMAGE_HARVESTER);
        assert(!memcmp(expected,g_viewportTerrainDamage,sizeof(expected)));
        assert(!memcmp(header,images[248],sizeof(header)));
        /* North-facing opacity excludes both side columns at tile centre. */
        if (!shape && !flags && px == 8)
            for (unsigned row = 0; row < 10; row++) assert(!(expected[row] & ~(1u << 4)));
        /* East-facing opacity starts below the transparent upper tile. */
        if (shape == 1 && !flags && py == 8) assert(!expected[3]);
    }
    /* Empty frames must not enqueue terrain or discovery work. */
    memset(g_viewportSpriteBounds[248],0,sizeof(g_viewportSpriteBounds[248]));
    clearDamage(); Map_ClearViewportDamage();
    Map_UpdateSprite(248,(tile32){0x1480,0x1480},0,0,0,MAP_SPRITE_DAMAGE_HARVESTER);
    assert(!g_dirtyViewportCount);
    for (unsigned row = 0; row < 10; row++) assert(!g_viewportTerrainDamage[row]);
    for (unsigned row = 0; row < 13; row++) assert(!g_viewportCandidateDamage[row]);
    return 0;
}
"""
        run_harness(harness.replace("/* PRODUCTION */", production))

    def test_harvester_discovery_cap_preserves_terrain_and_registration(self):
        source = (ROOT / "src/map.c").read_text()
        sprites = (ROOT / "src/sprites.c").read_text()
        tile = (ROOT / "src/tile.c").read_text()
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        production = rocket_directions(viewport) + "\n" + "\n".join(function(text, name) for text, name in (
            (sprites, "Sprite_GetWidth"), (sprites, "Sprite_GetHeight"),
            (tile, "Tile_AddTileDiff"), (tile, "Orientation_Orientation256ToOrientation8"),
            (tile, "Orientation_Orientation256ToOrientation16"),
            (source, "Map_UpdateViewportCandidateColumns"), (source, "Map_ClearViewportDamage"),
            (source, "Map_RebaseViewportDamage"), (source, "Map_Update"),
            (source, "Map_UpdateSprite"), (source, "Map_UpdateAround"),
            (viewport, "GUI_Widget_Viewport_GroundSprites"),
            (viewport, "GUI_Widget_Viewport_AirSprite"),
            (viewport, "GUI_Widget_Viewport_DamageUnit"),
        ))
        harness = COMMON + r"""
uint16 g_viewportPosition, g_minimapPosition;
uint16 g_viewportDamagePosition = 0xffff, g_viewportTerrainDamage[10], g_viewportCandidateTop;
uint32 g_viewportCandidateDamage[13], g_viewportCandidateColumns[64];
bool g_viewportNoHaloDamage;
static unsigned adds, removes;
uint8 Unit_GetHouseID(Unit *unit) { return unit->o.houseID; }
uint16 Map_GetLandscapeType(uint16 packed) { (void)packed; return LST_SPICE; }
void Unit_AddToTile(Unit *unit, uint16 packed) {
    assert(unit && packed < 4096); adds++;
}
void Unit_RemoveFromTile(Unit *unit, uint16 packed) {
    assert(unit && packed < 4096); removes++;
}
static void GUI_Widget_Viewport_AddSpriteLayer(GUI_SpriteLayers *layers, uint16 id,
    uint8 house, int16 x, int16 y, int flags) {
    GUI_SpriteLayer *layer = &layers->layer[layers->count++];
    layer->spriteID = id; layer->colourHouse = house;
    layer->offsetX = x; layer->offsetY = y; layer->flags = flags;
}
/* PRODUCTION */
static void candidateSquare(uint32 expected[13], uint16 packed, int radius) {
    memset(expected,0,13*sizeof(*expected));
    int x = packed & 63, y = packed >> 6;
    for (int dy = -radius; dy <= radius; dy++)
    for (int dx = -radius; dx <= radius; dx++) {
        if (x+dx < 0 || x+dx >= 64 || y+dy < 0 || y+dy >= 64) continue;
        uint16 row;
        uint32 column = Map_ViewportCandidateMask(Tile_PackXY(x+dx,y+dy),&row);
        if (column) expected[row] |= column;
    }
}
int main(void) {
    initSprites();
    for (unsigned id = 248; id <= 252; id++) images[id][2] = images[id][3] = 24;
    for (unsigned id = 180; id <= 182; id++) images[id][2] = 24;
    for (unsigned id = 0; id < 355; id++) fullBounds(id);
    g_viewportPosition = g_minimapPosition = Tile_PackXY(16,16);
    Unit u = {0}; u.o.type = UNIT_HARVESTER; u.o.flags.s.used = true;
    UnitInfo *ui = &g_table_unitInfo[UNIT_HARVESTER];
    ui->groundSpriteID = 248; ui->turretSpriteID = 0xffff; ui->destroyedSpriteID = 165;
    ui->displayMode = DISPLAYMODE_UNIT; ui->movementType = MOVEMENT_HARVESTER;
    for (unsigned angle = 0; angle < 8; angle++)
    for (unsigned frame = 0; frame < 4; frame++)
    for (unsigned flags = 0; flags < 8; flags++)
    for (unsigned px = 0; px < 16; px++)
    for (unsigned py = 0; py < 16; py++) {
        u.o.position = (tile32){(20*16+px)*16,(20*16+py)*16};
        u.orientation[0].current = angle*32; u.spriteOffset = frame == 3 ? -1 : (int)frame;
        u.actionID = flags & 1 ? ACTION_HARVEST : ACTION_GUARD;
        u.o.flags.s.isSmoking = (flags & 2) != 0;
        u.o.flags.s.bulletIsBig = (flags & 4) != 0;
        g_unitSelected = &u;
        GUI_SpriteLayers layers; int spriteFlags;
        uint16 body = GUI_Widget_Viewport_GroundSprites(&u,&spriteFlags,&layers,UNIT_SPRITE_ALL);
        uint8 expected[512] = {0};
        expectedSprite(expected,body,u.o.position,0,0);
        for (unsigned i = 0; i < layers.count; i++)
            expectedSprite(expected,layers.layer[i].spriteID,u.o.position,
                           layers.layer[i].offsetX,layers.layer[i].offsetY);
        clearDamage(); Map_ClearViewportDamage();
        GUI_Widget_Viewport_DamageUnit(&u,UNIT_SPRITE_ALL);
        uint32 candidates[13]; candidateSquare(candidates,Tile_PackTile(u.o.position),1);
        assert(!memcmp(candidates,g_viewportCandidateDamage,sizeof(candidates)));
        assert(!g_viewportNoHaloDamage);
        for (unsigned row = 0; row < 10; row++)
        for (unsigned col = 0; col < 15; col++)
            assert(!!(g_viewportTerrainDamage[row] & (1u<<col)) ==
                   !!BitArray_Test(expected,Tile_PackXY(16+col,16+row)));
    }
    /* A forced/history radius still visits every registration tile. */
    for (unsigned harvester = 0; harvester < 2; harvester++)
    for (unsigned callback = 2; callback <= 3; callback++)
    for (unsigned mark = 0; mark < 2; mark++)
    for (unsigned edge = 0; edge < 3; edge++) {
        uint16 centre = edge == 0 ? Tile_PackXY(20,20) :
                        edge == 1 ? Tile_PackXY(0,0) : Tile_PackXY(63,63);
        g_minimapPosition = g_viewportPosition = edge == 0 ? Tile_PackXY(16,16) :
            edge == 1 ? Tile_PackXY(0,0) : Tile_PackXY(49,54);
        u.o.type = harvester ? UNIT_HARVESTER : UNIT_TANK;
        u.o.position = Tile_UnpackTile(centre);
        clearDamage(); Map_ClearViewportDamage(); adds = removes = 0;
        if (harvester) {
            uint32 expected[13];
            Map_UpdateSprite(248,u.o.position,0,0,0,MAP_SPRITE_DAMAGE_HARVESTER);
            candidateSquare(expected,centre,1);
            assert(!memcmp(expected,g_viewportCandidateDamage,sizeof(expected)));
            assert(!g_viewportNoHaloDamage);
            clearDamage(); Map_ClearViewportDamage();
        }
        Map_UpdateAround(33,u.o.position,&u,callback,mark);
        unsigned visits = edge == 0 ? 25 : 9;
        assert(adds == (callback == 3 ? visits : 0));
        assert(removes == (callback == 2 ? visits : 0));
        uint32 expected[13] = {0};
        if (mark) candidateSquare(expected,centre,harvester ? 1 : 2);
        assert(!memcmp(expected,g_viewportCandidateDamage,sizeof(expected)));
        assert(!g_viewportNoHaloDamage);
        for (unsigned row = 0; row < 10; row++) assert(!g_viewportTerrainDamage[row]);
    }
    return 0;
}
"""
        production = function(tile, "Tile_UnpackTile") + "\n" + production
        run_harness(harness.replace("/* PRODUCTION */", production))

    def test_native_footprints_and_overlap_admission(self):
        source = (ROOT / "src/map.c").read_text()
        sprites = (ROOT / "src/sprites.c").read_text()
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        production = "\n".join(function(source, name) for name in (
            "Map_UpdateViewportCandidateColumns", "Map_ClearViewportDamage",
            "Map_RebaseViewportDamage", "Map_Update", "Map_UpdateSprite"))
        production = "\n".join(function(sprites, name) for name in (
            "Sprite_GetWidth", "Sprite_GetHeight")) + "\n" + production
        # This always-inline declaration has an attribute not handled by function().
        start = viewport.index("static inline __attribute__((always_inline)) bool Viewport_DirtyBitSet")
        admission = viewport[start:viewport.index("\n}", start) + 2]
        admission = admission[:admission.index("\t__asm__ goto")] + """
    return BitArray_Test(g_dirtyViewport,packed);
}
"""
        harness = COMMON + r"""
uint16 g_viewportPosition, g_minimapPosition;
uint16 g_viewportDamagePosition = 0xffff, g_viewportTerrainDamage[10];
uint16 g_viewportCandidateTop;
uint32 g_viewportCandidateDamage[13], g_viewportCandidateColumns[64];
bool g_viewportNoHaloDamage;
/* PRODUCTION */
/* ADMISSION */
int main(void) {
    initSprites(); (void)expectedSprite;
    g_viewportPosition = g_minimapPosition = Tile_PackXY(16,16);
    g_veiledTileID = 98;
    fogIcons[ICM_ICONGROUP_FOG_OF_WAR] = 32; fogIcons[47] = 99;
    for (unsigned debug = 0; debug < 2; debug++)
    for (unsigned fog = 0; fog < 4; fog++)
    for (unsigned small = 0; small < 2; small++)
    for (unsigned size = 8; size <= 17; size += size == 8 ? 8 : 1)
    for (unsigned px = 0; px < 16; px++)
    for (unsigned py = 0; py < 16; py++) {
        memset(g_map,0,sizeof(g_map));
        g_debugScenario = debug != 0;
        uint16 tile = Tile_PackXY(20,20);
        g_map[tile].overlayTileID = fog == 0 ? 0 : fog == 1 ? 97 : fog == 2 ? 98 : 99;
        images[10][3] = images[10][2] = size;
        fullBounds(10);
        tile32 pos = {(20*16+px)*16, (20*16+py)*16};
        clearDamage(); Map_ClearViewportDamage();
        Map_UpdateSprite(10,pos,0,0,0,small);
        uint16 terrain[10] = {0};
        uint32 candidates[13] = {0};
        bool tight = small && size <= 16, touched = false;
        int left = 20*16+px-size/2, top = 20*16+py-size/2;
        for (int y = top/16; y <= (top+(int)size-1)/16; y++)
        for (int x = left/16; x <= (left+(int)size-1)/16; x++) {
            if (!debug && fog >= 2 && Tile_PackXY(x,y) == tile) continue;
            terrain[y-16] |= 1u << (x-16);
            touched = true;
            int halo = tight ? 0 : 1;
            for (int dy = -halo; dy <= halo; dy++)
            for (int dx = -halo; dx <= halo; dx++)
                candidates[y-16+1+dy] |= 1u << (x-16+1+dx);
        }
        assert(!memcmp(terrain,g_viewportTerrainDamage,sizeof(terrain)));
        assert(!memcmp(candidates,g_viewportCandidateDamage,sizeof(candidates)));
        assert(g_viewportNoHaloDamage == (tight && touched));
        /* A large overlapping sprite can have its centre outside compact damage. */
        uint16 centre = Tile_PackXY(25,20);
        assert(!Map_ViewportCandidateDirty(centre));
        assert(Viewport_DirtyBitSet(centre,true) == g_viewportNoHaloDamage);
        assert(!Viewport_DirtyBitSet(centre,false));
        /* Genuine fog changes must still restore fully hidden terrain. */
        Map_ClearViewportDamage();
        Map_Update(tile,0,false);
        assert(g_viewportTerrainDamage[4] == (1u << 4));
        assert(!g_viewportNoHaloDamage);
        Map_ClearViewportDamage();
        assert(!g_viewportNoHaloDamage);
    }
    return 0;
}
"""
        run_harness(harness.replace("/* PRODUCTION */", production)
                    .replace("/* ADMISSION */", admission))

    def test_shared_fog_masks_and_metadata_refresh(self):
        gfx = (ROOT / "src/gfx.c").read_text()
        video = (ROOT / "src/video/video_atari.c").read_text()
        state = "\n".join(function(video, name) for name in (
            "Video_Atari_ResetViewportProtection", "Video_Atari_SetViewportFog",
            "Video_Atari_BeginViewportProtection", "Video_Atari_EndViewportProtection",
            "Video_Atari_ViewportProtectionOverlap", "Video_Atari_ViewportWritable"))
        header = (ROOT / "src/video/video.h").read_text()
        state = header[header.index("typedef enum VideoAtariTileCursorShape"):
                       header.index("} VideoAtariTileCursorShape;") +
                       len("} VideoAtariTileCursorShape;")] + "\n" + state
        state = state.replace("void Video_Atari_SetViewportFog(",
                              "static void SetViewportFogRaw(")
        harness = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#include "src/map.h"
#include "src/sprites.h"
#define lengthof(a) (sizeof(a)/sizeof((a)[0]))
Tile g_map[4096];
uint16 g_viewportPosition, g_viewportTerrainDamage[10], g_veiledTileID = 98;
static uint16 icons[128], tileMasks[128*16];
uint16 *g_iconMap = icons;
static uint16 *s_planarTileMasks = tileMasks;
static bool g_debugScenario;
static const uint16 *s_blitterHalftonePattern;
static unsigned metadataUpdates, cursorPrepares;
#define ST_PLANAR_LINE_BYTES 160
static bool s_viewportBlitter;
static uint16 g_tileCursorPen, g_tileCursorTargetPen;
static const uint16 *s_viewportFogWritable[10][15], *s_tileCursorPattern;
static uint16 s_viewportProtectedRows[10], s_viewportHiddenRows[10];
static bool s_viewportProtectionActive, g_videoTileCursorRestored;
static void (*g_videoTileCursorTail)(void);
static const uint16 s_tileCursorPatterns[6][16] = {{0}};
static void prepare_cursor(uint16 col, uint16 row, const uint16 *pattern, uint16 pen) {
    assert(col < 15 && row < 10 && pattern != NULL && pen <= 15);
    cursorPrepares++;
}
#define Video_Atari_PrepareTileCursor prepare_cursor
static void blit_cursor(void) { assert(false); }
static void Video_Atari_DrawTileCursorCPU(void) { assert(false); }
static const struct { void (*blit)(void); } cursorBackend = {blit_cursor},
    *s_tileCursorBackend = &cursorBackend;
void Video_Atari_EndViewportProtection(void);
/* VIDEO STATE */
void Video_Atari_SetViewportFog(uint16 col, uint16 row, const uint16 *writable) {
    metadataUpdates++;
    SetViewportFogRaw(col,row,writable);
}
static uint16 s_fogWritable[17][16];
static uint8 s_fogType[128];
static uint16 s_protectionDirtyRows[10];
static bool s_fogWritableReady, s_protectionDebug, s_protectionDirty;
static uint16 s_protectionPosition = 0xffff;
static unsigned decodes;
static uint16 GFX_GetPlanarTile(uint16 id, uint8 house) {
    assert(id >= 1 && id <= 14 && house == 0); decodes++; return id;
}
/* PREPARE */
int main(void) {
    (void)Video_Atari_ViewportProtectionOverlap;
    (void)Video_Atari_ViewportWritable;
    icons[ICM_ICONGROUP_FOG_OF_WAR] = 32;
    for (unsigned id = 0; id < 16; id++) {
        icons[32+id] = id;
        for (unsigned line = 0; line < 16; line++)
            tileMasks[id*16+line] = (id * 1531 + line * 177) & 0xffff;
    }
    g_viewportPosition = 20*64+20;
    for (unsigned row = 0; row < 10; row++)
    for (unsigned col = 0; col < 15; col++)
        g_map[g_viewportPosition+row*64+col].overlayTileID = col;
    g_map[g_viewportPosition].overlayTileID = 98;
    g_map[g_viewportPosition+1].overlayTileID = 15;
    g_map[g_viewportPosition+2].overlayTileID = 97; /* Crater, not fog. */
    GFX_PrepareViewportProtection(false);
    assert(decodes == 14 && metadataUpdates == 150);
    assert(s_viewportHiddenRows[0] == 3);
    assert(s_viewportFogWritable[0][2] == NULL);
    for (unsigned col = 3; col < 15; col++)
    for (unsigned line = 0; line < 16; line++)
        assert((uint16)(s_viewportFogWritable[0][col][line] ^
                        tileMasks[col*16+line]) == 0xffff);
    /* Ordinary terrain/sprite damage must not trigger fog inspection. */
    for (unsigned row = 0; row < 10; row++) g_viewportTerrainDamage[row] = 0x7fff;
    s_viewportProtectedRows[0] = 0;
    GFX_PrepareViewportProtection(false);
    assert(s_viewportProtectedRows[0] == 0 && decodes == 14 && metadataUpdates == 150);
    GFX_PrepareViewportProtection(true);
    assert(s_viewportProtectedRows[0] != 0 && metadataUpdates == 300);
    g_map[g_viewportPosition].overlayTileID = 0;
    GFX_InvalidateViewportProtection(g_viewportPosition);
    GFX_InvalidateViewportProtection(g_viewportPosition);
    /* Outside cells neither wrap into another row nor request a refresh. */
    GFX_InvalidateViewportProtection(g_viewportPosition-1);
    GFX_InvalidateViewportProtection(g_viewportPosition+15);
    GFX_InvalidateViewportProtection(g_viewportPosition+10*64);
    GFX_PrepareViewportProtection(false);
    assert(s_viewportFogWritable[0][0] == NULL && s_viewportHiddenRows[0] == 2);
    assert(metadataUpdates == 301 && !s_protectionDirty);
    for (unsigned row = 0; row < 10; row++) assert(s_protectionDirtyRows[row] == 0);
    memset(g_viewportTerrainDamage,0,sizeof(g_viewportTerrainDamage));
    g_debugScenario = true;
    GFX_PrepareViewportProtection(false);
    for (unsigned row = 0; row < 10; row++) assert(s_viewportProtectedRows[row] == 0);
    g_debugScenario = false;
    GFX_PrepareViewportProtection(false);
    assert(s_viewportHiddenRows[0] == 2);
    g_viewportPosition++;
    GFX_PrepareViewportProtection(false);
    assert(s_viewportHiddenRows[0] == 1);
    /* Cursor preparation never changes the fog-only protection metadata. */
    uint16 fog[16];
    for (unsigned line = 0; line < 16; line++) fog[line] = 0x5a5a ^ (line * 117);
    Video_Atari_ResetViewportProtection();
    Video_Atari_SetViewportFog(4,3,fog);
    for (unsigned hardware = 0; hardware < 2; hardware++)
    for (VideoAtariTileCursorShape shape = TILE_CURSOR_NORMAL;
         shape <= TILE_CURSOR_SCROLL_LEFT; shape++) {
        s_viewportBlitter = hardware;
        s_blitterHalftonePattern = fog;
        unsigned before = cursorPrepares;
        Video_Atari_BeginViewportProtection(true,4,3,shape);
        assert(cursorPrepares == before+1 && s_blitterHalftonePattern == fog);
        assert(g_videoTileCursorTail == (hardware ? blit_cursor : Video_Atari_DrawTileCursorCPU));
        assert(!g_videoTileCursorRestored);
        assert(Video_Atari_ViewportWritable(4,3) == fog);
        assert(Video_Atari_ViewportProtectionOverlap(64,88,16,16));
        Video_Atari_BeginViewportProtection(true,3,2,shape);
        assert(!Video_Atari_ViewportProtectionOverlap(48,72,16,16));
        assert(Video_Atari_ViewportWritable(3,2) == NULL);
        assert(Video_Atari_ViewportWritable(4,3) == fog);
        Video_Atari_EndViewportProtection();
        assert(!g_videoTileCursorTail && !s_viewportProtectionActive);
        Video_Atari_BeginViewportProtection(false,0,0,shape);
        assert(!g_videoTileCursorTail && s_viewportProtectionActive);
    }
    Video_Atari_ResetViewportProtection();
    assert(!s_viewportProtectionActive && !g_videoTileCursorTail && !s_blitterHalftonePattern);
    for (unsigned row = 0; row < 10; row++)
        for (unsigned col = 0; col < 15; col++)
            assert(!s_viewportProtectedRows[row] && !s_viewportHiddenRows[row] &&
                Video_Atari_ViewportWritable(col,row) == NULL);
    return 0;
}
"""
        harness = harness.replace("/* VIDEO STATE */", state)
        harness = harness.replace("/* PREPARE */", "\n".join(function(gfx, name) for name in (
            "GFX_InvalidateViewportProtection", "GFX_PrepareViewportProtection")))
        run_harness(harness)

    def test_fog_mutations_notify_protection(self):
        source = (ROOT / "src/map.c").read_text()
        harness = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#include "src/map.h"
#include "src/unit.h"
#include "src/sprites.h"
#ifdef TOS
#define SAME_FOG_REDRAW 0
#define FOG_CACHE_ACTIVE 1
#else
#define SAME_FOG_REDRAW 1
#define FOG_CACHE_ACTIVE 0
#endif
Tile g_map[4096];
static uint16 icons[128];
uint16 *g_iconMap = icons;
const int16 g_table_mapDiff[4] = {-64,1,64,-1};
uint16 g_validateStrictIfZero;
static unsigned invalidations, updates, visibilityUpdates;
static uint16 changed;
static bool direct = true;
static Unit occupant;
uint8 g_playerHouseID;
bool Video_Atari_CursorDirect(void) { return direct; }
bool Tile_IsUnveiled(uint16 id) { return id == 0; }
Unit *Unit_Get_ByPackedTile(uint16 packed) { (void)packed; return &occupant; }
void Unit_HouseUnitCount_Add(Unit *unit, uint8 house) {
    assert(unit == &occupant && house == g_playerHouseID); visibilityUpdates++;
}
void GFX_InvalidateViewportProtection(uint16 packed) { invalidations++; changed = packed; }
void Map_Update(uint16 packed, uint16 type, bool invisible) {
    assert(packed < 4096 && type == 0 && !invisible); updates++;
}
/* PRODUCTION */
int main(void) {
    icons[ICM_ICONGROUP_FOG_OF_WAR] = 32;
    for (unsigned i = 0; i < 16; i++) icons[32+i] = i;
    uint16 tile = 20*64+20;
    g_map[tile].overlayTileID = 98;
    Map_UnveilTile_Neighbour(tile);
    assert(invalidations == FOG_CACHE_ACTIVE && changed == (FOG_CACHE_ACTIVE ? tile : 0) &&
           g_map[tile].overlayTileID == 15);
    Map_UnveilTile_Neighbour(tile);
    assert(invalidations == FOG_CACHE_ACTIVE && updates == 1 + SAME_FOG_REDRAW);
    g_map[tile].isUnveiled = true;
    g_map[tile-64].isUnveiled = true;
    Map_UnveilTile_Neighbour(tile);
    assert(invalidations == 2*FOG_CACHE_ACTIVE && g_map[tile].overlayTileID == 14);
    Map_UnveilTile_Neighbour(tile);
    assert(invalidations == 2*FOG_CACHE_ACTIVE && visibilityUpdates == 2 &&
           updates == 2 + 2*SAME_FOG_REDRAW);
    for (unsigned i = 0; i < 4; i++) g_map[tile+g_table_mapDiff[i]].isUnveiled = true;
    Map_UnveilTile_Neighbour(tile);
    assert(invalidations == 3*FOG_CACHE_ACTIVE && g_map[tile].overlayTileID == 0);
    Map_UnveilTile_Neighbour(tile);
    Map_UnveilTile_Neighbour(0xffff);
    assert(invalidations == 3*FOG_CACHE_ACTIVE && updates == 3 + 2*SAME_FOG_REDRAW);
    /* Non-planar backends retain their existing redraw notification. */
    direct = false;
    g_map[tile].isUnveiled = false;
    g_map[tile].overlayTileID = 15;
    Map_UnveilTile_Neighbour(tile);
    assert(invalidations == 3*FOG_CACHE_ACTIVE && updates == 4 + 2*SAME_FOG_REDRAW);
    return 0;
}
"""
        production = harness.replace("/* PRODUCTION */",
                                     function(source, "Map_UnveilTile_Neighbour"))
        run_harness(production)
        run_harness(production, tos=False)


if __name__ == "__main__":
    unittest.main()
