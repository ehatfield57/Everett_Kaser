/*
 * kplat6.c - browser platform layer for the KINT 6 interpreter.
 *
 * Replaces the Windows parts of Everett Kaser's KINT 6 main.c.  The portable
 * parts (loader, message queue, heap) are used unchanged from gen/kmain6.c.
 * JavaScript helpers are in engine/k5/kint_lib.js, shared with KINT 5.
 * Like the KINT 5 port, kp_main() runs the program's message loop forever
 * inside a Web Worker.
 */
#include <emscripten.h>
#include "main.h"

/* ---------------------------------------------------------------- JS side */
extern void  js_poll_input(void);
extern int   js_input_pending(void);
extern void  js_wait(int ms);
extern void  js_sleep(int ms);
extern void  js_post_frame(BYTE *rgba, int x, int y, int w, int h, int cw, int ch);
extern DWORD js_fopen(const char *app, const char *pgm, int oflags);
extern DWORD js_fread(DWORD h, BYTE *p, DWORD n);
extern DWORD js_fwrite(DWORD h, const BYTE *p, DWORD n);
extern DWORD js_fseek(DWORD h, long off, int origin);
extern DWORD js_feof(DWORD h);
extern void  js_fclose(DWORD h);
extern DWORD js_fstat(const char *app, const char *pgm, DWORD *mtime, BYTE *typ);
extern int   js_find(const char *app, const char *pgm, int stripExt);
extern void  js_find_get(int i, char *buf, BYTE *attrib, BYTE *appdata);
extern int   js_mkdir(const char *path);
extern void  js_rmdir(const char *path);
extern void  js_delete(const char *path);
extern void  js_rename(const char *from, const char *to);
extern void  js_sound_file(const char *path);
extern void  js_sound_mem(const BYTE *p, int len, int nostop);
extern int   js_music_play(const char *path);
extern void  js_music_stop(void);
extern void  js_music_pause(int pause);
extern void  js_set_title(const char *s);
extern void  js_set_cursor(int type);
extern void  js_message(const char *s);
extern void  js_clipboard_set(const char *s);
extern void  js_open_url(const char *s);
extern void  js_toupper(char *s);
extern void  js_exit(void);

/* from gen/kmain6.c (Everett's code) */
BOOL LoadKE();
BOOL KEmsg(DWORD msg, DWORD arg1, DWORD arg2, DWORD arg3);
void AddMsg(DWORD cmd, DWORD arg1, DWORD arg2, DWORD arg3);
void SendNextMsg();
extern int	KINTmsgadd, KINTmsgrem;
extern BOOL	InSleep;
extern long	killpgm;

/* Events posted by the page (see play.js) */
enum {
	EV_MOUSEMOVE = 1, EV_MOUSEDOWN, EV_MOUSEUP, EV_WHEEL, EV_HWHEEL,
	EV_KEYDOWN, EV_KEYUP, EV_CHAR, EV_RESIZE, EV_BLUR, EV_MUSICDONE,
	EV_CLOSE, EV_HIDDEN, EV_FOCUS
};

/* ------------------------------------------------------------ globals */
HWND	hWndMain = NULL;
int		MaxScreenW, MaxScreenH, ScreenW, ScreenH, WndW, WndH;
BOOL	MusicPlaying = FALSE;
long	Expired = 0;
BOOL	InScreenUp = FALSE, ScreenDirty = FALSE;
SKBM	scrBM;
long	ClientW, ClientH;
TCHAR	PgmPath[PATHLEN] = "pgm/", AppDataPath[PATHLEN] = "app/", TmpPath[PATHLEN];
TCHAR	OSctrl_cmdSTR[32] = "Ctrl";
DWORD	UTF16buf[512];
BYTE	UTF8buf[1028];

// The paths the game is told about (as the native Mac app would report them).
TCHAR	PgmPathShown[PATHLEN] = "pgm/";
TCHAR	AppDataPathShown[PATHLEN] = "app/";

