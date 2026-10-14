"""Check repair-on-first-touch and its viewport publication boundaries."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

from test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class ViewportPhaseReversalTest(unittest.TestCase):
    def test_sandworm_reserved_slots(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        start = viewport.index("\t/* Draw Sandworm */")
        worm = viewport[start:viewport.index("\n\tif (g_unitSelected == NULL", start)]
        pool = (ROOT / "src/pool/unit.c").read_text()
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef struct {
    struct {
        struct { struct { bool used, isNotOnMap, isDirty; } s; } flags;
        uint16 type, position, houseID;
    } o;
    uint16 targetLast, targetPreLast;
} Unit;
typedef struct { uint16 type, index, houseID; } PoolFindStruct;
#define UNIT_SANDWORM 25
#define UNIT_INDEX_INVALID 0xffff
#define HOUSE_INVALID 0xffff
#define SCREEN_ACTIVE 0
#define GUI_SPRITE_COLOUR_EMBEDDED 0
#define DRAWSPRITE_FLAG_BLUR 1
#define DRAWSPRITE_FLAG_WIDGETPOS 2
#define DRAWSPRITE_FLAG_CENTER 4
static Unit units[102], *g_unitSelected;
static struct { uint16 indexStart, indexEnd, groundSpriteID; } g_table_unitInfo[27] = {
    [UNIT_SANDWORM] = {16, 17, 111}
};
static struct { bool isUnveiled; } g_map[4096];
static uint8 pixels[112], *g_sprites[112];
static bool g_debugScenario, visible[4096];
static uint16 g_validateStrictIfZero;
static unsigned peeks, draws, checks;
static uint16 drawn[8], checked[8];
static Unit *Unit_Get_ByIndex(uint16 index) {
    assert(index == 16 || index == 17);
    peeks++;
    return &units[index];
}
static uint16 Unit_GetHouseID(Unit *u) { return u->o.houseID; }
#ifndef TOS
static Unit *g_unitFindArray[102];
static uint16 g_unitFindCount;
/* FIND */
#endif
static uint16 Tile_PackTile(uint16 position) { return position; }
static void GUI_Widget_Viewport_GetSprite_HousePalette(uint16 id, uint16 house, uint8 *palette) {
    assert(id == 111 && house == 0);
    (void)palette;
}
static bool Map_IsPositionInViewport(uint16 position, uint16 *x, uint16 *y) {
    assert(checks < 8);
    checked[checks++] = position;
    *x = position; *y = 0;
    return visible[position];
}
static void GUI_DrawSprite(int screen, uint8 *sprite, uint16 id, int colour,
                           uint16 x, uint16 y, int widget, int flags) {
    assert(screen == 0 && sprite == g_sprites[id] && colour == 0 && y == 0 && widget == 2);
    assert(flags == (id == 6 ? 6 : 7));
    assert(draws < 8);
    drawn[draws++] = id == 6 ? 1000 + x : x;
}
static void draw(bool forceRedraw) {
    uint16 i = 0, x, y;
    PoolFindStruct find = {0};
    uint8 paletteHouse[16] = {0};
    (void)i; (void)find;
    /* WORM */
}
static void reset(void) {
    memset(units, 0, sizeof(units));
    memset(g_map, 0, sizeof(g_map));
    memset(visible, 0, sizeof(visible));
    peeks = draws = checks = 0;
    g_debugScenario = false;
    g_validateStrictIfZero = 0;
    g_unitSelected = NULL;
    for (unsigned i = 0; i < 112; i++) g_sprites[i] = &pixels[i];
    for (unsigned i = 16; i <= 17; i++) {
        Unit *u = &units[i];
        u->o.type = UNIT_SANDWORM;
        u->o.position = i;
        u->targetLast = i + 100;
        u->targetPreLast = i + 200;
        g_map[i].isUnveiled = true;
        visible[i] = visible[i + 100] = visible[i + 200] = true;
    }
#ifndef TOS
    g_unitFindCount = 0;
#endif
}
static void activate(unsigned i) {
    units[i].o.flags.s.used = true;
    units[i].o.flags.s.isDirty = true;
#ifndef TOS
    g_unitFindArray[g_unitFindCount++] = &units[i];
#endif
}
int main(void) {
    reset();
    draw(true);
    assert(!draws && !checks);
#ifdef TOS
    assert(peeks == 2);
#else
    assert(!peeks);
#endif
    /* Empty/wrong-type/off-map slots must not consume dirty flags. */
    reset();
    activate(16); activate(17);
    units[16].o.type = 0;
    units[17].o.flags.s.isNotOnMap = true;
    draw(true);
    assert(!draws && !checks);
    assert(units[16].o.flags.s.isDirty && units[17].o.flags.s.isDirty);
    /* Both worms, three positions each, plus selection; stable slot order on TOS. */
    reset();
    activate(17); activate(16);
    g_unitSelected = &units[17];
    draw(false);
    assert(draws == 7 && checks == 7);
    assert(!units[16].o.flags.s.isDirty && !units[17].o.flags.s.isDirty);
#ifdef TOS
    assert(peeks == 2);
    assert(drawn[0] == 16 && drawn[1] == 116 && drawn[2] == 216);
    assert(drawn[3] == 17 && drawn[6] == 1017);
#else
    assert(!peeks);
    assert(drawn[0] == 17 && drawn[3] == 1017 && drawn[4] == 16);
#endif
    /* Clean worm, forced redraw, fog and debug fog override. */
    reset(); activate(16);
    units[16].o.flags.s.isDirty = false;
    draw(false);
    assert(!draws && !checks);
    draw(true);
    assert(draws == 3);
    reset(); activate(16);
    g_map[16].isUnveiled = false;
    draw(false);
    assert(!draws && !checks && !units[16].o.flags.s.isDirty);
    g_debugScenario = true;
    draw(true);
    assert(draws == 3);
    /* A trailing position can be visible while the current position is outside. */
    reset(); activate(16);
    visible[16] = visible[216] = false;
    draw(false);
    assert(draws == 1 && drawn[0] == 116 && checks == 3);
    /* Match Unit_Find's strict-validation exception for off-map units. */
    reset(); activate(17);
    units[17].o.flags.s.isNotOnMap = true;
    g_validateStrictIfZero = 1;
    draw(false);
    assert(draws == 3 && !units[17].o.flags.s.isDirty);
    return 0;
}
"""
        harness = harness.replace("/* WORM */", worm)
        harness = harness.replace("/* FIND */", function(pool, "Unit_Find"))
        with tempfile.TemporaryDirectory(prefix="viewport-worm-slots-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            for platform in ([], ["-DTOS"]):
                subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                                "-Werror", "-Wno-unused-function", *flags, *platform,
                                str(source), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)

    def test_hidden_tile_damage_gate(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        start = viewport.index("\tif (g_dirtyViewportCount != 0 || forceRedraw) {")
        terrain = viewport[start:viewport.index(
            "\n#ifdef TOS\n\tGUI_Widget_Viewport_BeginSpriteDamage", start)]
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
typedef int16_t int16;
typedef struct { uint16 groundTileID, overlayTileID; uint8 houseID; } Tile;
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
#define ICM_ICONGROUP_FOG_OF_WAR 1
static Tile g_map[4096];
static uint8 g_dirtyViewport[512], g_dirtyMinimap[512], screen[200][320];
static uint16 g_dirtyViewportCount, g_viewportPosition, g_veiledTileID = 98;
static uint16 g_iconMap[32] = {[1] = 16, [31] = 99};
static bool g_debugScenario, s_viewportRepairActive;
static unsigned fogDraws, groundDraws, partialDraws, filledDraws;
static bool BitArray_Test(const uint8 *a, uint16 i) { return (a[i >> 3] >> (i & 7)) & 1; }
static void BitArray_Set(uint8 *a, uint16 i) { a[i >> 3] |= 1u << (i & 7); }
static void BitArray_Clear(uint8 *a, uint16 i) { a[i >> 3] &= ~(1u << (i & 7)); }
static uint16 Tile_PackXY(uint16 x, uint16 y) { return y * 64 + x; }
static bool Tile_IsUnveiled(uint16 tile) { return tile != 97; }
static void paint(uint16 x, uint16 y, uint8 c) {
    for (unsigned row = y; row < y + 16; row++) memset(screen[row] + x, c, 16);
}
static void GFX_DrawTile(uint16 tile, uint16 x, uint16 y, uint8 house) {
    (void)house; groundDraws++; paint(x, y, tile);
}
static void GFX_DrawPlanarTile(uint16 tile, uint16 x, uint16 y, uint8 house) {
    assert(!BitArray_Test(g_dirtyMinimap, g_viewportPosition + Tile_PackXY(x >> 4, (y - 40) >> 4)));
    GFX_DrawTile(tile, x, y, house);
}
static void GFX_DrawPlanarTileFogged(uint16 tile, uint16 fog, uint16 x, uint16 y, uint8 house) {
    assert(fog == 97);
    (void)house; partialDraws++;
    for (unsigned row = y; row < y + 16; row++)
        for (unsigned col = x; col < x + 16; col++) screen[row][col] = col & 1 ? 12 : tile;
}
static void GFX_DrawPlanarFogTile(uint16 x, uint16 y) {
    assert(!BitArray_Test(g_dirtyMinimap, g_viewportPosition + Tile_PackXY(x >> 4, (y - 40) >> 4)));
    fogDraws++; paint(x, y, 12);
}
static void GUI_DrawFilledRectangle(uint16 l, uint16 t, uint16 r, uint16 b, uint8 c) {
    assert(r == l + 15 && b == t + 15 && c == 12);
    filledDraws++; paint(l, t, c);
}
/* REPAIR */
static bool scan(bool planarViewport, bool forceRedraw) {
    bool drawToMainScreen = true, updateDisplay = forceRedraw;
    uint16 x, y, curPos, fullyFoggedTileID = 99;
    int minX[10], maxX[10];
    uint16 dirtyColumns[10] = {0};
    for (y = 0; y < 10; y++) { minX[y] = 15; maxX[y] = 0; }
    s_viewportRepairActive = planarViewport;
    /* TERRAIN */
    return updateDisplay;
}
static void reset(void) {
    memset(g_dirtyViewport, 0, sizeof(g_dirtyViewport));
    memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
    memset(g_map, 0, sizeof(g_map));
    memset(screen, 88, sizeof(screen));
    g_dirtyViewportCount = 1;
    fogDraws = groundDraws = partialDraws = filledDraws = 0;
}
int main(void) {
    for (unsigned planar = 0; planar < 2; planar++)
        for (unsigned dirty = 0; dirty < 4; dirty++)
            for (unsigned tile = 0; tile < 4; tile++)
                for (unsigned debug = 0; debug < 2; debug++) {
                    reset();
                    g_map[0].groundTileID = 7;
                    g_map[0].overlayTileID = tile == 0 ? 0 : tile == 1 ? 97 : tile == 2 ? 98 : 99;
                    g_debugScenario = debug != 0;
                    if (dirty & 1) BitArray_Set(g_dirtyViewport, 0);
                    if (dirty & 2) BitArray_Set(g_dirtyMinimap, 0);
                    bool updated = scan(planar != 0, false);
                    bool hidden = tile >= 2 && !debug;
                    bool restored = (dirty & 2) || (planar && hidden && (dirty & 1));
                    assert(updated == (dirty != 0));
                    if (planar) {
                        assert(!fogDraws && !groundDraws && !partialDraws && !filledDraws);
                        assert(BitArray_Test(g_dirtyMinimap, 0) == restored);
                        GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
                    }
                    assert(fogDraws == (restored && hidden && planar));
                    assert(filledDraws == (restored && hidden && !planar));
                    assert(partialDraws == (restored && planar && tile == 1 && !debug));
                    assert(groundDraws == (restored && !hidden && !partialDraws ?
                        1u + (tile != 0 && !debug) : 0u));
                    assert(BitArray_Test(g_dirtyViewport, 0) == ((dirty & 1) != 0 || restored));
                    assert(!g_dirtyViewportCount);
                }
    reset();
    g_debugScenario = false;
    g_map[0].overlayTileID = 98;
    assert(scan(true, true));
    GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
    assert(fogDraws == 1 && groundDraws == 149 && !filledDraws);
    /* Old sprite pixels in both hidden tiles; only viewport footprint damage. */
    reset();
    g_map[0].overlayTileID = 98;
    g_map[1].overlayTileID = 99;
    BitArray_Set(g_dirtyViewport, 0);
    BitArray_Set(g_dirtyViewport, 1);
    assert(scan(true, false));
    GUI_Widget_Viewport_RepairTiles(0, 40, 16, 56);
    screen[45][3] = 5; /* Current foreground after its background repair. */
    GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
    assert(fogDraws == 2 && screen[45][3] == 5 && screen[45][20] == 12);
    assert(screen[45][35] == 88); /* Undamaged hidden/visible neighbours stay untouched. */
    GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
    assert(fogDraws == 2 && screen[45][3] == 5);
    /* A moving unit crosses hidden, dithered and unveiled terrain. */
    reset();
    g_map[0].overlayTileID = 98;
    g_map[1].groundTileID = g_map[2].groundTileID = 7;
    g_map[1].overlayTileID = 97;
    BitArray_Set(g_dirtyViewport, 0);
    BitArray_Set(g_dirtyMinimap, 1);
    BitArray_Set(g_dirtyMinimap, 2);
    assert(scan(true, false));
    GUI_Widget_Viewport_RepairTiles(20, 45, 38, 46);
    memset(screen[45] + 20, 5, 18);
    GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
    assert(fogDraws == 1 && partialDraws == 1 && groundDraws == 1);
    assert(screen[45][3] == 12 && screen[45][16] == 7 && screen[45][17] == 12);
    assert(screen[45][20] == 5 && screen[45][37] == 5 && screen[45][38] == 7);
    GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
    assert(fogDraws == 1 && partialDraws == 1 && groundDraws == 1 && screen[45][20] == 5);
    return 0;
}
"""
        harness = harness.replace("/* TERRAIN */", terrain)
        harness = harness.replace("/* REPAIR */", function(viewport, "GUI_Widget_Viewport_RepairTiles"))
        with tempfile.TemporaryDirectory(prefix="viewport-fog-damage-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            subprocess.run([*compiler, "-std=c99", "-O2", "-DTOS",
                            "-DGFX_STORE_DIRTY_AREA_BLOCKS", *flags,
                            str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_aircraft_shadow_and_readiness_policy(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        eligibility = function(viewport, "GUI_Widget_Viewport_CanDrawPlanar")
        shadow_gate = re.search(r"if \(ui->o.flags.hasShadow.*?\) \{", viewport, re.S).group()
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
typedef uint16_t uint16;
typedef struct {
    struct { struct { bool blurTile, hasShadow; } flags; } o;
    uint16 groundSpriteID, destroyedSpriteID, turretSpriteID;
} UnitInfo;
static bool draws_shadow(bool shadow, bool directViewport) {
    UnitInfo info = {0};
    const UnitInfo *ui = &info;
    info.o.flags.hasShadow = shadow;
    (void)directViewport;
    /* SHADOW GATE */
        return true;
    }
    return false;
}
#ifdef TOS
static bool direct, tilesReady, spritesReady;
static bool Video_Atari_CursorDirect(void) { return direct; }
static bool GFX_PlanarTilesReady(void) { return tilesReady; }
static bool GUI_ViewportSpriteCacheReady(void) { return spritesReady; }
/* ELIGIBILITY */
#endif
int main(void) {
    assert(!draws_shadow(false, false));
    assert(!draws_shadow(false, true));
    assert(draws_shadow(true, false));
#ifdef TOS
    assert(!draws_shadow(true, true));
    /* No actor APIs are supplied: eligibility must only inspect readiness. */
    for (unsigned state = 0; state < 8; state++) {
        direct = (state & 1) != 0;
        tilesReady = (state & 2) != 0;
        spritesReady = (state & 4) != 0;
        assert(GUI_Widget_Viewport_CanDrawPlanar() == (state == 7));
    }
#else
    assert(draws_shadow(true, true));
#endif
    return 0;
}
"""
        harness = harness.replace("/* SHADOW GATE */", shadow_gate)
        harness = harness.replace("/* ELIGIBILITY */", eligibility)
        with tempfile.TemporaryDirectory(prefix="viewport-aircraft-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            for platform in ([], ["-DTOS"]):
                subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                                "-Werror", *flags, *platform, str(source), "-o", str(binary)],
                               check=True)
                subprocess.run([str(binary)], check=True)

    def test_stock_actor_sprite_cache_coverage(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        cache = function(gui, "GUI_InitViewportSpriteCache")
        bounds = re.search(
            r"for \(id = (\d+); id <= (\d+); id = id == (\d+) \? (\d+) : id \+ 1\)",
            cache,
        )
        self.assertIsNotNone(bounds)
        special, last, selector, first = map(int, bounds.groups())
        self.assertEqual(special, selector)
        prepared = {special, *range(first, last + 1)}
        units = (ROOT / "src/table/unitinfo.c").read_text()
        entries = re.findall(
            r'/\* name\s+\*/ "([^"]+)",.*?'
            r'/\* groundSpriteID\s+\*/ (\d+),\s*'
            r'/\* turretSpriteID\s+\*/ (-?\d+),.*?'
            r'/\* displayMode\s+\*/ (\w+),\s*'
            r'/\* destroyedSpriteID\s+\*/ (\d+)', units, re.S,
        )
        self.assertEqual(len(entries), len(re.findall(r"/\* name\s+\*/", units)))
        self.assertGreater(len(entries), 0)
        for name, body, turret, mode, destroyed in entries:
            with self.subTest(unit=name):
                body, turret, destroyed = map(int, (body, turret, destroyed))
                if mode == "DISPLAYMODE_INFANTRY_4_FRAMES":
                    offsets = range(12)
                elif mode == "DISPLAYMODE_INFANTRY_3_FRAMES":
                    offsets = range(9)
                elif mode == "DISPLAYMODE_ORNITHOPTER":
                    offsets = range(9)
                elif mode == "DISPLAYMODE_ROCKET":
                    offsets = range(10)
                elif mode == "DISPLAYMODE_UNIT":
                    offsets = range(6)
                else:
                    offsets = range(2)
                self.assertTrue({body + i for i in offsets} <= prepared)
                if turret != -1:
                    self.assertTrue({turret + i for i in range(5)} <= prepared)
                if destroyed:
                    # spriteOffset is signed 8-bit; cover every negative value.
                    self.assertTrue({destroyed - i - 1 for i in range(-128, 0)} <= prepared)
        explosions = (ROOT / "src/table/explosion.c").read_text()
        frames = set(map(int, re.findall(
            r"\{\s*EXPLOSION_SET_SPRITE\s*,\s*(\d+)\s*\}", explosions,
        )))
        self.assertGreater(len(frames), 0)
        self.assertTrue(frames <= prepared)

    def test_pending_tile_repair(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int16_t int16;
typedef uint32_t uint32;
typedef struct { uint16 groundTileID, overlayTileID; uint8 houseID; } Tile;
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
#define ICM_ICONGROUP_FOG_OF_WAR 1
static bool s_viewportRepairActive, g_debugScenario;
static uint16 g_viewportPosition, g_veiledTileID = 98, g_iconMap[32];
static uint8 g_dirtyMinimap[512], g_dirtyViewport[512];
static Tile g_map[4096];
static uint8 screen[200][320], expected[200][320];
static unsigned repaired[150], fogged, filled, draws;
static bool BitArray_Test(const uint8 *bits, uint16 p) { return (bits[p >> 3] >> (p & 7)) & 1; }
static void BitArray_Set(uint8 *bits, uint16 p) { bits[p >> 3] |= 1u << (p & 7); }
static void BitArray_Clear(uint8 *bits, uint16 p) { bits[p >> 3] &= ~(1u << (p & 7)); }
static uint16 Tile_PackXY(uint16 x, uint16 y) { return x + 64 * y; }
static bool Tile_IsUnveiled(uint16 tile) { return tile != 97; }
static void tile(uint16 x, uint16 y, uint8 colour) {
    assert(!(x & 15) && x < 240 && y >= 40 && !((y - 40) & 15) && y < 200);
    uint16 packed = g_viewportPosition + Tile_PackXY(x >> 4, (y - 40) >> 4);
    assert(!BitArray_Test(g_dirtyMinimap, packed));
    for (uint16 row = y; row < y + 16; row++) memset(screen[row] + x, colour, 16);
    draws++;
}
static void GFX_DrawPlanarTile(uint16 id, uint16 x, uint16 y, uint8 house) {
    assert(house == 0);
    if (id == 7) assert(++repaired[(y - 40) / 16 * 15 + x / 16] == 1);
    tile(x, y, id);
}
static void GFX_DrawPlanarTileFogged(uint16 id, uint16 overlay, uint16 x, uint16 y, uint8 house) {
    assert(id == 7 && overlay == 97 && house == 0);
    fogged++;
    tile(x, y, overlay);
}
static void GFX_DrawPlanarFogTile(uint16 x, uint16 y) {
    filled++;
    tile(x, y, 12);
}
/* REPAIR */
static void reset(void) {
    memset(screen, 88, sizeof(screen));
    memset(expected, 7, sizeof(expected));
    memset(repaired, 0, sizeof(repaired));
    memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
    memset(g_dirtyViewport, 0xff, sizeof(g_dirtyViewport));
    memset(g_map, 0, sizeof(g_map));
    g_viewportPosition = Tile_PackXY(19, 23);
    g_iconMap[1] = 16; g_iconMap[31] = 99;
    s_viewportRepairActive = true;
    g_debugScenario = false;
    fogged = filled = draws = 0;
    for (unsigned y = 0; y < 10; y++) for (unsigned x = 0; x < 15; x++) {
        uint16 p = g_viewportPosition + Tile_PackXY(x, y);
        g_map[p].groundTileID = 7;
        BitArray_Set(g_dirtyMinimap, p);
    }
}
static void sprite(int16 l, int16 t, int16 r, int16 b, uint8 colour) {
    GUI_Widget_Viewport_RepairTiles(l, t, r, b);
    for (int y = max(t, 40); y < min(b, 200); y++)
        for (int x = max(l, 0); x < min(r, 240); x++)
            if ((x + y + colour) % 3) screen[y][x] = expected[y][x] = colour;
}
static void compare(void) {
    GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
    assert(draws == 150);
    for (unsigned y = 0; y < 200; y++) for (unsigned x = 0; x < 320; x++) {
        if (y >= 40 && x < 240) assert(screen[y][x] == expected[y][x]);
        else assert(screen[y][x] == 88);
    }
    for (unsigned i = 0; i < 512; i++) assert(g_dirtyViewport[i] == 0xff);
    GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
    assert(draws == 150);
}
int main(void) {
    reset();
    s_viewportRepairActive = false;
    GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
    assert(draws == 0);
    s_viewportRepairActive = true;
    GUI_Widget_Viewport_RepairTiles(-32, -32, 0, 40);
    GUI_Widget_Viewport_RepairTiles(240, 200, 300, 220);
    GUI_Widget_Viewport_RepairTiles(20, 60, 20, 80);
    assert(draws == 0);
    /* Clipped sprites, overlapping painter layers and selection bounds. */
    sprite(-17, 25, 17, 57, 2);
    assert(draws == 4);
    sprite(15, 40, 49, 73, 3);
    assert(draws == 12);
    sprite(25, 51, 71, 93, 4);
    sprite(0, 39, 241, 41, 15);
    sprite(231, 187, 265, 218, 5);
    compare();
    /* Every viewport edge and tile boundary, with transparent sprite holes. */
    for (int y = 24; y <= 200; y += 16) for (int x = -16; x <= 240; x += 16) {
        reset();
        sprite(x - 1, y - 1, x + 17, y + 17, 2);
        sprite(x + 3, y + 3, x + 20, y + 20, 3);
        compare();
    }
    reset();
    uint16 p = g_viewportPosition;
    memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
    BitArray_Set(g_dirtyMinimap, p);
    g_map[p].overlayTileID = 97;
    GUI_Widget_Viewport_RepairTiles(0, 40, 16, 56);
    assert(fogged == 1 && screen[40][0] == 97);
    BitArray_Set(g_dirtyMinimap, p);
    g_map[p].overlayTileID = 98;
    GUI_Widget_Viewport_RepairTiles(0, 40, 16, 56);
    assert(filled == 1 && screen[40][0] == 12 && !BitArray_Test(g_dirtyMinimap, p));
    for (unsigned id = 98; id <= 99; id++) {
        BitArray_Set(g_dirtyMinimap, p);
        g_map[p].overlayTileID = id;
        GUI_Widget_Viewport_RepairTiles(0, 40, 16, 56);
        assert(screen[40][0] == 12);
    }
    assert(filled == 3);
    reset();
    memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
    BitArray_Set(g_dirtyMinimap, g_viewportPosition);
    g_map[g_viewportPosition].overlayTileID = 9;
    GUI_Widget_Viewport_RepairTiles(0, 40, 16, 56);
    assert(draws == 2 && screen[40][0] == 9);
    reset();
    g_debugScenario = true;
    g_map[g_viewportPosition].overlayTileID = 98;
    GUI_Widget_Viewport_RepairTiles(0, 40, 16, 56);
    assert(draws == 1 && screen[40][0] == 7);
    /* Every byte alignment, including the bottom-right two-byte range. */
    for (unsigned origin = 0; origin <= 49; origin++) {
        reset();
        g_viewportPosition = Tile_PackXY(origin, 54);
        memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
        for (unsigned row = 0; row < 10; row++) for (unsigned col = 0; col < 15; col++)
            g_map[g_viewportPosition + Tile_PackXY(col, row)].groundTileID = 7;
        GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
        assert(draws == 0);
        uint16 rowBase = g_viewportPosition + Tile_PackXY(0, 9);
        BitArray_Set(g_dirtyMinimap, rowBase + 2);
        BitArray_Set(g_dirtyMinimap, rowBase + 7);
        BitArray_Set(g_dirtyMinimap, rowBase + 14);
        if (origin != 0) BitArray_Set(g_dirtyMinimap, rowBase - 1);
        if (origin < 49) BitArray_Set(g_dirtyMinimap, rowBase + 15);
        /* Restrict repair to columns 1-3; leave the other set bits intact. */
        GUI_Widget_Viewport_RepairTiles(16, 184, 64, 200);
        assert(draws == 1 && screen[184][32] == 7);
        assert(!BitArray_Test(g_dirtyMinimap, rowBase + 2));
        assert(BitArray_Test(g_dirtyMinimap, rowBase + 7));
        assert(BitArray_Test(g_dirtyMinimap, rowBase + 14));
        GUI_Widget_Viewport_RepairTiles(16, 184, 64, 200);
        assert(draws == 1);
        GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
        assert(draws == 3 && screen[184][112] == 7 && screen[184][224] == 7);
        if (origin != 0) assert(BitArray_Test(g_dirtyMinimap, rowBase - 1));
        if (origin < 49) assert(BitArray_Test(g_dirtyMinimap, rowBase + 15));
        GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);
        assert(draws == 3);
    }
    return 0;
}
"""
        harness = harness.replace(
            "/* REPAIR */", function(viewport, "GUI_Widget_Viewport_RepairTiles"))
        with tempfile.TemporaryDirectory(prefix="viewport-phase-reversal-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                            "-Werror", str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_publication_order(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        gui = (ROOT / "src/gui/gui.c").read_text()
        gfx = (ROOT / "src/gfx.c").read_text()
        video = (ROOT / "src/video/video_atari.c").read_text()
        self.assertNotIn("GFX_QueueViewportTile", gfx)
        self.assertNotIn("GFX_ViewportSpriteMasks", gfx)
        self.assertNotIn("Video_Atari_RestorePlanarTile", video)
        draw = function(viewport, "GUI_Widget_Viewport_Draw")
        deferred = draw.index("BitArray_Set(g_dirtyMinimap, curPos);")
        self.assertIn("if (planarViewport)", draw[deferred - 40:deferred])
        self.assertIn("continue;", draw[deferred:deferred + 90])
        self.assertLess(deferred, draw.index("/* Draw Sandworm */"))
        self.assertLess(draw.index("GUI_Widget_Viewport_RepairTiles((int16)x1"),
                        draw.index("GUI_DrawWiredRectangle"))
        finish = draw.index("GUI_Widget_Viewport_RepairTiles(0, 40, 240, 200);")
        self.assertLess(draw.index("/* draw explosions */"), finish)
        self.assertLess(finish, draw.index("s_viewportRepairActive = false;"))
        self.assertLess(finish, draw.index("/* draw air units */"))
        self.assertLess(draw.index("/* draw air units */"),
                        draw.index("memset(g_dirtyViewport"))
        cached = function(gui, "GUI_ViewportPlanarSprite")
        repair = cached.index("GUI_Widget_Viewport_RepairTiles",
                              cached.index("for (i = 0; i < entry->width; i += 16)"))
        self.assertIn("column, row, column + 16, end", cached[repair:repair + 100])
        self.assertLess(cached.index("for (i = 0; i < entry->width; i += 16)"), repair)
        self.assertLess(cached.index("for (row = firstRow; row < bottom; )"), repair)
        self.assertLess(repair, cached.index("Video_Atari_PresentPlanarSpriteStrided"))
        self.assertIn("entry->masks + offset, 16, end - row, column, row, entry->width", cached)
        fallback = function(gui, "GUI_DrawSpriteInternal")
        hook = "GUI_Widget_Viewport_RepairTiles(screenX, screenY,"
        self.assertEqual(fallback.count(hook), 1)
        repair = fallback.index(hook)
        self.assertLess(fallback.index("viewportMasks[line * groups + group] ="), repair)
        self.assertIn("screenY + spriteHeightDraw", fallback[repair:repair + 170])
        self.assertLess(repair, fallback.index("Video_Atari_PresentSprite("))


if __name__ == "__main__":
    unittest.main()
