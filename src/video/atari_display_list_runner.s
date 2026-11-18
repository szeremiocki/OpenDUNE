	xdef	_Video_Atari_RunDisplayList
	xdef	_Video_Atari_QueueSpriteBlit
	xdef	_Video_Atari_QueueSpriteGeometry
	xdef	_Video_Atari_QueueTileBlit
	xdef	_Video_Atari_QueueTile
	xdef	_Video_Atari_QueueMaskedTile
	xdef	_Video_Atari_MaskedTileCode
	xdef	_Video_Atari_QueueMaskedRect
	xdef	_Video_Atari_MaskedRectCode
	xdef	_Video_Atari_BlitTileCode
	xdef	_Video_Atari_BlitPlaneCode
	xdef	_Video_Atari_TileCursorTail
	xdef	_Video_Atari_ConfigureBlitterDestination
	xref	_g_videoDisplayListNext
	xref	_g_videoBlitterTileSetup
	xref	_g_videoBlitterHalftonePattern
	xref	_g_videoTileCursorBlit
	xref	_g_videoTileCursorRestored

; C ABI: stream. Generated commands use a private register ABI and RTS.
_Video_Atari_RunDisplayList:
	movem.l	d2-d7/a2-a6,-(sp)
	move.l	48(sp),a0
	jsr	(a0)
	movem.l	(sp)+,d2-d7/a2-a6
	rts

; Same register ABI as BlitSpriteCode. The viewport has checked capacity.
; Geometry values become instructions, never pointers to temporary plans.
_Video_Atari_QueueSpriteBlit:
	movem.l	d1/a5,-(sp)
	move.l	_g_videoDisplayListNext,a5
	move.w	#$207c,(a5)+
	move.l	a0,(a5)+
	move.w	#$227c,(a5)+
	move.l	a1,(a5)+
	move.w	#$247c,(a5)+
	move.l	a2,(a5)+
	move.w	#$303c,(a5)+
	move.w	d0,(a5)+
	move.w	#$21fc,(a5)+
	move.l	(a3)+,(a5)+
	move.w	#$8a20,(a5)+
	move.w	#$21fc,(a5)+
	move.l	(a3)+,(a5)+
	move.w	#$8a28,(a5)+
	move.w	#$21fc,(a5)+
	move.l	(a3)+,(a5)+
	move.w	#$8a2c,(a5)+
	move.w	#$31fc,(a5)+
	move.w	(a3)+,(a5)+
	move.w	#$8a30,(a5)+
	move.w	#$31fc,(a5)+
	move.w	(a3)+,(a5)+
	move.w	#$8a36,(a5)+
	move.w	#$11fc,(a5)+
	moveq	#0,d1
	move.b	(a3),d1
	move.w	d1,(a5)+
	move.w	#$8a3d,(a5)+
	move.w	#$4239,(a5)+
	move.l	#_g_videoBlitterTileSetup,(a5)+
	move.w	#$4eb9,(a5)+
	move.l	a4,(a5)+
	move.l	a5,_g_videoDisplayListNext
	movem.l	(sp)+,d1/a5
	rts

; Cached geometry and recipe stay alive until their owner's eviction drain.
_Video_Atari_QueueSpriteGeometry:
	move.l	a5,-(sp)
	move.l	_g_videoDisplayListNext,a5
	move.w	#$207c,(a5)+
	move.l	a0,(a5)+
	move.w	#$227c,(a5)+
	move.l	a1,(a5)+
	move.w	#$247c,(a5)+
	move.l	a2,(a5)+
	move.w	#$267c,(a5)+
	move.l	a3,(a5)+
	move.w	#$287c,(a5)+
	move.l	a4,(a5)+
	move.w	#$303c,(a5)+
	move.w	d0,(a5)+
	move.w	#$4e93,(a5)+		; jsr (a3), geometry jumps to the recipe
	move.l	a5,_g_videoDisplayListNext
	move.l	(sp)+,a5
	rts

; Tile launch boundary: d2 pixels, a1 destination. Clobbers a0 only.
_Video_Atari_QueueTileBlit:
	move.l	a5,-(sp)
	move.l	_g_videoDisplayListNext,a5
	move.w	#$207c,(a5)+
	move.l	d2,(a5)+
	move.w	#$247c,(a5)+
	move.l	a1,(a5)+
	move.w	#$4eb9,(a5)+
	move.l	#_Video_Atari_BlitTileCode,(a5)+
	move.l	a5,_g_videoDisplayListNext
	move.l	(sp)+,a5
	rts

