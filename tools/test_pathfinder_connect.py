"""Check 40-step paired detours against an independent first-arrival reference."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_script_budget import function


ROOT = Path(__file__).resolve().parents[1]

REFERENCE_CONNECT = r"""
static unsigned referenceSteps;
static bool reference_connect(uint16 dst, Pathfinder_Data *data, int8 side, uint8 start) {
    uint16 current = data->packed, steps = 0;
    uint8 *buffer = data->buffer;
    while (steps < 40) {
        uint8 direction = start;
        uint16 next;
        for (;;) {
            direction = (direction + side) & 7;
            if ((direction & 1) && current + s_mapDirection[(direction + side) & 7] == dst) {
                direction = (direction + side) & 7;
                next = current + s_mapDirection[direction];
                break;
            }
            if (direction == start) return false;
            next = current + s_mapDirection[direction];
            if (Script_Unit_Pathfind_GetScore(next, direction) <= 255) break;
        }
        *buffer++ = direction;
        steps++;
        if (next == dst) {
            *buffer = 255;
            referenceSteps = steps;
            data->routeSize = steps;
            Script_Unit_Pathfinder_Smoothen(data);
            data->routeSize--;
            return true;
        }
        if (next == data->packed) return false;
        start = (direction - side * 3) & 7;
        current = next;
    }
    return false;
}
static unsigned outcomes[4], ties, counterclockwiseWins, clockwiseWins, nonCheapestWins;
static bool reference_pair(uint16 dst, Pathfinder_Data *data, uint8 start) {
    uint8 buffers[2][42];
    Pathfinder_Data routes[2] = {
        {data->packed, 0, 0, buffers[0]}, {data->packed, 0, 0, buffers[1]}
    };
    bool left = reference_connect(dst, &routes[0], -1, start);
    unsigned leftSteps = referenceSteps;
    bool right = reference_connect(dst, &routes[1], 1, start);
    unsigned rightSteps = referenceSteps;
    outcomes[left + 2 * right]++;
    if (!left && !right) return false;
    unsigned selected = !right || (left && leftSteps < rightSteps) ? 0 : 1;
    ties += left && right && leftSteps == rightSteps;
    counterclockwiseWins += selected == 0;
    clockwiseWins += selected == 1;
    nonCheapestWins += left && right && routes[selected].score > routes[1 - selected].score;
    data->score = routes[selected].score;
    data->routeSize = routes[selected].routeSize;
    memcpy(data->buffer, routes[selected].buffer, data->routeSize + 1);
    return true;
}
"""

REFERENCE_OBSTACLE = r"""
            uint8 dir;
            bool found = false;
            int16 routeSize;
            uint8 buffer[42];
            Pathfinder_Data route = {packedCur, 0, 0, buffer};
            while (true) {
                if (packedNext == packedDst) break;
                dir = Tile_GetDirectionPacked(packedNext, packedDst) / 32;
                packedNext += s_mapDirection[dir];
                if (Script_Unit_Pathfind_GetScore(packedNext, dir) > 255) continue;
                found = reference_pair(packedNext, &route, direction);
                if (found) break;
                do {
                    if (packedNext == packedDst) break;
                    dir = Tile_GetDirectionPacked(packedNext, packedDst) / 32;
                    packedNext += s_mapDirection[dir];
                } while (Script_Unit_Pathfind_GetScore(packedNext, dir) <= 255);
            }
            if (found) {
                routeSize = min(bufferSize - res.routeSize, route.routeSize);
                if (routeSize <= 0) break;
                memcpy(&res.buffer[res.routeSize], route.buffer, routeSize);
                res.routeSize += routeSize;
                res.score += route.score;
            } else {
                break;
            }
