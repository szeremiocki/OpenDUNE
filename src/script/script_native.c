/** @file src/script/script_native.c Load-time 68000 EMC compilation. */

#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include "types.h"
#include "../os/endian.h"
#include "script.h"
#include "../unit.h"

extern const uint32 Script_NativeHandlers[];

#ifdef SCRIPT_NATIVE_PAIR_STATS
#include "../os/error.h"
extern uint32 Script_NativePairStats[128 * 128];
#endif

/* The assembly uses the mint ABI, including two-byte structure alignment. */
typedef char NativeEngineLayout[
	(sizeof(void *) == 4 && offsetof(ScriptEngine, script) == 2 &&
	 offsetof(ScriptEngine, scriptInfo) == 6 && offsetof(ScriptEngine, returnValue) == 10 &&
	 offsetof(ScriptEngine, stackPointer) == 13 && offsetof(ScriptEngine, variables) == 14 &&
	 offsetof(ScriptEngine, stack) == 24 && offsetof(ScriptEngine, isSubroutine) == 54) ? 1 : -1];
typedef char NativeUnitLayout[offsetof(Unit, targetAttack) == 84 ? 1 : -1];
typedef char NativeInfoLayout[
	(offsetof(ScriptInfo, start) == 4 && offsetof(ScriptInfo, startCount) == 14 &&
	 offsetof(ScriptInfo, functions) == 16 && offsetof(ScriptInfo, nativeCode) == 22) ? 1 : -1];

static bool Script_NativePreservesContext(ScriptFunction callback)
{
	/* Audit callees too: no PC changes (except stack-error unloading), script
	 * replacement or native-code lifetime changes. Unknown callbacks rebind. */
	return callback == Script_General_Delay ||
	       callback == Script_General_DelayRandom ||
	       callback == Script_General_GetDistanceToTile ||
	       callback == Script_General_GetDistanceToObject ||
	       callback == Script_General_NoOperation ||
	       callback == Script_Unit_GetInfo ||
	       callback == Script_Unit_Rotate ||
	       callback == Script_Unit_FindStructure;
}

