"""Exercise periodic recounting and bounded Atari sort skipping."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function


ROOT = Path(__file__).resolve().parents[1]


class UnitRecountTest(unittest.TestCase):
    def test_live_game_loop_iteration(self):
        self.check_live_iteration(viewport=False)

    def test_live_viewport_ground_iteration(self):
        self.check_live_iteration(viewport=True)

    def check_live_iteration(self, viewport):
        if viewport:
            source = (ROOT / "src/gui/viewport.c").read_text()
            loop = function(source, "GUI_Widget_Viewport_Draw")
            start = loop.index("#ifdef TOS", loop.index("/* Draw ground units */"))
            end = loop.index("\n\t\t\tpacked = Unit_PackedTile", start)
            iterator = loop[start:end]
            for declaration in ("uint16 packed;", "uint16 index;", "int spriteFlags;",
                                "GUI_SpriteLayers layers;", "uint8 bodyHouse;"):
                iterator = iterator.replace("\t\t\t" + declaration + "\n", "")
        else:
            source = (ROOT / "src/unit.c").read_text()
            loop = function(source, "GameLoop_Unit")
            start = loop.index("#ifdef TOS\n\tfor (index")
            end = loop.index("\n\t\tif (tickUnknown4", start)
            iterator = loop[start:end].replace("\t\tconst UnitInfo *ui;\n", "")
            iterator = iterator.replace("\t\tui = &g_table_unitInfo[u->o.type];\n", "")
            iterator = iterator.replace("\t\tui = g_unitInfoByType[u->o.type];\n", "")
        iterator += "\n        visit(u);\n    }\n"
        harness = r"""
