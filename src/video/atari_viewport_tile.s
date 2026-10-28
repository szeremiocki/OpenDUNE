; vim: set tabstop=8 shiftwidth=8 noexpandtab:
	xdef	_GFX_DrawViewportTileFast	;export symbol
	xref	_g_videoViewportBlitter
	xref	_g_videoBlitterTileSetup
	xref	_g_videoPlanarBase
	xref	_g_atariSupervisorResident
	xref	_s_curViewportTiles
	xref	_s_planarTileHouse
	xref	_s_planarTileReady
	xref	_s_planarTiles
	;code

; prototype:
; long GFX_DrawViewportTileFast(unsigned long tileID, unsigned long col,
;                               unsigned long row, unsigned long house);
;
; Fast path for one opaque, overlay-free viewport tile: per-house index
; lookup, opacity check, then a single blitter run (the tile setup must
; already be cached by Video_Atari_BlitOpaque). Returns 1 when the tile was
; drawn and 0 when the caller must use the general C path (no blitter, setup
; not cached, supervisor not resident, cursor over the tile, tile not opaque
; or not yet decoded). Arguments are full longs.

PLANAR_TILE_OPAQUE	equ	3

_GFX_DrawViewportTileFast:
	move.l	d2,-(sp)
	tst.b	_g_videoViewportBlitter
	beq	.fail
	tst.b	_g_videoBlitterTileSetup
	beq	.fail
	tst.b	_g_atariSupervisorResident
	beq	.fail
	move.l	_g_videoPlanarBase,d0
	beq	.fail
	move.l	d0,a1
	move.l	16(sp),d1		; row
	move.l	12(sp),d2		; col
	add.w	d1,d1
	lea	_s_curViewportTiles,a0
	move.w	(a0,d1.w),d0
	btst	d2,d0
	bne	.fail
	lea	.rows(pc),a0
	move.w	(a0,d1.w),d1		; (40 + 16 * row) * 160
	lsl.w	#3,d2
	add.w	d2,d1
	lea	(a1,d1.w),a1		; destination
	move.l	20(sp),d0		; house
	lsl.w	#2,d0
	lea	_s_planarTileHouse,a0
	move.l	(a0,d0.w),a0
	move.l	8(sp),d0		; tileID
	add.l	d0,d0
	moveq	#0,d2
	move.w	(a0,d0.l),d2		; tile index
	move.l	_s_planarTileReady,a0
	cmp.b	#PLANAR_TILE_OPAQUE,(a0,d2.l)
	bne	.fail
	lsl.l	#7,d2
	add.l	_s_planarTiles,d2
	move.l	d2,$ffff8a24.w		; source address
	move.l	a1,$ffff8a32.w		; destination address
	move.w	#16,$ffff8a38.w		; lines
	move.b	#$c0,$ffff8a3c.w	; start, hog
.wait:	tst.b	$ffff8a3c.w
	bmi	.wait
	moveq	#1,d0
	move.l	(sp)+,d2
	rts
.fail:	moveq	#0,d0
	move.l	(sp)+,d2
	rts

.rows:	dc.w	6400,8960,11520,14080,16640,19200,21760,24320,26880,29440