static BOOL		ProgramReady = FALSE, MinFlag = FALSE, Quit = FALSE;
static double	TicksStart;
static DWORD	TimerPeriod = 0;
static double	TimerNext = 0;
static BYTE		KeyDown[256];
static int		DirtyX1, DirtyY1, DirtyX2, DirtyY2;
static double	LastPresent = 0;
static BYTE		*FrameBuf = NULL;
static size_t	FrameBufLen = 0;
static int		FindCount = 0, FindPos = 0;

static double now_ms(void) { return emscripten_get_now(); }
static BOOL QueueEmpty(void) { return KINTmsgadd == KINTmsgrem; }

/* ============================================================= display */
static void ResetDirty(void) {
	DirtyX1 = DirtyY1 = 0x7FFFFFFF;
	DirtyX2 = DirtyY2 = -0x7FFFFFFF;
}

void KInvalidate(long x1, long y1, long x2, long y2) {
	if( x1 < DirtyX1 ) DirtyX1 = x1;
	if( y1 < DirtyY1 ) DirtyY1 = y1;
	if( x2+1 > DirtyX2 ) DirtyX2 = x2+1;
	if( y2+1 > DirtyY2 ) DirtyY2 = y2+1;
}

static void InvalidateAll(void) {
	KInvalidate(0, 0, ClientW, ClientH);
}

/* Send the changed part of the screen bitmap (32-bit BGRA) to the page. */
static void Present(void) {

	int		x1, y1, x2, y2, w, h, x, y;
	BYTE	*s, *d;
	size_t	need;

	ScreenDirty = FALSE;
	if( scrBM.pBits==NULL || DirtyX2<=DirtyX1 || DirtyY2<=DirtyY1 ) return;
	x1 = max(DirtyX1, 0);  y1 = max(DirtyY1, 0);
	x2 = min(DirtyX2, ClientW); y2 = min(DirtyY2, ClientH);
	x2 = min(x2, scrBM.w); y2 = min(y2, scrBM.h);
	ResetDirty();
	LastPresent = now_ms();
	if( x2<=x1 || y2<=y1 ) return;

	w = x2-x1;
	h = y2-y1;
	need = (size_t)w*h*4;
	if( need > FrameBufLen ) {
		free(FrameBuf);
		FrameBuf = (BYTE *)malloc(need);
		FrameBufLen = FrameBuf ? need : 0;
		if( FrameBuf==NULL ) return;
	}
	d = FrameBuf;
	for(y=y1; y<y2; y++) {
		s = scrBM.pBits + y*scrBM.linelen + x1*4;
		for(x=w; x; --x) {
			d[0] = s[2];
			d[1] = s[1];
			d[2] = s[0];
			d[3] = 255;
			d += 4;
			s += 4;
		}
	}
	js_post_frame(FrameBuf, x1, y1, w, h, ClientW, ClientH);
}

static void MaybePresent(void) {
	if( now_ms()-LastPresent >= 16 ) Present();
}

/* Create the screen bitmap.  The game draws everything into it; the page
   shows the part that fits the browser window. */
static BOOL SetupScreen(int screenW, int screenH, int winW, int winH) {

	ScreenW = screenW;
	ScreenH = screenH;
	MaxScreenW = max(max(screenW, winW), 1024);
	MaxScreenH = max(max(screenH, winH), 768);
	if( !CreateSBM(&scrBM, MaxScreenW, MaxScreenH) ) {
		SystemMessage("Failed creating screen BITMAP.");
		return FALSE;
	}
	InitSysFonts();
	DrawRect(0, 0, 0, MaxScreenW, MaxScreenH, 0xFF000000, 0x00000000);
	return TRUE;
}

/* The browser window was resized (Windows WM_SIZE). */
static void WindowSized(int w, int h) {

	if( !InSleep && ProgramReady ) while( !QueueEmpty() ) SendNextMsg();
	ClientW = min(w, scrBM.w);
	ClientH = min(h, scrBM.h);
	AddMsg(KMSG_WINDOW_SIZED, ClientW, ClientH, K_RESTORED);
	if( ProgramReady ) SendNextMsg();
	InvalidateAll();
}

/* The page cannot move or resize the browser window. */
void KINT_SetWindowPos(DWORD x, DWORD y, DWORD w, DWORD h, DWORD showcmd) {}