bool Script_CompileNative(ScriptInfo *scriptInfo)
{
	uint16 i;
	uint16 *code;

	if (scriptInfo->startCount == 0) return false;
	/* One extra entry past the last opcode traps fall-through for the lean dispatch. */
	code = calloc((size_t)scriptInfo->startCount + 1, 16);
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
		if (opcode == SCRIPT_FUNCTION && scriptInfo->functions != NULL &&
		    (parameter & 0xFF) < SCRIPT_FUNCTIONS_COUNT &&
		    Script_NativePreservesContext(scriptInfo->functions[parameter & 0xFF])) {
			target = Script_NativeHandlers[45];
		}

		entry[0] = HTOBE16(0x7E00 | words * 16); /* moveq #step,d7 */
		entry[7] = HTOBE16(0x4E71);
		if (opcode == SCRIPT_SETRETURNVALUE ||
		    opcode == SCRIPT_STACK_REWIND || opcode == SCRIPT_STACK_FORWARD) {
			target = Script_NativeHandlers[42];
			entry[1] = HTOBE16(opcode == SCRIPT_SETRETURNVALUE ? 0x357C :
			                  opcode == SCRIPT_STACK_REWIND ? 0x062A : 0x042A);
			entry[2] = HTOBE16(opcode == SCRIPT_SETRETURNVALUE ? parameter : parameter & 0xFF);
			entry[3] = HTOBE16(opcode == SCRIPT_SETRETURNVALUE ? 10 : 13);
		} else if (opcode == SCRIPT_JUMP || opcode == SCRIPT_JUMP_NE) {
			uint16 destination = opcode == SCRIPT_JUMP ? parameter : parameter & 0x7FFF;
			uint32 address = (uint32)((uintptr_t)code + (uint32)destination * 16);

			/* The address is not dereferenced until the next-opcode check. */
			entry[1] = HTOBE16(0x207C); /* movea.l #destination,a0 */
			entry[2] = HTOBE16(address >> 16);
			entry[3] = HTOBE16(address);
		} else {
			entry[1] = HTOBE16(0x323C); /* move.w #parameter,d1 */
			entry[2] = HTOBE16(parameter);
			if (handler == 40 || handler == 41 || handler == 43) {
				entry[3] = HTOBE16(0x7000 | opcode);
			} else {
				entry[3] = HTOBE16(0x4EF9);
				entry[4] = HTOBE16(target >> 16);
				entry[5] = HTOBE16(target);
				entry[6] = HTOBE16(0x4E71);
				continue;
			}
		}
		entry[4] = HTOBE16(0x4EF9); /* jmp handler */
		entry[5] = HTOBE16(target >> 16);
		entry[6] = HTOBE16(target);
	}

	/* Match emitted entries so operand words and all parameter encodings
	 * retain exactly the same decoding as ordinary execution. */
	for (i = 0; i < scriptInfo->startCount; i++) {
		uint16 *entry = code + (size_t)i * 8;
		uint16 words = (BETOH16(entry[0]) & 0xFF) / 16;
		uint16 *next;
		uint16 fusion = 0;
		uint32 firstTarget;
		uint32 nextTarget;
		bool rewind = BETOH16(entry[1]) == 0x062A && BETOH16(entry[2]) == 1;
		bool normal = BETOH16(entry[1]) == 0x323C && BETOH16(entry[3]) == 0x4EF9;

		if ((!rewind && !normal) || words == 0 || i + words >= scriptInfo->startCount) continue;
		next = code + (size_t)(i + words) * 8;
		firstTarget = normal ? ((uint32)BETOH16(entry[4]) << 16) | BETOH16(entry[5]) : 0;
		if (BETOH16(next[1]) == 0x323C && BETOH16(next[3]) == 0x4EF9) {
			nextTarget = ((uint32)BETOH16(next[4]) << 16) | BETOH16(next[5]);
			if (rewind && nextTarget == Script_NativeHandlers[2] && BETOH16(next[2]) == 0) {
				fusion = 46;
			} else if (normal && firstTarget == Script_NativeHandlers[2] &&
			           BETOH16(entry[2]) == 0 &&
			           (nextTarget == Script_NativeHandlers[SCRIPT_PUSH] ||
			            nextTarget == Script_NativeHandlers[SCRIPT_PUSH2])) {
				fusion = 47;
			} else if (normal && BETOH16(entry[2]) == 5 &&
			           (firstTarget == Script_NativeHandlers[SCRIPT_PUSH] ||
			            firstTarget == Script_NativeHandlers[SCRIPT_PUSH2]) &&
			           (nextTarget == Script_NativeHandlers[14] || nextTarget == Script_NativeHandlers[45]) &&
			           scriptInfo->functions != NULL && (BETOH16(next[2]) & 0xFF) < SCRIPT_FUNCTIONS_COUNT &&
			           scriptInfo->functions[BETOH16(next[2]) & 0xFF] == Script_Unit_GetInfo) {
				fusion = 56;
			}
		} else if (normal && BETOH16(next[1]) == 0x207C) {
			nextTarget = ((uint32)BETOH16(next[5]) << 16) | BETOH16(next[6]);
			if (nextTarget == Script_NativeHandlers[SCRIPT_JUMP_NE]) {
				uint16 parameter = BETOH16(entry[2]);

				if (firstTarget == Script_NativeHandlers[2] && parameter == 0) {
					fusion = 48;
				} else if (parameter >= 2 && parameter <= 7 &&
				           firstTarget == Script_NativeHandlers[22 + parameter]) {
					fusion = 49 + parameter - 2;
				}
			}
		}
		if (fusion != 0) {
			uint32 target = Script_NativeHandlers[fusion];

			entry[1] = HTOBE16(0x323C);
			entry[3] = HTOBE16(0x4EF9);
			entry[4] = HTOBE16(target >> 16);
			entry[5] = HTOBE16(target);
			entry[6] = HTOBE16(0x4E71);
		}
	}
	{
		uint16 *entry = code + (size_t)scriptInfo->startCount * 8;
		uint32 target = Script_NativeHandlers[55];

		entry[0] = HTOBE16(0x7E00);
		entry[1] = HTOBE16(0x4EF9);
		entry[2] = HTOBE16(target >> 16);
		entry[3] = HTOBE16(target);
	}
