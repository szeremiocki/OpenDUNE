; Plain 68000 native EMC runner. A6 is authoritative between C boundaries.
; D2 = budget, D3 = stop-on-delay, D6 = DATA bytes, D7 = native step;
; A2 = engine, A3 = info, A4 = code base, A5 = code end, A6 = cursor.
	xdef	_Script_RunNative
	xdef	_Script_NativeHandlers
	xdef	_Script_NativeNext
	xref	_Script_RunNativeFallback
	xref	_Script_NativeError
	xref	_Script_NativePush
	xref	_Script_NativePop
	xref	_Script_NativePeek
	xref	_g_scriptCurrentUnit

; offsetof(Unit, targetAttack); script_native.c asserts the same value.
UNIT_TARGETATTACK equ 84

	text

; Opcode-pair statistics (build-time toggle). Must match
; SCRIPT_NATIVE_PAIR_STATS in script_native.c, which stores a per-entry code
; in word 7 and reads the counters. Counts sequential pairs only; jumps and
; their targets are not counted.
PAIRSTATS set 0
	ifne	PAIRSTATS
	xdef	_Script_NativePairStats
	endc
PAIRSTAT macro
	ifne	PAIRSTATS
	moveq	#0,d0
	move.w	14(a6),d0
	lsl.w	#7,d0
	move.w	14(a6,d7.w),d4
	and.w	#127,d4
	add.w	d4,d0
	lsl.l	#2,d0
	lea	_Script_NativePairStats,a0
	addq.l	#1,(a0,d0.l)
	endc
	endm

PUBLISH_PC macro
	move.l	a6,d0
	sub.l	a4,d0
	lsr.l	#3,d0
	add.l	4(a3),d0
	move.l	d0,2(a2)
	endm

PUBLISH_NEXT_PC macro
	; Never resurrect a script unloaded by an earlier stack error.
	tst.l	2(a2)
	beq	.done\@
	move.l	a6,d0
	add.l	d7,d0
	sub.l	a4,d0
	lsr.l	#3,d0
	add.l	4(a3),d0
	move.l	d0,2(a2)
.done\@:
	endm

; Lean dispatch (NativeLeanNext) skips the delay/unload/bounds checks, which
; only C callbacks and jumps can affect. A stack error calls C and may unload
; the script, so in LEAN regions it forces the next dispatch down the full path
; by parking the budget in d3's high word and setting d2 to 1 (d3 bit 8 = flag).
LEAN set 0
STASH_BUDGET macro
	ifne	LEAN
	btst	#8,d3
	bne	.stashed\@
	swap	d3
	move.w	d2,d3
	swap	d3
	bset	#8,d3
	moveq	#1,d2
.stashed\@:
	endc
	endm
NEXT macro
	ifne	LEAN
	bra	NativeLeanNext
	else
	bra	_Script_NativeNext
	endc
	endm

PUSH macro
	moveq	#0,d0
	move.b	13(a2),d0
	beq	.bad\@
	subq.b	#1,13(a2)
	subq.w	#1,d0
	add.w	d0,d0
	move.w	\1,24(a2,d0.w)
	bra	.end\@
.bad\@:
	PUBLISH_NEXT_PC
	move.l	d1,-(sp)
	moveq	#0,d0
	move.w	\1,d0
	move.l	d0,-(sp)
	move.l	a2,-(sp)
	jsr	_Script_NativePush
	addq.l	#8,sp
	move.l	(sp)+,d1
	STASH_BUDGET
.end\@:
	endm

POP macro
	moveq	#0,d0
	move.b	13(a2),d0
	cmp.b	#15,d0
	bcc	.bad\@
	addq.b	#1,13(a2)
	add.w	d0,d0
	move.w	24(a2,d0.w),\1
	bra	.end\@
.bad\@:
	PUBLISH_NEXT_PC
	move.l	d1,-(sp)
	move.l	a2,-(sp)
	jsr	_Script_NativePop
	addq.l	#4,sp
	move.l	(sp)+,d1
	move.w	d0,\1
	STASH_BUDGET
.end\@:
	endm

PEEK macro
	cmp.b	#16-\1,13(a2)
	bcc	.bad\@
	bra	.end\@
