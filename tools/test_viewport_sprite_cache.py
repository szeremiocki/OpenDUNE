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


def blit_plan_type():
    header = (ROOT / "src/video/video.h").read_text()
    start = header.index("typedef struct Video_Atari_SpriteBlitPlan {")
    end = header.index("} Video_Atari_SpriteBlitPlan;", start) + len("} Video_Atari_SpriteBlitPlan;")
    return "#ifndef TEST_BLIT_PLAN_TYPE\n#define TEST_BLIT_PLAN_TYPE\n" + header[start:end] + "\n#endif\n"


def blitter_model(video, tiles=False):
    """Execute production register setup against a persistent 32-bit latch."""
    model = r"""
#define ST_PLANAR_LINE_BYTES 160
#define Atari_SupervisorExec(callback) callback()
static bool s_viewportBlitter;
static bool s_blitterTileSetup;
static int16 reg_src_x, reg_src_y, reg_dst_x, reg_dst_y;
static uintptr_t reg_src, reg_dst;
static uint16 reg_mask1, reg_mask2, reg_mask3, reg_x, reg_y;
static uint8 reg_hop, reg_op, reg_ctrl, reg_skew;
#define BLITTER_SRC_XINC (&reg_src_x)
#define BLITTER_SRC_YINC (&reg_src_y)
#define BLITTER_SRC_ADDR (&reg_src)
#define BLITTER_ENDMASK1 (&reg_mask1)
#define BLITTER_ENDMASK2 (&reg_mask2)
#define BLITTER_ENDMASK3 (&reg_mask3)
#define BLITTER_DST_XINC (&reg_dst_x)
#define BLITTER_DST_YINC (&reg_dst_y)
#define BLITTER_DST_ADDR (&reg_dst)
#define BLITTER_XCOUNT (&reg_x)
#define BLITTER_YCOUNT (&reg_y)
#define BLITTER_HOP (&reg_hop)
#define BLITTER_OP (&reg_op)
#define BLITTER_CTRL (&reg_ctrl)
#define BLITTER_SKEW (&reg_skew)
static unsigned blitterLaunches, blitterLocks, blitterSetups, blitterPlanBuilds, cachedPlanDraws;
static uintptr_t blitterPixels, blitterMasks;
static uint16 blitterReadStride;
static void Video_Atari_BlitterStart(void) {
    static uint32 latch = 0xa39fbc71;
    unsigned words = reg_x, rows = reg_y;
    uintptr_t src = reg_src, dst = reg_dst;
    assert(!blitterLocks && reg_hop == 2 && words && rows);
    assert(reg_op == 3 || reg_op == 4 || reg_op == 7);
    assert(words != 1 || !(reg_skew & 0x40));
    blitterLaunches++;
    for (unsigned row = 0; row < rows; row++) {
        uintptr_t rowBase = (reg_op == 4 ? blitterMasks : blitterPixels) + row * blitterReadStride;
        if (reg_skew & 0x80) {
            assert(reg_op == 3 || (src >= rowBase && src + 2 <= rowBase + blitterReadStride));
            uint16 value = *(const uint16 *)src;
            latch = reg_src_x < 0 ? (latch >> 16) | ((uint32)value << 16) :
                                   (latch << 16) | value;
            src += reg_src_x;
        }
        for (unsigned word = 0; word < words; word++) {
            bool suppress = (reg_skew & 0x40) && word + 1 == words;
            uint16 old = *(uint16 *)dst;
            assert(suppress || reg_op == 3 ||
                   (src >= rowBase && src + 2 <= rowBase + blitterReadStride));
            uint16 value = suppress ? old : *(const uint16 *)src;
            latch = reg_src_x < 0 ? (latch >> 16) | ((uint32)value << 16) :
                                   (latch << 16) | value;
            uint16 shifted = latch >> (reg_skew & 15);
            uint16 result = reg_op == 3 ? shifted :
                            reg_op == 4 ? old & (uint16)~shifted : old | shifted;
            uint16 mask = word == 0 ? reg_mask1 :
                          word + 1 == words ? reg_mask3 : reg_mask2;
            *(uint16 *)dst = (old & (uint16)~mask) | (result & mask);
            if (suppress) {
                value = *(uint16 *)dst;
                latch = reg_src_x < 0 ? (latch >> 16) | ((uint32)value << 16) :
                                       (latch << 16) | value;
            } else {
                src += word + 1 == words || ((reg_skew & 0x40) && word + 2 == words) ?
                       reg_src_y : reg_src_x;
            }
            dst += word + 1 == words ? reg_dst_y : reg_dst_x;
        }
    }
    reg_src = src; reg_dst = dst; reg_y = 0; reg_ctrl = 0;
}
"""
    block = video[video.index("typedef struct PlanarBlit {"):
                  video.index("static PlanarBlit s_planarBlit;") + len("static PlanarBlit s_planarBlit;")]
    setup = function(video, "Video_Atari_BlitterSetup")
    setup = setup.replace("\n{\n", "\n{\n    blitterSetups++;\n", 1)
    builder = function(video, "Video_Atari_BuildSpriteBlitPlan")
    builder = builder.replace("\n{\n", "\n{\n    blitterPlanBuilds++;\n", 1)
    production = function(video, "Video_Atari_ViewportBlitter") + "\n" + setup + "\n" + block
    production += "\n" + builder + "\n" + function(video, "Video_Atari_BuildSpriteBlitPlans")
    if tiles:
        production += "\n" + function(video, "Video_Atari_BlitOpaque")
        production += "\n" + function(video, "Video_Atari_BlitTile")
    else:
        production += r"""
static bool Video_Atari_CursorRectOverlap(uint8 *base, uint16 first, uint16 end,
                                          uint16 y, uint16 height) {
    (void)base; (void)first; (void)end; (void)y; (void)height; return false;
}
#define Video_Atari_RefreshViewportCursorUnshifted(...) assert(false)
"""
    for name in ("Video_Atari_BlitMasked", "Video_Atari_ShiftSpriteWord",
                 "Video_Atari_RefreshViewportCursorUnshifted",
                 "Video_Atari_PresentPlanarSpriteUnshifted"):
        if name == "Video_Atari_RefreshViewportCursorUnshifted" and not tiles:
            continue
        body = function(video, name)
        if name == "Video_Atari_PresentPlanarSpriteUnshifted":
            body = body.replace("\n{\n", "\n{\n"
                "    if (plan != NULL) cachedPlanDraws++;\n"
                "    blitterPixels = (uintptr_t)pixels; blitterMasks = (uintptr_t)masks;\n"
                "    blitterReadStride = sourceWidth / 2;\n", 1)
        production += "\n" + body
    return blit_plan_type() + model + production.replace("(uint32)(size_t)", "(uintptr_t)")


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
static bool s_viewportPlanar = true, s_viewportSpriteReady = true, overlays, batchRepairs;
static ViewportSpriteMask s_viewportSpriteCache[512];
static uint16 *s_viewportSpriteMasks;
static unsigned decodes, encodes, overlayWrites, dirtyClears;
static unsigned compositions;
static bool pendingRepair;
static int16 repairLeft, repairTop, repairRight, repairBottom;
#define Warning(...) assert(false)
/* CACHE */
/* FREE */
static ViewportSpriteMask *GUI_ViewportSpriteMaskSlot(const uint8 *sprite) {
    for (unsigned i = 0; i < 70; i++) if (slots[i].sprite == sprite) return slots + i;
    assert(false); return NULL;
}
static void GUI_Widget_Viewport_RepairTiles(int16 left, int16 top, int16 right, int16 bottom) {
    assert(!pendingRepair && !(left & 15) && !(right & 15) && right > left);
    assert(left >= 0 && right <= 240 && top >= 40 && top < bottom && bottom <= 200);
    if (!batchRepairs) {
        assert(right - left == 16);
        assert((top - 40) / 16 == (bottom - 1 - 40) / 16);
    }
    pendingRepair = true;
    repairLeft = left; repairTop = top; repairRight = right; repairBottom = bottom;
}
static void GFX_Screen_SetDirtySource(unsigned source) { assert(source == DIRTY_SRC_SPRITE); }
static void GFX_Screen_ClearDirtyRect(uint16 l, uint16 t, uint16 r, uint16 b) {
    assert(!(l & 15) && !(r & 15) && l < r && r <= 240 && t >= 40 && t < b && b <= 200);
    assert(pendingRepair && l == repairLeft && t == repairTop &&
           r == repairRight && b == repairBottom);
    pendingRepair = false;
    dirtyClears++;
}
static uint8 *Video_Atari_PlanarBase(void) { return (uint8 *)visible; }
static bool Video_Atari_PlanarOverlaysOverlap(uint8 *base, uint16 x, uint16 y, uint16 w, uint16 h) {
    assert(base == (uint8 *)visible && !(x & 15) && !(w & 15) && y >= 40 && y + h <= 200);
    return overlays;
}
static bool Video_Atari_PlacementRectOverlap(uint8 *base, uint16 l, uint16 r, uint16 y, uint16 h) {
    assert(base == (uint8 *)visible && l < r && y >= 40 && y + h <= 200);
    return overlays;
}
static void Video_Atari_RefreshViewportCursor(uint8 *base, uint16 first, uint16 end,
                                             uint16 top, uint16 bottom,
                                             const uint16 *masks, uint16 stride) {
    (void)base; (void)first; (void)end; (void)top; (void)bottom; (void)masks; (void)stride;
    assert(false); /* This harness models placement overlaps, not a drawn cursor. */
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
static unsigned tile_count(int left, int top, int right, int bottom) {
    left = max(0, left & ~15); right = min(240, (right + 15) & ~15);
    top = max(40, top); bottom = min(200, bottom);
    if (left >= right || top >= bottom) return 0;
    return (right - left) / 16 * ((bottom - 40 + 15) / 16 - (top - 40) / 16);
}
static void check(unsigned id, int x, int y, int flags, bool recolour) {
    int ox = x, oy = y;
    unsigned before = dirtyClears;
    unsigned launches = blitterLaunches, setups = blitterSetups;
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
    unsigned portions = tile_count(ox, oy, ox + 23, oy + 27);
    assert(!pendingRepair && dirtyClears == before + (s_viewportBlitter ? !!portions : portions));
    assert(blitterLaunches == launches + (s_viewportBlitter && portions && !overlays ? 8 : 0));
    assert(blitterSetups == setups + (s_viewportBlitter && portions && !overlays ? 1 : 0));
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
    unsigned launches = blitterLaunches, setups = blitterSetups;
    int left = 0, top = 0, right = 23, bottom = 27;
    for (unsigned i = 0; i < layers->count; i++) {
        left = min(left, layers->layer[i].offsetX);
        top = min(top, layers->layer[i].offsetY);
        right = max(right, layers->layer[i].offsetX + 23);
        bottom = max(bottom, layers->layer[i].offsetY + 27);
    }
    assert(draw_layers(layers, x, y, flags | DRAWSPRITE_FLAG_CENTER | DRAWSPRITE_FLAG_WIDGETPOS |
                       DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_REMAP, palette, remap, 1));
    unsigned portions = tile_count(x - 11 + left, y + 40 - 13 + top,
                                  x - 11 + right, y + 40 - 13 + bottom);
    assert(!pendingRepair && dirtyClears == before + (s_viewportBlitter ? !!portions : portions));
    assert(blitterLaunches == launches + (s_viewportBlitter && portions && !overlays ? 8 : 0));
    assert(blitterSetups == setups + (s_viewportBlitter && portions && !overlays ? 1 : 0));
    assert(!memcmp(visible, expected, sizeof(visible)));
}
int main(int argc, char **argv) {
    unsigned before;
    ViewportPlanarSprite *saved;
    (void)argv;
    s_viewportBlitter = argc > 1;
    batchRepairs = s_viewportBlitter;
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
    s_viewportPlanarMasks = calloc(VIEWPORT_PLANAR_SPRITES * 320 * (s_viewportBlitter ? 4 : 1),
                                  sizeof(*s_viewportPlanarMasks));
    s_viewportPlanarComponents = calloc(VIEWPORT_PLANAR_COMPONENTS, sizeof(*s_viewportPlanarComponents));
    assert(s_viewportPlanarSprites && s_viewportPlanarMasks && s_viewportPlanarComponents);
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++)
        s_viewportPlanarSprites[i].masks = s_viewportPlanarMasks + i * 320 * (s_viewportBlitter ? 4 : 1);
    for (unsigned flags = 0; flags < 4; flags++) for (unsigned phase = 0; phase < 16; phase++) {
        check(0, 64 + phase, 60, flags, false);
        before = decodes;
        unsigned plans = blitterPlanBuilds, cached = cachedPlanDraws;
        check(0, 64 + phase, 60, flags, false);
        assert(decodes == before);
        assert(blitterPlanBuilds == plans);
        assert(cachedPlanDraws == cached + (s_viewportBlitter ? 1 : 0));
    }
    assert(decodes == 4 && encodes == 4);
    assert(compositions == (s_viewportBlitter ? 4 : 64));
    assert(blitterPlanBuilds == (s_viewportBlitter ? 4 * 16 : 0));
    if (s_viewportBlitter) assert(blitterLaunches && !(blitterLaunches % 8));
    for (unsigned flags = 0; flags < 4; flags++) {
        unsigned plans = blitterPlanBuilds;
        check(0, 64, 33, flags, false);
        check(0, 64, 191, flags, false);
        assert(blitterPlanBuilds == plans);
        check(0, -13, 33, flags, false);
        assert(blitterPlanBuilds == plans + (s_viewportBlitter ? 1 : 0));
        check(0, 231, 191, flags, false);
        assert(blitterPlanBuilds == plans + (s_viewportBlitter ? 2 : 0));
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
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) s_viewportPlanarSprites[i].key = 0;
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
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) s_viewportPlanarSprites[i].key = 0;
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
    composed = compositions;
    for (unsigned phase = 0; phase < 16; phase++) check_layers(&layers, 64 + phase, 50, 0);
    assert(decodes == before && encodes == encoded);
    if (s_viewportBlitter) assert(compositions == composed);
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
    if (s_viewportBlitter) {
        uint16 image[1280], masks[1280];
        overlays = false;
        for (unsigned stride = 16; stride <= 80; stride += 16) {
            unsigned groups = stride / 16;
            for (unsigned row = 0; row < 64; row++) for (unsigned group = 0; group < groups; group++) {
                uint16 mask = 0xa39f ^ (row * 131 + group * 911);
                for (unsigned p = 0; p < 4; p++) {
                    unsigned i = row * groups * 4 + group * 4 + p;
                    masks[i] = mask;
                    image[i] = (i * 137 + 41) & mask;
                }
            }
            for (unsigned edge = 0; edge < (groups == 1 ? 1u : 2u); edge++)
                for (unsigned phase = 0; phase < 16; phase++)
                    for (unsigned sourcePhase = 0; sourcePhase < 16; sourcePhase++) {
                        unsigned sourceX = (edge ? stride - 16 : 0) + sourcePhase;
                        unsigned remaining = stride - sourceX;
                        unsigned widths[] = {1, min(remaining, 16 - sourcePhase),
                                             min(remaining, 17 - sourcePhase), remaining};
                        unsigned heights[] = {1, 16, 64};
                        for (unsigned wi = 0; wi < 4; wi++) for (unsigned hi = 0; hi < 3; hi++) {
                            unsigned width = widths[wi], height = heights[hi], x = 64 + phase, y = 136;
                            for (unsigned i = 0; i < 16000; i++) visible[i] = expected[i] = i * 113 + 17;
                            for (unsigned row = 0; row < height; row++) for (unsigned col = 0; col < width; col++) {
                                unsigned source = row * groups * 4 + ((sourceX + col) / 16) * 4;
                                uint16 sb = 0x8000u >> ((sourceX + col) & 15);
                                uint16 db = 0x8000u >> ((x + col) & 15);
                                if (!(masks[source] & sb)) continue;
                                for (unsigned p = 0; p < 4; p++) {
                                    unsigned dest = (y + row) * 80 + ((x + col) / 16) * 4 + p;
                                    expected[dest] = (expected[dest] & (uint16)~db) |
                                        (image[source + p] & sb ? db : 0);
                                }
                            }
                            unsigned launches = blitterLaunches, setups = blitterSetups;
                            GUI_Widget_Viewport_RepairTiles(x & ~15, y, (x + width + 15) & ~15, y + height);
                            Video_Atari_PresentPlanarSpriteUnshifted(image, masks, stride, sourceX,
                                                                    width, height, x, y, NULL);
                            assert(!pendingRepair && blitterLaunches == launches + 8);
                            assert(blitterSetups == setups + 1);
                            assert(!memcmp(visible, expected, sizeof(visible)));
                        }
                    }
            /* Compare every full-image width/phase plan with calculated
             * geometry, including retained source padding and vertical clips. */
            for (unsigned width = 1; width <= stride; width++) {
                Video_Atari_SpriteBlitPlan plans[16];
                unsigned builds = blitterPlanBuilds;
                Video_Atari_BuildSpriteBlitPlans(plans, stride, width);
                assert(blitterPlanBuilds == builds + 16);
                for (unsigned phase = 0; phase < 16; phase++) {
                    Video_Atari_SpriteBlitPlan calculated;
                    Video_Atari_BuildSpriteBlitPlan(&calculated, stride, 0, width, phase);
                    assert(plans[phase].words == calculated.words);
                    assert(plans[phase].firstMask == calculated.firstMask);
                    assert(plans[phase].lastMask == calculated.lastMask);
                    assert(plans[phase].sourceXinc == calculated.sourceXinc);
                    assert(plans[phase].sourceYinc == calculated.sourceYinc);
                    assert(plans[phase].destinationYinc == calculated.destinationYinc);
                    assert(plans[phase].skew == calculated.skew);
                    for (unsigned top = 0; top < 2; top++) {
                        uint16 reference[16000];
                        unsigned offset = top * groups * 4;
                        for (unsigned i = 0; i < 16000; i++) visible[i] = i * 113 + 17;
                        GUI_Widget_Viewport_RepairTiles(64, 136, (64 + phase + width + 15) & ~15, 152);
                        Video_Atari_PresentPlanarSpriteUnshifted(image + offset, masks + offset,
                            stride, 0, width, 16, 64 + phase, 136, NULL);
                        memcpy(reference, visible, sizeof(reference));
                        for (unsigned i = 0; i < 16000; i++) visible[i] = i * 113 + 17;
                        builds = blitterPlanBuilds;
                        GUI_Widget_Viewport_RepairTiles(64, 136, (64 + phase + width + 15) & ~15, 152);
                        Video_Atari_PresentPlanarSpriteUnshifted(image + offset, masks + offset,
                            stride, 0, width, 16, 64 + phase, 136, &plans[phase]);
                        assert(blitterPlanBuilds == builds && !pendingRepair);
                        assert(!memcmp(reference, visible, sizeof(reference)));
                    }
                }
            }
        }
    }
    assert(dirtyClears);
    GUI_FreeViewportSpriteCache();
    assert(!s_viewportPlanarSprites && !s_viewportPlanar && !s_viewportSpriteReady && !s_viewportPlanarClock);
    assert(!s_viewportPlanarComponents && !s_viewportComponentClock);
    assert(!s_viewportPlanarMasks && !blitterLocks);
    assert(!draw(sprites[0], 64, 60, 0));
    return 0;
}
"""
        harness = harness.replace("/* FLAGS */", flags).replace("/* LAYER TYPES */", layer_types)
        harness = harness.replace("/* CACHE */", blit_plan_type() + cache)
        harness = harness.replace("/* FREE */", function(gui, "GUI_FreeViewportSpriteCache"))
        harness = harness.replace("/* MERGE */", function(video, "Video_Atari_PlanarMergePlain"))
        composer = function(video, "Video_Atari_ComposePlanarSprite")
        composer = composer.replace("\n{\n", "\n{\n    compositions++;\n", 1)
        harness = harness.replace("/* BLITTER */", composer + "\n" +
                                  function(video, "Video_Atari_PlanarCopyGroup") + "\n" +
                                  function(video, "Video_Atari_PublishViewportCursorRect") + "\n" +
                                  function(video, "Video_Atari_PresentPlanarSpriteOverlays") + "\n" +
                                  function(video, "Video_Atari_PublishPlanarSpritePlain") + "\n" +
                                  function(video, "Video_Atari_PresentPlanarSpriteStrided") + "\n" +
                                  function(video, "Video_Atari_PresentPlanarSprite") + "\n" +
                                  blitter_model(video))
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
            subprocess.run([str(binary), "blitter"], check=True)

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
