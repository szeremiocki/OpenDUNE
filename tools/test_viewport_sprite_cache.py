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
static unsigned evictionCandidates;
static unsigned lookupCandidates;
static unsigned lastHitMatches;
static unsigned layerComparisons;
static unsigned firstBinaryPosition;
static bool rejectSprite;
static int16 boundsLeft, boundsTop, boundsRight, boundsBottom;
static bool pendingRepair;
static int16 repairLeft, repairTop, repairRight, repairBottom;
#define Warning(...) assert(false)
/* CACHE */
static int compare_directory_keys(const void *left, const void *right) {
    const ViewportPlanarSpriteKey *a = left, *b = right;
    if (a->key != b->key) return a->key < b->key ? -1 : 1;
    if (!(a->key >> 20)) return 0;
    for (unsigned i = 0; i < 3; i++)
        if (a->layerKeys[i] != b->layerKeys[i])
            return a->layerKeys[i] < b->layerKeys[i] ? -1 : 1;
    return 0;
}
static void assert_directory(void) {
    unsigned count = 0, live = 0;
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++)
        if (s_viewportPlanarSprites[i].key) count++;
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) {
        const ViewportPlanarSpriteKey *key = s_viewportPlanarKeys + i;
        assert(key->sprite >= s_viewportPlanarSprites &&
               key->sprite < s_viewportPlanarSprites + VIEWPORT_PLANAR_SPRITES);
        assert(key->key == key->sprite->key);
        if (key->key) {
            live++;
            assert(i >= VIEWPORT_PLANAR_SPRITES - count);
            assert(!memcmp(key->layerKeys, key->sprite->layerKeys, sizeof(key->layerKeys)));
            if (!(key->key >> 20))
                assert(!key->layerKeys[0] && !key->layerKeys[1] && !key->layerKeys[2]);
        } else {
            assert(i < VIEWPORT_PLANAR_SPRITES - count);
            const uint32 zeros[3] = {0};
            assert(!memcmp(key->layerKeys, zeros, sizeof(zeros)));
        }
        assert(key->sprite->masks == s_viewportPlanarMasks +
               (key->sprite - s_viewportPlanarSprites) * 320 * (batchRepairs ? 4 : 1));
        if (i) assert(compare_directory_keys(key - 1, key) <= (key->key ? -1 : 0));
        for (unsigned j = 0; j < i; j++) assert(s_viewportPlanarKeys[j].sprite != key->sprite);
    }
    assert(count == live);
    assert(s_viewportPlanarLastHitPosition == VIEWPORT_PLANAR_SPRITES ||
           s_viewportPlanarKeys[s_viewportPlanarLastHitPosition].key != 0);
}
static void rebuild_directory(void) {
    s_viewportPlanarLastHitPosition = VIEWPORT_PLANAR_SPRITES;
    memset(s_viewportPlanarKeys, 0, sizeof(s_viewportPlanarKeys));
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) {
        ViewportPlanarSprite *entry = s_viewportPlanarSprites + i;
        ViewportPlanarSpriteKey *key = s_viewportPlanarKeys + i;
        key->key = entry->key;
        if (entry->key) memcpy(key->layerKeys, entry->layerKeys, sizeof(key->layerKeys));
        key->sprite = entry;
    }
    qsort(s_viewportPlanarKeys, VIEWPORT_PLANAR_SPRITES,
          sizeof(*s_viewportPlanarKeys), compare_directory_keys);
    assert_directory();
}
static ViewportPlanarSprite *expected_sprite_victim(void) {
    ViewportPlanarSprite *oldest = s_viewportPlanarSprites;
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) {
        ViewportPlanarSprite *candidate = s_viewportPlanarSprites + i;
        if (!candidate->key) return candidate;
        if (candidate->used < oldest->used) oldest = candidate;
    }
    return oldest;
}
static ViewportPlanarComponent *expected_component_victim(void) {
    ViewportPlanarComponent *oldest = s_viewportPlanarComponents;
    for (unsigned i = 0; i < VIEWPORT_PLANAR_COMPONENTS; i++) {
        ViewportPlanarComponent *candidate = s_viewportPlanarComponents + i;
        if (!candidate->key) return candidate;
        if (candidate->used < oldest->used) oldest = candidate;
    }
    return oldest;
}
/* FREE */
static void GFX_Screen_SetViewportPlanar(bool active) { (void)active; }
/* PLANAR SCOPE */
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
static bool GUI_Widget_Viewport_ShouldDrawSprite(int16 left, int16 top, int16 right, int16 bottom) {
    boundsLeft = left; boundsTop = top; boundsRight = right; boundsBottom = bottom;
    return !rejectSprite;
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
    if (id == 0) id = 111;
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
    if (portions) {
        assert(boundsLeft == ox && boundsTop == oy && boundsRight == ox + 23 && boundsBottom == oy + 27);
        rejectSprite = true;
        if (recolour) assert(draw(sprites[id], x, y, flags, palette, remap, 1));
        else if (flags & DRAWSPRITE_FLAG_PAL) assert(draw(sprites[id], x, y, flags, palette));
        else assert(draw(sprites[id], x, y, flags));
        rejectSprite = false;
    }
    assert(!pendingRepair && dirtyClears == before + (s_viewportBlitter ? !!portions : portions));
    assert(blitterLaunches == launches + (s_viewportBlitter && portions && !overlays ? 8 : 0));
    assert(blitterSetups == setups + (s_viewportBlitter && portions && !overlays ? 1 : 0));
    assert(!memcmp(visible, expected, sizeof(visible)));
}
static bool draw_layers(const GUI_SpriteLayers *layers, int16 x, int16 y, int flags, ...) {
    va_list ap;
    bool result;
    va_start(ap, flags);
    result = GUI_ViewportPlanarSprite(sprites[0], 111, 0, x, y, flags, &ap, layers);
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
    if (portions) {
        assert(boundsLeft == x - 11 + left && boundsTop == y + 40 - 13 + top &&
               boundsRight == x - 11 + right && boundsBottom == y + 40 - 13 + bottom);
        rejectSprite = true;
        assert(draw_layers(layers, x, y, flags | DRAWSPRITE_FLAG_CENTER | DRAWSPRITE_FLAG_WIDGETPOS |
                           DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_REMAP, palette, remap, 1));
        rejectSprite = false;
    }
    assert(!pendingRepair && dirtyClears == before + (s_viewportBlitter ? !!portions : portions));
    assert(blitterLaunches == launches + (s_viewportBlitter && portions && !overlays ? 8 : 0));
    assert(blitterSetups == setups + (s_viewportBlitter && portions && !overlays ? 1 : 0));
    assert(!memcmp(visible, expected, sizeof(visible)));
}
static void append_key_field(uint32 words[4], unsigned *position,
                             uint32 value, unsigned width) {
    for (unsigned bit = 0; bit < width; bit++, (*position)++)
        if ((value >> bit) & 1)
            words[*position / 32] |= (uint32)1 << (*position % 32);
}
static void check_compact_key_inputs(uint16 spriteID, uint8 colourHouse, int flags,
                                     bool highlighted, int16 x, bool blitter,
                                     const GUI_SpriteLayers *layers) {
    ViewportCompositeKey actual;
    uint32 reference[4] = {0};
    unsigned position = 0;
    memset(&actual, 0xa5, sizeof(actual));
    GUI_ViewportBuildCompositeKey(&actual, spriteID, colourHouse, flags,
                                  highlighted, x, blitter, layers);
    append_key_field(reference, &position, spriteID, 9);
    append_key_field(reference, &position,
                     colourHouse == GUI_SPRITE_COLOUR_EMBEDDED ? 6 : colourHouse, 3);
    append_key_field(reference, &position, flags & 3, 2);
    append_key_field(reference, &position, highlighted, 1);
    append_key_field(reference, &position, blitter ? 0 : (uint16)x % 16, 4);
    append_key_field(reference, &position, !!(flags & DRAWSPRITE_FLAG_CENTER), 1);
    for (unsigned i = 0; i < 4; i++) {
        if (!layers || i >= layers->count) {
            append_key_field(reference, &position, 0, 26);
            continue;
        }
        const GUI_SpriteLayer *layer = &layers->layer[i];
        append_key_field(reference, &position, layer->spriteID, 9);
        append_key_field(reference, &position,
                         layer->colourHouse == GUI_SPRITE_COLOUR_EMBEDDED ? 6 : layer->colourHouse, 3);
        append_key_field(reference, &position, layer->flags & 3, 2);
        append_key_field(reference, &position, layer->offsetX & 63, 6);
        append_key_field(reference, &position, layer->offsetY & 63, 6);
    }
    assert(position == 124 && actual.main == reference[0] && actual.main);
    if (layers && layers->count) {
        assert(!memcmp(actual.tail, reference + 1, sizeof(actual.tail)));
        assert((actual.tail[2] & 0xf0000000UL) == 0);
    } else {
        for (unsigned i = 0; i < 3; i++) assert(actual.tail[i] == 0xa5a5a5a5UL);
    }
}
static void check_compact_key(uint32 base, const GUI_SpriteLayers *layers) {
    unsigned colour = (base >> 9) & 7;
    int flags = (base >> 12) & 3;
    if (base & 0x80000u) flags |= DRAWSPRITE_FLAG_CENTER;
    check_compact_key_inputs(base & 511,
                            colour == 6 ? GUI_SPRITE_COLOUR_EMBEDDED : colour,
                            flags, !!(base & 0x4000u), (base >> 15) & 15,
                            false, layers);
}
static uint32 next_key_random(uint32 *state) {
    *state = *state * 1664525u + 1013904223u;
    return *state;
}
static void check_compact_keys(void) {
    assert(sizeof(ViewportCompositeKey) == 16);
    assert(sizeof(s_viewportPlanarSprites[0].layerKeys) == 12);
    assert(sizeof(s_viewportPlanarKeys[0].layerKeys) == 12);
    GUI_SpriteLayers full = {0}, empty = {0};
    ViewportCompositeKey reused;
    full.count = 4;
    for (unsigned i = 0; i < full.count; i++) {
        full.layer[i].spriteID = 354;
        full.layer[i].colourHouse = GUI_SPRITE_COLOUR_EMBEDDED;
        full.layer[i].flags = 3;
        full.layer[i].offsetX = -32;
        full.layer[i].offsetY = 31;
    }
    for (unsigned i = 0; i < 2; i++) {
        GUI_ViewportBuildCompositeKey(&reused, 354, 0, 0, false, 0, true, &full);
        assert(reused.main >> 20);
        assert(reused.tail[0] && reused.tail[1] && reused.tail[2]);
        uint32 tails[3];
        memcpy(tails, reused.tail, sizeof(tails));
        GUI_ViewportBuildCompositeKey(&reused, 354, 0, 0, false, 0, true, i ? &empty : NULL);
        assert(reused.main == 354);
        assert(!memcmp(reused.tail, tails, sizeof(tails)));
    }
    check_compact_key(1, NULL);
    for (unsigned id = 1; id <= 354; id++) {
        check_compact_key(id, NULL);
        check_compact_key(id | 0xffc00u, NULL);
    }
    for (unsigned colour = 0; colour <= 6; colour++)
        for (unsigned flips = 0; flips < 4; flips++)
            for (unsigned highlighted = 0; highlighted < 2; highlighted++)
                for (unsigned centered = 0; centered < 2; centered++)
                    for (unsigned blitter = 0; blitter < 2; blitter++)
                        for (int x = -17; x <= 31; x++) {
                            int flags = flips | DRAWSPRITE_FLAG_WIDGETPOS |
                                        DRAWSPRITE_FLAG_PAL | DRAWSPRITE_FLAG_REMAP;
                            if (centered) flags |= DRAWSPRITE_FLAG_CENTER;
                            check_compact_key_inputs(354,
                                colour == 6 ? GUI_SPRITE_COLOUR_EMBEDDED : colour,
                                flags, highlighted, x, blitter, NULL);
                        }
    for (unsigned count = 0; count <= 4; count++) {
        GUI_SpriteLayers layers = {0};
        layers.count = count;
        for (unsigned i = 0; i < count; i++) {
            layers.layer[i].spriteID = 354;
            layers.layer[i].colourHouse = GUI_SPRITE_COLOUR_EMBEDDED;
            layers.layer[i].flags = 3;
            layers.layer[i].offsetX = -32;
            layers.layer[i].offsetY = 31;
        }
        check_compact_key(0xffd62u, &layers);
        for (unsigned i = 0; i < count; i++) {
            GUI_SpriteLayer saved = layers.layer[i];
            GUI_SpriteLayer *layer = &layers.layer[i];
            for (unsigned id = 1; id <= 354; id++) {
                layer->spriteID = id;
                check_compact_key(0xffd62u, &layers);
            }
            *layer = saved;
            for (unsigned colour = 0; colour <= 6; colour++) {
                layer->colourHouse = colour == 6 ? GUI_SPRITE_COLOUR_EMBEDDED : colour;
                check_compact_key(0xffd62u, &layers);
            }
            *layer = saved;
            for (unsigned flags = 0; flags < 4; flags++) {
                layer->flags = flags;
                check_compact_key(0xffd62u, &layers);
            }
            *layer = saved;
            for (int offset = -32; offset <= 31; offset++) {
                layer->offsetX = offset;
                check_compact_key(0xffd62u, &layers);
                layer->offsetX = saved.offsetX;
                layer->offsetY = offset;
                check_compact_key(0xffd62u, &layers);
                layer->offsetY = saved.offsetY;
            }
        }
    }
    uint32 state = 0x98765432u;
    for (unsigned trial = 0; trial < 4096; trial++) {
        GUI_SpriteLayers layers = {0};
        layers.count = next_key_random(&state) % 5;
        uint32 base = (next_key_random(&state) & 0xff000u) |
                      ((next_key_random(&state) % 7) << 9) |
                      (next_key_random(&state) % 354 + 1);
        for (unsigned i = 0; i < layers.count; i++) {
            GUI_SpriteLayer *layer = &layers.layer[i];
            layer->spriteID = next_key_random(&state) % 354 + 1;
            unsigned colour = next_key_random(&state) % 7;
            layer->colourHouse = colour == 6 ? GUI_SPRITE_COLOUR_EMBEDDED : colour;
            layer->flags = next_key_random(&state) & 3;
            layer->offsetX = (int)(next_key_random(&state) & 63) - 32;
            layer->offsetY = (int)(next_key_random(&state) & 63) - 32;
        }
        check_compact_key(base, &layers);
    }
}
int main(int argc, char **argv) {
    unsigned before;
    ViewportPlanarSprite *saved;
    (void)argv;
    check_compact_keys();
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
    g_sprites[111] = sprites[0];
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
    rebuild_directory();
    uint16 emptyPosition = 99;
    const uint32 emptyLayers[3] = {0};
    assert(!draw_identity(0, GUI_SPRITE_COLOUR_EMBEDDED, 0));
    assert(!GUI_ViewportPlanarComponent(slots, 0, GUI_SPRITE_COLOUR_EMBEDDED, 0, NULL, NULL));
    GUI_SpriteLayers mouseLayer = {1, {{0, GUI_SPRITE_COLOUR_EMBEDDED, 0, 0, 0, {0}}}};
    assert(!draw_layers(&mouseLayer, 64, 60, DRAWSPRITE_FLAG_PAL, palette));
    assert(!s_viewportPlanarClock && !s_viewportComponentClock && !decodes && !encodes);
    assert_directory();
    assert(!GUI_ViewportFindPlanarSprite(0x80000000UL, emptyLayers, &emptyPosition));
    assert(emptyPosition == 64 && lookupCandidates == 6 && firstBinaryPosition == 32);
    for (unsigned flags = 0; flags < 4; flags++) for (unsigned phase = 0; phase < 16; phase++) {
        check(0, 64 + phase, 60, flags, false);
        before = decodes;
        unsigned plans = blitterPlanBuilds, cached = cachedPlanDraws;
        unsigned scans = evictionCandidates;
        unsigned probes = lookupCandidates;
        check(0, 64 + phase, 60, flags, false);
        assert(evictionCandidates == scans);
        assert(lookupCandidates > probes && lookupCandidates <= probes + 14);
        assert_directory();
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
    assert(!draw_identity(111, GUI_SPRITE_COLOUR_UNKNOWN, DRAWSPRITE_FLAG_PAL, palette));
    assert(!draw_identity(111, 0, 0));
    assert(decodes == before);
    /* Explicit house 0, embedded palette, and another house are separate keys. */
    assert(draw_identity(111, 0, DRAWSPRITE_FLAG_PAL, palette));
    assert(draw_identity(111, 1, DRAWSPRITE_FLAG_PAL, palette));
    before = decodes;
    assert(draw_identity(111, 0, DRAWSPRITE_FLAG_PAL, palette));
    assert(draw_identity(111, 1, DRAWSPRITE_FLAG_PAL, palette));
    assert(decodes == before);
    for (unsigned id = 1; id < 70; id++) check(id, 64, 60, 0, false);
    before = decodes;
    check(69, 64, 60, 0, false);
    assert(decodes == before);
    check(0, 64, 60, 0, false);
    assert(decodes == before + 1);
    s_viewportPlanarClock = 65535;
    check(0, 64, 60, 0, false);
    assert(s_viewportPlanarClock == 2 && decodes == before + 1);
    before = decodes;
    ViewportPlanarSpriteKey savedDirectory[64];
    memcpy(savedDirectory, s_viewportPlanarKeys, sizeof(savedDirectory));
    assert(draw(sprites[0], -100, -100, 0) && decodes == before);
    assert(!memcmp(savedDirectory, s_viewportPlanarKeys, sizeof(savedDirectory)));
    assert(!draw(sprites[0], 64, 60, DRAWSPRITE_FLAG_ZOOM));
    saved = s_viewportPlanarSprites; s_viewportPlanarSprites = NULL;
    assert(!draw(sprites[0], 64, 60, 0));
    s_viewportPlanarSprites = saved;
    ViewportPlanarComponent *savedComponents = s_viewportPlanarComponents;
    s_viewportPlanarComponents = NULL;
    assert(!draw(sprites[0], 64, 60, 0));
    s_viewportPlanarComponents = savedComponents;
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) s_viewportPlanarSprites[i].key = 0;
    rebuild_directory();
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
    rebuild_directory();
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
    ViewportPlanarComponent *component = GUI_ViewportPlanarComponent(slots, 111, 0, 0, palette, remap);
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
    /* A late hit must not select earlier empty slots for eviction. */
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) s_viewportPlanarSprites[i].key = 0;
    rebuild_directory();
    memset(s_viewportPlanarComponents, 0, VIEWPORT_PLANAR_COMPONENTS * sizeof(*s_viewportPlanarComponents));
    check(0, 64, 60, 0, false);
    uint16 *lateMasks = s_viewportPlanarSprites[63].masks;
    memcpy(lateMasks, s_viewportPlanarSprites[0].masks,
           320 * (s_viewportBlitter ? 4 : 1) * sizeof(*lateMasks));
    s_viewportPlanarSprites[63] = s_viewportPlanarSprites[0];
    s_viewportPlanarSprites[63].masks = lateMasks;
    s_viewportPlanarSprites[0].key = 0;
    s_viewportPlanarComponents[63] = s_viewportPlanarComponents[0];
    s_viewportPlanarComponents[0].key = 0;
    rebuild_directory();
    unsigned scans = evictionCandidates;
    unsigned probes = lookupCandidates;
    s_viewportPlanarClock = 65535;
    check(0, 64, 60, 0, false);
    assert(evictionCandidates == scans && s_viewportPlanarClock == 2);
    assert(lookupCandidates == probes + 7);
    assert(s_viewportPlanarSprites[63].used == 2 && !s_viewportPlanarSprites[0].key);
    /* Physical slot order is independent of directory order. */
    s_viewportPlanarSprites[0].key = s_viewportPlanarSprites[63].key;
    s_viewportPlanarSprites[63].key = 0;
    rebuild_directory();
    probes = lookupCandidates;
    check(0, 64, 60, 0, false);
    assert(lookupCandidates == probes + 7);
    assert(evictionCandidates == scans && s_viewportPlanarSprites[0].used == 4);
    /* Same body with and without a layer must remain distinct. */
    s_viewportPlanarSprites[1].key = s_viewportPlanarSprites[0].key | (0xc06u << 20);
    s_viewportPlanarSprites[1].layerKeys[0] = 1;
    rebuild_directory();
    probes = lookupCandidates;
    check(0, 64, 60, 0, false);
    assert(lookupCandidates == probes + 6);
    assert(evictionCandidates == scans);
    s_viewportComponentClock = 65535;
    component = GUI_ViewportPlanarComponent(slots, 111, GUI_SPRITE_COLOUR_EMBEDDED, 0, NULL, NULL);
    assert(component == s_viewportPlanarComponents + 63 && component->used == 1);
    assert(evictionCandidates == scans && !s_viewportPlanarComponents[0].key);
    for (unsigned empty = 0; empty < 2; empty++) {
        for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) {
            s_viewportPlanarSprites[i].key = 0xdead0000UL | i;
            s_viewportPlanarSprites[i].used = 9;
        }
        for (unsigned i = 0; i < VIEWPORT_PLANAR_COMPONENTS; i++) {
            s_viewportPlanarComponents[i].key = 0xdead0000UL | i;
            s_viewportPlanarComponents[i].used = 9;
        }
        s_viewportPlanarSprites[7].used = s_viewportPlanarSprites[19].used = 3;
        s_viewportPlanarComponents[7].used = s_viewportPlanarComponents[19].used = 3;
        if (empty) {
            s_viewportPlanarSprites[11].key = s_viewportPlanarSprites[23].key = 0;
            s_viewportPlanarComponents[11].key = s_viewportPlanarComponents[23].key = 0;
        }
        rebuild_directory();
        scans = evictionCandidates;
        probes = lookupCandidates;
        check(0, 64, 60, 0, false);
        assert(evictionCandidates == scans + VIEWPORT_PLANAR_SPRITES + VIEWPORT_PLANAR_COMPONENTS);
        unsigned victim = empty ? 11 : 7;
        assert(lookupCandidates > probes && lookupCandidates <= probes + 14);
        assert_directory();
        assert(s_viewportPlanarSprites[victim].key == 0x00000c6fUL);
        assert(s_viewportPlanarComponents[victim].key == 0x80000c6fUL);
        assert(s_viewportPlanarSprites[19].key == 0xdead0013UL);
        assert(s_viewportPlanarComponents[19].key == 0xdead0013UL);
        if (empty) {
            assert(!s_viewportPlanarSprites[23].key && !s_viewportPlanarComponents[23].key);
        }
    }
    /* Exercise insertion at both ends and every packed word comparison, including
     * unsigned values and absent layers, independently of sprite decoding. */
    for (unsigned differing = 0; differing < 4; differing++) {
        for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) s_viewportPlanarSprites[i].key = 0;
        rebuild_directory();
        for (unsigned n = 0; n < 64; n++) {
            unsigned slot = (n * 37) & 63;
            uint32 words[4] = {0x80000001UL, 0, 0, 0};
            words[differing] = 0x80000000UL + slot * 2;
            uint16 position;
            probes = lookupCandidates;
            assert(!GUI_ViewportFindPlanarSprite(words[0], words + 1, &position));
            assert(lookupCandidates <= probes + 8);
            assert(firstBinaryPosition == 32);
            ViewportPlanarSprite *previousHit =
                s_viewportPlanarLastHitPosition < VIEWPORT_PLANAR_SPRITES ?
                s_viewportPlanarKeys[s_viewportPlanarLastHitPosition].sprite : NULL;
            ViewportPlanarSprite *entry = s_viewportPlanarSprites + slot;
            entry->key = words[0];
            memcpy(entry->layerKeys, words + 1, sizeof(entry->layerKeys));
            GUI_ViewportIndexPlanarSprite(entry, position);
            assert_directory();
            if (previousHit)
                assert(s_viewportPlanarKeys[s_viewportPlanarLastHitPosition].sprite == previousHit);
            /* Check every occupancy from one through 64, including searches
             * on either side of the live suffix and hints shifted by insertion. */
            for (unsigned index = 64 - n - 1; index < 64; index++) {
                const ViewportPlanarSpriteKey *key = s_viewportPlanarKeys + index;
                probes = lookupCandidates;
                assert(GUI_ViewportFindPlanarSprite(key->key, key->layerKeys, &position) == key->sprite);
                assert(position == index && lookupCandidates <= probes + 8);
            }
            uint16 last = s_viewportPlanarLastHitPosition;
            unsigned comparisons = layerComparisons;
            assert(!GUI_ViewportFindPlanarSprite(1, emptyLayers, &position));
            assert(position == 64 - n - 1 && firstBinaryPosition == 32);
            assert(s_viewportPlanarLastHitPosition == last);
            assert(!GUI_ViewportFindPlanarSprite(0xffffffffUL, emptyLayers, &position));
            assert(position == 64 && firstBinaryPosition == 32);
            assert(s_viewportPlanarLastHitPosition == last);
            assert(layerComparisons == comparisons);
        }
        for (unsigned slot = 0; slot < 64; slot++) {
            ViewportPlanarSprite *entry = s_viewportPlanarSprites + slot;
            uint16 position;
            probes = lookupCandidates;
            assert(GUI_ViewportFindPlanarSprite(entry->key, entry->layerKeys, &position) == entry);
            assert(lookupCandidates > probes && lookupCandidates <= probes + 8);
            assert(position == slot);
            unsigned matches = lastHitMatches;
            unsigned comparisons = layerComparisons;
            probes = lookupCandidates;
            assert(GUI_ViewportFindPlanarSprite(entry->key, entry->layerKeys, &position) == entry);
            assert(position == slot && lookupCandidates == probes + 1);
            assert(lastHitMatches == matches + 1);
            assert(layerComparisons == comparisons);
            uint32 words[4];
            words[0] = entry->key;
            memcpy(words + 1, entry->layerKeys, sizeof(entry->layerKeys));
            words[differing]++;
            probes = lookupCandidates;
            assert(!GUI_ViewportFindPlanarSprite(words[0], words + 1, &position));
            assert(position == slot + 1 && lookupCandidates <= probes + 8);
            assert(s_viewportPlanarLastHitPosition == slot);
            assert(firstBinaryPosition == 32);
        }
        /* Replace a high key with a low key and then a low key with a high
         * key: removal must adjust the saved insertion position correctly. */
        for (unsigned pass = 0; pass < 4; pass++) {
            ViewportPlanarSprite *entry = s_viewportPlanarSprites + (pass ? 0 : 63);
            uint32 words[4] = {0x80000001UL, 0, 0, 0};
            words[differing] = pass & 1 ? 0xffffffffUL : pass == 0 ? 1 : 2;
            uint16 position;
            if (pass >= 2) {
                ViewportPlanarSprite *middle = s_viewportPlanarSprites + 32;
                assert(GUI_ViewportFindPlanarSprite(middle->key, middle->layerKeys, &position) == middle);
            }
            assert(!GUI_ViewportFindPlanarSprite(words[0], words + 1, &position));
            ViewportPlanarSprite *previousHit =
                s_viewportPlanarKeys[s_viewportPlanarLastHitPosition].sprite;
            uint32 oldKey = entry->key, oldLayers[3];
            memcpy(oldLayers, entry->layerKeys, sizeof(oldLayers));
            entry->key = words[0];
            memcpy(entry->layerKeys, words + 1, sizeof(entry->layerKeys));
            GUI_ViewportIndexPlanarSprite(entry, position);
            assert_directory();
            if (entry == previousHit) {
                assert(s_viewportPlanarLastHitPosition == VIEWPORT_PLANAR_SPRITES);
            } else {
                assert(s_viewportPlanarKeys[s_viewportPlanarLastHitPosition].sprite == previousHit);
                probes = lookupCandidates;
                assert(GUI_ViewportFindPlanarSprite(previousHit->key, previousHit->layerKeys,
                                                   &position) == previousHit);
                assert(lookupCandidates == probes + 1);
            }
            assert(!GUI_ViewportFindPlanarSprite(oldKey, oldLayers, &position));
            assert(GUI_ViewportFindPlanarSprite(words[0], words + 1, &position) == entry);
            assert(position == (pass & 1 ? 63 : pass == 0 ? 0 : 1));
        }
    }
    /* Every layerless hit/miss accepts an unreadable requested tail, including
     * the hint shortcut and every directory occupancy. */
    for (unsigned count = 0; count <= 64; count++) {
        for (unsigned slot = 0; slot < 64; slot++) {
            ViewportPlanarSprite *entry = s_viewportPlanarSprites + slot;
            entry->key = slot < count ? slot * 2 + 1 : 0;
            memset(entry->layerKeys, 0, sizeof(entry->layerKeys));
        }
        rebuild_directory();
        for (unsigned key = 1; key <= 129; key++) {
            uint16 position;
            unsigned comparisons = layerComparisons;
            ViewportPlanarSprite *entry = GUI_ViewportFindPlanarSprite(key, NULL, &position);
            bool found = (key & 1) && key / 2 < count;
            assert(entry == (found ? s_viewportPlanarSprites + key / 2 : NULL));
            assert(position == 64 - count + min(count, key / 2));
            assert(layerComparisons == comparisons);
            if (entry) {
                unsigned matches = lastHitMatches;
                assert(GUI_ViewportFindPlanarSprite(key, NULL, &position) == entry);
                assert(lastHitMatches == matches + 1 && layerComparisons == comparisons);
            }
        }
    }
    /* Real insertions/evictions and layered hits retain fixed image slots. */
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) s_viewportPlanarSprites[i].key = 0;
    rebuild_directory();
    for (unsigned id = 0; id < 70; id++) {
        check(id, 64, 60, 0, false);
        assert_directory();
    }
    check_layers(&layers, 64, 50, 0);
    assert_directory();
    ViewportPlanarSprite images[64];
    memcpy(images, s_viewportPlanarSprites, sizeof(images));
    before = decodes; encoded = encodes; composed = compositions;
    GUI_SetViewportPlanar(false);
    GUI_SetViewportPlanar(true);
    check_layers(&layers, 64, 50, 0);
    assert(decodes == before && encodes == encoded && compositions == composed);
    for (unsigned i = 0; i < 64; i++) {
        ViewportPlanarSprite actual = s_viewportPlanarSprites[i];
        actual.used = images[i].used;
        assert(!memcmp(&actual, images + i, sizeof(actual)));
    }
    assert_directory();
    GUI_FreeViewportSpriteCache();
    assert(!s_viewportPlanarSprites && !s_viewportPlanar && !s_viewportSpriteReady && !s_viewportPlanarClock);
    assert(!s_viewportPlanarComponents && !s_viewportComponentClock);
    assert(!s_viewportPlanarMasks && !blitterLocks);
    for (unsigned i = 0; i < VIEWPORT_PLANAR_SPRITES; i++) {
        assert(!s_viewportPlanarKeys[i].key && !s_viewportPlanarKeys[i].sprite);
        for (unsigned word = 0; word < 3; word++) assert(!s_viewportPlanarKeys[i].layerKeys[word]);
    }
    assert(s_viewportPlanarLastHitPosition == VIEWPORT_PLANAR_SPRITES);
    assert(!draw(sprites[0], 64, 60, 0));
    return 0;
}
"""
        harness = harness.replace("/* FLAGS */", flags).replace("/* LAYER TYPES */", layer_types)
        harness = harness.replace("/* CACHE */", blit_plan_type() + cache)
        harness = harness.replace("/* FREE */", function(gui, "GUI_FreeViewportSpriteCache"))
        harness = harness.replace("/* PLANAR SCOPE */", function(gui, "GUI_SetViewportPlanar"))
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
        finder = function(gui, "GUI_ViewportFindPlanarSprite")
        finder = finder.replace("\n{\n", "\n{\n    assert_directory();\n", 1)
        finder = finder.replace("if (s_viewportPlanarLastHitPosition < VIEWPORT_PLANAR_SPRITES) {",
                                "if (s_viewportPlanarLastHitPosition < VIEWPORT_PLANAR_SPRITES) {\n"
                                "        lookupCandidates++;")
        finder = finder.replace("*position = s_viewportPlanarLastHitPosition;",
                                "lastHitMatches++;\n"
                                "            *position = s_viewportPlanarLastHitPosition;")
        nodes = re.findall(r"^\s*VIEWPORT_SEARCH_NODE\((\d+),", finder, re.M)
        self.assertEqual(sorted(map(int, nodes)), list(range(64)))
        self.assertNotRegex(finder, r"\b(?:while|for)\s*\(")
        finder = finder.replace("\n{\n", "\n{\n    bool firstBinary = true;\n", 1)
        node_probe = "const ViewportPlanarSpriteKey *candidate = &s_viewportPlanarKeys[slot];"
        self.assertEqual(finder.count(node_probe), 1)
        finder = finder.replace(node_probe, node_probe + " \\\n"
                                "        lookupCandidates++; \\\n"
                                "        if (firstBinary) firstBinaryPosition = (slot); \\\n"
                                "        firstBinary = false;")
        indexer = function(gui, "GUI_ViewportIndexPlanarSprite")
        indexer = indexer[:-2] + "    assert_directory();\n}\n"
        comparator = function(gui, "GUI_ViewportCompareLayerKeys")
        comparator = comparator.replace("\n{\n", "\n{\n    layerComparisons++;\n", 1)
        lookup = function(gui, "GUI_ViewportBuildCompositeKey") + "\n"
        lookup += comparator + "\n" + finder + "\n" + indexer
        lookup += "\n" + function(gui, "GUI_ViewportDecodeLayer")
        for name, victim_check in (("GUI_ViewportPlanarComponent", "expected_component_victim"),
                                   ("GUI_ViewportPlanarSprite", "expected_sprite_victim")):
            body = function(gui, name)
            self.assertEqual(body.count("if (victim == NULL"), 1)
            self.assertEqual(body.count("entry = victim;"), 1)
            body = body.replace("if (victim == NULL", "evictionCandidates++;\n\t\t\tif (victim == NULL")
            body = body.replace("entry = victim;",
                                "assert(victim == " + victim_check + "());\n\t\tentry = victim;")
            lookup += "\n" + body
        harness = harness.replace("/* LOOKUP */", lookup)
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
static void GUI_Widget_Viewport_InvalidateSpriteDamage(void) {}
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
