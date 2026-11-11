/*
 * kplat.c - browser platform layer for the KINT 5 interpreter.
 *
 * This replaces Everett Kaser's Windows main.c.  The interpreter (pmach.c)
 * calls these functions for screen, files, sound, timers and input.  The
 * actual browser work is done by JavaScript in kint_lib.js, which runs
 * inside a Web Worker.  The worker never returns to the browser event loop:
 * kp_main() runs the program's message loop forever, the same way the
 * Windows message pump does.
 *
 * Message queue, idle handling, coordinate translation and path building
 * follow Everett's main.c closely so the .KE code sees the same behaviour.
 */
#include <emscripten.h>
#include <time.h>
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
extern void  js_sound_file(const char *path);
extern void  js_sound_mem(const BYTE *p, int len, int nostop);
extern int   js_music_play(const char *path);
extern void  js_music_stop(void);
extern void  js_music_pause(int pause);
extern void  js_set_title(const char *s);
extern void  js_set_cursor(int type);
extern void  js_message(const char *s);
extern void  js_clipboard_set(const char *s);
extern void  js_exit(void);

/* ---------------------------------------------------- KINT message codes */
/* Windows virtual-key codes used for the mouse buttons */
#define VK_LBUTTON  0x01
#define VK_RBUTTON  0x02
#define VK_MBUTTON  0x04
#define VK_LEFT     0x25
#define VK_UP       0x26
#define VK_RIGHT    0x27
#define VK_DOWN     0x28

/* Events posted by the page (see play.js) */
enum {
	EV_MOUSEMOVE = 1, EV_MOUSEDOWN, EV_MOUSEUP, EV_WHEEL, EV_HWHEEL,
	EV_KEYDOWN, EV_KEYUP, EV_CHAR, EV_RESIZE, EV_BLUR, EV_MUSICDONE,
	EV_CLOSE, EV_HIDDEN
};

#define	MAXMSGS		1024	// max messages queued at a time in KINTmsgs

/* ------------------------------------------------------------ globals */
char	OSctrl_cmdSTR[32] = "Ctrl";

extern PBMB	kBuf, pbFirst;
extern BYTE	Kregs[256];

KE		mainKE;
DWORD	*KINTmsgs=NULL;
int		KINTmsgadd=0, KINTmsgrem=0;

int		PhysicalScreenW, PhysicalScreenH, PhysicalScreenSizeIndex;
WORD	MinFlag=FALSE, MusicPlaying=FALSE;
BOOL	ProgramReady=FALSE, InSetWindowPos=FALSE, InSleep=FALSE;
int		CurCur=0;

TCHAR	PgmPath[PATHLEN]     = "pgm/";	// the game's own (read-only) files
TCHAR	AppDataPath[PATHLEN] = "app/";	// the player's saved files
TCHAR	TmpPath[PATHLEN];
TCHAR	PartPath[PATHLEN];

static double	TicksStart;
static DWORD	TimerPeriod=0;			// 0 = timer off
static double	TimerNext=0;
static BOOL		Quit=FALSE;

static int		DirtyX1, DirtyY1, DirtyX2, DirtyY2;	// pending screen update (exclusive x2/y2)
static double	LastPresent=0;
static BYTE		*FrameBuf=NULL;
static size_t	FrameBufLen=0;

static int		FindCount=0, FindPos=0;

static double now_ms(void) { return emscripten_get_now(); }