#include <assert.h>
#include <string.h>
#include "types.h"
#include "src/unit.h"
Unit g_unitArray[UNIT_INDEX_MAX];
Unit *g_unitFindArray[UNIT_INDEX_MAX];
uint16 g_unitFindCount, g_validateStrictIfZero;
static const bool viewport = /* VIEWPORT */;
static unsigned mode, calls, trace[UNIT_INDEX_MAX];
static void remove_at(unsigned index) {
    assert(index < g_unitFindCount);
    g_unitFindCount--;
    memmove(&g_unitFindArray[index], &g_unitFindArray[index + 1],
            (g_unitFindCount - index) * sizeof(g_unitFindArray[0]));
}
static void visit(Unit *u) {
    unsigned id = u - g_unitArray;
    assert(calls < UNIT_INDEX_MAX);
    trace[calls++] = id;
    if (mode == 1 && id == 0) {
        g_unitFindArray[g_unitFindCount++] = &g_unitArray[6];
    } else if (mode == 1 && id == 6) {
        g_unitFindArray[g_unitFindCount++] = &g_unitArray[7];
    } else if (mode == 2 && id == 0) {
        remove_at(0);
    } else if (mode == 3 && id == 2) {
        remove_at(0);
    } else if (mode == 4 && id == 0) {
        remove_at(3);
    } else if (mode == 5 && id == 0) {
        g_unitFindCount = 0;
    } else if (mode == 6 && id == 0) {
        g_unitArray[1].o.flags.s.isNotOnMap = true;
        g_unitArray[2].o.flags.s.isNotOnMap = false;
        g_validateStrictIfZero = !g_validateStrictIfZero;
    } else if (mode == 7 && id == 0) {
        remove_at(0);
        g_unitFindArray[g_unitFindCount++] = &g_unitArray[6];
    } else if (mode == 8 && id == 0) {
        Unit *temp = g_unitFindArray[1];
        g_unitFindArray[1] = g_unitFindArray[2];
        g_unitFindArray[2] = temp;
    }
}
static Unit *original_viewport_next(uint16 *index, bool skipNotOnMap) {
    uint16 i = *index + 1;
    while (i < g_unitFindCount) {
        Unit *u = g_unitFindArray[i];
        if (skipNotOnMap && u->o.flags.s.isNotOnMap) { i++; continue; }
        *index = i;
        return u;
    }
    *index = i;
    return NULL;
}
static void original_loop(void) {
    uint16 index = 0xffff;
    const bool strictIfZero = (g_validateStrictIfZero == 0);
    for (;;) {
        Unit *u = viewport ? original_viewport_next(&index, strictIfZero)
                           : Unit_FindNextAny(&index);
        if (u == NULL) break;
        if (viewport) {
            if (u->o.index < 20 || u->o.index > 101) continue;
        } else if (u->o.flags.s.isNotOnMap) continue;
        visit(u);
    }
}
static void current_loop(void) {
    uint16 /* INDEX */;
    /* ITERATOR */
}
static void reset(unsigned count, unsigned hidden, unsigned validate) {
    memset(g_unitArray, 0, sizeof(g_unitArray));
    memset(g_unitFindArray, 0, sizeof(g_unitFindArray));
    memset(trace, 0, sizeof(trace));
    g_unitFindCount = count;
    g_validateStrictIfZero = validate;
    calls = 0;
    const unsigned unitIndices[8] = {42, 20, 101, 19, 102, 15, 55, 100};
    for (unsigned i = 0; i < 8; i++) {
        g_unitArray[i].o.index = viewport ? unitIndices[i] : i;
        g_unitArray[i].o.flags.s.isNotOnMap = (hidden >> i) & 1;
        if (i < count) g_unitFindArray[i] = &g_unitArray[i];
    }
}
int main(void) {
    for (unsigned count = 0; count <= 6; count++)
    for (unsigned hidden = 0; hidden < 64; hidden++)
    for (unsigned validate = 0; validate < 2; validate++)
    for (mode = 0; mode <= 8; mode++) {
        if (mode != 0 && count != 6) continue;
        reset(count, hidden, validate);
        original_loop();
        unsigned expectedCalls = calls, expectedTrace[UNIT_INDEX_MAX];
        unsigned expectedList[UNIT_INDEX_MAX];
        uint16 expectedCount = g_unitFindCount, expectedValidate = g_validateStrictIfZero;
        Unit expectedUnits[UNIT_INDEX_MAX];
        memcpy(expectedTrace, trace, sizeof(trace));
        memcpy(expectedUnits, g_unitArray, sizeof(g_unitArray));
        for (unsigned i = 0; i < expectedCount; i++)
            expectedList[i] = g_unitFindArray[i]->o.index;
        reset(count, hidden, validate);
        current_loop();
        assert(calls == expectedCalls);
        assert(!memcmp(trace, expectedTrace, sizeof(trace)));
        assert(g_unitFindCount == expectedCount);
        assert(g_validateStrictIfZero == expectedValidate);
        assert(!memcmp(g_unitArray, expectedUnits, sizeof(g_unitArray)));
        for (unsigned i = 0; i < expectedCount; i++)
            assert(g_unitFindArray[i]->o.index == expectedList[i]);
        if (count == 6 && hidden == 0 && mode == 1) {
            unsigned expected = viewport ? 5 : 8;
            assert(calls == expected && trace[expected - 2] == 6 &&
                   trace[expected - 1] == 7);
        }
        if (count == 6 && hidden == 0 && mode == 2) {
            assert(calls == (viewport ? 2 : 5) && trace[0] == 0 && trace[1] == 2);
        }
    }
    return 0;
}
"""
        harness = harness.replace("/* ITERATOR */", iterator).replace(
            "/* VIEWPORT */", "true" if viewport else "false").replace(
            "/* INDEX */", "i" if viewport else "index")
        with tempfile.TemporaryDirectory(prefix="unit-loop-iterator-") as directory:
            source, binary = Path(directory) / "test.c", Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                            "-Werror", "-DTOS", "-I", str(ROOT),
                            "-I", str(ROOT / "include"), *flags, str(source),
                            "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_unit_info_address_table(self):
        source = (ROOT / "src/unit.c").read_text()
        loop = function(source, "GameLoop_Unit")
        start = loop.index("\t/* Cache addresses")
        initialization = loop[start:loop.index("\n\tif (Video_Atari_CursorDirect", start)]
        start = loop.index("#ifdef TOS\n\t\tui = ")
        lookup = loop[start:loop.index("\n\n\t\tif (u->o.flags.s.isNotOnMap)", start)]
        table = next(line for line in source.splitlines()
                     if line.startswith("const UnitInfo *g_unitInfoByType["))
        harness = r"""
