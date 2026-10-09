"""Exercise native sprite rejection against retained tile and foreground damage."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class ViewportSpriteDamageTest(unittest.TestCase):
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
static uint8 g_dirtyMinimap[512];
/* PRODUCTION */
static void tile(unsigned x, unsigned y) {
    unsigned packed = g_viewportPosition + y * 64 + x;
    g_dirtyMinimap[packed >> 3] |= 1u << (packed & 7);
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
                memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
                g_viewportPosition = (54 << 6) + origin;
                tile(col, row);
                begin();
                for (unsigned y = 0; y < 10; y++)
                    assert(s_viewportSpriteDamage[y] == (y == row ? 1u << col : 0));
                /* Live repair consumption must not remove selection damage. */
                memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
                int left = col * 16, top = 40 + row * 16;
                assert(!GUI_Widget_Viewport_ShouldDrawSprite(left - 16, top, left, top + 16));
                assert(!GUI_Widget_Viewport_ShouldDrawSprite(left + 16, top, left + 32, top + 16));
                assert(!GUI_Widget_Viewport_ShouldDrawSprite(left, top - 16, left + 16, top));
                assert(!GUI_Widget_Viewport_ShouldDrawSprite(left, top + 16, left + 16, top + 32));
                assert(GUI_Widget_Viewport_ShouldDrawSprite(left + 15, top + 15, left + 16, top + 16));
            }
    g_viewportPosition = 0;
    memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
    tile(1, 0);
    begin();
    /* A intersects terrain; B only intersects A's publication; C only B's.
     * No live tile bits survive the first terrain repair. */
    memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
    assert(GUI_Widget_Viewport_ShouldDrawSprite(24, 40, 48, 56));
    assert(GUI_Widget_Viewport_ShouldDrawSprite(40, 40, 64, 56));
    assert(GUI_Widget_Viewport_ShouldDrawSprite(56, 40, 80, 56));
    assert(!GUI_Widget_Viewport_ShouldDrawSprite(96, 40, 112, 56));
    /* Rejection must not itself propagate foreground damage. */
    assert(!GUI_Widget_Viewport_ShouldDrawSprite(100, 40, 120, 56));
    /* Viewport-only invalidation does not imply pixels were damaged:
     * independently dirty actors still publish and propagate their writes. */
    memset(g_dirtyMinimap, 0, sizeof(g_dirtyMinimap));
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
        self.assertIn("GUI_Widget_Viewport_InvalidateSpriteDamage", function(gui, "GUI_DrawSprite"))


if __name__ == "__main__":
    unittest.main()
