; vim: set tabstop=8 shiftwidth=8 noexpandtab:
	xdef	_GFX_CopyRows_asm	;export symbol
	;code

; prototype:
; void GFX_CopyRows_asm(void *dst, const void *src, long width, long height, long stride);
;
; Copies `height` rows of `width` bytes, advancing both pointers by `stride`
; after each row. Ascending copy only -- the caller must guarantee that the
; regions do not overlap in a way that needs a descending copy.
;
; Both pointers MUST be long-aligned; the caller guarantees this (68000
; bus-errors on a word/long access to an odd address).
;
; Replaces a GCC-generated loop that cost 10.0 cycles/byte: it emitted one
; MOVE.L plus a CMP.L, a BNE and a dead MOVE.L per 4 bytes, so half the loop
; was overhead. Unrolling by 8 and using DBRA amortises the loop control over
; 32 bytes: 8*20 + 10 = 170 cycles per 32 bytes = 5.31 cycles/byte.

_GFX_CopyRows_asm:
	movem.l	d2-d7/a2-a3,-(sp)	; 8 regs = 32 bytes, +4 return address
	move.l	36(sp),a0		; dst
	move.l	40(sp),a1		; src
	move.l	44(sp),d0		; width
	move.l	48(sp),d1		; height
	move.l	52(sp),d2		; stride

	tst.l	d1
	ble	.done
	tst.l	d0
	ble	.done

	move.l	d0,d3
	lsr.l	#2,d3			; d3 = whole longs in a row
	move.l	d0,d4
	and.l	#3,d4			; d4 = leftover bytes (0..3)
	move.l	d3,d5
	lsr.l	#3,d5			; d5 = 32-byte blocks
	move.l	d3,d6
	and.l	#7,d6			; d6 = leftover longs (0..7)

	subq.l	#1,d1			; bias height for DBRA

.rowloop:
	move.l	a0,a2			; working copies, row bases stay in a0/a1
	move.l	a1,a3

	move.l	d5,d7
	subq.l	#1,d7
	bmi.s	.remlongs		; fewer than 32 bytes in this row
.blk:
	move.l	(a3)+,(a2)+
	move.l	(a3)+,(a2)+
	move.l	(a3)+,(a2)+
	move.l	(a3)+,(a2)+
	move.l	(a3)+,(a2)+
	move.l	(a3)+,(a2)+
	move.l	(a3)+,(a2)+
	move.l	(a3)+,(a2)+
	dbra	d7,.blk

.remlongs:
	move.l	d6,d7
	subq.l	#1,d7
	bmi.s	.restbytes
.rl:
	move.l	(a3)+,(a2)+
	dbra	d7,.rl

.restbytes:
	move.l	d4,d7
	subq.l	#1,d7
	bmi.s	.nextrow
.rb:
	move.b	(a3)+,(a2)+
	dbra	d7,.rb

.nextrow:
	add.l	d2,a0
	add.l	d2,a1
	dbra	d1,.rowloop

.done:
	movem.l	(sp)+,d2-d7/a2-a3
	rts
