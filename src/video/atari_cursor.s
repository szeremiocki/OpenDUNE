; vim: set tabstop=8 shiftwidth=8 noexpandtab:
	xdef	_Video_Atari_CursorRestore
	xdef	_Video_Atari_CursorCompose
	xdef	_Video_Atari_CursorRefreshGroups
	xdef	_Video_Atari_CursorRowsEqual
	;code

; Software cursor loops. Plain 68000 code. Screen rows are 160 bytes apart
; and the screen, backup and drawn-data buffers are long-aligned (the C side
; declares them aligned(4)); every group is 4 bitplane words = 8 bytes.

; prototype:
; void Video_Atari_CursorRestore(uint16 *dst, const uint16 *save, long saveStride,
;                                long lines, long groups);
;
; Copies `groups` groups from each of `lines` backup rows (saveStride bytes
; apart) back onto the screen. lines and groups must be non-zero.

_Video_Atari_CursorRestore:
	movem.l	d2-d3/a2-a3,-(sp)	; 16 bytes, +4 return address
	move.l	20(sp),a0		; dst
	move.l	24(sp),a1		; save
	move.l	28(sp),d1		; saveStride
	move.l	32(sp),d2		; lines
	move.l	36(sp),d3		; groups
	subq.w	#1,d2
	subq.w	#1,d3
restore_line:
	move.l	a0,a2
	move.l	a1,a3
	move.w	d3,d0
restore_group:
	move.l	(a3)+,(a2)+
	move.l	(a3)+,(a2)+
	dbra	d0,restore_group
	lea	160(a0),a0
	adda.l	d1,a1
	dbra	d2,restore_line
	movem.l	(sp)+,d2-d3/a2-a3
	rts

; prototype:
; void Video_Atari_CursorCompose(const CursorComposeArgs *p);
;
; Saves the screen background, snapshots the cursor data/mask that is being
; drawn and composites the cursor over the screen. All fields are longs:
;  0 dst (screen)         4 save           8 drawnData      12 drawnMask
; 16 data (source)       20 mask (source) 24 lines         28 groups
; 32 dstSkip             36 saveSkip      40 drawnMaskSkip 44 dataSkip
; 48 maskSkip
; The skips are the byte offsets to add after a row to reach the next one.
; data must be long-aligned.

_Video_Atari_CursorCompose:
	movem.l	d2-d5/a2-a6,-(sp)	; 36 bytes, +4 return address
	move.l	40(sp),a6
	move.l	(a6),a0
	move.l	4(a6),a1
	move.l	8(a6),a2
	move.l	12(a6),a3
	move.l	16(a6),a4
	move.l	20(a6),a5
	move.l	24(a6),d2
	move.l	28(a6),d3
	subq.w	#1,d2
	subq.w	#1,d3
compose_line:
	move.w	d3,d4
compose_group:
	move.w	(a5)+,d0
	move.w	d0,(a3)+
	not.w	d0
	move.w	d0,d5
	swap	d0
	move.w	d5,d0			; keep mask in both halves
	move.l	(a0),d1
	move.l	d1,(a1)+
	move.l	(a4)+,d5
	move.l	d5,(a2)+
	and.l	d0,d1
	or.l	d5,d1
	move.l	d1,(a0)+
	move.l	(a0),d1
	move.l	d1,(a1)+
	move.l	(a4)+,d5
	move.l	d5,(a2)+
	and.l	d0,d1
	or.l	d5,d1
	move.l	d1,(a0)+
	dbra	d4,compose_group
	adda.l	32(a6),a0
	adda.l	36(a6),a1
	adda.l	36(a6),a2
	adda.l	40(a6),a3
	adda.l	44(a6),a4
	adda.l	48(a6),a5
	dbra	d2,compose_line
	movem.l	(sp)+,d2-d5/a2-a6
	rts

