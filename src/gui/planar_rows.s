; vim: set tabstop=8 shiftwidth=8 noexpandtab:
	xdef	_Planar_FillRows_asm	;export symbol
	;code

; prototype:
; void Planar_FillRows_asm(uint16 *dst, const uint16 *pattern, long strideBytes, long rows, long groups);
;
; Stores `rows` rows of `groups` prebuilt planar groups (4 words each, contiguous in
; `pattern`) at `dst`, advancing dst by strideBytes per row. Write-only.
;
; dst and pattern MUST be word-aligned (all the 68000 requires for MOVEM.L/MOVE.L).
; 1..5 groups keep the whole pattern in registers: one MOVEM.L store per row.
; More groups use a long-pair copy loop. rows <= 0 or groups <= 0 do nothing.

_Planar_FillRows_asm:
	movem.l	d2-d7/a2-a5,-(sp)	; 10 regs = 40 bytes, +4 return address
	move.l	44(sp),a0		; dst
	move.l	48(sp),a1		; pattern
	move.l	52(sp),a3		; stride in bytes
	move.l	56(sp),d1		; rows
	move.l	60(sp),d0		; groups

	subq.l	#1,d1			; bias rows for DBRA
	bmi	.done
	tst.l	d0
	ble	.done
	cmp.l	#5,d0
	bgt	.generic
	subq.l	#1,d0
	beq.s	.g1
	subq.l	#1,d0
	beq.s	.g2
	subq.l	#1,d0
	beq.s	.g3
	subq.l	#1,d0
	beq.s	.g4

.g5:	movem.l	(a1),d0/d2-d7/a2/a4/a5
.l5:	movem.l	d0/d2-d7/a2/a4/a5,(a0)
	add.l	a3,a0
	dbra	d1,.l5
	bra	.done

.g4:	movem.l	(a1),d0/d2-d7/a2
.l4:	movem.l	d0/d2-d7/a2,(a0)
	add.l	a3,a0
	dbra	d1,.l4
	bra.s	.done

.g3:	movem.l	(a1),d2-d7
.l3:	movem.l	d2-d7,(a0)
	add.l	a3,a0
	dbra	d1,.l3
	bra.s	.done

.g2:	movem.l	(a1),d2-d5
.l2:	movem.l	d2-d5,(a0)
	add.l	a3,a0
	dbra	d1,.l2
	bra.s	.done

.g1:	movem.l	(a1),d2-d3
.l1:	movem.l	d2-d3,(a0)
	add.l	a3,a0
	dbra	d1,.l1
	bra.s	.done

.generic:
	subq.l	#1,d0			; groups - 1 for DBRA
.grow:
	move.l	a0,a4
	move.l	a1,a2
	move.w	d0,d2
.gg:	move.l	(a2)+,(a4)+
	move.l	(a2)+,(a4)+
	dbra	d2,.gg
	add.l	a3,a0
	dbra	d1,.grow

.done:
	movem.l	(sp)+,d2-d7/a2-a5
	rts
