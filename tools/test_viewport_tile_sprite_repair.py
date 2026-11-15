"""Exercise tile-clipped repair with cached CPU images and compiled BLITTER code."""

from pathlib import Path
import unittest

from tools.test_unit_smoke_damage import run_harness
from tools.test_viewport_sprite_cache import blit_plan_type, blitter_model, function, inactive_display_list


ROOT = Path(__file__).resolve().parents[1]


class ViewportTileSpriteRepairTest(unittest.TestCase):
    def test_pixels_batching_and_foreground_order(self):
        gui = (ROOT / "src/gui/gui.c").read_text()
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        video = (ROOT / "src/video/video_atari.c").read_text()
        cached = function(gui, "GUI_ViewportPlanarSprite")
        publication = cached[cached.index("\tentry->used = s_viewportPlanarClock;"):]
        publication = publication[:publication.rfind("\n}")].replace("\npresent:\n", "\n")
        sprite_type = gui[gui.index("typedef struct ViewportPlanarSprite {"):
                          gui.index("} ViewportPlanarSprite;") + len("} ViewportPlanarSprite;")]
        header = (ROOT / "src/gui/gui.h").read_text()
        bounds_type = header[header.index("typedef struct GUI_SpriteBounds {"):
                             header.index("} GUI_SpriteBounds;") + len("} GUI_SpriteBounds;")]
        image_type = gui[gui.index("typedef struct ViewportPlanarImage {"):
                         gui.index("} ViewportPlanarImage;") + len("} ViewportPlanarImage;")]
        sprite_type = bounds_type + "\n" + image_type + "\n" + sprite_type
        damage = "\n".join(function(viewport, name) for name in (
            "Viewport_ColumnMask",
            "GUI_Widget_Viewport_DebugRect",
            "GUI_Widget_Viewport_BeginSpriteDamage",
            "GUI_Widget_Viewport_SpriteDamageRect",
            "GUI_Widget_Viewport_ShouldDrawSprite",
            "GUI_Widget_Viewport_SpriteRepairMask",
        ))
        cpu = inactive_display_list() + "\n".join(function(video, name) for name in (
            "Video_Atari_CursorRectOverlap",
            "Video_Atari_PlacementRectOverlap",
            "Video_Atari_PlanarOverlaysOverlap",
            "Video_Atari_PlanarMergePlain",
            "Video_Atari_PlanarCopyGroup",
            "Video_Atari_CursorGroup",
            "Video_Atari_CursorBackground",
            "Video_Atari_CursorWriteGroup",
            "Video_Atari_PlacementBlock",
            "Video_Atari_PlanarMergeGroup",
        ))
        merge = function(video, "Video_Atari_PlanarMergeGroup")
        cpu = cpu.replace(merge, merge.replace("\n{", "\n{\n    mergeGroups++;", 1))
        cpu += r"""
/* Model the assembly refresh's masked backup update and cursor reapply.
 * The production unshifted mask alignment and all protected publishers
 * remain intact. */
static void Video_Atari_RefreshViewportCursor(uint8 *base, uint16 first, uint16 end,
    uint16 top, uint16 bottom, const uint16 *masks, uint16 stride) {
    if (!s_curDrawn || base != s_curDrawnBase) return;
    for (unsigned y = max(top, s_curDrawnY); y < min(bottom, s_curDrawnY + s_curDrawnH); y++)
        for (unsigned group = max(first, s_curDrawnGroup);
             group < min(end, s_curDrawnGroup + s_curDrawnGroups); group++) {
            uint16 mask = masks ? masks[(y - top) * stride + group - first] : 0xffff;
            uint16 words[4];
            unsigned cy = y - s_curDrawnY, cg = group - s_curDrawnGroup;
            for (unsigned p = 0; p < 4; p++)
                words[p] = (s_curSave[cy][cg * 4 + p] & (uint16)~mask) |
                           (screen[y * 80 + group * 4 + p] & mask);
            Video_Atari_CursorWriteGroup(base, y, group, words);
        }
}
"""
        cpu += "\n".join(function(video, name) for name in (
            "Video_Atari_PublishViewportCursorRect",
            "Video_Atari_PresentPlanarSpriteOverlays",
            "Video_Atari_PublishPlanarSpritePlain",
            "Video_Atari_PresentPlanarSpriteStrided",
        ))
        protection = video[video.index("static const uint16 s_tileCursorPatterns"):
                           video.index("/* Battlefield tile cursor:")]
        header = (ROOT / "src/video/video.h").read_text()
        shape_type = header[header.index("typedef enum VideoAtariTileCursorShape"):
                            header.index("} VideoAtariTileCursorShape;") +
                            len("} VideoAtariTileCursorShape;")]
        protection = (shape_type + "\n" + blit_plan_type() + """
static const uint16 *s_blitterHalftonePattern;
void Video_Atari_EndViewportProtection(void);
static void Video_Atari_PresentProtectedSprite(const uint16 *, const uint16 *,
    uint16, uint16, uint16, uint16, uint16, uint16, bool,
    const Video_Atari_SpriteBlitCode *);
void Video_Atari_PresentPlanarSpriteUnshifted(const uint16 *, const uint16 *,
    uint16, uint16, uint16, uint16, uint16, uint16,
    const Video_Atari_SpriteBlitGeometry *, const Video_Atari_SpriteBlitCode *);
""" + protection)
        model = blitter_model(video, protected=True)
        stub_start = model.index("static bool Video_Atari_CursorRectOverlap(")
        stub_end = model.index("#define Video_Atari_RefreshViewportCursorUnshifted", stub_start)
        stub_end = model.index("\n", stub_end) + 1
        model = model[:stub_start] + (
            "static uint16 Video_Atari_ShiftSpriteWord(const uint16 *, uint16, uint16, uint16, uint16);\n" +
            function(video, "Video_Atari_RefreshViewportCursorUnshifted") + "\n" +
            model[stub_end:])
        helper = function(video, "Video_Atari_SetHalftonePattern").replace(
            "(volatile uint16 *)0xFFFF8A00UL", "halftoneRAM")
        tail = helper + """
static void Video_Atari_BlitterStartLine(uint16 line) {
    reg_ctrl = 0xc0 | line;
    Video_Atari_BlitterStart();
}
"""
        tail += function(video, "Video_Atari_BlitProtectedSprite").replace(
            "(uint32)(size_t)", "(uintptr_t)")
        publisher = function(video, "Video_Atari_PresentProtectedSprite")
        publisher = publisher.replace("Atari_SupervisorExec(Video_Atari_BlitProtectedSprite);", """
                    blitterPixels = (uintptr_t)srcPixels;
                    blitterMasks = (uintptr_t)srcMasks;
                    blitterReadStride = sourceWidth / 2;
                    Atari_SupervisorExec(Video_Atari_BlitProtectedSprite);""")
        tail += publisher
        tail += """
#define SCREEN_WIDTH 320
#define SCREEN_HEIGHT 200
static bool Video_Atari_TileOverlaysOverlap(uint8 *base, uint16 x, uint16 y) {
    return Video_Atari_PlanarOverlaysOverlap(base,x,y,16,16);
}
#define Video_Atari_BlitTile(...) assert(false)
"""
        tail += "\n".join(function(video, name) for name in (
            "Video_Atari_DrawPlanarTileFoggedCursor",
            "Video_Atari_DrawPlanarTile", "Video_Atari_DrawPlanarTileFogged"))
        placement = video[video.index("typedef struct PlacementBlock"):
                          video.index("} PlacementBlock;") + len("} PlacementBlock;")]
        limits = "\n".join(line for line in header.splitlines()
                           if line.startswith(("#define VIDEO_ATARI_CURSOR_MAX_WIDTH",
                                               "#define VIDEO_ATARI_CURSOR_MAX_HEIGHT")))
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int16_t int16;
typedef uint32_t uint32;
#include "src/gui/viewport_key.h"
#define VIEWPORT_DEBUG_DAMAGE
#define ATARI_SUPERVISOR_RESIDENT 1
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
#define DIRTY_SRC_SPRITE 1
static bool g_atariSupervisorResident;
static bool s_damageDebugCollect = true;
static uint16 s_damageDebugAccepted[10], g_viewportTerrainDamage[10];
static uint16 s_viewportSpriteDamage[10], s_viewportPlanarClock;
static bool s_viewportSpriteFilterActive, s_viewportSpriteNeedsRedraw;
static uint16 screen[16000], expected[16000], ground[16000], displayed[16000], noCursor[16000];
static uint16 pending[10], permitted[10], repaired[10], published[10];
static unsigned publications, repairCalls, mergeGroups;
static bool cropMargins;
static bool awaitingSprite, restrictWrites;
/* PROTECTION */
/* LIMITS */
#define CURSOR_MAX_H VIDEO_ATARI_CURSOR_MAX_HEIGHT
#define CURSOR_MAX_GROUPS (VIDEO_ATARI_CURSOR_MAX_WIDTH / 16)
/* PLACEMENT */
static unsigned overlayMode;
static bool s_curDrawn;
static uint8 *s_curDrawnBase, *s_placeDrawnBase;
static uint16 s_curDrawnGroup, s_curDrawnGroups, s_curDrawnY, s_curDrawnH;
static uint16 s_curSave[CURSOR_MAX_H][CURSOR_MAX_GROUPS * 4];
static uint16 s_curDrawnData[CURSOR_MAX_H][CURSOR_MAX_GROUPS * 4];
static uint16 s_curDrawnMask[CURSOR_MAX_H][CURSOR_MAX_GROUPS];
static PlacementBlock s_placeBlocks[24];
static uint16 s_placeBlockCount, s_placeDrawnWidth, s_placeDrawnHeight;
static int16 s_placeDrawnX, s_placeDrawnY;
static uint8 s_placePen = 5;
static void Video_Atari_PlanarMergeGroup(uint8 *, uint16, uint16, uint16, const uint16[4]);
static uint8 *Video_Atari_PlanarBase(void) { return (uint8 *)screen; }
static void GFX_Screen_SetDirtySource(unsigned source) {
    assert(source == DIRTY_SRC_SPRITE && awaitingSprite);
}
static void GFX_Screen_ClearDirtyRect(uint16 l, uint16 t, uint16 r, uint16 b) {
    assert((awaitingSprite || s_viewportProtectionActive) && !(l & 15) && !(r & 15));
    assert(l < r && r <= 240 && t >= 40 && t < b && b <= 200);
    uint16 columns = (0x7fff >> (15 - (r >> 4))) & (0x7fff << (l >> 4));
    for (unsigned row = (t - 40) / 16; row < (unsigned)(b - 40 + 15) / 16; row++) {
        if (restrictWrites) assert(!(columns & (uint16)~permitted[row]));
        published[row] |= columns;
    }
    publications++;
    awaitingSprite = false;
}
static void GUI_Widget_Viewport_RepairTiles(int16 l, int16 t, int16 r, int16 b) {
    assert((!awaitingSprite || s_viewportProtectionActive) && !(l & 15) && !(r & 15));
    assert(l >= 0 && l < r && r <= 240 && t >= 40 && t < b && b <= 200);
    uint16 columns = (0x7fff >> (15 - (r >> 4))) & (0x7fff << (l >> 4));
    for (unsigned row = (t - 40) / 16; row < (unsigned)(b - 40 + 15) / 16; row++) {
        uint16 bits = pending[row] & columns;
        assert(!(repaired[row] & bits));
        pending[row] &= (uint16)~bits;
        repaired[row] |= bits;
        for (unsigned col = 0; col < 15; col++) if (bits & (1u << col)) {
            for (unsigned y = 40 + row * 16; y < 56 + row * 16; y++)
                Video_Atari_PlanarMergeGroup((uint8 *)screen, y, col, 0xffff,
                                           ground + y * 80 + col * 4);
        }
    }
    awaitingSprite = true;
    repairCalls++;
}
/* CPU */
/* BLITTER */
/* PROTECTED PUBLISHER */
/* SPRITE TYPE */
/* DAMAGE */
/* REPAIR */
static void drawCached(ViewportPlanarSprite *entry, int16 x, int16 y,
                       bool blitter, uint16 highlight) {
    const ViewportPlanarImage *image;
    /* PUBLICATION */
}
static ViewportPlanarSprite entry;
static uint16 masks[1280], savedPixels[1280], savedMasks[1280];
static void composite(void) {
    memcpy(noCursor, expected, sizeof(noCursor));
    for (unsigned b = 0; b < s_placeBlockCount; b++) {
        PlacementBlock *block = s_placeBlocks + b;
        unsigned dst = block->y * 80 + block->group * 4;
        for (unsigned p = 0; p < 4; p++)
            noCursor[dst + p] = (noCursor[dst + p] & (uint16)~block->mask) |
                               (s_placePen & (1u << p) ? block->mask : 0);
    }
    memcpy(displayed, noCursor, sizeof(displayed));
    if (s_curDrawn) for (unsigned row = 0; row < s_curDrawnH; row++)
        for (unsigned group = 0; group < s_curDrawnGroups; group++) {
            unsigned dst = (s_curDrawnY + row) * 80 + (s_curDrawnGroup + group) * 4;
            uint16 mask = s_curDrawnMask[row][group];
            for (unsigned p = 0; p < 4; p++)
                displayed[dst + p] = (displayed[dst + p] & (uint16)~mask) |
                                    s_curDrawnData[row][group * 4 + p];
        }
}
static void image(int16 left, unsigned width, unsigned height, bool blitter, unsigned variant) {
    memset(&entry, 0, sizeof(entry));
    memset(masks, 0, sizeof(masks));
    unsigned pad = blitter ? 0 : left & 15;
    entry.offsetX = -(int16)pad;
    entry.width = (pad + width + 15) & ~15;
    entry.extentWidth = pad + width;
    entry.boundsWidth = width;
    entry.boundsHeight = height;
    entry.height = height;
    entry.masks = masks;
    unsigned groups = entry.width / 16;
    if (cropMargins) {
        entry.boundsOffsetX = 4;
        entry.boundsOffsetY = 3;
        entry.boundsWidth = width - 9;
        entry.boundsHeight = height - 8;
    }
    for (unsigned row = 0; row < height; row++) for (unsigned x = 0; x < width; x++) {
        if (cropMargins && (x < 4 || x >= width - 5 || row < 3 || row >= height - 5)) continue;
        if ((x + row) % 5 == 0) continue;
        unsigned col = pad + x, group = row * groups + col / 16;
        uint16 bit = 0x8000u >> (col & 15);
        uint16 colour = variant == 1 ? 15 : variant == 2 ? 0 : (x * 3 + row) & 15;
        if (blitter) for (unsigned p = 0; p < 4; p++) masks[group * 4 + p] |= bit;
        else masks[group] |= bit;
        for (unsigned p = 0; p < 4; p++)
            if (colour & (1u << p)) entry.pixels[group * 4 + p] |= bit;
    }
    if (blitter) {
        /* Classify the same compact opacity used at production cache fill. */
        uint16 compact[320];
        for (unsigned i = 0; i < groups * height; i++) compact[i] = masks[i * 4];
        Video_Atari_CompileSpriteBlitCode(&entry.blitCode,
            Video_Atari_BuildSpriteBlitRecipe(entry.pixels, compact, groups * height));
        Video_Atari_BuildSpriteBlitGeometry(entry.blitGeometry, entry.width,
            pad + entry.boundsOffsetX, entry.boundsWidth);
    }
    GUI_ViewportSetPlanarImage(&entry);
    memcpy(savedPixels, entry.pixels, sizeof(savedPixels));
    memcpy(savedMasks, masks, sizeof(savedMasks));
}
static void reference(int16 x, int16 y, bool blitter, bool full, uint16 highlight) {
    int16 left = x + entry.offsetX, top = y + entry.offsetY;
    unsigned groups = entry.width / 16;
    for (unsigned row = 0; row < entry.height; row++) {
        int16 sy = top + row;
        if (sy < 40 || sy >= 200) continue;
        for (unsigned col = 0; col < entry.extentWidth; col++) {
            int16 sx = left + col;
            if (sx < 0 || sx >= 240) continue;
            if (!full && !(permitted[(sy - 40) / 16] & (1u << (sx / 16)))) continue;
            unsigned src = row * groups + col / 16;
            uint16 sb = 0x8000u >> (col & 15), db = 0x8000u >> (sx & 15);
            if (!(masks[blitter ? src * 4 : src] & sb)) continue;
            if (s_viewportProtectionActive) {
                const uint16 *w = Video_Atari_ViewportWritable(sx / 16, (sy - 40) / 16);
                if (w != NULL && !(w[(sy - 40) & 15] & db)) continue;
            }
            for (unsigned p = 0; p < 4; p++) {
                unsigned recipe = highlight ? s_highlightRecipes[highlight - 1][p] : p;
                bool bit = recipe == HL_ZERO ? false : recipe >= 4 ? true :
                           (entry.pixels[src * 4 + recipe] & sb) != 0;
                unsigned dst = sy * 80 + (sx / 16) * 4 + p;
                expected[dst] = (expected[dst] & (uint16)~db) | (bit ? db : 0);
            }
        }
    }
}
static void reset(unsigned pattern) {
    Video_Atari_ResetViewportProtection();
    for (unsigned i = 0; i < 16000; i++) screen[i] = expected[i] = ground[i] = i * 113 + 17;
    memset(repaired, 0, sizeof(repaired));
    memset(published, 0, sizeof(published));
    memset(s_damageDebugAccepted, 0, sizeof(s_damageDebugAccepted));
    for (unsigned row = 0; row < 10; row++) {
        permitted[row] = pattern == 0 ? 0 : pattern == 1 ? 0x7fff :
                         pattern == 2 ? 0x5555u >> (row & 1) :
                         pattern == 3 ? (row >= 2 && row <= 5 ? 0x60 : 0) :
                         pattern == 4 ? (row == 3 ? 1u << 5 : 0) : 0x16b5 ^ (row * 137);
        permitted[row] &= 0x7fff;
    }
    memcpy(pending, permitted, sizeof(pending));
    memcpy(g_viewportTerrainDamage, permitted, sizeof(g_viewportTerrainDamage));
    GUI_Widget_Viewport_BeginSpriteDamage(true);
    publications = repairCalls = 0;
    awaitingSprite = false;
    restrictWrites = true;
    s_placeDrawnBase = s_curDrawnBase = (uint8 *)screen;
    s_placeDrawnX = 64; s_placeDrawnY = 74;
    s_placeDrawnWidth = 32; s_placeDrawnHeight = 12;
    s_placeBlockCount = 0;
    if (overlayMode & 2) for (unsigned y = 74; y < 86; y++)
        for (unsigned group = 4; group < 6; group++) {
            PlacementBlock *b = s_placeBlocks + s_placeBlockCount++;
            b->y = y; b->group = group; b->mask = y % 3 ? 0x39a1 : 0xffff;
            memcpy(b->saved, expected + y * 80 + group * 4, 8);
        }
    s_curDrawn = (overlayMode & 1) != 0;
    s_curDrawnGroup = 4; s_curDrawnGroups = 2; s_curDrawnY = 74; s_curDrawnH = 24;
    for (unsigned row = 0; row < s_curDrawnH; row++)
        for (unsigned group = 0; group < s_curDrawnGroups; group++) {
            uint16 mask = row % 4 == 0 ? 0 : row % 4 == 1 ? 0xffff : 0x39a1 >> group;
            s_curDrawnMask[row][group] = mask;
            for (unsigned p = 0; p < 4; p++)
                s_curDrawnData[row][group * 4 + p] = p == 1 ? 0 : mask;
        }
    composite();
    memcpy(screen, displayed, sizeof(screen));
    for (unsigned row = 0; row < s_curDrawnH; row++)
        memcpy(s_curSave[row], noCursor + (s_curDrawnY + row) * 80 + s_curDrawnGroup * 4,
               s_curDrawnGroups * 8);
}
static void check(int16 x, int16 y, bool blitter, bool full, unsigned highlight) {
    s_viewportSpriteNeedsRedraw = full;
    restrictWrites = !full;
    reference(x, y, blitter, full, highlight);
    uint16 before[10];
    memcpy(before, s_viewportSpriteDamage, sizeof(before));
    drawCached(&entry, x, y, blitter, highlight);
    if (s_viewportProtectionActive) awaitingSprite = false;
    assert(!awaitingSprite && (s_viewportProtectionActive || publications == repairCalls) &&
           s_spriteHighlight == NULL);
    composite();
    assert(!memcmp(screen, displayed, sizeof(screen)));
    if (s_curDrawn) for (unsigned row = 0; row < s_curDrawnH; row++)
        assert(!memcmp(s_curSave[row], noCursor + (s_curDrawnY + row) * 80 + s_curDrawnGroup * 4,
                       s_curDrawnGroups * 8));
    for (unsigned b = 0; b < s_placeBlockCount; b++)
        assert(!memcmp(s_placeBlocks[b].saved,
                       expected + s_placeBlocks[b].y * 80 + s_placeBlocks[b].group * 4, 8));
    assert(!memcmp(entry.pixels, savedPixels, sizeof(savedPixels)));
    assert(!memcmp(masks, savedMasks, sizeof(savedMasks)));
    if (!full) {
        assert(!memcmp(before, s_viewportSpriteDamage, sizeof(before)));
        if (!s_viewportProtectionActive)
            assert(!memcmp(s_damageDebugAccepted, published, sizeof(published)));
    }
}
int main(void) {
    (void)FULL_SPRITE_BLIT_CODE;
    unsigned widths[] = {1, 17, 32, 49, 64};
    unsigned heights[] = {1, 17, 32, 49, 64};
    int16 edges[] = {-31, -1, 0, 223, 239, 240};
    int16 tops[] = {8, 24, 39, 40, 185, 199, 200};
    for (unsigned mode = 0; mode < 2; mode++) {
        s_viewportBlitter = mode != 0;
        /* Transparent margins retain the original source canvas/stride.
         * Full-width draws reuse plans with a nonzero source origin. */
        cropMargins = true;
        for (unsigned phase = 0; phase < 16; phase++)
        for (unsigned yp = 0; yp < 16; yp++)
        for (unsigned full = 0; full < 2; full++)
        for (unsigned pattern = 0; pattern < 6; pattern++) {
            image(64 + phase, 49, 49, mode, pattern % 3);
            reset(pattern);
            check(64 + phase, 72 + yp, mode, full, 0);
        }
        for (unsigned xi = 0; xi < 6; xi++)
        for (unsigned yi = 0; yi < 7; yi++)
        for (unsigned full = 0; full < 2; full++) {
            image(edges[xi],49,49,mode,0);
            reset(2);
            check(edges[xi],tops[yi],mode,full,0);
        }
        cropMargins = false;
        for (unsigned phase = 0; phase < 16; phase++) for (unsigned yphase = 0; yphase < 16; yphase++)
            for (unsigned w = 0; w < 5; w++) for (unsigned pattern = 0; pattern < 6; pattern++) {
                int16 x = 64 + phase, y = 72 + yphase;
                image(x, widths[w], heights[w], mode, pattern % 3);
                reset(pattern);
                g_atariSupervisorResident = (phase & 1) != 0;
                check(x, y, mode, false, 0);
                if (pattern == 1) assert(publications == 1);
                if (pattern == 0) assert(publications == 0);
            }
        for (unsigned x = 0; x < 6; x++) for (unsigned y = 0; y < 7; y++)
            for (unsigned pattern = 0; pattern < 6; pattern++) {
                image(edges[x], 49, 49, mode, 0);
                reset(pattern);
                check(edges[x], tops[y], mode, false, 0);
            }
        for (overlayMode = 1; overlayMode <= 3; overlayMode++)
            for (unsigned phase = 0; phase < 16; phase++)
                for (unsigned pattern = 1; pattern < 6; pattern++) {
                    image(64 + phase, 49, 49, mode, 0);
                    reset(pattern);
                    check(64 + phase, 65 + phase, mode, false, 0);
                }
        overlayMode = 3;
        for (unsigned effect = 0; effect <= 9; effect++) {
            /* CPU's existing compact-cache highlighting is covered for a
             * plane permutation; BLITTER highlights use expanded opacity. */
            if (!mode && effect != 0 && effect != 2) continue;
            image(79, 49, 49, mode, 0);
            reset(4);
            check(79, 81, mode, false, effect);
            reset(0);
            check(79, 81, mode, true, effect);
        }
        /* An independently dirty lower sprite expands foreground damage.
         * Later repair-only images must use that snapshot after terrain was
         * consumed, and must not grow it to their own complete bounds. */
        image(64, 32, 32, mode, 0);
        reset(4);
        check(64, 72, mode, true, 0);
        memcpy(permitted, s_viewportSpriteDamage, sizeof(permitted));
        image(79, 49, 49, mode, 1);
        memset(s_damageDebugAccepted, 0, sizeof(s_damageDebugAccepted));
        memset(published, 0, sizeof(published));
        check(79, 81, mode, false, 0);
        /* Repeat a shared cached image without restoring terrain over the
         * foreground already published, including a disconnected fragment. */
        memset(s_damageDebugAccepted, 0, sizeof(s_damageDebugAccepted));
        memset(published, 0, sizeof(published));
        check(95, 88, mode, false, 0);
        {
            static uint16 hidden[16];
            image(80,8,8,mode,0);
            reset(1);
            Video_Atari_SetViewportFog(5,2,hidden);
            Video_Atari_BeginViewportProtection(false,0,0,false);
            unsigned launches = blitterLaunches;
            check(80,72,mode,false,0);
            assert(blitterLaunches == launches && publications == 0);
            image(80,49,49,mode,0);
            reset(1);
            Video_Atari_BeginViewportProtection(false,0,0,false);
            check(80,72,mode,false,0);
            assert(publications == 1); /* Clear active rectangles keep batching. */
        }
        for (unsigned xi = 0; xi < 6; xi++)
        for (unsigned yi = 0; yi < 7; yi++)
        for (unsigned full = 0; full < 2; full++) {
            static uint16 fog[16], hidden[16];
            image(edges[xi],49,49,mode,0);
            reset(2);
            for (unsigned line = 0; line < 16; line++) fog[line] = line & 1 ? 0x937a : 0xf14c;
            for (unsigned row = 0; row < 10; row++) {
                Video_Atari_SetViewportFog(0,row,fog);
                Video_Atari_SetViewportFog(13,row,hidden);
                Video_Atari_SetViewportFog(14,row,fog);
            }
            Video_Atari_BeginViewportProtection(true,14,9,true);
            check(edges[xi],tops[yi],mode,full,0);
        }
        /* Fog, full rejection and cursor protection, including saved mouse
         * and placement backgrounds, all phases and highlight recipes. */
        for (overlayMode = 0; overlayMode < 4; overlayMode++)
        for (unsigned phase = 0; phase < 16; phase++)
        for (unsigned yp = 0; yp < 16; yp++)
        for (unsigned effect = 0; effect <= 9; effect++) {
            if (!mode && effect != 0 && effect != 2) continue;
            cropMargins = (phase & 1) != 0;
            static uint16 fog[16], hidden[16];
            for (unsigned line = 0; line < 16; line++)
                fog[line] = line & 1 ? 0x39a1 : 0xe50c;
            image(64 + phase, 49, 49, mode, effect % 3);
            reset(1);
            Video_Atari_SetViewportFog(4, 2, fog);
            Video_Atari_SetViewportFog(5, 2, hidden);
            Video_Atari_SetViewportFog(6, 3, fog);
            Video_Atari_SetViewportFog(7, 4, hidden);
            Video_Atari_BeginViewportProtection(true, 4 + phase % 3, 2, (phase & 1) != 0);
            check(64 + phase, 72 + yp, mode, false, effect);
            /* A second pass changes the same mutable mask addresses. */
            Video_Atari_EndViewportProtection();
            Video_Atari_BeginViewportProtection(true, 5, 3, (phase & 1) == 0);
            image(64 + phase, 49, 49, mode, 0);
            check(64 + phase, 72 + yp, mode, true, effect);
        }
        cropMargins = false;
        for (overlayMode = 0; overlayMode < 4; overlayMode++)
        for (unsigned target = 0; target < 2; target++)
        for (unsigned fogged = 0; fogged < 2; fogged++)
        for (unsigned opaque = 0; opaque < 2; opaque++) {
            uint16 tile[64], tileMask[16], fogPixels[64], fogMask[16];
            reset(1);
            Video_Atari_BeginViewportProtection(true,4,2,target);
            for (unsigned line = 0; line < 16; line++) {
                tileMask[line] = opaque ? 0xffff : 0x937a;
                fogMask[line] = line & 1 ? 0xa39f : 0xfad1;
                for (unsigned p = 0; p < 4; p++) {
                    unsigned index = line*4+p, dst = (72+line)*80+16+p;
                    tile[index] = (line*771+p*933) & tileMask[line];
                    fogPixels[index] = (line*37+p*917) & fogMask[line];
                    uint16 write = (fogged ? tileMask[line] | fogMask[line] : tileMask[line]) &
                                   (uint16)~s_tileCursorPatterns[target][line];
                    uint16 colour = fogged ?
                        (tile[index] & (uint16)~fogMask[line]) | fogPixels[index] : tile[index];
                    expected[dst] = (expected[dst] & (uint16)~write) | (colour & write);
                }
            }
            awaitingSprite = true;
            unsigned beforeMerges = mergeGroups;
            if (fogged)
                Video_Atari_DrawPlanarTileFogged(tile,tileMask,fogPixels,fogMask,64,72,NULL);
            else
                Video_Atari_DrawPlanarTile(tile,tileMask,64,72,opaque ? tile : NULL);
            assert(overlayMode ? mergeGroups > beforeMerges : mergeGroups == beforeMerges);
            composite();
            assert(!memcmp(screen,displayed,sizeof(screen)));
            /* Moving/hiding the tile cursor releases its old footprint. */
            Video_Atari_EndViewportProtection();
            s_viewportBlitter = false;
            for (unsigned line = 0; line < 16; line++) for (unsigned p = 0; p < 4; p++) {
                unsigned dst = (72+line)*80+16+p;
                expected[dst] = (expected[dst] & (uint16)~tileMask[line]) |
                                (tile[line*4+p] & tileMask[line]);
            }
            awaitingSprite = true;
            Video_Atari_DrawPlanarTile(tile,tileMask,64,72,NULL);
            composite();
            assert(!memcmp(screen,displayed,sizeof(screen)));
            s_viewportBlitter = mode != 0;
        }
        assert(blitterLocks == 0);
        overlayMode = 0;
    }
    assert(cachedPlanDraws > 0 && blitterLaunches > 0);
    return 0;
}
"""
        harness = harness.replace("/* CPU */", cpu).replace("/* BLITTER */", model)
        harness = harness.replace("/* PROTECTION */", protection)
        harness = harness.replace("/* PROTECTED PUBLISHER */", tail)
        harness = harness.replace("/* PLACEMENT */", placement).replace("/* LIMITS */", limits)
        harness = harness.replace("/* SPRITE TYPE */", sprite_type)
        harness = harness.replace("/* DAMAGE */", damage)
        harness = harness.replace("/* REPAIR */",
                                  function(gui, "GUI_ViewportSetPlanarImage") + "\n" +
                                  function(gui, "GUI_ViewportPlanarSpriteRepair") + "\n" +
                                  function(gui, "GUI_ViewportPresentPlanarSprite"))
        harness = harness.replace("/* PUBLICATION */", publication)
        run_harness(harness)


if __name__ == "__main__":
    unittest.main()
