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
    def test_composite_bounds_leave_storage_geometry_unchanged(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        cached = function(gui, "GUI_ViewportPlanarSprite")
        geometry = cached[cached.index("\t\tViewportSpriteMask *masks[4];"):
                          cached.index("\t\tfor (i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) {",
                                       cached.index("\t\tViewportSpriteMask *masks[4];"))]
        fields = cached[cached.index("\t\tentry->width = stride;"):
                        cached.index("\t\tif (key->main &")]
        mask_type = gui[gui.index("typedef struct ViewportSpriteMask {"):
                        gui.index("} ViewportSpriteMask;") + len("} ViewportSpriteMask;")]
        sprite_type = gui[gui.index("typedef struct ViewportPlanarSprite {"):
                          gui.index("} ViewportPlanarSprite;") + len("} ViewportPlanarSprite;")]
        image_type = gui[gui.index("typedef struct ViewportPlanarImage {"):
                         gui.index("} ViewportPlanarImage;") + len("} ViewportPlanarImage;")]
        harness = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#include "src/gui/viewport_key.h"
#include "src/gui/gui.h"
#include "src/video/video.h"
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
/* TYPES */
GUI_SpriteBounds g_viewportSpriteBounds[355][4];
static ViewportSpriteMask slots[355];
static uint8 images[355][10], *sprites[355];
uint8 **g_sprites = sprites;
static bool built;
static ViewportSpriteMask *GUI_ViewportSpriteMaskSlot(uint16 id) { return &slots[id]; }
static void geometry(ViewportPlanarSprite *entry, const GUI_SpriteLayers *layers,
                     int16 x, int16 y, int flags, bool blitter, bool centered) {
    ViewportSpriteMask *mask = &slots[111];
    uint16 spriteID = 111, count = layers->count, i;
    int16 centreX = centered ? mask->width / 2 : 0;
    int16 centreY = centered ? mask->height / 2 : 0;
    /* GEOMETRY */
    (void)masks; (void)groups;
    /* FIELDS */
    built = true;
}
static void shape(unsigned id, unsigned width, unsigned height,
                  unsigned l, unsigned t, unsigned r, unsigned b) {
    slots[id].sprite = sprites[id] = images[id];
    slots[id].width = images[id][3] = width;
    slots[id].height = images[id][2] = height;
    for (unsigned flags = 0; flags < 4; flags++)
        g_viewportSpriteBounds[id][flags] = (GUI_SpriteBounds){
            flags & DRAWSPRITE_FLAG_RTL ? width - r : l,
            flags & DRAWSPRITE_FLAG_BOTTOMUP ? height - b : t,
            flags & DRAWSPRITE_FLAG_RTL ? width - l : r,
            flags & DRAWSPRITE_FLAG_BOTTOMUP ? height - t : b};
}
int main(void) {
    shape(111,24,24,4,1,19,22);
    shape(112,17,15,3,2,13,12);
    shape(113,16,24,4,3,12,20);
    shape(114,16,16,1,1,15,15);
    GUI_SpriteLayers layers = {0};
    layers.layer[0] = (GUI_SpriteLayer){.spriteID=112,.offsetX=-14,.offsetY=7};
    layers.layer[1] = (GUI_SpriteLayer){.spriteID=113,.offsetY=-14};
    layers.layer[2] = (GUI_SpriteLayer){.spriteID=114};
    for (unsigned centered = 0; centered < 2; centered++)
    for (unsigned blitter = 0; blitter < 2; blitter++)
    for (unsigned phase = 0; phase < 16; phase++)
    for (int flags = 0; flags < 4; flags++)
    for (layers.count = 0; layers.count <= 3; layers.count++) {
        ViewportPlanarSprite entry = {0}; built = false;
        for (unsigned i = 0; i < 3; i++) layers.layer[i].flags = (flags + i) & 3;
        int minX=0,minY=0,maxX=24,maxY=24,l=100,t=100,r=-100,b=-100;
        for (unsigned i = 0; i <= layers.count; i++) {
            unsigned id = i ? layers.layer[i-1].spriteID : 111;
            int ox = i ? (centered ? 12 : 0) + layers.layer[i-1].offsetX - slots[id].width/2 : 0;
            int oy = i ? (centered ? 12 : 0) + layers.layer[i-1].offsetY - slots[id].height/2 : 0;
            const GUI_SpriteBounds *bounds = GUI_ViewportSpriteBounds(id,i ? layers.layer[i-1].flags : flags);
            minX=min(minX,ox); minY=min(minY,oy);
            maxX=max(maxX,ox+slots[id].width); maxY=max(maxY,oy+slots[id].height);
            l=min(l,ox+bounds->left); t=min(t,oy+bounds->top);
            r=max(r,ox+bounds->right); b=max(b,oy+bounds->bottom);
        }
        if (!blitter) minX -= (64+phase+minX)&15;
        uint8 originals[355][10]; memcpy(originals,images,sizeof(originals));
        geometry(&entry,&layers,64+phase,80,flags,blitter,centered);
        assert(built && entry.offsetX==minX && entry.offsetY==minY);
        assert(entry.width==((maxX-minX+15)&~15) && entry.height==maxY-minY);
        assert(entry.extentWidth==maxX-minX);
        assert(entry.boundsOffsetX==l && entry.boundsOffsetY==t);
        assert(entry.boundsWidth==r-l && entry.boundsHeight==b-t);
        assert(!memcmp(originals,images,sizeof(originals)));
    }
    memset(g_viewportSpriteBounds,0,sizeof(g_viewportSpriteBounds));
    layers.count = 3;
    ViewportPlanarSprite entry = {0}; built = false;
    geometry(&entry,&layers,64,80,0,true,true);
    assert(!built);
    return 0;
}
"""
        run_harness(harness.replace("/* TYPES */", mask_type + "\n" + image_type + "\n" +
                                   sprite_type + "\n" + function(gui, "GUI_ViewportSetPlanarImage"))
                    .replace("/* GEOMETRY */", geometry).replace("/* FIELDS */", fields))

    def test_unit_footprint_cache_and_early_rejection(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        draw = function(viewport, "GUI_Widget_Viewport_Draw")
        ground = draw[draw.index("bool boundsReady"):draw.index("bodyHouse =")]
        ground = ground.replace("#ifdef TOS", "").replace("#endif", "")
        ground = ground.replace("GUI_Widget_Viewport_UnitDamageFree(", "count_damage_check(")
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
GUI_SpriteBounds g_viewportSpriteBounds[355][4];
static GUI_SpriteLayers currentLayers;
static int currentFlags;
static unsigned builds, damageChecks;
static uint16 GUI_Widget_Viewport_GroundSprites(Unit *u, int *flags,
                                                GUI_SpriteLayers *layers, uint16 parts) {
    (void)u; *flags = currentFlags; assert(parts == UNIT_SPRITE_ALL);
    builds++;
    *layers = currentLayers;
    return 0;
}
/* PRODUCTION */
static bool count_damage_check(const Unit *u, int16 x, int16 y) {
    damageChecks++;
    return GUI_Widget_Viewport_UnitDamageFree(u,x,y);
}
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
    for (unsigned flags = 0; flags < 4; flags++)
        g_viewportSpriteBounds[id][flags] = (GUI_SpriteBounds){0,0,width,height};
}
static void checkBox(Unit *u, int x, int y) {
    const GUI_SpriteBounds *b = GUI_ViewportSpriteBounds(0,currentFlags);
    bool visible = b->left != b->right && b->top != b->bottom;
    int left = x - images[0][3] / 2 + b->left, top = y - images[0][2] / 2 + b->top;
    int right = x - images[0][3] / 2 + b->right, bottom = y - images[0][2] / 2 + b->bottom;
    for (unsigned i = 0; i < currentLayers.count; i++) {
        GUI_SpriteLayer *layer = &currentLayers.layer[i];
        unsigned id = layer->spriteID;
        b = GUI_ViewportSpriteBounds(id,layer->flags);
        if (b->left == b->right || b->top == b->bottom) continue;
        int l = x + layer->offsetX - images[id][3] / 2;
        int t = y + layer->offsetY - images[id][2] / 2;
        left = visible ? min(left,l + b->left) : l + b->left;
        top = visible ? min(top,t + b->top) : t + b->top;
        right = visible ? max(right,l + b->right) : l + b->right;
        bottom = visible ? max(bottom,t + b->bottom) : t + b->bottom;
        visible = true;
    }
    if (!visible) {
        assert(!u->viewportBoundsWidth && !u->viewportBoundsHeight);
        assert(GUI_Widget_Viewport_UnitDamageFree(u,x,y));
        return;
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
static void opaqueBounds(unsigned id, unsigned l, unsigned t, unsigned r, unsigned b) {
    for (unsigned flags = 0; flags < 4; flags++)
        g_viewportSpriteBounds[id][flags] = (GUI_SpriteBounds){
            flags & DRAWSPRITE_FLAG_RTL ? images[id][3] - r : l,
            flags & DRAWSPRITE_FLAG_BOTTOMUP ? images[id][2] - b : t,
            flags & DRAWSPRITE_FLAG_RTL ? images[id][3] - l : r,
            flags & DRAWSPRITE_FLAG_BOTTOMUP ? images[id][2] - t : b};
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
        GUI_Widget_Viewport_UpdateUnitBounds(&u,0,0,&currentLayers);
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
    unsigned checksBefore = damageChecks;
    assert(candidate(&u,100,80) && builds == 4);
    assert(damageChecks == checksBefore);
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
    /* Original centres are retained for asymmetric, mirrored, layered and
     * entirely transparent frames; damage admission uses only opacity. */
    dimensions(0,24,24); opaqueBounds(0,4,1,19,22);
    dimensions(1,17,15); opaqueBounds(1,3,2,13,12);
    dimensions(2,16,24); opaqueBounds(2,4,3,12,20);
    dimensions(3,16,16); opaqueBounds(3,1,1,15,15);
    for (currentFlags = 0; currentFlags < 4; currentFlags++)
    for (unsigned count = 0; count <= 3; count++)
    for (unsigned layerFlags = 0; layerFlags < 4; layerFlags++) {
        currentLayers.count = count;
        for (unsigned i = 0; i < 3; i++) currentLayers.layer[i].flags = layerFlags;
        GUI_Widget_Viewport_UpdateUnitBounds(&u,0,currentFlags,&currentLayers);
        for (unsigned px = 0; px < 16; px++) for (unsigned py = 0; py < 16; py++) {
            memset(s_viewportSpriteDamage,0,sizeof(s_viewportSpriteDamage));
            s_viewportSpriteDamage[2] = 1u << (px % 8);
            checkBox(&u,64 + px,32 + py);
        }
    }
    memset(g_viewportSpriteBounds[0],0,sizeof(g_viewportSpriteBounds[0]));
    for (unsigned count = 0; count <= 3; count++) {
        currentLayers.count = count;
        GUI_Widget_Viewport_UpdateUnitBounds(&u,0,0,&currentLayers);
        currentFlags = 0;
        checkBox(&u,24,8);
    }
    memset(g_viewportSpriteBounds,0,sizeof(g_viewportSpriteBounds));
    GUI_Widget_Viewport_UpdateUnitBounds(&u,0,0,&currentLayers);
    checkBox(&u,24,8);
    /* Required redraws bypass damage checks after rebuilding bounds too,
     * but entirely transparent frames still must be rejected. */
    s_viewportSpriteNeedsRedraw = true;
    currentLayers.count = 0;
    currentFlags = 0;
    for (unsigned harvester = 0; harvester < 2; harvester++)
    for (unsigned visible = 0; visible < 2; visible++) {
        u.o.type = harvester ? UNIT_HARVESTER : UNIT_TANK;
        Unit_ClearViewportKey(&u);
        dimensions(0,16,16);
        if (!visible) memset(g_viewportSpriteBounds[0],0,sizeof(g_viewportSpriteBounds[0]));
        checksBefore = damageChecks;
        assert(candidate(&u,24,8) == (visible != 0));
        assert(damageChecks == checksBefore);
        assert((u.viewportBoundsWidth != 0) == (visible != 0));
    }
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
            "GUI_Widget_Viewport_SpriteRepairMask",
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
    /* A repairs only its damaged tile. B/C must not be recruited by the
     * undamaged part of A's bounding rectangle. */
    memset(g_viewportTerrainDamage, 0, sizeof(g_viewportTerrainDamage));
    assert(GUI_Widget_Viewport_ShouldDrawSprite(24, 40, 48, 56));
    assert(GUI_Widget_Viewport_SpriteRepairMask() == s_viewportSpriteDamage);
    assert(s_viewportSpriteDamage[0] == (1u << 1));
    assert(!GUI_Widget_Viewport_ShouldDrawSprite(40, 40, 64, 56));
    assert(!GUI_Widget_Viewport_ShouldDrawSprite(56, 40, 80, 56));
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
    assert(GUI_Widget_Viewport_SpriteRepairMask() == NULL);
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
    assert(GUI_Widget_Viewport_SpriteRepairMask() == NULL);
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
        publication = function(gui, "GUI_ViewportPresentPlanarSprite")
        self.assertLess(publication.index("GUI_Widget_Viewport_ShouldDrawSprite"),
                        publication.index("GUI_Widget_Viewport_RepairTiles"))
        dispatch = function(gui, "GUI_DrawSprite")
        self.assertNotIn("GUI_Widget_Viewport_InvalidateSpriteDamage", dispatch)
        self.assertNotIn("va_copy", dispatch)
        self.assertNotIn("return false", cached)


if __name__ == "__main__":
    unittest.main()