; prototype:
; void Video_Atari_CursorRefreshGroups(CursorRefreshArgs *p);
;
; After a write to the screen: for each written group (write mask != 0) the
; new clean pixels go into the backup and the cursor is redrawn over them.
;  0 dst           4 save          8 drawnData     12 drawnMask
; 16 masks (write masks, one word per group)       20 lines (modified)
; 24 groups       28 dstSkip      32 saveSkip     36 drawnMaskSkip
; 40 masksSkip
; Uses the same skip convention as Video_Atari_CursorCompose.

_Video_Atari_CursorRefreshGroups:
	movem.l	d2-d7/a2-a6,-(sp)	; 44 bytes, +4 return address
	move.l	48(sp),a6
	move.l	(a6),a0
	move.l	4(a6),a1
	move.l	8(a6),a2
	move.l	12(a6),a3
	move.l	16(a6),a5
refresh_line:
	move.l	24(a6),d4
	subq.w	#1,d4
refresh_group:
	move.w	(a5)+,d1
	beq	refresh_skip
	move.w	d1,d0
	swap	d0
	move.w	d1,d0			; d0 = write mask
	move.l	d0,d1
	not.l	d1			; d1 = ~write mask
	move.w	(a3)+,d5
	and.w	d0,d5
	move.w	d5,d6
	swap	d5
	move.w	d6,d5			; d5 = cursor bits to redraw
	move.l	d5,d6
	not.l	d6
	move.l	(a0),d7
	move.l	(a1),d2
	and.l	d1,d2
	move.l	d7,d3
	and.l	d0,d3
	or.l	d3,d2
	move.l	d2,(a1)+
	move.l	(a2)+,d3
	and.l	d5,d3
	and.l	d6,d7
	or.l	d3,d7
	move.l	d7,(a0)+
	move.l	(a0),d7
	move.l	(a1),d2
	and.l	d1,d2
	move.l	d7,d3
	and.l	d0,d3
	or.l	d3,d2
	move.l	d2,(a1)+
	move.l	(a2)+,d3
	and.l	d5,d3
	and.l	d6,d7
	or.l	d3,d7
	move.l	d7,(a0)+
	dbra	d4,refresh_group
	bra	refresh_next
refresh_skip:
	addq.l	#2,a3
	addq.l	#8,a0
	addq.l	#8,a1
	addq.l	#8,a2
	dbra	d4,refresh_group
refresh_next:
	adda.l	28(a6),a0
	adda.l	32(a6),a1
	adda.l	32(a6),a2
	adda.l	36(a6),a3
	adda.l	40(a6),a5
	subq.l	#1,20(a6)
	bne	refresh_line
	movem.l	(sp)+,d2-d7/a2-a6
	rts

; prototype:
; long Video_Atari_CursorRowsEqual(const uint16 *a, long strideA, const uint16 *b,
;                                  long strideB, long lines, long words);
;
; Returns 1 when `lines` rows of `words` words are identical, else 0.
; lines and words must be non-zero. Word-aligned pointers suffice.

_Video_Atari_CursorRowsEqual:
	movem.l	d2-d3/a2-a3,-(sp)
	move.l	20(sp),a0		; a
	move.l	24(sp),d1		; strideA
	move.l	28(sp),a1		; b
	move.l	32(sp),d3		; strideB
	move.l	36(sp),d2		; lines
	move.l	40(sp),d0		; words
	subq.w	#1,d2
	subq.w	#1,d0
rows_line:
	move.l	a0,a2
	move.l	a1,a3
	move.w	d0,-(sp)
rows_word:
	cmpm.w	(a2)+,(a3)+
	dbne	d0,rows_word
	bne	rows_differ
	move.w	(sp)+,d0
	adda.l	d1,a0
	adda.l	d3,a1
	dbra	d2,rows_line
	moveq	#1,d0
	bra	rows_done
rows_differ:
	addq.l	#2,sp
	moveq	#0,d0
rows_done:
	movem.l	(sp)+,d2-d3/a2-a3
	rts
