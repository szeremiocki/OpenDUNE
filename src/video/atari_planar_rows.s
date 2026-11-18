; vim: set tabstop=8 shiftwidth=8 noexpandtab:
	xdef	_Planar_DrawBorder	;export symbol
	;code

; prototype (C ABI; 16-bit arguments sit in the low word of a 4-byte slot):
; void Planar_DrawBorder(uint16 *dst, uint16 stride, uint16 x, uint16 width, uint16 height,
;                        const uint16 groups[16]);
;
; See atari_planar.h for the contract. Each row is  left group | middle groups | right group  (one group
; when the rectangle fits in a single 16-pixel group). Per plane a group is
;   (margin & ~span) | the class masks anded with that class group's plane word
; with, for the three row types (fill, bottom/right, top/left, corner),
;   top:      (span & ~edgeR) top/left, edgeR corner
;   interior: (span & ~(edgeL | edgeR)) fill, edgeL top/left, edgeR bottom/right
;   bottom:   (span & ~edgeL) bottom/right, edgeL corner
; Each row type samples its own first row (the margin repeats vertically over the rectangle), builds
; the left and right groups in registers (the middle groups are the plain class group) and writes the
; rows straight to the screen, one MOVEM per row for up to four groups.
; Two planes are processed per longword: masks are replicated into both halves and anded with the
; plane words of the class groups (fill 0, bottom/right 8, top/left 16, corner 24 bytes into groups[],
; kept in a2). Word alignment of dst is all the 68000 needs.

v_sl	equ	-4		; left group span, replicated in both halves
v_ell	equ	-8		; left group left edge
v_erl	equ	-12		; left group right edge (only when the rectangle has one group)
v_sr	equ	-16		; right group span
v_err	equ	-20		; right group right edge
v_count	equ	-24		; groups
v_first	equ	-28		; dst + first group
v_strideb	equ	-32		; stride in bytes
v_roff	equ	-36		; byte offset of the right group

REP	macro			; \1 = low word replicated into both halves, stored at \3(a6); \2 scratch
	move.w	\1,\2
	swap	\1
	move.w	\2,\1
	move.l	\1,\3(a6)
	endm

MARGIN	macro			; d\3:d\4 = the two margin longs at (\1) outside the span \2(a6); d7 scratch
	move.l	\2(a6),d7
	not.l	d7
	move.l	(\1),\3
	and.l	d7,\3
	move.l	4(\1),\4
	and.l	d7,\4
	endm

TERM	macro			; \2:\3 |= \1 & the plane words \4(a2); d6 scratch
	move.l	\1,d6
	and.l	\4(a2),d6
	or.l	d6,\2
	move.l	\1,d6
	and.l	\4+4(a2),d6
	or.l	d6,\3
	endm

_Planar_DrawBorder:
	link	a6,#-36
	movem.l	d2-d7/a2-a5,-(sp)
	moveq	#0,d0
	move.w	14(a6),d0
	add.l	d0,d0
	move.l	d0,v_strideb(a6)
	moveq	#0,d4
	move.w	18(a6),d4		; x
	moveq	#0,d5
	move.w	22(a6),d5
	add.l	d4,d5
	subq.l	#1,d5			; x1
	move.l	d4,d2
	lsr.l	#4,d2			; first group
	move.l	d5,d3
	lsr.l	#4,d3
	sub.l	d2,d3
	addq.l	#1,d3			; group count
	move.l	d3,v_count(a6)
	lsl.l	#3,d2
	add.l	8(a6),d2
	move.l	d2,v_first(a6)

	moveq	#15,d6
	and.w	d4,d6			; a = x & 15
	moveq	#15,d7
	and.w	d5,d7			; b = x1 & 15
	move.l	#$8000,d1
	lsr.l	d6,d1			; edgeL
	move.l	#$ffff,d0
	lsr.l	d6,d0			; span = $ffff >> a
	moveq	#0,d2			; edgeR
	cmp.l	#1,d3
	bne.s	.two
	move.l	#$8000,d2
	lsr.l	d7,d2			; one group: edgeR = $8000 >> b
	moveq	#15,d6
	sub.w	d7,d6
	move.l	#$ffff,d3
	lsl.l	d6,d3
	and.w	d3,d0			; span &= $ffff << (15 - b)
	bra.s	.left
.two:	move.l	#$8000,d3
	lsr.l	d7,d3			; right group: edgeR
	moveq	#15,d6
	sub.w	d7,d6
	move.l	#$ffff,d4
	lsl.l	d6,d4			; right group: span
	REP	d3,d5,v_err
	REP	d4,d5,v_sr
