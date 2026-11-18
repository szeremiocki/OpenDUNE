; vim: set tabstop=8 shiftwidth=8 noexpandtab:
	xdef	_GFX_QueueViewportTileFast
	xdef	_GFX_QueueViewportPixelsFast
	xdef	_Video_Atari_ExpandTileNibbles
	xref	_g_videoViewportBlitter
	xref	_g_videoPlanarBase
	xref	_g_videoAtariMono
	xref	_g_atariSupervisorResident
	xref	_s_curViewportTiles
	xref	_s_planarTileHouse
	xref	_s_planarTileReady
	xref	_s_planarTiles
	xref	_Video_Atari_QueueTileBlit
	;code

; prototype:
; long GFX_QueueViewportTileFast(unsigned long tileID, unsigned long col,
;                               unsigned long row, unsigned long house);
;
; Fast path for one opaque, overlay-free viewport tile: per-house index
; lookup, opacity check, then a queue-only launch. Requires an active list
; when BLITTER publication is enabled. Returns 1 when the tile was queued
; and 0 when the caller must use the general C path (no
; blitter, supervisor not resident, cursor over the tile, tile not opaque or
; not yet decoded). Arguments are full longs.

PLANAR_TILE_OPAQUE	equ	3

_GFX_QueueViewportTileFast:
	move.l	d2,-(sp)
	tst.b	_g_videoAtariMono
	bne	tile_fail
	tst.b	_g_videoViewportBlitter
	beq	tile_fail
	tst.b	_g_atariSupervisorResident
	beq	tile_fail
	move.l	_g_videoPlanarBase,d0
	beq	tile_fail
	move.l	d0,a1
	move.l	16(sp),d1		; row
	move.l	12(sp),d2		; col
	add.w	d1,d1
	lea	_s_curViewportTiles,a0
	move.w	(a0,d1.w),d0
	btst	d2,d0
	bne	tile_fail
	lea	tile_rows(pc),a0
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
	bne	tile_fail
	lsl.l	#7,d2
	add.l	_s_planarTiles,d2
tile_blit:
	jsr	_Video_Atari_QueueTileBlit
	moveq	#1,d0
	move.l	(sp)+,d2
	rts
tile_fail:	moveq	#0,d0
	move.l	(sp)+,d2
	rts

; long GFX_QueueViewportPixelsFast(unsigned long pixels, unsigned long col,
;                                 unsigned long row);
; Same as above for an already composed opaque tile image at "pixels".
_GFX_QueueViewportPixelsFast:
	move.l	d2,-(sp)
	tst.b	_g_videoAtariMono
	bne	tile_fail
	tst.b	_g_videoViewportBlitter
	beq	tile_fail
	tst.b	_g_atariSupervisorResident
	beq	tile_fail
	move.l	_g_videoPlanarBase,d0
	beq	tile_fail
	move.l	d0,a1
	move.l	16(sp),d1		; row
	move.l	12(sp),d2		; col
	add.w	d1,d1
	lea	_s_curViewportTiles,a0
	move.w	(a0,d1.w),d0
	btst	d2,d0
	bne	tile_fail
	lea	tile_rows(pc),a0
	move.w	(a0,d1.w),d1
	lsl.w	#3,d2
	add.w	d2,d1
	lea	(a1,d1.w),a1
	move.l	8(sp),d2		; pixels
	bra	tile_blit

tile_rows:	dc.w	6400,8960,11520,14080,16640,19200,21760,24320,26880,29440

; prototype:
; void Video_Atari_ExpandTileNibbles(const uint8 *src, const uint8 *pens, uint8 *chunky);
;
; Expands 128 source bytes (two 4-bit pixels each, high nibble first) into 256
; chunky bytes through the 16-entry pen table. Plain 68000 code.
_Video_Atari_ExpandTileNibbles:
	movem.l	d2/a2,-(sp)
	move.l	12(sp),a0		; src
	move.l	16(sp),a1		; pens
	move.l	20(sp),a2		; chunky
	moveq	#0,d0			; the upper bits stay zero: only move.b writes d0
	moveq	#63,d2
expand_loop:
	move.b	(a0)+,d0
	move.w	d0,d1
	lsr.w	#4,d1
	and.w	#15,d0
	move.b	(a1,d1.w),(a2)+
	move.b	(a1,d0.w),(a2)+
	move.b	(a0)+,d0
	move.w	d0,d1
	lsr.w	#4,d1
	and.w	#15,d0
	move.b	(a1,d1.w),(a2)+
	move.b	(a1,d0.w),(a2)+
	dbra	d2,expand_loop
	movem.l	(sp)+,d2/a2
	rts
