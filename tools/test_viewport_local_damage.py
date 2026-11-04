"""Exercise native viewport damage producers and scroll rebasing."""

import unittest

from tools.test_unit_smoke_damage import ROOT, run_harness
from tools.test_viewport_sprite_cache import function


class ViewportLocalDamageTest(unittest.TestCase):
    def test_marking_rebasing_and_legacy_masks(self):
        source = (ROOT / "src/map.c").read_text()
        production = function((ROOT / "src/tile.c").read_text(), "Tile_AddTileDiff")
        production += "\n" + "\n".join(function(source, name) for name in (
            "Map_IsTileVisible", "Map_UpdateViewportCandidateColumns",
            "Map_ClearViewportDamage", "Map_RebaseViewportDamage",
            "Map_Update", "Map_UpdateAround"))
        harness = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#include "src/map.h"
#include "src/tile.h"
#include "src/table/tilediff.c"
#define max(a,b) ((a) > (b) ? (a) : (b))
#define BitArray_Set(a,n) ((a)[(n) >> 3] |= 1u << ((n) & 7))
#define BitArray_Test(a,n) (((a)[(n) >> 3] >> ((n) & 7)) & 1)
uint8 g_dirtyMinimap[512], g_dirtyViewport[512], g_displayedViewport[512];
uint16 g_viewportPosition, g_minimapPosition, g_dirtyViewportCount;
uint16 g_viewportDamagePosition = 0xffff, g_viewportTerrainDamage[10];
uint16 g_viewportCandidateTop;
uint32 g_viewportCandidateDamage[13], g_viewportCandidateColumns[64];
bool g_selectionRectangleNeedRepaint;
static bool direct = true;
bool Video_Atari_CursorDirect(void) { return direct; }
typedef struct Unit Unit;
static unsigned callbacks;
static bool expectMarked;
void Unit_AddToTile(Unit *unit, uint16 packed) {
    uint16 row;
    (void)unit;
    if (expectMarked && Map_ViewportCandidateMask(packed,&row) != 0)
        assert(Map_ViewportCandidateDirty(packed));
    callbacks++;
}
void Unit_RemoveFromTile(Unit *unit, uint16 packed) { Unit_AddToTile(unit,packed); }
/* PRODUCTION */
static uint32 state = 17;
static uint32 next(void) {
    state ^= state << 13; state ^= state >> 17; state ^= state << 5;
    return state;
}
static bool inside(unsigned p, unsigned origin, int left, int top, int right, int bottom) {
    int x = (int)(p & 63) - (int)(origin & 63);
    int y = (int)(p >> 6) - (int)(origin >> 6);
    return x >= left && x < right && y >= top && y < bottom;
}
static void check_mark(unsigned p, unsigned type, bool ignore) {
    static const int offsets[] = {-64,-63,1,65,64,63,-1,-65,0};
    uint8 expected[512] = {0};
    bool visible = inside(p,g_minimapPosition,0,0,15,10);
    memset(g_dirtyMinimap,0xa5,sizeof(g_dirtyMinimap));
    memset(g_dirtyViewport,0x5a,sizeof(g_dirtyViewport));
    Map_ClearViewportDamage();
    g_dirtyViewportCount = 0;
    g_selectionRectangleNeedRepaint = false;
    bool accepted = visible || ignore;
    if (accepted) {
        if (type == 0) {
            for (unsigned i = 0; i < 9; i++) BitArray_Set(expected,(p + offsets[i]) & 4095);
        } else if (type != 4 || visible) {
            BitArray_Set(expected,p);
        }
    }
    Map_Update(p,type,ignore);
    for (unsigned q = 0; q < 4096; q++) {
        bool candidate = inside(q,g_viewportDamagePosition,-1,-1,17,12);
        assert(Map_ViewportCandidateDirty(q) == (candidate && !!BitArray_Test(expected,q)));
    }
    for (unsigned row = 0; row < 10; row++) {
        uint16 terrain = 0;
        if (accepted && visible && (type == 0 || type == 4) &&
            row == (p >> 6) - (g_viewportDamagePosition >> 6))
            terrain = 1u << ((p & 63) - (g_viewportDamagePosition & 63));
        assert(g_viewportTerrainDamage[row] == terrain);
    }
    for (unsigned i = 0; i < 512; i++) {
        assert(g_dirtyMinimap[i] == 0xa5 && g_dirtyViewport[i] == 0x5a);
    }
    if (visible && (type == 0 || type == 4)) {
        unsigned count = g_dirtyViewportCount;
        Map_Update(p,type,ignore);
        assert(g_dirtyViewportCount == count);
    }
}
int main(void) {
    /* First origin zero must initialise lookups, including its clipped border. */
    g_minimapPosition = 0;
    Map_ClearViewportDamage();
    assert(g_viewportDamagePosition == 0 && g_viewportCandidateTop == 65535);
    for (unsigned x = 0; x < 64; x++)
        assert(g_viewportCandidateColumns[x] == (x < 17 ? (uint32)2 << x : 0));
    for (unsigned oy = 0; oy < 64; oy++)
        for (unsigned ox = 0; ox < 64; ox++) {
            g_minimapPosition = oy * 64 + ox;
            Map_ClearViewportDamage();
            uint32 columns[64];
            memcpy(columns,g_viewportCandidateColumns,sizeof(columns));
            for (unsigned r = 0; r < 13; r++) g_viewportCandidateDamage[r] = next() & 0x3ffff;
            Map_SetViewportDamagePosition(g_minimapPosition);
            assert(memcmp(columns,g_viewportCandidateColumns,sizeof(columns)) == 0);
            for (unsigned q = 0; q < 4096; q++) {
                int x = (int)(q & 63) - (int)ox + 1;
                int y = (int)(q >> 6) - (int)oy + 1;
                bool expected = x >= 0 && x < 18 && y >= 0 && y < 13 &&
                    (g_viewportCandidateDamage[y] & ((uint32)1 << x)) != 0;
                assert(Map_ViewportCandidateDirty(q) == expected);
                uint16 row = 65535;
                uint32 mask = Map_ViewportCandidateMask(q,&row);
                assert(mask == (x >= 0 && x < 18 && y >= 0 && y < 13 ? (uint32)1 << x : 0));
                if (mask) assert(row == y);
            }
            assert(!Map_ViewportCandidateDirty(0xffff));
            Map_ClearViewportDamage();
            assert(memcmp(columns,g_viewportCandidateColumns,sizeof(columns)) == 0);
            for (unsigned r = 0; r < 13; r++) assert(g_viewportCandidateDamage[r] == 0);
        }
    for (unsigned ox = 0; ox <= 49; ox += 7)
        for (unsigned oy = 0; oy <= 54; oy += 9) {
            g_minimapPosition = oy * 64 + ox;
            for (int y = -2; y <= 12; y++)
                for (int x = -2; x <= 17; x++) {
                    if ((int)ox+x < 0 || ox+x >= 64 || (int)oy+y < 0 || oy+y >= 64) continue;
                    unsigned p = (oy+y)*64 + ox+x;
                    for (unsigned type = 0; type <= 4; type++)
                        for (unsigned ignore = 0; ignore < 2; ignore++)
                            check_mark(p,type,ignore != 0);
                }
        }
    for (unsigned iteration = 0; iteration < 400; iteration++) {
        unsigned ox = next()%50, oy = next()%55;
        unsigned nx = next()%50, ny = next()%55;
        if (iteration < 100) {
            ox = 20; oy = 20; nx = 16 + iteration%10; ny = 16 + iteration/10;
        }
        g_minimapPosition = oy*64+ox;
        Map_ClearViewportDamage();
        uint16 terrain[10]; uint32 candidates[13];
        for (unsigned r = 0; r < 10; r++)
            terrain[r] = g_viewportTerrainDamage[r] = next() & 0x7fff;
        for (unsigned r = 0; r < 13; r++)
            candidates[r] = g_viewportCandidateDamage[r] = next() & 0x3ffff;
        for (unsigned r = 0; r < 10; r++)
            candidates[r + 1] = g_viewportCandidateDamage[r + 1] |= (uint32)terrain[r] << 1;
        Map_SetViewportDamagePosition(ny*64+nx);
        assert(g_viewportDamagePosition == ny*64+nx);
        for (int r = 0; r < 13; r++) {
            uint32 expected = 0;
            int oldRow = r + (int)ny - (int)oy;
            for (int c = 0; c < 18; c++) {
                int oldColumn = c + (int)nx - (int)ox;
                if (oldRow >= 0 && oldRow < 13 && oldColumn >= 0 && oldColumn < 18 &&
                    (candidates[oldRow] & ((uint32)1 << oldColumn)))
                    expected |= (uint32)1 << c;
            }
            assert(g_viewportCandidateDamage[r] == expected);
        }
        for (int r = 0; r < 10; r++) {
            uint16 expected = 0;
            int oldRow = r + (int)ny - (int)oy;
            for (int c = 0; c < 15; c++) {
                int oldColumn = c + (int)nx - (int)ox;
                if (oldRow >= 0 && oldRow < 10 && oldColumn >= 0 && oldColumn < 15 &&
                    (terrain[oldRow] & (1u << oldColumn))) expected |= 1u << c;
            }
            assert(g_viewportTerrainDamage[r] == expected);
        }
        g_minimapPosition = ny*64+nx;
        /* Exposed edges mark in the new origin, not the last displayed one. */
        Map_Update(g_minimapPosition+14,4,true);
        assert(g_viewportTerrainDamage[0] & (1u << 14));
        assert(Map_ViewportCandidateDirty(g_minimapPosition+14));
    }
    /* Offscreen registration still runs, independently of local candidate clipping. */
    g_minimapPosition = 20*64+20;
    for (unsigned outside = 0; outside < 2; outside++)
        for (unsigned radius = 16; radius <= 33; radius += 17)
            for (unsigned callback = 2; callback <= 3; callback++) {
                unsigned visits = 0;
                tile32 position = outside ? (tile32){0x3c80,0x3c80} :
                    (tile32){0x1480,0x1480};
                for (unsigned marked = 0; marked < 2; marked++) {
                    Map_ClearViewportDamage();
                    callbacks = g_dirtyViewportCount = 0;
                    expectMarked = marked != 0;
                    Map_UpdateAround(radius,position,NULL,callback,expectMarked);
                    assert(callbacks != 0);
                    if (!marked) visits = callbacks;
                    else assert(callbacks == visits && g_dirtyViewportCount == visits);
                    for (unsigned r = 0; r < 10; r++) assert(!g_viewportTerrainDamage[r]);
                    if (!marked || outside)
                        for (unsigned r = 0; r < 13; r++) assert(!g_viewportCandidateDamage[r]);
                }
            }
    direct = false;
    g_minimapPosition = 20*64+20;
    memset(g_dirtyMinimap,0,sizeof(g_dirtyMinimap));
    memset(g_dirtyViewport,0,sizeof(g_dirtyViewport));
    Map_Update(g_minimapPosition,0,false);
    assert(BitArray_Test(g_dirtyMinimap,g_minimapPosition));
    for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++)
        assert(BitArray_Test(g_dirtyViewport,g_minimapPosition+y*64+x));
    return 0;
}
"""
        run_harness(harness.replace("/* PRODUCTION */", production))

    def test_unchanged_origin_does_not_enter_rebaser(self):
        run_harness(r"""