"""


class PathfinderConnectTest(unittest.TestCase):
    def test_first_arrival_and_capacity(self):
        source = (ROOT / "src/script/unit.c").read_text()
        tile = (ROOT / "src/tile.c").read_text()
        production = "\n".join(function(source, name) for name in (
            "Script_Unit_Pathfind_GetScore", "Script_Unit_Pathfinder_Smoothen",
            "Script_Unit_Pathfinder_Connect", "Script_Unit_Pathfinder"))
        pathfinder = function(source, "Script_Unit_Pathfinder")
        first = pathfinder.index("\t\t\tuint8 dir;")
        last = pathfinder.index("\n\t\t}\n\n\t\tpackedCur = packedNext;", first)
        reference = pathfinder[:first] + REFERENCE_OBSTACLE + pathfinder[last:]
        reference = reference.replace("Script_Unit_Pathfinder(", "reference_pathfinder(", 1)
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef int8_t int8;
typedef int16_t int16;
typedef struct { uint16 packed; int16 score; uint16 routeSize; uint8 *buffer; } Pathfinder_Data;
typedef struct { unsigned unused; } Unit;
static Unit unit;
static Unit *g_scriptCurrentUnit = &unit;
static bool g_dune2_enhanced;
static const int16 s_mapDirection[8] = {-64,-63,1,65,64,63,-1,-65};
static int16 costs[4096];
static unsigned probes, traceLength;
static uint16 trace[8];
#define min(a,b) ((a) < (b) ? (a) : (b))
#define Tile_GetPackedX(packed) ((packed) & 63)
#define Tile_GetPackedY(packed) (((packed) >> 6) & 63)
static uint16 pack(unsigned x, unsigned y) { return x + 64 * y; }
static int16 Unit_GetTileEnterScore(Unit *u, uint16 packed, uint16 direction) {
    (void)u;
    probes++;
    if (traceLength < 8) trace[traceLength++] = packed;
    if (packed >= 4096) return 256;
    unsigned x = Tile_GetPackedX(packed), y = Tile_GetPackedY(packed);
    if (!x || x == 63 || !y || y == 63) return 256;
    int16 score = costs[packed];
    if (score < 0 || score == 256) return score;
    return score + ((direction & 1) && score < 250 ? 3 : 0);
}
/* TILE DIRECTION */
/* PRODUCTION */
/* REFERENCE CONNECT */
/* REFERENCE PATHFINDER */
static void reset_costs(int16 cost) {
    for (unsigned i = 0; i < 4096; i++) costs[i] = cost;
}
static void check_pair(uint16 src, uint16 dst, uint8 start) {
    uint8 expectedBuffer[44], actualBuffer[44];
    memset(expectedBuffer, 0xa5, sizeof(expectedBuffer));
    memset(actualBuffer, 0xa5, sizeof(actualBuffer));
    Pathfinder_Data expected = {src, 0, 0, expectedBuffer + 1};
    Pathfinder_Data actual = {src, 0, 0, actualBuffer + 1};
    probes = traceLength = 0;
    bool expectedResult = reference_pair(dst, &expected, start);
    unsigned expectedProbes = probes;
    probes = traceLength = 0;
    bool actualResult = Script_Unit_Pathfinder_Connect(dst, &actual, start);
    assert(actualResult == expectedResult && probes <= expectedProbes);
    assert(actual.packed == expected.packed && actual.score == expected.score);
    assert(actual.routeSize == expected.routeSize);
    assert(actualBuffer[0] == 0xa5 && actualBuffer[43] == 0xa5);
    if (actualResult) {
        assert(actual.routeSize <= 40);
        assert(!memcmp(actual.buffer, expected.buffer, actual.routeSize + 1));
    } else {
        assert(!memcmp(actualBuffer, expectedBuffer, sizeof(actualBuffer)));
    }
}
static void check_path(uint16 src, uint16 dst, int16 capacity) {
    uint8 expectedBuffer[44], actualBuffer[44];
    memset(expectedBuffer, 0xa5, sizeof(expectedBuffer));
    memset(actualBuffer, 0xa5, sizeof(actualBuffer));
    probes = traceLength = 0;
    Pathfinder_Data expected = reference_pathfinder(src, dst, expectedBuffer + 1, capacity);
    unsigned expectedProbes = probes;
    probes = traceLength = 0;
    Pathfinder_Data actual = Script_Unit_Pathfinder(src, dst, actualBuffer + 1, capacity);
    assert(probes <= expectedProbes);
    assert(actual.packed == expected.packed && actual.score == expected.score);
    assert(actual.routeSize == expected.routeSize);
    assert(!memcmp(actualBuffer, expectedBuffer, sizeof(actualBuffer)));
}
static uint32_t randomState = 0x12345678;
static uint32_t random_value(void) {
    randomState = randomState * 1664525u + 1013904223u;
    return randomState;
}
int main(void) {
    const uint16 src = 32 + 32 * 64;
    for (unsigned mode = 0; mode < 2; mode++) {
        g_dune2_enhanced = mode;
        reset_costs(1);
        costs[src - 64] = 256;
        check_pair(src, src - 128, 0);
        uint8 result[42];
        Pathfinder_Data route = {src, 0, 0, result};
        probes = traceLength = 0;
        assert(Script_Unit_Pathfinder_Connect(src - 128, &route, 0));
        assert(route.routeSize == 2 && result[0] == 1 && result[1] == 7);
        assert(trace[0] == src - 63 && trace[1] == src - 65);
        costs[src - 63] = 200;
        check_pair(src, src - 128, 0);
        assert(Script_Unit_Pathfinder_Connect(src - 128, &route, 0));
        assert(result[0] == 1 && result[1] == 7);
        costs[src - 63] = 1;
        costs[src - 65] = 200;
        check_pair(src, src - 128, 0);
        reset_costs(256);
        costs[src] = 1;
        for (unsigned start = 0; start < 8; start++) {
            check_pair(src, src - 128, start);
            check_pair(src, src, start);
        }
        check_path(src, src, 40);
        check_path(src, src - 128, 40);

        /* Both walks hit the 40-step limit in a trapped 52-tile corridor. */
        reset_costs(256);
        for (unsigned x = 5; x <= 56; x++) costs[pack(x, 30)] = 1;
        costs[pack(5, 20)] = 1;
        check_pair(pack(5, 30), pack(5, 20), 0);
        check_path(pack(5, 30), pack(5, 20), 40);
        /* Success on step 40 is allowed; a goal requiring 41 steps is rejected. */
        reset_costs(256);
        for (unsigned x = 2; x <= 43; x++) costs[pack(x, 30)] = 1;
        check_pair(pack(2, 30), pack(42, 30), 0);
        route = (Pathfinder_Data){pack(2, 30), 0, 0, result};
        assert(Script_Unit_Pathfinder_Connect(pack(42, 30), &route, 0));
        assert(referenceSteps == 40);
        check_pair(pack(2, 30), pack(43, 30), 0);
        route = (Pathfinder_Data){pack(2, 30), 0, 0, result};
        assert(!Script_Unit_Pathfinder_Connect(pack(43, 30), &route, 0));
        check_path(pack(2, 30), pack(42, 30), 40);
        reset_costs(1);
        costs[src - 64] = 256;
        for (unsigned capacity = 1; capacity <= 40; capacity++)
            check_path(src, src - 128, capacity);

        for (unsigned sample = 0; sample < 5000; sample++) {
            if (sample % 20 == 0) {
                reset_costs(256);
                for (unsigned y = 24; y <= 40; y++)
                    for (unsigned x = 24; x <= 40; x++) {
                        uint32_t value = random_value();
                        costs[pack(x, y)] = value % 5 == 0 ? 256 :
                            value % 31 == 0 ? -1 : value % 37 == 0 ? -2 :
                            1 + (int)((value >> 16) % 250);
                    }
                costs[src] = 1;
            }
            uint16 dst = pack(24 + ((random_value() >> 16) % 17),
                              24 + ((random_value() >> 16) % 17));
            uint8 start = (random_value() >> 16) & 7;
            check_pair(src, dst, start);
            if (sample % 10 == 0) {
                check_path(src, dst, 1 + ((random_value() >> 16) % 40));
                check_path(src, dst, 40);
            }
        }
        /* Every heading, including diagonal goals and playable-map edges. */
        reset_costs(1);
        for (unsigned start = 0; start < 8; start++) {
            for (unsigned goal = 0; goal < 8; goal++)
                check_pair(src, src + s_mapDirection[goal], start);
            check_pair(pack(1, 1), pack(62, 62), start);
        }
        check_path(pack(1, 1), pack(62, 62), 40);
        check_path(pack(62, 62), pack(1, 1), 40);
    }
    for (unsigned i = 0; i < 4; i++) assert(outcomes[i]);
    assert(ties && counterclockwiseWins && clockwiseWins && nonCheapestWins);
    return 0;
}
"""
        harness = harness.replace("/* TILE DIRECTION */", function(tile, "Tile_GetDirectionPacked"))
        harness = harness.replace("/* PRODUCTION */", production)
        harness = harness.replace("/* REFERENCE CONNECT */", REFERENCE_CONNECT)
        harness = harness.replace("/* REFERENCE PATHFINDER */", reference)
        with tempfile.TemporaryDirectory(prefix="pathfinder-connect-") as directory:
            source_file = Path(directory) / "test.c"
            binary = Path(directory) / "test"
            source_file.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                            "-Werror", str(source_file), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