void KINT_GetWindowPos(DWORD *x, DWORD *y, DWORD *w, DWORD *h, DWORD *showcmd) {
	*x = 0;
	*y = 0;
	*w = (DWORD)ClientW;
	*h = (DWORD)ClientH;
	*showcmd = 1;	// SW_SHOWNORMAL
}

/* ===================================================== program control */
static void ShutDown(void) {	// what the Windows WM_DESTROY handler does

	if( Quit ) return;
	KEmsg(KMSG_SHUTDOWN, 0, 0, 0);
	if( MusicPlaying ) StopMusic();
	StopTimer();
	FreeSysFonts();
	Quit = TRUE;
}

void KillProgram() {
	ShutDown();
}

long unhandled_handler(void *e) {
	char	buf[256];

	sprintf(buf, "KINT internal error: KPC=%8.8lX KSP=%8.8lX", GETMEMD(KEHED_PC), GETMEMD(KEHED_SP));
	SystemMessage(buf);
	return 0;
}

void SystemMessage(char *pMem) {
	js_message(pMem);
}

void WriteDebug(char *str) {
	printf("KINT debug: %s\n", str);
}

int GetSystemEOL(char *pMem) {
	*pMem++ = '\r';
	*pMem++ = '\n';
	return 2;
}

DWORD KGetOSversion(char *pMem) {
	sprintf(pMem, "KINT %d.%d - web port (WebAssembly in Chrome)", INTERP_MAJORREV, INTERP_MINORREV);
	return 0;	// report "Windows" so the .KE behaves as it does there
}

void DoHTML(char *url) { js_open_url(url); }

void KClipboardSet(const char *text, long len) {
	char	*s = (char *)malloc(len+1);
	if( s==NULL ) return;
	memcpy(s, text, len);
	s[len] = 0;
	js_clipboard_set(s);
	free(s);
}

void KClipboardGet(char *buf, long maxlen) { if( maxlen>0 ) *buf = 0; }
void KToUpperUTF8(char *s) { js_toupper(s); }

DWORD KGetKeyState(DWORD vk) {
	return KeyDown[vk & 0xFF] ? 0xFFFF8000 : 0;	// SHORT with the high bit set, sign-extended
}

void KSetCursor(WORD curtype) { js_set_cursor(curtype); }
void KSetWindowText(char *pStr) { js_set_title(pStr); }
void KSetTitle(BYTE *pMem) { js_set_title((char *)pMem); }
void KCaptureMouse(BOOL cap) {}

/* =============================================================== sound */
void KPlaySound(char *pMem) {
	BuildPath(pMem, FALSE);
	js_sound_file(TmpPath);
}

void KPlaySoundMem(char *pMem, DWORD len, BOOL nostop) {
	js_sound_mem((BYTE *)pMem, (int)len, nostop);
}

/* Length of a .WAV file in milliseconds (+200), as Everett's KSoundMilli(). */
DWORD KSoundMilli(char *pMem) {

	BYTE	buf[512], *p;
	DWORD	fh, n, cs, ds, sr, bps, nc;

	if( 0xFFFFFFFF==(fh=Kopen(pMem, O_RDBIN)) ) return 0;
	n = Kread(fh, buf, sizeof(buf));
	Kclose(fh);
	if( n < 44 || memcmp(buf, "RIFF", 4) || memcmp(buf+8, "WAVEfmt ", 8) ) return 0;
	p = buf+16;
	cs = *(DWORD*)p;			p += 4;
	if( *(WORD*)p != 1 ) return 0;	// PCM only
	nc = *(WORD*)(p+2);
	sr = *(DWORD*)(p+4);
	bps = *(WORD*)(p+14);
	p += cs;
	if( p+8 <= buf+n && !memcmp(p, "fact", 4) ) p += 8 + *(DWORD*)(p+4);
	if( p+8 > buf+n || memcmp(p, "data", 4) ) return 0;
	ds = *(DWORD*)(p+4);
	if( !nc || !bps || !sr ) return 0;
	return 1000*(ds/(nc*(bps/8)))/sr + 200;
}

void PlayMusic(char *pMem) {
	StopMusic();
	BuildPath(pMem, FALSE);
	if( js_music_play(TmpPath) ) MusicPlaying = TRUE;
}

