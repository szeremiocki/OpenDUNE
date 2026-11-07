"""Exercise resident projectile/impact construction, lookup and cache lifetime."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_unit_smoke_damage import run_harness
from tools.test_viewport_sprite_cache import function, inactive_display_list, rocket_directions


ROOT = Path(__file__).resolve().parents[1]


class ViewportProjectileTest(unittest.TestCase):
    def harness(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        video = (ROOT / "src/video/video_atari.c").read_text()
        mask_type = gui[gui.index("typedef struct ViewportSpriteMask {"):
                        gui.index("enum { VIEWPORT_PLANAR_SPRITES")]
        cache = gui[gui.index("enum { VIEWPORT_PLANAR_SPRITES"):
                    gui.index("\nvoid GUI_FreeViewportSpriteCache")]
        directions = rocket_directions(viewport)
        cached = function(gui, "GUI_ViewportPlanarSprite")
        admission = cached[:cached.index("\tif (key == NULL)")] + """
    (void)entry; (void)position; (void)temporary; (void)palette; (void)key;
    fallthroughs++;
    return;
""" + cached[cached.index("\npresent:"):]
        functions = inactive_display_list() + "\n".join(function(gui, name) for name in (
            "GUI_FreeViewportSpriteCache", "GUI_ViewportSpriteMaskSlot",
            "GUI_InitViewportSpriteCache", "GUI_ViewportDecodeLayer",
            "GUI_ViewportResidentSpriteID", "GUI_InitViewportResidentSprites",
            "GUI_ViewportResidentSprite", "GUI_SetViewportPlanar",
        ))
        compile_code = function(video, "Video_Atari_CompileSpriteBlitCode").replace(
            "\n{", "\n{\n    compiles++;", 1)
        production_video = "\n".join(function(video, name) for name in (
            "Video_Atari_DisplayMoveLong", "Video_Atari_DisplayGeometry",
            "Video_Atari_BuildSpriteBlitPlan", "Video_Atari_BuildSpriteBlitPlans",
            "Video_Atari_BuildSpriteBlitGeometry",
            "Video_Atari_BuildSpriteBlitRecipe", "Video_Atari_CompileSpriteBlit",
        )) + "\n" + compile_code
        harness = r"""
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdint.h>
#include <stdarg.h>
#include <string.h>
#include "types.h"
#include "src/os/common.h"
#include "src/os/endian.h"
#include "src/gui/gui.h"
#include "src/gui/viewport_key.h"
#include "src/gui/widget.h"
#include "src/video/video.h"
#include "src/house.h"
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
#define UNIT_INDEX_MAX 1
#define Unit_Get_ByIndex(i) (i)
#define Unit_ClearViewportKey(unit) ((void)(unit))
#define GUI_Sidebar_Free() ((void)0)
#define GFX_Screen_SetViewportPlanar(active) ((void)(active))
#define ST_PLANAR_LINE_BYTES 160
uint16 endian_bswap16(uint16 value) { return (value >> 8) | (value << 8); }
static uint8 images[355][10 + 32 * 32], *sprites[355];
uint8 **g_sprites = sprites;
WidgetProperties g_widgetProperties[22];
bool g_videoViewportBlitter;
static bool s_blitterTileSetup;
uint8 *g_paletteMapping2;
static uint16 g_blinkEffect;
static unsigned allocations, encodes, compiles, fallthroughs, published;
static int16 capturedX, capturedY;
static size_t residentBytes;
static bool paletteReady, failAllocation;
static const ViewportPlanarImage *captured; /* forward replaced below */
/* MASKS */
/* CACHE */
static const uint16 s_blitterLeftMasks[16] = {
    0xffff,0x7fff,0x3fff,0x1fff,0xfff,0x7ff,0x3ff,0x1ff,
    0xff,0x7f,0x3f,0x1f,0xf,7,3,1};
static const uint16 s_blitterRightMasks[16] = {
    0xffff,0x8000,0xc000,0xe000,0xf000,0xf800,0xfc00,0xfe00,
    0xff00,0xff80,0xffc0,0xffe0,0xfff0,0xfff8,0xfffc,0xfffe};