.bad\@:
	PUBLISH_NEXT_PC
	move.l	#\1,-(sp)
	move.l	a2,-(sp)
	jsr	_Script_NativePeek
	addq.l	#8,sp
	bra	NativeFailure
.end\@:
	endm

_Script_RunNative:
	movem.l	d2-d7/a2-a6,-(sp)
	move.l	48(sp),a2
	move.w	54(sp),d2
	moveq	#0,d3
	move.b	59(sp),d3
	cmpa.w	#0,a2
	beq	NativeFailure
	bra	NativeRebindCheck

_Script_NativeNext:
	PAIRSTAT
	adda.w	d7,a6
	subq.w	#1,d2
NativeCheck:
	tst.w	d2
	beq	NativeCursorSuccess
	tst.b	d3
	beq	NativeCursorFetch
	tst.w	(a2)
	bne	NativeCursorSuccess
NativeCursorFetch:
	tst.l	2(a2)
	beq	NativeFailure
	cmpa.l	a5,a6
	bcc	NativeCursorBounds
	jmp	(a6)

NativeLeanNext:
NativeNextOneWord:
NativeNextTwoWords:
	PAIRSTAT
	adda.w	d7,a6
	subq.w	#1,d2
	beq	NativeLeanZero
NativeLeanJump:
	jmp	(a6)
NativeLeanZero:
	btst	#8,d3
	beq	NativeCursorSuccess
	move.l	d3,d2
	swap	d2
	and.l	#$ff,d3
	subq.w	#1,d2
	bra	NativeCheck
NativeSentinel:
	bra	NativeCursorBounds

NativeBranchNext:
	subq.w	#1,d2
	bra	NativeCheck
NativeFetch:
	move.l	2(a2),a0
	cmpa.w	#0,a0
	beq	NativeFailure
	move.l	a0,d0
	sub.l	4(a3),d0
	cmp.l	d6,d0
	bcc	NativeBounds
	btst	#0,d0
	bne	NativeBounds
	lsl.l	#3,d0
	lea	(a4,d0.l),a6
	jmp	(a6)

NativeReenter:
	subq.w	#1,d2
NativeRebindCheck:
	tst.w	d2
	beq	NativeSuccess
	tst.b	d3
	beq	NativeRebind
	tst.w	(a2)
	bne	NativeSuccess
NativeRebind:
	; Only callbacks can replace/unload info or free/recompile its code.
	move.l	2(a2),a0
	cmpa.w	#0,a0
	beq	NativeFailure
	move.l	6(a2),a3
	cmpa.w	#0,a3
	beq	NativeFailure
	move.l	22(a3),a4
	cmpa.w	#0,a4
	beq	NativeFallback
	moveq	#0,d6
	move.w	14(a3),d6
	add.l	d6,d6
	move.l	d6,d0
	lsl.l	#3,d0
	lea	(a4,d0.l),a5
	bra	NativeFetch

NativeFallback:
	move.l	d3,-(sp)
	moveq	#0,d0
	move.w	d2,d0
	move.l	d0,-(sp)
	move.l	a2,-(sp)
	jsr	_Script_RunNativeFallback
	lea	12(sp),sp
	bra	NativeExit
NativeBounds:
	moveq	#32,d0
	moveq	#0,d1
	bra	NativeInvalidPublished
NativeCursorBounds:
	PUBLISH_PC
	bra	NativeBounds
NativeTruncated:
	moveq	#33,d0
	bra	NativeInvalid
NativeCursorSuccess:
	tst.l	2(a2)
	beq	NativeSuccess
	PUBLISH_PC
NativeSuccess:
	moveq	#1,d0
	bra	NativeExit
NativeFailure:
	moveq	#0,d0
NativeExit:
	movem.l	(sp)+,d2-d7/a2-a6
	rts

NativeInvalid:
	move.l	d0,-(sp)
	PUBLISH_NEXT_PC
	move.l	(sp)+,d0
NativeInvalidPublished:
	and.l	#$ffff,d1
	move.l	d1,-(sp)
	move.l	d0,-(sp)
	move.l	a2,-(sp)
	jsr	_Script_NativeError
	lea	12(sp),sp
	bra	NativeExit

LEAN set 1
NativeJump:
	move.l	a0,a6
	bra	NativeBranchNext