.left:	REP	d0,d5,v_sl
	REP	d1,d5,v_ell
	REP	d2,d5,v_erl

	move.l	v_count(a6),d0
	subq.l	#1,d0
	lsl.l	#3,d0
	move.l	d0,v_roff(a6)
	move.l	28(a6),a2

	; ---- top row: span & ~edgeR top/left, edgeR corner
	move.l	v_first(a6),a0
	MARGIN	a0,v_sl,d0,d1
	move.l	v_sl(a6),d2
	move.l	v_erl(a6),d3
	beq.s	.tl
	eor.l	d3,d2
	TERM	d3,d0,d1,24
.tl:	TERM	d2,d0,d1,16
	cmp.l	#1,v_count(a6)
	beq.s	.tw
	move.l	v_roff(a6),d7
	lea	0(a0,d7.l),a1
	MARGIN	a1,v_sr,d4,d5
	move.l	v_sr(a6),d7
	move.l	v_err(a6),d6
	eor.l	d6,d7
	TERM	d7,d4,d5,16
	move.l	v_err(a6),d7
	TERM	d7,d4,d5,24
.tw:	lea	16(a2),a1
	moveq	#1,d6
	bsr	.write

	; ---- interior rows (a0 is left on their first row by the top row's write): span & ~(edgeL | edgeR) fill, edgeL top/left, edgeR bottom/right
	MARGIN	a0,v_sl,d0,d1
	move.l	v_sl(a6),d2
	move.l	v_ell(a6),d3
	eor.l	d3,d2
	TERM	d3,d0,d1,16
	move.l	v_erl(a6),d3
	beq.s	.il
	eor.l	d3,d2
	TERM	d3,d0,d1,8
.il:	TERM	d2,d0,d1,0
	cmp.l	#1,v_count(a6)
	beq.s	.iw
	move.l	v_roff(a6),d7
	lea	0(a0,d7.l),a1
	MARGIN	a1,v_sr,d4,d5
	move.l	v_sr(a6),d7
	move.l	v_err(a6),d6
	eor.l	d6,d7
	TERM	d7,d4,d5,0
	move.l	v_err(a6),d7
	TERM	d7,d4,d5,8
.iw:	move.l	a2,a1
	moveq	#0,d6
	move.w	26(a6),d6
	subq.w	#2,d6
	bsr	.write

	; ---- bottom row (a0 is left on it by the interior write): span & ~edgeL bottom/right, edgeL corner
	MARGIN	a0,v_sl,d0,d1
	move.l	v_sl(a6),d2
	move.l	v_ell(a6),d3
	eor.l	d3,d2
	TERM	d3,d0,d1,24
	TERM	d2,d0,d1,8
	cmp.l	#1,v_count(a6)
	beq.s	.bw
	move.l	v_roff(a6),d7
	lea	0(a0,d7.l),a1
	MARGIN	a1,v_sr,d4,d5
	move.l	v_sr(a6),d7
	TERM	d7,d4,d5,8
.bw:	lea	8(a2),a1
	moveq	#1,d6
	bsr	.write

	movem.l	(sp)+,d2-d7/a2-a5
	unlk	a6
	rts

; Writes d6 rows at a0: left group d0:d1, v_count-2 middle groups (plane words at (a1)), right group d4:d5.
; Leaves a0 on the row after the last one written.
.write:	move.l	v_strideb(a6),a3
	move.l	v_count(a6),d7
	subq.w	#1,d6			; rows - 1 for DBRA
	subq.l	#1,d7
	beq.s	.w1
	subq.l	#1,d7
	beq.s	.w2
	move.l	(a1),d2
	move.l	4(a1),d3
	subq.l	#1,d7
	beq.s	.w3
	subq.l	#1,d7
	beq.s	.w4
	addq.l	#3,d7
	lsl.l	#3,d7			; (count - 1) groups of 8 bytes
	lea	0(a0,d7.l),a4		; end of the middle groups in the first row
.wn:	move.l	a0,a1
	move.l	d0,(a1)+
	move.l	d1,(a1)+
.wm:	move.l	d2,(a1)+
	move.l	d3,(a1)+
	cmp.l	a4,a1
	bne.s	.wm
	move.l	d4,(a1)+
	move.l	d5,(a1)
	add.l	a3,a0
	add.l	a3,a4
	dbra	d6,.wn
	rts
; up to four groups are one MOVEM per row: left d0-d1, middle d2-d3 (d4-d5), right in the next registers (a4-a5 for four)
.w4:	move.l	d4,a4			; right group
	move.l	d5,a5
	move.l	d2,d4			; second middle group
	move.l	d3,d5
.w4l:	movem.l	d0-d5/a4-a5,(a0)
	add.l	a3,a0
	dbra	d6,.w4l
	rts
.w3:	movem.l	d0-d5,(a0)
	add.l	a3,a0
	dbra	d6,.w3
	rts
.w2:	move.l	d4,d2
	move.l	d5,d3
.w2l:	movem.l	d0-d3,(a0)
	add.l	a3,a0
	dbra	d6,.w2l
	rts
.w1:	movem.l	d0-d1,(a0)
	add.l	a3,a0
	dbra	d6,.w1
	rts
