"""Exercise the actual mono glyph, publication and overlay paths on native bitmaps."""

from pathlib import Path
import unittest

from tools.test_dither_preparation import backend_declarations, glyph_backend, run_harness, surface_backend
from tools.test_viewport_sprite_cache import blit_plan_type, blitter_model, function, inactive_display_list


ROOT = Path(__file__).resolve().parents[1]
VIDEO = (ROOT / "src/video/video_atari.c").read_text()
COMMON = r"""
#define TOS
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "atari_mono.h"
#include "atari_mono_palette.h"
#define Video_Atari_Mono() true
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
#define lengthof(a) (sizeof(a) / sizeof(*(a)))
static bool s_monoWhiteIsOne = true;
static inline unsigned pixel(const uint16 *p, unsigned stride, unsigned x, unsigned y)
{
    return !!(p[y * stride + x / 16] & (0x8000u >> (x & 15)));
}
static void put(uint16 *p, unsigned stride, unsigned x, unsigned y, unsigned value)
{
    uint16 bit = 0x8000u >> (x & 15), *word = &p[y * stride + x / 16];
    *word = (*word & ~bit) | (value ? bit : 0);
}
"""


class MonoRenderingTest(unittest.TestCase):
    def test_semantic_highlights_preserve_native_effects(self):
        recipes = VIDEO[VIDEO.index("#define HL_ZERO"):
                        VIDEO.index("\nvoid Video_Atari_SetSpriteHighlight")]
        production = "\n".join(function(VIDEO, name) for name in (
            "Video_Atari_SetSpriteHighlight", "Video_Atari_HighlightPixels"))
        harness = COMMON + r"""
#undef Video_Atari_Mono
static bool nativeMono;
#define Video_Atari_Mono() nativeMono
#define VIDEO_ATARI_HIGHLIGHT_EFFECTS 9
static uint16 s_spriteHighlightEffect;
/* RECIPES */
/* PRODUCTION */
int main(void)
{
    uint16 pixels[8], masks[8], output[8], expected[8];
    (void)pixel; (void)put;
    for (unsigned i = 0; i < 8; i++) {
        masks[i] = i < 4 ? 0x936f : 0x7b15;
        pixels[i] = (0x7d13u ^ (i * 137u)) & masks[i];
    }
    for (unsigned mode = 0; mode < 2; mode++)
    for (unsigned polarity = 0; polarity < 2; polarity++)
    for (unsigned effect = 1; effect <= 9; effect++) {
        nativeMono = mode; s_monoWhiteIsOne = polarity;
        Video_Atari_SetSpriteHighlight(effect);
        assert(s_spriteHighlightEffect == effect);
        memset(expected, 0, sizeof(expected));
        if (mode)
            for (unsigned i = 0; i < 8; i++) expected[i] = ~pixels[i];
        else
            for (unsigned g = 0; g < 2; g++)
            for (unsigned x = 0; x < 16; x++) {
                uint16 bit = 0x8000u >> x, pen = 0;
                if (!(masks[g * 4] & bit)) continue;
                for (unsigned p = 0; p < 4; p++)
                    if (pixels[g * 4 + p] & bit) pen |= 1u << p;
                switch (effect) {
                    case 1: pen |= 8; break;
                    case 2: pen = (pen & 6) | ((pen & 1) << 3) | ((pen & 8) >> 3); break;
                    case 3: pen = (pen & 9) | ((pen & 2) << 1) | ((pen & 4) >> 1); break;
                    case 4: pen |= 1; break;
                    case 5: pen = ((pen & 1) << 3) | ((pen & 2) << 1) | ((pen & 4) >> 1) | ((pen & 8) >> 3); break;
                    case 6: pen = (pen >> 1) | ((pen & 1) << 3); break;
                    case 7: pen &= 7; break;
                    case 8: pen |= 2; break;
                    case 9: pen |= 4; break;
                }
                for (unsigned p = 0; p < 4; p++)
                    if (pen & (1u << p)) expected[g * 4 + p] |= bit;
            }
        Video_Atari_HighlightPixels(output, pixels, masks, 2, effect);
        assert(!memcmp(output, expected, sizeof(output)));
    }
    Video_Atari_SetSpriteHighlight(0); assert(s_spriteHighlightEffect == 0);
    Video_Atari_SetSpriteHighlight(10); assert(s_spriteHighlightEffect == 0);
    Video_Atari_SetSpriteHighlight(65535); assert(s_spriteHighlightEffect == 0);
    return 0;
}
"""
        run_harness(harness.replace("/* RECIPES */", recipes).replace("/* PRODUCTION */", production))

    def test_sprite_publishers_keep_mode_out_of_policy(self):
        for name in ("Video_Atari_PresentPlanarSpriteStrided",
                     "Video_Atari_PresentPlanarSpriteUnshifted",
                     "Video_Atari_PresentProtectedSprite"):
            self.assertNotIn("Video_Atari_Mono()", function(VIDEO, name))
        self.assertNotIn("Video_Atari_MonoPublish", VIDEO)

    def test_retired_cursor_protection_and_fog_entry_points_stay_removed(self):
        assembly = (ROOT / "src/video/atari_viewport_tile.s").read_text()
        header = (ROOT / "src/video/video.h").read_text()
        for name in ("g_videoTileCursorTiles", "s_tileCursorWritable",
                     "Video_Atari_PlanarRunProtected", "Video_Atari_PlanarWritableMask",
                     "Video_Atari_DrawPlanarTileFogged"):
            self.assertNotIn(name, VIDEO + header + assembly)
        fog = function((ROOT / "src/gfx.c").read_text(), "GFX_DrawPlanarTileFogged")
        self.assertIn("GFX_PlanarCompositeSlot(", fog)
        self.assertIn("Video_Atari_DrawPlanarTile(", fog)

    def test_border_matches_generic_source_anchored_fills(self):
        production = "\n".join(function(VIDEO, name) for name in (
            "Video_Atari_MonoPenWords", "Video_Atari_PaintMono", "Video_Atari_DrawPlanarBorder"))
        run_harness(COMMON + r"""
static uint8 Video_Atari_GetPalettePen(uint8 colour) { return (colour * 7) & 15; }
#define Planar_SolidGroup(g,p) ((void)(g), (void)(p), assert(false))
#define Planar_DrawBorder(d,s,x,w,h,g) ((void)(d), (void)(s), (void)(x), (void)(w), (void)(h), (void)(g), assert(false))
/* PRODUCTION */
int main(void)
{
    enum { STRIDE = 24, HEIGHT = 20 };
    const unsigned widths[] = {2,3,7,16,17,47,64}, heights[] = {3,4,7,16};
    uint16 out[STRIDE * HEIGHT + 2], expected[STRIDE * HEIGHT];
    for (unsigned polarity = 0; polarity < 2; polarity++)
     for (unsigned pen = 0; pen < 16; pen++)
      for (unsigned x = 0; x < 32; x++)
       for (unsigned wi = 0; wi < sizeof(widths) / sizeof(*widths); wi++)
        for (unsigned hi = 0; hi < sizeof(heights) / sizeof(*heights); hi++) {
            unsigned width = widths[wi], height = heights[hi];
            uint8 colours[] = {pen, pen + 3, pen + 7, pen + 11};
            for (unsigned i = 0; i < STRIDE * HEIGHT + 2; i++) out[i] = 0xa55a;
            memcpy(expected, out + 1, sizeof(expected));
            for (unsigned row = 0; row < height; row++)
             for (unsigned col = 0; col < width; col++) {
                unsigned colour, sx, sy;
                if ((!row && col + 1 == width) || (row + 1 == height && !col)) {
                    colour = 3; sx = sy = 0;
                } else if (!row || !col) {
                    colour = 2; sx = !row ? col : 0; sy = !col ? row : 0;
                } else if (row + 1 == height || col + 1 == width) {
                    colour = 1; sx = col + 1 == width ? 0 : col; sy = col + 1 == width ? row : 0;
                } else {
                    colour = 0; sx = col; sy = row;
                }
                unsigned mapped = Video_Atari_GetPalettePen(colours[colour]);
                for (unsigned py = 0; py < 2; py++)
                    for (unsigned px = 0; px < 2; px++) {
                        unsigned bit = 15 - (((sy * 2 + py) & 3) * 4 + ((sx * 2 + px) & 3));
                        put(expected, STRIDE / 2, (x + col) * 2 + px, row * 2 + py,
                            ((s_paletteMonoST[mapped] >> bit) & 1) ^ !polarity);
                    }
             }
            s_monoWhiteIsOne = polarity;
            Video_Atari_DrawPlanarBorder(out + 1, STRIDE, x, width, height, colours);
            assert(!memcmp(out + 1, expected, sizeof(expected)));
            assert(out[0] == 0xa55a && out[STRIDE * HEIGHT + 1] == 0xa55a);
            (void)pixel;
        }
    return 0;
}
""".replace("/* PRODUCTION */", production))

    def test_protected_colour_slices_preserve_masks_and_highlights(self):
        tables = VIDEO[VIDEO.index("static const uint16 s_blitterLeftMasks[16]"):
                       VIDEO.index("static PlanarBlit s_planarBlit;")]
        plan = VIDEO[VIDEO.index("typedef struct PlanarBlit {"):
                     VIDEO.index("} PlanarBlit;") + len("} PlanarBlit;")]
        production = "\n".join(function(VIDEO, name) for name in (
            "Video_Atari_PlanarMergePlain", "Video_Atari_ViewportWritable",
            "Video_Atari_ShiftSpriteWord", "Video_Atari_ReadColourSpriteMask", "Video_Atari_ReadSpriteMask",
            "Video_Atari_ReadColourSprite", "Video_Atari_BuildSpriteBlitPlan",
            "Video_Atari_PublishColourSpriteRows", "Video_Atari_PublishSpriteRows"))
        harness = COMMON + r"""
#undef Video_Atari_Mono
#define Video_Atari_Mono() false
#define Video_Atari_GroupWords() 4
#define HL_ZERO 8
enum { ST_PLANAR_LINE_BYTES = 160 };
static uint16 screen[16000], expected[16000], original[16000];
static uint16 s_viewportHiddenRows[10];
static uint16 fog[16], hidden[16], partialFog[16];
static const uint16 *s_viewportFogWritable[10][15];
static uint16 s_spriteHighlightEffect;
static const uint8 s_highlightRecipes[][4] = {{0,1,2,7}, {0,1,2,8}};
static const struct { bool blitterProtectedSprites, blitterSpriteEffects; } colourBackend = {true, true};
#define s_planarBackend (&colourBackend)
#define Video_Atari_PublishMonoSpriteRows(...) assert(false)
static bool s_viewportBlitter, g_videoDisplayListActive;
/* TYPES */
/* TABLES */
/* PLAN */
static PlanarBlit s_planarBlit;
static unsigned clearSlices;
static uint8 *Video_Atari_PlanarBase(void) { return (uint8 *)screen; }
static void Video_Atari_DisplayListFlush(void) {}
static void Video_Atari_RestoreTileCursor(void) {}
static void GFX_Screen_ClearDirtyRect(unsigned l, unsigned t, unsigned r, unsigned b)
{ assert(l < r && r <= 240 && t >= 40 && t < b && b <= 200); }
static bool Video_Atari_CursorRectOverlap(uint8 *b, uint16 f, uint16 e, uint16 y, uint16 h)
{ (void)b; (void)f; (void)e; (void)y; (void)h; return false; }
static bool Video_Atari_PlacementRectOverlap(uint8 *b, uint16 l, uint16 r, uint16 y, uint16 h)
{ (void)b; (void)l; (void)r; (void)y; (void)h; return false; }
static void Video_Atari_PlanarMergeGroup(uint8 *b, uint16 y, uint16 g, uint16 mask, const uint16 p[4])
{ (void)b; (void)y; (void)g; (void)mask; (void)p; assert(false); }
static void Video_Atari_RefreshViewportCursor(uint8 *b, uint16 f, uint16 e,
    uint16 t, uint16 bottom, const uint16 *m, uint16 stride)
{ (void)b; (void)f; (void)e; (void)t; (void)bottom; (void)m; (void)stride; assert(false); }
static void Video_Atari_BlitProtectedSprite(void) { assert(false); }
#define Atari_SupervisorExec(callback) (callback)()
#define Video_Atari_QueueMaskedBlit(protected) ((void)(protected), assert(false))
/* PRODUCTION */
static void clear(const uint16 *p, const uint16 *m, uint16 sw, uint16 sx,
    uint16 w, uint16 h, uint16 x, uint16 y, bool expanded)
{
    clearSlices++;
    for (unsigned row = 0; row < h; row++)
        for (unsigned g = x / 16; g < (unsigned)(x + w + 15) / 16; g++) {
            unsigned left = max(x, g * 16), right = min(x + w, (g + 1) * 16);
            unsigned source = sx + left - x, phase = left & 15;
            uint16 words[4], edge = s_blitterLeftMasks[phase] & s_blitterRightMasks[right & 15];
            assert(Video_Atari_ViewportWritable(g, (y + row - 40) / 16) == NULL);
            uint16 mask = Video_Atari_ReadSpriteMask(m, sw, source, phase, expanded) & edge;
            Video_Atari_ReadColourSprite(p, m, sw, source, phase, expanded, words, s_spriteHighlightEffect);
            Video_Atari_PlanarMergePlain(screen + (y + row) * 80 + g * 4, mask, words);
        }
}
static void Video_Atari_PresentPlanarSpriteUnshifted(const uint16 *p, const uint16 *m,
    uint16 sw, uint16 sx, uint16 w, uint16 h, uint16 x, uint16 y,
    const Video_Atari_SpriteBlitGeometry *geometry, const Video_Atari_SpriteBlitCode *code)
{
    (void)geometry; (void)code;
    for (unsigned row = 0; row < h; row++)
        clear(p + row * (sw / 4), m + row * (sw / 4), sw, sx, w, 1, x, y + row, true);
}
static void Video_Atari_PresentPlanarSpriteStrided(const uint16 *p, const uint16 *m,
    uint16 w, uint16 h, int16 x, int16 y, uint16 sw)
{
    for (unsigned row = 0; row < h; row++)
        clear(p + row * (sw / 4), m + row * (sw / 16), sw, 0, w, 1, x, y + row, false);
}
/* SPLITTER */
int main(void)
{
    enum { SW = 80, SH = 33, GROUPS = SW / 16 };
    uint16 pixels[GROUPS * SH * 4], compact[GROUPS * SH], expanded[GROUPS * SH * 4];
    uint16 saved[GROUPS * SH * 4];
    const unsigned widths[] = {1, 17, 33};
    const uint8 highlights[][4] = {{0,1,2,7}, {0,1,2,8}};
    (void)s_monoWhiteIsOne; (void)pixel; (void)put;
    for (unsigned i = 0; i < 16000; i++) original[i] = 0xa39fu ^ (i * 1973u);
    for (unsigned i = 0; i < GROUPS * SH; i++) {
        compact[i] = 0x936fu ^ (i * 971u);
        for (unsigned p = 0; p < 4; p++) {
            pixels[i * 4 + p] = 0x7d13u ^ ((i * 4 + p) * 137u);
            expanded[i * 4 + p] = compact[i];
        }
    }
    memcpy(saved, pixels, sizeof(saved));
    for (unsigned line = 0; line < 16; line++) {
        fog[line] = 0xd7bdu ^ (line * 71u);
        partialFog[line] = line == 0 || line == 15 ? 0 : 0x7ffe;
    }
    s_viewportFogWritable[0][2] = fog;
    s_viewportFogWritable[1][3] = hidden;
    s_viewportHiddenRows[1] = 1u << 3;
    s_viewportFogWritable[1][1] = partialFog;
    for (unsigned wide = 0; wide < 2; wide++)
    for (unsigned effect = 0; effect < 3; effect++)
    for (unsigned phase = 0; phase < (wide ? 16u : 1u); phase++)
    for (unsigned sourcePhase = 0; sourcePhase < (wide ? 16u : 1u); sourcePhase++)
    for (unsigned wi = 0; wi < (wide ? 3u : 1u); wi++) {
        unsigned x = 16 + phase, y = 49, sx = 16 + sourcePhase, w = wide ? widths[wi] : 48;
        s_spriteHighlightEffect = effect;
        memcpy(screen, original, sizeof(screen)); memcpy(expected, original, sizeof(expected));
        clearSlices = 0;
        for (unsigned row = 0; row < SH; row++)
            for (unsigned col = 0; col < w; col++) {
                unsigned dx = x + col, dy = y + row, sourceX = sx + col;
                const uint16 *writable = Video_Atari_ViewportWritable(dx / 16, (dy - 40) / 16);
                uint16 bit = 0x8000u >> (dx & 15), sourceBit = 0x8000u >> (sourceX & 15);
                unsigned index = row * GROUPS + sourceX / 16;
                if (writable && !(writable[(dy - 40) & 15] & bit)) continue;
                if (!(compact[index] & sourceBit)) continue;
                for (unsigned p = 0; p < 4; p++) {
                    unsigned recipe = wide && effect ? highlights[effect - 1][p] : p;
                    bool set = recipe < 4 ? !!(pixels[index * 4 + recipe] & sourceBit) : recipe < 8;
                    uint16 *dst = expected + dy * 80 + (dx / 16) * 4 + p;
                    *dst = (*dst & ~bit) | (set ? bit : 0);
                }
            }
        Video_Atari_PresentProtectedSprite(pixels, wide ? expanded : compact, SW, sx, w, SH,
            x, y, wide, NULL);
        assert(!memcmp(screen, expected, sizeof(screen)));
        assert(!memcmp(saved, pixels, sizeof(saved)) && clearSlices > 0);
    }
    return 0;
}
"""
        run_harness(harness.replace("/* TYPES */", blit_plan_type())
                    .replace("/* TABLES */", tables).replace("/* PLAN */", plan)
                    .replace("/* PRODUCTION */", production)
                    .replace("/* SPLITTER */", function(VIDEO, "Video_Atari_PresentProtectedSprite")))

    def test_native_rectangles_share_bulk_and_edges(self):
        copies = "\n".join(function(VIDEO, name) for name in (
            "Video_Atari_CopyColourRun", "Video_Atari_CopyMonoRun"))
        production = "\n".join(function(VIDEO, name) for name in (
            "Video_Atari_PublishPlanarRun", "Video_Atari_PublishPlanarRect",
            "Video_Atari_PresentPlanarWindow", "Video_Atari_PresentRestoreStrided",
            "Video_Atari_PresentPlanarSubRect", "Video_Atari_PresentPlanarRect"))
        harness = r"""
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "atari_mono.h"
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
enum { SCREEN_WIDTH = 320, SCREEN_HEIGHT = 200, ST_PLANAR_LINE_BYTES = 160 };
static bool mono, overlays;
#define Video_Atari_Mono() mono
#define Video_Atari_PublishNativeRect(...) assert(false)
static uint16 allocation[16002], expected[16000], original[16000];
static uint8 *screen = (uint8 *)(allocation + 1);
static unsigned bulkGroups, merges, cleared;
/* COPIES */
static void copy_run(uint8 *d, uint16 ds, const uint8 *s, uint16 ss, uint16 g, uint16 h)
{
    if (ds == 160) bulkGroups += g * h;
    if (mono) Video_Atari_CopyMonoRun(d, ds, s, ss, g, h);
    else Video_Atari_CopyColourRun(d, ds, s, ss, g, h);
}
static struct {
    void (*copyRun)(uint8 *, uint16, const uint8 *, uint16, uint16, uint16);
    uint8 xShift;
} backend = {copy_run, 1}, *s_planarBackend = &backend;
static uint8 *Video_Atari_PlanarBase(void) { return screen; }
static bool Video_Atari_CursorDirect(void) { return true; }
static void Video_Atari_DisplayListFlush(void) {}
static void Video_Atari_RestoreTileCursor(void) {}
static void Video_Atari_PlanarFinishRun(uint8 *base, uint16 x, uint16 y, uint16 w, uint16 h)
{ assert(base == screen && !(x & 15) && !(w & 15) && x + w <= 320 && y + h <= 200); }
static void GFX_Screen_ClearDirtyRect(unsigned l, unsigned t, unsigned r, unsigned b)
{ assert(l < r && !(l & 15) && !(r & 15) && r <= 320 && t < b && b <= 200); cleared++; }
static void Video_Atari_PlanarMergeGroup(uint8 *base, uint16 y, uint16 g,
    uint16 mask, const uint16 words[4])
{
    merges++;
    if (mono) {
        uint16 old[4];
        Video_Atari_MonoReadGroup((uint16 *)base, 80, y, g, old);
        Video_Atari_MonoMergeWords(old, words, mask);
        Video_Atari_MonoWriteGroup((uint16 *)base, 80, y, g, old);
    } else {
        uint16 *dst = (uint16 *)base + y * 80 + g * 4;
        for (unsigned p = 0; p < 4; p++) dst[p] = (dst[p] & ~mask) | (words[p] & mask);
    }
}
static bool Video_Atari_PlanarOverlaysOverlap(uint8 *b, uint16 x, uint16 y, uint16 w, uint16 h)
{ (void)b; (void)x; (void)y; (void)w; (void)h; return overlays; }
static void Video_Atari_PlanarMergePlain(uint16 *dst, uint16 mask, const uint16 words[4])
{ for (unsigned p = 0; p < 4; p++) dst[p] = (dst[p] & ~mask) | (words[p] & mask); }
/* PRODUCTION */
static unsigned pixel(const uint8 *src, unsigned stride, unsigned x, unsigned y)
{
    unsigned pen = 0;
    for (unsigned p = 0; p < (mono ? 1u : 4u); p++) {
        uint16 word;
        memcpy(&word, src + y * (mono ? stride / 2 : stride) +
            (x / 16) * (mono ? 2 : 8) + p * 2, 2);
        pen |= ((word >> (15 - (x & 15))) & 1) << p;
    }
    return pen;
}
static void put(uint16 *dst, unsigned x, unsigned y, unsigned pen)
{
    for (unsigned p = 0; p < (mono ? 1u : 4u); p++) {
        uint16 *word = dst + y * (mono ? 40 : 80) + x / 16 * (mono ? 1 : 4) + p;
        uint16 bit = 0x8000u >> (x & 15);
        *word = (*word & ~bit) | ((pen & (1u << p)) ? bit : 0);
    }
}
int main(void)
{
    const unsigned widths[] = {1, 7, 15, 16, 17, 31, 32, 63, 241};
    const unsigned ys[] = {0, 39, 49, 191};
    for (unsigned i = 0; i < 16000; i++) original[i] = 0xa39fu ^ (i * 1973u);
    for (unsigned mode = 0; mode < 2; mode++)
        for (unsigned variant = 0; variant < 5; variant++)
          for (unsigned phase = 0; phase < 16; phase++)
            for (unsigned wi = 0; wi < sizeof(widths) / sizeof(*widths); wi++)
              for (unsigned yi = 0; yi < sizeof(ys) / sizeof(*ys); yi++) {
                unsigned x = 32 + phase, y = ys[yi], w = widths[wi], h = 9;
                unsigned left = variant == 2 ? x & ~15u : x;
                unsigned right = variant == 2 ? (x + w + 15) & ~15u : x + w;
                unsigned sourceX = variant == 2 || variant == 4 ? 0 : variant == 3 ? x & 15 : x;
                unsigned stride = variant == 0 || variant >= 3 ? 160 : mode ? 162 : 161;
                unsigned bytes = stride * h;
                uint8 *sourceAllocation, *src;
                if (variant == 4 && phase != 0) continue;
                sourceAllocation = malloc(bytes + 4);
                assert(sourceAllocation != NULL && right <= 320);
                src = sourceAllocation + (variant == 1 || variant == 2 ? 1 : 2);
                memset(sourceAllocation, 0x5a, bytes + 4);
                for (unsigned i = 0; i < bytes; i++) src[i] = i * 37 + i / stride * 53;
                mono = mode; backend.xShift = mono ? 2 : 1;
                overlays = y == 39;
                allocation[0] = allocation[16001] = 0xcafe;
                memcpy(screen, original, 32000); memcpy(expected, original, 32000);
                for (unsigned row = 0; row < h; row++)
                    for (unsigned col = left; col < right; col++) {
                        unsigned scale = mono ? 2 : 1;
                        for (unsigned dy = 0; dy < scale; dy++)
                            for (unsigned dx = 0; dx < scale; dx++)
                                put(expected, col * scale + dx, (y + row) * scale + dy,
                                    pixel(src, stride, (sourceX + col - left) * scale + dx,
                                        row * scale + dy));
                    }
                bulkGroups = merges = cleared = 0;
                if (variant == 0)
                    Video_Atari_PresentPlanarWindow((const uint16 *)src, x, y, w, h);
                else if (variant == 1)
                    Video_Atari_PublishPlanarRect(src, stride, x, x, y, w, h);
                else if (variant == 2)
                    assert(Video_Atari_PresentRestoreStrided(x, y, w, h, src, stride));
                else if (variant == 3)
                    assert(Video_Atari_PresentPlanarSubRect((const uint16 *)src, stride, sourceX, x, y, w, h));
                else assert(Video_Atari_PresentPlanarRect((const uint16 *)src, stride, x, y, w, h));
                assert(!memcmp(screen, expected, 32000));
                assert(allocation[0] == 0xcafe && allocation[16001] == 0xcafe && cleared == 1);
                assert(src[-1] == 0x5a && src[bytes] == 0x5a);
                {
                    unsigned full = right / 16 - (left + 15) / 16;
                    if ((left + 15) / 16 > right / 16) full = 0;
                    if (variant == 3 && phase == 8 && !(w & 15) && !overlays) {
                        assert(bulkGroups == 0 && merges == 0);
                    } else {
                        assert(bulkGroups == full * h);
                        assert(merges == ((right + 15) / 16 - left / 16 - full) * h);
                    }
                }
                free(sourceAllocation);
              }
    return 0;
}
"""
        run_harness(harness.replace("/* COPIES */", copies).replace("/* PRODUCTION */", production))

    def test_tick_uses_shared_scheduler_for_both_damage_sources(self):
        tick = function(VIDEO, "Video_Tick")
        self.assertNotIn("Video_Atari_Mono()", tick)
        self.assertNotIn("Video_Atari_MonoDirty", VIDEO)
        self.assertIn("area->top, area->bottom, DIRTY_SWEEP_LEGACY", tick)
        self.assertIn("vpArea->top, vpArea->bottom, DIRTY_SWEEP_VIEWPORT", tick)

    def test_native_text_target_and_individual_glyph_fallback(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        glyph = "\n".join(line for line in (ROOT / "src/gui/glyph.c").read_text().splitlines()
                          if not line.startswith("#include "))
        harness = COMMON + r"""
#include "../gui/glyph.h"
enum { SCREEN_WIDTH = 320, SCREEN_HEIGHT = 200 };
int8 g_fontCharOffset;
static AtariDitherLookup s_palette4BitDither;
static uint8 Video_Atari_GetPalettePen(uint8 c) { return c & 15; }
/* CELL */
static void Video_Atari_PreparePlanar(const AtariDitherSource *source,
    const AtariDitherLookup *lookup, uint16 *pixels)
{
    AtariMonoPackedLookup packed;
    assert(lookup == NULL);
    Video_Atari_MonoPreparePackedLookup(&packed, &s_palette4BitDither, 0, 256, s_monoWhiteIsOne);
    Video_Atari_MonoPackNative(source, &packed, pixels, ((source->width + 15) & ~15) / 4);
}
/* SURFACE */
/* GLYPH */
typedef struct { uint16 left, top, right, bottom; } PlanarBox;
static PlanarBox *s_planarTouch;
static uint16 *s_planarTarget, s_planarTargetStride, s_planarTargetRows;
Font *g_fontCurrent;
static uint8 g_colours[16];
static void PlanarBox_Union(PlanarBox *dst, const PlanarBox *src)
{ *dst = *src; }
/* TARGET */
int main(void)
{
    FontChar chars[128] = {{0}};
    uint8 data[21];
    Font font = {9, 7, 128, chars, NULL};
    uint16 pixels[24 * 80], expected[24 * 80];
    PlanarBox touched;
    for (unsigned i = 0; i < sizeof(data); i++) data[i] = i % 4;
    chars['A'] = (FontChar){7, 2, 3, data};
    GUI_Glyph_FontBuild(&font);
    g_fontCurrent = &font;
    s_planarTarget = pixels; s_planarTargetStride = 80; s_planarTargetRows = 24;
    s_planarTouch = &touched;
    g_colours[1] = 7; g_colours[2] = 23; g_colours[3] = 191;
    for (unsigned colour = 0; colour < 256; colour++)
        for (unsigned y = 0; y < 4; y++)
            for (unsigned x = 0; x < 4; x++)
                s_palette4BitDither.pens[y][x][colour] =
                    ((colour >> ((x + y * 4) & 7)) ^ x ^ (y >> 1)) & 1;
    for (unsigned polarity = 0; polarity < 2; polarity++)
        for (unsigned fallback = 0; fallback < 2; fallback++)
            for (unsigned x = 0; x < (fallback ? 320u : 314u); x++)
                for (unsigned y = 0; y < 24; y += 11) {
                    s_monoWhiteIsOne = polarity;
                    for (unsigned i = 0; i < 24 * 80; i++)
                        pixels[i] = expected[i] = 0xa39fu ^ (i * 1973u);
                    for (unsigned sy = 0; sy < 3 && y + sy + 2 < 24; sy++)
                        for (unsigned sx = 0; sx < 7 && x + sx < 320; sx++) {
                            uint8 colour = g_colours[data[sy * 7 + sx]];
                            if (!colour) continue;
                            unsigned py = sy + 2;
                            for (unsigned dy = 0; dy < 2; dy++)
                                for (unsigned dx = 0; dx < 2; dx++)
                                    put(expected, 40, (x + sx) * 2 + dx,
                                        (y + py) * 2 + dy,
                                        s_palette4BitDither.pens[(py * 2 + dy) & 3]
                                            [(sx * 2 + dx) & 3][colour] ^ !polarity);
                        }
                    if (fallback) GUI_PlanarTarget_Chunky(&chars['A'], x, y);
                    else assert(GUI_PlanarTarget_Text("A", x, y) == ((x & 15) + 7 + 15) / 16);
                    assert(!memcmp(pixels, expected, sizeof(pixels)));
                }
    GUI_Glyph_FontFree(&font);
    return 0;
}
"""
        target = "\n".join(function(gui, name) for name in (
            "GUI_RenderGlyph", "GUI_PlanarTarget_Text", "GUI_PlanarTarget_Chunky"))
        backend = surface_backend(VIDEO) + "\n".join(function(VIDEO, name) for name in (
            "Video_Atari_PlanarMergePlain", "Video_Atari_BlitPlanarSprite", "Video_Atari_BlitChunkyTransparent"))
        run_harness(harness.replace("/* CELL */", function(VIDEO, "Video_Atari_MonoPenWords"))
                    .replace("/* SURFACE */", backend)
                    .replace("/* GLYPH */", glyph_backend(VIDEO) + glyph).replace("/* TARGET */", target))

    def test_instant_palette_install_outside_animation_enclaves(self):
        production = "\n".join(function(VIDEO, name) for name in (
            "Video_Atari_PresentPaletteRange", "Video_Atari_PresentPalette",
            "Video_Atari_TryPaletteFadeUniform"))
        harness = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#define Video_Atari_Mono() true
static bool s_presentMode, s_screen_needrepaint, s_hwPaletteInit;
static uint8 s_hwPalette[48], s_palette4BitPC[64], installed[768];
static unsigned installs;
static void Video_SetPalette(void *palette, int from, int count)
{
    assert(from == 0 && count == 256);
    memcpy(installed, palette, sizeof(installed));
    installs++;
}
static int Video_Atari_PaletteUniformValue(const uint8 *p)
{ (void)p; assert(false); return -1; }
static void Video_Atari_HwPaletteRamp(const uint8 *p, int16 ticks)
{ (void)p; (void)ticks; assert(false); }
static int Video_Atari_HwColorWord(uint8 r, uint8 g, uint8 b)
{ (void)r; (void)g; (void)b; assert(false); return 0; }
static int Setcolor(int pen, int value)
{ (void)pen; (void)value; assert(false); return 0; }
/* PRODUCTION */
int main(void)
{
    uint8 active[768], target[768];
    for (unsigned present = 0; present < 2; present++)
        for (unsigned uniform = 0; uniform < 2; uniform++) {
            s_presentMode = present;
            installs = 0;
            memset(active, 0, sizeof(active));
            for (unsigned i = 0; i < sizeof(target); i++)
                target[i] = uniform ? 0 : (i * 37 + 13) & 63;
            assert(Video_Atari_TryPaletteFadeUniform(active, target, 30));
            assert(installs == 1 && !s_screen_needrepaint);
            assert(!memcmp(active, target, sizeof(active)));
            assert(!memcmp(installed, target, sizeof(installed)));
        }
    return 0;
}
"""
        run_harness(harness.replace("/* PRODUCTION */", production))

    def test_startup_detection_and_system_palette_polarity(self):
        harness = r"""
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include "types.h"
typedef int VideoScaleFilter;
enum { SCREEN_WIDTH = 320, SCREEN_HEIGHT = 200 };
enum { MCH_UNKNOWN, MCH_ST, MCH_STE, MCH_MEGA_STE, MCH_TT, MCH_FALCON };
enum { VM_INQUIRE = -1, VGA = 1, PAL = 2, BPS8 = 4, COL40 = 8, VERTFLAG = 16, TT_LOW = 7 };
#define Debug(...) ((void)0)
#define Warning(...) ((void)0)
#define Error(...) assert(false)
#define Video_Atari_Mono() g_videoAtariMono
#define Atari_SupervisorExec(callback) ((callback)())
static uint8 logical[32000], physical[32000], *s_planarBase;
static void *s_framebuffer, *s_savedLogBase, *s_savedPhysBase;
static const uint16 *s_blitterHalftonePattern;
static uint32 s_paletteBackup[256], s_stScreenBase;
static uint16 s_SquareTable[256];
static uint8 s_palette4BitPC[64];
static int s_machine_type, s_savedMode, s_savedCpuSpeed = -1, s_center_image_offset;
static bool g_videoAtariMono, g_consoleActive = true, s_viewportBlitter;
static bool s_blitterDestinationWord, s_blitterTileSetup, s_curDirect, s_monoWhiteIsOne;
static int s_monoBackend, s_colourBackend;
static const void *s_planarBackend;
static int resolution, palette0, modeWrites, paletteReads, paletteWrites, restoredBase;
static int lookupBuilds, interrupts, configuredMono;
static void Video_Atari_CursorInitStorage(void) {}
static void Detect_Machine(void) { s_machine_type = MCH_STE; }
static int IniFile_GetInteger(const char *key, int value) { (void)key; return value; }
static int Getrez(void) { return resolution; }
static void *Logbase(void) { return logical; }
static void *Physbase(void) { return physical; }
static int Setcolor(int pen, int value)
{
    assert(pen >= 0 && pen < 16);
    if (value == -1) { assert(pen == 0); paletteReads++; return palette0; }
    paletteWrites++;
    return pen;
}
static void set_mode(int rez) { modeWrites++; resolution = rez; }
#define Setscreen(log,phys,rez) set_mode(rez)
static int forbidden(void) { assert(false); return 0; }
#define Cconws(...) ((void)0)
#define Cursconf(...) ((void)0)
#define Blitmode(...) forbidden()
#define VsetMode(...) forbidden()
#define VgetSize(mode) ((void)(mode), forbidden())
#define Srealloc(size) ((void)(size), forbidden())
#define VsetScreen(a,b,c,d) ((void)(a), (void)(b), (void)(c), (void)(d), forbidden())
#define VgetRGB(...) forbidden()
#define VsetRGB(...) forbidden()
#define EgetShift(...) forbidden()
#define EsetShift(...) forbidden()
#define EgetPalette(...) forbidden()
#define EsetPalette(...) forbidden()
static void MegaSTE_SpeedUp(void) { s_savedCpuSpeed = 8; }
static void MegaSTE_SpeedRestore(void) {}
static void install_ikbd_handler(void) { interrupts++; }
static void uninstall_ikbd_handler(void) { interrupts--; }
static void Video_Atari_InitBlitterDestination(void) { configuredMono = Video_Atari_Mono(); }
static void Video_Atari_InitTileCursorBackend(void)
{ assert(s_planarBackend == (Video_Atari_Mono() ? (const void *)&s_monoBackend : (const void *)&s_colourBackend)); }
static void Rebuild_Palette4BitPairMap(int from, int count)
{ assert(from == 0 && count == 256); lookupBuilds++; }
static void Video_Atari_DisplayListFree(void) {}
static void Video_Atari_ConfigureBlitterDestination(uint32 word, uint32 mono)
{ assert(!word && !mono); }
static void Video_ST_SetBase(void)
{ assert(s_stScreenBase == (uint32)(uintptr_t)physical); restoredBase++; }
/* PRODUCTION */
int main(void)
{
    for (unsigned machine = MCH_ST; machine <= MCH_MEGA_STE; machine++)
        for (unsigned high = 0; high < 2; high++)
            for (unsigned polarity = 0; polarity < 2; polarity++) {
                s_machine_type = machine;
                resolution = high ? 2 : 1;
                palette0 = polarity ? 0x777 : 0;
                modeWrites = paletteReads = paletteWrites = restoredBase = lookupBuilds = 0;
                g_videoAtariMono = false;
                assert(Video_Init(1, 0));
                assert(Video_Atari_Mono() == (bool)high && configuredMono == (int)high);
                assert(s_planarBackend == (high ? &s_monoBackend : &s_colourBackend));
                assert(paletteReads == (int)high);
                assert(paletteWrites == (high ? 0 : 16));
                assert(modeWrites == (high ? 0 : 1));
                assert(lookupBuilds == (int)high && interrupts == 1);
                assert(s_curDirect && s_planarBase == logical && s_framebuffer != NULL);
                assert(s_SquareTable[255] == 65025);
                if (high) assert(s_monoWhiteIsOne == !polarity && resolution == 2);
                Video_Uninit();
                assert(paletteWrites == (high ? 0 : 32));
                assert(modeWrites == (high ? 0 : 2) && restoredBase == (int)high);
                assert(resolution == (high ? 2 : 1));
                assert(g_consoleActive && s_framebuffer == NULL && s_planarBase == NULL);
                assert(interrupts == 0 && s_savedCpuSpeed == -1);
            }
    return 0;
}
"""
        run_harness(harness.replace("/* PRODUCTION */",
                    function(VIDEO, "Video_Init") + "\n" + function(VIDEO, "Video_Uninit")))

    def test_glyph_phases_clipping_overlap_and_transparency(self):
        glyph = "\n".join(line for line in (ROOT / "src/gui/glyph.c").read_text().splitlines()
                          if not line.startswith("#include "))
        harness = COMMON + r"""
#include "../gui/glyph.h"
int8 g_fontCharOffset;
static AtariDitherLookup s_palette4BitDither;
static uint8 Video_Atari_GetPalettePen(uint8 c) { return c & 15; }
/* CELL */
/* GLYPH */
int main(void)
{
    FontChar chars[128] = {{0}};
    uint8 a[21], b[44], c[9], colours[16] = {0, 7, 23, 191};
    Font font = {9, 11, 128, chars, NULL};
    for (unsigned i = 0; i < sizeof(a); i++) a[i] = i % 4;
    for (unsigned i = 0; i < sizeof(b); i++) b[i] = (i / 3 + i) % 4;
    for (unsigned i = 0; i < sizeof(c); i++) c[i] = (i + 1) % 4;
    chars['A'] = (FontChar){7, 2, 3, a};
    chars['B'] = (FontChar){11, 1, 4, b};
    chars['C'] = (FontChar){3, 0, 3, c};
    GUI_Glyph_FontBuild(&font);
    assert(GUI_Glyph_Usable(&font));
    for (unsigned colour = 0; colour < 256; colour++)
        for (unsigned y = 0; y < 4; y++)
            for (unsigned x = 0; x < 4; x++)
                s_palette4BitDither.pens[y][x][colour] =
                    ((colour >> ((x + y * 4) & 7)) ^ x ^ (y >> 1)) & 1;
    for (unsigned polarity = 0; polarity < 2; polarity++)
        for (unsigned phase = 0; phase < 16; phase++)
            for (unsigned rows = 1; rows <= 9; rows += 4)
                for (int spacing = -2; spacing <= 2; spacing += 2)
                    for (unsigned transparent = 0; transparent < 2; transparent++) {
                        enum { STRIDE = 16, MASK_STRIDE = 4 };
                        uint16 pixels[STRIDE * 9], expected[STRIDE * 9];
                        uint16 masks[MASK_STRIDE * 9], wanted[MASK_STRIDE * 9];
                        const char *text = "ABCAB\nCA", *s;
                        unsigned x = phase, extent = phase, count = 0;
                        s_monoWhiteIsOne = polarity;
                        g_fontCharOffset = spacing;
                        colours[2] = transparent ? 0 : 23;
                        for (unsigned i = 0; i < STRIDE * 9; i++)
                            pixels[i] = expected[i] = 0xa39fu ^ (i * 1973u);
                        for (unsigned i = 0; i < MASK_STRIDE * 9; i++)
                            masks[i] = wanted[i] = 0x180u ^ (i * 971u);
                        for (s = text; *s && *s != '\n'; s++) {
                            const FontChar *fc = &chars[(unsigned char)*s];
                            if (x + fc->width <= 48) {
                                count++;
                                if (x + fc->width > extent) extent = x + fc->width;
                                for (unsigned sy = 0; sy < fc->usedLines; sy++) {
                                    unsigned y = sy + fc->unusedLines;
                                    if (y >= rows) continue;
                                    for (unsigned sx = 0; sx < fc->width; sx++) {
                                        uint8 colour = colours[fc->data[sy * fc->width + sx]];
                                        if (!colour) continue;
                                        wanted[y * MASK_STRIDE + (x + sx) / 16] |=
                                            0x8000u >> ((x + sx) & 15);
                                        for (unsigned dy = 0; dy < 2; dy++)
                                            for (unsigned dx = 0; dx < 2; dx++)
                                                put(expected, STRIDE / 2, (x + sx) * 2 + dx,
                                                    y * 2 + dy, s_palette4BitDither.pens[
                                                        (y * 2 + dy) & 3][(sx * 2 + dx) & 3][colour] ^
                                                        !s_monoWhiteIsOne);
                                    }
                                }
                            }
                            x += fc->width + spacing;
                        }
                        assert(GUI_Glyph_Line(&font, colours, text, phase, 3, rows,
                            pixels, STRIDE, masks, MASK_STRIDE) == (count ? (extent + 15) / 16 : 0));
                        assert(!memcmp(pixels, expected, sizeof(pixels)));
                        assert(!memcmp(masks, wanted, sizeof(masks)));
                        g_fontCharOffset = -4;
                        assert(GUI_Glyph_Line(&font, colours, "ABC", phase, 3, rows,
                            pixels, STRIDE, masks, MASK_STRIDE) == GLYPH_LINE_UNSUPPORTED);
                        assert(!memcmp(pixels, expected, sizeof(pixels)));
                        assert(!memcmp(masks, wanted, sizeof(masks)));
                    }
    GUI_Glyph_FontFree(&font);
    return 0;
}
"""
        run_harness(harness.replace("/* CELL */", "")
                    .replace("/* GLYPH */", glyph_backend(VIDEO) + glyph))

    def test_publication_clipping_fog_cursor_backups_and_save_restore(self):
        production = "\n".join(function(VIDEO, name) for name in (
            "Video_Atari_PlanarMergePlain", "Video_Atari_PlanarCopyGroup",
            "Video_Atari_MergeNativeWords", "Video_Atari_WriteNativeGroup", "Video_Atari_PenGroupWords",
            "Video_Atari_CursorGroup",
            "Video_Atari_CursorBackground", "Video_Atari_CursorWriteGroup",
            "Video_Atari_PlacementBlock", "Video_Atari_PlanarMergeGroup",
            "Video_Atari_CursorRectOverlap", "Video_Atari_PlacementRectOverlap",
            "Video_Atari_RefreshViewportCursor",
            "Video_Atari_PlanarFinishRun",
            "Video_Atari_ViewportWritable", "Video_Atari_PublishNativeRect",
            "Video_Atari_PresentSave",
            "Video_Atari_PrepareMonoCustom", "Video_Atari_PrepareMono",
            "Video_Atari_ConvertColour", "Video_Atari_ColourReadGroup",
            "Video_Atari_PublishPlanarRun", "Video_Atari_PublishPlanarRect",
            "Video_Atari_PresentRestoreStrided",
            "Video_Atari_ConvertRun", "Video_Atari_PresentRun",
            "Video_Atari_PresentGroupMasked", "Video_Atari_PresentRunMasked",
            "Video_Atari_PresentPlanarWindow",
            "Video_Atari_PresentChunky",
        ))
        model = blitter_model(VIDEO, protected=True, native=True)[len(inactive_display_list()):]
        start = model.index("static bool Video_Atari_CursorRectOverlap(")
        end = model.index("#define Video_Atari_RefreshViewportCursorUnshifted", start)
        model = model[:start] + model[end:]
        sprite = "\n".join(function(VIDEO, name) for name in (
            "Video_Atari_PlanarOverlaysOverlap", "Video_Atari_ViewportProtectionOverlap",
            "Video_Atari_PublishMonoRows", "Video_Atari_PublishViewportCursorRect", "Video_Atari_PresentPlanarSpriteOverlays",
            "Video_Atari_PublishPlanarSpritePlain", "Video_Atari_PublishCompactSpriteRows",
            "Video_Atari_PresentPlanarSpriteStrided"))
        sprite += model + "\n" + "\n".join(function(VIDEO, name) for name in (
            "Video_Atari_PresentProtectedSprite", "Video_Atari_TileOverlaysOverlap",
            "Video_Atari_DrawPlanarTile", "Video_Atari_PresentPlanarText"))
        start = VIDEO.index("typedef struct CursorRefreshArgs {")
        refresh_args = VIDEO[start:VIDEO.index("} CursorRefreshArgs;", start) + len("} CursorRefreshArgs;")]
        header = (ROOT / "src/video/video.h").read_text()
        cursor_types = header[header.index("typedef enum VideoAtariTileCursorShape"):
                              header.index("} VideoAtariTileCursorShape;") + len("} VideoAtariTileCursorShape;")]
        cursor_types += header[header.index("typedef struct Video_Atari_TileCursorBlit"):
                               header.index("} Video_Atari_TileCursorBlit;") + len("} Video_Atari_TileCursorBlit;")]
        cursor = VIDEO[VIDEO.index("static const uint16 s_tileCursorPatterns"):
                       VIDEO.index("static const uint16 *s_viewportFogWritable")]
        cursor += VIDEO[VIDEO.index("static uint16 s_tileCursorCol, s_tileCursorTop;"):
                        VIDEO.index("\nvoid Video_Atari_ResetViewportProtection")]
        cursor += "\n".join(function(VIDEO, name) for name in (
            "Video_Atari_BlitMonoTileCursor", "Video_Atari_BeginViewportProtection",
            "Video_Atari_EndViewportProtection", "Video_Atari_RestoreTileCursor",
            "Video_Atari_TileCursorFrame"))
        cursor = cursor.replace(
            "static void Video_Atari_BlitMonoTileCursor(void)\n{",
            "static void Video_Atari_BlitMonoTileCursor(void)\n{\n"
            "    blitterPixels = (uintptr_t)s_tileCursorPixels;\n"
            "    blitterMasks = (uintptr_t)s_tileCursorMasks; blitterReadStride = 4;")
        harness = COMMON + r"""
#undef Video_Atari_Mono
static bool nativeMono = true;
#define Video_Atari_Mono() nativeMono
enum { SCREEN_WIDTH = 320, SCREEN_HEIGHT = 200, ST_PLANAR_LINE_BYTES = 160 };
static uint16 screen[16000], original[16000], scene[16000], expected[16000];
static bool s_curDrawn, s_viewportProtectionActive;
static uint8 *s_curDrawnBase, *s_placeDrawnBase;
static uint16 s_curDrawnY, s_curDrawnH, s_curDrawnGroup, s_curDrawnGroups;
static uint16 s_curSave[3][8], s_curDrawnData[3][8], s_curDrawnMask[3][2];
static uint16 s_curViewportTiles[10], s_placeViewportTiles[10];
typedef struct PlacementBlock { uint16 y, group, mask, saved[4]; } PlacementBlock;
static PlacementBlock s_placeBlocks[6];
static uint16 s_placeBlockCount, s_placeDrawnWidth, s_placeDrawnHeight;
static int16 s_placeDrawnX, s_placeDrawnY;
static uint8 s_placePen = 1;
static AtariDitherLookup s_palette4BitDither, s_tileDither;
static AtariMonoPackedLookup s_paletteMonoPacked, s_tileMonoPacked;
static uint16 s_palette4BitPairMap[1];
static unsigned fastRows, slowCalls, convertedPixels;
/* BACKEND */
static void Video_Atari_PrepareColour(const AtariDitherSource *s,
    const AtariDitherLookup *l, uint16 *p, uint16 stride)
{ (void)s; (void)l; (void)p; (void)stride; assert(false); }
static void record_prepare(const AtariDitherSource *s,
    const AtariDitherLookup *l, uint16 *p, uint16 stride)
{ fastRows += s->height; convertedPixels += s->width * s->height;
  Video_Atari_PrepareMono(s, l, p, stride); }
static uint16 partialFog[16];
static uint16 fog[16];
static uint16 hidden[16], s_viewportProtectedRows[10], s_viewportHiddenRows[10];
static const uint16 *s_viewportFogWritable[10][15], *unused;
static uint16 s_spriteHighlightEffect;
/* BLIT TYPES */
/* CURSOR TYPES */
static uint16 g_tileCursorPen, g_tileCursorTargetPen;
static void (*g_videoTileCursorTail)(void);
static Video_Atari_TileCursorBlit g_videoTileCursorBlit;
static bool g_videoTileCursorRestored;
static void Video_Atari_TileCursorTail(void);
static bool g_videoDisplayListActive, g_videoScrollPending;
static unsigned spriteQueues, spriteFallbacks, spriteMerges, spriteFlushes, scrollFinishes, opaqueRuns;
static bool checkingSprite;
static bool Video_Atari_PlanarOverlaysOverlap(uint8 *, uint16, uint16, uint16, uint16);
static void Video_Atari_PublishSpriteRows(uint8 *, const uint16 *, const uint16 *,
    uint16, uint16, uint16, uint16, uint16, uint16, bool, bool, const uint16 *, uint16);
static void Video_Atari_PresentProtectedSprite(const uint16 *, const uint16 *,
    uint16, uint16, uint16, uint16, uint16, uint16, bool, const Video_Atari_SpriteBlitCode *);
static void Video_Atari_QueueSpriteBlitCode(const Video_Atari_SpriteBlitCode *,
    const uint16 *, const uint16 *, uint16 *, uint16, const Video_Atari_SpriteBlitPlan *);
static void Video_Atari_QueueSpriteBlitGeometry(const Video_Atari_SpriteBlitCode *,
    const uint16 *, const uint16 *, uint16 *, uint16, const Video_Atari_SpriteBlitGeometry *);
static void Video_Atari_BlitProtectedSprite(void) { assert(false); }
#define Video_Atari_QueueMaskedBlit(protected) ((void)(protected), assert(false))
#define Video_Atari_GroupWords() (nativeMono ? 2 : 4)
/* REFRESH ARGS */
static bool s_curDrawnPointer;
static const uint16 s_cursorAllOnes[2] = {0xffff, 0xffff};
static void Video_Atari_CursorRefreshGroups(CursorRefreshArgs *args)
{
    for (unsigned y = 0; y < args->lines; y++) {
        uint16 *dst = (uint16 *)((uint8 *)args->dst + y * (args->groups * 8 + args->dstSkip));
        uint16 *save = (uint16 *)((uint8 *)args->save + y * (args->groups * 8 + args->saveSkip));
        const uint16 *data = (const uint16 *)((const uint8 *)args->drawnData + y * (args->groups * 8 + args->saveSkip));
        const uint16 *drawn = (const uint16 *)((const uint8 *)args->drawnMask + y * (args->groups * 2 + args->drawnMaskSkip));
        const uint16 *mask = (const uint16 *)((const uint8 *)args->masks +
            y * (args->groups * 2 + (int32)args->masksSkip));
        for (unsigned g = 0; g < args->groups; g++)
            for (unsigned p = 0; p < 4; p++) {
                unsigned i = g * 4 + p;
                save[i] = (save[i] & ~mask[g]) | (dst[i] & mask[g]);
                dst[i] = (save[i] & ~drawn[g]) | (data[i] & drawn[g]);
            }
    }
}
#define Video_Atari_CursorRefreshPointer Video_Atari_CursorRefreshGroups
static uint16 commands[32], *g_videoDisplayListNext = commands, *g_videoDisplayListLimit = commands + 32;
#define VIDEO_ATARI_DISPLAY_TEXT_BYTES 32
#define Video_Atari_DisplayListCheck(bytes) ((void)(bytes))
#define Video_Atari_QueueTile(p,d) ((void)(p), (void)(d), assert(false))
#define Video_Atari_QueueMaskedTile(p,m,d) ((void)(p), (void)(m), (void)(d), assert(false))
#define Video_Atari_QueueMaskedRect(p,m,d,g,h) ((void)(p), (void)(m), (void)(d), (void)(g), (void)(h), assert(false))
#define Video_Atari_BlitTile(p,b,x,y) ((void)(p), (void)(b), (void)(x), (void)(y), assert(false))
static uint8 *Video_Atari_PlanarBase(void) { return (uint8 *)screen; }
static bool Video_Atari_CursorDirect(void) { return true; }
static void Video_Atari_DisplayListFlush(void);
static void Video_Atari_FinishScroll(void)
{ assert(g_videoScrollPending); g_videoScrollPending = false; scrollFinishes++; }
static void Video_Atari_RestoreTileCursor(void);
static bool Video_Atari_DisplayListPending(void);
static void GFX_Screen_ClearDirtyRect(unsigned l, unsigned t, unsigned r, unsigned b)
{ assert(l < r && r <= 320 && t < b && b <= 200); }
static void c2p1x1_4_st(void *dst, const void *src, uint32 w, uint32 h, const void *pal)
{ (void)dst; (void)src; (void)w; (void)h; (void)pal; assert(false); }
static void c2p1x1_4_st_strided(void *dst, const void *src, uint32 w, uint32 h,
    const void *pal, uint32 ss, uint32 ds)
{ (void)dst; (void)src; (void)w; (void)h; (void)pal; (void)ss; (void)ds; assert(false); }
/* PRODUCTION */
/* SPRITE */
/* CURSOR */
typedef struct QueuedSprite {
    const uint16 *pixels, *masks;
    uint16 *dst, height;
    Video_Atari_SpriteBlitPlan plan;
    const Video_Atari_SpriteBlitCode *code;
    uintptr_t pixelBase, maskBase;
    uint16 stride;
    void (*tail)(void);
} QueuedSprite;
static QueuedSprite queue[32];
static unsigned queueCount;
static void Video_Atari_QueueSpriteBlitCode(const Video_Atari_SpriteBlitCode *code,
    const uint16 *p, const uint16 *m, uint16 *d, uint16 h, const Video_Atari_SpriteBlitPlan *plan)
{
    assert(queueCount < 32 && code->passes == (nativeMono ? 0x11 : 0xff));
    queue[queueCount++] = (QueuedSprite){p, m, d, h, *plan, code,
        blitterPixels, blitterMasks, blitterReadStride, NULL};
    spriteQueues++;
}
static void Video_Atari_QueueSpriteBlitGeometry(const Video_Atari_SpriteBlitCode *code,
    const uint16 *p, const uint16 *m, uint16 *d, uint16 h, const Video_Atari_SpriteBlitGeometry *g)
{
    Video_Atari_SpriteBlitPlan plan;
    Video_Atari_DecodeSpriteBlitGeometry(&plan, g);
    Video_Atari_QueueSpriteBlitCode(code, p, m, d, h, &plan);
}
static void Video_Atari_DisplayListFlush(void)
{
    spriteFlushes++;
    for (unsigned i = 0; i < queueCount; i++) {
        QueuedSprite *q = &queue[i];
        if (q->tail != NULL) { q->tail(); continue; }
        blitterPixels = q->pixelBase; blitterMasks = q->maskBase;
        blitterReadStride = q->stride;
        Video_Atari_ExecuteSpriteBlitCode(q->code, q->pixels, q->masks, q->dst, q->height, &q->plan);
    }
    queueCount = 0;
}
static bool Video_Atari_DisplayListPending(void) { return queueCount != 0; }
static void Video_Atari_TileCursorTail(void)
{
    uint16 *dst = (uint16 *)g_videoTileCursorBlit.dst;
    for (unsigned line = 0; line < 16; line++)
        for (unsigned plane = 0; plane < 4; plane++) {
            uint16 *word = dst + line * 80 + plane, mask = g_videoTileCursorBlit.pattern[line];
            assert(g_videoTileCursorBlit.operations[plane] == 4 ||
                   g_videoTileCursorBlit.operations[plane] == 7);
            *word = g_videoTileCursorBlit.operations[plane] == 7 ? *word | mask : *word & ~mask;
        }
    blitterLaunches += 4;
    g_videoTileCursorRestored = true;
}
static void overlays(uint16 *dst)
{
    if (!nativeMono) {
        for (unsigned i = 0; i < s_placeBlockCount; i++) {
            PlacementBlock *block = &s_placeBlocks[i];
            for (unsigned p = 0; p < 4; p++) {
                uint16 *word = dst + block->y * 80 + block->group * 4 + p;
                *word = (*word & ~block->mask) | ((s_placePen & (1u << p)) ? block->mask : 0);
            }
        }
        if (s_curDrawn)
            for (unsigned y = 0; y < 3; y++)
                for (unsigned g = 0; g < 2; g++)
                    for (unsigned p = 0; p < 4; p++) {
                        uint16 mask = s_curDrawnMask[y][g];
                        uint16 *word = dst + (50 + y) * 80 + (2 + g) * 4 + p;
                        *word = (*word & ~mask) | (s_curDrawnData[y][g * 4 + p] & mask);
                    }
        return;
    }
    for (unsigned i = 0; i < s_placeBlockCount; i++) {
        PlacementBlock *block = &s_placeBlocks[i];
        for (unsigned x = 0; x < 16; x++) {
            if (!(block->mask & (0x8000u >> x))) continue;
            for (unsigned dy = 0; dy < 2; dy++)
                for (unsigned dx = 0; dx < 2; dx++) {
                    unsigned px = block->group * 32 + x * 2 + dx, py = block->y * 2 + dy;
                    unsigned bit = 15 - (((py - s_placeDrawnY * 2) & 3) * 4 +
                        ((px - s_placeDrawnX * 2) & 3));
                    put(dst, 40, px, py, ((s_paletteMonoST[s_placePen] >> bit) & 1) ^ !s_monoWhiteIsOne);
                }
        }
    }
    if (!s_curDrawn) return;
    for (unsigned y = 0; y < 3; y++)
        for (unsigned x = 0; x < 32; x++)
            if (s_curDrawnMask[y][x / 16] & (0x8000u >> (x & 15)))
                for (unsigned dy = 0; dy < 2; dy++)
                    for (unsigned dx = 0; dx < 2; dx++)
                        put(dst, 40, 64 + x * 2 + dx, (50 + y) * 2 + dy,
                            !!(s_curDrawnData[y][(x / 16) * 4 + (x & 15) / 8 + dy * 2] &
                               (0x8000u >> ((x & 7) * 2 + dx))));
}
static void reset_layers(bool cursor, bool placement)
{
    memcpy(screen, original, sizeof(screen));
    memcpy(scene, original, sizeof(scene));
    s_curDrawn = cursor;
    s_curDrawnY = 50; s_curDrawnH = 3; s_curDrawnGroup = 2; s_curDrawnGroups = 2;
    s_curDrawnBase = s_placeDrawnBase = (uint8 *)screen;
    s_placeBlockCount = placement ? 6 : 0;
    s_placeDrawnX = 32; s_placeDrawnY = 50; s_placeDrawnWidth = 32; s_placeDrawnHeight = 3;
    for (unsigned y = 0; y < 3; y++)
        for (unsigned group = 0; group < 2; group++) {
            PlacementBlock *block = &s_placeBlocks[y * 2 + group];
            block->y = y + 50; block->group = group + 2; block->mask = 0xe7d3u;
            s_planarBackend->readGroup(original, 80, y + 50, group + 2, block->saved);
            s_curDrawnMask[y][group] = 0x3c97u;
            for (unsigned i = 0; i < 4; i++)
                s_curDrawnData[y][group * 4 + i] =
                    (0x95e3u ^ (i * 971u + y * 71)) & (nativeMono ? 0xffff : s_curDrawnMask[y][group]);
        }
    /* Save cursor backgrounds after placement, but before drawing the pointer. */
    s_curDrawn = false;
    overlays(screen);
    for (unsigned y = 0; y < 3; y++)
        for (unsigned group = 0; group < 2; group++)
            s_planarBackend->readGroup(screen, 80, y + 50, group + 2, &s_curSave[y][group * 4]);
    s_curDrawn = cursor;
    overlays(screen);
    memset(s_curViewportTiles, 0, sizeof(s_curViewportTiles));
    memset(s_placeViewportTiles, 0, sizeof(s_placeViewportTiles));
    s_curViewportTiles[0] = cursor ? (1u << 2) | (1u << 3) : 0;
    s_placeViewportTiles[0] = placement ? (1u << 2) | (1u << 3) : 0;
}
static void reset(bool overlay) { reset_layers(overlay, overlay); }

static void check_shared_overlay_order(void)
{
    const uint16 masks[] = {0, 0xffff, 0x936f};
    for (unsigned mode = 0; mode < 2; mode++)
      for (unsigned polarity = 0; polarity < 2; polarity++)
       for (unsigned pen = 0; pen < 16; pen++)
        for (unsigned layers = 0; layers < 4; layers++) {
            nativeMono = mode;
            s_planarBackend = mode ? &s_monoBackend : &s_colourBackend;
            s_monoWhiteIsOne = polarity;
            s_placePen = pen;
            reset_layers(layers & 1, layers & 2);
            for (unsigned pass = 0; pass < 3; pass++)
             for (unsigned y = 49; y < 54; y++)
              for (unsigned g = 1; g < 5; g++) {
                uint16 words[4], mask = masks[(pass + y + g) % 3];
                for (unsigned i = 0; i < 4; i++) words[i] = pass == 1 ? 0 : 0xb39fu ^ (i * 771u + y * 137u);
                for (unsigned x = 0; x < 16; x++) {
                    if (!(mask & (0x8000u >> x))) continue;
                    if (mode)
                        for (unsigned py = 0; py < 2; py++)
                            for (unsigned px = 0; px < 2; px++)
                                put(scene, 40, g * 32 + x * 2 + px, y * 2 + py,
                                    !!(words[py * 2 + x / 8] & (0x8000u >> ((x & 7) * 2 + px))));
                    else
                        for (unsigned p = 0; p < 4; p++) {
                            uint16 bit = 0x8000u >> x, *word = scene + y * 80 + g * 4 + p;
                            *word = (*word & ~bit) | (words[p] & bit);
                        }
                }
                Video_Atari_PlanarMergeGroup((uint8 *)screen, y, g, mask, words);
                memcpy(expected, scene, sizeof(scene));
                overlays(expected);
                assert(!memcmp(screen, expected, sizeof(screen)));
            }
            for (unsigned i = 0; i < s_placeBlockCount; i++) {
                PlacementBlock *block = &s_placeBlocks[i];
                uint16 words[4];
                s_planarBackend->readGroup(scene, 80, block->y, block->group, words);
                assert(!memcmp(words, block->saved, sizeof(words)));
            }
            s_curDrawn = false;
            memcpy(expected, scene, sizeof(scene));
            overlays(expected);
            if (layers & 1)
                for (unsigned y = 0; y < 3; y++)
                    for (unsigned g = 0; g < 2; g++) {
                        uint16 words[4];
                        s_planarBackend->readGroup(expected, 80, y + 50, g + 2, words);
                        assert(!memcmp(words, &s_curSave[y][g * 4], sizeof(words)));
                    }
        }
    nativeMono = true;
    s_planarBackend = &s_monoBackend;
}
static void check_shared_tile_text(void)
{
    const unsigned positions[][2] = {{32,49}, {0,0}, {272,184}};
    uint16 pixels[64], masks[16], saved[64];
    for (unsigned i = 0; i < 64; i++) pixels[i] = 0x7d13u ^ (i * 137u);
    for (unsigned i = 0; i < 16; i++) masks[i] = i % 3 == 0 ? 0 : i % 3 == 1 ? 0xffff : 0x936f;
    memcpy(saved, pixels, sizeof(saved));
    s_viewportBlitter = g_videoDisplayListActive = false;
    for (unsigned mode = 0; mode < 2; mode++)
     for (unsigned layers = 0; layers < 4; layers++)
      for (unsigned pos = 0; pos < 3; pos++)
       for (unsigned kind = 0; kind < 3; kind++) {
        unsigned width = kind == 2 ? 48 : 16, height = kind == 2 ? 5 : 16;
        unsigned x = positions[pos][0], y = positions[pos][1];
        nativeMono = mode;
        s_planarBackend = mode ? &s_monoBackend : &s_colourBackend;
        reset_layers(layers & 1, layers & 2);
        for (unsigned row = 0; row < height; row++)
         for (unsigned col = 0; col < width; col++) {
            unsigned index = row * (width / 16) + col / 16;
            uint16 bit = 0x8000u >> (col & 15);
            if (kind && !(masks[index] & bit)) continue;
            if (mode)
                for (unsigned py = 0; py < 2; py++)
                    for (unsigned px = 0; px < 2; px++)
                        put(scene, 40, (x + col) * 2 + px, (y + row) * 2 + py,
                            pixel(pixels, width / 8, col * 2 + px, row * 2 + py));
            else
                for (unsigned p = 0; p < 4; p++) {
                    uint16 *word = scene + (y + row) * 80 + (x + col) / 16 * 4 + p;
                    *word = (*word & ~bit) | (pixels[index * 4 + p] & bit);
                }
         }
        if (kind == 2) Video_Atari_PresentPlanarText(pixels, masks, width, height, x, y);
        else Video_Atari_DrawPlanarTile(pixels, masks, x, y, kind == 0 ? pixels : NULL);
        memcpy(expected, scene, sizeof(scene));
        overlays(expected);
        assert(!memcmp(screen, expected, sizeof(screen)));
        assert(!memcmp(saved, pixels, sizeof(saved)));
       }
    nativeMono = true;
    s_planarBackend = &s_monoBackend;
}
static void check_opaque_runs(void)
{
    const unsigned cases[][5] = {
        {0, 0, 320, 200, 320}, {16, 49, 32, 5, 35}, {240, 197, 80, 3, 81},
        {0, 39, 16, 3, 16}, {32, 50, 16, 1, 16}, {48, 51, 16, 2, 17},
        {16, 49, 64, 5, 320},
    };
    for (unsigned y = 0; y < 4; y++)
        for (unsigned x = 0; x < 4; x++)
            for (unsigned c = 0; c < 256; c++)
                s_palette4BitDither.pens[y][x][c] = ((c >> ((x + y * 4) & 7)) ^ x ^ y) & 1;
    for (unsigned polarity = 0; polarity < 2; polarity++)
        for (unsigned overlay = 0; overlay < 4; overlay++)
             for (unsigned absolutePhase = 0; absolutePhase < 2; absolutePhase++)
              for (unsigned i = 0; i < sizeof(cases) / sizeof(*cases); i++) {
                unsigned x = cases[i][0], y = cases[i][1], w = cases[i][2];
                unsigned h = cases[i][3], stride = cases[i][4];
                size_t size = (h - 1) * stride + w;
                uint8 *allocation = malloc(size + 1), *src;
                assert(allocation != NULL);
                src = allocation + 1;
                for (unsigned j = 0; j < size; j++) src[j] = j * 37 + j / stride * 53;
                s_monoWhiteIsOne = polarity;
                Video_Atari_MonoPreparePackedLookup(&s_paletteMonoPacked, &s_palette4BitDither,
                    0, 256, polarity);
                reset_layers(overlay & 1, overlay & 2);
                for (unsigned sy = 0; sy < h; sy++)
                    for (unsigned sx = 0; sx < w; sx++) {
                        for (unsigned dy = 0; dy < 2; dy++)
                            for (unsigned dx = 0; dx < 2; dx++)
                                put(scene, 40, (x + sx) * 2 + dx, (y + sy) * 2 + dy,
                                    s_palette4BitDither.pens[((sy + (absolutePhase ? y : 0)) * 2 + dy) & 3]
                                        [((sx + (absolutePhase ? x : 0)) * 2 + dx) & 3]
                                        [src[sy * stride + sx]] ^ !polarity);
                    }
                fastRows = slowCalls = 0;
                if (absolutePhase)
                    Video_Atari_ConvertRun((uint8 *)screen, src, stride, x, y, w, h, x, y);
                else assert(Video_Atari_PresentChunky(src, stride, x, y, w, h));
                assert(fastRows == h && slowCalls == 0);
                memcpy(expected, scene, sizeof(scene));
                overlays(expected);
                assert(!memcmp(screen, expected, sizeof(screen)));
                uint16 saved[24];
                assert(Video_Atari_PresentSave(32, 50, 32, 3, (uint8 *)saved));
                for (unsigned row = 0; row < 6; row++)
                    for (unsigned col = 0; col < 64; col++)
                        assert(pixel(saved, 4, col, row) == pixel(scene, 40, col + 64, row + 100));
                free(allocation);
            }
    /* Bottom-row and partial-group conversion retain their bounded fast paths. */
    uint8 src[320] = {0};
    fastRows = slowCalls = 0;
    assert(Video_Atari_PresentChunky(src, 320, 0, 199, 320, 1));
    convertedPixels = 0;
    assert(Video_Atari_PresentChunky(src, 320, 1, 0, 15, 1));
    assert(fastRows == 2 && slowCalls == 0 && convertedPixels == 16);
}
static void check_unaligned_opaque_runs(void)
{
    const unsigned widths[] = {1, 7, 15, 16, 17, 31, 32, 63, 271};
    const unsigned ys[] = {0, 39, 49, 191};
    for (unsigned phase = 0; phase < 16; phase++)
      for (unsigned wi = 0; wi < sizeof(widths) / sizeof(*widths); wi++)
        for (unsigned yi = 0; yi < sizeof(ys) / sizeof(*ys); yi++)
          for (unsigned polarity = 0; polarity < 2; polarity++)
            for (unsigned overlay = 0; overlay < 2; overlay++) {
                unsigned x = 32 + phase, y = ys[yi], w = widths[wi], h = 9, stride = w + 3;
                size_t bytes = (h - 1) * stride + w;
                uint8 *allocation = malloc(bytes + 1), *src;
                assert(allocation != NULL);
                src = allocation + 1;
                for (unsigned i = 0; i < bytes; i++) src[i] = i * 37 + i / stride * 53;
                s_monoWhiteIsOne = polarity;
                Video_Atari_MonoPreparePackedLookup(&s_paletteMonoPacked, &s_palette4BitDither,
                    0, 256, polarity);
                reset(overlay);
                for (unsigned row = 0; row < h; row++)
                    for (unsigned col = 0; col < w; col++) {
                        for (unsigned dy = 0; dy < 2; dy++)
                            for (unsigned dx = 0; dx < 2; dx++)
                                put(scene, 40, (x + col) * 2 + dx, (y + row) * 2 + dy,
                                    s_palette4BitDither.pens[(row * 2 + dy) & 3]
                                        [(col * 2 + dx) & 3][src[row * stride + col]] ^ !polarity);
                    }
                convertedPixels = 0;
                assert(Video_Atari_PresentChunky(src, stride, x, y, w, h));
                assert(convertedPixels <= (w + 30) / 16 * 16 * h);
                memcpy(expected, scene, sizeof(scene));
                overlays(expected);
                assert(!memcmp(screen, expected, sizeof(screen)));
                uint16 saved[24];
                assert(Video_Atari_PresentSave(32, 50, 32, 3, (uint8 *)saved));
                for (unsigned row = 0; row < 6; row++)
                    for (unsigned col = 0; col < 64; col++)
                        assert(pixel(saved, 4, col, row) == pixel(scene, 40, col + 64, row + 100));
                free(allocation);
              }
}
static void check_native_overlay_rectangles(void)
{
    uint16 pixels[80 * 9];
    const unsigned widths[] = {1, 15, 16, 17, 31, 32, 63};
    for (unsigned i = 0; i < 80 * 9; i++) pixels[i] = 0x7d13u ^ (i * 137u);
    for (unsigned phase = 0; phase < 16; phase++)
      for (unsigned wi = 0; wi < sizeof(widths) / sizeof(*widths); wi++)
        for (unsigned restore = 0; restore < 2; restore++)
          for (unsigned overlay = 0; overlay < 2; overlay++) {
                unsigned x = 32 + phase, w = widths[wi], y = 49, h = 9;
                unsigned left = restore ? x & ~15u : x;
                unsigned right = restore ? (x + w + 15) & ~15u : x + w;
                unsigned sx = restore ? 0 : x;
                reset(overlay);
                for (unsigned row = 0; row < h; row++)
                    for (unsigned col = left; col < right; col++) {
                        for (unsigned dy = 0; dy < 2; dy++)
                            for (unsigned dx = 0; dx < 2; dx++)
                                put(scene, 40, col * 2 + dx, (y + row) * 2 + dy,
                                    pixel(pixels, 40, (sx + col - left) * 2 + dx, row * 2 + dy));
                    }
                if (restore)
                    assert(Video_Atari_PresentRestoreStrided(x, y, w, h, (const uint8 *)pixels, 160));
                else Video_Atari_PresentPlanarWindow(pixels, x, y, w, h);
                memcpy(expected, scene, sizeof(scene));
                overlays(expected);
                assert(!memcmp(screen, expected, sizeof(screen)));
                uint16 saved[24];
                assert(Video_Atari_PresentSave(32, 50, 32, 3, (uint8 *)saved));
                for (unsigned row = 0; row < 6; row++)
                    for (unsigned col = 0; col < 64; col++)
                        assert(pixel(saved, 4, col, row) == pixel(scene, 40, col + 64, row + 100));
            }
}
static void check_protected_sprites(void)
{
    enum { SW = 80, SH = 33 };
    uint16 pixels[SW / 4 * SH], masked[SW / 4 * SH], expanded[SW / 4 * SH];
    uint16 masks[SW / 16 * SH], savedPixels[SW / 4 * SH], savedMasks[SW / 4 * SH];
    const unsigned widths[] = {1, 17, 33, 0};
    Video_Atari_SpriteBlitCode code;
    (void)FULL_SPRITE_BLIT_CODE;
    for (unsigned i = 0; i < SW / 4 * SH; i++) pixels[i] = 0x7d13u ^ (i * 137u);
    for (unsigned i = 0; i < SW / 16 * SH; i++) masks[i] = 0x936fu ^ (i * 971u);
    memcpy(masked, pixels, sizeof(pixels));
    Video_Atari_MonoMaskBitmap(masked, expanded, masks, SW, SH);
    memcpy(savedPixels, masked, sizeof(masked)); memcpy(savedMasks, expanded, sizeof(expanded));
    Video_Atari_CompileSpriteBlitCode(&code, Video_Atari_BuildSpriteBlitRecipe(masked, masks, SW / 16 * SH));
    memset(s_viewportFogWritable, 0, sizeof(s_viewportFogWritable));
    s_viewportFogWritable[0][2] = fog;
    s_viewportFogWritable[1][3] = hidden;
    s_viewportProtectedRows[0] = 1u << 2;
    s_viewportProtectedRows[1] = (1u << 3) | (1u << 1);
    s_viewportHiddenRows[1] = 1u << 3;
    s_viewportFogWritable[1][1] = partialFog;
    s_viewportProtectionActive = true;
    for (unsigned queued = 0; queued < 2; queued++)
    for (unsigned hardware = 0; hardware < 2; hardware++)
    for (unsigned highlight = 0; highlight < 2; highlight++)
    for (unsigned overlay = 0; overlay < 2; overlay++)
    for (unsigned phase = 0; phase < 16; phase++)
    for (unsigned sourceBase = 0; sourceBase < 2; sourceBase++)
    for (unsigned sourcePhase = 0; sourcePhase < 16; sourcePhase++)
    for (unsigned wi = 0; wi < sizeof(widths) / sizeof(*widths); wi++) {
        unsigned x = 16 + phase, y = 49, sx = sourceBase * 16 + sourcePhase;
        unsigned w = widths[wi] ? widths[wi] : SW - sx;
        reset(overlay);
        g_videoDisplayListActive = queued; s_viewportBlitter = hardware;
        s_spriteHighlightEffect = highlight;
        spriteQueues = spriteFallbacks = spriteMerges = 0;
        unsigned launches = blitterLaunches;
        for (unsigned row = 0; row < SH; row++)
            for (unsigned col = 0; col < w; col++) {
                unsigned dx = x + col, dy = y + row, sourceX = sx + col;
                const uint16 *writable = Video_Atari_ViewportWritable(dx / 16, (dy - 40) / 16);
                if (writable && !(writable[(dy - 40) & 15] & (0x8000u >> (dx & 15)))) continue;
                if (!(masks[row * (SW / 16) + sourceX / 16] & (0x8000u >> (sourceX & 15)))) continue;
                for (unsigned py = 0; py < 2; py++)
                    for (unsigned px = 0; px < 2; px++)
                        put(scene, 40, dx * 2 + px, dy * 2 + py,
                            pixel(pixels, SW / 8, sourceX * 2 + px, row * 2 + py) ^ highlight);
            }
        checkingSprite = true;
        Video_Atari_PresentPlanarSpriteUnshifted(masked, expanded, SW, sx, w, SH, x, y, NULL, &code);
        Video_Atari_DisplayListFlush();
        checkingSprite = false;
        memcpy(expected, scene, sizeof(scene)); overlays(expected);
        assert(!memcmp(screen, expected, sizeof(screen)));
        assert(!memcmp(masked, savedPixels, sizeof(masked)) && !memcmp(expanded, savedMasks, sizeof(expanded)));
        if (hardware && !highlight && !overlay) {
            assert(spriteFallbacks == 0);
            assert(blitterLaunches > launches);
            assert(queued ? spriteQueues > 0 : spriteQueues == 0);
            assert(spriteMerges == 0);
        } else if (!hardware || highlight) assert(blitterLaunches == launches);
        if (hardware && !highlight && overlay == 1) assert(blitterLaunches > launches);
        if (overlay & 2) {
            for (unsigned row = 0; row < 3; row++)
                for (unsigned group = 0; group < 2; group++) {
                    uint16 background[4];
                    Video_Atari_MonoReadGroup(scene, 80, row + 50, group + 2, background);
                    assert(!memcmp(background, s_placeBlocks[row * 2 + group].saved, sizeof(background)));
                }
        }
    }
    /* A fully hidden sprite must neither merge pixels nor emit a launch/flush. */
    reset(false);
    s_spriteHighlightEffect = 0;
    spriteQueues = spriteFallbacks = spriteMerges = 0;
    unsigned flushes = spriteFlushes, launches = blitterLaunches;
    checkingSprite = true;
    Video_Atari_PresentPlanarSpriteUnshifted(masked, expanded, SW, 1, 7, 9, 49, 57, NULL, &code);
    checkingSprite = false;
    assert(spriteQueues == 0 && spriteFallbacks == 0 && spriteMerges == 0);
    assert(spriteFlushes == flushes && blitterLaunches == launches);
    assert(!memcmp(screen, original, sizeof(screen)));
    /* Compact CPU sprites use the same clipping/splitting, with native column offsets. */
    const int compactX[] = {-16, 0, 16, 32, 224};
    const int compactY[] = {38, 49, 183};
    for (unsigned xi = 0; xi < sizeof(compactX) / sizeof(*compactX); xi++)
    for (unsigned yi = 0; yi < sizeof(compactY) / sizeof(*compactY); yi++) {
        int x = compactX[xi], y = compactY[yi];
        reset(true);
        s_viewportBlitter = false; g_videoDisplayListActive = false;
        for (unsigned row = 0; row < SH; row++)
            for (unsigned col = 0; col < 64; col++) {
                int dx = x + col, dy = y + row;
                if (dx < 0 || dx >= 240 || dy < 40 || dy >= 200) continue;
                const uint16 *writable = Video_Atari_ViewportWritable(dx / 16, (dy - 40) / 16);
                if (writable && !(writable[(dy - 40) & 15] & (0x8000u >> (dx & 15)))) continue;
                if (!(masks[row * (SW / 16) + col / 16] & (0x8000u >> (col & 15)))) continue;
                for (unsigned py = 0; py < 2; py++) for (unsigned px = 0; px < 2; px++)
                    put(scene, 40, dx * 2 + px, dy * 2 + py,
                        pixel(pixels, SW / 8, col * 2 + px, row * 2 + py));
            }
        Video_Atari_PresentPlanarSpriteStrided(pixels, masks, 64, SH, x, y, SW);
        memcpy(expected, scene, sizeof(scene)); overlays(expected);
        assert(!memcmp(screen, expected, sizeof(screen)));
    }
    g_videoScrollPending = true;
    unsigned finished = scrollFinishes;
    Video_Atari_PresentPlanarSpriteUnshifted(masked, expanded, SW, 0, 7, 1, 128, 40, NULL, &code);
    assert(!g_videoScrollPending && scrollFinishes == finished + 1);
    Video_Atari_SpriteBlitGeometry geometry[16];
    Video_Atari_BuildSpriteBlitGeometry(geometry, SW, 0, 7);
    reset(false);
    g_videoDisplayListActive = true; s_viewportBlitter = true;
    for (unsigned col = 0; col < 7; col++) {
        if (!(masks[col / 16] & (0x8000u >> (col & 15)))) continue;
        for (unsigned py = 0; py < 2; py++) for (unsigned px = 0; px < 2; px++)
            put(scene, 40, (128 + col) * 2 + px, 80 + py,
                pixel(pixels, SW / 8, col * 2 + px, py));
    }
    unsigned queued = spriteQueues;
    Video_Atari_PresentPlanarSpriteUnshifted(masked, expanded, SW, 0, 7, 1, 128, 40, &geometry[0], &code);
    assert(spriteQueues == queued + 1);
    Video_Atari_DisplayListFlush();
    assert(!memcmp(screen, scene, sizeof(screen)));
}
static void check_mode_neutral_cursor(void)
{
    uint16 pixels[64], masks[64];
    Video_Atari_SpriteBlitCode code;
    for (unsigned i = 0; i < 64; i++) { pixels[i] = 0xa39fu ^ (i * 1973u); masks[i] = 0xffff; }
    for (unsigned mode = 0; mode < 2; mode++)
    for (unsigned hardware = 0; hardware < 2; hardware++)
    for (unsigned queued = 0; queued <= hardware; queued++)
    for (unsigned shape = TILE_CURSOR_NORMAL; shape <= TILE_CURSOR_SCROLL_LEFT; shape++)
    for (unsigned pen = 0; pen < 16; pen++) {
        nativeMono = mode;
        s_planarBackend = mode ? &s_monoBackend : &s_colourBackend;
        Video_Atari_InitTileCursorBackend();
        reset(false);
        memset(s_viewportProtectedRows, 0, sizeof(s_viewportProtectedRows));
        memset(s_viewportHiddenRows, 0, sizeof(s_viewportHiddenRows));
        memset(s_viewportFogWritable, 0, sizeof(s_viewportFogWritable));
        g_videoDisplayListActive = queued; s_viewportBlitter = hardware;
        s_spriteHighlightEffect = 0;
        g_tileCursorPen = g_tileCursorTargetPen = pen;
        Video_Atari_BeginViewportProtection(true, 3, 2, shape);
        unsigned flushes = spriteFlushes;
        Video_Atari_BeginViewportProtection(true, 3, 2, shape);
        assert(spriteFlushes == flushes);
        assert(!Video_Atari_ViewportProtectionOverlap(48, 72, 16, 16));
        assert(Video_Atari_ViewportWritable(3, 2) == NULL);
        assert(g_videoTileCursorTail != NULL && !g_videoTileCursorRestored);
        void (*tail)(void) = g_videoTileCursorTail;
        uint16 prepared[64];
        memcpy(prepared, s_tileCursorPixels, sizeof(prepared));
        if (queued) queue[queueCount++] = (QueuedSprite){.tail = tail};
        g_tileCursorPen = g_tileCursorTargetPen = (pen + 1) & 15;
        Video_Atari_TileCursorFrame(3, 2, shape == TILE_CURSOR_SCROLL_LEFT ? TILE_CURSOR_NORMAL : shape + 1);
        g_tileCursorPen = g_tileCursorTargetPen = pen;
        assert(queueCount == 0 && g_videoTileCursorTail == tail);
        assert(s_tileCursorCol == 3 && s_tileCursorTop == 72 && s_tileCursorPen == pen);
        assert(s_tileCursorPattern == s_tileCursorPatterns[shape]);
        assert(!memcmp(prepared, s_tileCursorPixels, sizeof(prepared)));
        if (hardware) {
            Video_Atari_CompileSpriteBlitCode(&code, mode ? 0x11 : 0xff);
            checkingSprite = true;
            spriteFallbacks = spriteMerges = 0;
            Video_Atari_PresentPlanarSpriteUnshifted(pixels, masks, 16, 0, 16, 16, 48, 72, NULL, &code);
            Video_Atari_DisplayListFlush();
            checkingSprite = false;
            assert(spriteFallbacks == 0 && spriteMerges == 0);
        } else {
            unsigned before = opaqueRuns;
            Video_Atari_DrawPlanarTile(pixels, masks, 48, 72, pixels);
            assert(opaqueRuns == before + 1);
            assert(g_videoTileCursorRestored);
        }
        memcpy(expected, original, sizeof(expected));
        for (unsigned line = 0; line < 16; line++)
            for (unsigned col = 0; col < 16; col++) {
                bool frame = !!(s_tileCursorPatterns[shape][line] & (0x8000u >> col));
                if (mode) {
                    for (unsigned py = 0; py < 2; py++) for (unsigned px = 0; px < 2; px++) {
                        unsigned value = pixel(pixels, 2, col * 2 + px, line * 2 + py);
                        if (frame) {
                            unsigned bit = 15 - (((line * 2 + py) & 3) * 4 + ((col * 2 + px) & 3));
                            value = ((s_paletteMonoST[pen] >> bit) & 1) ^ !s_monoWhiteIsOne;
                        }
                        put(expected, 40, 96 + col * 2 + px, 144 + line * 2 + py, value);
                    }
                } else for (unsigned plane = 0; plane < 4; plane++) {
                    uint16 bit = 0x8000u >> col, *dst = expected + (72 + line) * 80 + 12 + plane;
                    bool value = frame ? !!(pen & (1u << plane)) : !!(pixels[line * 4 + plane] & bit);
                    *dst = (*dst & ~bit) | (value ? bit : 0);
                }
            }
        if (!hardware) {
            assert(!memcmp(screen, expected, sizeof(screen)));
            Video_Atari_PublishPlanarRect((const uint8 *)pixels, 8, 0, 48, 72, 16, 16);
            assert(g_videoTileCursorRestored && !memcmp(screen, expected, sizeof(screen)));
        }
        if (queued) {
            assert(queueCount < 32);
            queue[queueCount++] = (QueuedSprite){.tail = g_videoTileCursorTail};
            Video_Atari_EndViewportProtection();
            Video_Atari_DisplayListFlush();
        } else {
            g_videoTileCursorRestored = false;
            Video_Atari_TileCursorFrame(3, 2, shape);
            Video_Atari_EndViewportProtection();
        }
        assert(!memcmp(screen, expected, sizeof(screen)));
        assert(g_videoTileCursorRestored && g_videoTileCursorTail == NULL);
        s_viewportFogWritable[2][3] = hidden;
        s_viewportProtectedRows[2] = s_viewportHiddenRows[2] = 1u << 3;
        Video_Atari_BeginViewportProtection(true, 3, 2, shape);
        assert(Video_Atari_ViewportProtectionOverlap(48, 72, 16, 16));
        assert(Video_Atari_ViewportWritable(3, 2) == hidden);
        Video_Atari_EndViewportProtection();
    }
    nativeMono = true;
    s_planarBackend = &s_monoBackend;
}
int main(void)
{
    AtariPlanarBackend backend = s_monoBackend;
    backend.convert = record_prepare;
    s_planarBackend = &backend;
    enum { SW = 48, SH = 5 };
    uint16 pixels[SW / 4 * SH], masked[SW / 4 * SH], expanded[SW / 4 * SH], masks[SW / 16 * SH];
    const int xs[] = {-19, -1, 0, 1, 7, 8, 15, 16, 31, 32, 47, 63, 224, 239, 319};
    const int ys[] = {-2, 38, 49, 198};
    for (unsigned i = 0; i < 16000; i++) original[i] = 0xa39fu ^ (i * 1973u);
    for (unsigned i = 0; i < SW / 4 * SH; i++) pixels[i] = 0x7d13u ^ (i * 137u);
    for (unsigned i = 0; i < SW / 16 * SH; i++) masks[i] = 0x936fu ^ (i * 971u);
    memcpy(masked, pixels, sizeof(pixels));
    Video_Atari_MonoMaskBitmap(masked, expanded, masks, SW, SH);
    for (unsigned row = 0; row < 16; row++) {
        fog[row] = 0xd7bdu ^ (row * 71u);
        partialFog[row] = row == 0 || row == 15 ? 0 : 0x7ffe;
    }
    s_viewportFogWritable[0][0] = fog;
    s_viewportFogWritable[0][1] = fog;
    unused = s_viewportFogWritable[0][2];
    assert(unused == NULL);
    for (unsigned xi = 0; xi < sizeof(xs) / sizeof(*xs); xi++)
        for (unsigned yi = 0; yi < sizeof(ys) / sizeof(*ys); yi++)
            for (unsigned sx = 0; sx <= 17; sx += 1)
                for (unsigned variant = 0; variant < 4; variant++) {
                    int x = xs[xi], y = ys[yi];
                    unsigned width = (variant & 1) ? 1 : SW - sx;
                    bool overlay = (variant & 2) != 0, highlight = (sx & 2) != 0;
                    reset(overlay);
                    s_viewportProtectionActive = false;
                    s_spriteHighlightEffect = highlight;
                    for (unsigned row = 0; row < SH; row++)
                        for (unsigned col = 0; col < width; col++) {
                            int dx = x + col, dy = y + row;
                            unsigned sourceX = sx + col;
                            if (dx < 0 || dx >= 320 || dy < 0 || dy >= 200) continue;
                            if (!(masks[row * 3 + sourceX / 16] & (0x8000u >> (sourceX & 15)))) continue;
                            for (unsigned py = 0; py < 2; py++)
                                for (unsigned px = 0; px < 2; px++)
                                    put(scene, 40, dx * 2 + px, dy * 2 + py,
                                        pixel(pixels, SW / 8, sourceX * 2 + px, row * 2 + py));
                        }
                    Video_Atari_PublishNativeRect(pixels, masks, SW, sx, width, SH, x, y);
                    memcpy(expected, scene, sizeof(scene));
                    overlays(expected);
                    assert(!memcmp(screen, expected, sizeof(screen)));
                    uint16 saved[24];
                    assert(Video_Atari_PresentSave(32, 50, 32, 3, (uint8 *)saved));
                    for (unsigned row = 0; row < 6; row++)
                        for (unsigned col = 0; col < 64; col++)
                            assert(pixel(saved, 4, col, row) == pixel(scene, 40, col + 64, row + 100));
                    assert(Video_Atari_PresentRestoreStrided(0, 10, 32, 3, (const uint8 *)saved, 16));
                    for (unsigned row = 0; row < 6; row++)
                        for (unsigned col = 0; col < 64; col++)
                            put(expected, 40, col, row + 20, pixel(saved, 4, col, row));
                    assert(!memcmp(screen, expected, sizeof(screen)));
                }
    check_opaque_runs();
    check_unaligned_opaque_runs();
    check_native_overlay_rectangles();
    check_protected_sprites();
    check_mode_neutral_cursor();
    check_shared_overlay_order();
    check_shared_tile_text();
    return 0;
}
"""
        merge = function(VIDEO, "Video_Atari_PlanarMergeGroup")
        production = production.replace(merge, merge.replace("\n{", "\n{\n    if (checkingSprite) spriteMerges++;", 1))
        bulk = function(VIDEO, "Video_Atari_PublishPlanarRun")
        production = production.replace(bulk, bulk.replace("\n{", "\n{\n    opaqueRuns++;", 1))
        run_harness(harness.replace("/* BACKEND */", backend_declarations(VIDEO))
                    .replace("/* BLIT TYPES */", blit_plan_type())
                    .replace("/* CURSOR TYPES */", cursor_types)
                    .replace("/* REFRESH ARGS */", refresh_args)
                    .replace("/* SPRITE */", sprite)
                    .replace("/* CURSOR */", cursor)
                    .replace("/* PRODUCTION */", production.replace(
            "(uint32)src", "(uintptr_t)src").replace("(uint32)fullSrc", "(uintptr_t)fullSrc")))


if __name__ == "__main__":
    unittest.main()
