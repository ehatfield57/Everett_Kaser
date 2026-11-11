#!/usr/bin/env python3
"""
Copy Everett Kaser's KINT 5 sources from kint_src/k5/src into engine/k5/gen
and apply the small set of web-port patches.

The originals are never modified. Every patch is an exact text replacement,
so if a patch no longer matches (e.g. a different KINT release), this script
stops with an error instead of silently producing a broken build.
"""
import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "kint_src" / "k5" / "src"
PORT = ROOT / "engine" / "k5"          # our own port files (kport.h, kplat.c, ...)
GEN = PORT / "gen"                     # patched copies of Everett's files


def read(name):
    return (SRC / name).read_text(encoding="latin-1").replace("\r\n", "\n")


def write(name, text):
    (GEN / name).write_text(text, encoding="latin-1")


def replace_once(text, old, new, what):
    n = text.count(old)
    if n != 1:
        sys.exit(f"patch '{what}': expected 1 match, found {n}")
    return text.replace(old, new)


def replace_between(text, start, end, new, what, keep_end=True):
    """Replace text from `start` (inclusive) up to `end` (kept unless keep_end=False)."""
    i = text.find(start)
    j = text.find(end, i + 1) if i >= 0 else -1
    if i < 0 or j < 0 or text.count(start) != 1:
        sys.exit(f"patch '{what}': markers not found exactly once")
    if not keep_end:
        j += len(end)
    return text[:i] + new + text[j:]


def patch_main_h():
    s = read("Main.h")
    for flag in ("KINT_MS_WINDOWS", "KINT_PRINT", "KINT_MIDI", "KINT_MAKE_COPY"):
        s, n = re.subn(r"(#define\t%s\t+)1" % flag, r"\g<1>0", s)
        if n != 1:
            sys.exit(f"patch main.h: flag {flag} not found")
    s = replace_once(
        s,
        "#else\n  typedef\tunsigned char\tBYTE;\n  typedef\tunsigned short\tWORD;\n"
        "  typedef\tunsigned long\tDWORD;\n  #define\tNULL\t0\n  #define\tFALSE\t0\n#endif",
        "#else\n  /* WEB PORT: browser/WebAssembly build */\n  #include \"kport.h\"\n#endif",
        "main.h types",
    )
    write("main.h", s)