; C ABI adapter: pixels, destination.
_Video_Atari_QueueTile:
	move.l	d2,-(sp)
	move.l	8(sp),d2
	move.l	12(sp),a1
	jsr	_Video_Atari_QueueTileBlit
	move.l	(sp)+,d2
	rts

; C ABI: cached pixels, 16 mask words, destination. One 24-byte command.
_Video_Atari_QueueMaskedTile:
	move.l	a5,-(sp)
	move.l	_g_videoDisplayListNext,a5
	move.w	#$207c,(a5)+
	move.l	8(sp),(a5)+
	move.w	#$227c,(a5)+
	move.l	12(sp),(a5)+
	move.w	#$247c,(a5)+
	move.l	16(sp),(a5)+
	move.w	#$4eb9,(a5)+
	move.l	#_Video_Atari_MaskedTileCode,(a5)+
	move.l	a5,_g_videoDisplayListNext
	move.l	(sp)+,a5
	rts

; a0 pixels, a1 masks, a2 destination; private playback ABI, d0-d3 scratch.
; Two longword merges per row, preserving pixels outside the 16-bit mask.
_Video_Atari_MaskedTileCode:
	moveq	#15,d3
.row:
	move.w	(a1)+,d0
	move.w	d0,d1
	swap	d0
	move.w	d1,d0
	rept	2
	move.l	(a2),d2
	move.l	(a0)+,d1
	eor.l	d2,d1
	and.l	d0,d1
	eor.l	d1,d2
	move.l	d2,(a2)+
	endr
	lea	152(a2),a2
	dbra	d3,.row
	rts

; C ABI: pixels, packed masks, destination, groups, rows. One 32-byte command.
_Video_Atari_QueueMaskedRect:
	move.l	a5,-(sp)
	move.l	_g_videoDisplayListNext,a5
	move.w	#$207c,(a5)+
	move.l	8(sp),(a5)+
	move.w	#$227c,(a5)+
	move.l	12(sp),(a5)+
	move.w	#$247c,(a5)+
	move.l	16(sp),(a5)+
	move.w	#$363c,(a5)+
	move.w	22(sp),(a5)+
	move.w	#$383c,(a5)+
	move.w	26(sp),(a5)+
	move.w	#$4eb9,(a5)+
	move.l	#_Video_Atari_MaskedRectCode,(a5)+
	move.l	a5,_g_videoDisplayListNext
	move.l	(sp)+,a5
	rts

; a0 pixels, a1 masks, a2 destination, d3 groups, d4 rows.
; Contiguous sources, 160-byte screen rows; d0-d6 scratch, no BLITTER state.
_Video_Atari_MaskedRectCode:
	move.w	d3,d6
	lsl.w	#3,d6
	neg.w	d6
	add.w	#160,d6
	subq.w	#1,d3
	subq.w	#1,d4
.row:
	move.w	d3,d5
.group:
	move.w	(a1)+,d0
	beq.s	.empty
	move.w	d0,d1
	swap	d0
	move.w	d1,d0
	rept	2
	move.l	(a2),d2
	move.l	(a0)+,d1
	eor.l	d2,d1
	and.l	d0,d1
	eor.l	d1,d2
	move.l	d2,(a2)+
	endr
	bra.s	.next
.empty:
	addq.l	#8,a0
	addq.l	#8,a2
.next:
	dbra	d5,.group
	adda.w	d6,a2
	dbra	d4,.row
	rts

; a0 pixels, a2 destination. Retain the existing opaque-tile setup cache.
_Video_Atari_BlitTileCode:
	tst.b	_g_videoBlitterTileSetup
	bne.s	tile_ready
.idle:
	tst.b	$ffff8a3c.w
	bmi.s	.idle
	move.l	#$00020002,$ffff8a20.w
	move.l	#$ffffffff,$ffff8a28.w
	move.l	#$ffff0002,$ffff8a2c.w
tile_yinc:
	move.w	#154,$ffff8a30.w
tile_words:
	move.w	#4,$ffff8a36.w
	move.w	#$0203,$ffff8a3a.w
	move.b	#0,$ffff8a3d.w
	move.b	#1,_g_videoBlitterTileSetup
tile_ready:
	move.l	a0,$ffff8a24.w
tile_destination:
	move.l	a2,$ffff8a32.w
