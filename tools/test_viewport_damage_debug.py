"""Exercise opt-in damage masks, reversible overlays and input stepping."""

import unittest

from tools.test_unit_smoke_damage import ROOT, run_harness
from tools.test_viewport_sprite_cache import function, inactive_display_list


class ViewportDamageDebugTest(unittest.TestCase):
    def test_shortcut_from_keyboard_scancodes(self):
        inputs = (ROOT / "src/input/input.c").read_text()
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        tables = []
        for name in ("s_translateExtendedMap", "s_translateMap", "s_translateTo", "s_keyTranslate"):
            start = inputs.index("static const uint8 " + name + "[]")
            tables.append(inputs[start:inputs.index("};", start) + 2])
        production = "\n".join(tables) + "\n" + "\n".join(
            function(source, name) for source, name in (
                (viewport, "GUI_Widget_Viewport_DebugInput"),
                (inputs, "Input_Keyboard_Translate"),
                (inputs, "Input_HandleInput"),
                (inputs, "Input_EventHandler"),
            ))
        harness = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#include "src/input/input.h"
#include "src/opendune.h"
#define VIEWPORT_DEBUG_DAMAGE
#define SCREEN_WIDTH 320
#define SCREEN_HEIGHT 200
#define lengthof(array) (sizeof(array) / sizeof((array)[0]))
static uint16 g_inputFlags, g_mouseX, g_mouseY, g_prevButtonState, g_mouseLock;
static uint16 s_historyTail, history[128];
static uint8 g_mouseMode, g_mouseFileID, s_activeInputMap[16];
static uint32 g_timerInput;
GameMode g_gameMode = GM_NORMAL;
static bool s_input_extendedKey;
static volatile bool s_damageDebugEnabled;
static bool s_damageDebugShortcutDown;
static bool Video_Atari_CursorDirect(void) { return true; }
static uint16 Input_History_Add(uint16 value) {
    history[s_historyTail / 2] = value; s_historyTail = (s_historyTail + 2) & 255; return 0;
}
static void GUI_Mouse_Hide(void) {}
static void GUI_Mouse_Show(void) {}
static void File_Write(uint8 file, const void *buffer, uint16 count) {
    (void)file; (void)buffer; (void)count; assert(false);
}
/* PRODUCTION */
int main(void) {
    Input_EventHandler(0x1d); /* Atari/AT Ctrl */
    Input_EventHandler(0x38); /* Alt */
    assert((s_activeInputMap[7] & 0x14) == 0x14);
    Input_EventHandler(0x20); /* D */
    assert(!s_damageDebugEnabled && !s_damageDebugShortcutDown);
    Input_EventHandler(0x43); /* Modified F9 must not toggle either. */
    assert(!s_damageDebugEnabled && !s_damageDebugShortcutDown);
    Input_EventHandler(0xc3);
    Input_EventHandler(0x9d);
    Input_EventHandler(0xb8);
    Input_EventHandler(0xa0);
    uint16 tail = s_historyTail;
    Input_EventHandler(0x43); /* Atari/AT F9 */
    assert(s_damageDebugEnabled && s_damageDebugShortcutDown);
    assert(s_historyTail == tail && (s_activeInputMap[15] & 1));
    Input_EventHandler(0x43); /* repeat */
    assert(s_damageDebugEnabled && s_historyTail == tail);
    Input_EventHandler(0xc3);
    assert(!s_damageDebugShortcutDown && !(s_activeInputMap[15] & 1));
    assert(s_historyTail == tail);
    Input_EventHandler(0x43);
    assert(!s_damageDebugEnabled && s_damageDebugShortcutDown);
    return 0;
}
"""
        run_harness(harness.replace("/* PRODUCTION */", production))

    def test_collection_and_acceptance(self):
        source = (ROOT / "src/gui/viewport.c").read_text()
        production = inactive_display_list() + "\n".join(function(source, name) for name in (
            "GUI_Widget_Viewport_DebugInput",
            "GUI_Widget_Viewport_DebugBegin",
            "GUI_Widget_Viewport_DebugRect",
            "GUI_Widget_Viewport_DebugEnd",
            "GUI_Widget_Viewport_BeginSpriteDamage",
            "GUI_Widget_Viewport_SpriteDamageRect",
            "GUI_Widget_Viewport_ShouldDrawSprite",
            "GUI_Widget_Viewport_RepairTiles"))
        harness = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#define VIEWPORT_DEBUG_DAMAGE
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
#define INPUT_MOUSE_MODE_NORMAL 0
#define GM_NORMAL 1
static volatile bool s_damageDebugEnabled;
static bool s_damageDebugShortcutDown, s_damageDebugCollect;
static uint16 s_damageDebugAccepted[10], s_viewportSpriteDamage[10];
static bool s_viewportSpriteFilterActive, s_viewportSpriteNeedsRedraw;
static uint16 g_viewportTerrainDamage[10];
static uint32 g_viewportCandidateDamage[13];
typedef struct Tile { uint16 groundTileID, overlayTileID, houseID; } Tile;
static Tile g_map[4096];
static uint16 g_viewportPosition = 129, g_iconMap[16], g_veiledTileID = 1235;
static bool g_debugScenario, s_viewportRepairActive;
static uint8 s_viewportSelectionTiles[10][15], s_viewportSelectionPen;
#define ICM_ICONGROUP_FOG_OF_WAR 0
static unsigned repairs;
static void recordTile(unsigned col, unsigned row) {
    assert(col < 15 && row < 10);
    assert(s_damageDebugAccepted[row] & (1u << col));
    assert(!(g_viewportTerrainDamage[row] & (1u << col)));
    repairs++;
}
static void GFX_DrawPlanarSelectionTile(unsigned ground, unsigned fog, unsigned x,
    unsigned y, unsigned house, unsigned edges, unsigned pen) {
    (void)ground; (void)fog; (void)house; (void)edges; (void)pen;
    recordTile(x >> 4, (y - 40) >> 4);
}
static void GFX_DrawPlanarViewportFog(unsigned col, unsigned row) { recordTile(col,row); }
static bool GFX_QueueViewportTileFast(unsigned ground, unsigned col, unsigned row, unsigned house) {
    (void)ground; (void)house; recordTile(col,row); return true;
}
static void GFX_DrawPlanarViewportTile(unsigned ground, unsigned fog, unsigned x,
    unsigned y, unsigned house, unsigned packed) {
    (void)ground; (void)fog; (void)house; (void)packed;
    recordTile(x,y);
}
static unsigned g_mouseMode, g_gameMode = GM_NORMAL;
static bool direct = true, cancel;
static bool Video_Atari_CursorDirect(void) { return direct; }
static unsigned phases;
static uint16 phaseRows[2][10];
static void GUI_Widget_Viewport_DebugPhase(const uint16 rows[10], bool accepted) {
    assert(accepted == (phases != 0));
    memcpy(phaseRows[phases++], rows, 20);
    if (cancel) s_damageDebugEnabled = false;
}
/* PRODUCTION */
static void reset(void) {
    phases = 0;
    memset(g_viewportCandidateDamage, 0, sizeof(g_viewportCandidateDamage));
    memset(g_viewportTerrainDamage, 0, sizeof(g_viewportTerrainDamage));
}
int main(void) {
    assert(!GUI_Widget_Viewport_DebugInput(0x21));
    assert(!GUI_Widget_Viewport_DebugInput(0x77));
    assert(!GUI_Widget_Viewport_DebugInput(0x178));
    assert(!GUI_Widget_Viewport_DebugInput(0x678));
    assert(GUI_Widget_Viewport_DebugInput(0x78));
    assert(s_damageDebugEnabled);
    assert(GUI_Widget_Viewport_DebugInput(0x78)); /* repeat */
    assert(s_damageDebugEnabled);
    assert(GUI_Widget_Viewport_DebugInput(0x878));
    assert(!s_damageDebugShortcutDown);
    reset();
    g_viewportCandidateDamage[0] = 0x3ffff; /* offscreen top */
    g_viewportCandidateDamage[1] = 0x20003; /* visible col 0, offscreen borders */
    g_viewportCandidateDamage[10] = 1u << 15;
    g_viewportCandidateDamage[12] = 0x3ffff;
    GUI_Widget_Viewport_DebugBegin(true);
    assert(phases == 1 && s_damageDebugCollect);
    assert(phaseRows[0][0] == 1 && phaseRows[0][9] == 0x4000);
    for (unsigned r = 1; r < 9; r++) assert(phaseRows[0][r] == 0);
    g_viewportTerrainDamage[0] = 1;
    GUI_Widget_Viewport_BeginSpriteDamage(true);
    s_viewportSpriteNeedsRedraw = false;
    assert(!GUI_Widget_Viewport_ShouldDrawSprite(32,40,48,56));
    assert(s_damageDebugAccepted[0] == 0);
    assert(GUI_Widget_Viewport_ShouldDrawSprite(-8,32,17,57));
    assert(s_damageDebugAccepted[0] == 0 && s_damageDebugAccepted[1] == 0);
    /* The publisher records the actual repair fragment, not the full bounds. */
    GUI_Widget_Viewport_DebugRect(0,40,16,56);
    assert(s_damageDebugAccepted[0] == 1 && s_damageDebugAccepted[1] == 0);
    assert(!GUI_Widget_Viewport_ShouldDrawSprite(16,56,33,72));
    s_viewportSpriteNeedsRedraw = true;
    assert(GUI_Widget_Viewport_ShouldDrawSprite(239,199,260,220));
    assert(s_damageDebugAccepted[9] == 0x4000);
    assert(GUI_Widget_Viewport_ShouldDrawSprite(-20,-20,-1,20) == false);
    assert(GUI_Widget_Viewport_ShouldDrawSprite(240,40,260,60) == false);
    GUI_Widget_Viewport_DebugEnd();
    assert(phases == 2 && !s_damageDebugCollect);
    assert(phaseRows[1][0] == 1 && phaseRows[1][1] == 0);
    assert(phaseRows[1][9] == 0x4000);
    reset();
    GUI_Widget_Viewport_DebugBegin(true);
    GUI_Widget_Viewport_BeginSpriteDamage(false); /* force/scroll */
    assert(GUI_Widget_Viewport_ShouldDrawSprite(0,40,240,200));
    for (unsigned r = 0; r < 10; r++) assert(s_damageDebugAccepted[r] == 0x7fff);
    GUI_Widget_Viewport_DebugEnd();
    reset();
    GUI_Widget_Viewport_DebugBegin(true);
    s_viewportRepairActive = true;
    g_iconMap[15] = 1234;
    s_viewportSelectionTiles[0][0] = 1;
    g_map[g_viewportPosition + 1].overlayTileID = g_veiledTileID;
    g_map[g_viewportPosition + 2].overlayTileID = 5;
    for (unsigned r = 0; r < 10; r++) g_viewportTerrainDamage[r] = 0x7fff;
    GUI_Widget_Viewport_RepairTiles(0,40,17,57);
    assert(repairs == 4 && s_damageDebugAccepted[0] == 3 && s_damageDebugAccepted[1] == 3);
    GUI_Widget_Viewport_RepairTiles(0,40,240,200);
    assert(repairs == 150);
    for (unsigned r = 0; r < 10; r++)
        assert(s_damageDebugAccepted[r] == 0x7fff && !g_viewportTerrainDamage[r]);
    GUI_Widget_Viewport_RepairTiles(0,40,240,200);
    assert(repairs == 150); /* no double repair */
    GUI_Widget_Viewport_DebugEnd();
    reset();
    cancel = true;
    GUI_Widget_Viewport_DebugBegin(true);
    assert(phases == 1 && !s_damageDebugCollect && !s_damageDebugEnabled);
    GUI_Widget_Viewport_DebugEnd();
    assert(phases == 1);
    cancel = false;
    for (unsigned mode = 0; mode < 3; mode++) {
        reset(); s_damageDebugEnabled = true;
        g_mouseMode = mode == 0 ? 1 : 0;
        g_gameMode = mode == 1 ? 0 : GM_NORMAL;
        GUI_Widget_Viewport_DebugBegin(mode != 2);
        GUI_Widget_Viewport_DebugEnd();
        assert(phases == 0 && !s_damageDebugCollect);
    }
    return 0;
}
"""
        run_harness(harness.replace("/* PRODUCTION */", production))

    def test_shortcut_updates_held_state_without_queuing_commands(self):
        source = (ROOT / "src/input/input.c").read_text()
        production = function(source, "Input_HandleInput")
        harness = r"""
#include <assert.h>
#include "types.h"
#include "src/input/input.h"
#include "src/opendune.h"
#define VIEWPORT_DEBUG_DAMAGE
#define SCREEN_WIDTH 320
#define SCREEN_HEIGHT 200
static uint16 g_inputFlags, g_mouseX, g_mouseY, g_prevButtonState, g_mouseLock;
static uint16 s_historyTail, history[128];
static uint8 g_mouseMode, g_mouseFileID, s_activeInputMap[16];
static uint32 g_timerInput;
static bool shortcut, acceptShortcut;
static unsigned writes;
static bool GUI_Widget_Viewport_DebugInput(uint16 input) {
    if ((input & 0xff) != 0x78) return false;
    if ((input & 0x800) != 0) { bool swallowed = shortcut; shortcut = false; return swallowed; }
    if (acceptShortcut && (input & 0x700) == 0) shortcut = true;
    return shortcut;
}
static uint16 Input_History_Add(uint16 value) {
    history[s_historyTail / 2] = value; s_historyTail = (s_historyTail + 2) & 255; return 0;
}
static void GUI_Mouse_Hide(void) {}
static void GUI_Mouse_Show(void) {}
static void File_Write(uint8 file, const void *buffer, uint16 count) {
    (void)file; (void)buffer; (void)count; writes++;
}
/* PRODUCTION */
int main(void) {
    Input_HandleInput(0x78); /* F9 was held before debugger eligibility. */
    assert(s_activeInputMap[15] & 1);
    uint16 tail = s_historyTail;
    acceptShortcut = true;
    Input_HandleInput(0x78);
    assert(shortcut && s_historyTail == tail && (s_activeInputMap[15] & 1));
    Input_HandleInput(0x78);
    assert(s_historyTail == tail);
    Input_HandleInput(0x878);
    assert(!shortcut && s_historyTail == tail && !(s_activeInputMap[15] & 1));
    acceptShortcut = false;
    Input_HandleInput(0x78);
    assert(s_historyTail != tail && (s_activeInputMap[15] & 1));
    assert(writes == 0);
    return 0;
}
"""
        run_harness(harness.replace("/* PRODUCTION */", production))

    def test_xor_overlays_cpu_and_blitter(self):
        video = (ROOT / "src/video/video_atari.c").read_text()
        start = video.index("typedef struct PlacementTint {")
        end = video.index("static PlacementTint s_placeTint;", start)
        production = inactive_display_list() + video[start:end + len("static PlacementTint s_placeTint;")]
        helper = function(video, "Video_Atari_SetHalftonePattern").replace(
            "(volatile uint16 *)0xFFFF8A00UL", "halftoneRAM")
        production += "\n" + helper
        production += "\n" + "\n".join(function(video, name) for name in (
            "Video_Atari_PlacementTintBlit", "Video_Atari_PlacementTint",
            "Video_Atari_DebugDamageTint", "Video_Atari_DebugDamageBegin",
            "Video_Atari_DebugDamageEnd"))
        harness = r"""
#include <assert.h>
#include <string.h>
#include <stdint.h>
#include "types.h"
#define VIEWPORT_DEBUG_DAMAGE
#define ST_PLANAR_LINE_BYTES 160
#define Atari_SupervisorExec(callback) (callback)()
static bool s_curDirect = true, s_viewportBlitter, s_blitterTileSetup;
static bool s_damageDebugOverlay, s_damageDebugAccepted;
static uint16 s_damageDebugRows[10], screen[16000], before[16000];
static const uint16 *s_blitterHalftonePattern;
static uint16 halftoneRAM[16];
static uint16 g_placementValidPlane = 1, g_placementInvalidPlane = 3;
static uint16 mask1, mask2, mask3, xcount, ycount;
static int16 xinc, yinc;
static uint32 destination;
static uint8 ctrl, hop, op, skew;
static unsigned hidden, erases, syncs, launches;
#define BLITTER_CTRL (&ctrl)
#define BLITTER_ENDMASK1 (&mask1)
#define BLITTER_ENDMASK2 (&mask2)
#define BLITTER_ENDMASK3 (&mask3)
#define BLITTER_DST_XINC (&xinc)
#define BLITTER_DST_YINC (&yinc)
#define BLITTER_XCOUNT (&xcount)
#define BLITTER_YCOUNT (&ycount)
#define BLITTER_HOP (&hop)
#define BLITTER_OP (&op)
#define BLITTER_SKEW (&skew)
#define BLITTER_DST_ADDR (&destination)
static uint8 *Video_Atari_PlanarBase(void) { return (uint8 *)screen; }
static void GUI_Mouse_Hide(void) { hidden++; }
static void GUI_Mouse_Show(void) { assert(hidden); hidden--; }
static void Video_Atari_CursorEraseFull(void) { assert(hidden); erases++; }
static void Video_Atari_CursorSync(uint8 *base) {
    assert(!s_damageDebugOverlay && base == (uint8 *)screen); syncs++;
}
static void Video_Atari_BlitterStart(void) {
    assert(hop == 1 && skew == 0 && (op == 6 || op == 7));
    assert(mask1 == 0xffff && mask2 == 0xffff && mask3 == 0xffff);
    unsigned index = (destination - (uint32)(uintptr_t)screen) / 2;
    for (unsigned row = 0; row < ycount; row++)
    for (unsigned word = 0; word < xcount; word++) {
        assert(index < 16000);
        if (op == 6) screen[index] ^= halftoneRAM[row & 15];
        else screen[index] |= halftoneRAM[row & 15];
        index += (word + 1 == xcount ? yinc : xinc) / 2;
    }
    launches++;
}
/* PRODUCTION */
static void check(const uint16 rows[10], bool accepted, bool marked) {
    unsigned plane = accepted ? g_placementInvalidPlane : g_placementValidPlane;
    for (unsigned y = 0; y < 200; y++)
    for (unsigned x = 0; x < 20; x++)
    for (unsigned p = 0; p < 4; p++) {
        unsigned i = y * 80 + x * 4 + p;
        uint16 pattern = 0;
        if (marked && y >= 40 && x < 15 && p == plane &&
            (rows[(y-40)/16] & (1u << x)))
            pattern = (y & 1) ? 0x5555 : 0xaaaa;
        assert(screen[i] == (uint16)(before[i] ^ pattern));
    }
}
int main(void) {
    for (unsigned i = 0; i < 16000; i++) screen[i] = i * 139 + 73;
    memcpy(before, screen, sizeof(screen));
    for (unsigned blitter = 0; blitter < 2; blitter++) {
        s_viewportBlitter = blitter != 0;
        for (unsigned accepted = 0; accepted < 2; accepted++)
        for (unsigned tile = 0; tile <= 150; tile++) {
            uint16 rows[10] = {0};
            if (tile < 150) rows[tile / 15] = 1u << (tile % 15);
            else for (unsigned y = 0; y < 10; y++) rows[y] = 0xffff;
            Video_Atari_DebugDamageBegin(rows, accepted != 0);
            assert(s_damageDebugOverlay && hidden == 1);
            check(rows, accepted != 0, true);
            /* End must use the recorded mask, not a mutable caller array. */
            uint16 original[10]; memcpy(original, rows, sizeof(rows));
            memset(rows, 0, sizeof(rows));
            Video_Atari_DebugDamageEnd();
            assert(!s_damageDebugOverlay && hidden == 0);
            check(original, accepted != 0, false);
        }
    }
    assert(erases == syncs && launches != 0);
    /* Normal placement remains OR/idempotent in a diagnostic build. */
    Video_Atari_PlacementTint(0,40,16,16,false);
    uint16 once[16000]; memcpy(once, screen, sizeof(screen));
    Video_Atari_PlacementTint(0,40,16,16,false);
    assert(memcmp(once, screen, sizeof(screen)) == 0 && op == 7);
    return 0;
}
"""
        run_harness(harness.replace("/* PRODUCTION */", production))

    def test_step_input_and_timer_states(self):
        source = (ROOT / "src/gui/viewport.c").read_text()
        production = "\n".join(function(source, name) for name in (
            "GUI_Widget_Viewport_DebugKeyDown", "GUI_Widget_Viewport_DebugWait",
            "GUI_Widget_Viewport_DebugPhase"))
        harness = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#define TIMER_GAME 2
