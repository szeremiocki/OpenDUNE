"""Exercise native script construction, loader fallback and buffer ownership."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tools.test_script_budget import ROOT, function


class ScriptNativeLoaderTest(unittest.TestCase):
    def test_decode_and_lifetime(self):
        source = (ROOT / "src/script/script.c").read_text()
        native = (ROOT / "src/script/script_native.c").read_text()
        production = "\n".join(function(native, name) for name in
                               ("Script_NativePreservesContext", "Script_CompileNative")) + "\n"
        production += "\n".join(function(source, name) for name in
                                ("Script_ClearInfo", "Script_LoadFromFile"))
        harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
typedef int8_t int8;
typedef int16_t int16;
#include "/* HEADER */"
#include "/* ENDIAN */"
#include "/* FOURCC */"
const uint32 Script_NativeHandlers[] = {/* HANDLERS */};
#define CONTEXT_CALLBACK(name, value) \
    uint16 name(ScriptEngine *script) { (void)script; return value; }
CONTEXT_CALLBACK(Script_General_Delay, 1)
CONTEXT_CALLBACK(Script_General_DelayRandom, 2)
CONTEXT_CALLBACK(Script_General_GetDistanceToTile, 3)
CONTEXT_CALLBACK(Script_General_GetDistanceToObject, 4)
CONTEXT_CALLBACK(Script_General_NoOperation, 5)
CONTEXT_CALLBACK(Script_Unit_GetInfo, 6)
CONTEXT_CALLBACK(Script_Unit_Rotate, 7)
CONTEXT_CALLBACK(Script_Unit_FindStructure, 8)
CONTEXT_CALLBACK(Script_Unit_Fire, 9)
CONTEXT_CALLBACK(Script_Unit_MoveToTarget, 10)
#undef CONTEXT_CALLBACK
uint16 endian_bswap16(uint16 value) {
    return (uint16)((value << 8) | (value >> 8));
}
uint32 endian_bswap32(uint32 value) {
    return ((value & 0xff) << 24) | ((value & 0xff00) << 8) |
           ((value >> 8) & 0xff00) | (value >> 24);
}
static bool nativeST = true, exists = true, failDecode;
static unsigned warnings, opened, closed;
static const uint8 text[] = {1, 2, 3};
static uint16 offsets[2], data[4];
static uint32 orderLength = sizeof(offsets), dataLength = sizeof(data);
static bool Video_Atari_CursorDirect(void) { return nativeST; }
static bool File_Exists(const char *filename) {
    assert(!strcmp(filename, "TEST.EMC"));
    return exists;
}
static uint8 ChunkFile_Open(const char *filename) {
    assert(!strcmp(filename, "TEST.EMC"));
    opened++;
    return 7;
}
static uint32 ChunkFile_Seek(uint8 index, uint32 chunk) {
    assert(index == 7);
    if (chunk == HTOBE32(CC_TEXT)) return sizeof(text);
    if (chunk == HTOBE32(CC_ORDR)) return orderLength;
    assert(chunk == HTOBE32(CC_DATA));
    return dataLength;
}
static void ChunkFile_Read(uint8 index, uint32 chunk, void *buffer, uint32 length) {
    assert(index == 7 && buffer != NULL);
    const void *source = chunk == HTOBE32(CC_TEXT) ? (const void *)text :
                         chunk == HTOBE32(CC_ORDR) ? (const void *)offsets :
                         (const void *)data;
    memcpy(buffer, source, length);
}
static void ChunkFile_Close(uint8 index) {
    assert(index == 7);
    closed++;
}
static void Warning(const char *format, const char *filename) {
    assert(strstr(format, "using bytecode decoder") != NULL);
    assert(!strcmp(filename, "TEST.EMC"));
    warnings++;
}
static void *test_calloc(size_t count, size_t size) {
    if (failDecode && count == 5 && size == 16)
        return NULL;
    return calloc(count, size);
}
#define calloc test_calloc
/* PRODUCTION */
#undef calloc
static const ScriptFunction callbacks[SCRIPT_FUNCTIONS_COUNT] = {0};
static uint32 entry_target(const uint16 *entry) {
    unsigned jump = BETOH16(entry[1]) == 0x323c &&
                    BETOH16(entry[3]) == 0x4ef9 ? 3 : 4;
    assert(BETOH16(entry[jump]) == 0x4ef9);
    return ((uint32)BETOH16(entry[jump + 1]) << 16) | BETOH16(entry[jump + 2]);
}
static void check_loaded(const ScriptInfo *info, bool cached) {
    assert(info->functions == callbacks);
    assert(info->startCount == 4 && info->offsetsCount == 2);
    assert(info->offsets[0] == 0 && info->offsets[1] == 2);
    assert(!memcmp(info->start, data, sizeof(data)));
    assert((info->nativeCode != NULL) == cached);
    if (cached) {
        assert(BETOH16(info->nativeCode[0]) == 0x7e20);
        assert(BETOH16(info->nativeCode[1]) == 0x357c);
        assert(BETOH16(info->nativeCode[2]) == 0xf123);
        assert(BETOH16(info->nativeCode[2 * 8 + 2]) == 0xffff);
        assert(BETOH16(info->nativeCode[3 * 8]) == 0x7e10);
        uint32 destination = ((uint32)BETOH16(info->nativeCode[3 * 8 + 2]) << 16) |
                             BETOH16(info->nativeCode[3 * 8 + 3]);
        assert(destination == (uint32)((uintptr_t)info->nativeCode + 2 * 16));
    }
}
int main(void) {
    ScriptInfo info = {0};
    assert(!Script_CompileNative(&info) && info.nativeCode == NULL);
    /* All flag combinations, opcode bits and signed inline parameters. */
    uint16 words[8];
    info.start = words;
    info.startCount = 2;
    for (unsigned encoding = 0; encoding <= 0xffff; encoding++) {
        words[0] = HTOBE16(encoding);
        words[1] = HTOBE16(0xf123);
        assert(Script_CompileNative(&info));
        unsigned opcode = (encoding >> 8) & 31;
        uint16 parameter = 0;
        unsigned length = 1;
        if (encoding & 0x8000) {
            opcode = SCRIPT_JUMP;
            parameter = encoding & 0x7fff;
        } else if (encoding & 0x4000) {
            parameter = (int16)(int8)(encoding & 255);
        } else if (encoding & 0x2000) {
            parameter = 0xf123;
            length = 2;
        }
        unsigned handler = opcode <= SCRIPT_RETURN ? opcode : 40;
        if ((opcode == SCRIPT_PUSH_RETURN_OR_LOCATION ||
             opcode == SCRIPT_POP_RETURN_OR_LOCATION) && parameter > 1) handler = 40;
        if (opcode == SCRIPT_UNARY) handler = parameter < 3 ? 19 + parameter : 40;
        if (opcode == SCRIPT_BINARY) handler = parameter < 18 ? 22 + parameter : 43;
        uint16 operation = 0x323c;
        unsigned jump = 3;
        if (opcode == SCRIPT_SETRETURNVALUE || opcode == SCRIPT_STACK_REWIND ||
            opcode == SCRIPT_STACK_FORWARD) {
            handler = 42;
            operation = opcode == SCRIPT_SETRETURNVALUE ? 0x357c :
                        opcode == SCRIPT_STACK_REWIND ? 0x062a : 0x042a;
            if (opcode != SCRIPT_SETRETURNVALUE) parameter &= 255;
            jump = 4;
            assert(BETOH16(info.nativeCode[3]) ==
                   (opcode == SCRIPT_SETRETURNVALUE ? 10 : 13));
        } else if (opcode == SCRIPT_JUMP || opcode == SCRIPT_JUMP_NE) {
            uint16 destination = opcode == SCRIPT_JUMP ? parameter : parameter & 0x7fff;
            uint32 address = ((uint32)BETOH16(info.nativeCode[2]) << 16) |
                             BETOH16(info.nativeCode[3]);
            assert(address == (uint32)((uintptr_t)info.nativeCode + destination * 16u));
            operation = 0x207c;
            jump = 4;
        } else if (handler == 40 || handler == 41 || handler == 43) {
            assert(BETOH16(info.nativeCode[3]) == (0x7000 | opcode));
            jump = 4;
        }
        uint32 target = ((uint32)BETOH16(info.nativeCode[jump + 1]) << 16) |
                        BETOH16(info.nativeCode[jump + 2]);
        assert(BETOH16(info.nativeCode[0]) == (0x7e00 | length * 16));
        assert(BETOH16(info.nativeCode[1]) == operation);
        if (operation != 0x207c) assert(BETOH16(info.nativeCode[2]) == parameter);
        assert(BETOH16(info.nativeCode[jump]) == 0x4ef9);
        assert(target == Script_NativeHandlers[handler]);
        Script_ClearInfo(&info);
        info.start = words;
    }
    /* Classification follows actual function identity, not category or ID. */
    const ScriptFunction audited[] = {
        Script_General_Delay, Script_General_DelayRandom,
        Script_General_GetDistanceToTile, Script_General_GetDistanceToObject,
        Script_General_NoOperation, Script_Unit_GetInfo, Script_Unit_Rotate,
        Script_Unit_FindStructure, Script_Unit_Fire, Script_Unit_MoveToTarget, NULL
    };
    ScriptFunction testCallbacks[SCRIPT_FUNCTIONS_COUNT] = {0};
    info.functions = testCallbacks;
    for (unsigned callback = 0; callback < sizeof(audited) / sizeof(audited[0]); callback++) {
        for (unsigned id = 0; id < SCRIPT_FUNCTIONS_COUNT; id++) {
            testCallbacks[id] = audited[callback];
            for (unsigned extended = 0; extended < 2; extended++) {
                words[0] = HTOBE16((SCRIPT_FUNCTION << 8) |
                                  (extended ? 0x2000 : 0x4000 | id));
                words[1] = HTOBE16(0xab00 | id);
                assert(Script_CompileNative(&info));
                uint32 target = ((uint32)BETOH16(info.nativeCode[4]) << 16) |
                                BETOH16(info.nativeCode[5]);
                assert(target == Script_NativeHandlers[callback < 8 ? 45 : SCRIPT_FUNCTION]);
                assert(BETOH16(info.nativeCode[0]) == (extended ? 0x7e20 : 0x7e10));
                Script_ClearInfo(&info);
                info.start = words;
            }
            testCallbacks[id] = NULL;
        }
    }
    for (unsigned id = SCRIPT_FUNCTIONS_COUNT; id <= 255; id++) {
        words[0] = HTOBE16(0x2000 | (SCRIPT_FUNCTION << 8));
        words[1] = HTOBE16(0xab00 | id);
        assert(Script_CompileNative(&info));
        uint32 target = ((uint32)BETOH16(info.nativeCode[4]) << 16) |
                        BETOH16(info.nativeCode[5]);
        assert(target == Script_NativeHandlers[SCRIPT_FUNCTION]);
        Script_ClearInfo(&info);
        info.start = words;
    }
    info.functions = NULL;
    /* Each family against every following-word encoding, including flag
     * precedence, sign extension, PUSH2 and non-matching operations. */
    info.startCount = 6;
    for (unsigned family = 0; family < 9; family++) {
        unsigned opcode = family == 0 ? SCRIPT_STACK_REWIND :
                          family < 3 ? SCRIPT_PUSH_RETURN_OR_LOCATION : SCRIPT_BINARY;
        unsigned parameter = family == 0 ? 1 : family < 3 ? 0 : family - 1;
        for (unsigned format = 0; format < 3; format++) {
            unsigned length = format == 1 ? 2 : 1;
            unsigned firstParameter = format == 2 ? 0 : parameter;
            for (unsigned encoding = 0; encoding <= 0xffff; encoding++) {
                for (unsigned i = 0; i < 8; i++) words[i] = HTOBE16(0x4100);
                words[0] = HTOBE16((opcode << 8) |
                           (format == 0 ? 0x4000 | parameter : format == 1 ? 0x2000 : 0));
                if (format == 1) words[1] = HTOBE16(parameter);
                words[length] = HTOBE16(encoding);
                words[length + 1] = HTOBE16(0xffff);
                unsigned secondOpcode = (encoding >> 8) & 31;
                uint16 secondParameter = 0;
                if (encoding & 0x8000) {
                    secondOpcode = SCRIPT_JUMP;
                    secondParameter = encoding & 0x7fff;
                } else if (encoding & 0x4000) {
                    secondParameter = (int16)(int8)(encoding & 255);
                } else if (encoding & 0x2000) {
                    secondParameter = 0xffff;
                }
                unsigned expected = family == 0 ? 42 :
                                    family < 3 ? 2 : 22 + firstParameter;
                if (family == 0 && firstParameter == 1 &&
                    secondOpcode == SCRIPT_PUSH_RETURN_OR_LOCATION && secondParameter == 0) {
                    expected = 46;
                } else if (family < 3 && family != 0 &&
                           (secondOpcode == SCRIPT_PUSH || secondOpcode == SCRIPT_PUSH2)) {
                    expected = 47;
                } else if (family < 3 && family != 0 && secondOpcode == SCRIPT_JUMP_NE) {
                    expected = 48;
                } else if (family >= 3 && firstParameter >= 2 &&
                           secondOpcode == SCRIPT_JUMP_NE) {
                    expected = 49 + firstParameter - 2;
                }
                assert(Script_CompileNative(&info));
                assert(entry_target(info.nativeCode) == Script_NativeHandlers[expected]);
                assert(BETOH16(info.nativeCode[0]) == (0x7e00 | length * 16));
                Script_ClearInfo(&info);
                info.start = words;
            }
        }
    }
    /* A matching second opcode with a missing parameter is not fusible. */
    for (unsigned family = 0; family < 9; family++) {
        unsigned firstOpcode = family == 0 ? SCRIPT_STACK_REWIND :
                               family < 3 ? SCRIPT_PUSH_RETURN_OR_LOCATION : SCRIPT_BINARY;
        unsigned firstParameter = family == 0 ? 1 : family < 3 ? 0 : family - 1;
        unsigned secondOpcode = family == 0 ? SCRIPT_PUSH_RETURN_OR_LOCATION :
                                family == 1 ? SCRIPT_PUSH : SCRIPT_JUMP_NE;
        words[0] = HTOBE16(0x4000 | (firstOpcode << 8) | firstParameter);
        words[1] = HTOBE16(0x2000 | (secondOpcode << 8));
        info.startCount = 2;
        assert(Script_CompileNative(&info));
        assert(entry_target(info.nativeCode) ==
               Script_NativeHandlers[family == 0 ? 42 : family < 3 ? 2 : 22 + firstParameter]);
        assert(entry_target(info.nativeCode + 8) == Script_NativeHandlers[41]);
        Script_ClearInfo(&info);
        info.start = words;
    }
    /* The uint16 loop must terminate even at the largest DATA word count. */
    Script_ClearInfo(&info);
    info.isAllocated = 1;
    info.startCount = 0xffff;
    info.start = calloc(info.startCount, sizeof(*info.start));
    assert(info.start != NULL);
    info.start[0xfffe] = HTOBE16(0x2100);
    assert(Script_CompileNative(&info));
    assert(BETOH16(info.nativeCode[0xfffe * 8]) == 0x7e00);
    assert(BETOH16(info.nativeCode[0xfffe * 8 + 3]) == 0x7021);
    Script_ClearInfo(&info);

    offsets[0] = HTOBE16(0); offsets[1] = HTOBE16(2);
    data[0] = HTOBE16(0x2100); data[1] = HTOBE16(0xf123);
    data[2] = HTOBE16(0x41ff); data[3] = HTOBE16(0x8002);
    uint16 borrowed[32] = {0};
    for (unsigned owned = 0; owned < 2; owned++) {
        uint8 *buffer = owned ? NULL : (uint8 *)borrowed;
        for (unsigned cached = 0; cached < 2; cached++) {
            nativeST = cached != 0;
            for (unsigned reload = 0; reload < 3; reload++) {
                assert(Script_LoadFromFile("TEST.EMC", &info, callbacks, buffer) == 15);
                check_loaded(&info, cached != 0);
                assert(info.isAllocated == owned);
                if (!owned) {
                    assert(info.text == borrowed);
                    assert(info.offsets == borrowed + 2);
                    assert(info.start == borrowed + 4);
                }
            }
        }
        nativeST = true;
        failDecode = true;
        unsigned before = warnings;
        assert(Script_LoadFromFile("TEST.EMC", &info, callbacks, buffer) == 15);
        check_loaded(&info, false);
        assert(warnings == before + 1);
        failDecode = false;
        assert(Script_LoadFromFile("TEST.EMC", &info, callbacks, buffer) == 15);
        check_loaded(&info, true);
        /* Failure after a successful load must release the previous cache. */
        for (unsigned missing = 0; missing < 3; missing++) {
            exists = missing != 0;
            orderLength = missing == 1 ? 0 : sizeof(offsets);
            dataLength = missing == 2 ? 0 : sizeof(data);
            assert(Script_LoadFromFile("TEST.EMC", &info, callbacks, buffer) == 0);
            assert(info.nativeCode == NULL && info.start == NULL);
            assert(info.text == NULL && info.offsets == NULL);
            exists = true;
            orderLength = sizeof(offsets);
            dataLength = sizeof(data);
            assert(Script_LoadFromFile("TEST.EMC", &info, callbacks, buffer) == 15);
            check_loaded(&info, true);
        }
        Script_ClearInfo(&info);
        Script_ClearInfo(&info);
        assert(info.nativeCode == NULL && info.start == NULL);
    }
    Script_ClearInfo(NULL);
    assert(Script_LoadFromFile(NULL, &info, callbacks, NULL) == 0);
    assert(Script_LoadFromFile("TEST.EMC", NULL, callbacks, NULL) == 0);
    assert(opened == closed);
    return 0;
}
"""
        harness = harness.replace("/* HEADER */", str(ROOT / "src/script/script.h"))
        harness = harness.replace("/* ENDIAN */", str(ROOT / "src/os/endian.h"))
        harness = harness.replace("/* FOURCC */", str(ROOT / "include/multichar.h"))
        harness = harness.replace("/* HANDLERS */",
                                  ",".join(hex(0x100000 + i * 16) for i in range(57)))
        harness = harness.replace("/* PRODUCTION */", production)
        with tempfile.TemporaryDirectory(prefix="script-native-loader-") as directory:
            c_file = Path(directory) / "test.c"
            c_file.write_text(harness)
            compiler = shlex.split(os.environ.get("CC", "cc"))
            binary = Path(directory) / "test"
            subprocess.run([*compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
                            "-Werror", "-DTOS", str(c_file), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