tile_rows:
	move.w	#16,$ffff8a38.w
	move.b	#$c0,$ffff8a3c.w
.wait:
	tst.b	$ffff8a3c.w
	bmi.s	.wait
	rts

; a0 source, a2 destination, d0 rows, d1 HOP/OP, d2 start/halftone line.
_Video_Atari_BlitPlaneCode:
	move.w	d1,$ffff8a3a.w
	move.l	a0,$ffff8a24.w
plane_destination:
	move.l	a2,$ffff8a32.w
	move.w	d0,$ffff8a38.w
	move.b	d2,$ffff8a3c.w
.wait:
	btst	#7,$ffff8a3c.w
	bne.s	.wait
	rts

; No arguments: frame-stable destination/pattern/OP pointers at 0/4/8.
; Fixed four-plane geometry; only caller-saved d0-d1/a0-a1 are clobbered.
_Video_Atari_TileCursorTail:
.idle:
	tst.b	$ffff8a3c.w
	bmi.s	.idle
	clr.b	_g_videoBlitterTileSetup
	move.l	_g_videoTileCursorBlit+4,a0
	cmpa.l	_g_videoBlitterHalftonePattern,a0
	beq.s	.pattern_ready
	move.l	a0,_g_videoBlitterHalftonePattern
	movem.l	(a0)+,d0-d1
	movem.l	d0-d1,$ffff8a00.w
	movem.l	(a0)+,d0-d1
	movem.l	d0-d1,$ffff8a08.w
	movem.l	(a0)+,d0-d1
	movem.l	d0-d1,$ffff8a10.w
	movem.l	(a0)+,d0-d1
	movem.l	d0-d1,$ffff8a18.w
.pattern_ready:
	move.l	_g_videoTileCursorBlit+8,a1
	move.l	_g_videoTileCursorBlit,a0
	move.l	#$ffffffff,$ffff8a28.w
	move.l	#$ffff0008,$ffff8a2c.w
	move.w	#160,$ffff8a30.w
	move.w	#1,$ffff8a36.w
	move.b	#1,$ffff8a3a.w
	clr.b	$ffff8a3d.w
	move.b	(a1)+,$ffff8a3b.w
cursor_destination0:
	move.l	a0,$ffff8a32.w
	addq.l	#2,a0
	move.w	#16,$ffff8a38.w
	move.b	#$c0,$ffff8a3c.w
	nop
	move.b	(a1)+,$ffff8a3b.w
cursor_destination1:
	move.l	a0,$ffff8a32.w
	addq.l	#2,a0
	move.w	#16,$ffff8a38.w
	move.b	#$c0,$ffff8a3c.w
	nop
	move.b	(a1)+,$ffff8a3b.w
cursor_destination2:
	move.l	a0,$ffff8a32.w
	addq.l	#2,a0
	move.w	#16,$ffff8a38.w
	move.b	#$c0,$ffff8a3c.w
	nop
	move.b	(a1)+,$ffff8a3b.w
cursor_destination3:
	move.l	a0,$ffff8a32.w
	move.w	#16,$ffff8a38.w
	move.b	#$c0,$ffff8a3c.w
.wait:
	tst.b	$ffff8a3c.w
	bmi.s	.wait
	move.b	#2,$ffff8a3a.w
	move.b	#1,_g_videoTileCursorRestored
	rts

; Initialization only, with no queued draws. Select once, not at each launch.
; MOVE.L An,abs.w and MOVE.W An,abs.w have the same instruction length.
_Video_Atari_ConfigureBlitterDestination:
	move.w	#154,tile_yinc+2
	move.w	#4,tile_words+2
	move.w	#16,tile_rows+2
	tst.l	8(sp)
	beq.s	.colour
	move.w	#78,tile_yinc+2
	move.w	#2,tile_words+2
	move.w	#32,tile_rows+2
.colour:
	move.l	4(sp),d0
	lea	destination_writes(pc),a0
	moveq	#5,d1
.next:
	move.l	(a0)+,a1
	andi.w	#$efff,(a1)
	move.w	#$8a32,2(a1)
	tst.l	d0
	beq.s	.full
	ori.w	#$1000,(a1)
	move.w	#$8a34,2(a1)
.full:
	dbra	d1,.next
	rts
destination_writes:
	dc.l	tile_destination,plane_destination
	dc.l	cursor_destination0,cursor_destination1,cursor_destination2,cursor_destination3
