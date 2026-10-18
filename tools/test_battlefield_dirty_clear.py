"""Check battlefield mask parity and conservative dirty-summary transitions."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BattlefieldDirtyClearTest(unittest.TestCase):
    def test_mask_parity(self):
        source = (ROOT / "src/gfx.c").read_text()
        header = (ROOT / "src/gfx.h").read_text()
        gui = (ROOT / "src/gui/gui.c").read_text()
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        self.assertIn("GUI_SetViewportPlanar(planarViewport);", viewport)
        self.assertIn("GUI_SetViewportPlanar(false);", viewport)
        self.assertNotIn("GFX_Screen_ClearDirtyBattlefield();", viewport)
        functions = []
        for name in ("GFX_Screen_IsNativeViewportRect", "GFX_Screen_ClearDirtyRect"):
            start = header.index(name + "(")
            start = header.rfind("\n", 0, start) + 1
            functions.append(header[start:header.index("\n}", start) + 2])
        for name in ("GFX_Screen_SetDirtySuppress", "GFX_Screen_DirtyIntersectsBattlefield",
                     "GFX_Screen_SetDirtyBlocks",
                     "GFX_Screen_SetDirty_", "GFX_Screen_SetClean",
                     "GFX_Screen_SetDirtyViewport", "GFX_Screen_SetCleanViewport",
                     "GFX_Screen_ClearDirtyRect_", "GFX_Screen_ClearDirtyViewportRect",
                     "GFX_Screen_ClearDirtyBattlefield", "GFX_Screen_SetViewportPlanar"):
            start = source.index(name + "(")
            start = source.rfind("\n", 0, start) + 1
            implementation = source[start:source.index("\n}", start) + 2]
            if name == "GFX_Screen_ClearDirtyRect_":
                implementation = implementation.replace(
                    "\n{", "\n{\n    dirtyClearCalls++;", 1)
            functions.append(implementation)
        start = gui.index("GUI_SetViewportPlanar(")
        start = gui.rfind("\n", 0, start) + 1
        functions.append(gui[start:gui.index("\n}", start) + 2])
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
typedef uint16_t uint16;
typedef uint32_t uint32;
#define SCREEN_HEIGHT 200
#define GFX_STORE_DIRTY_AREA_BLOCKS
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
typedef enum { SCREEN_0, SCREEN_1, SCREEN_ACTIVE } Screen;
struct dirty_area { uint16 left, top, right, bottom; };
static Screen s_screenActiveID = SCREEN_0;
static bool s_dirtySuppress, s_screen0_is_dirty, s_screen1_is_dirty;
static bool s_screen0_battlefield_dirty, s_screen1_battlefield_dirty;
static bool g_screenViewportPlanar, s_viewportPlanar;
static unsigned dirtyClearCalls;
static struct dirty_area s_screen0_dirty_area, s_screen1_dirty_area;
#ifdef GFX_DIRTY_SOURCE_STATS
static int s_dirtySource;
static uint32 s_dirtyCalls[1], s_dirtyPx[1], s_dirtyAlignedPx[1], s_dirtyNewBlocks[1];
#endif
void GFX_Screen_ClearDirtyRect_(uint16 left, uint16 top, uint16 right, uint16 bottom);
typedef struct {
    uint32 before;
    uint32 rows[SCREEN_HEIGHT];
    uint32 after;
} Masks;
static Masks normal, viewport, inputNormal, inputViewport, expectedNormal, expectedViewport;
#define g_dirty_blocks normal.rows
#define g_dirty_blocks_viewport viewport.rows
/* FUNCTIONS */
static void compare(void) {
    s_screen0_battlefield_dirty = s_screen1_battlefield_dirty = true;
    inputNormal = normal;
    inputViewport = viewport;
    GFX_Screen_ClearDirtyRect(0, 40, 240, 200);
    GFX_Screen_ClearDirtyViewportRect(0, 40, 240, 200);
    expectedNormal = normal;
    expectedViewport = viewport;
    normal = inputNormal;
    viewport = inputViewport;
    GFX_Screen_ClearDirtyBattlefield();
    assert(!memcmp(&normal, &expectedNormal, sizeof(normal)));
    assert(!memcmp(&viewport, &expectedViewport, sizeof(viewport)));
    assert(normal.before == 0x12345678 && normal.after == 0x87654321);
    assert(viewport.before == 0x12345678 && viewport.after == 0x87654321);
    assert(!s_screen0_battlefield_dirty && !s_screen1_battlefield_dirty);
}
static void reset(void) {
    GUI_SetViewportPlanar(false);
    GFX_Screen_SetDirtySuppress(false);
    s_screenActiveID = SCREEN_0;
    GFX_Screen_SetClean(SCREEN_0);
    GFX_Screen_SetCleanViewport();
    assert(!s_screen0_battlefield_dirty && !s_screen1_battlefield_dirty);
}
static void native_scope(void) {
    unsigned y, group;
    reset();
    GFX_Screen_SetDirty_(0, 0, 320, 200);
    GFX_Screen_SetDirtyViewport(0, 0, 320, 200);
    inputNormal = normal;
    inputViewport = viewport;
    GUI_SetViewportPlanar(true);
    assert(g_screenViewportPlanar && s_viewportPlanar);
    assert(!s_screen0_battlefield_dirty && !s_screen1_battlefield_dirty);
    for (y = 0; y < SCREEN_HEIGHT; y++) {
        uint32 kept = y < 40 ? UINT32_MAX : UINT32_C(0xffff8000);
        assert(normal.rows[y] == (inputNormal.rows[y] & kept));
        assert(viewport.rows[y] == (inputViewport.rows[y] & kept));
    }
    inputNormal = normal;
    inputViewport = viewport;
    unsigned before = dirtyClearCalls;
    GFX_Screen_SetDirty_(0, 40, 240, 200);
    GFX_Screen_SetDirtyViewport(239, 199, 240, 200);
    GFX_Screen_ClearDirtyRect(0, 40, 240, 200);
    GFX_Screen_ClearDirtyRect(239, 199, 240, 200);
    assert(dirtyClearCalls == before);
    assert(!memcmp(&normal, &inputNormal, sizeof(normal)));
    assert(!memcmp(&viewport, &inputViewport, sizeof(viewport)));
    GFX_Screen_ClearDirtyRect(239, 39, 241, 41);
    GFX_Screen_ClearDirtyRect(240, 40, 320, 200);
    assert(dirtyClearCalls == before + 2);
    GUI_SetViewportPlanar(false);
    GFX_Screen_SetDirty_(0, 40, 16, 41);
    GFX_Screen_SetDirtyViewport(0, 40, 16, 41);
    assert(!g_screenViewportPlanar && !s_viewportPlanar);
    assert(normal.rows[40] & 1);
    assert(viewport.rows[40] & 1);
    assert(s_screen0_battlefield_dirty && s_screen1_battlefield_dirty);
    GFX_Screen_ClearDirtyRect(0, 40, 16, 41);
    assert(dirtyClearCalls == before + 3 && !(normal.rows[40] & 1));
    reset();
    GUI_SetViewportPlanar(true);
    struct dirty_area area0 = s_screen0_dirty_area, area1 = s_screen1_dirty_area;
    GFX_Screen_SetDirty_(16, 56, 32, 72);
    GFX_Screen_SetDirtyViewport(16, 56, 32, 72);
    assert(!s_screen0_is_dirty && !s_screen1_is_dirty);
    assert(!memcmp(&area0, &s_screen0_dirty_area, sizeof(area0)));
    assert(!memcmp(&area1, &s_screen1_dirty_area, sizeof(area1)));
    GFX_Screen_SetDirty_(239, 39, 241, 41);
    GFX_Screen_SetDirtyViewport(239, 39, 241, 41);
    assert(normal.rows[39] == 0xc000 && normal.rows[40] == 0x8000);
    assert(viewport.rows[39] == 0xc000 && viewport.rows[40] == 0x8000);
    assert(!s_screen0_battlefield_dirty && !s_screen1_battlefield_dirty);
    reset();
    GUI_SetViewportPlanar(true);
#ifdef GFX_DIRTY_SOURCE_STATS
    uint32 oldPx = s_dirtyPx[0], oldBlocks = s_dirtyNewBlocks[0];
#endif
    GFX_Screen_SetDirty_(0, 0, 320, 200);
    GFX_Screen_SetDirtyViewport(0, 0, 320, 200);
    for (y = 0; y < SCREEN_HEIGHT; y++) {
        for (group = 0; group < 20; group++) {
            bool outside = y < 40 || group >= 15;
            assert(((normal.rows[y] >> group) & 1) == outside);
            assert(((viewport.rows[y] >> group) & 1) == outside);
        }
    }
#ifdef GFX_DIRTY_SOURCE_STATS
    assert(s_dirtyPx[0] - oldPx == 25600);
    assert(s_dirtyNewBlocks[0] - oldBlocks == 1600);
#endif
    assert(!s_screen0_battlefield_dirty && !s_screen1_battlefield_dirty);
    reset();
    GUI_SetViewportPlanar(true);
    GFX_Screen_SetDirtySuppress(true);
    GFX_Screen_SetDirty_(240, 40, 320, 200);
    GFX_Screen_SetDirtyViewport(256, 136, 320, 200);
    assert(!s_screen0_is_dirty && s_screen1_is_dirty);
    assert(viewport.rows[136] == 0xf0000);
    assert(!normal.rows[136]);
    reset();
}
static void check_summary(void) {
    unsigned y;
    for (y = 40; y < SCREEN_HEIGHT; y++) {
        assert(!(normal.rows[y] & 0x7FFFUL) || s_screen0_battlefield_dirty);
        assert(!(viewport.rows[y] & 0x7FFFUL) || s_screen1_battlefield_dirty);
    }
}
static void transitions(void) {
    static const uint16 cases[][5] = {
        {0, 0, 320, 40, 0}, {240, 40, 320, 200, 0},
        {0, 40, 0, 200, 0}, {0, 40, 240, 40, 0},
        {0, 200, 240, 200, 0}, {239, 39, 241, 41, 1},
        {0, 39, 1, 40, 0}, {0, 40, 1, 41, 1},
        {239, 199, 240, 200, 1}, {240, 199, 241, 200, 0}
    };
    unsigned i;
    for (i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        const uint16 *r = cases[i];
        reset();
        GFX_Screen_SetDirty_(r[0], r[1], r[2], r[3]);
        GFX_Screen_SetDirtyViewport(r[0], r[1], r[2], r[3]);
        assert(s_screen0_battlefield_dirty == (r[4] != 0));
        assert(s_screen1_battlefield_dirty == (r[4] != 0));
        check_summary();
        compare();
    }
    reset();
    GFX_Screen_SetDirtySuppress(true);
    GFX_Screen_SetDirty_(0, 40, 240, 200);
    assert(!s_screen0_battlefield_dirty && !normal.rows[40]);
    GFX_Screen_SetDirtyViewport(0, 40, 240, 200);
    assert(s_screen1_battlefield_dirty);
    GFX_Screen_ClearDirtyBattlefield();
    assert(!s_screen1_battlefield_dirty && !viewport.rows[40]);
    reset();
    GFX_Screen_SetDirty_(0, 40, 240, 200);
    GFX_Screen_SetDirtyViewport(0, 40, 240, 200);
    GFX_Screen_ClearDirtyRect(0, 40, 16, 41);
    GFX_Screen_ClearDirtyViewportRect(0, 40, 16, 41);
    assert(s_screen0_battlefield_dirty && s_screen1_battlefield_dirty);
    check_summary();
    GFX_Screen_ClearDirtyRect(0, 40, 240, 200);
    GFX_Screen_ClearDirtyViewportRect(0, 40, 240, 200);
    assert(s_screen0_battlefield_dirty && s_screen1_battlefield_dirty);
    GFX_Screen_ClearDirtyBattlefield();
    assert(!s_screen0_battlefield_dirty && !s_screen1_battlefield_dirty);
    GFX_Screen_SetDirty_(0, 40, 240, 200);
    GFX_Screen_SetDirtyViewport(0, 40, 240, 200);
    GFX_Screen_SetClean(SCREEN_1);
    assert(s_screen0_battlefield_dirty && s_screen1_battlefield_dirty);
    s_screenActiveID = SCREEN_1;
    GFX_Screen_SetClean(SCREEN_ACTIVE);
    assert(s_screen0_battlefield_dirty);
    s_screenActiveID = SCREEN_0;
    GFX_Screen_SetClean(SCREEN_ACTIVE);
    assert(!s_screen0_battlefield_dirty && s_screen1_battlefield_dirty);
    GFX_Screen_SetCleanViewport();
    assert(!s_screen1_battlefield_dirty);
    /* Seed outside the producers to prove each false flag skips its array. */
    normal.rows[40] = viewport.rows[40] = 1;
    s_screen0_battlefield_dirty = true;
    GFX_Screen_ClearDirtyBattlefield();
    assert(normal.rows[40] == 0 && viewport.rows[40] == 1);
    normal.rows[40] = 1;
    s_screen1_battlefield_dirty = true;
    GFX_Screen_ClearDirtyBattlefield();
    assert(normal.rows[40] == 1 && viewport.rows[40] == 0);
    viewport.rows[40] = 1;
    GFX_Screen_ClearDirtyBattlefield();
    assert(normal.rows[40] == 1 && viewport.rows[40] == 1);
    reset();
}
static uint32 next_random(uint32 *state) {
    *state = *state * UINT32_C(1664525) + UINT32_C(1013904223);
    return *state;
}
static void sequences(void) {
    uint32 random = 0x87654321;
    unsigned step, y;
    reset();
    expectedNormal = normal;
    expectedViewport = viewport;
    for (step = 0; step < 2000; step++) {
        unsigned op = next_random(&random) % 9;
        uint16 left = next_random(&random) % 320;
        uint16 right = left + 1 + next_random(&random) % (320 - left);
        uint16 top = next_random(&random) % 200;
        uint16 bottom = top + 1 + next_random(&random) % (200 - top);
        uint32 mask;
        if (op < 2) {
            Masks *expected = op == 0 ? &expectedNormal : &expectedViewport;
            mask = (UINT32_C(1) << ((right + 15) >> 4)) -
                   (UINT32_C(1) << (left >> 4));
            for (y = top; y < bottom; y++)
                expected->rows[y] |= g_screenViewportPlanar && y >= 40 ?
                                     mask & 0xFFFF8000UL : mask;
            if (op == 0) GFX_Screen_SetDirty_(left, top, right, bottom);
            else GFX_Screen_SetDirtyViewport(left, top, right, bottom);
        } else if (op < 4) {
            Masks *expected = op == 2 ? &expectedNormal : &expectedViewport;
            mask = ((UINT32_C(1) << (right >> 4)) - 1) &
                   ~((UINT32_C(1) << ((left + 15) >> 4)) - 1);
            for (y = top; y < bottom; y++) expected->rows[y] &= ~mask;
            if (op == 2) GFX_Screen_ClearDirtyRect(left, top, right, bottom);
            else GFX_Screen_ClearDirtyViewportRect(left, top, right, bottom);
        } else if (op == 4) {
            for (y = 40; y < SCREEN_HEIGHT; y++) {
                expectedNormal.rows[y] &= 0xFFFF8000UL;
                expectedViewport.rows[y] &= 0xFFFF8000UL;
            }
            GFX_Screen_ClearDirtyBattlefield();
        } else if (op == 5) {
            memset(expectedNormal.rows, 0, sizeof(expectedNormal.rows));
            GFX_Screen_SetClean(SCREEN_0);
        } else if (op == 6) {
            memset(expectedViewport.rows, 0, sizeof(expectedViewport.rows));
            GFX_Screen_SetCleanViewport();
        } else if (op == 7) {
            if (!g_screenViewportPlanar) {
                for (y = 40; y < SCREEN_HEIGHT; y++) {
                    expectedNormal.rows[y] &= 0xFFFF8000UL;
                    expectedViewport.rows[y] &= 0xFFFF8000UL;
                }
                GUI_SetViewportPlanar(true);
            }
        } else {
            GUI_SetViewportPlanar(false);
        }
        assert(!memcmp(&normal, &expectedNormal, sizeof(normal)));
        assert(!memcmp(&viewport, &expectedViewport, sizeof(viewport)));
        check_summary();
    }
}
#ifdef TOS
static void clear_unconditionally(void) {
    unsigned y;
    for (y = 40; y < SCREEN_HEIGHT; y++) {
        normal.rows[y] &= 0xFFFF8000UL;
        viewport.rows[y] &= 0xFFFF8000UL;
    }
}
#endif
int main(void) {
    unsigned bit, y, sample;
    uint32 random = 0x12345678;
    normal.before = viewport.before = 0x12345678;
    normal.after = viewport.after = 0x87654321;
    for (bit = 0; bit < 32; bit++) {
        for (y = 0; y < SCREEN_HEIGHT; y++) {
            normal.rows[y] = UINT32_C(1) << bit;
            viewport.rows[y] = ~(UINT32_C(1) << bit);
        }
        compare();
    }
    for (sample = 0; sample < 1000; sample++) {
        for (y = 0; y < SCREEN_HEIGHT; y++) {
            random = random * UINT32_C(1664525) + UINT32_C(1013904223);
            normal.rows[y] = random;
            random = random * UINT32_C(1664525) + UINT32_C(1013904223);
            viewport.rows[y] = random;
        }
        compare();
    }
    for (y = 0; y < SCREEN_HEIGHT; y++) {
        normal.rows[y] = 0;
        viewport.rows[y] = 0;
    }
    compare();
    transitions();
    native_scope();
    sequences();
    reset();
#ifdef TOS
    {
        void (*volatile clearNormal)(uint16, uint16, uint16, uint16) = GFX_Screen_ClearDirtyRect;
        void (*volatile clearViewport)(uint16, uint16, uint16, uint16) = GFX_Screen_ClearDirtyViewportRect;
        void (*volatile clearBattlefield)(void) = GFX_Screen_ClearDirtyBattlefield;
        void (*volatile clearAlways)(void) = clear_unconditionally;
        clock_t start, oldTicks, alwaysTicks, cleanTicks, oneTicks, bothTicks;
        unsigned i;
        FILE *out = fopen("BENCH.TXT", "w");
        assert(out != NULL);
        start = clock();
        for (i = 0; i < 5000; i++) {
            clearNormal(0, 40, 240, 200);
            clearViewport(0, 40, 240, 200);
        }
        oldTicks = clock() - start;
        start = clock();
        for (i = 0; i < 5000; i++) clearAlways();
        alwaysTicks = clock() - start;
        reset();
        start = clock();
        for (i = 0; i < 5000; i++) clearBattlefield();
        cleanTicks = clock() - start;
        start = clock();
        for (i = 0; i < 5000; i++) {
            s_screen0_battlefield_dirty = true;
            clearBattlefield();
        }
        oneTicks = clock() - start;
        start = clock();
        for (i = 0; i < 5000; i++) {
            s_screen0_battlefield_dirty = s_screen1_battlefield_dirty = true;
            clearBattlefield();
        }
        bothTicks = clock() - start;
        fprintf(out, "5000 battlefield clears: generic=%ld unconditional=%ld clean=%ld one=%ld both=%ld ticks, Hz=%ld\n",
                (long)oldTicks, (long)alwaysTicks, (long)cleanTicks, (long)oneTicks,
                (long)bothTicks, (long)CLOCKS_PER_SEC);
        fclose(out);
        assert(cleanTicks < oneTicks && oneTicks < bothTicks);
        assert(bothTicks < oldTicks);
        assert(bothTicks * 100 <= alwaysTicks * 103);
    }
#endif
    return 0;
}
"""
        harness = harness.replace("/* FUNCTIONS */", "\n\n".join(functions))
        with tempfile.TemporaryDirectory(prefix="battlefield-clear-") as directory:
            test = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            test.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            for flags in ([], ["-DGFX_DIRTY_SOURCE_STATS"]):
                subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                                *flags, str(test), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
