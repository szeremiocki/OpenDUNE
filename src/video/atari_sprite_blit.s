; Register ABI: a0 pixels, a1 opacity, a2 destination, a3 geometry plan,
; a4 compiled recipe, d0 height. Only a3 and condition codes are clobbered.
; JSR here, JMP to the recipe, then its RTS returns directly to the caller.
	xdef	_Video_Atari_BlitSpriteCode

_Video_Atari_BlitSpriteCode:
.wait:
	btst	#7,$ffff8a3c.w
	bne.s	.wait
	move.l	(a3),$ffff8a20.w
	move.l	4(a3),$ffff8a28.w
	move.l	8(a3),$ffff8a2c.w
	move.w	12(a3),$ffff8a30.w
	move.w	14(a3),$ffff8a36.w
	move.b	16(a3),$ffff8a3d.w
	jmp	(a4)