NativeSetReturn:
	move.w	d1,10(a2)
	NEXT
NativePushReturn:
	tst.w	d1
	beq	.pushReturn
	cmp.w	#1,d1
	bne	.invalid
	move.l	a6,d4
	add.l	d7,d4
	sub.l	a4,d4
	lsr.l	#4,d4
	addq.l	#1,d4
	PUSH	d4
	moveq	#0,d4
	move.b	12(a2),d4
	PUSH	d4
	move.b	13(a2),d0
	addq.b	#2,d0
	move.b	d0,12(a2)
	NEXT
.pushReturn:
	move.w	10(a2),d4
	PUSH	d4
	NEXT
.invalid:
	moveq	#2,d0
	bra	NativeInvalid
NativePush:
	PUSH	d1
	NEXT
NativePushVariable:
	and.l	#$ffff,d1
	add.l	d1,d1
	move.w	14(a2,d1.l),d4
	PUSH	d4
	NEXT

LOCAL_INDEX macro
	and.l	#$ffff,d1
	moveq	#0,d4
	move.b	12(a2),d4
	sub.l	d1,d4
	subq.l	#2,d4
	cmp.l	#15,d4
	bge	NativeStackBounds
	add.l	d4,d4
	endm
PARAMETER_INDEX macro
	and.l	#$ffff,d1
	moveq	#0,d4
	move.b	12(a2),d4
	add.l	d1,d4
	subq.l	#1,d4
	cmp.l	#15,d4
	bge	NativeStackBounds
	add.l	d4,d4
	endm

NativePushLocal:
	LOCAL_INDEX
	move.w	24(a2,d4.l),d4
	PUSH	d4
	NEXT
NativePushParameter:
	PARAMETER_INDEX
	move.w	24(a2,d4.l),d4
	PUSH	d4
	NEXT
NativeStackBounds:
	; Use the existing peek diagnostic without changing the stack pointer.
	PUBLISH_NEXT_PC
	move.l	#16,-(sp)
	move.l	a2,-(sp)
	jsr	_Script_NativePeek
	addq.l	#8,sp
	bra	NativeFailure
LEAN set 0
NativePopReturn:
	tst.w	d1
	beq	.popReturn
	cmp.w	#1,d1
	bne	.invalid
	PEEK	2
	POP	d4
	move.b	d4,12(a2)
	POP	d4
	and.l	#$ffff,d4
	lsl.l	#4,d4
	lea	(a4,d4.l),a6
	bra	NativeBranchNext
.popReturn:
	POP	d4
	move.w	d4,10(a2)
	NEXT
.invalid:
	moveq	#8,d0
	bra	NativeInvalid
LEAN set 1
NativePopVariable:
	and.l	#$ffff,d1
	add.l	d1,d1
	move.l	d1,d5
	POP	d4
	move.w	d4,14(a2,d5.l)
	NEXT
NativePopLocal:
	LOCAL_INDEX
	move.l	d4,d5
	POP	d4
	move.w	d4,24(a2,d5.l)
	NEXT
NativePopParameter:
	PARAMETER_INDEX
	move.l	d4,d5
	POP	d4
	move.w	d4,24(a2,d5.l)
	NEXT
NativeStackRewind:
	add.b	d1,13(a2)
	NEXT
NativeStackForward:
	sub.b	d1,13(a2)
	NEXT
CALL_FUNCTION macro
	PUBLISH_NEXT_PC
	and.l	#$ff,d1
	cmp.w	#64,d1
	bcc	.invalid\@
	move.l	d1,d4
	lsl.l	#2,d4
	move.l	16(a3),a1
	move.l	(a1,d4.l),a1
	cmpa.w	#0,a1
	beq	.invalid\@
	move.l	a2,-(sp)
	jsr	(a1)
	addq.l	#4,sp
	move.w	d0,10(a2)
	bra	\1
.invalid\@:
	moveq	#14,d0
	bra	NativeInvalid
	endm

LEAN set 0
NativeFunction:
	CALL_FUNCTION	NativeReenter
NativeFunctionFast:
	CALL_FUNCTION	_Script_NativeNext
NativeJumpNE:
	PEEK	1
	POP	d4
	tst.w	d4
	bne	_Script_NativeNext
	bra	NativeJump
