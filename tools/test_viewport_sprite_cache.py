"""Check the isolated planar image cache and direct-screen sprite alignment."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    match = re.search(r"^(?:static )?(?:inline )?[^\n]*\b" + name + r"\([^;]*?\n\{", source, re.M)
    if match is None:
        raise ValueError("Missing function: " + name)
    return source[match.start():source.index("\n}\n", match.end()) + 3]


class ViewportSpriteCacheTest(unittest.TestCase):
    def test_cache_and_direct_blits(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        video = (ROOT / "src/video/video_atari.c").read_text()
        cache = gui[gui.index("enum { VIEWPORT_PLANAR_SPRITES"):gui.index("\nvoid GUI_FreeViewportSpriteCache")]
        flags = "\n".join(line for line in (ROOT / "src/gui/gui.h").read_text().splitlines()
                          if line.startswith(("#define DRAWSPRITE_FLAG_", "#define GUI_SPRITE_")))
        header = (ROOT / "src/gui/gui.h").read_text()
        layer_types = header[header.index("typedef struct GUI_SpriteLayer"):header.index("/* colourHouse identifies")]
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int16_t int16;
typedef uint32_t uint32;
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
#define READ_LE_UINT16(p) ((uint16)((p)[0] | ((uint16)(p)[1] << 8)))
#define DIRTY_SRC_SPRITE 1
#define HOUSE_MAX 6
#define VARIABLE_NOT_USED(x) ((void)(x))
/* FLAGS */
/* LAYER TYPES */
typedef struct { uint16 xBase, yBase, width, height; } WidgetProperties;
typedef struct { const uint8 *sprite; uint16 *rows; uint16 width, height; } ViewportSpriteMask;
static WidgetProperties g_widgetProperties[3] = {{0}, {0}, {0, 40, 30, 160}};
static uint8 sprites[70][26 + 23 * 27], palette[16], remap[256];
static uint8 *g_sprites[355], *g_paletteMapping2 = remap;
static ViewportSpriteMask slots[70];
static uint16 maskStorage[70][2 * 2 * 27];
static uint16 visible[16000], expected[16000];
static bool s_viewportPlanar = true, s_viewportSpriteReady = true, overlays;
static ViewportSpriteMask s_viewportSpriteCache[512];
static uint16 *s_viewportSpriteMasks;
static unsigned decodes, encodes, overlayWrites, dirtyClears;
static unsigned compositions;
#define Warning(...) assert(false)
/* CACHE */
/* FREE */
static ViewportSpriteMask *GUI_ViewportSpriteMaskSlot(const uint8 *sprite) {
    for (unsigned i = 0; i < 70; i++) if (slots[i].sprite == sprite) return slots + i;
    assert(false); return NULL;
}
static void GFX_Screen_SetDirtySource(unsigned source) { assert(source == DIRTY_SRC_SPRITE); }
static void GFX_Screen_ClearDirtyRect(uint16 l, uint16 t, uint16 r, uint16 b) {
    assert(!(l & 15) && !(r & 15) && l < r && r <= 240 && t >= 40 && t < b && b <= 200);
    dirtyClears++;
}
static uint8 *Video_Atari_PlanarBase(void) { return (uint8 *)visible; }
static bool Video_Atari_PlanarOverlaysOverlap(uint8 *base, uint16 x, uint16 y, uint16 w, uint16 h) {
    assert(base == (uint8 *)visible && !(x & 15) && !(w & 15) && y >= 40 && y + h <= 200);
    return overlays;
}
/* MERGE */
static void Video_Atari_PlanarMergeGroup(uint8 *base, uint16 y, uint16 group,
                                       uint16 mask, const uint16 words[4]) {
    assert(base == (uint8 *)visible && overlays);
    overlayWrites++;
    Video_Atari_PlanarMergePlain(visible + y * 80 + group * 4, mask, words);
}
static void GUI_DrawSpriteMask(uint8 *buffer, uint16 width, uint16 height,
                               const uint8 *sprite, int16 left, int16 top, int flags, ...) {
    va_list ap;
    const uint8 *colours = NULL, *mapping = NULL;
    va_start(ap, flags);
    if (flags & DRAWSPRITE_FLAG_PAL) colours = va_arg(ap, uint8 *);
    if (flags & DRAWSPRITE_FLAG_REMAP) {
        mapping = va_arg(ap, const uint8 *);
        assert(va_arg(ap, int) == 1);
    }
    va_end(ap);
    assert(left >= 0 && top >= 0 && left + 23 <= width && top + 27 <= height);
    decodes++;
    for (unsigned y = 0; y < 27; y++) for (unsigned x = 0; x < 23; x++) {
        unsigned sx = flags & DRAWSPRITE_FLAG_RTL ? 22 - x : x;
        unsigned sy = flags & DRAWSPRITE_FLAG_BOTTOMUP ? 26 - y : y;
        uint8 index = sprite[((sprite[0] & 1) ? 26 : 10) + sy * 23 + sx];
        if (index) {
            uint8 colour = sprite[0] & 1 ? colours[index] : index;
            buffer[(y + top) * width + x + left] = mapping ? mapping[colour] : colour;
        }
    }
}
static void Video_Atari_EncodePlanar(const uint8 *src, uint16 *dst, uint16 width, uint16 height) {
    encodes++;
    memset(dst, 0, width * height / 2);
    for (unsigned y = 0; y < height; y++) for (unsigned x = 0; x < width; x++)
        for (unsigned p = 0; p < 4; p++)
            if (src[y * width + x] & (1u << p))
                dst[y * (width / 4) + (x >> 4) * 4 + p] |= 0x8000u >> (x & 15);
}
/* BLITTER */
/* LOOKUP */
static bool draw(const uint8 *sprite, int16 x, int16 y, int flags, ...) {
    bool result;
    va_list ap;
    uint16 id = (sprite - sprites[0]) / sizeof(sprites[0]);
    va_start(ap, flags);
    result = GUI_ViewportPlanarSprite(sprite, id,
        flags & DRAWSPRITE_FLAG_PAL ? 0 : GUI_SPRITE_COLOUR_EMBEDDED, x, y, flags, &ap, NULL);
    va_end(ap);
    return result;
}
static bool draw_identity(uint16 id, uint8 house, int flags, ...) {
    bool result;
    va_list ap;
    va_start(ap, flags);
    result = GUI_ViewportPlanarSprite(sprites[0], id, house, 64, 60, flags, &ap, NULL);
    va_end(ap);
    return result;
}
static void check(unsigned id, int x, int y, int flags, bool recolour) {
    int ox = x, oy = y;
    if (flags & DRAWSPRITE_FLAG_WIDGETPOS) oy += 40;
    if (flags & DRAWSPRITE_FLAG_CENTER) { ox -= 11; oy -= 13; }
    for (unsigned i = 0; i < 16000; i++) visible[i] = expected[i] = i * 137 + 41;
    for (unsigned row = 0; row < 27; row++) for (unsigned col = 0; col < 23; col++) {
        int dx = ox + col, dy = oy + row;
        unsigned sx = flags & DRAWSPRITE_FLAG_RTL ? 22 - col : col;
        unsigned sy = flags & DRAWSPRITE_FLAG_BOTTOMUP ? 26 - row : row;
        uint8 index = sprites[id][((sprites[id][0] & 1) ? 26 : 10) + sy * 23 + sx], colour;
        if (!index || dx < 0 || dx >= 240 || dy < 40 || dy >= 200) continue;
        colour = !(sprites[id][0] & 1) ? index :
            (flags & DRAWSPRITE_FLAG_PAL ? palette[index] : sprites[id][10 + index]);
        if (recolour) colour = remap[colour];
        for (unsigned p = 0; p < 4; p++) {
            uint16 bit = 0x8000u >> (dx & 15);
            uint16 *dst = expected + dy * 80 + (dx >> 4) * 4 + p;
            *dst = (*dst & (uint16)~bit) | ((colour & (1u << p)) ? bit : 0);
        }
    }
    if (recolour) assert(draw(sprites[id], x, y, flags, palette, remap, 1));
    else if (flags & DRAWSPRITE_FLAG_PAL) assert(draw(sprites[id], x, y, flags, palette));
    else assert(draw(sprites[id], x, y, flags));
    assert(!memcmp(visible, expected, sizeof(visible)));
}
static bool draw_layers(const GUI_SpriteLayers *layers, int16 x, int16 y, int flags, ...) {
    va_list ap;
    bool result;
    va_start(ap, flags);
    result = GUI_ViewportPlanarSprite(sprites[0], 0, 0, x, y, flags, &ap, layers);
    va_end(ap);
    return result;
}
static void reference_layer(unsigned id, int x, int y, int flags,
                            const uint8 *colours, const uint8 *mapping) {
    for (unsigned row = 0; row < 27; row++) for (unsigned col = 0; col < 23; col++) {
        int dx = x - 11 + col, dy = y - 13 + row;
        unsigned sx = flags & DRAWSPRITE_FLAG_RTL ? 22 - col : col;
        unsigned sy = flags & DRAWSPRITE_FLAG_BOTTOMUP ? 26 - row : row;
        uint8 index = sprites[id][((sprites[id][0] & 1) ? 26 : 10) + sy * 23 + sx];
        if (!index || dx < 0 || dx >= 240 || dy < 40 || dy >= 200) continue;
        uint8 colour = sprites[id][0] & 1 ? (colours ? colours[index] : sprites[id][10 + index]) : index;
        colour = mapping ? mapping[colour] : colour;
        for (unsigned p = 0; p < 4; p++) {
            uint16 bit = 0x8000u >> (dx & 15);
            uint16 *dst = expected + dy * 80 + (dx >> 4) * 4 + p;
            *dst = (*dst & (uint16)~bit) | ((colour & (1u << p)) ? bit : 0);
        }
    }
}
static void check_layers(const GUI_SpriteLayers *layers, int x, int y, int flags) {
    for (unsigned i = 0; i < 16000; i++) visible[i] = expected[i] = i * 137 + 41;
    reference_layer(0, x, y + 40, flags, palette, remap);
    for (unsigned i = 0; i < layers->count; i++) {
        const GUI_SpriteLayer *layer = &layers->layer[i];
        reference_layer(layer->spriteID, x + layer->offsetX, y + 40 + layer->offsetY,
                        layer->flags, layer->flags & DRAWSPRITE_FLAG_PAL ? layer->palette : NULL, NULL);
    }
    unsigned before = dirtyClears;
    assert(draw_layers(layers, x, y, flags | DRAWSPRITE_FLAG_CENTER | DRAWSPRITE_FLAG_WIDGETPOS |
                       DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_REMAP, palette, remap, 1));
    assert(dirtyClears == before + 1);
    assert(!memcmp(visible, expected, sizeof(visible)));
}
int main(void) {
    unsigned before;
    ViewportPlanarSprite *saved;
    for (unsigned id = 0; id < 70; id++) {
        uint8 *sprite = sprites[id];
        g_sprites[id] = sprite;
        sprite[0] = id == 6 ? 2 : 3; sprite[2] = 27; sprite[3] = 23;
        for (unsigned x = 0; x < 16; x++) sprite[10 + x] = x;
        for (unsigned y = 0; y < 27; y++) for (unsigned x = 0; x < 23; x++)
            sprite[(id == 6 ? 10 : 26) + y * 23 + x] =
                (x + y) % 5 == 0 ? 0 : (id == 6 ? 200 : 1) + (x + y) % 15;
        slots[id].sprite = sprite; slots[id].width = 23; slots[id].height = 27;
        slots[id].rows = maskStorage[id];
        for (unsigned mirror = 0; mirror < 2; mirror++)
            for (unsigned y = 0; y < 27; y++) for (unsigned x = 0; x < 23; x++)
                if (sprite[(id == 6 ? 10 : 26) + y * 23 + (mirror ? 22 - x : x)])
                    maskStorage[id][mirror * 54 + y * 2 + (x >> 4)] |= 0x8000u >> (x & 15);
    }
    for (unsigned x = 0; x < 16; x++) palette[x] = x + 16;
    for (unsigned x = 0; x < 256; x++) remap[x] = x;
    remap[17] = 0; remap[0] = 2;
    s_viewportPlanarSprites = calloc(VIEWPORT_PLANAR_SPRITES, sizeof(*s_viewportPlanarSprites));
    s_viewportPlanarComponents = calloc(VIEWPORT_PLANAR_COMPONENTS, sizeof(*s_viewportPlanarComponents));
    assert(s_viewportPlanarSprites && s_viewportPlanarComponents);
    for (unsigned flags = 0; flags < 4; flags++) for (unsigned phase = 0; phase < 16; phase++) {
        check(0, 64 + phase, 60, flags, false);
        before = decodes;
        check(0, 64 + phase, 60, flags, false);
        assert(decodes == before);
    }
    assert(decodes == 4 && encodes == 4);
    for (unsigned flags = 0; flags < 4; flags++) {
        check(0, -13, 33, flags, false);
        check(0, 231, 191, flags, false);
        check(0, 4, 45, flags | DRAWSPRITE_FLAG_CENTER, false);
        check(0, 64, 20, flags | DRAWSPRITE_FLAG_WIDGETPOS, false);
    }
    overlays = true;
    check(0, 65, 60, DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_REMAP, true);
    assert(overlayWrites);
    overlays = false;
    check(0, 64, 60, DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_REMAP, true);
    before = decodes;
    check(0, 64, 60, DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_REMAP, true);
    assert(decodes == before);
    assert(!draw(sprites[0], 64, 60, DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_REMAP, palette, remap, 2));
    assert(!draw_identity(GUI_SPRITE_ID_UNKNOWN, GUI_SPRITE_COLOUR_EMBEDDED, 0));
    assert(!draw_identity(1, GUI_SPRITE_COLOUR_EMBEDDED, 0));
    assert(!draw_identity(0, GUI_SPRITE_COLOUR_UNKNOWN, DRAWSPRITE_FLAG_PAL, palette));
    assert(!draw_identity(0, 0, 0));
    assert(decodes == before);
    /* Explicit house 0, embedded palette, and another house are separate keys. */
    assert(draw_identity(0, 0, DRAWSPRITE_FLAG_PAL, palette));
    assert(draw_identity(0, 1, DRAWSPRITE_FLAG_PAL, palette));
    before = decodes;
    assert(draw_identity(0, 0, DRAWSPRITE_FLAG_PAL, palette));
    assert(draw_identity(0, 1, DRAWSPRITE_FLAG_PAL, palette));
    assert(decodes == before);
    for (unsigned id = 1; id < 70; id++) check(id, 64, 60, 0, false);
    before = decodes;
    check(69, 64, 60, 0, false);
    assert(decodes == before);
    check(0, 64, 60, 0, false);
    assert(decodes == before + 1);
    s_viewportPlanarClock = 65535;
    check(0, 64, 60, 0, false);
    assert(s_viewportPlanarClock == 1 && decodes == before + 1);
    before = decodes;
    assert(draw(sprites[0], -100, -100, 0) && decodes == before);
    assert(!draw(sprites[0], 64, 60, DRAWSPRITE_FLAG_ZOOM));
    saved = s_viewportPlanarSprites; s_viewportPlanarSprites = NULL;
    assert(!draw(sprites[0], 64, 60, 0));
    s_viewportPlanarSprites = saved;
    ViewportPlanarComponent *savedComponents = s_viewportPlanarComponents;
    s_viewportPlanarComponents = NULL;
    assert(!draw(sprites[0], 64, 60, 0));
    s_viewportPlanarComponents = savedComponents;
    memset(s_viewportPlanarSprites, 0, VIEWPORT_PLANAR_SPRITES * sizeof(*s_viewportPlanarSprites));
    memset(s_viewportPlanarComponents, 0, VIEWPORT_PLANAR_COMPONENTS * sizeof(*s_viewportPlanarComponents));
    /* Complete unit: attachment, independent turret, smoke, direct-index selection.
     * Overlap, opaque colour 0, wide negative offsets and taller bounds matter. */
    GUI_SpriteLayers layers = {4, {
        {1, GUI_SPRITE_COLOUR_EMBEDDED, -14, 7, DRAWSPRITE_FLAG_RTL, {0}},
        {2, 2, 2, -5, DRAWSPRITE_FLAG_BOTTOMUP | DRAWSPRITE_FLAG_PAL, {0}},
        {3, GUI_SPRITE_COLOUR_EMBEDDED, 0, -14, 0, {0}},
        {6, GUI_SPRITE_COLOUR_EMBEDDED, 0, 0, 0, {0}}
    }};
    for (unsigned i = 0; i < 16; i++) layers.layer[1].palette[i] = i == 1 ? 0 : i + 32;
    before = decodes;
    unsigned encoded = encodes;
    check_layers(&layers, 65, 50, DRAWSPRITE_FLAG_RTL);
    assert(decodes == before + 5 && encodes == encoded + 5);
    before = decodes;
    encoded = encodes;
    unsigned composed = compositions;
    overlays = true;
    check_layers(&layers, 81, 66, DRAWSPRITE_FLAG_RTL);
    assert(decodes == before && encodes == encoded && compositions == composed);
    overlays = false;
    layers.count = 3;
    check_layers(&layers, 65, 50, DRAWSPRITE_FLAG_RTL);
    assert(decodes == before && encodes == encoded && compositions == composed + 4);
    before = decodes;
    layers.count = 4;
    check_layers(&layers, 65, 50, DRAWSPRITE_FLAG_RTL);
    assert(decodes == before);
    layers.layer[1].offsetX--;
    check_layers(&layers, 65, 50, DRAWSPRITE_FLAG_RTL);
    assert(decodes == before && encodes == encoded);
    before = decodes;
    layers.layer[1].colourHouse++;
    layers.layer[1].palette[1] = 7;
    check_layers(&layers, 65, 50, DRAWSPRITE_FLAG_RTL);
    assert(decodes == before + 1 && encodes == encoded + 1);
    layers.layer[1].spriteID++;
    layers.layer[1].flags ^= DRAWSPRITE_FLAG_RTL;
    check_layers(&layers, -5, 0, DRAWSPRITE_FLAG_BOTTOMUP);
    check_layers(&layers, 239, 159, DRAWSPRITE_FLAG_BOTTOMUP);
    before = decodes;
    check_layers(&layers, 65, 50, DRAWSPRITE_FLAG_RTL);
    assert(decodes == before);
    /* A composite eviction must not discard its independently cached parts. */
    memset(s_viewportPlanarSprites, 0, VIEWPORT_PLANAR_SPRITES * sizeof(*s_viewportPlanarSprites));
    encoded = encodes;
    composed = compositions;
    check_layers(&layers, 65, 50, DRAWSPRITE_FLAG_RTL);
    assert(decodes == before && encodes == encoded && compositions == composed + 5);
    /* Composite alignment is determined by the union, not just the body.
     * Exercise every phase/flip at both viewport edges and on cache hits. */
    for (unsigned flags = 0; flags < 4; flags++) {
        for (unsigned phase = 0; phase < 16; phase++) {
            check_layers(&layers, 64 + phase, 50, flags);
            before = decodes;
            encoded = encodes;
            check_layers(&layers, 80 + phase, 66, flags);
            assert(decodes == before && encodes == encoded);
            check_layers(&layers, -5 + phase, 0, flags);
            check_layers(&layers, 224 + phase, 159, flags);
        }
    }
    /* Phase changes/rebuilt composites do not generate more component variants. */
    before = decodes;
    encoded = encodes;
    for (unsigned phase = 0; phase < 16; phase++) check_layers(&layers, 64 + phase, 50, 0);
    assert(decodes == before && encodes == encoded);
    /* A new smoke frame decodes only itself, not the body/turret/selection. */
    layers.layer[2].spriteID = 4;
    check_layers(&layers, 79, 50, 0);
    assert(decodes == before + 1 && encodes == encoded + 1);
    before = decodes;
    encoded = encodes;
    layers.layer[2].spriteID = 3;
    check_layers(&layers, 79, 50, 0);
    assert(decodes == before && encodes == encoded);
    s_viewportComponentClock = 65535;
    ViewportPlanarComponent *component = GUI_ViewportPlanarComponent(slots, 0, 0, 0, palette, remap);
    assert(s_viewportComponentClock == 1 && decodes == before && component->used == 1);
    /* Component evictions cannot invalidate a completed composite. */
    for (unsigned id = 7; id < 70; id++)
        GUI_ViewportPlanarComponent(slots + id, id, GUI_SPRITE_COLOUR_EMBEDDED, 0, NULL, NULL);
    before = decodes;
    check_layers(&layers, 79, 50, 0);
    assert(decodes == before);
    {
        uint16 dst[1280], want[1280], opacity[320], wantOpacity[320];
        uint16 src[256], srcMasks[64];
        unsigned widths[] = {1, 16, 17, 32};
        for (unsigned w = 0; w < 4; w++) for (unsigned height = 1; height <= 32; height += 31) {
            unsigned width = widths[w], stride = (width + 15) & ~15, groups = stride / 16;
            for (unsigned x = 0; x + width <= 80; x++) {
                unsigned top = 64 - height;
                for (unsigned i = 0; i < 1280; i++) dst[i] = want[i] = i * 137 + 41;
                for (unsigned i = 0; i < 320; i++) opacity[i] = wantOpacity[i] = i * 113 + 13;
                memset(src, 0, sizeof(src));
                memset(srcMasks, 0, sizeof(srcMasks));
                for (unsigned y = 0; y < height; y++) for (unsigned col = 0; col < width; col++) {
                    if ((x & 1) && (col + y) % 5 == 0) continue;
                    uint16 colour = (col * 3 + y) & 15;
                    uint16 sb = 0x8000u >> (col & 15), db = 0x8000u >> ((x + col) & 15);
                    unsigned si = y * groups + col / 16, di = (top + y) * 5 + (x + col) / 16;
                    srcMasks[si] |= sb;
                    wantOpacity[di] |= db;
                    for (unsigned p = 0; p < 4; p++) {
                        if (colour & (1u << p)) src[si * 4 + p] |= sb;
                        want[di * 4 + p] = (want[di * 4 + p] & (uint16)~db) |
                            ((colour & (1u << p)) ? db : 0);
                    }
                }
                Video_Atari_ComposePlanarSprite(dst, opacity, 80, 64,
                    src, srcMasks, stride, height, x, top);
                assert(!memcmp(dst, want, sizeof(dst)));
                assert(!memcmp(opacity, wantOpacity, sizeof(opacity)));
            }
        }
    }
    assert(dirtyClears);
    GUI_FreeViewportSpriteCache();
    assert(!s_viewportPlanarSprites && !s_viewportPlanar && !s_viewportSpriteReady && !s_viewportPlanarClock);
    assert(!s_viewportPlanarComponents && !s_viewportComponentClock);
    assert(!draw(sprites[0], 64, 60, 0));
    return 0;
}
"""
        harness = harness.replace("/* FLAGS */", flags).replace("/* LAYER TYPES */", layer_types)
        harness = harness.replace("/* CACHE */", cache)
        harness = harness.replace("/* FREE */", function(gui, "GUI_FreeViewportSpriteCache"))
        harness = harness.replace("/* MERGE */", function(video, "Video_Atari_PlanarMergePlain"))
        composer = function(video, "Video_Atari_ComposePlanarSprite")
        composer = composer.replace("\n{\n", "\n{\n    compositions++;\n", 1)
        harness = harness.replace("/* BLITTER */", composer + "\n" +
                                  function(video, "Video_Atari_PlanarCopyGroup") + "\n" +
                                  function(video, "Video_Atari_PresentPlanarSprite"))
        harness = harness.replace("/* LOOKUP */", function(gui, "GUI_ViewportDecodeLayer") + "\n" +
                                  function(gui, "GUI_ViewportPlanarComponent") + "\n" +
                                  function(gui, "GUI_ViewportPlanarSprite"))
        with tempfile.TemporaryDirectory(prefix="viewport-sprite-cache-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                            str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_layered_dispatch_and_fallback(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        viewport_flags = re.search(r"(?:int|uint16) spriteFlags = 0;", viewport).group()
        header = (ROOT / "src/gui/gui.h").read_text()
        flags = "\n".join(line for line in header.splitlines()
                          if line.startswith(("#define DRAWSPRITE_FLAG_", "#define GUI_SPRITE_")))
        layer_types = header[header.index("typedef struct GUI_SpriteLayer"):header.index("/* colourHouse identifies")]
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>
#include <stddef.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int16_t int16;
typedef int Screen;
#define SCREEN_0 0
#define VARIABLE_NOT_USED(x) ((void)(x))
/* FLAGS */
/* LAYER TYPES */
static uint8 assets[5], *g_sprites[5], screen[2], bodyPalette[16], remap[256];
static GUI_SpriteLayers layers;
static bool cached;
static unsigned attempts, draws;
static uint8 *GFX_Screen_Get_ByIndex(Screen id) { return screen + id; }
static bool GUI_ViewportPlanarSprite(const uint8 *sprite, uint16 id, uint8 house,
                                    int16 x, int16 y, int flags, va_list *ap,
                                    const GUI_SpriteLayers *composition) {
    attempts++;
    if (sprite != g_sprites[0]) {
        assert(composition == NULL);
        return false;
    }
    assert(sprite == g_sprites[0] && id == 0 && house == 1);
    assert(x == 50 && y == 60 && !(flags & DRAWSPRITE_FLAG_LAYERS));
    assert(composition == &layers);
    assert(va_arg(*ap, uint8 *) == bodyPalette);
    assert(va_arg(*ap, uint8 *) == remap && va_arg(*ap, int) == 1);
    return cached;
}
static void GUI_DrawSpriteInternal(Screen screenID, const uint8 *sprite, int16 x, int16 y,
                                  uint16 windowID, int flags, va_list *ap,
                                  uint8 *target, uint16 width, uint16 height) {
    unsigned id = draws++;
    assert(id < 5 && sprite == g_sprites[id] && windowID == 2);
    assert(screenID == 0 || screenID == 1);
    assert(!target && !width && !height && !(flags & DRAWSPRITE_FLAG_LAYERS));
    if (id == 0) {
        assert(x == 50 && y == 60);
        assert(va_arg(*ap, uint8 *) == bodyPalette);
        assert(va_arg(*ap, uint8 *) == remap && va_arg(*ap, int) == 1);
    } else {
        const GUI_SpriteLayer *layer = &layers.layer[id - 1];
        assert(x == 50 + layer->offsetX && y == 60 + layer->offsetY);
        assert(flags == (layer->flags | DRAWSPRITE_FLAG_CENTER | DRAWSPRITE_FLAG_WIDGETPOS));
        if (flags & DRAWSPRITE_FLAG_PAL) assert(va_arg(*ap, const uint8 *) == layer->palette);
    }
}
/* DRAW */
int main(void) {
    for (unsigned i = 0; i < 5; i++) g_sprites[i] = assets + i;
    layers.count = 4;
    for (unsigned i = 0; i < 4; i++) {
        layers.layer[i].spriteID = i + 1;
        layers.layer[i].colourHouse = GUI_SPRITE_COLOUR_EMBEDDED;
        layers.layer[i].offsetX = (int)i - 2;
        layers.layer[i].offsetY = -14 + i * 3;
        layers.layer[i].flags = i == 1 ? DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_RTL : 0;
    }
    /* VIEWPORT FLAGS */
    spriteFlags |= DRAWSPRITE_FLAG_CENTER | DRAWSPRITE_FLAG_WIDGETPOS |
                   DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_REMAP;
    spriteFlags |= DRAWSPRITE_FLAG_LAYERS;
    assert(spriteFlags & DRAWSPRITE_FLAG_LAYERS);
    int flags = spriteFlags;
    cached = true;
    GUI_DrawSprite(0, g_sprites[0], 0, 1, 50, 60, 2, flags, &layers, bodyPalette, remap, 1);
#ifdef TOS
    assert(attempts == 1 && draws == 0);
#else
    assert(attempts == 0 && draws == 5);
#endif
    draws = attempts = 0;
    cached = false;
    GUI_DrawSprite(0, g_sprites[0], 0, 1, 50, 60, 2, flags, &layers, bodyPalette, remap, 1);
    assert(draws == 5);
    draws = attempts = 0;
    GUI_DrawSprite(1, g_sprites[0], 0, 1, 50, 60, 2, flags, &layers, bodyPalette, remap, 1);
    assert(attempts == 0 && draws == 5);
    return 0;
}
"""
        harness = harness.replace("/* FLAGS */", flags).replace("/* LAYER TYPES */", layer_types)
        harness = harness.replace("/* VIEWPORT FLAGS */", viewport_flags)
        harness = harness.replace("/* DRAW */", function(gui, "GUI_DrawSprite"))
        with tempfile.TemporaryDirectory(prefix="viewport-layer-dispatch-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            for defines in ([], ["-DTOS"]):
                subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                                "-Werror", "-Wno-unused-function", *defines,
                                str(source), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)