SYSFONT_PORT = r'''#define	NUMSYSFONT	100

/* WEB PORT ------------------------------------------------------------------
 * The Windows build draws "system font" text with GDI (Tahoma, Courier New,
 * Times New Roman).  Here the browser draws it on a canvas (see kint_lib.js).
 * The line-breaking and justification logic below follows the original.
 * ------------------------------------------------------------------------- */
extern int  js_sysfont_prepare(const char *utf8, int h, int fontflags);
extern int  js_sysfont_width(int n);
extern int  js_sysfont_char(int i);
extern void js_sysfont_draw(BYTE *bits, int linelen, int bw, int bh, int n, DWORD fclr);

int		SysFontW;	// width of SysFontBMB
int		SysFontH;	// height of SysFontBMB
PBMB	SysFontBMB=NULL;

void InitSysFonts(int w, int h) {
	if( w<SYSFONTMINW ) w = SYSFONTMINW;
	SysFontW = w;
	SysFontH = h;
	SysFontBMB = CreateBMB(SysFontW, SysFontH, TRUE);
}

void FreeSysFonts() {
	if( SysFontBMB!=NULL ) DeleteBMB(SysFontBMB);
	SysFontBMB = NULL;
}

static void SysFontFill(int w, int h, COLORREF clr) {
	int		x, y;
	BYTE	*p;

	if( w > SysFontBMB->physW ) w = SysFontBMB->physW;
	if( h > SysFontBMB->physH ) h = SysFontBMB->physH;
	for(y=0; y<h; y++) {
		p = SysFontBMB->pBits + y*SysFontBMB->linelen;
		for(x=0; x<w; x++) {
			*p++ = (BYTE)(clr>>16);
			*p++ = (BYTE)(clr>>8);
			*p++ = (BYTE)clr;
		}
	}
}

static void SysFontText(int n, int w, int h, COLORREF fclr) {
	if( w > SysFontBMB->physW ) w = SysFontBMB->physW;
	if( h > SysFontBMB->physH ) h = SysFontBMB->physH;
	if( n > 0 && w > 0 && h > 0 ) js_sysfont_draw(SysFontBMB->pBits, SysFontBMB->linelen, w, h, n, fclr);
}

DWORD DrawSysFontText(PBMB pBM, char *pText, int x, int y, int w, int h, int flags, COLORREF bclr, COLORREF fclr, long *pW) {

	char		c;
	int			wcnt, curend, ww, i, savend, rw, dw;
	WORD		th;

	/// bail if nothing to do
	if( SysFontBMB==NULL || w==0 || h==0 || *pText==0 ) return 0;
	if( bclr==CLR_NONE ) flags &= ~128;	// don't allow rotate if we're not filling the background

	wcnt = js_sysfont_prepare(pText, h, flags & ST_FONT_CHARS);
	SetupBMD(&SysFontBMB);

	curend = wcnt;
	if( js_sysfont_width(curend) > w ) {	// if the string won't fit in the remaining space on this line
		if( (flags & 512) ) {	// if breaking on SPACE
			int		lastSpace=0;

			for(curend=0; curend<wcnt; curend++) {
				if( js_sysfont_char(curend)==' ' ) lastSpace = curend;
				if( js_sysfont_width(curend+1) > w ) {	// if still too big
					if( curend==0 ) return 0;	// if not room to output even a single char
					if( lastSpace==0 && (flags & 256) ) goto breakany;
					while( curend && lastSpace>=0 && curend > lastSpace ) --curend;
					break;
				}
			}
		} else if( (flags & 256) ) {	// if breaking on ANY CHAR
breakany:
			for(curend=0; curend<wcnt; curend++) {
				if( js_sysfont_width(curend+1) > w ) {
					if( curend==0 ) return 0;	// if not room to output even a single char
					--curend;
					break;
				}
			}
		}
	}

	ww = js_sysfont_width(curend);
	dw = max(w, ww) + h;	// width of the work area the text may touch
	if( bclr==CLR_NONE ) {
		BltBMB(SysFontBMB, 0, 0, pBM, x, y, w, h, (int)FALSE, (int)FALSE);
	} else {
		rw = w;
		if( flags & 4 ) rw = min(w+h, 2048);	// little extra for italics
		SysFontFill(max(rw, dw), h, bclr);
	}
	SysFontText(curend, dw, h, fclr);

	if( curend && (flags & 4) ) {	// italics
		ww += h/6;	// hack! a little slop for last char of italics
	}

	if( !(flags & 32768) ) {	// if not just doing a "get text width," copy the drawn text
		if( flags & 128 ) {	// rotate our WORK bitmap
			th = SysFontBMB->logH;
			SysFontBMB->logH = SysFontBMB->logW;
			SysFontBMB->logW = th;
			SysFontBMB->orient = BMO_270;
			SysFontBMB->clipX1 = SysFontBMB->clipY1 = 0;
			SysFontBMB->clipX2 = SysFontBMB->physH;
			SysFontBMB->clipY2 = SysFontBMB->physW;
		}
		if( flags & 32 ) {			/// CENTERED
			if( bclr==CLR_NONE ) {
				BltBMB(SysFontBMB, 0, 0, pBM, x+(w-ww)/2, y, ww, h, (int)FALSE, (int)FALSE);
				SysFontText(curend, dw, h, fclr);
			}
			if( flags & 128 ) BltBMB(pBM, x, y+(w-ww)/2, SysFontBMB, 0, SysFontBMB->physW-ww, h, ww, (int)FALSE, (int)FALSE);
			else BltBMB(pBM, x+(w-ww)/2, y, SysFontBMB, 0, 0, ww, h, (int)FALSE, (int)FALSE);
		} else if( flags & 64 ) {	/// RIGHT JUSTIFIED
			if( bclr==CLR_NONE ) {
				BltBMB(SysFontBMB, 0, 0, pBM, x+w-ww, y, ww, h, (int)FALSE, (int)FALSE);
				SysFontText(curend, dw, h, fclr);
			}
			if( flags & 128 ) BltBMB(pBM, x, y, SysFontBMB, 0, SysFontBMB->physW-ww, h, ww, (int)FALSE, (int)FALSE);
			else BltBMB(pBM, x+w-ww, y, SysFontBMB, 0, 0, ww, h, (int)FALSE, (int)FALSE);
		} else {					/// LEFT JUSTIFIED
			if( flags & 128 ) BltBMB(pBM, x, y+w-ww, SysFontBMB, 0, SysFontBMB->physW-min(w,ww), h, min(w,ww), (int)FALSE, (int)FALSE);
			else BltBMB(pBM, x, y, SysFontBMB, 0, 0, min(w,ww), h, (int)FALSE, (int)FALSE);
		}
		if( flags & 128 ) {	// rotate our WORK bitmap back
			th = SysFontBMB->logH;
			SysFontBMB->logH = SysFontBMB->logW;
			SysFontBMB->logW = th;
			SysFontBMB->orient = BMO_NORMAL;
			SysFontBMB->clipX1 = SysFontBMB->clipY1 = 0;
			SysFontBMB->clipX2 = SysFontBMB->physW;
			SysFontBMB->clipY2 = SysFontBMB->physH;
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


def patch_pmach_c():
    s = read("pmach.c")

    # BMP file header must be packed to 14 bytes, as <windows.h> does.
    s = replace_once(s, "#if !KINT_MS_WINDOWS\n\ttypedef struct tagBITMAPFILEHEADER",
                     "#if !KINT_MS_WINDOWS\n#pragma pack(push, 2)\n\ttypedef struct tagBITMAPFILEHEADER",
                     "BMP header pack")
    s = replace_once(s, "\t} BITMAPFILEHEADER;\n", "\t} BITMAPFILEHEADER;\n#pragma pack(pop)\n",
                     "BMP header pack end")

    s = replace_once(s, "#include <malloc.h>\n", "", "malloc.h")

    # Smooth (halftone) stretch used GDI StretchBlt; use KINT's own averaging shrink.
    s = replace_between(
        s,
        "\t\t\tif( h & 0x8000 ) {\n\t\t\t\tHDC\thSDC, hDDC;",
        "\t\t\t} else CompressBMB(",
        "\t\t\tif( h & 0x8000 ) {\t/* WEB PORT: was GDI HALFTONE StretchBlt */\n"
        "\t\t\t\tCompressBMB((PBMB)GETREGD(REG_15), (int)(short)GETREGW(REG_39), (int)(short)GETREGW(REG_38),\n"
        "\t\t\t\t\t(int)(short)GETREGW(REG_33), (int)(short)GETREGW(REG_32),\n"
        "\t\t\t\t\t(PBMB)GETREGD(REG_14), (int)(short)GETREGW(REG_37), (int)(short)GETREGW(REG_36),\n"
        "\t\t\t\t\t-((int)(short)w), -((int)(short)h), FALSE);\n",
        "halftone stretch",
    )

    # Clipboard
    s = replace_between(
        s,
        "\t\t case 8:\t// write pMem (0:R15) to ClipBoard as TEXT",
        "\t\t case 10:\t// sprintf",
        "\t\t case 8:\t// write pMem (0:R15) to ClipBoard as TEXT (WEB PORT)\n"
        "\t\t\tKClipboardSet((char*)pMem);\n\t\t\tbreak;\n"
        "\t\t case 9:\t// read Clipboard TEXT to pMem (WEB PORT)\n"
        "\t\t\tKClipboardGet((char*)pMem, GETREGW(REG_39));\n\t\t\tbreak;\n\n",
        "clipboard",
    )

    # Screen size: the platform layer keeps PhysicalScreenW/H current.
    s = replace_between(
        s,
        "\t\tif( hWndMain!=0 ) {\n\t\t\tHMONITOR\thMon;",
        "\t\tSETREGW(REG_39, PhysicalScreenW);",
        "\t\t/* WEB PORT: PhysicalScreenW/H are kept current by kplat.c */\n"
        "\t\t     if( kBuf->logW<800  || kBuf->logH<600 ) PhysicalScreenSizeIndex = 0;\n"
        "\t\telse if( kBuf->logW<1024 || kBuf->logH<768 ) PhysicalScreenSizeIndex = 1;\n"
        "\t\telse if( kBuf->logW<1152 || kBuf->logH<864 ) PhysicalScreenSizeIndex = 2;\n"
        "\t\telse if( kBuf->logW<1280 || kBuf->logH<1024) PhysicalScreenSizeIndex = 3;\n"
        "\t\telse if( kBuf->logW<1600 || kBuf->logH<1280) PhysicalScreenSizeIndex = 4;\n"
        "\t\telse PhysicalScreenSizeIndex = 5;\n\n",
        "screen size",
    )

    # System-font text (GDI) -> browser canvas
    s = replace_between(s, "#define\tNUMSYSFONT\t100", "//#endif // _IS_BB", SYSFONT_PORT, "sysfont")

    write("pmach.c", s)


def patch_djpeg_h():
    # Two callbacks are defined returning int but declared as returning void.
    # x86 tolerates that; WebAssembly traps on a mismatched indirect call.
    s = read("djpeg.h")
    s = replace_once(s, "JMETHOD(void, skip_input_data,", "JMETHOD(int, skip_input_data,", "skip_input_data")
    s = replace_once(s, "JMETHOD(void, prepare_for_output_pass,", "JMETHOD(int, prepare_for_output_pass,",
                     "prepare_for_output_pass")
    write("djpeg.h", s)


def main():
    if GEN.exists():
        shutil.rmtree(GEN)
    GEN.mkdir(parents=True)
    patch_main_h()
    patch_pmach_c()
    patch_djpeg_h()
    for name in ("pmach.h", "float.c", "djpeg.c"):
        write(name, read(name))
    print(f"patched sources written to {GEN.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
