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
    def make_harness(self):
        source = (ROOT / "src/script/script.c").read_text()
        general = (ROOT / "src/script/general.c").read_text()
        helpers = []
        for declaration in ("void Script_Stack_Push", "uint16 Script_Stack_Pop",
                            "uint16 Script_Stack_Peek"):
            start = source.index("#ifdef _DEBUG\n" + declaration)
            helpers.append(source[start:source.index("\n}\n", start) + 3])
        production = "\n".join(helpers + [
            function(source, name) for name in
            ("Script_IsLoaded", "Script_RunInternal", "Script_RunDispatch", "Script_Run", "Script_RunBudget")
        ] + ["#ifdef TOS\n" + "\n".join(function(source, name) for name in
                 ("Script_RunNativeFallback", "Script_NativeError")) + "\n#endif",
             function(general, "Script_General_Delay")])
        native = (ROOT / "src/script/script_native.c").read_text()
        production += "\n#ifdef NATIVE_EMULATED\nextern const uint32 Script_NativeHandlers[];\n"
        production += "\n".join(function(native, name) for name in
                               ("Script_NativePreservesContext", "Script_CompileNative", "Script_NativePush",
                                "Script_NativePop", "Script_NativePeek"))
        production += "\n#elif defined(TOS)\nbool Script_RunNative(ScriptEngine *script, uint16 budget, bool stopOnDelay) {\n"
        production += "return Script_RunInternal(script, budget, stopOnDelay);\n}\n#endif\n"
        reference = os.environ.get("SCRIPT_RUN_REFERENCE_SOURCE")
        if reference:
            reference = function(Path(reference).read_text(), "Script_Run")
            reference = reference.replace("bool Script_Run(", "bool reference_step(", 1)
        else:
            reference = """
static bool reference_step(ScriptEngine *script) {
    return Script_RunInternal(script, 1, false);
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
static uint8 callbackTrace[128];
static const uint16 *callbackPCs[128];
static void record_call(ScriptEngine *script, uint8 functionID) {
    assert(nativeCalls < sizeof(callbackTrace));
    callbackPCs[nativeCalls] = script->script;
    callbackTrace[nativeCalls++] = functionID;
}
static void Script_Error(const char *message, ...) {
    assert(message != NULL);
    errors++;
}
/* PRODUCTION */
/* REFERENCE */
static ScriptInfo info, replacement;
static uint16 words[128], otherWords[128];
#ifdef NATIVE_EMULATED
volatile unsigned nativeCursorCase;
#endif
static void clear_cache(void) {
#ifdef TOS
    free(info.nativeCode); info.nativeCode = NULL;
    free(replacement.nativeCode); replacement.nativeCode = NULL;
#endif
}
static uint16 count_call(ScriptEngine *script) {
    record_call(script, 0);
    return ++script->variables[0];
}
static uint16 delay_call(ScriptEngine *script) {
    record_call(script, 1);
    return Script_General_Delay(script);
}
static uint16 unload_call(ScriptEngine *script) {
    record_call(script, 2);
    script->script = NULL;
    return 42;
}
static uint16 replace_call(ScriptEngine *script) {
    record_call(script, 3);
    script->scriptInfo = &replacement;
    script->script = otherWords;
    return 43;
}
static uint16 clear_info_call(ScriptEngine *script) {
    record_call(script, 4);
    script->scriptInfo = NULL;
    return 44;
}
static uint16 unload_delayed_call(ScriptEngine *script) {
    record_call(script, 5);
    script->script = NULL;
    script->delay = 4;
    return 45;
}
static uint16 jump_call(ScriptEngine *script) {
    record_call(script, 6);
    script->script = words;
    return 46;
}
static uint16 rewind_call(ScriptEngine *script) {
    record_call(script, 7);
    script->script--;
    script->delay = 1;
    return 47;
}
static uint16 discard_code_call(ScriptEngine *script) {
    record_call(script, 8);
#ifdef TOS
    free(script->scriptInfo->nativeCode);
    script->scriptInfo->nativeCode = NULL;
#else
    (void)script;
#endif
    return 48;
}
static uint16 recompile_call(ScriptEngine *script) {
    record_call(script, 9);
#ifdef NATIVE_EMULATED
    uint16 *oldCode = script->scriptInfo->nativeCode;
    script->scriptInfo->nativeCode = NULL;
    assert(Script_CompileNative(script->scriptInfo));
    assert(script->scriptInfo->nativeCode != oldCode);
    free(oldCode);
#else
    (void)script;
#endif
    return 49;
}
static uint16 uncached_replacement_call(ScriptEngine *script) {
    record_call(script, 10);
#ifdef TOS
    free(replacement.nativeCode);
    replacement.nativeCode = NULL;
#endif
    script->scriptInfo = &replacement;
    script->script = otherWords;
    return 50;
}
static uint16 replacement_count_call(ScriptEngine *script) {
    record_call(script, 11);
    return ++script->variables[1];
}
struct Unit *g_scriptCurrentUnit;
/* Fake unit: targetAttack sits at byte offset 84 (UNIT_TARGETATTACK in the runner). */
static uint16 unitWords[64];
uint16 Script_Unit_GetInfo(ScriptEngine *script) {
    if (STACK_PEEK(1) == 5) return unitWords[42];
    record_call(script, 12);
    return STACK_PEEK(1);
}
#define CONTEXT_CALLBACK(name) \
    uint16 name(ScriptEngine *script) { (void)script; return 0; }
CONTEXT_CALLBACK(Script_General_DelayRandom)
CONTEXT_CALLBACK(Script_General_GetDistanceToTile)
CONTEXT_CALLBACK(Script_General_GetDistanceToObject)
CONTEXT_CALLBACK(Script_General_NoOperation)
CONTEXT_CALLBACK(Script_Unit_Rotate)
CONTEXT_CALLBACK(Script_Unit_FindStructure)
#undef CONTEXT_CALLBACK
static const ScriptFunction callbacks[SCRIPT_FUNCTIONS_COUNT] = {
    count_call, delay_call, unload_call, replace_call, clear_info_call,
    unload_delayed_call, jump_call, rewind_call, discard_code_call,
    recompile_call, uncached_replacement_call, Script_Unit_GetInfo,
    Script_General_Delay
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
    clear_cache();
    for (unsigned i = 0; i < 128; i++) {
        words[i] = inline_command(SCRIPT_SETRETURNVALUE, i & 127);
        otherWords[i] = inline_command(SCRIPT_SETRETURNVALUE, 100);
    }
    info.start = words;
    info.startCount = 128;
    info.functions = callbacks;
    replacement.start = otherWords;
    replacement.startCount = 128;
    replacement.functions = replacementCallbacks;
    otherWords[0] = inline_command(SCRIPT_FUNCTION, 0);
    otherWords[1] = inline_command(SCRIPT_JUMP, 3);
}
/* CACHE RUNNERS */
static bool repeated_steps(ScriptEngine *script, unsigned budget) {
    for (; budget && script->delay == 0; budget--)
        if (!reference_step(script)) return false;
    return true;
}
static void compare(ScriptEngine seed, unsigned budget) {
    ScriptEngine expected = seed, actual = seed;
    clear_cache();
    errors = nativeCalls = 0;
    bool expectedResult = repeated_steps(&expected, budget);
    unsigned expectedErrors = errors, expectedCalls = nativeCalls;
    uint8 expectedTrace[128];
    const uint16 *expectedPCs[128];
    if (expectedCalls) memcpy(expectedTrace, callbackTrace, expectedCalls);
    if (expectedCalls) memcpy(expectedPCs, callbackPCs, expectedCalls * sizeof(*expectedPCs));
    errors = nativeCalls = 0;
    bool actualResult = Script_RunBudget(&actual, budget);
    assert(actualResult == expectedResult);
    assert(errors == expectedErrors && nativeCalls == expectedCalls);
    if (expectedCalls) assert(!memcmp(callbackTrace, expectedTrace, expectedCalls));
    if (expectedCalls) assert(!memcmp(callbackPCs, expectedPCs, expectedCalls * sizeof(*expectedPCs)));
    assert(!memcmp(&actual, &expected, sizeof(actual)));
}
static void compare_steps(ScriptEngine seed, unsigned steps) {
    ScriptEngine expected = seed, actual = seed;
    for (unsigned i = 0; i < steps; i++) {
        errors = nativeCalls = 0;
        bool expectedResult = repeated_steps(&expected, 1);
        unsigned expectedErrors = errors, expectedCalls = nativeCalls;
        uint8 expectedTrace[128];
        const uint16 *expectedPCs[128];
        if (expectedCalls) memcpy(expectedTrace, callbackTrace, expectedCalls);
        if (expectedCalls) memcpy(expectedPCs, callbackPCs, expectedCalls * sizeof(*expectedPCs));
        errors = nativeCalls = 0;
        bool actualResult = Script_RunBudget(&actual, 1);
        assert(actualResult == expectedResult);
        assert(errors == expectedErrors && nativeCalls == expectedCalls);
        if (expectedCalls) assert(!memcmp(callbackTrace, expectedTrace, expectedCalls));
        if (expectedCalls) assert(!memcmp(callbackPCs, expectedPCs, expectedCalls * sizeof(*expectedPCs)));
        assert(!memcmp(&actual, &expected, sizeof(actual)));
        if (!expectedResult) break;
        if (expected.delay) { expected.delay--; actual.delay--; }
    }
}
#ifdef NATIVE_EMULATED
static unsigned fusion_pair(unsigned family, unsigned firstWords, unsigned secondWords) {
    fill();
    unsigned firstOpcode = family == 0 ? SCRIPT_STACK_REWIND :
                           family < 3 ? SCRIPT_PUSH_RETURN_OR_LOCATION : SCRIPT_BINARY;
    unsigned firstParameter = family == 0 ? 1 : family < 3 ? 0 : family - 1;
    unsigned secondOpcode = family == 0 ? SCRIPT_PUSH_RETURN_OR_LOCATION :
                            family == 1 ? SCRIPT_PUSH : SCRIPT_JUMP_NE;
    unsigned secondParameter = family == 0 ? 0 : family == 1 ? 0xff81 : 8;
    words[0] = firstWords == 1 ? inline_command(firstOpcode, firstParameter) :
               HTOBE16(0x2000 | (firstOpcode << 8));
    if (firstWords == 2) words[1] = HTOBE16(firstParameter);
    words[firstWords] = secondWords == 1 ? inline_command(secondOpcode, secondParameter) :
                        HTOBE16(0x2000 | (secondOpcode << 8));
    if (secondWords == 2) words[firstWords + 1] = HTOBE16(secondParameter);
    words[firstWords + secondWords] = inline_command(SCRIPT_FUNCTION, 0);
    words[8] = inline_command(SCRIPT_FUNCTION, 0);
    return firstWords + secondWords;
}
#endif
int main(void) {
    fill();
    const unsigned budgets[] = {0, 1, 2, 3, 52};
    /* Every opcode and parameter format, with a tail that makes early
     * accidental returns observable in the final instruction pointer. */
    for (unsigned opcode = 0; opcode <= SCRIPT_RETURN; opcode++) {
        unsigned parameters = opcode == SCRIPT_BINARY ? 18 :
                              opcode == SCRIPT_UNARY ? 3 :
                              opcode == SCRIPT_FUNCTION ? 13 :
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
                compare_steps(initial(), 8);
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
    /* Signed 16-bit arithmetic, including the DIVS quotient-overflow case. */
    const uint16 values[] = {0, 1, 3, 0x7fff, 0x8000, 0xffff};
    for (unsigned op = 0; op < 18; op++)
        for (unsigned left = 0; left < sizeof(values) / sizeof(values[0]); left++)
            for (unsigned right = 0; right < sizeof(values) / sizeof(values[0]); right++) {
                if ((op == 11 || op == 16) && values[right] == 0) continue;
                if ((op == 12 || op == 13) && values[right] > 15) continue;
                if (op == 13 && (int16)values[left] < 0) continue;
                fill();
                words[0] = inline_command(SCRIPT_BINARY, op);
                ScriptEngine seed = initial();
                seed.stack[7] = values[right];
                seed.stack[8] = values[left];
                compare(seed, 1);
                compare_steps(seed, 3);
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
    ScriptEngine script;
    words[0] = HTOBE16(0x8003);
    compare(initial(), 52);
    /* Original PCs can enter a word also used as another opcode's operand. */
    fill();
    words[0] = HTOBE16((SCRIPT_SETRETURNVALUE << 8) | 0x2000);
    words[1] = inline_command(SCRIPT_SETRETURNVALUE, 73);
    words[2] = HTOBE16(0x8001);
    compare(initial(), 52);
    /* Both callback paths observe the advanced bytecode PC after a mixed
     * sequence of native fall-through and prelinked branches. */
    fill();
    words[0] = HTOBE16(0x2000 | (SCRIPT_SETRETURNVALUE << 8));
    words[1] = HTOBE16(73);
    words[2] = inline_command(SCRIPT_PUSH, 0);
    words[3] = HTOBE16(0x2000 | (SCRIPT_JUMP_NE << 8));
    words[4] = HTOBE16(0x8006);
    words[5] = inline_command(31, 0);
    words[6] = HTOBE16(0x2000 | (SCRIPT_FUNCTION << 8));
    words[7] = HTOBE16(11);
    words[9] = inline_command(SCRIPT_FUNCTION, 0);
    for (unsigned b = 0; b < sizeof(budgets) / sizeof(budgets[0]); b++)
        compare(initial(), budgets[b]);
    compare_steps(initial(), 12);
    /* MoveToTarget-style rewinds repeat the original bytecode instruction. */
    fill();
    words[0] = inline_command(SCRIPT_FUNCTION, 7);
    compare(initial(), 52);
    script = initial();
    assert(Script_RunBudget(&script, 52));
    assert(script.script == words && script.delay == 1 && script.returnValue == 47);
    script.delay = 0;
    assert(Script_RunBudget(&script, 52));
    assert(script.script == words && script.delay == 1 && script.returnValue == 47);
    fill();
    words[0] = inline_command(SCRIPT_PUSH, 255);
    script = initial();
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
        for (unsigned stack = 0; stack <= 15; stack++) {
            script = initial();
            script.stackPointer = stack;
            compare(script, 1);
            compare(script, 3);
        }
        for (unsigned opcode = SCRIPT_PUSH_RETURN_OR_LOCATION;
             opcode <= SCRIPT_POP_RETURN_OR_LOCATION; opcode += 6) {
            fill();
            words[0] = inline_command(opcode, 1);
            for (unsigned stack = 0; stack <= 15; stack++) {
                script = initial();
                script.stackPointer = stack;
                compare(script, 1);
                compare_steps(script, 3);
            }
        }
        const unsigned frameOpcodes[] = {
            SCRIPT_PUSH_LOCAL_VARIABLE, SCRIPT_PUSH_PARAMETER,
            SCRIPT_POP_LOCAL_VARIABLE, SCRIPT_POP_PARAMETER
        };
        for (unsigned i = 0; i < sizeof(frameOpcodes) / sizeof(frameOpcodes[0]); i++) {
            fill();
            words[0] = inline_command(frameOpcodes[i], 0);
            script = initial();
            script.framePointer = 25;
            compare(script, 1);
            compare_steps(script, 3);
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
#ifdef NATIVE_EMULATED
    /* Both sides of budget and stack guards, and both entry lengths. The
     * full engine comparison includes persistent, no-longer-live stack slots. */
    const unsigned fusionStacks[] = {0, 1, 2, 7, 13, 14, 15};
    for (unsigned family = 0; family < 9; family++) {
        for (unsigned firstWords = 1; firstWords <= 2; firstWords++) {
            for (unsigned secondWords = 1; secondWords <= 2; secondWords++) {
                fusion_pair(family, firstWords, secondWords);
                for (unsigned s = 0; s < sizeof(fusionStacks) / sizeof(fusionStacks[0]); s++) {
                    unsigned stack = fusionStacks[s];
                    if (family == 0 && stack == 15) continue;
                    script = initial();
                    script.stackPointer = stack;
                    script.returnValue = stack & 1 ? 0xffff : 0;
                    for (unsigned i = 0; i < 15; i++) script.stack[i] = 0x4100 + i;
                    for (unsigned b = 0; b < sizeof(budgets) / sizeof(budgets[0]); b++)
                        compare(script, budgets[b]);
                }
                /* Direct entry at the second opcode must remain independent. */
                script = initial();
                script.script = words + firstWords;
                compare(script, 1);
                compare(script, 3);
                compare_steps(initial(), 4);
            }
        }
    }
    /* Signed comparisons and both branch outcomes for every comparison family. */
    for (unsigned family = 3; family < 9; family++) {
        fusion_pair(family, 2, 2);
        for (unsigned left = 0; left < sizeof(values) / sizeof(values[0]); left++) {
            for (unsigned right = 0; right < sizeof(values) / sizeof(values[0]); right++) {
                script = initial();
                script.stack[7] = values[right];
                script.stack[8] = values[left];
                compare(script, 2);
                compare(script, 3);
            }
        }
    }
    fusion_pair(0, 1, 1);
    script = initial();
    script.stackPointer = 255;
    compare(script, 1);
    compare(script, 2);
    compare(script, 3);
    /* Each family must actually bypass the second entry, not just compile
     * into an always-falling-back wrapper with equivalent results. */
    for (unsigned family = 0; family < 9; family++) {
        fusion_pair(family, 2, 2);
        script = initial();
        script.returnValue = 0;
        nativeCursorCase = 13 + family;
        compare(script, 3);
        nativeCursorCase = 0;
    }
    /* PUSH #5 + Script_Unit_GetInfo (callback 11) reads targetAttack inline. */
    g_scriptCurrentUnit = (struct Unit *)unitWords;
    for (unsigned firstWords = 1; firstWords <= 2; firstWords++) {
        for (unsigned target = 0; target < 3; target++) {
            fill();
            unitWords[42] = target * 0x8001;
            words[0] = firstWords == 1 ? inline_command(SCRIPT_PUSH, 5) :
                       HTOBE16(0x2000 | (SCRIPT_PUSH << 8));
            if (firstWords == 2) words[1] = HTOBE16(5);
            words[firstWords] = inline_command(SCRIPT_FUNCTION, 11);
            words[firstWords + 1] = inline_command(SCRIPT_FUNCTION, 0);
            for (unsigned b = 0; b < sizeof(budgets) / sizeof(budgets[0]); b++)
                compare(initial(), budgets[b]);
            script = initial();
            script.stackPointer = 0;
            compare(script, 3);
            script.stackPointer = 255;
            compare(script, 3);
            script = initial();
            script.script = words + firstWords;
            compare(script, 2);
            compare_steps(initial(), 4);
            script = initial();
            nativeCursorCase = 22;
            compare(script, 3);
            nativeCursorCase = 0;
        }
    }
    /* A null current unit takes the plain path instead of dereferencing it. */
    g_scriptCurrentUnit = NULL;
    fill();
    words[0] = inline_command(SCRIPT_PUSH, 5);
    words[1] = inline_command(SCRIPT_FUNCTION, 11);
    compare(initial(), 3);
    g_scriptCurrentUnit = (struct Unit *)unitWords;
    /* Overlapping pairs execute left-to-right. Entering the middle still
     * enables its own pair, while budget two must not consume three opcodes. */
    fill();
    words[0] = inline_command(SCRIPT_STACK_REWIND, 1);
    words[1] = inline_command(SCRIPT_PUSH_RETURN_OR_LOCATION, 0);
    words[2] = inline_command(SCRIPT_PUSH2, 0x81);
    for (unsigned b = 0; b < sizeof(budgets) / sizeof(budgets[0]); b++)
        compare(initial(), budgets[b]);
    script = initial();
    script.script = words + 1;
    compare(script, 2);
    compare_steps(initial(), 4);
    fill();
    words[0] = inline_command(SCRIPT_STACK_REWIND, 1);
    words[1] = inline_command(SCRIPT_PUSH_RETURN_OR_LOCATION, 0);
    words[2] = HTOBE16(0x2000 | (SCRIPT_JUMP_NE << 8));
    words[3] = HTOBE16(8);
    for (unsigned b = 0; b < sizeof(budgets) / sizeof(budgets[0]); b++)
        compare(initial(), budgets[b]);
    script = initial();
    script.script = words + 1;
    compare(script, 2);
    compare_steps(initial(), 4);
    /* An operand can itself begin a fused pair without changing the literal
     * value consumed by the preceding two-word instruction. */
    fill();
    words[0] = HTOBE16(0x2000 | (SCRIPT_SETRETURNVALUE << 8));
    words[1] = inline_command(SCRIPT_STACK_REWIND, 1);
    words[2] = inline_command(SCRIPT_PUSH_RETURN_OR_LOCATION, 0);
    words[3] = inline_command(SCRIPT_PUSH2, 1);
    words[4] = HTOBE16(0x8001);
    for (unsigned b = 0; b < sizeof(budgets) / sizeof(budgets[0]); b++)
        compare(initial(), budgets[b]);
    script = initial();
    script.script = words + 1;
    compare(script, 2);
    compare_steps(initial(), 4);
    fusion_pair(0, 2, 1);
    words[1] = HTOBE16(0x0101);
    compare(initial(), 1);
    compare(initial(), 2);
    compare(initial(), 3);
    /* Fused pairs at DATA's end and taken out-of-range targets retain the
     * final-budget success before the next attempted opcode is rejected. */
    for (unsigned family = 0; family < 9; family++) {
        unsigned secondWords = family < 2 ? 1 : 2;
        unsigned length = fusion_pair(family, 1, secondWords);
        uint16 pair[3];
        memcpy(pair, words, length * sizeof(*pair));
        unsigned start = 128 - length;
        memcpy(words + start, pair, length * sizeof(*pair));
        if (family >= 2) words[127] = HTOBE16(128);
        script = initial();
        script.script = words + start;
        compare(script, 1);
        compare(script, 2);
        errors = 0;
        assert(Script_RunBudget(&script, 2) && script.script == words + 128 && errors == 0);
        assert(!Script_RunBudget(&script, 1) && script.script == NULL && errors == 1);
        script = initial();
        script.script = words + start;
        errors = 0;
        assert(!Script_RunBudget(&script, 3) && script.script == NULL && errors == 1);
        if (family >= 2) {
            words[127] = HTOBE16(0xffff);
            script = initial();
            script.script = words + start;
            script.returnValue = 0;
            bool branchTaken = family == 2 || family == 4 || family == 5 || family == 7;
            errors = 0;
            assert(Script_RunBudget(&script, 2) && errors == 0);
            assert((uintptr_t)script.script ==
                   (uintptr_t)words + (branchTaken ? 0x7fff : 128) * 2);
            assert(!Script_RunBudget(&script, 1) && script.script == NULL && errors == 1);
        }
    }
    /* Path counters in the simulator distinguish cursor dispatch from PC
     * resolution while the usual comparison checks complete VM state. */
    fill();
    for (unsigned i = 0; i < 4; i++) {
        unsigned offset = i * 6;
        words[offset] = HTOBE16(0x2000 | (SCRIPT_SETRETURNVALUE << 8));
        words[offset + 1] = HTOBE16(73);
        words[offset + 2] = HTOBE16(0x2000 | (SCRIPT_PUSH << 8));
        words[offset + 3] = HTOBE16(2);
        words[offset + 4] = inline_command(SCRIPT_POP_RETURN_OR_LOCATION, 0);
        words[offset + 5] = inline_command(SCRIPT_STACK_REWIND, 0);
    }
    nativeCursorCase = 1;
    compare(initial(), 17);
    nativeCursorCase = 0;
    fill();
    words[0] = HTOBE16(0x8000);
    nativeCursorCase = 2;
    compare(initial(), 5);
    nativeCursorCase = 0;
    fill();
    for (unsigned i = 0; i < 4; i++) words[i] = inline_command(SCRIPT_FUNCTION, 0);
    nativeCursorCase = 3;
    compare(initial(), 4);
    nativeCursorCase = 0;
    fill();
    words[0] = HTOBE16(0x2000 | (SCRIPT_SETRETURNVALUE << 8));
    words[1] = inline_command(SCRIPT_SETRETURNVALUE, 73);
    words[2] = HTOBE16(0x8001);
    nativeCursorCase = 4;
    compare(initial(), 4);
    nativeCursorCase = 0;
    for (unsigned value = 0; value <= 1; value++) {
        fill();
        words[0] = inline_command(SCRIPT_JUMP_NE, 3);
        script = initial();
        script.stack[7] = value;
        nativeCursorCase = 5 + value;
        compare(script, 3);
        nativeCursorCase = 0;
    }
    const unsigned returnOpcodes[] = {SCRIPT_RETURN, SCRIPT_POP_RETURN_OR_LOCATION};
    for (unsigned i = 0; i < 2; i++) {
        fill();
        words[0] = inline_command(returnOpcodes[i], i);
        script = initial();
        script.stack[8] = 4;
        nativeCursorCase = 7 + i;
        compare(script, 3);
        nativeCursorCase = 0;
    }
    /* Audited callbacks keep the cursor, including extended operands. */
    fill();
    for (unsigned i = 0; i < 4; i++) words[i] = inline_command(SCRIPT_FUNCTION, 11);
    nativeCursorCase = 9;
    compare(initial(), 4);
    nativeCursorCase = 0;
    fill();
    words[0] = HTOBE16(0x2000 | (SCRIPT_FUNCTION << 8));
    words[1] = HTOBE16(11);
    words[2] = inline_command(SCRIPT_FUNCTION, 11);
    words[3] = HTOBE16(0x2000 | (SCRIPT_FUNCTION << 8));
    words[4] = HTOBE16(11);
    nativeCursorCase = 10;
    compare(initial(), 3);
    nativeCursorCase = 0;
    fill();
    words[0] = inline_command(SCRIPT_FUNCTION, 12);
    script = initial();
    script.stack[7] = 20;
    nativeCursorCase = 11;
    compare(script, 52);
    nativeCursorCase = 0;
    assert(Script_RunBudget(&script, 52));
    assert(script.delay == 4 && script.script == words + 1 && script.returnValue == 4);
    assert(Script_Run(&script) && script.script == words + 2 && script.delay == 4);
    script = initial();
    script.stack[7] = 4;
    compare(script, 3);
    assert(Script_RunBudget(&script, 3));
    assert(script.delay == 0 && script.script == words + 3);
    fill();
    words[0] = inline_command(SCRIPT_FUNCTION, 11);
    script = initial();
    script.stackPointer = 15;
    nativeCursorCase = 12;
    compare(script, 1);
    compare(script, 3);
    nativeCursorCase = 0;
    script = initial();
    script.stack[7] = 0xffff;
    assert(Script_RunBudget(&script, 1) && script.returnValue == 0xffff);
    /* A fast return must not weaken the next callback's conservative path. */
    for (unsigned callback = 2; callback <= 10; callback++) {
        fill();
        words[0] = inline_command(SCRIPT_FUNCTION, 11);
        words[1] = inline_command(SCRIPT_FUNCTION, callback);
        for (unsigned b = 0; b < sizeof(budgets) / sizeof(budgets[0]); b++)
            compare(initial(), budgets[b]);
        compare_steps(initial(), 8);
    }
    fill();
    words[0] = inline_command(SCRIPT_FUNCTION, 12);
    script = initial();
    script.stackPointer = 15;
    compare(script, 1);
    compare(script, 3);
    /* Unreachable malformed trailing data does not disable the cache. */
    fill();
    words[127] = HTOBE16(0x2000 | (SCRIPT_SETRETURNVALUE << 8));
    refresh_cache();
    assert(BETOH16(info.nativeCode[127 * 8 + 3]) == 0x7021);
    script = initial();
    assert(Script_RunBudget(&script, 1));
    assert(script.script == words + 1);
    script.script = words + 127;
    errors = 0;
    assert(!Script_RunBudget(&script, 1));
    assert(script.script == NULL && errors == 1);
    script = initial();
    script.script = (uint16 *)((uint8 *)words + 1);
    errors = 0;
    assert(!Script_RunBudget(&script, 1));
    assert(script.script == NULL && errors == 1);
    script = initial();
    script.script = words + 128;
    errors = 0;
    assert(!Script_RunBudget(&script, 1));
    assert(script.script == NULL && errors == 1);
    /* Prelinked targets are checked only when execution can continue.
     * An untaken conditional must never validate its unused destination. */
    const uint16 destinations[] = {128, 129, 0x7fff, 0xffff};
    for (unsigned conditional = 0; conditional <= 1; conditional++) {
        for (unsigned i = 0; i < sizeof(destinations) / sizeof(destinations[0]); i++) {
            fill();
            unsigned target = conditional ? destinations[i] & 0x7fff : destinations[i];
            words[0] = HTOBE16(0x2000 |
                       ((conditional ? SCRIPT_JUMP_NE : SCRIPT_JUMP) << 8));
            words[1] = HTOBE16(destinations[i]);
            script = initial();
            script.stack[7] = 0;
            errors = 0;
            assert(Script_RunBudget(&script, 1));
            assert((uintptr_t)script.script == (uintptr_t)words + target * 2);
            assert(errors == 0);
            script.delay = 1;
            assert(Script_RunBudget(&script, 52) && errors == 0);
            script.delay = 0;
            assert(!Script_RunBudget(&script, 1));
            assert(script.script == NULL && errors == 1);
            script = initial();
            script.stack[7] = 0;
            errors = 0;
            assert(!Script_RunBudget(&script, 2));
            assert(script.script == NULL && errors == 1);
            if (conditional) {
                script = initial();
                script.stack[7] = 1;
                errors = 0;
                assert(Script_RunBudget(&script, 2));
                assert(script.script == words + 3 && errors == 0);
            }
        }
    }
    /* A valid opcode may advance to DATA's end; reject only on execution. */
    fill();
    script = initial();
    script.script = words + 127;
    assert(Script_RunBudget(&script, 1) && script.script == words + 128);
    errors = 0;
    assert(!Script_RunBudget(&script, 1));
    assert(script.script == NULL && errors == 1);
    script = initial();
    script.script = words + 126;
    assert(Script_RunBudget(&script, 2) && script.script == words + 128);
    script.delay = 1;
    assert(Script_RunBudget(&script, 1) && script.script == words + 128);
    errors = 0;
    assert(!Script_Run(&script));
    assert(script.script == NULL && errors == 1);
    script = initial();
    script.script = words + 127;
    errors = 0;
    assert(!Script_RunBudget(&script, 2));
    assert(script.script == NULL && errors == 1);
    fill();
    words[127] = inline_command(SCRIPT_FUNCTION, 1);
    script = initial();
    script.script = words + 127;
    script.stack[7] = 20;
    errors = 0;
    assert(Script_RunBudget(&script, 52));
    assert(script.script == words + 128 && script.delay == 4 && errors == 0);
    script.delay = 0;
    assert(!Script_RunBudget(&script, 1));
    assert(script.script == NULL && errors == 1);
    /* Fast callbacks at DATA's end retain deferred bounds validation. */
    fill();
    words[126] = HTOBE16(0x2000 | (SCRIPT_FUNCTION << 8));
    words[127] = HTOBE16(11);
    script = initial();
    script.script = words + 126;
    assert(Script_RunBudget(&script, 1) && script.script == words + 128);
    errors = 0;
    assert(!Script_RunBudget(&script, 1));
    assert(script.script == NULL && errors == 1);
    fill();
    words[127] = inline_command(SCRIPT_FUNCTION, 12);
    script = initial();
    script.script = words + 127;
    script.stack[7] = 20;
    errors = 0;
    assert(Script_RunBudget(&script, 52));
    assert(script.script == words + 128 && script.delay == 4 && errors == 0);
    script.delay = 0;
    assert(!Script_RunBudget(&script, 1));
    assert(script.script == NULL && errors == 1);
#endif
    clear_cache();
    return 0;
}
"""
        harness = harness.replace("Script_RunBudget(", "run_budget(").replace(
            "Script_Run(", "run_step(")
        harness = harness.replace("/* CACHE RUNNERS */", r"""
static void refresh_cache(void) {
    clear_cache();
#ifdef NATIVE_EMULATED
    assert(Script_CompileNative(&info));
    assert(Script_CompileNative(&replacement));
#endif
}
static bool run_budget(ScriptEngine *script, uint16 budget) {
    refresh_cache();
    return Script_RunBudget(script, budget);
}
static bool run_step(ScriptEngine *script) {
    refresh_cache();
    return Script_Run(script);
}
""")
        harness = harness.replace("/* HEADER */", str(ROOT / "src/script/script.h"))
        harness = harness.replace("/* ENDIAN */", str(ROOT / "src/os/endian.h"))
        harness = harness.replace("/* PRODUCTION */", production)
        harness = harness.replace("/* REFERENCE */", reference)
        return harness

    def test_budget_and_single_step(self):
        harness = self.make_harness()
        with tempfile.TemporaryDirectory(prefix="script-budget-") as directory:
            c_file = Path(directory) / "test.c"
            c_file.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            for tos in (False, True):
                for debug in (False, True):
                    with self.subTest(tos=tos, debug=debug):
                        binary = Path(directory) / f"test-{tos}-{debug}"
                        flags = (["-D_DEBUG"] if debug else []) + (["-DTOS"] if tos else [])
                        subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                                        "-Werror", *flags, str(c_file), "-o", str(binary)], check=True)
                        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