void StopMusic() {
	if( MusicPlaying ) {
		js_music_stop();
		MusicPlaying = FALSE;
	}
}

void PauseMidi(void)  { js_music_pause(1); }
void ResumeMidi(void) { js_music_pause(0); }

/* =============================================================== timer */
void StopTimer() {
	TimerPeriod = 0;
}

void StartTimer(DWORD timval) {
	if( timval==0 ) StopTimer();
	else if( TimerPeriod==0 ) {
		TimerPeriod = timval;
		TimerNext = now_ms() + timval;
	}
}

static BOOL TimerDue(void) {
	return TimerPeriod && now_ms() >= TimerNext;
}

DWORD KGetTicks() {
	return (DWORD)(now_ms() - TicksStart);
}

void KSleep(DWORD tm) {
	Present();	// a 0ms sleep just lets the screen update
	if( tm==0 ) return;
	InSleep = TRUE;
	js_sleep((int)tm);
	InSleep = FALSE;
}

void KGetTime(KTIME *pT) {

	time_t		t = time(NULL);
	struct tm	*lt = localtime(&t);

	pT->y = (WORD)(lt->tm_year+1900);
	pT->mo= (WORD)(lt->tm_mon+1);
	pT->d = (WORD)lt->tm_mday;
	pT->h = (WORD)lt->tm_hour;
	pT->mi= (WORD)lt->tm_min;
	pT->s = (WORD)lt->tm_sec;
}

void KTimeToString(BYTE *pMem) {

	KTIME	t;

	KGetTime(&t);
	sprintf((char *)pMem, "%4.4d-%2.2d-%2.2d %2.2d:%2.2d:%2.2d", t.y, t.mo, t.d, t.h, t.mi, t.s);
}

/* =============================================================== files */
/* "pgm/" (game files) and "app/" (saved files) are resolved by server.py. */
void BuildPath(char *pMem, BOOL AppData) {

	char	*p;

	strcpy(TmpPath, AppData ? AppDataPath : PgmPath);
	strncat(TmpPath, pMem, PATHLEN - strlen(TmpPath) - 1);
	for(p=TmpPath; *p; p++) if( *p=='\\' ) *p = '/';
}

static void BuildBoth(char *fname, char *app) {
	BuildPath(fname, TRUE);
	strcpy(app, TmpPath);
	BuildPath(fname, FALSE);
}

DWORD Kopen(char *fname, int oflags) {
	char	app[PATHLEN];

	BuildBoth(fname, app);
	return js_fopen(app, TmpPath, oflags);
}

DWORD Kstat(char *fname, QWORD *modtim, BYTE *filtyp) {
	char	app[PATHLEN];
	DWORD	mt = 0, len;

	BuildBoth(fname, app);
	len = js_fstat(app, TmpPath, &mt, filtyp);
	*modtim = mt;
	return len;
}

DWORD Kseek(DWORD fhandle, DWORD foffset, int origin) { return js_fseek(fhandle, (long)foffset, origin); }
void  Kclose(DWORD fhandle) { js_fclose(fhandle); }
DWORD Keof(DWORD fhandle) { return js_feof(fhandle); }
DWORD Kread(DWORD fhandle, BYTE *pMem, DWORD numbytes) { return js_fread(fhandle, pMem, numbytes); }
DWORD Kwrite(DWORD fhandle, BYTE *pMem, DWORD numbytes) { return js_fwrite(fhandle, pMem, numbytes); }

void Kfindclose() {
	FindCount = FindPos = 0;
}

DWORD Kfindnext(BYTE *fbuf, long *attrib, long *appdata) {
	BYTE	at, ad;

	if( FindPos < FindCount ) {
		js_find_get(FindPos++, (char *)fbuf, &at, &ad);
		if( attrib!=NULL ) *attrib = at;
		if( appdata!=NULL ) *appdata = ad;
		return 0;
	}
	return 0xFFFFFFFF;
}

DWORD Kfindfirst(char *fname, BYTE *fbuf, long *attrib, long *appdata) {
	char	app[PATHLEN];

	Kfindclose();
	BuildBoth(fname, app);
	FindCount = js_find(app, TmpPath, 0);
	FindPos = 0;
	return Kfindnext(fbuf, attrib, appdata);
}

