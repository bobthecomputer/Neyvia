// Previsibility containment for job-owned, non-brokered x64 Windows processes.
// No input injection, activation, desktop switching, or unowned-window writes.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <dwmapi.h>

#pragma data_seg(".c11shared")
wchar_t jobName[160] = {};
LONG creates = 0, vetoes = 0, positions = 0, failures = 0;
LONG bureauMode = 0;
LONG registrationState[8] = {};
wchar_t lastFailureClass[256] = {};
#pragma data_seg()
#pragma comment(linker, "/SECTION:.c11shared,RWS")
static HINSTANCE module;
static HHOOK hook;
static HHOOK returnedHook;
static const wchar_t* originalKey = L"Neyvia.C11.Parked.OriginalProc";
static const wchar_t* cloakKey = L"Neyvia.C11.Bureau.Cloaked";
static const wchar_t* alphaKey = L"Neyvia.C11.Bureau.Transparent";
static const wchar_t* offscreenKey = L"Neyvia.C11.Bureau.Offscreen";
static const wchar_t* memberKey = L"Neyvia.C11.Bureau.Member";
static UINT bureauMessage() { return RegisterWindowMessageW(L"Neyvia.C11.Bureau.RegisterCloaked.v1"); }
static bool cloaked(HWND window) {
    DWORD state = 0;
    return SUCCEEDED(DwmGetWindowAttribute(window, DWMWA_CLOAKED, &state, sizeof(state))) && state;
}
static bool transparent(HWND window) {
    BYTE alpha = 255; DWORD flags = 0;
    return GetLayeredWindowAttributes(window, nullptr, &alpha, &flags) && (flags & LWA_ALPHA) && alpha == 0;
}
static bool invisible(HWND window) {
    RECT r = {};
    bool outside = GetPropW(window, offscreenKey) && GetWindowRect(window, &r)
        && r.left == -32000 && r.top == -32000 && r.right < -16000 && r.bottom < -16000;
    return cloaked(window) || transparent(window) || outside;
}

