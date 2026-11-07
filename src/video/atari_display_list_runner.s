	xdef	_Video_Atari_RunDisplayList
	xdef	_Video_Atari_QueueSpriteBlit
	xdef	_Video_Atari_QueueSpriteGeometry
	xdef	_Video_Atari_QueueTileBlit
	xdef	_Video_Atari_QueueTile
	xdef	_Video_Atari_BlitTileCode
	xdef	_Video_Atari_BlitPlaneCode
	xref	_g_videoDisplayListNext
	xref	_g_videoBlitterTileSetup
	xref	_Video_Atari_BlitSpriteGeometry

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
	move.w	#$4eb9,(a5)+
	move.l	#_Video_Atari_BlitSpriteGeometry,(a5)+
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

; a0 pixels, a2 destination. Retain the existing opaque-tile setup cache.
_Video_Atari_BlitTileCode:
	tst.b	_g_videoBlitterTileSetup
	bne.s	.ready
.idle:
	tst.b	$ffff8a3c.w
	bmi.s	.idle
	move.l	#$00020002,$ffff8a20.w
	move.l	#$ffffffff,$ffff8a28.w
	move.l	#$ffff0002,$ffff8a2c.w
	move.w	#154,$ffff8a30.w
	move.w	#4,$ffff8a36.w
	move.w	#$0203,$ffff8a3a.w
	move.b	#0,$ffff8a3d.w
	move.b	#1,_g_videoBlitterTileSetup
.ready:
	move.l	a0,$ffff8a24.w
	move.l	a2,$ffff8a32.w
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
	move.l	a2,$ffff8a32.w
	move.w	d0,$ffff8a38.w
	move.b	d2,$ffff8a3c.w
.wait:
	btst	#7,$ffff8a3c.w
	bne.s	.wait
	rts