/* ======================================================== message queue */
BOOL KeyMsg(DWORD *cmd, DWORD *arg1, DWORD *arg2, DWORD *arg3) {

	DWORD	p, s, d, i;

	js_poll_input();	// on Windows the queue fills asynchronously; here we pull new input now
	if( KINTmsgs!=NULL ) {	// first trash all messages we want trashed
		p = KINTmsgrem;
		while( p != KINTmsgadd ) {
			*cmd = KINTmsgs[p*4];
			*arg1=KINTmsgs[p*4+1];
			*arg2=KINTmsgs[p*4+2];
			*arg3=KINTmsgs[p*4+3];
			if( *cmd==KHDR_POINTER_MOVE || *cmd==KHDR_TIMER || *cmd==KHDR_IDLE ) {
				d = p;
				s = p+1;
				if( s >= MAXMSGS ) s = 0;
				while( s!=KINTmsgadd ) {	// trash this message, close the hole
					for(i=0; i<4; i++) KINTmsgs[d*4+i] = KINTmsgs[s*4+i];
					if( ++d >= MAXMSGS ) d = 0;
					if( ++s >= MAXMSGS ) s = 0;
				}
				if( KINTmsgadd==0 ) KINTmsgadd = MAXMSGS-1;
				else --KINTmsgadd;
			} else ++p;
		}
	}
	if( KINTmsgs!=NULL ) {	// now find first KEY msg
		p = KINTmsgrem;
		while( p != KINTmsgadd ) {
			*cmd = KINTmsgs[p*4];
			*arg1=KINTmsgs[p*4+1];
			*arg2=KINTmsgs[p*4+2];
			*arg3=KINTmsgs[p*4+3];
			if( *cmd==KHDR_KEY_DOWN || *cmd==KHDR_KEY_UP ) {
				d = p;
				s = p+1;
				if( s >= MAXMSGS ) s = 0;
				while( s!=KINTmsgadd ) {	// trash this message, close the hole
					for(i=0; i<4; i++) KINTmsgs[d*4+i] = KINTmsgs[s*4+i];
					if( ++d >= MAXMSGS ) d = 0;
					if( ++s >= MAXMSGS ) s = 0;
				}
				if( KINTmsgadd==0 ) KINTmsgadd = MAXMSGS-1;
				else --KINTmsgadd;
				return TRUE;
			} else ++p;
		}
	}
	return FALSE;
}

void AddMsg(WORD cmd, DWORD arg1, DWORD arg2, DWORD arg3) {

	if( !InSleep && KINTmsgs!=NULL ) {
		KINTmsgs[KINTmsgadd*4] = (DWORD)cmd;
		KINTmsgs[KINTmsgadd*4+1] = arg1;
		KINTmsgs[KINTmsgadd*4+2] = arg2;
		KINTmsgs[KINTmsgadd*4+3] = arg3;
		++KINTmsgadd;
		if( KINTmsgadd >= MAXMSGS ) KINTmsgadd = 0;
		if( KINTmsgadd == KINTmsgrem ) {
			--KINTmsgadd;
			if( KINTmsgadd < 0 ) KINTmsgadd = MAXMSGS-1;
		}
	} else {
		KEmsg(&mainKE, cmd, arg1, arg2, arg3);
	}
}

void SendNextMsg() {

	if( !InSleep && KINTmsgs!=NULL && KINTmsgrem != KINTmsgadd ) {
		KEmsg(&mainKE, (WORD)KINTmsgs[KINTmsgrem*4], KINTmsgs[KINTmsgrem*4+1], KINTmsgs[KINTmsgrem*4+2], KINTmsgs[KINTmsgrem*4+3]);
		++KINTmsgrem;
		if( KINTmsgrem >= MAXMSGS ) KINTmsgrem = 0;
	}
}

static BOOL QueueEmpty(void) { return KINTmsgs==NULL || KINTmsgadd==KINTmsgrem; }

/* ====================================================== screen rotation */
/* Translate window x/y into KINT coordinates, allowing for screen rotation. */
static DWORD FixXY(int x, int y) {

	DWORD	r;

	switch( kBuf->orient ) {
	 case BMO_NORMAL:	r = (DWORD)((x) & 0xFFFF) | (((DWORD)(y))<<16); break;
	 case BMO_180:		r = (DWORD)((kBuf->logW-1-x) & 0xFFFF) | (((DWORD)(kBuf->logH-1-y))<<16); break;
	 case BMO_90:		r = (DWORD)((kBuf->logW-1-y) & 0xFFFF) | (((DWORD)(x))<<16); break;
	 case BMO_270:		r = (DWORD)((y) & 0xFFFF) | (((DWORD)(kBuf->logH-1-x))<<16); break;
	 case BMO_FNORMAL:	r = (DWORD)((kBuf->logW-1-x) & 0xFFFF) | (((DWORD)(y))<<16); break;
	 case BMO_F180:		r = (DWORD)((x) & 0xFFFF) | (((DWORD)(kBuf->logH-1-y))<<16); break;
	 case BMO_F90:		r = (DWORD)((kBuf->logW-1-y) & 0xFFFF) | (((DWORD)(kBuf->logH-1-x))<<16); break;
	 case BMO_F270:		r = (DWORD)((y) & 0xFFFF) | (((DWORD)(x))<<16); break;
	 default:			SOerr(kBuf); return 0;
	}
	return r;
}

