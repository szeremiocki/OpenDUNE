"""Check budgeted interpretation against repeated single-opcode execution."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    match = re.search(r"^(?:static )?[^\n]*\b" + name + r"\([^;]*?\n\{", source, re.M)
    if match is None:
        raise ValueError("Missing function: " + name)
    return source[match.start():source.index("\n}\n", match.end()) + 3]


class ScriptBudgetTest(unittest.TestCase):
    def test_budget_and_single_step(self):
        source = (ROOT / "src/script/script.c").read_text()
        general = (ROOT / "src/script/general.c").read_text()
        helpers = []
        for declaration in ("void Script_Stack_Push", "uint16 Script_Stack_Pop",
                            "uint16 Script_Stack_Peek"):
            start = source.index("#ifdef _DEBUG\n" + declaration)
            helpers.append(source[start:source.index("\n}\n", start) + 3])
        production = "\n".join(helpers + [
            function(source, name) for name in
            ("Script_IsLoaded", "Script_RunInternal", "Script_Run", "Script_RunBudget")
        ] + [function(general, "Script_General_Delay")])
        reference = os.environ.get("SCRIPT_RUN_REFERENCE_SOURCE")
        if reference:
            reference = function(Path(reference).read_text(), "Script_Run")
            reference = reference.replace("bool Script_Run(", "bool reference_step(", 1)
        else:
            reference = """