void Kdelete(char *fname) {
	BuildPath(fname, TRUE);
	js_delete(TmpPath);
}

void Krename(char *fname, char *tname) {
	char	to[PATHLEN];

	BuildPath(tname, TRUE);
	strcpy(to, TmpPath);
	BuildPath(fname, TRUE);
	js_rename(TmpPath, to);
}

int KMakeFolder(char *fname) {
	BuildPath(fname, TRUE);
	return js_mkdir(TmpPath);
}

void KDelFolder(char *fname) {
	BuildPath(fname, TRUE);
	js_rmdir(TmpPath);
}

/* ================================================================ input */
static DWORD PackXY(int x, int y) {
	return ((DWORD)(WORD)(short)x) | (((DWORD)(WORD)(short)y)<<16);
}

/* Called by kint_lib.js for each input event from the page. */
EMSCRIPTEN_KEEPALIVE void kp_event(int type, int a, int b, int c, int d) {

	static const DWORD btnVK[3] = { VK_LBUTTON, VK_MBUTTON, VK_RBUTTON };
	BYTE	u[8];
	int		cp;

	if( scrBM.pBits==NULL || Quit ) return;
	switch( type ) {
	 case EV_MOUSEMOVE:	// a=x b=y c=button/modifier flags (MK_xxx)
		if( !InSleep ) AddMsg(KMSG_POINTER_MOVE, (DWORD)(long)(short)a, (DWORD)(long)(short)b, (DWORD)c);
		break;
	 case EV_MOUSEDOWN:	// a=button(0 left,1 middle,2 right) b=x c=y d=flags
		if( a>=0 && a<3 ) {
			KeyDown[btnVK[a]] = 1;
			if( !InSleep ) AddMsg(KMSG_KEY_DOWN, btnVK[a], (DWORD)d, PackXY(b, c));
		}
		break;
	 case EV_MOUSEUP:
		if( a>=0 && a<3 ) {
			KeyDown[btnVK[a]] = 0;
			if( !InSleep ) AddMsg(KMSG_KEY_UP, btnVK[a], (DWORD)d, PackXY(b, c));
		}
		break;
	 case EV_WHEEL:		// a=clicks (+ away from user) b=x c=y
		if( !InSleep ) AddMsg(KMSG_KEY_DOWN, 0x00008003, (DWORD)(long)a, PackXY(b, c));
		break;
	 case EV_HWHEEL:
		if( !InSleep ) AddMsg(KMSG_KEY_DOWN, 0x00008004, (DWORD)(long)a, PackXY(b, c));
		break;
	 case EV_KEYDOWN:	// a=VK code
		KeyDown[a & 0xFF] = 1;
		AddMsg(KMSG_KEY_DOWN, (DWORD)a, 1, 0);
		break;
	 case EV_KEYUP:
		KeyDown[a & 0xFF] = 0;
		AddMsg(KMSG_KEY_UP, (DWORD)a, 1, 0);
		break;
	 case EV_CHAR:		// a=Unicode code point; KINT 6 wants it as UTF-8 bytes in arg1/arg2
		cp = a;
		if( cp < 0x20 ) break;
		memset(u, 0, sizeof(u));
		if( cp < 0x80 ) u[0] = (BYTE)cp;
		else if( cp < 0x800 ) { u[0] = 0xC0 | (cp>>6); u[1] = 0x80 | (cp & 0x3F); }
		else if( cp < 0x10000 ) { u[0] = 0xE0 | (cp>>12); u[1] = 0x80 | ((cp>>6) & 0x3F); u[2] = 0x80 | (cp & 0x3F); }
		else { u[0] = 0xF0 | (cp>>18); u[1] = 0x80 | ((cp>>12) & 0x3F); u[2] = 0x80 | ((cp>>6) & 0x3F); u[3] = 0x80 | (cp & 0x3F); }
		AddMsg(KMSG_CHAR, *(DWORD*)u, *(DWORD*)(u+4), 1);
		break;
	 case EV_RESIZE:	// a=width b=height (CSS pixels)
		if( a>0 && b>0 ) WindowSized(a, b);
		break;
	 case EV_BLUR:		// like WM_KILLFOCUS + WM_ACTIVATEAPP
		memset(KeyDown, 0, sizeof(KeyDown));
		AddMsg(KMSG_FOCUS, 0, 0, 0);
		AddMsg(KMSG_KEY_UP, 0xF5, 1, 0);
		break;
	 case EV_FOCUS:
		AddMsg(KMSG_FOCUS, 1, 0, 0);
		break;
	 case EV_MUSICDONE:
		if( MusicPlaying ) {
			MusicPlaying = FALSE;
			AddMsg(KMSG_MUSIC_DONE, 0, 0, 0);
		}
		break;
	 case EV_CLOSE:		// the player asked to close the game
		if( KEmsg(KMSG_QUERY_QUIT, 0, 0, 0) ) ShutDown();
		break;
	 case EV_HIDDEN:	// a=1 tab hidden, 0 visible again
		if( a && !MinFlag ) { MinFlag = TRUE; AddMsg(KMSG_WINDOW_HIDDEN, 1, 0, 0); if( MusicPlaying ) PauseMidi(); }
		else if( !a && MinFlag ) { MinFlag = FALSE; AddMsg(KMSG_WINDOW_HIDDEN, 0, 0, 0); ResumeMidi(); }
		break;
	}
}

