/*
 * kport.h - types and helpers for building KINT 5 as WebAssembly.
 *
 * KINT assumes a 32-bit little-endian machine where pointers fit in a DWORD.
 * wasm32 matches that exactly (int, long and pointers are all 32 bits).
 */
#ifndef KPORT_H
#define KPORT_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <ctype.h>
#include <stdint.h>
#include <math.h>

typedef unsigned char   BYTE;
typedef unsigned short  WORD;
typedef unsigned long   DWORD;   /* 32 bits on wasm32 */
typedef int             BOOL;
typedef char            TCHAR;
typedef uint16_t        WCHAR;
typedef DWORD           COLORREF;
typedef long            LONG;
typedef int32_t         INT32;
typedef void           *HFONT, *HDC, *HBITMAP, *HWND;

typedef struct { long cx, cy; } SIZE;
typedef struct { long left, top, right, bottom; } RECT;

#ifndef TRUE
  #define TRUE  1
#endif
#ifndef FALSE
  #define FALSE 0
#endif
#define TEXT(s)        (s)
#define UNALIGNED
#define MAX_PATH       260
#define CLR_NONE       0xFFFFFFFFUL

#ifndef min
  #define min(a, b)    (((a) < (b)) ? (a) : (b))
  #define max(a, b)    (((a) > (b)) ? (a) : (b))
#endif

#define strnicmp       strncasecmp
#define _strnicmp      strncasecmp
#define stricmp        strcasecmp
#define _stricmp       strcasecmp

#ifndef SEEK_SET
  #define SEEK_SET 0
  #define SEEK_CUR 1
  #define SEEK_END 2
#endif

/* Functions the web platform layer (kplat.c) provides to pmach.c */
void  KSleep(DWORD tm);
BOOL  KeyMsg(DWORD *cmd, DWORD *arg1, DWORD *arg2, DWORD *arg3);
DWORD KGetOSversion(BYTE *pMem);
void  PauseMidi(void);
void  ResumeMidi(void);
void  KClipboardSet(const char *text);
void  KClipboardGet(char *buf, int maxlen);

#endif
