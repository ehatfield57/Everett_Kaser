#!/usr/bin/env python3
"""
Copy Everett Kaser's KINT 6 sources from kint_src/k6/src/kint/MicrosoftWindows
into engine/k6/gen and apply the web-port patches.

The Windows main.c is not compiled.  Its portable parts (the .KE loader, the
message queue and the heap manager) are lifted out unchanged into
gen/kmain6.c; engine/k6/kplat6.c supplies the browser platform layer.

Every patch is an exact text replacement; if one no longer matches, this
script stops with an error rather than producing a broken build.
"""
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "kint_src" / "k6" / "src" / "kint" / "MicrosoftWindows"
GEN = ROOT / "engine" / "k6" / "gen"


def read(name):
    return (SRC / name).read_text(encoding="latin-1").replace("\r\n", "\n")


def write(name, text):
    (GEN / name).write_text(text, encoding="latin-1")


def replace_once(text, old, new, what):
    n = text.count(old)
    if n != 1:
        sys.exit(f"patch '{what}': expected 1 match, found {n}")
    return text.replace(old, new)


def between(text, start, end, what, include_end=False):
    """Return text from `start` up to (not including) `end`, or to EOF if end is None."""
    if text.count(start) != 1:
        sys.exit(f"extract '{what}': start marker found {text.count(start)} times")
    i = text.index(start)
    if end is None:
        return text[i:]
    j = text.find(end, i + len(start))
    if j < 0:
        sys.exit(f"extract '{what}': end marker not found")
    return text[i:j + (len(end) if include_end else 0)]


def replace_between(text, start, end, new, what):
    old = between(text, start, end, what)
    return text.replace(old, new, 1)


# ------------------------------------------------------------------ main.h
def patch_main_h():
    s = read("main.h")
    s = replace_once(s, "#define\t_UNICODE\n#define\tUNICODE\n", "/* WEB PORT: 8-bit (UTF-8) strings */\n", "unicode")
    s = replace_between(
        s, "#ifndef _WINDOWS_\n    #include <windows.h>", '#include "midi.h"\n',
        '/* WEB PORT: browser/WebAssembly build */\n#include "kport6.h"\n', "includes")
    s = replace_once(s, '#include "midi.h"\n', "", "midi include")
    write("main.h", s)


# ------------------------------------------------------------------ pmach.c
def patch_pmach_c():
    s = read("pmach.c")
    s = replace_between(
        s, "\t\tif( IsClipboardFormatAvailable(CF_UNICODETEXT) ) {", "\t\tbreak;\n\t case SYS_WRITECLIPBOARD:",
        "\t\tKClipboardGet((char*)pB, i);\t/* WEB PORT */\n", "read clipboard")
    s = replace_between(
        s, "\t\t{\n\t\t\tWCHAR\t*SMbuf=NULL;\n\t\t\tint\t\tSMbufLen;\n\n\t\t\tSMbufLen = 2+MultiByteToWideChar(CP_UTF8, 0, pB, -1, 0, 0);",
        "\t\tbreak;\n\t case SYS_CAPTUREMOUSE:",
        "\t\tKClipboardSet((char*)pB, i);\t/* WEB PORT */\n", "write clipboard")
    s = replace_between(
        s, "\t\t{\n\t\t\tTCHAR\tbbb[20];\n", "\t\tbreak;\n/// memcpy(",
        "\t\tKToUpperUTF8(pS);\t/* WEB PORT */\n", "toupper")
    # Paths and strings are already UTF-8 here.  Report the paths the native
    # Mac app would use (with '/' dividers, as on the Mac).
    s = replace_once(s, "\t\tWideCharToMultiByte(CP_UTF8, 0, (LPCWSTR)AppDataPath, -1, UTF8buf, sizeof(UTF8buf), NULL, NULL);\n",
                     "\t\tstrcpy((char*)UTF8buf, AppDataPathShown);\t/* WEB PORT */\n", "appdata path")
    s = replace_once(s, "\t\tWideCharToMultiByte(CP_UTF8, 0, (LPCWSTR)PgmPath, -1, UTF8buf, sizeof(UTF8buf), NULL, NULL);\n",
                     "\t\tstrcpy((char*)UTF8buf, PgmPathShown);\t/* WEB PORT */\n", "pgm path")
    s = replace_once(s, "\t\tWideCharToMultiByte(CP_UTF8, 0, (LPCWSTR)OSctrl_cmdSTR, -1, UTF8buf, sizeof(UTF8buf), NULL, NULL);\n",
                     "\t\tstrcpy((char*)UTF8buf, OSctrl_cmdSTR);\t/* WEB PORT */\n", "ctrl name")
    s = replace_once(s, '\t \tstrcpy((char*)pB, "\\\\");\t// or "/" for Mac OS\n',
                     '\t \tstrcpy((char*)pB, "/");\t/* WEB PORT: as on Mac OS */\n', "path divider")
    s = replace_once(s, "GetKeyState(GETMEMD(pArgs))", "KGetKeyState(GETMEMD(pArgs))", "key state")
    write("pmach.c", s)


