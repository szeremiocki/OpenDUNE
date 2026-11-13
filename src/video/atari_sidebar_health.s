	xdef	_Video_Atari_SidebarHealthCode

; Private list ABI: a0 points at group 288 on the bar's first row (y=52).
; d0-d3 contain the new four plane pairs for the 24-pixel interior at x=293.
_Video_Atari_SidebarHealthCode:
	moveq	#6,d5
.row:
	move.l	(a0),d4
	and.l	#$f800f800,d4
	or.l	d0,d4
	move.l	d4,(a0)+
	move.l	(a0),d4
	and.l	#$f800f800,d4
	or.l	d1,d4
	move.l	d4,(a0)+
	move.l	(a0),d4
	and.l	#$00070007,d4
	or.l	d2,d4
	move.l	d4,(a0)+
	move.l	(a0),d4
	and.l	#$00070007,d4
	or.l	d3,d4
	move.l	d4,(a0)+
	lea	144(a0),a0
	dbra	d5,.row
	rts