static LONG_PTR guardedExtendedStyle(LONG_PTR style) {
    return bureauMode
        ? (style | WS_EX_NOACTIVATE | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
        : (style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW;
}

static bool owned() {
    if (!jobName[0]) return false;
    HANDLE job = OpenJobObjectW(JOB_OBJECT_QUERY, FALSE, jobName);
    if (!job) return false;
    BOOL contained = FALSE;
    BOOL ok = IsProcessInJob(GetCurrentProcess(), job, &contained);
    CloseHandle(job);
    return ok && contained;
}

static LRESULT CALLBACK parkedProc(HWND window, UINT message, WPARAM wp, LPARAM lp) {
    auto original = reinterpret_cast<WNDPROC>(GetPropW(window, originalKey));
    if (!original) return DefWindowProcW(window, message, wp, lp);
    if (message == bureauMessage()) {
        registrationState[0] = static_cast<LONG>(wp);
        if (!bureauMode || !owned()) return FALSE;
        if (wp == 7) {
            // Alternative for Shell builds that exclude alpha-zero views.
            // All geometry writes are intercepted before they can be shown.
            if (IsWindowVisible(window) || GetPropW(window, memberKey)) return FALSE;
            if (!SetPropW(window, offscreenKey, reinterpret_cast<HANDLE>(1))
                || !SetPropW(window, cloakKey, reinterpret_cast<HANDLE>(1))) return FALSE;
            SetWindowPos(window, nullptr, -32000, -32000, 0, 0,
                SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOZORDER);
            SetWindowLongPtrW(window, GWL_EXSTYLE,
                GetWindowLongPtrW(window, GWL_EXSTYLE) & ~WS_EX_NOACTIVATE);
            ShowWindow(window, SW_SHOWNOACTIVATE);
            return IsWindowVisible(window) && invisible(window);
        }
        if (wp == 5) {
            // A Shell view needs WS_VISIBLE, but no pixels may reach the input
            // desktop. Establish BOTH alpha zero and offscreen while hidden.
            if (IsWindowVisible(window) || GetPropW(window, memberKey)) return FALSE;
            if (!SetPropW(window, offscreenKey, reinterpret_cast<HANDLE>(1))) return FALSE;
            SetWindowLongPtrW(window, GWL_EXSTYLE,
                GetWindowLongPtrW(window, GWL_EXSTYLE) | WS_EX_LAYERED);
            if (!SetLayeredWindowAttributes(window, 0, 0, LWA_ALPHA)
                || !transparent(window)) return FALSE;
            if (!SetPropW(window, alphaKey, reinterpret_cast<HANDLE>(1))
                || !SetPropW(window, cloakKey, reinterpret_cast<HANDLE>(1))) return FALSE;
            SetWindowPos(window, nullptr, -32000, -32000, 0, 0,
                SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOZORDER);
            SetWindowLongPtrW(window, GWL_EXSTYLE,
                GetWindowLongPtrW(window, GWL_EXSTYLE) & ~WS_EX_NOACTIVATE);
            ShowWindow(window, SW_SHOWNOACTIVATE);
            return IsWindowVisible(window) && transparent(window) && invisible(window);
        }
        if (wp == 6) {
            DWORD state = 0;
            // The controller proved the target GUID; independently require
            // SHELL cloak (not an application-requested cloak) before paint.
            if (FAILED(DwmGetWindowAttribute(window, DWMWA_CLOAKED, &state, sizeof(state)))
                || !(state & DWM_CLOAKED_SHELL)) return FALSE;
            if (!SetPropW(window, memberKey, reinterpret_cast<HANDLE>(1))) return FALSE;
            RemovePropW(window, alphaKey);
            SetWindowLongPtrW(window, GWL_EXSTYLE,
                (GetWindowLongPtrW(window, GWL_EXSTYLE) | WS_EX_NOACTIVATE) & ~WS_EX_LAYERED);
            SetWindowPos(window, nullptr, 0, 0, 0, 0,
                SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOZORDER | SWP_SHOWWINDOW);
            return cloaked(window);
        }
        if (wp == 3) {
            if (!cloaked(window)) return FALSE;
            ShowWindow(window, SW_HIDE);
            if (!SetPropW(window, offscreenKey, reinterpret_cast<HANDLE>(1))) return FALSE;
            SetWindowPos(window, nullptr, -32000, -32000, 0, 0,
                SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOZORDER);
            BOOL cloak = FALSE;
            if (FAILED(DwmSetWindowAttribute(window, DWMWA_CLOAK, &cloak, sizeof(cloak)))) return FALSE;
            DwmFlush();
            SetWindowLongPtrW(window, GWL_EXSTYLE, GetWindowLongPtrW(window, GWL_EXSTYLE) & ~WS_EX_NOACTIVATE);
            ShowWindow(window, SW_SHOWNOACTIVATE);
            return IsWindowVisible(window) && invisible(window);
        }
        if (wp == 2 || wp == 4) {
            // Shell omits an app-cloaked view from registration. Zero opacity
            // is established while still cloaked, before removing that cloak.
            if (wp == 2 && !cloaked(window)) return FALSE;
            if (wp == 4 && IsWindowVisible(window)) return FALSE;
            SetWindowLongPtrW(window, GWL_EXSTYLE, GetWindowLongPtrW(window, GWL_EXSTYLE) | WS_EX_LAYERED);
            registrationState[1] = SetLayeredWindowAttributes(window, 0, 0, LWA_ALPHA);
            registrationState[2] = GetLastError();
            registrationState[3] = transparent(window);
            if (!registrationState[1] || !registrationState[3]) return FALSE;
            if (!SetPropW(window, alphaKey, reinterpret_cast<HANDLE>(1))) return FALSE;
            if (!SetPropW(window, cloakKey, reinterpret_cast<HANDLE>(1))) return FALSE;
            ShowWindow(window, SW_HIDE);
            BOOL cloak = FALSE;
            if (FAILED(DwmSetWindowAttribute(window, DWMWA_CLOAK, &cloak, sizeof(cloak)))) return FALSE;
            DwmFlush();
            SetWindowLongPtrW(window, GWL_EXSTYLE, GetWindowLongPtrW(window, GWL_EXSTYLE) & ~WS_EX_NOACTIVATE);
            // Minimized windows do not necessarily acquire a Shell view on
            // current Windows 11. Register a normal, zero-opacity window;
            // CBT still vetoes focus and the independent guard checks alpha.
            ShowWindow(window, SW_SHOWNOACTIVATE);
            registrationState[4] = IsWindowVisible(window);
            registrationState[5] = transparent(window);
            return registrationState[4] && registrationState[5];
        }
        BOOL cloak = TRUE;
        registrationState[6] = DwmSetWindowAttribute(window, DWMWA_CLOAK, &cloak, sizeof(cloak));
        DwmFlush();
        registrationState[7] = cloaked(window);
        if (FAILED(registrationState[6]) || !registrationState[7]) return FALSE;
        SetWindowLongPtrW(window, GWL_EXSTYLE, guardedExtendedStyle(GetWindowLongPtrW(window, GWL_EXSTYLE)));
        if (!SetPropW(window, cloakKey, reinterpret_cast<HANDLE>(1))) return FALSE;
        ShowWindow(window, SW_SHOWNOACTIVATE);
        return IsWindowVisible(window) && cloaked(window);
    }
    if (message == WM_NCCREATE) {
        LRESULT result = CallWindowProcW(original, window, message, wp, lp);
        // At NCCREATE the HWND's styles are assigned. CREATEWND runs earlier;
        // some dialog managers ignore CREATESTRUCT.dwExStyle changes there.
        SetLastError(0);
        LONG_PTR style = GetWindowLongPtrW(window, GWL_EXSTYLE);
        if (!SetWindowLongPtrW(window, GWL_EXSTYLE, guardedExtendedStyle(style))
                && GetLastError()) {
            InterlockedIncrement(&failures); return FALSE;
        }
        return result;
    }
    if (message == WM_MOUSEACTIVATE) return MA_NOACTIVATEANDEAT;
    if (message == WM_WINDOWPOSCHANGING) {
        // Let the application adjust size first; containment takes precedence.
        LRESULT result = CallWindowProcW(original, window, message, wp, lp);
        auto pos = reinterpret_cast<WINDOWPOS*>(lp);
        pos->x = (GetPropW(window, memberKey) && cloaked(window)) || transparent(window) ? 0 : -32000;
        pos->y = (GetPropW(window, memberKey) && cloaked(window)) || transparent(window) ? 0 : -32000;
        pos->flags &= ~SWP_NOMOVE;
        if (!GetPropW(window, cloakKey) || !invisible(window)) {
            pos->flags &= ~SWP_SHOWWINDOW;
            pos->flags |= SWP_HIDEWINDOW;
        }
        pos->flags |= SWP_NOACTIVATE | SWP_NOZORDER;
        InterlockedIncrement(&positions);
        return result;
    }
    if (message == WM_STYLECHANGING && wp == GWL_EXSTYLE) {
        LRESULT result = CallWindowProcW(original, window, message, wp, lp);
        auto style = reinterpret_cast<STYLESTRUCT*>(lp);
        style->styleNew = static_cast<DWORD>(guardedExtendedStyle(style->styleNew));
        if (GetPropW(window, alphaKey)) style->styleNew |= WS_EX_LAYERED;
        if (GetPropW(window, alphaKey) && transparent(window) && !GetPropW(window, memberKey))
            style->styleNew &= ~WS_EX_NOACTIVATE;
        if (GetPropW(window, offscreenKey) && !GetPropW(window, memberKey) && !cloaked(window))
            style->styleNew &= ~WS_EX_NOACTIVATE;
        return result;
    }
    if (message == WM_STYLECHANGING && wp == GWL_STYLE) {
        LRESULT result = CallWindowProcW(original, window, message, wp, lp);
        if (!GetPropW(window, cloakKey) || !invisible(window))
            reinterpret_cast<STYLESTRUCT*>(lp)->styleNew &= ~WS_VISIBLE;
        return result;
    }
    LRESULT result = CallWindowProcW(original, window, message, wp, lp);
    if (message == WM_NCDESTROY) { RemovePropW(window, originalKey); RemovePropW(window, cloakKey); RemovePropW(window, alphaKey); }
    return result;
}

static LRESULT CALLBACK cbt(int code, WPARAM wp, LPARAM lp) {
    if (code >= 0 && owned()) {
        if (code == HCBT_ACTIVATE || code == HCBT_SETFOCUS) {
            InterlockedIncrement(&vetoes);
            return 1;
        }
        if (code == HCBT_CREATEWND) {
            auto created = reinterpret_cast<CBT_CREATEWNDW*>(lp);
            // Message-only windows have no visual surface or z-order. Chrome
            // uses them before its real view exists; subclassing them as a
            // top-level GUI can abort startup without improving containment.
            if (created->lpcs->hwndParent == HWND_MESSAGE)
                return CallNextHookEx(nullptr, code, wp, lp);
            if (!(created->lpcs->style & WS_CHILD)) {
                HWND window = reinterpret_cast<HWND>(wp);
                created->lpcs->style &= ~WS_VISIBLE;
                created->lpcs->dwExStyle = static_cast<DWORD>(guardedExtendedStyle(created->lpcs->dwExStyle));
                created->lpcs->x = -32000; created->lpcs->y = -32000;
                // CREATEWND precedes a valid HWND on current Windows. Setting
                // properties here fails for real apps, although simple probes
                // may tolerate it. Install after NCCREATE, before CREATE/show.
            }
        }
    }
    return CallNextHookEx(nullptr, code, wp, lp);
}

static LRESULT CALLBACK returned(int code, WPARAM wp, LPARAM lp) {
    if (code >= 0 && owned()) {
        auto message = reinterpret_cast<CWPRETSTRUCT*>(lp);
        HWND window = message->hwnd;
        if (message->message == WM_NCCREATE && message->lResult
            && !(GetWindowLongPtrW(window, GWL_STYLE) & WS_CHILD)
            && GetParent(window) != HWND_MESSAGE && !GetPropW(window, originalKey)) {
            auto original = reinterpret_cast<WNDPROC>(GetWindowLongPtrW(window, GWLP_WNDPROC));
            if (!original || !SetPropW(window, originalKey, reinterpret_cast<HANDLE>(original))) {
                GetClassNameW(window,lastFailureClass,256);
                InterlockedIncrement(&failures);
                ShowWindow(window, SW_HIDE);
            } else {
                SetLastError(0);
                if (!SetWindowLongPtrW(window, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(parkedProc)) && GetLastError()) {
                    RemovePropW(window, originalKey); InterlockedIncrement(&failures);
                    ShowWindow(window, SW_HIDE);
                } else {
                    SetWindowLongPtrW(window, GWL_EXSTYLE, guardedExtendedStyle(GetWindowLongPtrW(window, GWL_EXSTYLE)));
                    InterlockedIncrement(&creates);
                }
            }
        }
    }
    return CallNextHookEx(nullptr, code, wp, lp);
}

extern "C" __declspec(dllexport) BOOL __cdecl InstallParked(const wchar_t* name) {
    if (hook || !name || wcslen(name) >= 160) return FALSE;
    wcscpy_s(jobName, name);
    creates = vetoes = positions = failures = bureauMode = 0;
    for(auto &value:registrationState)value=0;
    hook = SetWindowsHookExW(WH_CBT, cbt, module, 0);
    returnedHook = SetWindowsHookExW(WH_CALLWNDPROCRET, returned, module, 0);
    if (!hook || !returnedHook) {
        if (hook) UnhookWindowsHookEx(hook);
        if (returnedHook) UnhookWindowsHookEx(returnedHook);
        hook = returnedHook = nullptr; jobName[0] = 0; return FALSE;
    }
    return TRUE;
}
extern "C" __declspec(dllexport) BOOL __cdecl UninstallParked() {
    if (hook && !UnhookWindowsHookEx(hook)) return FALSE;
    if (returnedHook && !UnhookWindowsHookEx(returnedHook)) return FALSE;
    hook = returnedHook = nullptr; jobName[0] = 0; bureauMode = 0; return TRUE;
}
extern "C" __declspec(dllexport) BOOL __cdecl SetBureauMode(BOOL enabled) {
    if (!hook || !jobName[0] || creates) return FALSE;
    InterlockedExchange(&bureauMode, enabled ? 1 : 0);
    return TRUE;
}
extern "C" __declspec(dllexport) LONG __cdecl ParkedCounter(int index) {
    switch(index) { case 0: return creates; case 1: return vetoes; case 2: return positions; default: return failures; }
}
extern "C" __declspec(dllexport) LONG __cdecl BureauRegistrationState(int index) { return index>=0 && index<8?registrationState[index]:-1; }
extern "C" __declspec(dllexport) BOOL __cdecl ParkedLastFailure(wchar_t* output, int length) {
    if (!output || length < 256) return FALSE;
    wcscpy_s(output,length,lastFailureClass);return TRUE;
}
extern "C" __declspec(dllexport) BOOL __cdecl RegisterCloakedBureauWindow(HWND window) {
    SetLastError(0);
    DWORD_PTR result = 0;
    return SendMessageTimeoutW(window, bureauMessage(), 0, 0, SMTO_ABORTIFHUNG | SMTO_BLOCK, 1000, &result) && result;
}
extern "C" __declspec(dllexport) BOOL __cdecl RegisterPrevisibilityBureauWindow(HWND window) {
    DWORD_PTR result = 0;
    SetLastError(0);
    LRESULT sent=SendMessageTimeoutW(window, bureauMessage(), 7, 0, SMTO_ABORTIFHUNG | SMTO_BLOCK, 750, &result);
    registrationState[1]=static_cast<LONG>(sent);
    registrationState[2]=GetLastError();
    registrationState[3]=static_cast<LONG>(result);
    return sent && result;
}
extern "C" __declspec(dllexport) BOOL __cdecl AdmitBureauWindow(HWND window) {
    DWORD_PTR result = 0;
    SetLastError(0);
    LRESULT sent=SendMessageTimeoutW(window, bureauMessage(), 6, 0, SMTO_ABORTIFHUNG | SMTO_BLOCK, 750, &result);
    registrationState[1]=static_cast<LONG>(sent);
    registrationState[2]=GetLastError();
    registrationState[3]=static_cast<LONG>(result);
    return sent && result;
}
extern "C" __declspec(dllexport) BOOL __cdecl RegisterTransparentBureauWindow(HWND window) {
    SetLastError(0);
    DWORD_PTR result = 0;
    return SendMessageTimeoutW(window, bureauMessage(), 2, 0, SMTO_ABORTIFHUNG | SMTO_BLOCK, 1000, &result) && result;
}
extern "C" __declspec(dllexport) BOOL __cdecl RegisterHiddenTransparentBureauWindow(HWND window) {
    SetLastError(0);
    DWORD_PTR result = 0;
    return SendMessageTimeoutW(window, bureauMessage(), 4, 0, SMTO_ABORTIFHUNG | SMTO_BLOCK, 1000, &result) && result;
}
extern "C" __declspec(dllexport) BOOL __cdecl RegisterOffscreenBureauWindow(HWND window) {
    DWORD_PTR result = 0;
    return SendMessageTimeoutW(window, bureauMessage(), 3, 0, SMTO_ABORTIFHUNG | SMTO_BLOCK, 1000, &result) && result;
}
BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) { module = instance; DisableThreadLibraryCalls(instance); }
    return TRUE;
}