/* Translate up/down/left/right arrow keys for screen rotation */
static DWORD MapCursor(DWORD vk) {

	switch( kBuf->orient ) {
	 case BMO_180:
		if( vk==VK_LEFT ) vk = VK_RIGHT; else if( vk==VK_RIGHT ) vk = VK_LEFT;
		else if( vk==VK_UP ) vk = VK_DOWN; else if( vk==VK_DOWN ) vk = VK_UP;
		break;
	 case BMO_90:
		if( vk==VK_LEFT ) vk = VK_UP; else if( vk==VK_RIGHT ) vk = VK_DOWN;
		else if( vk==VK_UP ) vk = VK_RIGHT; else if( vk==VK_DOWN ) vk = VK_LEFT;
		break;
	 case BMO_270:
		if( vk==VK_LEFT ) vk = VK_DOWN; else if( vk==VK_RIGHT ) vk = VK_UP;
		else if( vk==VK_UP ) vk = VK_LEFT; else if( vk==VK_DOWN ) vk = VK_RIGHT;
		break;
	 case BMO_FNORMAL:
		if( vk==VK_LEFT ) vk = VK_RIGHT; else if( vk==VK_RIGHT ) vk = VK_LEFT;
		break;
	 case BMO_F180:
		if( vk==VK_UP ) vk = VK_DOWN; else if( vk==VK_DOWN ) vk = VK_UP;
		break;
	 case BMO_F90:
		if( vk==VK_LEFT ) vk = VK_DOWN; else if( vk==VK_RIGHT ) vk = VK_UP;
		else if( vk==VK_UP ) vk = VK_RIGHT; else if( vk==VK_DOWN ) vk = VK_LEFT;
		break;
	 case BMO_F270:
		if( vk==VK_LEFT ) vk = VK_UP; else if( vk==VK_RIGHT ) vk = VK_DOWN;
		else if( vk==VK_UP ) vk = VK_LEFT; else if( vk==VK_DOWN ) vk = VK_RIGHT;
		break;
	}
	return vk;
}

/* ============================================================= display */
static void ClientSize(int *cw, int *ch) {
	if( kBuf->orient & BMO_90 ) { *cw = kBuf->logH; *ch = kBuf->logW; }
	else { *cw = kBuf->logW; *ch = kBuf->logH; }
}

/* Send the changed part of the screen bitmap to the page. */
static void Present(void) {

	int		cw, ch, x1, y1, x2, y2, w, h, x, y;
	BYTE	*s, *d;
	size_t	need;

	if( kBuf==NULL || DirtyX2<=DirtyX1 || DirtyY2<=DirtyY1 ) return;
	ClientSize(&cw, &ch);
	x1 = max(DirtyX1, 0);  y1 = max(DirtyY1, 0);
	x2 = min(DirtyX2, cw); y2 = min(DirtyY2, ch);
	x2 = min(x2, (int)kBuf->physW); y2 = min(y2, (int)kBuf->physH);
	DirtyX1 = DirtyY1 = 0x7FFFFFFF;
	DirtyX2 = DirtyY2 = -0x7FFFFFFF;
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
	for(y=y1; y<y2; y++) {	// screen bitmap is 24-bit BGR, canvas wants RGBA
		s = kBuf->pBits + y*kBuf->linelen + x1*3;
		for(x=w; x; --x) {
			d[0] = s[2];
			d[1] = s[1];
			d[2] = s[0];
			d[3] = 255;
			d += 4;
			s += 3;
		}
	}
	js_post_frame(FrameBuf, x1, y1, w, h, cw, ch);
}

static void MaybePresent(void) {
	if( now_ms()-LastPresent >= 16 ) Present();
}

static void InvalidateAll(void) {
	int cw, ch;
	ClientSize(&cw, &ch);
	DirtyX1 = 0; DirtyY1 = 0; DirtyX2 = cw; DirtyY2 = ch;
}