static bool reference_step(ScriptEngine *script) {
    return Script_Run(script);
}
"""
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
typedef int8_t int8;
typedef int16_t int16;
typedef int32_t int32;
#include "/* HEADER */"
#include "/* ENDIAN */"
uint16 endian_bswap16(uint16 value) {
    return (uint16)((value << 8) | (value >> 8));
}
static unsigned errors, nativeCalls;
static void Script_Error(const char *message, ...) {
    assert(message != NULL);
    errors++;
}
/* PRODUCTION */
/* REFERENCE */
static ScriptInfo info, replacement;
static uint16 words[128], otherWords[128];
static uint16 count_call(ScriptEngine *script) {
    nativeCalls++;
    return ++script->variables[0];
}
static uint16 delay_call(ScriptEngine *script) {
    nativeCalls++;
    return Script_General_Delay(script);
}
static uint16 unload_call(ScriptEngine *script) {
    nativeCalls++;
    script->script = NULL;
    return 42;
}
static uint16 replace_call(ScriptEngine *script) {
    nativeCalls++;
    script->scriptInfo = &replacement;
    script->script = otherWords;
    return 43;
}
static uint16 clear_info_call(ScriptEngine *script) {
    nativeCalls++;
    script->scriptInfo = NULL;
    return 44;
}
static uint16 unload_delayed_call(ScriptEngine *script) {
    nativeCalls++;
    script->script = NULL;
    script->delay = 4;
    return 45;
}
static uint16 jump_call(ScriptEngine *script) {
    nativeCalls++;
    script->script = words;
    return 46;
}
static uint16 replacement_count_call(ScriptEngine *script) {
    nativeCalls++;
    return ++script->variables[1];
}
static const ScriptFunction callbacks[SCRIPT_FUNCTIONS_COUNT] = {
    count_call, delay_call, unload_call, replace_call, clear_info_call,
    unload_delayed_call, jump_call
};
static const ScriptFunction replacementCallbacks[SCRIPT_FUNCTIONS_COUNT] = {
    replacement_count_call
};
static uint16 inline_command(unsigned opcode, unsigned parameter) {
    return HTOBE16(0x4000 | (opcode << 8) | (parameter & 255));
}
static ScriptEngine initial(void) {
    ScriptEngine script = {0};
    script.script = words;
    script.scriptInfo = &info;
    script.stackPointer = 7;
    script.framePointer = 10;
    script.returnValue = 3;
    script.isSubroutine = 1;
    for (unsigned i = 0; i < 15; i++) script.stack[i] = 3;
    for (unsigned i = 0; i < 5; i++) script.variables[i] = i + 1;
    return script;
}
static void fill(void) {
    for (unsigned i = 0; i < 128; i++) {
        words[i] = inline_command(SCRIPT_SETRETURNVALUE, i & 127);
        otherWords[i] = inline_command(SCRIPT_SETRETURNVALUE, 100);
    }
    info.start = words;
    info.functions = callbacks;
    replacement.start = otherWords;
    replacement.functions = replacementCallbacks;
    otherWords[0] = inline_command(SCRIPT_FUNCTION, 0);
    otherWords[1] = inline_command(SCRIPT_JUMP, 3);
}
static bool repeated_steps(ScriptEngine *script, unsigned budget) {
    for (; budget && script->delay == 0; budget--)
        if (!reference_step(script)) return false;
    return true;
}
static void compare(ScriptEngine seed, unsigned budget) {
    ScriptEngine expected = seed, actual = seed;
    errors = nativeCalls = 0;
    bool expectedResult = repeated_steps(&expected, budget);
    unsigned expectedErrors = errors, expectedCalls = nativeCalls;
    errors = nativeCalls = 0;
    bool actualResult = Script_RunBudget(&actual, budget);
    assert(actualResult == expectedResult);
    assert(errors == expectedErrors && nativeCalls == expectedCalls);
    assert(!memcmp(&actual, &expected, sizeof(actual)));
}
int main(void) {
    fill();
    const unsigned budgets[] = {0, 1, 2, 3, 52};
    /* Every opcode and parameter format, with a tail that makes early
     * accidental returns observable in the final instruction pointer. */
    for (unsigned opcode = 0; opcode <= SCRIPT_RETURN; opcode++) {
        unsigned parameters = opcode == SCRIPT_BINARY ? 18 :
                              opcode == SCRIPT_UNARY ? 3 :
                              opcode == SCRIPT_FUNCTION ? 7 :
                              opcode == SCRIPT_PUSH_RETURN_OR_LOCATION ||
                              opcode == SCRIPT_POP_RETURN_OR_LOCATION ? 2 : 1;
        for (unsigned parameter = 0; parameter < parameters; parameter++)
            for (unsigned format = 0; format < 3; format++) {
                fill();
                words[0] = format == 0 ? inline_command(opcode, parameter) :
                           HTOBE16((opcode << 8) | (format == 1 ? 0x2000 : 0));
                if (format == 1) words[1] = HTOBE16(parameter);
                for (unsigned b = 0; b < sizeof(budgets) / sizeof(budgets[0]); b++)
                    compare(initial(), budgets[b]);
            }
    }
    /* Independent expectations for the nested binary/unary switches. */
    const uint16 binaryResults[] = {
        1, 1, 0, 1, 0, 0, 1, 1, 15, 9, 36, 4, 1, 96, 0, 15, 0, 15
    };
    for (unsigned op = 0; op < 18; op++) {
        fill();
        words[0] = inline_command(SCRIPT_BINARY, op);
        ScriptEngine script = initial();
        script.stack[7] = 3; script.stack[8] = 12;
        assert(Script_RunBudget(&script, 1));
        assert(script.stackPointer == 8 && script.stack[8] == binaryResults[op]);
    }
    const uint16 unaryResults[] = {0, (uint16)-5, (uint16)~5};
    for (unsigned op = 0; op < 3; op++) {
        fill();
        words[0] = inline_command(SCRIPT_UNARY, op);
        ScriptEngine script = initial();
        script.stack[7] = 5;
        assert(Script_RunBudget(&script, 2));
        assert(script.stackPointer == 7 && script.stack[7] == unaryResults[op]);
        assert(script.script == words + 2);
    }
    /* Conditional jumps distinguish both exits from the opcode case. */
    for (unsigned value = 0; value <= 1; value++) {
        fill();
        words[0] = inline_command(SCRIPT_JUMP_NE, 3);
        ScriptEngine script = initial();
        script.stack[7] = value;
        assert(Script_RunBudget(&script, 1));
        assert(script.script == words + (value ? 1 : 3));
        compare(script, 3);
    }
    /* Direct jump encoding, sign extension and extended parameters. */
    fill();
    words[0] = HTOBE16(0x8003);
    compare(initial(), 52);
    words[0] = inline_command(SCRIPT_PUSH, 255);
    ScriptEngine script = initial();
    assert(Script_RunBudget(&script, 1) && script.stack[6] == 0xffff);
    words[0] = HTOBE16((SCRIPT_SETRETURNVALUE << 8) | 0x2000);
    words[1] = HTOBE16(0xf123);
    script = initial();
    assert(Script_RunBudget(&script, 1));
    assert(script.returnValue == 0xf123 && script.script == words + 2);
    /* Delay yields without consuming the next opcode or decrementing delay. */
    fill();
    words[0] = inline_command(SCRIPT_FUNCTION, 1);
    script = initial();
    script.stack[7] = 20;
    compare(script, 52);
    assert(Script_RunBudget(&script, 52));
    assert(script.delay == 4 && script.returnValue == 4 && script.script == words + 1);
    ScriptEngine unchanged = script;
    assert(Script_RunBudget(&script, 52));
    assert(!memcmp(&script, &unchanged, sizeof(script)));
    /* Single-step callers still execute with an existing nonzero delay. */
    assert(Script_Run(&script) && script.script == words + 2 && script.delay == 4);
    assert(Script_Run(&script) && script.script == words + 3 && script.delay == 4);
    assert(Script_Run(&script) && script.script == words + 4 && script.delay == 4);
    script = initial();
    script.stack[7] = 4;
    assert(Script_RunBudget(&script, 3));
    assert(!script.delay && script.script == words + 3);
    /* Errors still report false; malformed stack handling keeps its
     * original last-opcode versus next-opcode result. */
    const unsigned invalid[][2] = {
        {31, 0}, {SCRIPT_PUSH_RETURN_OR_LOCATION, 2},
        {SCRIPT_POP_RETURN_OR_LOCATION, 2}, {SCRIPT_UNARY, 3},
        {SCRIPT_BINARY, 18}, {SCRIPT_FUNCTION, 63}, {SCRIPT_FUNCTION, 64}
    };
    for (unsigned i = 0; i < sizeof(invalid) / sizeof(invalid[0]); i++) {
        fill();
        words[0] = inline_command(invalid[i][0], invalid[i][1]);
        compare(initial(), 52);
        script = initial();
        errors = 0;
        assert(!Script_RunBudget(&script, 52) && errors == 1);
    }
    for (unsigned opcode = SCRIPT_PUSH; opcode <= SCRIPT_RETURN; opcode++) {
        fill();
        words[0] = inline_command(opcode, 0);
        for (unsigned stack = 0; stack <= 15; stack += 15) {
            script = initial();
            script.stackPointer = stack;
            compare(script, 1);
            compare(script, 3);
        }
    }
    fill();
    script = initial();
    script.script = NULL;
    compare(script, 3);
    script = initial();
    script.scriptInfo = NULL;
    compare(script, 3);
    assert(!Script_RunBudget(NULL, 3) && !Script_Run(NULL));
    return 0;
}
"""
        harness = harness.replace("/* HEADER */", str(ROOT / "src/script/script.h"))
        harness = harness.replace("/* ENDIAN */", str(ROOT / "src/os/endian.h"))
        harness = harness.replace("/* PRODUCTION */", production)
        harness = harness.replace("/* REFERENCE */", reference)
        with tempfile.TemporaryDirectory(prefix="script-budget-") as directory:
            c_file = Path(directory) / "test.c"
            c_file.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            for debug in (False, True):
                with self.subTest(debug=debug):
                    binary = Path(directory) / ("debug" if debug else "release")
                    flags = ["-D_DEBUG"] if debug else []
                    subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                                    "-Werror", *flags, str(c_file), "-o", str(binary)], check=True)
                    subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
