"""Exercise native sprite rejection against retained tile and foreground damage."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function
from tools.test_unit_smoke_damage import run_harness


ROOT = Path(__file__).resolve().parents[1]


class ViewportSpriteDamageTest(unittest.TestCase):
    def test_unit_footprint_cache_and_early_rejection(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        draw = function(viewport, "GUI_Widget_Viewport_Draw")
        ground = draw[draw.index("bool boundsReady"):draw.index("bodyHouse =")]
        ground = ground.replace("#ifdef TOS", "").replace("#endif", "")
        production = "\n".join(function(viewport, name) for name in (
            "GUI_Widget_Viewport_SpriteDamageRect",
            "GUI_Widget_Viewport_SpriteDamageFree",
            "GUI_Widget_Viewport_UpdateUnitBounds",
            "GUI_Widget_Viewport_UnitDamageFree",
            "GUI_Widget_Viewport_ShouldDrawSprite",
        ))
        harness = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#include "src/unit.h"
#include "src/gui/gui.h"
#include "src/gui/widget.h"
#include "src/os/endian.h"
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
static bool s_viewportSpriteFilterActive = true, s_viewportSpriteNeedsRedraw;
static uint16 s_viewportSpriteDamage[10];
WidgetProperties g_widgetProperties[22];
static uint8 images[4][5], *sprites[4];
uint8 **g_sprites = sprites;
static GUI_SpriteLayers currentLayers;
static unsigned builds;
static uint16 GUI_Widget_Viewport_GroundSprites(Unit *u, int *flags,
                                                GUI_SpriteLayers *layers, uint16 parts) {
    (void)u; (void)flags; assert(parts == UNIT_SPRITE_ALL);
    builds++;
    *layers = currentLayers;
    return 0;
}
/* PRODUCTION */
static bool candidate(Unit *u, int16 x, int16 y) {
    for (unsigned once = 0; once < 1; once++) {
        int spriteFlags;
        uint16 index;
        GUI_SpriteLayers layers;
        /* GROUND */
        return true;
    }
    return false;
}
static void dimensions(unsigned id, unsigned width, unsigned height) {
    images[id][3] = width; images[id][2] = height;
}
static void checkBox(Unit *u, int x, int y) {
    int left = x - images[0][3] / 2, top = y - images[0][2] / 2;
    int right = left + images[0][3], bottom = top + images[0][2];
    for (unsigned i = 0; i < currentLayers.count; i++) {
        GUI_SpriteLayer *layer = &currentLayers.layer[i];
        unsigned id = layer->spriteID;
        int l = x + layer->offsetX - images[id][3] / 2;
        int t = y + layer->offsetY - images[id][2] / 2;
        left = min(left,l); top = min(top,t);
        right = max(right,l + images[id][3]); bottom = max(bottom,t + images[id][2]);
    }
    x += g_widgetProperties[2].xBase << 3; y += g_widgetProperties[2].yBase;
    assert(x + u->viewportBoundsLeft == left + (g_widgetProperties[2].xBase << 3));
    assert(y + u->viewportBoundsTop == top + g_widgetProperties[2].yBase);
    assert(u->viewportBoundsWidth == right - left);
    assert(u->viewportBoundsHeight == bottom - top);
    bool expected = GUI_Widget_Viewport_SpriteDamageFree(
        left + (g_widgetProperties[2].xBase << 3), top + g_widgetProperties[2].yBase,
        right + (g_widgetProperties[2].xBase << 3), bottom + g_widgetProperties[2].yBase);
    assert(GUI_Widget_Viewport_UnitDamageFree(u,x - (g_widgetProperties[2].xBase << 3),
                                                y - g_widgetProperties[2].yBase) == expected);
}
int main(void) {
    Unit u = {0}; u.o.type = UNIT_TANK;
    for (unsigned id = 0; id < 4; id++) {
        sprites[id] = images[id]; dimensions(id,16,16);
    }
    currentLayers.count = 3;
    for (unsigned i = 0; i < 3; i++) currentLayers.layer[i].spriteID = i + 1;
    currentLayers.layer[0].offsetX = -14; currentLayers.layer[0].offsetY = 7;
    currentLayers.layer[1].offsetY = -14;
    /* Odd and even dimensions, all combinations of zero to three layers. */
    g_widgetProperties[2].xBase = 2; g_widgetProperties[2].yBase = 40;
    for (unsigned count = 0; count <= 3; count++)
    for (unsigned width = 1; width <= 32; width++)
    for (unsigned height = 1; height <= 32; height++) {
        currentLayers.count = count;
        dimensions(0,width,height);
        dimensions(1,33-width,33-height);
        GUI_Widget_Viewport_UpdateUnitBounds(&u,0,&currentLayers);
        for (int pos = -32; pos <= 240; pos += 16) {
            memset(s_viewportSpriteDamage,0,sizeof(s_viewportSpriteDamage));
            s_viewportSpriteDamage[0] = 1;
            s_viewportSpriteDamage[9] = 1u << 14;
            checkBox(&u,pos,pos - 40);
        }
    }
    g_widgetProperties[2].xBase = 0;
    dimensions(0,16,16); currentLayers.count = 0;
    memset(s_viewportSpriteDamage,0,sizeof(s_viewportSpriteDamage));
    Unit_ClearViewportKey(&u);
    assert(!u.viewportBoundsWidth);
    assert(!candidate(&u,24,8) && builds == 1 && u.viewportBoundsWidth == 16);
    /* A cached rejection skips layer construction, including after movement. */
    assert(!candidate(&u,24,8) && builds == 1);
    tile32 position = {256,256}; Unit_SetPos(&u,position); u.wobbleIndex = 3;
    assert(!candidate(&u,25,9) && builds == 1);
    s_viewportSpriteDamage[0] = 1u << 1;
    assert(candidate(&u,24,8) && builds == 2);
    /* Retained foreground publication, independently dirty units and clipping. */
    memset(s_viewportSpriteDamage,0,sizeof(s_viewportSpriteDamage));
    assert(!candidate(&u,56,8) && builds == 2);
    s_viewportSpriteNeedsRedraw = true;
    assert(GUI_Widget_Viewport_ShouldDrawSprite(40,40,64,56));
    s_viewportSpriteNeedsRedraw = false;
    assert(candidate(&u,56,8) && builds == 3);
    s_viewportSpriteNeedsRedraw = true;
    assert(candidate(&u,100,80) && builds == 4);
    s_viewportSpriteNeedsRedraw = false;
    assert(!candidate(&u,248,8) && builds == 4);
    s_viewportSpriteFilterActive = false;
    assert(candidate(&u,100,80) && builds == 5);
    s_viewportSpriteFilterActive = true;
    /* Terrain-dependent harvester layers always rebuild and remeasure. */
    u.o.type = UNIT_HARVESTER;
    memset(s_viewportSpriteDamage,0,sizeof(s_viewportSpriteDamage));
    assert(!candidate(&u,24,8) && builds == 6);
    currentLayers.count = 1;
    s_viewportSpriteDamage[0] = 1;
    assert(candidate(&u,24,8) && builds == 7);
    assert(u.viewportBoundsWidth > 16);
    currentLayers.count = 0;
    assert(!candidate(&u,24,8) && builds == 8 && u.viewportBoundsWidth == 16);
    return 0;
}
"""
        run_harness(harness.replace("/* PRODUCTION */", production).replace("/* GROUND */", ground))

    def test_damage_snapshot_and_foreground_dependencies(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        production = "\n".join(function(viewport, name) for name in (
            "GUI_Widget_Viewport_BeginSpriteDamage",
            "GUI_Widget_Viewport_SpriteDamageRect",
            "GUI_Widget_Viewport_ShouldDrawSprite",
            "GUI_Widget_Viewport_InvalidateSpriteDamage",
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
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
static bool s_viewportSpriteFilterActive, s_viewportSpriteNeedsRedraw;
static uint16 s_viewportSpriteDamage[10], g_viewportPosition;
static uint16 g_viewportTerrainDamage[10];
/* PRODUCTION */
static void tile(unsigned x, unsigned y) {
    g_viewportTerrainDamage[y] |= 1u << x;
}
static void begin(void) {
    GUI_Widget_Viewport_BeginSpriteDamage(true);
    s_viewportSpriteNeedsRedraw = false;
}
int main(void) {
    /* Every byte-alignment shift and viewport row, including the map edge. */
    for (unsigned origin = 0; origin <= 49; origin++)
        for (unsigned row = 0; row < 10; row++)
            for (unsigned col = 0; col < 15; col++) {
                memset(g_viewportTerrainDamage, 0, sizeof(g_viewportTerrainDamage));
                g_viewportPosition = (54 << 6) + origin;
                tile(col, row);
                begin();
                for (unsigned y = 0; y < 10; y++)
                    assert(s_viewportSpriteDamage[y] == (y == row ? 1u << col : 0));
                /* Live repair consumption must not remove selection damage. */
                memset(g_viewportTerrainDamage, 0, sizeof(g_viewportTerrainDamage));
                int left = col * 16, top = 40 + row * 16;
                assert(!GUI_Widget_Viewport_ShouldDrawSprite(left - 16, top, left, top + 16));
                assert(!GUI_Widget_Viewport_ShouldDrawSprite(left + 16, top, left + 32, top + 16));
                assert(!GUI_Widget_Viewport_ShouldDrawSprite(left, top - 16, left + 16, top));
                assert(!GUI_Widget_Viewport_ShouldDrawSprite(left, top + 16, left + 16, top + 32));
                assert(GUI_Widget_Viewport_ShouldDrawSprite(left + 15, top + 15, left + 16, top + 16));
            }
    g_viewportPosition = 0;
    memset(g_viewportTerrainDamage, 0, sizeof(g_viewportTerrainDamage));
    tile(1, 0);
    begin();
    /* A intersects terrain; B only intersects A's publication; C only B's.
     * No live tile bits survive the first terrain repair. */
    memset(g_viewportTerrainDamage, 0, sizeof(g_viewportTerrainDamage));
    assert(GUI_Widget_Viewport_ShouldDrawSprite(24, 40, 48, 56));
    assert(GUI_Widget_Viewport_ShouldDrawSprite(40, 40, 64, 56));
    assert(GUI_Widget_Viewport_ShouldDrawSprite(56, 40, 80, 56));
    assert(!GUI_Widget_Viewport_ShouldDrawSprite(96, 40, 112, 56));
    /* Rejection must not itself propagate foreground damage. */
    assert(!GUI_Widget_Viewport_ShouldDrawSprite(100, 40, 120, 56));
    /* Viewport-only invalidation does not imply pixels were damaged:
     * independently dirty actors still publish and propagate their writes. */
    memset(g_viewportTerrainDamage, 0, sizeof(g_viewportTerrainDamage));
    begin();
    assert(!GUI_Widget_Viewport_ShouldDrawSprite(16, 40, 32, 56));
    s_viewportSpriteNeedsRedraw = true;
    assert(GUI_Widget_Viewport_ShouldDrawSprite(16, 40, 32, 56));
    s_viewportSpriteNeedsRedraw = false;
    assert(GUI_Widget_Viewport_ShouldDrawSprite(24, 40, 48, 56));
    /* Selection-outline writes participate in the same ordering. */
    begin();
    GUI_Widget_Viewport_SpriteDamageRect(80, 60, 112, 90, true);
    assert(GUI_Widget_Viewport_ShouldDrawSprite(90, 70, 100, 80));
    assert(!GUI_Widget_Viewport_ShouldDrawSprite(144, 70, 160, 80));
    /* Clip outside the battlefield and retain its last column/row. */
    begin();
    s_viewportSpriteNeedsRedraw = true;
    assert(GUI_Widget_Viewport_ShouldDrawSprite(230, 190, 300, 250));
    assert(s_viewportSpriteDamage[9] == (1u << 14));
    s_viewportSpriteNeedsRedraw = false;
    assert(GUI_Widget_Viewport_ShouldDrawSprite(239, 199, 240, 200));
    assert(!GUI_Widget_Viewport_ShouldDrawSprite(240, 199, 241, 200));
    assert(!GUI_Widget_Viewport_ShouldDrawSprite(239, 200, 240, 201));
    /* Unexpected chunky fallback conservatively keeps all later candidates. */
    begin();
    GUI_Widget_Viewport_InvalidateSpriteDamage();
    for (unsigned y = 0; y < 10; y++) assert(s_viewportSpriteDamage[y] == 0x7fff);
    assert(GUI_Widget_Viewport_ShouldDrawSprite(0, 40, 1, 41));
    /* Forced redraw, scrolling and non-native modes disable the filter. */
    GUI_Widget_Viewport_BeginSpriteDamage(false);
    s_viewportSpriteNeedsRedraw = false;
    assert(GUI_Widget_Viewport_ShouldDrawSprite(96, 40, 112, 56));
    return 0;
}
"""
        harness = harness.replace("/* PRODUCTION */", production)
        with tempfile.TemporaryDirectory(prefix="viewport-sprite-damage-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                            "-Werror", str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_renderer_integration(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        gui = (ROOT / "src/gui/gui.c").read_text()
        draw = function(viewport, "GUI_Widget_Viewport_Draw")
        begin = draw.index("GUI_Widget_Viewport_BeginSpriteDamage")
        self.assertLess(draw.index("g_dirtyViewportCount = 0"), begin)
        self.assertLess(begin, draw.index("/* Draw Sandworm */"))
        self.assertIn("planarViewport && !forceRedraw && !hasScrolled", draw)
        self.assertEqual(draw.count(
            "s_viewportSpriteNeedsRedraw = u->o.flags.s.isDirty || forceRedraw"), 2)
        explosion = draw[draw.index("/* draw explosions */"):draw.index("/* draw air units */")]
        self.assertLess(explosion.index("s_viewportSpriteNeedsRedraw = e->isDirty"),
                        explosion.index("e->isDirty = true"))
        self.assertLess(draw.index("g_dirtyAirUnitCount = 0"),
                        draw.index("s_viewportSpriteFilterActive = false"))
        cached = function(gui, "GUI_ViewportPlanarSprite")
        self.assertLess(cached.index("GUI_Widget_Viewport_ShouldDrawSprite"),
                        cached.index("GUI_Widget_Viewport_RepairTiles"))
        dispatch = function(gui, "GUI_DrawSprite")
        self.assertNotIn("GUI_Widget_Viewport_InvalidateSpriteDamage", dispatch)
        self.assertNotIn("va_copy", dispatch)
        self.assertNotIn("return false", cached)


if __name__ == "__main__":
    unittest.main()