void InvalidateScreen(int x1, int y1, int x2, int y2) {

	int		t, l, tp, r, b;

	if( x1>x2 ) { t = x1; x1 = x2; x2 = t; }
	if( y1>y2 ) { t = y1; y1 = y2; y2 = t; }
	switch( kBuf->orient ) {
	 case BMO_NORMAL:	l = x1; tp = y1; r = x2; b = y2; break;
	 case BMO_180:		l = kBuf->logW-x2; tp = kBuf->logH-y2; r = kBuf->logW-x1; b = kBuf->logH-y1; break;
	 case BMO_90:		l = y1; tp = kBuf->logW-x2; r = y2; b = kBuf->logW-x1; break;
	 case BMO_270:		l = kBuf->logH-y2; tp = x1; r = kBuf->logH-y1; b = x2; break;
	 case BMO_FNORMAL:	l = kBuf->logW-x2; tp = y1; r = kBuf->logW-x1; b = y2; break;
	 case BMO_F180:		l = x1; tp = kBuf->logH-y2; r = x2; b = kBuf->logH-y1; break;
	 case BMO_F90:		l = kBuf->logH-y2; tp = kBuf->logW-x2; r = kBuf->logH-y1; b = kBuf->logW-x1; break;
	 case BMO_F270:		l = y1; tp = x1; r = y2; b = x2; break;
	 default:			SOerr(kBuf); return;
	}
	// be generous by one pixel: callers aren't consistent about inclusive/exclusive edges
	--l; --tp; r += 2; b += 2;
	if( l < DirtyX1 ) DirtyX1 = l;
	if( tp < DirtyY1 ) DirtyY1 = tp;
	if( r > DirtyX2 ) DirtyX2 = r;
	if( b > DirtyY2 ) DirtyY2 = b;
}

void FlushScreen() {
	Present();
}

PBMB CreateBMB(WORD w, WORD h, WORD sysBM) {

	PBMB	pX;

	pX = (PBMB)malloc(sizeof(BMB));
	if( pX!=NULL ) {
		pX->linelen = 4*((3*w+3)/4);	// force line of pixels to take even number of DWORDS
		if( NULL==(pX->pBits=(BYTE *)malloc((size_t)pX->linelen*h)) ) {
			free(pX);
			return NULL;
		}
		pX->pAND = NULL;
		pX->pNext = (void *)pbFirst;
		if( pbFirst!=NULL ) pbFirst->pPrev = (void *)pX;
		pX->pPrev = NULL;
		pbFirst = pX;
		pX->physW = w;
		pX->physH = h;
		pX->clipX1 = pX->clipY1 = 0;
		pX->clipX2 = (int)w;
		pX->clipY2 = (int)h;
		pX->logW = w;
		pX->logH = h;
		pX->orient = BMO_NORMAL;
	}
	return pX;
}

void DeleteBMB(PBMB pX) {

	if( pX!=NULL ) {
		if( pX->pAND!= NULL ) free(pX->pAND);
		if( pX->pBits != NULL ) free(pX->pBits);
		if( pX==pbFirst ) {
			pbFirst = (PBMB)pX->pNext;
			if( pbFirst!=NULL ) pbFirst->pPrev = NULL;
		} else {
			if( pX->pNext!=NULL ) ((PBMB)pX->pNext)->pPrev = pX->pPrev;
			if( pX->pPrev!=NULL ) ((PBMB)pX->pPrev)->pNext = pX->pNext;
		}
		free(pX);
	}
}

void InitScreen(long minW, long minH) {

	int		redraw;
	WORD	o, ow, oh;

	if( minW==-1 ) {
		ow = kBuf->logW;
		oh = kBuf->logH;
		minW = minH = 0;
	} else {
		ow = (WORD)minW;
		oh = (WORD)minH;
	}
	if( kBuf!=NULL ) {
		DeleteBMB(kBuf);
		redraw = 1;
	} else redraw = 0;

	if( PhysicalScreenW > minW ) minW = PhysicalScreenW;
	if( PhysicalScreenH > minH ) minH = PhysicalScreenH;

	if( 3*1024 > minW ) minW = 3*1024;
	if( 2*1024 > minH ) minH = 2*1024;

	kBuf = CreateBMB((WORD)minW, (WORD)minH, TRUE);
	if( NULL==kBuf ) {
		SystemMessage("Failed creating screen BITMAP");
		Quit = TRUE;
		return;
	}
		 if( kBuf->logW<800  || kBuf->logH<600 ) PhysicalScreenSizeIndex = 0;
	else if( kBuf->logW<1024 || kBuf->logH<768 ) PhysicalScreenSizeIndex = 1;
	else if( kBuf->logW<1152 || kBuf->logH<864 ) PhysicalScreenSizeIndex = 2;
	else if( kBuf->logW<1280 || kBuf->logH<1024) PhysicalScreenSizeIndex = 3;
	else if( kBuf->logW<1600 || kBuf->logH<1280) PhysicalScreenSizeIndex = 4;
	else PhysicalScreenSizeIndex = 5;

	// initialize the ENTIRE screen bitmap to black
	o = kBuf->orient;
	kBuf->orient = BMO_NORMAL;
	RectBMB(0, 0, 0, kBuf->physW, kBuf->physH, 0x00000000, -1);
	kBuf->orient = o;

	kBuf->logW = ow;
	kBuf->logH = oh;

	if( redraw ) {
		AddMsg(KHDR_SCREEN_CHANGE, 0, 0, 0);
		SendNextMsg();
	}
}

