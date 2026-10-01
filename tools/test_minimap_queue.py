"""Exercise the production minimap queue producer and batch consumer."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MinimapQueueTest(unittest.TestCase):
    def test_queue_lifecycle(self):
        source = (ROOT / "src/map.c").read_text()
        start = source.index("void Map_MarkTileDirty(")
        end = source.index("\n}", start) + 2
        producer = source[start:end]
        source = (ROOT / "src/gui/viewport.c").read_text()
        start = source.index("\tif (g_changedTilesCount != 0")
        end = source.index("\n\tif ((g_viewportMessageCounter", start)
        consumer = source[start:end]
        start = source.index("static bool GUI_Widget_Viewport_MinimapUpdateDue(")
        cadence = source[start:source.index("\n}", start) + 2]
        interval = re.search(r"^#define MINIMAP_UPDATE_INTERVAL .*$", source, re.M)[0]
        bit_macros = "\n".join(re.findall(
            r"^#define BitArray_(?:Test|Set|Clear)\(.*$",
            (ROOT / "src/tools.h").read_text(), re.M))
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
typedef int Screen;
#define SCREEN_0 0
#define SCREEN_1 1
#define SCREEN_ACTIVE 2
#define lengthof(a) (sizeof(a) / sizeof((a)[0]))
#define Tile_GetPackedY(p) ((p) >> 6)
static struct { uint16 mapScale; } g_scenario;
static struct { uint16 minY; } g_mapInfos[3] = {{1}, {16}, {21}};
static uint8 g_displayedMinimap[512], g_changedTilesMap[512];
static uint16 g_changedTiles[200], g_changedTilesCount, g_minimapPosition;
static unsigned draws[4096], outlineUpdates, copies, copyHeight;
static bool unchanged;
static uint8 colours[4096], painted[4096];
#ifdef TOS
static uint32 g_timerGUI, s_minimapLastUpdate;
static bool s_minimapUpdateStarted, direct;
static bool Video_Atari_CursorDirect(void) { return direct; }
/* CADENCE */
#endif
static Screen GFX_Screen_SetActive(Screen s) { return s; }
static void GUI_Mouse_Hide_InWidget(unsigned w) { (void)w; }
static void GUI_Mouse_Show_InWidget(void) {}
static void Map_UpdateMinimapPosition(uint16 p, bool force) {
    (void)p; assert(force); outlineUpdates++;
}
static void GUI_Screen_Copy(int a,int b,int c,int d,int e,int f,int g,int h) {
    (void)a; (void)b; (void)c; (void)d;
    (void)e; (void)g; (void)h;
    copies++; copyHeight = f;
}
/* BIT_MACROS */
static bool GUI_Widget_Viewport_DrawTile(uint16 p) {
    assert(p < 4096);
    draws[p]++;
    if (unchanged) return false;
    if (BitArray_Test(g_displayedMinimap, p)) return false;
    painted[p] = colours[p];
    return true;
}
/* PRODUCER */
static void consumeNow(void) {
    uint16 i, curPos, y;
    bool hasScrolled = false;
    /* CONSUMER */
}
static void consume(void) {
#ifdef TOS
    g_timerGUI += 30;
#endif
    consumeNow();
}
static void reset(void) {
    memset(g_displayedMinimap, 0, sizeof(g_displayedMinimap));
    memset(g_changedTilesMap, 0, sizeof(g_changedTilesMap));
    memset(draws, 0, sizeof(draws));
    memset(painted, 0, sizeof(painted));
    g_changedTilesCount = 0;
    outlineUpdates = 0;
    copies = copyHeight = 0;
    unchanged = false;
    g_scenario.mapScale = 0;
#ifdef TOS
    g_timerGUI = s_minimapLastUpdate = 0;
    s_minimapUpdateStarted = false;
    direct = true;
#endif
}
int main(void) {
    unsigned p, n, batches;
    reset();
    for (n = 0; n < 100; n++) {
        colours[65] = n;
        Map_MarkTileDirty(65);
    }
    assert(g_changedTilesCount == 1);
    consume();
    assert(draws[65] == 1 && painted[65] == 99);
    assert(copies == 1 && copyHeight == 1);
    assert(!BitArray_Test(g_changedTilesMap, 65));
    Map_MarkTileDirty(65);
    assert(g_changedTilesCount == 1);
    consume();
    assert(draws[65] == 2);

    reset();
    for (p = 0; p < 200; p++) Map_MarkTileDirty(p);
    assert(g_changedTilesCount == 200);
    consume();
    assert(g_changedTilesCount == 0);
    for (p = 0; p < 200; p++) assert(draws[p] == 1);

    reset();
    for (p = 0; p <= 200; p++) Map_MarkTileDirty(p);
    for (n = 0; n < 100; n++) Map_MarkTileDirty(200);
    assert(g_changedTilesCount == 200);
    consume();
#ifdef TOS
    assert(g_changedTilesCount == 0 && draws[200] == 1);
#else
    assert(g_changedTilesCount == 1 && g_changedTiles[0] == 200);
    assert(BitArray_Test(g_changedTilesMap, 200));
#endif
    Map_MarkTileDirty(0);
    Map_MarkTileDirty(200);
    assert(g_changedTilesCount == 2);
    consume();
    assert(draws[0] == 2);
#ifdef TOS
    assert(draws[200] == 2);
#else
    assert(draws[200] == 1);
#endif
    assert(g_changedTilesCount == 0);

    reset();
    for (n = 0; n < 3; n++) {
        for (p = 0; p < 4096; p++) {
            colours[p] = p + n;
            Map_MarkTileDirty(p);
        }
        assert(g_changedTilesCount == 200);
    }
    for (batches = 0; g_changedTilesCount != 0; batches++) {
        assert(batches < 21);
        consume();
    }
#ifdef TOS
    assert(batches == 1);
#else
    assert(batches == 21);
#endif
    for (p = 0; p < 4096; p++) {
        assert(draws[p] == 1 && painted[p] == (uint8)(p + 2));
        assert(!BitArray_Test(g_changedTilesMap, p));
    }

    reset();
    BitArray_Set(g_displayedMinimap, 65);
    for (n = 0; n < 100; n++) Map_MarkTileDirty(65);
    consume();
    assert(draws[65] == 1 && outlineUpdates == 1);
    reset();
    unchanged = true;
    Map_MarkTileDirty(65);
    consume();
    assert(g_changedTilesCount == 0);
    assert(!BitArray_Test(g_changedTilesMap, 65));
    assert(copies == 0);
    reset();
    g_scenario.mapScale = 2;
    Map_MarkTileDirty(21 * 64 + 21);
    consume();
    assert(copies == 1 && copyHeight == 3);
#ifdef TOS
    reset();
    consumeNow();
    assert(!s_minimapUpdateStarted);
    g_timerGUI = 100;
    Map_MarkTileDirty(65);
    consumeNow();
    assert(draws[65] == 1);
    for (n = 101; n < 130; n++) {
        g_timerGUI = n;
        colours[65] = n;
        Map_MarkTileDirty(65);
        consumeNow();
        assert(draws[65] == 1 && g_changedTilesCount == 1);
        assert(BitArray_Test(g_changedTilesMap, 65));
    }
    g_timerGUI = 130;
    consumeNow();
    assert(draws[65] == 2 && painted[65] == 129);
    assert(g_changedTilesCount == 0);
    Map_MarkTileDirty(65);
    consumeNow();
    assert(draws[65] == 2);
    g_timerGUI = 1000;
    consumeNow();
    assert(draws[65] == 3);
    Map_MarkTileDirty(65);
    consumeNow();
    assert(draws[65] == 3); /* No catch-up burst after a long stall. */

    reset();
    for (n = 0; n < 120; n++) {
        g_timerGUI = n;
        Map_MarkTileDirty(65);
        consumeNow();
    }
    assert(draws[65] == 4); /* Exactly two batches per 60 GUI ticks. */
    assert(g_changedTilesCount == 1);

    reset();
    g_timerGUI = 100;
    Map_MarkTileDirty(65);
    consumeNow();
    for (p = 0; p < 4096; p++) Map_MarkTileDirty(p);
    g_timerGUI = 129;
    consumeNow();
    assert(g_changedTilesCount == 200 && draws[65] == 1);
    for (p = 0; p < 4096; p++) assert(BitArray_Test(g_changedTilesMap, p));
    g_timerGUI = 130;
    consumeNow();
    assert(g_changedTilesCount == 0);
    for (p = 0; p < 4096; p++) {
        assert(draws[p] == (p == 65 ? 2 : 1));
        assert(!BitArray_Test(g_changedTilesMap, p));
    }

    reset();
    g_timerGUI = UINT32_MAX - 10;
    Map_MarkTileDirty(65);
    consumeNow();
    Map_MarkTileDirty(65);
    g_timerGUI = 18;
    consumeNow();
    assert(draws[65] == 1);
    g_timerGUI = 19;
    consumeNow();
    assert(draws[65] == 2);

    reset();
    direct = false;
    for (n = 0; n < 10; n++) {
        Map_MarkTileDirty(65);
        consumeNow();
    }
    assert(draws[65] == 10); /* Other Atari machines are not throttled. */
#endif
    return 0;
}
"""
        harness = harness.replace("/* BIT_MACROS */", bit_macros)
        harness = harness.replace("/* PRODUCER */", producer)
        harness = harness.replace("/* CONSUMER */", consumer)
        harness = harness.replace("/* CADENCE */", interval + "\n" + cadence)
        with tempfile.TemporaryDirectory(prefix="minimap-queue-") as directory:
            test = Path(directory) / "test.c"
            test.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            for tos in (False, True):
                with self.subTest(tos=tos):
                    binary = Path(directory) / ("atari" if tos else "generic")
                    subprocess.run([*compiler, "-std=c99", "-Wall", "-Wextra", "-Werror",
                                    *(["-DTOS"] if tos else []),
                                    str(test), "-o", str(binary)], check=True)
                    subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
