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