void MakePalette() {}
void DestroyPalette() {}

/* The browser window was resized (Windows WM_SIZE). */
static void WindowSized(int w, int h) {

	if( !InSleep && ProgramReady && !InSetWindowPos ) while( !QueueEmpty() ) SendNextMsg();
	if( kBuf->orient & BMO_90 ) {
		kBuf->logW = (WORD)h;
		kBuf->logH = (WORD)w;
	} else {
		kBuf->logW = (WORD)w;
		kBuf->logH = (WORD)h;
	}
	if( kBuf->logW > kBuf->physW || kBuf->logH > kBuf->physH ) InitScreen(kBuf->logW, kBuf->logH);
	AddMsg(KHDR_WINDOW_SIZE, kBuf->logW, kBuf->logH, K_RESTORED);
	if( ProgramReady ) SendNextMsg();
	InvalidateAll();
}

/* The page cannot move or resize the browser window, so these are no-ops
   apart from reporting the current size. */
void KINT_SetWindowPos(DWORD r11, DWORD r12, DWORD r13, DWORD r14, DWORD r15) {}

void KINT_GetWindowPos(DWORD *r11, DWORD *r12, DWORD *r13, DWORD *r14, DWORD *r15) {
	int cw, ch;
	*r11 = 1;	// SW_SHOWNORMAL
	if( kBuf==NULL ) return;
	ClientSize(&cw, &ch);
	*r15 = 0;
	*r14 = 0;
	*r13 = (DWORD)cw;
	*r12 = (DWORD)ch;
}

/* ===================================================== program control */
static void ShutDown(void) {	// what the Windows WM_DESTROY handler does

	if( Quit ) return;
	if( MusicPlaying ) StopMusic();
	StopTimer();
	while( !QueueEmpty() ) SendNextMsg();
	KEmsg(&mainKE, KHDR_SHUT_DOWN, 0, 0, 0);
	SysCleanup();
	Quit = TRUE;
}

void KillProgram() {
	ShutDown();
}

void SystemMessage(char *pMem) {
	js_message(pMem);
}

int GetSystemEOL(BYTE *pMem) {
	*pMem++ = '\r';
	*pMem++ = '\n';
	return 2;
}

DWORD KGetOSversion(BYTE *pMem) {
	sprintf((char*)pMem, "KINT %d.%d - web port (WebAssembly in Chrome)", INTERP_MAJOR_REV, INTERP_MINOR_REV);
	return 0;	// report "Windows" so the .KE behaves as it does there
}

void KClipboardSet(const char *text) { js_clipboard_set(text); }
void KClipboardGet(char *buf, int maxlen) { if( maxlen>0 ) *buf = 0; }

void KSetCursor(WORD curtype) {
	CurCur = curtype;
	js_set_cursor(curtype);
}

void KSetTitle(BYTE *pMem) { js_set_title((char *)pMem); }
void KCaptureMouse(BOOL cap) {}

/* =============================================================== sound */
void KPlaySound(char *pMem) {
	BuildPath(pMem, DIR_SOUNDS, FALSE);
	js_sound_file(TmpPath);
}

void KPlaySoundMem(char *pMem, DWORD len, BOOL nostop) {
	js_sound_mem((BYTE *)pMem, (int)len, nostop);
}

void PlayMusic(char *pMem) {
	StopMusic();
	BuildPath(pMem, DIR_MUSIC, FALSE);
	if( js_music_play(TmpPath) ) MusicPlaying = 1;
}

void StopMusic() {
	if( MusicPlaying ) {
		js_music_stop();
		MusicPlaying = 0;
	}
}

void PauseMidi(void)  { js_music_pause(1); }
void ResumeMidi(void) { js_music_pause(0); }

/* =============================================================== timer */
void StartTimer(DWORD timval) {
	if( TimerPeriod==0 ) {
		TimerPeriod = timval ? timval : 1;
		TimerNext = now_ms() + TimerPeriod;
	}
}