#ifdef SCRIPT_NATIVE_PAIR_STATS
	/* Word 7 (never executed) holds a code: handler + 1, or 64 + callback index. */
	for (i = 0; i < scriptInfo->startCount; i++) {
		uint16 *entry = code + (size_t)i * 8;
		uint32 target;
		uint16 h;
		uint16 callback = BETOH16(entry[2]) & 63;

		if (BETOH16(entry[3]) == 0x4EF9) target = ((uint32)BETOH16(entry[4]) << 16) | BETOH16(entry[5]);
		else if (BETOH16(entry[4]) == 0x4EF9) target = ((uint32)BETOH16(entry[5]) << 16) | BETOH16(entry[6]);
		else continue;
		for (h = 0; h < 57 && Script_NativeHandlers[h] != target; h++) {}
		if (h >= 57) continue;
		entry[7] = HTOBE16((h == 14 || h == 45) ? 64 + callback : h + 1);
	}
#endif
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

#ifdef SCRIPT_NATIVE_PAIR_STATS
static const char *Script_NativeCodeName(uint16 code, char *buffer)
{
	static const char *const names[57] = {
		"JUMP", "SETRET", "PUSHRET", "PUSH", "PUSH2", "PUSHVAR", "PUSHLOC", "PUSHPAR",
		"POPRET", "POPVAR", "POPLOC", "POPPAR", "REWIND", "FORWARD", "FUNC", "JUMPNE",
		"INV", "INV", "RETURN", "NOT", "NEG", "COMPL", "AND", "OR", "EQ", "NE", "LT",
		"LE", "GT", "GE", "ADD", "SUB", "MUL", "DIV", "SHR", "SHL", "BAND", "BOR",
		"MOD", "XOR", "INV", "TRUNC", "NEXT1", "BININV", "NEXT2", "FUNCFAST",
		"F_REWRET", "F_RETIMM", "F_RETJMP", "F_EQJ", "F_NEJ", "F_LTJ", "F_LEJ",
		"F_GTJ", "F_GEJ", "SENTINEL", "F_TGT"
	};
	if (code == 0) {
		buffer[0] = '-'; buffer[1] = 0;
		return buffer;
	}
	if (code >= 64) {
		/* Function callback index */
		static const char hex[] = "0123456789ABCDEF";
		buffer[0] = 'C'; buffer[1] = 'A'; buffer[2] = 'L'; buffer[3] = 'L';
		buffer[4] = hex[(code - 64) >> 4]; buffer[5] = hex[(code - 64) & 15]; buffer[6] = 0;
		return buffer;
	}
	return names[code - 1];
}

void Script_NativePairStatsDump(void)
{
	enum { TOP = 40 };
	uint32 topCount[TOP];
	uint16 topIndex[TOP];
	uint32 total = 0;
	uint16 i, k, shown = 0;

	for (k = 0; k < TOP; k++) { topCount[k] = 0; topIndex[k] = 0; }
	for (i = 0; i < 128 * 128; i++) {
		uint32 c = Script_NativePairStats[i];
		if (c == 0) continue;
		total += c;
		if (c <= topCount[TOP - 1]) continue;
		for (k = TOP - 1; k > 0 && topCount[k - 1] < c; k--) {
			topCount[k] = topCount[k - 1];
			topIndex[k] = topIndex[k - 1];
		}
		topCount[k] = c;
		topIndex[k] = i;
	}
	Warning("NATIVEPAIRS total=%lu\n", (unsigned long)total);
	for (k = 0; k < TOP && topCount[k] != 0; k++) {
		char a[8], b[8];
		Warning("NATIVEPAIR %-9s -> %-9s %lu\n",
			Script_NativeCodeName(topIndex[k] >> 7, a),
			Script_NativeCodeName(topIndex[k] & 127, b), (unsigned long)topCount[k]);
		shown++;
	}
	(void)shown;
}

void Script_NativePairStatsPoll(uint32 now)
{
	static uint32 s_next;
	static bool s_registered;

	if (!s_registered) {
		s_registered = true;
		atexit(Script_NativePairStatsDump);
	}
	if (now < s_next) return;
	s_next = now + 3600; /* every minute of game time */
	Script_NativePairStatsDump();
}
#endif
