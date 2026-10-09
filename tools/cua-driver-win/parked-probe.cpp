#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdio>
#include <shobjidl.h>
#include <dwmapi.h>
static wchar_t output[MAX_PATH];
static void write(const wchar_t* suffix, const char* value) { wchar_t path[MAX_PATH]; swprintf_s(path,L"%s%s",output,suffix); FILE* file=nullptr; _wfopen_s(&file,path,L"wb"); if(file){fputs(value,file); fclose(file);} }
static LRESULT CALLBACK proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
 if(msg==WM_APP){ ShowWindow(hwnd,SW_SHOWNOACTIVATE); SetWindowPos(hwnd,HWND_TOP,90,110,460,440,SWP_NOACTIVATE); SetForegroundWindow(hwnd); SetFocus(hwnd); write(L".result",IsWindowVisible(hwnd)?"visible":"hidden"); return 0; }
 if(msg==WM_APP+1){
  wchar_t path[MAX_PATH], text[80]={}; swprintf_s(path,L"%s.target",output);
  FILE* file=nullptr; _wfopen_s(&file,path,L"rt,ccs=UTF-8");
  if(!file){write(L".move","target unavailable"); return 0;}
  fgetws(text,80,file); fclose(file); GUID target={}; HRESULT result=CLSIDFromString(text,&target);
  HRESULT initialized=CoInitializeEx(nullptr,COINIT_MULTITHREADED);
  IVirtualDesktopManager* manager=nullptr;
  if(SUCCEEDED(result)) result=CoCreateInstance(CLSID_VirtualDesktopManager,nullptr,CLSCTX_ALL,IID_PPV_ARGS(&manager));
  if(SUCCEEDED(result)){
   result=manager->MoveWindowToDesktop(hwnd,target);
   GUID actual={}; HRESULT query=manager->GetWindowDesktopId(hwnd,&actual);
   char queryStatus[50]; sprintf_s(queryStatus,"0x%08lx",static_cast<unsigned long>(query)); write(L".query",queryStatus);
   wchar_t actualText[80]; StringFromGUID2(actual,actualText,80); char actualUtf8[100]; WideCharToMultiByte(CP_UTF8,0,actualText,-1,actualUtf8,100,nullptr,nullptr); write(L".actual",actualUtf8);
   write(L".assigned",SUCCEEDED(query)&&IsEqualGUID(actual,target)?"yes":"no");
   manager->Release();
  }
  char status[50]; sprintf_s(status,"0x%08lx",static_cast<unsigned long>(result)); write(L".move",status);
  if(SUCCEEDED(initialized)) CoUninitialize(); return 0;
 }
 if(msg==WM_APP+2){
  BOOL cloak=TRUE; DWORD state=0;
  HRESULT set=DwmSetWindowAttribute(hwnd,DWMWA_CLOAK,&cloak,sizeof(cloak));
  HRESULT get=DwmGetWindowAttribute(hwnd,DWMWA_CLOAKED,&state,sizeof(state));
  char status[100]; sprintf_s(status,"set=0x%08lx get=0x%08lx state=%lu hidden=%d",static_cast<unsigned long>(set),static_cast<unsigned long>(get),state,!IsWindowVisible(hwnd));
  write(L".cloak",status); return 0;
 }
 if(msg==WM_CLOSE){DestroyWindow(hwnd); return 0;}
 if(msg==WM_DESTROY){PostQuitMessage(0); return 0;}
 return DefWindowProcW(hwnd,msg,wp,lp);
}
int WINAPI wWinMain(HINSTANCE instance,HINSTANCE,LPWSTR argument,int) {
 SetCurrentProcessExplicitAppUserModelID(L"Neyvia.C11.DisposableBureauProbe");
 wcscpy_s(output,argument); WNDCLASSW wc={}; wc.hInstance=instance; wc.lpszClassName=L"C11ParkedProbe"; wc.lpfnWndProc=proc; RegisterClassW(&wc);
 HWND hwnd=CreateWindowExW(0,wc.lpszClassName,argument,WS_OVERLAPPEDWINDOW,90,110,460,440,nullptr,nullptr,instance,nullptr);
 if(!hwnd){write(L".error","create refused"); return 2;}
 char handle[40]; sprintf_s(handle,"%llu",(unsigned long long)hwnd); write(L".hwnd",handle);
 MSG message; while(GetMessageW(&message,nullptr,0,0)>0){TranslateMessage(&message); DispatchMessageW(&message);} return 0;
}