void StopTimer() {
	TimerPeriod = 0;
}

static BOOL TimerDue(void) {
	return TimerPeriod && now_ms() >= TimerNext;
}

DWORD KGetTicks() {
	return (DWORD)(now_ms() - TicksStart);
}

void KSleep(DWORD tm) {
	Present();	// show what was drawn before pausing
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

/* ============================================================== printing */
DWORD KPrintStart(DWORD *pw, DWORD *ph, DWORD *Xppi, DWORD *Yppi) {
	SystemMessage("Printing is not available in the browser version.");
	return 0;
}
void KPrintStop() {}
BYTE KPrintBeginPage() { return 0; }
BYTE KPrintEndPage() { return 0; }
void KPrintText(int x, int y, char *str, DWORD clr) {}
void KPrintGetTextSize(char *str, DWORD *dw, DWORD *dh, DWORD *dasc) { *dw = *dh = *dasc = 0; }
void KPrintBMB(int xd, int yd, int wd, int hd, PBMB bmS, int xs, int ys, int ws, int hs) {}
void KPrintRect(int xd, int yd, int wd, int hd, DWORD fillcolor, DWORD edgecolor) {}
void KPrintFont(WORD hlim, WORD flags, WORD *h, WORD *asc) { *h = *asc = 0; }
void KPrintLines(DWORD *pMem, WORD numpoints, DWORD clr) {}

/* =============================================================== files */
/* Don't allow access above the game folder: no absolute paths, '..' or '//'. */
char *GetFileName(char *fname, char *xname) {

	char	*p;

	if( fname[0]=='\\' || fname[0]=='/' ) return NULL;
	strcpy(PartPath, fname);
	for(p=PartPath; *p; p++) {
		if( (*p=='.' && *(p+1)=='.')
		 || (*p=='/' && *(p+1)=='/')
		 || (*p==':')
		) return NULL;
		if( *p=='\\' ) *p = '/';
	}
	strcat(PartPath, xname);
	return PartPath;
}

static void AddName(const char *dir, char *name, BYTE folder, BOOL plain) {
	if( dir ) strcat(TmpPath, dir);
	if( plain ) {
		char *p = GetFileName(name, "");
		strcat(TmpPath, p ? p : "?invalid?");
	} else {
		strcat(TmpPath, name);
	}
}

static void AddExt(BYTE folder, const char *ext) {
	if( !(folder & DIR_NOEXT) ) {
		if( ext ) strcat(TmpPath, ext);
		else strcat(TmpPath, (folder & DIR_LOSSY) ? ".JPG" : ".BMP");
	}
}

/* Build the full file path in TmpPath (same folder rules as Everett's main.c).
   The "pgm/" and "app/" roots are resolved by the Python server. */
void BuildPath(char *pMem, BYTE folder, BOOL AppData) {

	strcpy(TmpPath, AppData ? AppDataPath : PgmPath);
	switch( folder & 0x0F ) {
	 case DIR_GAME:		AddName(NULL, pMem, folder, TRUE); break;
	 case DIR_UI:		AddName("UI/", pMem, folder, FALSE); AddExt(folder, NULL); break;
	 case DIR_IMAGES:	AddName("IMAGES/", pMem, folder, FALSE); AddExt(folder, NULL); break;
	 case DIR_BACKGNDS:	AddName("BACKGNDS/", pMem, folder, FALSE); AddExt(folder, NULL); break;
	 case DIR_MUSIC:	AddName("../MUSIC/", pMem, folder, FALSE); AddExt(folder, ".MID"); break;
	 case DIR_SOUNDS:	AddName(NULL, pMem, folder, TRUE); AddExt(folder, ".WAV"); break;
	 case DIR_GAME_IMG:	AddName(NULL, pMem, folder, TRUE); AddExt(folder, NULL); break;
	 case DIR_UI_COMMON:AddName("../COMMONUI/", pMem, folder, FALSE); AddExt(folder, NULL); break;
	 default:			break;
	}
	{	// normalise separators
		char *p;
		for(p=TmpPath; *p; p++) if( *p=='\\' ) *p = '/';
	}
}

int KMakeFolder(char *fname) {
	if( !strcmp(fname, "../COMMONUI") ) {
		strcpy(TmpPath, AppDataPath);
		strcat(TmpPath, "../COMMONUI");
	} else {
		BuildPath(fname, DIR_GAME, TRUE);
	}
	return js_mkdir(TmpPath);
}

void KDelFolder(char *fname) {
	BuildPath(fname, DIR_GAME, TRUE);
	js_rmdir(TmpPath);
}

/* Reads look in the player's saved files first, then the game's own files.
   Writes always go to the saved files (copying the game's file there first). */
DWORD Kopen(char *fname, int oflags, BYTE dir) {

	char	app[PATHLEN];

	BuildPath(fname, dir, TRUE);
	strcpy(app, TmpPath);
	BuildPath(fname, dir, FALSE);
	return js_fopen(app, TmpPath, oflags);
}

DWORD Kstat(char *fname, BYTE dir, DWORD *modtim, BYTE *filtyp) {

	char	app[PATHLEN];

	BuildPath(fname, dir, TRUE);
	strcpy(app, TmpPath);
	BuildPath(fname, dir, FALSE);
	return js_fstat(app, TmpPath, modtim, filtyp);
}

DWORD Kseek(DWORD fhandle, DWORD foffset, int origin) { return js_fseek(fhandle, (long)foffset, origin); }
void  Kclose(DWORD fhandle) { js_fclose(fhandle); }
DWORD Keof(DWORD fhandle) { return js_feof(fhandle); }
DWORD Kread(DWORD fhandle, BYTE *pMem, DWORD numbytes) { return js_fread(fhandle, pMem, numbytes); }
DWORD Kwrite(DWORD fhandle, BYTE *pMem, DWORD numbytes) { return js_fwrite(fhandle, pMem, numbytes); }

void Kfindclose() {
	FindCount = FindPos = 0;
}

DWORD Kfindfirst(char *fname, BYTE *fbuf, BYTE *attrib, BYTE *appdata, BYTE dir) {

	char	app[PATHLEN];
	BOOL	stripEXT;

	Kfindclose();
	stripEXT = dir!=DIR_GAME && !(dir & DIR_NOEXT);
	BuildPath(fname, dir, TRUE);
	strcpy(app, TmpPath);
	BuildPath(fname, dir, FALSE);
	FindCount = js_find(app, TmpPath, stripEXT);
	FindPos = 0;
	return Kfindnext(fbuf, attrib, appdata);
}

DWORD Kfindnext(BYTE *fbuf, BYTE *attrib, BYTE *appdata) {
	if( FindPos < FindCount ) {
		js_find_get(FindPos++, (char *)fbuf, attrib, appdata);
		return 0;
	}
	return 0xFFFFFFFF;
}

void Kdelete(char *fname, BYTE dir) {
	BuildPath(fname, dir, TRUE);
	js_delete(TmpPath);
}

WORD KCopyFile(char *src, char *dst) {
	return 0;	// only used by the shareware-copy feature, which is disabled
}

/* ================================================================ input */
/* Called by kint_lib.js for each input event from the page. */
EMSCRIPTEN_KEEPALIVE void kp_event(int type, int a, int b, int c, int d) {

	static const DWORD btnVK[3] = { VK_LBUTTON, VK_MBUTTON, VK_RBUTTON };
	DWORD	xy;

	if( kBuf==NULL || Quit ) return;
	switch( type ) {
	 case EV_MOUSEMOVE:	// a=x b=y c=button/modifier flags (MK_xxx)
		CurCur = -1;
		xy = FixXY(a, b);
		AddMsg(KHDR_POINTER_MOVE, (DWORD)(long)(short)(WORD)(xy & 0xFFFF), (DWORD)(long)(short)(WORD)(xy>>16), (DWORD)c);
		if( CurCur==-1 ) KSetCursor(0);
		break;
	 case EV_MOUSEDOWN:	// a=button(0 left,1 middle,2 right) b=x c=y d=flags
		if( a>=0 && a<3 ) AddMsg(KHDR_KEY_DOWN, btnVK[a], (DWORD)d, FixXY(b, c));
		break;
	 case EV_MOUSEUP:
		if( a>=0 && a<3 ) AddMsg(KHDR_KEY_UP, btnVK[a], (DWORD)d, FixXY(b, c));
		break;
	 case EV_WHEEL:		// a=clicks (+ away from user) b=x c=y
		AddMsg(KHDR_KEY_DOWN, 0x00008003, (DWORD)(long)a, FixXY(b, c));
		break;
	 case EV_HWHEEL:
		AddMsg(KHDR_KEY_DOWN, 0x00008004, (DWORD)(long)a, FixXY(b, c));
		break;
	 case EV_KEYDOWN:	// a=VK code b=alt held
		if( (a>=0x30 && a<=0x39) || (a>=0x41 && a<=0x5A) ) {
			AddMsg(KHDR_ALPHAKEY_DOWN, (DWORD)a, 1, 0);
			if( b ) AddMsg(KHDR_CHAR, (DWORD)a, 1, 0);	// Windows sends no WM_CHAR for ALT-alpha
		} else {
			AddMsg(KHDR_KEY_DOWN, b ? (DWORD)a : MapCursor((DWORD)a), 1, b ? 1 : 0);
		}
		break;
	 case EV_KEYUP:
		if( (a>=0x30 && a<=0x39) || (a>=0x41 && a<=0x5A) ) {
			AddMsg(KHDR_ALPHAKEY_UP, (DWORD)a, 1, 0);
		} else {
			AddMsg(KHDR_KEY_UP, b ? (DWORD)a : MapCursor((DWORD)a), 1, b ? 1 : 0);
		}
		break;
	 case EV_CHAR:		// a=character code
		if( a>=0x20 ) AddMsg(KHDR_CHAR, (DWORD)a, 1, 0);
		break;
	 case EV_RESIZE:	// a=width b=height (CSS pixels)
		if( a>0 && b>0 ) WindowSized(a, b);
		break;
	 case EV_BLUR:		// like WM_ACTIVATEAPP: don't leave ALT stuck down
		AddMsg(KHDR_KEY_UP, 0xF5, 1, 0);
		break;
	 case EV_MUSICDONE:
		if( MusicPlaying ) {
			MusicPlaying = 0;
			AddMsg(KHDR_MUSIC_DONE, 0, 0, 0);
		}
		break;
	 case EV_CLOSE:		// the player asked to close the game
		if( KEmsg(&mainKE, KHDR_QUERY_QUIT, 0, 0, 0) ) ShutDown();
		break;
	 case EV_HIDDEN:	// a=1 tab hidden, 0 visible again
		if( a && !MinFlag ) { MinFlag = TRUE; AddMsg(KHDR_WINDOW_HIDDEN, 1, 0, 0); }
		else if( !a && MinFlag ) { MinFlag = FALSE; AddMsg(KHDR_WINDOW_HIDDEN, 0, 0, 0); }
		break;
	}
}

/* ============================================================ main loop */
EMSCRIPTEN_KEEPALIVE int kp_main(int screenW, int screenH, int winW, int winH) {

	DWORD	IdleCount;

	PhysicalScreenW = screenW;
	PhysicalScreenH = screenH;
	TicksStart = now_ms();
	DirtyX1 = DirtyY1 = 0x7FFFFFFF;
	DirtyX2 = DirtyY2 = -0x7FFFFFFF;

	if( NULL==(KINTmsgs=(DWORD *)malloc(MAXMSGS*16)) ) {
		SystemMessage("Failed to allocate MSG buf");
		return 1;
	}
	if( !LoadKEFile("main.ke", &mainKE) ) return 2;

	SysStartup();
	InitScreen(0, 0);
	if( Quit ) return 3;

	KEmsg(&mainKE, KHDR_BEGIN_STARTUP, 0, 0, 0);
	WindowSized(winW, winH);		// Windows sends WM_SIZE when the window is created
	KEmsg(&mainKE, KHDR_END_STARTUP, 0, 0, 0);
	KEmsg(&mainKE, KHDR_IDLE, 0, 0, 0);
	ProgramReady = TRUE;

	while( !Quit ) {
		js_poll_input();
		while( !Quit && !QueueEmpty() ) {
			SendNextMsg();
			js_poll_input();
			MaybePresent();
		}
		if( Quit ) break;
		// idle work: keep calling IDLE until it returns 0 or something arrives
		IdleCount = 0;
		while( !Quit && QueueEmpty() && !js_input_pending() && !TimerDue() ) {
			if( !KEmsg(&mainKE, KHDR_IDLE, IdleCount++, 0, 0) ) break;
			MaybePresent();
		}
		if( Quit ) break;
		if( TimerDue() ) {	// like WM_TIMER: only one pending at a time
			TimerNext = now_ms() + TimerPeriod;
			AddMsg(KHDR_TIMER, 0, 0, 0);
			continue;
		}
		if( !QueueEmpty() || js_input_pending() ) continue;
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
