"""Exercise Atari leaf-call and callback-lifetime optimizations."""

from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

from tools.test_viewport_sprite_cache import function

ROOT = Path(__file__).resolve().parents[1]
COMMON = r"""
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "types.h"
#include "tools.h"
#include "tile.h"
#include "unit.h"
#include "structure.h"
#include "pool/unit.h"
#include "pool/structure.h"
#include "script/script.h"
#include "house.h"
#include "opendune.h"
#include "video/video.h"
#include "gfx.h"
"""
INCLUDES = ["-iquote", str(ROOT / "src"), "-I", str(ROOT / "include")]


class AtariCallAbiTest(unittest.TestCase):
    def test_index_validation(self):
        production = function((ROOT / "src/tools.c").read_text(), "Tools_Index_IsValid")
        harness = COMMON + r"""
Unit g_unitArray[UNIT_INDEX_MAX];
Structure g_structureArray[STRUCTURE_INDEX_MAX_HARD];
#ifndef TOS
Unit *Unit_Get_ByIndex(uint16 index) { return &g_unitArray[index]; }
Structure *Structure_Get_ByIndex(uint16 index) { return &g_structureArray[index]; }
#endif
/* PRODUCTION */
int main(void) {
    for (unsigned state = 0; state < 4; state++) {
        for (unsigned i = 0; i < UNIT_INDEX_MAX; i++) {
            g_unitArray[i].o.flags.s.used = (i + state) & 1;
            g_unitArray[i].o.flags.s.allocated = (i + (state >> 1)) & 1;
        }
        for (unsigned i = 0; i < STRUCTURE_INDEX_MAX_HARD; i++)
            g_structureArray[i].o.flags.s.used = (i + state) & 1;
        for (unsigned encoded = 0; encoded <= 0xffff; encoded++) {
            unsigned type = encoded & 0xc000, index = encoded & 0x3fff;
            bool expected = type == 0xc000;
            if (type == 0x4000 && index < UNIT_INDEX_MAX)
                expected = g_unitArray[index].o.flags.s.used &&
                           g_unitArray[index].o.flags.s.allocated;
            if (type == 0x8000 && index < STRUCTURE_INDEX_MAX_HARD)
                expected = g_structureArray[index].o.flags.s.used;
            assert(Tools_Index_IsValid(encoded) == expected);
        }
    }
    return 0;
}
"""
        with tempfile.TemporaryDirectory(prefix="atari-index-") as directory:
            source, binary = Path(directory) / "test.c", Path(directory) / "test"
            source.write_text(harness.replace("/* PRODUCTION */", production))
            for tos in (False, True):
                subprocess.run(["cc", "-std=gnu17", "-O2", "-Wall", "-Wextra",
                                "-Werror", *(["-DTOS"] if tos else []), *INCLUDES,
                                str(source), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)

    def test_native_register_argument_and_live_cursor_mode(self):
        try:
            import unicorn
            from unicorn import m68k_const as registers
        except ImportError:
            self.skipTest("Optional Unicorn instruction execution required")
        tools = ("m68k-atari-mint-gcc", "m68k-atari-mint-nm")
        if any(shutil.which(tool) is None for tool in tools):
            self.skipTest("Atari cross compiler and object tools required")
        production = function((ROOT / "src/tools.c").read_text(), "Tools_Index_IsValid")
        callee = COMMON + """
Unit g_unitArray[UNIT_INDEX_MAX];
Structure g_structureArray[STRUCTURE_INDEX_MAX_HARD];
bool g_videoAtariCursorDirect;
Screen g_screenActiveID;
""" + production
        caller = COMMON + r"""
__attribute__((noinline))
bool read_cursor_mode(void) { return Video_Atari_CursorDirect(); }
__attribute__((noinline))
bool check_index(uint16 encoded) { return Tools_Index_IsValid(encoded); }
__attribute__((noinline))
Screen change_screen(Screen next) { return GFX_Screen_SetActive(next); }
unsigned test_entry(void) {
    g_videoAtariCursorDirect = false;
    if (read_cursor_mode()) return 1;
    g_videoAtariCursorDirect = true;
    if (!read_cursor_mode()) return 2;
    g_videoAtariCursorDirect = false;
    if (read_cursor_mode()) return 3;
    g_unitArray[0].o.flags.s.used = true;
    g_unitArray[0].o.flags.s.allocated = true;
    g_unitArray[UNIT_INDEX_MAX - 1].o.flags.s.used = true;
    g_unitArray[UNIT_INDEX_MAX - 1].o.flags.s.allocated = true;
    if (!check_index(0x4000) || !check_index(0x4000 + UNIT_INDEX_MAX - 1)) return 4;
    g_unitArray[0].o.flags.s.allocated = false;
    if (check_index(0x4000) || check_index(0x4000 + UNIT_INDEX_MAX)) return 5;
    g_structureArray[0].o.flags.s.used = true;
    g_structureArray[STRUCTURE_INDEX_MAX_HARD - 1].o.flags.s.used = true;
    if (!check_index(0x8000) || !check_index(0x8000 + STRUCTURE_INDEX_MAX_HARD - 1)) return 6;
    if (check_index(0x8000 + STRUCTURE_INDEX_MAX_HARD) || check_index(0)) return 7;
    if (!check_index(0xc000) || !check_index(0xffff)) return 8;
    for (Screen old = SCREEN_0; old <= SCREEN_3; old++)
    for (Screen next = SCREEN_ACTIVE; next <= SCREEN_3; next++) {
        g_screenActiveID = old;
        if (change_screen(next) != old) return 9;
        if (g_screenActiveID != (next == SCREEN_ACTIVE ? old : next)) return 10;
    }
    return 0;
}
"""
        flags = ["-m68000", "-msoft-float", "-std=gnu17", "-Ofast",
                 "-fno-split-paths", "-fomit-frame-pointer", "-Wall", "-Wextra",
                 "-Werror", "-DTOS", "-DNDEBUG", *INCLUDES]
        with tempfile.TemporaryDirectory(prefix="atari-call-68000-") as directory:
            directory = Path(directory)
            objects = []
            for name, content in (("caller", caller), ("callee", callee)):
                source, obj = directory / (name + ".c"), directory / (name + ".o")
                source.write_text(content)
                subprocess.run([tools[0], *flags, "-c", str(source),
                                "-o", str(obj)], check=True)
                assembly = directory / (name + ".s")
                subprocess.run([tools[0], *flags, "-S", str(source),
                                "-o", str(assembly)], check=True)
                generated = assembly.read_text()
                if name == "caller":
                    self.assertNotIn("_Video_Atari_CursorDirect", generated)
                    self.assertNotIn("_GFX_Screen_SetActive", generated)
                else:
                    self.assertNotIn("%sp", generated)
                objects.append(obj)
            linked = directory / "test.tos"
            subprocess.run([tools[0], "-m68000", "-msoft-float", "-nostdlib",
                            "-Wl,-e,_test_entry", "-o", str(linked),
                            *map(str, objects), "-lgcc"], check=True)
            symbols = subprocess.check_output([tools[1], "-n", str(linked)], text=True)
            base = 0x10000
            entry = base + int(re.search(r"^([0-9a-f]+) T _test_entry$", symbols, re.M)[1], 16)
            raw = linked.read_bytes()
            self.assertEqual(raw[:2], b"\x60\x1a")
            text, data, bss, symbol_size = struct.unpack_from(">4I", raw, 2)
            image = bytearray(raw[28:28 + text + data])
            relocation = 28 + text + data + symbol_size
            offset = struct.unpack_from(">I", raw, relocation)[0]
            relocation += 4
            if offset:
                while True:
                    value = struct.unpack_from(">I", image, offset)[0]
                    struct.pack_into(">I", image, offset, value + base)
                    while raw[relocation] == 1:
                        offset += 254
                        relocation += 1
                    increment = raw[relocation]
                    relocation += 1
                    if not increment:
                        break
                    offset += increment
            self.assertLess(base + text + data + bss, 0x80000)
            cpu = unicorn.Uc(unicorn.UC_ARCH_M68K, unicorn.UC_MODE_BIG_ENDIAN)
            cpu.ctl_set_cpu_model(registers.UC_CPU_M68K_M68000)
            cpu.mem_map(0, 0x100000)
            cpu.mem_write(base, bytes(image))
            cpu.mem_write(0x80000, struct.pack(">I", 0x90000))
            cpu.reg_write(registers.UC_M68K_REG_A7, 0x80000)
            preserved = {
                registers.UC_M68K_REG_D2: 0x12345678,
                registers.UC_M68K_REG_A2: 0x34567890,
            }
            for register, value in preserved.items():
                cpu.reg_write(register, value)
            cpu.emu_start(entry, 0x90000, count=100000)
            self.assertEqual(cpu.reg_read(registers.UC_M68K_REG_PC), 0x90000)
            self.assertEqual(cpu.reg_read(registers.UC_M68K_REG_D0), 0)
            for register, value in preserved.items():
                self.assertEqual(cpu.reg_read(register), value)

    def test_getinfo_context_lifetime(self):
        production = function((ROOT / "src/script/unit.c").read_text(), "Script_Unit_GetInfo")
        reference = production.replace("\tu = g_scriptCurrentUnit;\n", "")
        reference = reference.replace(
            "\twhat = STACK_PEEK(1);",
            "\tu = g_scriptCurrentUnit;\n\twhat = STACK_PEEK(1);")
        reference = reference.replace(
            "#else\n\tui = ", "#else\n\tu = g_scriptCurrentUnit;\n\tui = ")
        reference = reference.replace(
            "? g_scriptCurrentUnit->targetMove : 0", "? u->targetMove : 0")
        reference = reference.replace(
            "return g_scriptCurrentUnit->originEncoded;", "return u->originEncoded;")
        reference = reference.replace("Script_Unit_GetInfo(", "reference_getinfo(", 1)
        encode = function((ROOT / "src/tools.c").read_text(), "Tools_Index_Encode")
        house = function((ROOT / "src/unit.c").read_text(), "Unit_GetHouseID")
        harness = COMMON + r"""
Unit g_unitArray[UNIT_INDEX_MAX];
UnitInfo g_table_unitInfo[UNIT_MAX];
Unit *g_scriptCurrentUnit;
#ifndef TOS
Unit *Unit_Get_ByIndex(uint16 index) { return &g_unitArray[index]; }
#endif
HouseType g_playerHouseID;
bool g_dune2_enhanced;
static unsigned peeks, validations, searches;
#ifdef _DEBUG
uint16 Script_Stack_Peek(ScriptEngine *script, int position, const char *file, int line) {
    (void)file; (void)line;
#else
uint16 Script_Stack_Peek(ScriptEngine *script, int position) {
#endif
    peeks++;
    if (script->stackPointer >= 16 - position) { script->script = NULL; return 0; }
    return script->stack[script->stackPointer + position - 1];
}
bool GCC_FASTCALL Tools_Index_IsValid(uint16 encoded) {
    validations++;
    return (encoded & 1) != 0;
}
uint16 Unit_FindClosestRefinery(Unit *unit) {
    assert(unit == g_scriptCurrentUnit);
    searches++; unit->originEncoded = 0x8055; return 1;
}
/* PRODUCTION */
int main(void) {
    uint16 words[1] = {0};
    g_playerHouseID = 2;
    for (unsigned variant = 0; variant < 8; variant++)
    for (unsigned what = 0; what < 32; what++)
    for (unsigned stack = 0; stack < 18; stack++) {
        Unit seed = {0};
        seed.o.index = 0;
        seed.o.type = variant & 1 ? UNIT_HARVESTER : UNIT_TANK;
        seed.o.hitpoints = 37;
        seed.o.flags.s.allocated = variant & 1;
        seed.o.flags.s.byScenario = (variant & 2) != 0;
        seed.o.houseID = 4;
        seed.o.seenByHouses = variant & 4 ? 4 : 0;
        seed.orientation[0].current = -100; seed.orientation[0].target = 99;
        seed.orientation[1].current = 31; seed.orientation[1].target = -88;
        seed.targetMove = variant;
        seed.targetAttack = 0x4011;
        seed.originEncoded = variant & 2 ? 0x8022 : 0;
        seed.currentDestination.x = variant & 4;
        seed.movingSpeed = 13;
        seed.fireDelay = variant & 2;
        seed.deviated = variant & 4;
        seed.deviatedHouse = 3;
        g_dune2_enhanced = variant & 2;
        UnitInfo *ui = &g_table_unitInfo[seed.o.type];
        memset(ui,0,sizeof(*ui));
        ui->o.hitpoints = 100; ui->fireDistance = 7;
        ui->o.flags.hasTurret = (variant & 2) != 0;
        ui->flags.explodeOnDeath = (variant & 4) != 0;
        ui->movementType = variant & 1 ? 0x40 : 0;
        ScriptEngine scriptSeed = {0};
        scriptSeed.script = words; scriptSeed.stackPointer = stack;
        scriptSeed.returnValue = 0x1234;
        for (unsigned i = 0; i < 15; i++) scriptSeed.stack[i] = what;
        ScriptEngine expectedScript = scriptSeed, actualScript = scriptSeed;
        g_unitArray[0] = seed; g_scriptCurrentUnit = &g_unitArray[0];
        peeks = validations = searches = 0;
        uint16 expected = reference_getinfo(&expectedScript);
        Unit expectedUnit = g_unitArray[0];
        unsigned expectedPeeks = peeks, expectedValidations = validations, expectedSearches = searches;
        g_unitArray[0] = seed; peeks = validations = searches = 0;
        assert(Script_Unit_GetInfo(&actualScript) == expected);
        assert(!memcmp(&g_unitArray[0],&expectedUnit,sizeof(expectedUnit)));
        assert(!memcmp(&actualScript,&expectedScript,sizeof(actualScript)));
        assert(peeks == expectedPeeks && validations == expectedValidations && searches == expectedSearches);
        assert(g_scriptCurrentUnit == &g_unitArray[0]);
    }
    return 0;
}
"""
        harness = harness.replace("/* PRODUCTION */", "\n".join((encode, house, reference, production)))
        with tempfile.TemporaryDirectory(prefix="getinfo-context-") as directory:
            source = Path(directory) / "test.c"
            source.write_text(harness)
            for tos, debug in ((False, False), (False, True), (True, False), (True, True)):
                binary = Path(directory) / ("test-" + str(debug))
                subprocess.run(["cc", "-std=gnu17", "-O2", "-Wall", "-Wextra",
                                "-Werror", *(["-DTOS"] if tos else []),
                                *(["-D_DEBUG"] if debug else []),
                                *INCLUDES, str(source), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)

    def test_native_getinfo_has_no_local_frame(self):
        compiler = shutil.which("m68k-atari-mint-gcc")
        if compiler is None:
            self.skipTest("Atari cross compiler required")
        production = function((ROOT / "src/script/unit.c").read_text(), "Script_Unit_GetInfo")
        with tempfile.TemporaryDirectory(prefix="getinfo-frame-") as directory:
            source, assembly = Path(directory) / "test.c", Path(directory) / "test.s"
            source.write_text(COMMON + production)
            subprocess.run([compiler, "-m68000", "-msoft-float", "-std=gnu17",
                            "-Ofast", "-fno-split-paths", "-fomit-frame-pointer",
                            "-DTOS", "-DNDEBUG", *INCLUDES, "-S", str(source),
                            "-o", str(assembly)], check=True)
            entry = assembly.read_text().split("_Script_Unit_GetInfo:\n", 1)[1]
            prologue = entry.split("\n.L", 1)[0]
            self.assertNotRegex(prologue, r"\b(?:subq\.l|sub\.l|lea)\b[^\n]*%sp")

    def test_rotate_metadata_and_context_lifetime(self):
        production = function((ROOT / "src/script/unit.c").read_text(), "Script_Unit_Rotate")
        harness = COMMON + r"""
UnitInfo g_table_unitInfo[UNIT_MAX];
#ifdef TOS
const UnitInfo *g_unitInfoByType[UNIT_MAX];
#endif
Unit *g_scriptCurrentUnit;
static tile32 destination;
static int8 direction;
static unsigned logCalls[4];
static unsigned logCount;
static void record(unsigned call) {
    assert(logCount < 4);
    logCalls[logCount++] = call;
}
bool GCC_FASTCALL Tools_Index_IsValid(uint16 encoded) {
    record(1);
    return encoded != 0;
}
tile32 Tools_Index_GetTile(uint16 encoded) {
    assert(encoded == g_scriptCurrentUnit->targetAttack);
    record(2);
    return destination;
}
int8 Tile_GetDirection(tile32 from, tile32 to) {
    assert(from.x == g_scriptCurrentUnit->o.position.x);
    assert(from.y == g_scriptCurrentUnit->o.position.y);
    assert(to.x == destination.x && to.y == destination.y);
    record(3);
    return direction;
}
void Unit_SetOrientation(Unit *unit, int8 value, bool instant, uint16 level) {
    assert(unit == g_scriptCurrentUnit && !instant);
    assert(level == (g_table_unitInfo[unit->o.type].o.flags.hasTurret ? 1 : 0));
    record(4);
    unit->orientation[level].target = value;
    unit->orientation[level].speed = value < 0 ? -4 : 4;
}
static uint16 reference_rotate(void) {
    Unit *unit = g_scriptCurrentUnit;
    const UnitInfo *info = &g_table_unitInfo[unit->o.type];
    if (info->movementType != MOVEMENT_WINGER &&
        (unit->currentDestination.x || unit->currentDestination.y)) return 1;
    uint16 level = info->o.flags.hasTurret ? 1 : 0;
    if (unit->orientation[level].speed) return 1;
    int8 current = unit->orientation[level].current;
    if (!Tools_Index_IsValid(unit->targetAttack)) return 0;
    tile32 to = Tools_Index_GetTile(unit->targetAttack);
    int8 value;
#ifdef TOS
    if (unit->rotateValid &&
        unit->rotateFrom.x == unit->o.position.x && unit->rotateFrom.y == unit->o.position.y &&
        unit->rotateTo.x == to.x && unit->rotateTo.y == to.y) {
        value = unit->rotateOrientation;
    } else {
        value = Tile_GetDirection(unit->o.position, to);
        unit->rotateFrom = unit->o.position;
        unit->rotateTo = to;
        unit->rotateOrientation = value;
        unit->rotateValid = 1;
    }
#else
    value = Tile_GetDirection(unit->o.position, to);
#endif
    if (value == current) return 0;
    Unit_SetOrientation(unit, value, false, level);
    return 1;
}
/* PRODUCTION */
int main(void) {
    static const int8 angles[] = {-128, -1, 0, 1, 127};
    for (unsigned type = 0; type < UNIT_MAX; type++) {
#ifdef TOS
        g_unitInfoByType[type] = &g_table_unitInfo[type];
#endif
    }
    for (unsigned type = 0; type < UNIT_MAX; type++)
    for (unsigned flags = 0; flags < 32; flags++)
    for (unsigned cache = 0; cache < 8; cache++)
    for (unsigned angle = 0; angle < 5; angle++) {
        Unit seed = {0};
        seed.o.type = type;
        seed.o.position = (tile32){0x1020,0x3456};
        seed.currentDestination = (tile32){flags & 1 ? 1 : 0,flags & 2 ? 1 : 0};
        seed.targetAttack = flags & 4 ? 0x4011 : 0;
        UnitInfo *info = &g_table_unitInfo[type];
        info->movementType = flags & 8 ? MOVEMENT_WINGER : MOVEMENT_TRACKED;
        info->o.flags.hasTurret = (flags & 16) != 0;
        unsigned level = info->o.flags.hasTurret ? 1 : 0;
        seed.orientation[level].current = angles[angle];
        seed.orientation[level].speed = cache == 7 ? -4 : 0;
        destination = (tile32){0x4567,0x8765};
        direction = angles[(angle + cache) % 5];
#ifdef TOS
        seed.rotateValid = cache != 0;
        seed.rotateFrom = seed.o.position;
        seed.rotateTo = destination;
        if (cache == 1) seed.rotateFrom.x++;
        if (cache == 2) seed.rotateFrom.y++;
        if (cache == 3) seed.rotateTo.x++;
        if (cache == 4) seed.rotateTo.y++;
        seed.rotateOrientation = angles[cache == 6 ? angle : (angle + 1) % 5];
#endif
        Unit expectedUnit = seed, actualUnit = seed;
        ScriptEngine script = {0}, scriptSeed = script;
        g_scriptCurrentUnit = &expectedUnit;
        memset(logCalls,0,sizeof(logCalls)); logCount = 0;
        uint16 expected = reference_rotate();
        unsigned expectedLog[4], expectedCount = logCount;
        memcpy(expectedLog,logCalls,sizeof(logCalls));
        g_scriptCurrentUnit = &actualUnit;
        memset(logCalls,0,sizeof(logCalls)); logCount = 0;
        assert(Script_Unit_Rotate(&script) == expected);
        assert(!memcmp(&actualUnit,&expectedUnit,sizeof(actualUnit)));
        assert(logCount == expectedCount && !memcmp(logCalls,expectedLog,sizeof(logCalls)));
        assert(!memcmp(&script,&scriptSeed,sizeof(script)));
        assert(g_scriptCurrentUnit == &actualUnit);
    }
    return 0;
}
"""
        with tempfile.TemporaryDirectory(prefix="rotate-context-") as directory:
            source, binary = Path(directory) / "test.c", Path(directory) / "test"
            source.write_text(harness.replace("/* PRODUCTION */", production))
            for tos in (False, True):
                subprocess.run(["cc", "-std=gnu17", "-O2", "-Wall", "-Wextra",
                                "-Werror", *(["-DTOS"] if tos else []),
                                *INCLUDES, str(source), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)

    def test_native_rotate_reuses_metadata_and_shortens_frame(self):
        compiler = shutil.which("m68k-atari-mint-gcc")
        if compiler is None:
            self.skipTest("Atari cross compiler required")
        production = function((ROOT / "src/script/unit.c").read_text(), "Script_Unit_Rotate")
        reference = production.replace("ui = g_unitInfoByType[u->o.type];",
                                       "ui = &g_table_unitInfo[u->o.type];")
        first_assignment = reference.index("\tu = g_scriptCurrentUnit;")
        end_assignment = first_assignment + len("\tu = g_scriptCurrentUnit;")
        reference = reference[:end_assignment] + reference[end_assignment:].replace(
            "\tu = g_scriptCurrentUnit;\n", "")
        with tempfile.TemporaryDirectory(prefix="rotate-frame-") as directory:
            frames = []
            for name, body in (("reference", reference), ("optimized", production)):
                source, assembly = Path(directory) / (name + ".c"), Path(directory) / (name + ".s")
                source.write_text(COMMON + body)
                subprocess.run([compiler, "-m68000", "-msoft-float", "-std=gnu17",
                                "-Ofast", "-fno-split-paths", "-fomit-frame-pointer",
                                "-DTOS", "-DNDEBUG", *INCLUDES, "-S", str(source),
                                "-o", str(assembly)], check=True)
                generated = assembly.read_text().split("_Script_Unit_Rotate:\n", 1)[1]
                frame = re.search(r"lea \(-(\d+),%sp\),%sp", generated)
                self.assertIsNotNone(frame)
                frames.append(int(frame[1]))
                if name == "optimized":
                    self.assertIn("_g_unitInfoByType", generated)
                    self.assertNotIn("_g_table_unitInfo", generated)
            self.assertLess(frames[1], frames[0])


if __name__ == "__main__":
    unittest.main()