/* ============================================================ main loop */
EMSCRIPTEN_KEEPALIVE void kp_set_paths(const char *pgmShown, const char *appShown) {
	strncpy(PgmPathShown, pgmShown, PATHLEN-1);
	strncpy(AppDataPathShown, appShown, PATHLEN-1);
}

/* Beta-test games: the date (y/m/d) from which the game no longer runs, or
   0/0/0 if not known.  Like the Mac beta interpreter, it then refuses to start. */
int KBetaBuild = 0;
static int BetaY, BetaM, BetaD;
EMSCRIPTEN_KEEPALIVE void kp_set_beta(int y, int m, int d) {
	KBetaBuild = 1;
	BetaY = y; BetaM = m; BetaD = d;
}

static BOOL BetaExpired(void) {
	KTIME	t;

	if( !KBetaBuild || !BetaY ) return FALSE;
	KGetTime(&t);
	return t.y*10000 + t.mo*100 + t.d >= BetaY*10000 + BetaM*100 + BetaD;
}

EMSCRIPTEN_KEEPALIVE int kp_main(int screenW, int screenH, int winW, int winH) {

	if( BetaExpired() ) return 4;
	ResetDirty();
	if( !LoadKE() ) return 2;
	if( !SetupScreen(screenW, screenH, winW, winH) ) return 3;
	TicksStart = now_ms();

	KEmsg(KMSG_BEGIN_STARTUP, 0, 0, 0);
	ClientW = min(winW, scrBM.w);	// the "window" is the browser tab
	ClientH = min(winH, scrBM.h);
	KEmsg(KMSG_END_STARTUP, 0, 0, 0);
	WindowSized(winW, winH);		// ShowWindow() sends WM_SIZE and WM_SETFOCUS
	AddMsg(KMSG_FOCUS, 1, 0, 0);
	ProgramReady = TRUE;

	while( !Quit ) {
		js_poll_input();
		while( !Quit && !QueueEmpty() ) {
			SendNextMsg();
			js_poll_input();
			MaybePresent();
		}
		if( Quit ) break;
		if( InScreenUp ) {	// the program paused so the screen could update (PAUSE opcode)
			Present();
			InScreenUp = FALSE;
			js_poll_input();	// input that arrived meanwhile goes ahead of RESUME, as on Windows
			AddMsg(KMSG_RESUME, 0, 0, 0);
			continue;
		}
		if( TimerDue() ) {	// like WM_TIMER: only one pending at a time
			TimerNext = now_ms() + TimerPeriod;
			AddMsg(KMSG_TIMER, 0, 0, 0);
			continue;
		}
		if( js_input_pending() ) continue;
		// nothing to do: show the screen and wait for input or the timer
		Present();
		if( TimerPeriod ) {
			int wait = (int)(TimerNext - now_ms());
			if( wait > 0 ) js_wait(wait);
		} else {
			js_wait(-1);
		}
	}
	Present();
	js_exit();
	return 0;
}