# ------------------------------------------------------------------ graph.c
SYSFONT_PORT = r'''#define	SYSFONTNUM	18

/* WEB PORT ------------------------------------------------------------------
 * The Windows build draws "system font" text with GDI.  Here the browser
 * draws it on a canvas (see kint_lib.js).  Line breaking and justification
 * follow the original DrawSysFontText().
 * ------------------------------------------------------------------------- */
extern int  js_sysfont_prepare(const char *utf8, int h, int fontflags);
extern int  js_sysfont_width(int n);
extern int  js_sysfont_char(int i);
extern void js_sysfont_draw(BYTE *bits, int linelen, int bw, int bh, int n, DWORD fclr, int bpp);

int		SysFontW;	// width of SysFontBM
int		SysFontH;	// height of SysFontBM

void InitSysFonts() {
	SysFontW = scrBM.w;
	SysFontH = max(256, scrBM.h/15);
	CreateSBM(&SysFontBM, SysFontW, SysFontH);
}

void FreeSysFonts() {
	DeleteSBM(&SysFontBM);
}

/* browser font flags: 1 fixed, 2 bold, 4 italic, 8 underline, 16 serif */
static int WebFontFlags(DWORD flags) {
	return ((flags & CF_FIXED) ? 1 : 0) | ((flags & CF_BOLD) ? 2 : 0) | ((flags & CF_ITALIC) ? 4 : 0)
	     | ((flags & CF_UNDERLINE) ? 8 : 0) | ((flags & CF_SERIF) ? 16 : 0);
}

/* draw the first n characters at the top-left of SysFontBM (also makes the area opaque, like Untrans()) */
static void SysFontText(int n, long w, long h, DWORD fclr) {
	if( w > SysFontW ) w = SysFontW;
	if( h > SysFontH ) h = SysFontH;
	if( n > 0 && w > 0 && h > 0 ) js_sysfont_draw(SysFontBM.pBits, SysFontBM.linelen, w, h, n, fclr, 4);
}

DWORD DrawSysFontText(DWORD pArgs) {

	DWORD	hBM;
	char	*pText;
	int		x, y, w, h;
	DWORD	bclr, fclr, flags;
	char	c;
	int		wcnt, i, ww, savend, curend, dw;

	hBM = GETMEMD(pArgs); pArgs += 4;
	pText = (char*)(mainKE + GETMEMD(pArgs)); pArgs += 4;
	x = (int)GETMEMD(pArgs); pArgs += 4;
	y = (int)GETMEMD(pArgs); pArgs += 4;
	w = (int)GETMEMD(pArgs); pArgs += 4;
	h = (int)GETMEMD(pArgs); pArgs += 4;
	if( h>SysFontH ) h = SysFontH;
	flags = GETMEMD(pArgs); pArgs += 4;
	bclr = GETMEMD(pArgs); pArgs += 4;
	fclr = GETMEMD(pArgs);

	if( w==0 || h==0 || *pText==0 ) return 0;

	wcnt = js_sysfont_prepare(pText, h, WebFontFlags(flags));
	curend = wcnt;
	ww = js_sysfont_width(curend);
	if( ww > w ) {	// if the string won't fit in the remaining space on this line
		if( (flags & TF_BREAK_SPACE) ) {	// if breaking on SPACE
			int		lastSpace=0;

			for(curend=0; curend<wcnt; curend++) {
				if( js_sysfont_char(curend)==' ' ) lastSpace = curend;
				if( js_sysfont_width(curend+1) > w ) {	// if still too big
					if( curend==0 ) return 0;	// if not room to output even a single char
					if( lastSpace==0 && (flags & TF_BREAK_CHAR) ) goto breakany;
					while( curend && lastSpace>=0 && curend > lastSpace ) --curend;
					break;
				}
			}
		} else if( (flags & TF_BREAK_CHAR) ) {	// if breaking on ANY CHAR
breakany:
			for(curend=0; curend<wcnt; curend++) {
				if( js_sysfont_width(curend+1) > w ) {
					if( curend==0 ) return 0;	// if not room to output even a single char
					--curend;
					break;
				}
			}
		}
		ww = js_sysfont_width(curend);
	}
	dw = max(w, ww) + h;
	if( curend && (flags & CF_ITALIC) ) {	// italics
		ww += h/6;	// hack! a little slop for last char of italics
	}

	if( !(flags & TF_GET_WIDTH) ) {	// if not just doing a "get text width," copy the drawn text
		if( flags & CF_CENTER ) {			/// CENTERED
			if( (bclr & 0xFF000000)!=0xFF000000 ) DrawBM(-2, 0, 0, hBM, x+(w-ww)/2, y, ww, h, 0, 0, 0);
			else DrawRect(-2, 0, 0, w, h, bclr, 0);
			SysFontText(curend, dw, h, fclr);
			DrawBM(hBM, x+(w-ww)/2, y, -2, 0, 0, ww, h, 0, 0, 0);
		} else if( flags & CF_RIGHT ) {	/// RIGHT JUSTIFIED
			if( (bclr&0xFF000000)!=0xFF000000 ) DrawBM(-2, 0, 0, hBM, x+w-ww, y, ww, h, 0, 0, 0);
			else DrawRect(-2, 0, 0, w, h, bclr, 0);
			SysFontText(curend, dw, h, fclr);
			DrawBM(hBM, x+w-ww, y, -2, 0, 0, ww, h, 0, 0, 0);
		} else {					/// LEFT JUSTIFIED
			if( (bclr&0xFF000000)!=0xFF000000 ) DrawBM(-2, 0, 0, hBM, x, y, ww, h, 0, 0, 0);
			else DrawRect(-2, 0, 0, w, h, bclr, 0);
			SysFontText(curend, dw, h, fclr);
			DrawBM(hBM, x, y, -2, 0, 0, min(w,ww), h, 0, 0, 0);
		}
	}

	for(i=0, savend=curend; savend && pText[i]; --savend) {
		c = pText[i];
		if( c & 0x80 ) {
			if( (c & 0xE0)==0xC0 ) {		/// 2-byte code
				c = pText[++i];
				if( (c & 0xC0)==0x80 ) ++i;
			} else if( (c & 0xF0)==0xE0 ) {	/// 3-byte code
				c = pText[++i];
				if( (c & 0xC0)==0x80 ) {
					c = pText[++i];
					if( (c & 0xC0)==0x80 ) ++i;
				}
			} else if( (c & 0xF8)==0xF0 ) {	/// 4-byte code
				c = pText[++i];
				if( (c & 0xC0)==0x80 ) {
					c = pText[++i];
					if( (c & 0xC0)==0x80 ) {
						c = pText[++i];
						if( (c & 0xC0)==0x80 ) ++i;
					}
				}
			}
		} else ++i;							/// 1-byte code
	}
	/// return length drawn (in lower word) & pixel-width of drawn text (in upper word)
	return (ww<<16)+i;
}
'''