static void GUI_InitViewportResidentSprites(void);
bool Video_Atari_CursorDirect(void) { return true; }
static void Error(const char *format, ...) {
    va_list ap; va_start(ap, format); vfprintf(stderr, format, ap); va_end(ap);
}
static void *test_malloc(size_t bytes) {
    allocations++;
    if (s_viewportSpriteReady) {
        residentBytes = bytes;
        if (failAllocation) return NULL;
    }
    return malloc(bytes);
}
static void *test_calloc(size_t count, size_t bytes) {
    allocations++;
    return calloc(count, bytes);
}
#define malloc test_malloc
#define calloc test_calloc
static void GUI_DrawSpriteMask(uint8 *dst, uint16 stride, uint16 height,
                               const uint8 *sprite, int16 x, int16 y, int flags, ...) {
    unsigned width = READ_LE_UINT16(sprite + 3);
    const uint8 *mapping = NULL;
    assert(!x && !y && height == sprite[2]);
    if (flags & DRAWSPRITE_FLAG_REMAP) {
        va_list ap; va_start(ap, flags);
        mapping = va_arg(ap, const uint8 *);
        assert(va_arg(ap, int) == 1); va_end(ap);
    }
    for (unsigned row = 0; row < height; row++)
    for (unsigned col = 0; col < width; col++) {
        unsigned sx = flags & 1 ? width - 1 - col : col;
        unsigned sy = flags & 2 ? height - 1 - row : row;
        unsigned colour = sprite[10 + sy * width + sx];
        if (colour != 255) dst[row * stride + col] = mapping ? mapping[colour] : colour;
    }
}
void Video_Atari_EncodePlanar(const uint8 *src, uint16 *pixels, uint16 width, uint16 height) {
    assert(paletteReady && !((uintptr_t)src & 1));
    encodes++;
    memset(pixels, 0, width * height / 2);
    for (unsigned y = 0; y < height; y++) for (unsigned x = 0; x < width; x++) {
        unsigned pen = (src[y * width + x] + 5) & 15;
        unsigned group = y * (width / 16) + x / 16;
        for (unsigned plane = 0; plane < 4; plane++)
            if (pen & (1u << plane)) pixels[group * 4 + plane] |= 0x8000u >> (x & 15);
    }
}
/* VIDEO */
/* DIRECTIONS */
/* FLIPS */
/* FUNCTIONS */
static void GUI_ViewportPresentPlanarSprite(const ViewportPlanarImage *image,
                                           int16 x, int16 y, bool blitter, uint16 highlight) {
    assert(blitter && !highlight && image->blitCode);
    captured = image; capturedX = x; capturedY = y; published++;
}
/* ADMISSION */
static void request(unsigned id, int flags, const GUI_SpriteLayers *layers, ViewportCompositeKey *key, ...) {
    va_list ap; va_start(ap, key);
    GUI_ViewportPlanarSprite(sprites[id], id, GUI_SPRITE_COLOUR_EMBEDDED,
        15, 50, flags, &ap, layers, key);
    va_end(ap);
}
static void shapes(void) {
    memset(sprites, 0, sizeof(sprites));
    for (unsigned slot = 0; slot < VIEWPORT_RESIDENT_SPRITES; slot++) {
        unsigned id = GUI_ViewportResidentSpriteID(slot);
        unsigned size = slot < 2 ? slot + 3 : id < 268 ? 16 : 8;
        uint8 *sprite = sprites[id] = images[id];
        memset(sprite, 0, sizeof(images[id]));
        sprite[0] = 2; sprite[2] = size; sprite[3] = size;
        for (unsigned y = 0; y < size; y++) for (unsigned x = 0; x < size; x++)
            sprite[10 + y * size + x] = id == 270 || x == size - 1 ||
                (size > 4 && y < 2) ? 255 : (x * 3 + y) & 15;
    }
}
int main(int argc, char **argv) {
    (void)argv;
    shapes();
    GUI_InitViewportSpriteCache();
    assert(allocations == 4 && !s_viewportResidentsReady);
    GUI_SetViewportPlanar(true);
    assert(allocations == 4 && !encodes);
    GUI_SetViewportPlanar(false);
    g_videoViewportBlitter = paletteReady = true;
    failAllocation = argc > 1;
    GUI_SetViewportPlanar(true);
    assert(allocations == 5 && encodes == 69 && compiles == 29);
    assert(s_viewportResidentsReady);
    size_t expectedBytes = VIEWPORT_RESIDENT_SPRITES * sizeof(Video_Atari_SpriteBlitCode);
    const Video_Atari_SpriteBlitGeometry *uniqueGeometry[VIEWPORT_RESIDENT_SPRITES * 2];
    unsigned geometryCount = 0;
    for (unsigned slot = 0; slot < VIEWPORT_RESIDENT_SPRITES; slot++)
        for (unsigned flags = 0; flags < 4; flags++) {
            const ViewportPlanarImage *image = s_viewportResidentSprites[slot][flags];
            if (!image) continue;
            expectedBytes += sizeof(*image) + image->width * image->height;
            if (!image->blitGeometry) continue;
            unsigned i = 0;
            while (i < geometryCount && uniqueGeometry[i] != image->blitGeometry) i++;
            if (i == geometryCount) {
                assert(geometryCount < VIEWPORT_RESIDENT_SPRITES * 2);
                uniqueGeometry[geometryCount++] = image->blitGeometry;
                expectedBytes += sizeof(Video_Atari_SpriteBlitGeometry) * 16;
            }
        }
    assert(residentBytes == expectedBytes);
    for (unsigned slot = 0; slot < VIEWPORT_RESIDENT_SPRITES; slot++) {
        unsigned id = GUI_ViewportResidentSpriteID(slot);
        uint8 *sprite = sprites[id];
        unsigned size = sprite[2];
        unsigned flips = slot < VIEWPORT_RESIDENT_PROJECTILES ?
            GUI_Widget_Viewport_ProjectileFlipMask(id) : 1;
        for (unsigned flags = 0; flags < 4; flags++) {
            const ViewportPlanarImage *image = GUI_ViewportResidentSprite(id,flags);
            assert((image != NULL) == !!(flips & (1u << flags)));
            if (!image) continue;
            assert(image->width == ((size + 15) & ~15) && image->height == size);
            assert(!memcmp(&image->bounds, GUI_ViewportSpriteBounds(id,flags), sizeof(image->bounds)));
            assert(image->blitCode == GUI_ViewportResidentSprite(id,0)->blitCode);
            for (unsigned y = 0; y < size; y++) for (unsigned x = 0; x < image->width; x++) {
                unsigned sx = flags & 1 ? size - 1 - x : x;
                unsigned sy = flags & 2 ? size - 1 - y : y;
                unsigned raw = x < size ? sprite[10 + sy * size + sx] : 255;
                unsigned word = (y * image->width / 16 + x / 16) * 4;
                unsigned bit = 0x8000u >> (x & 15), colour = 0;
                for (unsigned plane = 0; plane < 4; plane++) {
                    assert(!!(image->masks[word + plane] & bit) == (raw != 255));
                    if (image->pixels[word + plane] & bit) colour |= 1u << plane;
                }
                assert(colour == (raw == 255 ? 0 : (raw + 5) & 15));
            }
            if (flags & 2) {
                const ViewportPlanarImage *other = GUI_ViewportResidentSprite(id,flags & 1);
                assert(image->blitGeometry == other->blitGeometry);
            }
        }
    }
    assert(!GUI_ViewportResidentSprite(160,0) && !GUI_ViewportResidentSprite(278,0));
    assert(!GUI_ViewportResidentSprite(155,0) && !GUI_ViewportResidentSprite(159,0));
    assert(!GUI_ViewportResidentSprite(182,0));
    assert(!GUI_ViewportResidentSprite(185,0));
    static const unsigned impacts[] = {153,154,156,157,158,183,184};
    for (unsigned i = 0; i < sizeof(impacts) / sizeof(*impacts); i++) {
        assert(GUI_ViewportResidentSpriteID(22 + i) == impacts[i]);
        assert(GUI_ViewportResidentSprite(impacts[i],0) == s_viewportResidentSprites[22 + i][0]);
    }
    s_viewportPlanarClock = 17; s_viewportComponentClock = 19;
    ViewportCompositeKey key = {.main = 0x12345678};
    g_widgetProperties[2].yBase = 40;
    request(174,DRAWSPRITE_FLAG_CENTER | DRAWSPRITE_FLAG_WIDGETPOS,NULL,&key);
    assert(published == 1 && captured == s_viewportResidentSprites[0][0]);
    assert(capturedX == 14 && capturedY == 89);
    assert(!fallthroughs && key.main == 0x12345678);
    assert(s_viewportPlanarClock == 17 && s_viewportComponentClock == 19);
    for (unsigned i = 0; i < 64; i++)
        assert(!s_viewportPlanarSprites[i].key.main && !s_viewportPlanarComponents[i].key);
    request(174,DRAWSPRITE_FLAG_RTL,NULL,&key);
    assert(fallthroughs == 1);
    g_videoViewportBlitter = false;
    request(174,0,NULL,&key);
    assert(fallthroughs == 2 && published == 1);
    g_videoViewportBlitter = true;
    GUI_SpriteLayers layers = {.count = 1, .layer = {{
        .spriteID = 174, .colourHouse = GUI_SPRITE_COLOUR_EMBEDDED}}};
    request(174,0,&layers,&key);
    assert(fallthroughs == 3 && published == 1);
    g_videoViewportBlitter = false;
    request(153,0,NULL,&key);
    assert(fallthroughs == 4 && published == 1);
    g_videoViewportBlitter = true;
    request(153,0,&layers,&key);
    assert(fallthroughs == 5 && published == 1);
    g_widgetProperties[2].xBase = 3;
    for (unsigned slot = 0; slot < VIEWPORT_RESIDENT_SPRITES; slot++) {
        unsigned id = GUI_ViewportResidentSpriteID(slot);
        for (unsigned flags = 0; flags < 4; flags++) {
            if (!s_viewportResidentSprites[slot][flags]) continue;
            unsigned before = published;
            request(id,flags | DRAWSPRITE_FLAG_CENTER | DRAWSPRITE_FLAG_WIDGETPOS,NULL,&key);
            assert(published == before + 1 && captured == s_viewportResidentSprites[slot][flags]);
            assert(capturedX == 39 - sprites[id][3] / 2);
            assert(capturedY == 90 - sprites[id][2] / 2);
        }
    }
    assert(published == 70 && fallthroughs == 5 && key.main == 0x12345678);
    for (unsigned i = 0; i < sizeof(impacts) / sizeof(*impacts); i++)
        for (unsigned flags = 1; flags < 4; flags++)
            request(impacts[i],flags,NULL,&key);
    assert(published == 70 && fallthroughs == 26);
    assert(s_viewportPlanarClock == 17 && s_viewportComponentClock == 19);
    for (unsigned i = 0; i < 64; i++)
        assert(!s_viewportPlanarSprites[i].key.main && !s_viewportPlanarComponents[i].key);
    for (unsigned i = 0; i < 100; i++) { GUI_SetViewportPlanar(false); GUI_SetViewportPlanar(true); }
    assert(allocations == 5 && encodes == 69 && compiles == 29);
    uint8 original[sizeof(images)]; memcpy(original,images,sizeof(images));
    GUI_InitViewportSpriteCache();
    assert(!s_viewportResidentsReady && !s_viewportResidentStorage);
    for (unsigned slot = 0; slot < VIEWPORT_RESIDENT_SPRITES; slot++) for (unsigned flags = 0; flags < 4; flags++)
        assert(!s_viewportResidentSprites[slot][flags]);
    GUI_SetViewportPlanar(true);
    assert(encodes == 138 && compiles == 58 && !memcmp(original,images,sizeof(images)));
    GUI_FreeViewportSpriteCache();
    assert(!s_viewportResidentStorage && !s_viewportResidentsReady);
    return 0;
}
"""
        harness = harness.replace(
            "static const ViewportPlanarImage *captured; /* forward replaced below */", "")
        harness = harness.replace("/* MASKS */", mask_type).replace(
            "/* CACHE */", cache + "\nstatic const ViewportPlanarImage *captured;")
        return (harness.replace("/* VIDEO */", production_video)
                .replace("/* DIRECTIONS */", directions)
                .replace("/* FLIPS */", function(viewport, "GUI_Widget_Viewport_ProjectileFlipMask"))
                .replace("/* FUNCTIONS */", functions)
                .replace("/* ADMISSION */", admission))

    def test_residency_pixels_dispatch_and_reload(self):
        run_harness(self.harness())

    def test_single_publication_join(self):
        cached = function((ROOT / "src/gui/gui.c").read_text(), "GUI_ViewportPlanarSprite")
        self.assertEqual(cached.count("GUI_ViewportPresentPlanarSprite("), 1)
        self.assertLess(cached.index("goto present;"), cached.index("if (key == NULL)"))
        self.assertLess(cached.index("x += entry->offsetX;"), cached.index("\npresent:"))
        self.assertLess(cached.index("y += entry->offsetY;"), cached.index("\npresent:"))

    def test_allocation_failure_is_explicit(self):
        with tempfile.TemporaryDirectory(prefix="projectile-cache-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(self.harness())
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                            "-DTOS", *flags, "-I" + str(ROOT), "-iquote", str(ROOT / "src"),
                            "-I" + str(ROOT / "include"), str(source), "-o", str(binary)], check=True)
            result = subprocess.run([str(binary), "fail"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Out of memory for resident planar sprites", result.stderr)


if __name__ == "__main__":
    unittest.main()
