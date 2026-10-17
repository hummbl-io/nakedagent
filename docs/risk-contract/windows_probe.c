/* Fixed Win64 probe; imports only kernel32, no CRT/CLR/user32 initialization. */
typedef void *HANDLE;
typedef unsigned long DWORD;
typedef int BOOL;
typedef unsigned short WCHAR;
#define API __declspec(dllimport)
API HANDLE __stdcall GetStdHandle(DWORD);
API BOOL __stdcall ReadFile(HANDLE, void *, DWORD, DWORD *, void *);
API BOOL __stdcall WriteFile(HANDLE, const void *, DWORD, DWORD *, void *);
API DWORD __stdcall GetCurrentDirectoryW(DWORD, WCHAR *);
API HANDLE __stdcall CreateFileW(const WCHAR *, DWORD, DWORD, void *, DWORD, DWORD, HANDLE);
API BOOL __stdcall CloseHandle(HANDLE);
API DWORD __stdcall GetLastError(void);
API void __stdcall ExitProcess(DWORD);
static WCHAR path[4096];
static char response[4096];
static HANDLE input, output;
static DWORD length(const char *s) { DWORD n=0; while(s[n]) n++; return n; }
static void emit(const char *s) {
    DWORD n; DWORD wanted=length(s);
    if(!WriteFile(output,s,wanted,&n,0)||n!=wanted) ExitProcess(4);
}
static void number(DWORD n) {
    char b[16]; int i=15; b[i]=0;
    do { b[--i]=(char)('0'+n%10); n/=10; } while(n);
    emit(b+i); emit("\n");
}
static void append(const WCHAR *s) {
    DWORD i=0,j=0; while(path[i]) i++;
    while(s[j]) { if(i>=4095) ExitProcess(5); path[i++]=s[j++]; } path[i]=0;
}
static DWORD probe(DWORD rights,DWORD flags) {
    HANDLE h=CreateFileW(path,rights,7,0,3,flags,0);
    if(h==(HANDLE)(long long)-1) return GetLastError();
    CloseHandle(h); return 0;
}
static void exchange(const char *request) {
    emit("REQUEST|"); emit(request); emit("\n");
    DWORD i=0,n; char c;
    for(;;) {
        if(!ReadFile(input,&c,1,&n,0)||n!=1) ExitProcess(6);
        if(c=='\n') break;
        if(c=='\r') continue;
        if(i>=4095) ExitProcess(7);
        response[i++]=c;
    }
    response[i]=0; emit("RESPONSE|"); emit(response); emit("\n");
}
void mainCRTStartup(void) {
    input=GetStdHandle((DWORD)-10); output=GetStdHandle((DWORD)-11);
    DWORD n=GetCurrentDirectoryW(4096,path);
    if(n==0||n>=4096) ExitProcess(8);
    append((const WCHAR *)L"\\private\\public.txt");
    emit("DIRECT|"); number(probe(0x80000000,0));
    emit("WRITE_DAC|"); number(probe(0x00040000,0));
    path[n]=0; append((const WCHAR *)L"\\private");
    emit("DIR_DELETE|"); number(probe(0x00010000,0x02000000));
    path[n]=0; append((const WCHAR *)L"\\reservations.sqlite");
    emit("STATE_WRITE|"); number(probe(0x40000000,0));
    exchange("allowed"); exchange("replay"); exchange("expired"); exchange("budget"); exchange("revoked"); exchange("wrong-resource");
    path[n]=0; append((const WCHAR *)L"\\private\\public.txt");
    emit("DIRECT_AFTER|"); number(probe(0x80000000,0));
    ExitProcess(0);
}