#include <assert.h>
#include <stddef.h>
#include "types.h"
#include "src/unit.h"
UnitInfo g_table_unitInfo[UNIT_MAX];
/* TABLE */
static void initialize(void) {
    uint16 index;
    /* INITIALIZATION */
}
static const UnitInfo *info(Unit *u) {
    const UnitInfo *ui;
    /* LOOKUP */
    return ui;
}
int main(void) {
    Unit u = {0};
    initialize();
    for (unsigned pass = 0; pass < 2; pass++) {
        for (unsigned type = 0; type < UNIT_MAX; type++) {
            u.o.type = type;
            const UnitInfo *ui = info(&u);
            assert(ui == &g_table_unitInfo[type]);
            g_table_unitInfo[type].movementType = type + pass;
            g_table_unitInfo[type].animationSpeed = type + 10 + pass;
            g_table_unitInfo[type].o.flags.hasTurret = (type + pass) & 1;
            assert(ui->movementType == type + pass);
            assert(ui->animationSpeed == type + 10 + pass);
            assert(ui->o.flags.hasTurret == ((type + pass) & 1));
        }
        initialize();
    }
    return 0;
}
"""
        harness = harness.replace("/* TABLE */", table).replace(
            "/* INITIALIZATION */", initialization).replace("/* LOOKUP */", lookup)
        with tempfile.TemporaryDirectory(prefix="unit-info-addresses-") as directory:
            source, binary = Path(directory) / "test.c", Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                            "-Werror", "-DTOS", "-I", str(ROOT),
                            "-I", str(ROOT / "include"), *flags, str(source),
                            "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_sorting_and_recount_cadence(self):
        production = function((ROOT / "src/unit.c").read_text(), "Unit_Sort")
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int16_t int16;
typedef struct {
    struct {
        uint16 position;
        uint8 type, houseID, seenByHouses;
        struct { struct { bool isNotOnMap; } s; } flags;
    } o;
} Unit;
typedef struct { uint16 unitCountEnemy, unitCountAllied; } House;
enum { MOVEMENT_FOOT, MOVEMENT_TRACKED };
static const struct { uint16 movementType; } g_table_unitInfo[] = {
    {MOVEMENT_TRACKED}, {MOVEMENT_FOOT}
};
static Unit units[4];
static Unit *g_unitFindArray[4];
static uint16 g_unitFindCount;
static uint8 g_playerHouseID;
static House house, otherHouse;
static House *g_playerHouse = &house;
static unsigned allianceChecks;
static uint16 Tile_GetY(uint16 position) { return position; }
static bool House_AreAllied(uint8 first, uint8 second) {
    allianceChecks++;
    return first == second;
}
/* PRODUCTION */
static void scramble(void) {
    for (unsigned i = 0; i < 4; i++) {
        g_unitFindArray[i] = &units[i];
        units[i].o.position = (4 - i) * 0x100;
    }
}
int main(void) {
    g_unitFindCount = 4;
    units[0].o.seenByHouses = 1;
    units[1].o.seenByHouses = 1;
    units[1].o.houseID = 1;
    units[2].o.seenByHouses = 2;
    units[3].o.seenByHouses = 1;
    units[3].o.flags.s.isNotOnMap = true;
    for (unsigned call = 1; call <= 41; call++) {
        bool recount = (call - 1) % 10 == 0;
        unsigned before = allianceChecks;
        House *h = g_playerHouse;
        uint16 allies = h->unitCountAllied, enemies = h->unitCountEnemy;
        scramble();
        Unit_Sort();
        /* Still exactly one bubble pass, even when recounting is skipped. */
        assert(g_unitFindArray[0] == &units[1]);
        assert(g_unitFindArray[1] == &units[2]);
        assert(g_unitFindArray[2] == &units[3]);
        assert(g_unitFindArray[3] == &units[0]);
        if (recount) {
            assert(allianceChecks == before + (g_playerHouseID == 0 ? 2 : 1));
            assert(h->unitCountAllied == (g_playerHouseID == 0 ? 1 : 0));
            assert(h->unitCountEnemy == 1);
        } else {
            assert(allianceChecks == before);
            assert(h->unitCountAllied == allies);
            assert(h->unitCountEnemy == enemies);
        }
        /* Model incremental updates: skipped recounts must not clear them. */
        h->unitCountAllied += 2;
        h->unitCountEnemy += 3;
        if (call == 15) {
            g_playerHouse = &otherHouse;
            g_playerHouseID = 1;
        }
    }
    assert(allianceChecks == 7);
    /* Empty and single-unit lists also preserve the countdown cadence. */
    g_unitFindCount = 0;
    for (unsigned i = 0; i < 10; i++) Unit_Sort();
    assert(otherHouse.unitCountAllied == 0);
    assert(otherHouse.unitCountEnemy == 0);
    assert(allianceChecks == 7);
    g_unitFindCount = 1;
    g_unitFindArray[0] = &units[2];
    for (unsigned i = 0; i < 10; i++) Unit_Sort();
    assert(otherHouse.unitCountAllied == 0);
    assert(otherHouse.unitCountEnemy == 1);
    assert(allianceChecks == 8);
    /* Infantry retain their one-tile sorting bias between recounts. */
    g_unitFindCount = 2;
    g_unitFindArray[0] = &units[0];
    g_unitFindArray[1] = &units[1];
    units[0].o.position = 0x200;
    units[1].o.position = 0x280;
    units[1].o.type = 1;
    Unit_Sort();
    assert(g_unitFindArray[0] == &units[1]);
    assert(g_unitFindArray[1] == &units[0]);
    return 0;
}
"""
        harness = harness.replace("/* PRODUCTION */", production)
        with tempfile.TemporaryDirectory(prefix="unit-recount-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                            "-Werror", *flags, str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_atari_skip_rearm_and_executed_recount(self):
        production = function((ROOT / "src/unit.c").read_text(), "Unit_Sort")
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int16_t int16;
typedef struct {
    struct {
        uint16 position;
        uint8 type, houseID, seenByHouses;
        struct { struct { bool isNotOnMap; } s; } flags;
    } o;
} Unit;
typedef struct { uint16 unitCountEnemy, unitCountAllied; } House;
enum { MOVEMENT_FOOT, MOVEMENT_TRACKED, UNIT_MAX = 2 };
static const struct { uint16 movementType; } g_table_unitInfo[UNIT_MAX] = {
    {MOVEMENT_TRACKED}, {MOVEMENT_FOOT}
};
static Unit units[4];
static Unit *g_unitFindArray[4];
static uint16 g_unitFindCount = 4;
static uint8 g_playerHouseID;
static House house;
static House *g_playerHouse = &house;
static unsigned yReads, allianceChecks, executedPasses;
static uint16 Tile_GetY(uint16 position) {
    yReads++;
    return position;
}
static bool House_AreAllied(uint8 first, uint8 second) {
    allianceChecks++;
    return first == second;
}
/* PRODUCTION */
static void run(bool execute) {
    unsigned readsBefore = yReads, checksBefore = allianceChecks;
    uint16 alliesBefore = house.unitCountAllied, enemiesBefore = house.unitCountEnemy;
    Unit_Sort();
    assert(yReads == readsBefore + (execute ? g_unitFindCount : 0));
    if (execute) executedPasses++;
    if (execute && (executedPasses - 1) % 10 == 0) {
        unsigned allies = 0, enemies = 0;
        for (unsigned i = 0; i < g_unitFindCount; i++) {
            Unit *u = g_unitFindArray[i];
            if (!(u->o.seenByHouses & (1 << g_playerHouseID)) ||
                u->o.flags.s.isNotOnMap) continue;
            if (u->o.houseID == g_playerHouseID) allies++;
            else enemies++;
        }
        assert(allianceChecks == checksBefore + allies + enemies);
        assert(house.unitCountAllied == allies && house.unitCountEnemy == enemies);
    } else {
        assert(allianceChecks == checksBefore);
        assert(house.unitCountAllied == alliesBefore && house.unitCountEnemy == enemiesBefore);
    }
}
static void order(unsigned a, unsigned b, unsigned c, unsigned d) {
    assert(g_unitFindArray[0] == &units[a] && g_unitFindArray[1] == &units[b] &&
           g_unitFindArray[2] == &units[c] && g_unitFindArray[3] == &units[d]);
}
int main(void) {
    for (unsigned i = 0; i < 4; i++) {
        g_unitFindArray[i] = &units[i];
        units[i].o.position = (4 - i) * 0x100;
        units[i].o.seenByHouses = 1;
    }
    /* Swapping passes run consecutively; each remains a single bubble pass. */
    run(true); order(1, 2, 3, 0);
    run(true); order(2, 3, 1, 0);
    run(true); order(3, 2, 1, 0);
    run(true); order(3, 2, 1, 0);
    /* New movement waits at most one skipped call, then bubbles upward. */
    units[0].o.position = 0x50;
    run(false); order(3, 2, 1, 0);
    run(true); order(3, 2, 0, 1);
    run(true); order(3, 0, 2, 1);
    run(true); order(0, 3, 2, 1);
    run(true); order(0, 3, 2, 1);
    assert(executedPasses == 8);
    units[0].o.seenByHouses = 0;
    units[1].o.flags.s.isNotOnMap = true;
    units[2].o.houseID = 1;
    /* Skips leave the countdown untouched: recount only on executed pass 11. */
    run(false);
    for (unsigned i = 0; i < 10; i++) run(i % 2 == 0);
    assert(executedPasses == 13 && house.unitCountAllied == 1 &&
           house.unitCountEnemy == 1);
    /* Empty and singleton runs still re-arm, rather than latching sorting off. */
    g_unitFindCount = 0;
    run(true);
    run(false);
    g_unitFindCount = 1;
    g_unitFindArray[0] = &units[0];
    run(true);
    g_unitFindCount = 2;
    g_unitFindArray[1] = &units[1];
    units[0].o.position = 0x200;
    units[1].o.position = 0x280;
    units[1].o.type = 1;
    run(false);
    assert(g_unitFindArray[0] == &units[0]);
    run(true);
    assert(g_unitFindArray[0] == &units[1] && g_unitFindArray[1] == &units[0]);
    return 0;
}
"""
        harness = harness.replace("/* PRODUCTION */", production)
        with tempfile.TemporaryDirectory(prefix="unit-sort-skip-") as directory:
            source = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            flags = shlex.split(os.environ.get("TEST_CFLAGS", ""))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                            "-Werror", "-DTOS", *flags, str(source), "-o", str(binary)],
                           check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
