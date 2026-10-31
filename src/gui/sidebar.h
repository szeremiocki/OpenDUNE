#ifndef GUI_SIDEBAR_H
#define GUI_SIDEBAR_H

#ifdef TOS
#include "font.h"

struct Widget;

extern bool GUI_Sidebar_Active(void);
extern bool GUI_Sidebar_Valid(void);
extern void GUI_Sidebar_Invalidate(void);
extern void GUI_Sidebar_Free(void);
extern void GUI_Sidebar_Begin(bool force);
extern void GUI_Sidebar_End(void);
extern bool GUI_Sidebar_WidgetBegin(const struct Widget *w);
extern void GUI_Sidebar_Fill(int16 left, int16 top, int16 right, int16 bottom, uint8 colour);
/* Write-only bordered rectangle: colours are the 4 border schema entries. The edge groups are
 * sampled once and must repeat vertically over the rectangle's rows (caller's contract). */
extern bool GUI_Sidebar_Border(int16 left, int16 top, uint16 width, uint16 height, const uint8 colours[4], bool fill);
extern bool GUI_Sidebar_Text(const char *string, int16 left, int16 top, const uint8 colours[16]);
extern void GUI_Sidebar_Char(unsigned char c, uint16 x, uint16 y, const uint8 colours[16]);
extern void GUI_Sidebar_Sprite(const uint8 *sprite, uint16 spriteID, int16 x, int16 y,
                               int flags, const uint8 *remap, uint16 remapCount);
#endif

#endif
