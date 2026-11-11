/*
 * kport6.h - types and helpers for building KINT 6 as WebAssembly.
 *
 * KINT 6 keeps all program memory as offsets into one block, and its data
 * types follow Windows (long = 32 bits), which wasm32 matches.
 */
#ifndef KPORT6_H
#define KPORT6_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <ctype.h>
#include <stdint.h>
#include <math.h>
#include <time.h>
#include <errno.h>
#include <sys/types.h>
#include <sys/stat.h>

typedef unsigned char   BYTE;
typedef unsigned short  WORD;
typedef unsigned long   DWORD;   /* 32 bits on wasm32 */
typedef unsigned int    UINT;
typedef int             BOOL;
typedef char            TCHAR;
typedef uint16_t        WCHAR;
typedef DWORD           COLORREF;
typedef long            LONG;
typedef void           *HFONT, *HDC, *HBITMAP, *HWND, *HGLOBAL, *HANDLE;

typedef struct { long cx, cy; } SIZE;
typedef struct { long left, top, right, bottom; } RECT;

#ifndef TRUE
  #define TRUE  1
#endif
#ifndef FALSE
  #define FALSE 0
#endif
#define TEXT(s)        (s)
#define MAX_PATH       260
#define _stat          stat

#ifndef min
  #define min(a, b)    (((a) < (b)) ? (a) : (b))
  #define max(a, b)    (((a) > (b)) ? (a) : (b))
#endif

#define strnicmp       strncasecmp
#define _strnicmp      strncasecmp
#define stricmp        strcasecmp
#define _stricmp       strcasecmp

/* Windows bitmap file structures (BMP load/save) */
#pragma pack(push, 2)
typedef struct {
	WORD	bfType;
	DWORD	bfSize;
	WORD	bfReserved1;
	WORD	bfReserved2;
	DWORD	bfOffBits;
} BITMAPFILEHEADER;
#pragma pack(pop)

typedef struct {
	DWORD	biSize;
	long	biWidth;
	long	biHeight;
	WORD	biPlanes;
	WORD	biBitCount;
	DWORD	biCompression;
	DWORD	biSizeImage;
	long	biXPelsPerMeter;
	long	biYPelsPerMeter;
	DWORD	biClrUsed;
	DWORD	biClrImportant;
} BITMAPINFOHEADER;

typedef struct { BYTE rgbBlue, rgbGreen, rgbRed, rgbReserved; } RGBQUAD;

typedef struct tagBITMAPINFO {
	BITMAPINFOHEADER	bmiHeader;
	RGBQUAD				bmiColors[1];
} BITMAPINFO;

typedef struct {	/* only the fields CreateSBM() fills in */
	DWORD	bV5Size;
	long	bV5Width;
	long	bV5Height;
	WORD	bV5Planes;
	WORD	bV5BitCount;
	DWORD	bV5Compression;
	DWORD	bV5SizeImage;
	long	bV5XPelsPerMeter;
	long	bV5YPelsPerMeter;
	DWORD	bV5ClrUsed;
	DWORD	bV5ClrImportant;
} BITMAPV5HEADER;

/* Windows virtual-key codes the interpreter refers to */
#define VK_LBUTTON     0x01
#define VK_RBUTTON     0x02
#define VK_MBUTTON     0x04

/* Functions the web platform layer (kplat6.c) provides */
void KillProgram(void);
void KInvalidate(long x1, long y1, long x2, long y2);
void KClipboardGet(char *buf, long maxlen);
void KClipboardSet(const char *text, long len);
void KToUpperUTF8(char *s);
void PauseMidi(void);
void ResumeMidi(void);
DWORD KGetKeyState(DWORD vk);
long unhandled_handler(void *e);
extern char PgmPathShown[], AppDataPathShown[];

#endif