NativeReturn:
	PEEK	2
	POP	d4
	move.w	d4,10(a2)
	POP	d4
	and.l	#$ffff,d4
	lsl.l	#4,d4
	lea	(a4,d4.l),a6
	clr.b	54(a2)
	bra	NativeBranchNext

LEAN set 1
UNARY macro
	POP	d4
	\1	d4
	PUSH	d4
	NEXT
	endm
NativeNot:
	POP	d4
	tst.w	d4
	seq	d4
	and.w	#1,d4
	PUSH	d4
	NEXT
NativeNeg:
	UNARY	neg.w
NativeComplement:
	UNARY	not.w

BINARY_LOAD macro
	POP	d5
	POP	d4
	endm
BINARY_STORE macro
	PUSH	d4
	NEXT
	endm
COMPARISON macro
	BINARY_LOAD
	cmp.w	d5,d4
	\1	d4
	and.w	#1,d4
	BINARY_STORE
	endm
BINARY_OP macro
	BINARY_LOAD
	\1	d5,d4
	BINARY_STORE
	endm

NativeAnd:
	BINARY_LOAD
	tst.w	d5
	sne	d5
	tst.w	d4
	sne	d4
	and.w	d5,d4
	and.w	#1,d4
	BINARY_STORE
NativeOr:
	BINARY_LOAD
	or.w	d5,d4
	sne	d4
	and.w	#1,d4
	BINARY_STORE
NativeEqual:
	COMPARISON	seq
NativeNotEqual:
	COMPARISON	sne
NativeLess:
	COMPARISON	slt
NativeLessEqual:
	COMPARISON	sle
NativeGreater:
	COMPARISON	sgt
NativeGreaterEqual:
	COMPARISON	sge
NativeAdd:
	BINARY_OP	add.w
NativeSubtract:
	BINARY_OP	sub.w
NativeMultiply:
	BINARY_OP	muls.w
NativeDivide:
	BINARY_LOAD
	ext.l	d4
	divs.w	d5,d4
	BINARY_STORE
NativeShiftRight:
	BINARY_LOAD
	ext.l	d4
	asr.l	d5,d4
	BINARY_STORE
NativeShiftLeft:
	BINARY_LOAD
	ext.l	d4
	lsl.l	d5,d4
	BINARY_STORE
NativeBitAnd:
	BINARY_OP	and.w
NativeBitOr:
	BINARY_OP	or.w
NativeModulo:
	BINARY_LOAD
	ext.l	d4
	divs.w	d5,d4
	bvs	.overflow
	swap	d4
	bra	.store
.overflow:
	moveq	#0,d4
.store:
	BINARY_STORE
NativeBitXor:
	BINARY_OP	eor.w
NativeBinaryInvalid:
	BINARY_LOAD
	moveq	#17,d0
	bra	NativeInvalid

LEAN set 0

NativeFuseRewindReturn:
	cmp.w	#2,d2
	bcs	NativeStackRewind
	moveq	#0,d0
	move.b	13(a2),d0
	cmp.b	#15,d0
	bcc	NativeStackRewind
	add.w	d0,d0
	move.w	10(a2),24(a2,d0.w)
	bra	NativeFusedNext

NativeFuseReturnImmediate:
	cmp.w	#2,d2
	bcs	NativePushReturn
	moveq	#0,d0
	move.b	13(a2),d0
	cmp.b	#2,d0
	bcs	NativePushReturn
	cmp.b	#15,d0
	bhi	NativePushReturn
	subq.b	#2,13(a2)
	subq.w	#1,d0
	add.w	d0,d0
	move.w	10(a2),24(a2,d0.w)
	lea	(a6,d7.w),a0
	move.w	4(a0),22(a2,d0.w)
	bra	NativeFusedNext

NativeFuseReturnJump:
	cmp.w	#2,d2
	bcs	NativePushReturn
	moveq	#0,d0
	move.b	13(a2),d0
	beq	NativePushReturn
	cmp.b	#15,d0
	bhi	NativePushReturn
	subq.w	#1,d0
	add.w	d0,d0
	move.w	10(a2),d4
	move.w	d4,24(a2,d0.w)
	tst.w	d4
	beq	NativeFusedJump
	bra	NativeFusedNext