def patch_graph_c():
    s = read("graph.c")
    s = replace_once(
        s, "\tif( NULL==(pX->hBitmap=CreateDIBSection(NULL, (BITMAPINFO*)&pbmi, DIB_RGB_COLORS, (void **)&pX->pBits, NULL, 0)) ) return FALSE;",
        "\t/* WEB PORT: a plain memory bitmap instead of a GDI DIB section */\n"
        "\tif( NULL==(pX->pBits=(BYTE *)calloc(1, (size_t)pX->linelen*h)) ) return FALSE;\n"
        "\tpX->hBitmap = (HBITMAP)pX->pBits;",
        "CreateSBM")
    s = replace_once(
        s, "\tif( pX->hBitmap != NULL ) DeleteObject(pX->hBitmap);",
        "\tif( pX->pBits != NULL ) free(pX->pBits);\t/* WEB PORT */\n\tpX->pBits = NULL;\n\tpX->hBitmap = NULL;",
        "DeleteSBM")
    s = replace_once(s, "\tInvalidateRect(hWndMain, &rect, FALSE);\n\tScreenDirty = TRUE;",
                     "\tKInvalidate(rect.left, rect.top, rect.right, rect.bottom);\t/* WEB PORT */\n\tScreenDirty = TRUE;",
                     "InvalidateScreen")
    # The GDI system-font code runs from here to the end of the file.
    s = s[:s.index(between(s, "#define\tSYSFONTNUM\t18", None, "sysfont"))] + SYSFONT_PORT
    write("graph.c", s)