#define TIMER_GUI 1
static volatile bool s_damageDebugEnabled;
static bool keys[128], gameTimer, guiTimer, overlay;
static uint16 queued, phase;
static unsigned tick, readAt, begins, ends, clears;
static bool stopByShortcut;
static uint16 Input_Test(uint16 key) { return keys[key]; }
static void Input_History_Clear(void) { queued = 0; clears++; }
static uint16 Input_IsInputAvailable(void) { return queued != 0; }
static uint16 Input_Wait(void) {
    assert(queued); uint16 value = queued; queued = 0; readAt = tick; return value;
}
static void SleepAndProcessBackgroundTasks(void) {
    assert(overlay && !gameTimer && !guiTimer);
    tick++;
    switch (tick) {
        case 1: queued = 0x41; break; /* held starting click/repeat, not fresh */
        case 2: keys[0x41] = false; queued = 0x841; break;
        case 3: queued = 0x2d; break; /* movement */
        case 4: queued = 0x83d; break; /* release */
        case 5:
            if (stopByShortcut) { s_damageDebugEnabled = false; break; }
            queued = phase ? 0x6e : 0x41;
            keys[queued] = true;
            break;
        case 6: queued = phase ? 0x6e : 0x41; break; /* repeat must be drained */
        case 7: memset(keys, 0, sizeof(keys)); queued = 0x841; break;
        default: assert(0);
    }
}
static bool Timer_SetTimer(unsigned timer, bool enabled) {
    bool *state = timer == TIMER_GAME ? &gameTimer : &guiTimer;
    bool old = *state; *state = enabled; return old;
}
static void Video_Atari_DebugDamageBegin(const uint16 *rows, bool accepted) {
    assert(!gameTimer && !guiTimer && rows[0] == 3);
    assert(accepted == (phase != 0)); overlay = true; begins++;
}
static void Video_Atari_DebugDamageEnd(void) {
    assert(overlay && !gameTimer && !guiTimer);
    overlay = false; ends++;
}
/* PRODUCTION */
int main(void) {
    for (unsigned states = 0; states < 4; states++)
    for (phase = 0; phase < 2; phase++) {
        uint16 rows[10] = {3};
        s_damageDebugEnabled = true;
        gameTimer = (states & 1) != 0; guiTimer = (states & 2) != 0;
        tick = 0; readAt = 0; keys[0x41] = true;
        queued = 0x21; /* queued gameplay input is discarded */
        GUI_Widget_Viewport_DebugPhase(rows, phase != 0);
        assert(tick == 7 && readAt == 5 && queued == 0);
        assert(s_damageDebugEnabled == (phase == 0));
        assert(gameTimer == ((states & 1) != 0));
        assert(guiTimer == ((states & 2) != 0));
    }
    uint16 rows[10] = {3};
    phase = 0; tick = 0; keys[0x41] = true;
    s_damageDebugEnabled = true; stopByShortcut = true;
    GUI_Widget_Viewport_DebugPhase(rows, false);
    assert(!s_damageDebugEnabled && tick == 5 && !overlay);
    assert(begins == ends && clears != 0);
    return 0;
}
"""
        run_harness(harness.replace("/* PRODUCTION */", production))

    def test_hooks_and_pause_publication_gate(self):
        viewport = (ROOT / "src/gui/viewport.c").read_text()
        repair = function(viewport, "GUI_Widget_Viewport_RepairTiles")
        self.assertIn("s_damageDebugAccepted[y] |= column;", repair)
        self.assertLess(repair.index("s_damageDebugAccepted[y] |= column;"),
                        repair.index("g_viewportTerrainDamage[y] &="))
        draw = function(viewport, "GUI_Widget_Viewport_Draw")
        self.assertLess(draw.index("GUI_Widget_Viewport_DebugBegin("),
                        draw.index("GUI_Widget_Viewport_BeginSpriteDamage("))
        self.assertLess(draw.index("GUI_Widget_Viewport_DebugEnd("),
                        draw.index("Map_ClearViewportDamage("))
        video = (ROOT / "src/video/video_atari.c").read_text()
        tick = function(video, "Video_Tick")
        self.assertLess(tick.index("Mouse_EventHandler("),
                        tick.index("if (s_damageDebugOverlay)"))
        gate = tick[tick.index("if (s_damageDebugOverlay)"):]
        self.assertLess(gate.index("return;"), gate.index("if (s_presentMode)"))
        inputs = (ROOT / "src/input/input.c").read_text()
        handler = function(inputs, "Input_HandleInput")
        self.assertLess(handler.index("s_activeInputMap[index] |= bit_value;"),
                        handler.index("if (damageDebugInput)"))
        self.assertIn("s_historyTail = oldTail;", handler[handler.index("if (damageDebugInput)"):])


if __name__ == "__main__":
    unittest.main()