FUSED_COMPARISON macro
	cmp.w	#2,d2
	bcs	\2
	moveq	#0,d0
	move.b	13(a2),d0
	cmp.b	#13,d0
	bhi	\2
	addq.b	#2,13(a2)
	add.w	d0,d0
	move.w	24(a2,d0.w),d5
	move.w	26(a2,d0.w),d4
	cmp.w	d5,d4
	\1	d4
	and.w	#1,d4
	; The comparison's push remains visible in the persistent VM stack.
	move.w	d4,26(a2,d0.w)
	tst.w	d4
	beq	NativeFusedJump
	bra	NativeFusedNext
	endm

NativeFuseEqualJump:
	FUSED_COMPARISON	seq,NativeEqual
NativeFuseNotEqualJump:
	FUSED_COMPARISON	sne,NativeNotEqual
NativeFuseLessJump:
	FUSED_COMPARISON	slt,NativeLess
NativeFuseLessEqualJump:
	FUSED_COMPARISON	sle,NativeLessEqual
NativeFuseGreaterJump:
	FUSED_COMPARISON	sgt,NativeGreater
NativeFuseGreaterEqualJump:
	FUSED_COMPARISON	sge,NativeGreaterEqual

; PUSH #5 + Script_Unit_GetInfo: GetInfo(5) is the unit's targetAttack. The push
; stays visible on the VM stack; the callback itself cannot change the PC or
; script, so no PC is published. Any unusual state takes the plain PUSH path.
NativeFuseTargetAttack:
	cmp.w	#2,d2
	bcs	NativePush
	move.l	_g_scriptCurrentUnit,a0
	cmpa.w	#0,a0
	beq	NativePush
	moveq	#0,d0
	move.b	13(a2),d0
	beq	NativePush
	cmp.b	#15,d0
	bhi	NativePush
	subq.b	#1,13(a2)
	subq.w	#1,d0
	add.w	d0,d0
	move.w	d1,24(a2,d0.w)
	move.w	UNIT_TARGETATTACK(a0),d4
	move.w	d4,10(a2)
	bra	NativeFusedNext

NativeFusedNext:
	adda.w	d7,a6
	moveq	#0,d7
	move.b	1(a6),d7
	subq.w	#1,d2
	bra	_Script_NativeNext
NativeFusedJump:
	adda.w	d7,a6
	move.l	4(a6),a6
	subq.w	#1,d2
	bra	NativeBranchNext

	data
	even
_Script_NativeHandlers:
	dc.l	NativeJump,NativeSetReturn,NativePushReturn,NativePush,NativePush
	dc.l	NativePushVariable,NativePushLocal,NativePushParameter,NativePopReturn
	dc.l	NativePopVariable,NativePopLocal,NativePopParameter
	dc.l	NativeStackRewind,NativeStackForward,NativeFunction,NativeJumpNE
	dc.l	NativeInvalid,NativeInvalid,NativeReturn
	dc.l	NativeNot,NativeNeg,NativeComplement
	dc.l	NativeAnd,NativeOr,NativeEqual,NativeNotEqual,NativeLess,NativeLessEqual
	dc.l	NativeGreater,NativeGreaterEqual,NativeAdd,NativeSubtract,NativeMultiply
	dc.l	NativeDivide,NativeShiftRight,NativeShiftLeft,NativeBitAnd,NativeBitOr
	dc.l	NativeModulo,NativeBitXor,NativeInvalid,NativeTruncated,NativeNextOneWord
	dc.l	NativeBinaryInvalid
	dc.l	NativeNextTwoWords
	dc.l	NativeFunctionFast
	dc.l	NativeFuseRewindReturn,NativeFuseReturnImmediate,NativeFuseReturnJump
	dc.l	NativeFuseEqualJump,NativeFuseNotEqualJump,NativeFuseLessJump
	dc.l	NativeFuseLessEqualJump,NativeFuseGreaterJump,NativeFuseGreaterEqualJump
	dc.l	NativeSentinel
	dc.l	NativeFuseTargetAttack

	ifne	PAIRSTATS
	bss
	even
_Script_NativePairStats:
	ds.l	128*128
	endc