#include <assert.h>
#include <stddef.h>
#include "types.h"
#include "src/map.h"
uint16 g_viewportDamagePosition = 0xffff;
static unsigned rebases;
void Map_RebaseViewportDamage(uint16 packed) {
    rebases++;
    g_viewportDamagePosition = packed;
}
int main(void) {
    Map_SetViewportDamagePosition(0);
    assert(rebases == 1);
    for (unsigned i = 0; i < 1000; i++) Map_SetViewportDamagePosition(0);
    assert(rebases == 1);
    Map_SetViewportDamagePosition(20 * 64 + 20);
    assert(rebases == 2);
    Map_SetViewportDamagePosition(20 * 64 + 20);
    assert(rebases == 2);
    return 0;
}
""")

    def test_scroll_origin_order_and_reset(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        draw = function(gui, "GUI_DrawScreen")
        self.assertLess(draw.index("Map_SetViewportDamagePosition(g_minimapPosition)"),
                        draw.index("Explosion_Tick"))
        shift = draw.index("Video_Atari_ShiftPlanar")
        rebase = draw.index("Map_SetViewportDamagePosition(g_viewportPosition)", shift)
        edge = draw.index("Map_Update(x + viewportX", rebase)
        self.assertLess(rebase, edge)
        self.assertLess(edge, draw.index("g_minimapPosition = g_viewportPosition"))
        reset = function((ROOT / "src/opendune.c").read_text(), "Game_Init")
        self.assertIn("Map_ClearViewportDamage()", reset)


if __name__ == "__main__":
    unittest.main()