# ------------------------------------------------------------------ miniz.c
def patch_miniz_c():
    s = read("miniz.c")
    s = replace_between(
        s, "/// return file len if successful, else -1\nint KMZ_stat(", "#define MZ_FOPEN(f, m) KMZ_open(f, m)",
        "/* WEB PORT: stat through the KINT file layer */\n"
        "int KMZ_stat(const char *fname, struct _stat *buf) {\n"
        "\tQWORD\tmt;\n\tBYTE\tft;\n\tDWORD\tlen;\n\n"
        "\tlen = Kstat((char*)fname, &mt, &ft);\n"
        "\tif( len==0xFFFFFFFF ) return -1;\n"
        "\tmemset(buf, 0, sizeof(*buf));\n\tbuf->st_size = len;\n\tbuf->st_mtime = (time_t)mt;\n"
        "\treturn 0;\n}\n\n",
        "KMZ_stat")
    write("miniz.c", s)


# ------------------------------------------------------------------ kmain6.c
KMAIN_PRELUDE = '''/*
 * kmain6.c - GENERATED by engine/patch_k6.py.
 * The portable parts of Everett Kaser's KINT 6 Windows main.c, unchanged:
 * the .KE loader, message queue and heap manager.
 */
#include "main.h"

#define	MAXMSGS		1024			/// max messages queued at a time in KINTmsgs

void KillProgram();
void InitHeap();

BYTE		BytBuf[8192];
BYTE		*mainKE;		/// memory for main .KE program
DWORD		KINTmsgs[MAXMSGS*4];	/// memory for .KE message queue
int			KINTmsgadd=0, KINTmsgrem=0;
BOOL		InSleep=FALSE;	/// set when .KE requests a SLEEP period
DWORD		NonHeapLen, HeapLen, HeapTop, HighestHeapTop;
long		killpgm=0;		/// non-zero if the program is dying
DWORD		HeapLockedCnt=0;

'''


def make_kmain6():
    s = read("main.c")
    parts = [
        between(s, "///=========================================================================================\n/// Load MAIN.KE",
                "///===============================================================\n/// When an exception (CRASH!) occurs", "loader+queue"),
        between(s, "/**=======================================================================\nNonHeap memory starts", None, "heap"),
    ]
    write("kmain6.c", KMAIN_PRELUDE + "\n".join(parts))


def main():
    if GEN.exists():
        shutil.rmtree(GEN)
    GEN.mkdir(parents=True)
    patch_main_h()
    patch_pmach_c()
    patch_graph_c()
    patch_miniz_c()
    make_kmain6()
    for name in ("miniz.h", "spng.c", "spng.h"):
        write(name, read(name))
    print(f"patched sources written to {GEN.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
