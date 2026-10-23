#ifndef GUI_SIDEBAR_H
#define GUI_SIDEBAR_H

#ifdef TOS
#include "font.h"

struct Widget;

enum {
	SIDEBAR_FRAGMENT_TEXT,
	SIDEBAR_FRAGMENT_BUTTON,
	SIDEBAR_FRAGMENT_PORTRAIT,
	SIDEBAR_FRAGMENT_FRAME,
	SIDEBAR_FRAGMENT_SPRITE
};

extern bool GUI_Sidebar_Active(void);
extern bool GUI_Sidebar_Valid(void);
extern void GUI_Sidebar_Invalidate(void);
extern void GUI_Sidebar_Free(void);
extern void GUI_Sidebar_Begin(bool force);
extern void GUI_Sidebar_End(void);
extern bool GUI_Sidebar_Background(void);
extern void GUI_Sidebar_CacheBackground(void);
extern bool GUI_Sidebar_WidgetBegin(const struct Widget *w);
extern bool GUI_Sidebar_ButtonBegin(const struct Widget *w, uint8 colour);
extern bool GUI_Sidebar_FragmentBegin(uint16 kind, const char *text, int16 left, int16 top,
                                     uint16 width, uint16 height, uint16 state, const uint8 *colours);
extern void GUI_Sidebar_FragmentEnd(void);
extern bool GUI_Sidebar_CommandRestore(uint16 actionType);
extern void GUI_Sidebar_CommandCache(uint16 actionType);
extern void GUI_Sidebar_Fill(int16 left, int16 top, int16 right, int16 bottom, uint8 colour);
extern void GUI_Sidebar_Char(unsigned char c, uint16 x, uint16 y, const uint8 colours[16]);
extern void GUI_Sidebar_Sprite(const uint8 *sprite, uint16 spriteID, int16 x, int16 y,
                               int flags, const uint8 *remap, uint16 remapCount);
#endif

#endif
