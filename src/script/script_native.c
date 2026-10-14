/** @file src/script/script_native.c Load-time 68000 EMC compilation. */

#include <stddef.h>
#include <stdlib.h>
#include "types.h"
#include "../os/endian.h"
#include "script.h"

extern const uint32 Script_NativeHandlers[];

/* The assembly uses the mint ABI, including two-byte structure alignment. */
typedef char NativeEngineLayout[
	(sizeof(void *) == 4 && offsetof(ScriptEngine, script) == 2 &&
	 offsetof(ScriptEngine, scriptInfo) == 6 && offsetof(ScriptEngine, returnValue) == 10 &&
	 offsetof(ScriptEngine, stackPointer) == 13 && offsetof(ScriptEngine, variables) == 14 &&
	 offsetof(ScriptEngine, stack) == 24 && offsetof(ScriptEngine, isSubroutine) == 54) ? 1 : -1];
typedef char NativeInfoLayout[
	(offsetof(ScriptInfo, start) == 4 && offsetof(ScriptInfo, startCount) == 14 &&
	 offsetof(ScriptInfo, functions) == 16 && offsetof(ScriptInfo, nativeCode) == 22) ? 1 : -1];

bool Script_CompileNative(ScriptInfo *scriptInfo)
{
	uint16 i;
	uint16 *code;

	if (scriptInfo->startCount == 0) return false;
	code = calloc(scriptInfo->startCount, 16);
	if (code == NULL) return false;

	/* Every DATA word is an entry, including words used as operands. */
	for (i = 0; i < scriptInfo->startCount; i++) {
		uint16 current = BETOH16(scriptInfo->start[i]);
		uint16 parameter = 0;
		uint16 opcode = (current >> 8) & 0x1F;
		uint16 words = 1;
		uint16 handler;
		uint32 target;
		uint16 *entry = code + (size_t)i * 8;

		if ((current & 0x8000) != 0) {
			opcode = SCRIPT_JUMP;
			parameter = current & 0x7FFF;
		} else if ((current & 0x4000) != 0) {
			parameter = (int16)(int8)(current & 0xFF);
		} else if ((current & 0x2000) != 0) {
			if (i + 1 >= scriptInfo->startCount) {
				opcode = 33;
				words = 0;
			} else {
				parameter = BETOH16(scriptInfo->start[i + 1]);
				words = 2;
			}
		}

		handler = opcode <= SCRIPT_RETURN ? opcode : 40;
		if ((opcode == SCRIPT_PUSH_RETURN_OR_LOCATION ||
		     opcode == SCRIPT_POP_RETURN_OR_LOCATION) && parameter > 1) handler = 40;
		if (opcode == SCRIPT_UNARY) handler = parameter < 3 ? 19 + parameter : 40;
		if (opcode == SCRIPT_BINARY) handler = parameter < 18 ? 22 + parameter : 43;
		if (opcode == 33) handler = 41;
		target = Script_NativeHandlers[handler];

		entry[0] = HTOBE16(words == 0 ? 0x4E71 : words == 1 ? 0x54AA : 0x58AA);
		entry[1] = HTOBE16(words == 0 ? 0x4E71 : 2);
		entry[2] = HTOBE16(0x323C);          /* move.w #parameter,d1 */
		entry[3] = HTOBE16(parameter);
		entry[4] = HTOBE16(handler < 40 ? 0x7E00 | words * 16 : 0x7000 | opcode);
		entry[5] = HTOBE16(0x4EF9);          /* jmp handler */
		entry[6] = HTOBE16(target >> 16);
		entry[7] = HTOBE16(target);

		if (opcode == SCRIPT_SETRETURNVALUE ||
		    opcode == SCRIPT_STACK_REWIND || opcode == SCRIPT_STACK_FORWARD) {
			target = Script_NativeHandlers[words == 1 ? 42 : 44];
			entry[2] = HTOBE16(opcode == SCRIPT_SETRETURNVALUE ? 0x357C :
			                  opcode == SCRIPT_STACK_REWIND ? 0x062A : 0x042A);
			entry[3] = HTOBE16(opcode == SCRIPT_SETRETURNVALUE ? parameter : parameter & 0xFF);
			entry[4] = HTOBE16(opcode == SCRIPT_SETRETURNVALUE ? 10 : 13);
			entry[6] = HTOBE16(target >> 16);
			entry[7] = HTOBE16(target);
		}
	}
	scriptInfo->nativeCode = code;
	return true;
}

void Script_NativePush(ScriptEngine *script, uint16 value)
{
	STACK_PUSH(value);
}

uint16 Script_NativePop(ScriptEngine *script)
{
	return STACK_POP();
}

uint16 Script_NativePeek(ScriptEngine *script, int position)
{
	return STACK_PEEK(position);
}
