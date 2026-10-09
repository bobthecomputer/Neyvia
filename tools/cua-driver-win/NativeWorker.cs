using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Automation;

namespace T16 {
public static class NativeWorker {
    [StructLayout(LayoutKind.Sequential)] struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] struct POINT { public int X,Y; }
    [StructLayout(LayoutKind.Sequential)] struct LASTINPUTINFO { public uint cbSize,dwTime; }
    [StructLayout(LayoutKind.Sequential)] struct GUITHREADINFO { public uint cbSize,flags; public IntPtr hwndActive,hwndFocus,hwndCapture,hwndMenuOwner,hwndMoveSize,hwndCaret; public RECT rcCaret; }
    [StructLayout(LayoutKind.Sequential)] struct MSG { public IntPtr hwnd; public uint message; public UIntPtr wParam; public IntPtr lParam; public uint time; public POINT pt; public uint lPrivate; }
    [StructLayout(LayoutKind.Sequential)] struct KBD { public uint vkCode, scanCode, flags, time; public UIntPtr extra; }
    [StructLayout(LayoutKind.Sequential)] struct MOUSE { public POINT pt; public uint mouseData, flags, time; public UIntPtr extra; }
    delegate bool EnumProc(IntPtr h, IntPtr p);
    delegate IntPtr HookProc(int code, IntPtr w, IntPtr l);
    delegate void WinEventProc(IntPtr hook,uint evt,IntPtr hwnd,int obj,int child,uint thread,uint tick);
    [DllImport("user32.dll")] static extern IntPtr SetWinEventHook(uint min,uint max,IntPtr module,WinEventProc cb,uint pid,uint tid,uint flags);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] static extern bool IsWindow(IntPtr h);
    [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] static extern bool IsChild(IntPtr parent, IntPtr child);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s,int n);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder s,int n);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h,out uint pid);
    [DllImport("user32.dll")] static extern bool GetGUIThreadInfo(uint thread,ref GUITHREADINFO info);
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h,out RECT r);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern bool GetCursorPos(out POINT p);
    [DllImport("user32.dll",SetLastError=true)] static extern IntPtr OpenInputDesktop(uint flags,bool inherit,uint access);
    [DllImport("user32.dll")] static extern IntPtr GetThreadDesktop(uint thread);
    [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
    [DllImport("user32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool GetUserObjectInformation(IntPtr handle,int index,StringBuilder value,uint size,out uint needed);
    [DllImport("user32.dll")] static extern bool CloseDesktop(IntPtr handle);
    static string DesktopName(IntPtr handle){if(handle==IntPtr.Zero)return "unavailable";uint needed;var value=new StringBuilder(256);return GetUserObjectInformation(handle,2,value,512,out needed)?value.ToString():"unavailable";}
    public static object DesktopStatus(){var input=OpenInputDesktop(0,false,0x100);try{string inputName=DesktopName(input),threadName=DesktopName(GetThreadDesktop(GetCurrentThreadId()));POINT point;return Map("inputDesktop",inputName,"threadDesktop",threadName,"interactive",inputName==threadName&&GetForegroundWindow()!=IntPtr.Zero&&GetCursorPos(out point));}finally{if(input!=IntPtr.Zero)CloseDesktop(input);}}
    [DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LASTINPUTINFO info);
    [DllImport("kernel32.dll")] static extern uint GetTickCount();
    [DllImport("user32.dll")] static extern bool PrintWindow(IntPtr h,IntPtr dc,uint flags);
    [DllImport("user32.dll",SetLastError=true)] static extern bool PostMessage(IntPtr h,uint msg,IntPtr w,IntPtr l);
    [DllImport("user32.dll",EntryPoint="SendMessageTimeoutW",CharSet=CharSet.Unicode,SetLastError=true)] static extern IntPtr SendMessageTimeout(IntPtr h,uint msg,IntPtr w,IntPtr l,uint flags,uint timeout,out UIntPtr result);
    [DllImport("user32.dll")] static extern bool ScreenToClient(IntPtr h,ref POINT p);
    [DllImport("user32.dll",SetLastError=true)] static extern IntPtr SetWindowsHookEx(int id,HookProc cb,IntPtr module,uint tid);
    [DllImport("user32.dll")] static extern IntPtr CallNextHookEx(IntPtr hook,int code,IntPtr w,IntPtr l);
    [DllImport("user32.dll")] static extern int GetMessage(out MSG msg,IntPtr h,uint min,uint max);
    [DllImport("user32.dll")] static extern bool TranslateMessage(ref MSG msg);
    [DllImport("user32.dll")] static extern IntPtr DispatchMessage(ref MSG msg);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode)] static extern IntPtr GetModuleHandle(string name);
    [DllImport("user32.dll")] static extern bool SetProcessDpiAwarenessContext(IntPtr value);
    static long inputGeneration;
    static IntPtr keyboardHook,mouseHook;
    static HookProc keyboardCallback,mouseCallback;
    static WinEventProc foregroundCallback;
    static IntPtr foregroundHook;
    static long foregroundGeneration;
    static readonly object foregroundLock=new object();
    static readonly List<object> foregroundEvents=new List<object>();
    static readonly List<object> foregroundNotifications=new List<object>();
    static IntPtr observedForeground;
    static bool hooksReady;
    static Dictionary<string,object> Map(params object[] pairs) { var d=new Dictionary<string,object>(); for(int i=0;i<pairs.Length;i+=2)d[(string)pairs[i]]=pairs[i+1];return d; }
    static string Id(IntPtr h){return h.ToInt64().ToString(CultureInfo.InvariantCulture);}
    static IntPtr Window(string id) { long v;if(!long.TryParse(id,out v)||v==0)throw new ArgumentException("Invalid windowId"); var h=new IntPtr(v);if(!IsWindow(h))throw new ArgumentException("Window no longer exists");return h; }
    static void ObserveForeground(IntPtr notification) {
        IntPtr actual=GetForegroundWindow();
        lock(foregroundLock) {
            if(notification!=IntPtr.Zero&&notification!=actual) {
                uint source;GetWindowThreadProcessId(notification,out source);
                foregroundNotifications.Add(Map("windowId",Id(notification),"actualWindowId",Id(actual),"pid",source,"className",ClassName(notification),"tick",GetTickCount()));
                if(foregroundNotifications.Count>32)foregroundNotifications.RemoveAt(0);
            }
            if(actual==observedForeground)return;
            observedForeground=actual;uint pid;GetWindowThreadProcessId(actual,out pid);
            long seq=Interlocked.Increment(ref foregroundGeneration);
            foregroundEvents.Add(Map("generation",seq,"windowId",Id(actual),"pid",pid,"className",ClassName(actual),"tick",GetTickCount()));
            if(foregroundEvents.Count>32)foregroundEvents.RemoveAt(0);
        }
    }
    public static void StartHooks() {
        // UIA bounds and window captures use physical desktop pixels.
        try { SetProcessDpiAwarenessContext(new IntPtr(-4)); } catch(EntryPointNotFoundException) {}
        observedForeground=GetForegroundWindow();
        var observer=new Thread(delegate(){while(true){ObserveForeground(IntPtr.Zero);Thread.Sleep(2);}});observer.IsBackground=true;observer.Start();
        var started=new ManualResetEvent(false);
        var thread=new Thread(delegate(){
            keyboardCallback=delegate(int c,IntPtr w,IntPtr l){if(c>=0 && (Marshal.PtrToStructure<KBD>(l).flags&0x12)==0)Interlocked.Increment(ref inputGeneration);return CallNextHookEx(keyboardHook,c,w,l);};
            mouseCallback=delegate(int c,IntPtr w,IntPtr l){if(c>=0 && (Marshal.PtrToStructure<MOUSE>(l).flags&3)==0)Interlocked.Increment(ref inputGeneration);return CallNextHookEx(mouseHook,c,w,l);};
            keyboardHook=SetWindowsHookEx(13,keyboardCallback,GetModuleHandle(null),0);
            mouseHook=SetWindowsHookEx(14,mouseCallback,GetModuleHandle(null),0);
            foregroundCallback=delegate(IntPtr h,uint evt,IntPtr hwnd,int obj,int child,uint tid,uint tick){ObserveForeground(hwnd);};
            foregroundHook=SetWinEventHook(3,3,IntPtr.Zero,foregroundCallback,0,0,0);
            hooksReady=keyboardHook!=IntPtr.Zero&&mouseHook!=IntPtr.Zero&&foregroundHook!=IntPtr.Zero;started.Set();
            MSG msg;while(GetMessage(out msg,IntPtr.Zero,0,0)>0){TranslateMessage(ref msg);DispatchMessage(ref msg);}
        });thread.IsBackground=true;thread.SetApartmentState(ApartmentState.STA);thread.Start();started.WaitOne(3000);
    }
    public static Dictionary<string,object> Status(){POINT p;GetCursorPos(out p);var i=new LASTINPUTINFO{cbSize=(uint)Marshal.SizeOf(typeof(LASTINPUTINFO))};if(!GetLastInputInfo(ref i))throw new InvalidOperationException("GetLastInputInfo failed");ObserveForeground(IntPtr.Zero);object[] events,notifications;lock(foregroundLock){events=foregroundEvents.ToArray();notifications=foregroundNotifications.ToArray();}return Map("foregroundWindowId",Id(GetForegroundWindow()),"foregroundGeneration",Interlocked.Read(ref foregroundGeneration),"foregroundEvents",events,"foregroundNotifications",notifications,"cursor",Map("x",p.X,"y",p.Y),"lastInputTick",i.dwTime,"tickCount",GetTickCount(),"inputGeneration",Interlocked.Read(ref inputGeneration),"hooksReady",hooksReady);}
    static object Bounds(RECT r){return Map("x",r.Left,"y",r.Top,"width",r.Right-r.Left,"height",r.Bottom-r.Top);}
    static readonly Dictionary<uint,Dictionary<string,object>> processIdentities=new Dictionary<uint,Dictionary<string,object>>();
    static Dictionary<string,object> WindowInfo(IntPtr h){uint pid;GetWindowThreadProcessId(h,out pid);RECT r;GetWindowRect(h,out r);var s=new StringBuilder(4096);GetWindowText(h,s,s.Capacity);string name="",exe=null,startTime=null;try{var p=Process.GetProcessById((int)pid);startTime=p.StartTime.ToUniversalTime().ToString("o",CultureInfo.InvariantCulture);Dictionary<string,object> cached;if(processIdentities.TryGetValue(pid,out cached) && Equals(cached["start"],startTime)){name=(string)cached["name"];exe=(string)cached["exe"];}else{name=p.ProcessName;try{exe=p.MainModule.FileName;}catch{}processIdentities[pid]=Map("start",startTime,"name",name,"exe",exe);}}catch{}return Map("windowId",Id(h),"pid",pid,"title",s.ToString(),"processName",name,"exe",exe,"processStartTime",startTime,"bounds",Bounds(r),"minimized",IsIconic(h));}
    public static object Windows(){var items=new List<object>();EnumWindows(delegate(IntPtr h,IntPtr p){if(IsWindowVisible(h))items.Add(WindowInfo(h));return true;},IntPtr.Zero);return items;}
    public static object WindowMetadata(string id){return WindowInfo(Window(id));}
    static string ElementId(AutomationElement e){return "uia:"+String.Join(".",Array.ConvertAll(e.GetRuntimeId(),x=>x.ToString(CultureInfo.InvariantCulture)));}
    static readonly AutomationPattern[] patterns={InvokePattern.Pattern,ValuePattern.Pattern,TogglePattern.Pattern,ScrollPattern.Pattern,TextPattern.Pattern,SelectionPattern.Pattern,SelectionItemPattern.Pattern,RangeValuePattern.Pattern,ExpandCollapsePattern.Pattern};
    static readonly string[] patternNames={"invoke","value","toggle","scroll","text","selection","selectionItem","rangeValue","expandCollapse"};
    static double Finite(double n){return Double.IsNaN(n)||Double.IsInfinity(n)?0:n;}
    static object Node(AutomationElement e,int depth,string parent){var c=e.Current;var b=c.BoundingRectangle;var supported=new List<string>();object p;for(int n=0;n<patterns.Length;n++)if(e.TryGetCurrentPattern(patterns[n],out p))supported.Add(patternNames[n]);bool protectedField=ProtectedField(e);var d=Map("id",ElementId(e),"parentId",parent,"depth",depth,"name",c.Name,"role",c.ControlType.ProgrammaticName.Replace("ControlType.",""),"className",c.ClassName,"nativeWindowHandle",c.NativeWindowHandle,"automationId",c.AutomationId,"bounds",Map("x",Finite(b.X),"y",Finite(b.Y),"width",Finite(b.Width),"height",Finite(b.Height)),"enabled",c.IsEnabled,"offscreen",c.IsOffscreen,"isPassword",protectedField,"patterns",supported);if(!protectedField && e.TryGetCurrentPattern(ValuePattern.Pattern,out p))d["value"]=((ValuePattern)p).Current.Value;return d;}
    public static object Inspect(string id,int maxDepth,int maxNodes){return InspectCore(id,maxDepth,maxNodes,false);}
    public static object InspectElements(string id,string[] elementIds){
        if(elementIds==null || elementIds.Length<1 || elementIds.Length>8)throw new ArgumentException("Element read limits out of range");
        var h=Window(id);var root=AutomationElement.FromHandle(h);string rootId=ElementId(root);
        string indexedRoot;if(!indexedRoots.TryGetValue(id,out indexedRoot) || indexedRoot!=rootId)throw new InvalidOperationException("stale_element_token");
        var nodes=new List<object>();
        foreach(string elementId in elementIds){
            if(String.IsNullOrEmpty(elementId))throw new ArgumentException("Invalid elementId");
            var e=Find(h,elementId,true);
            nodes.Add(Node(e,0,null));
        }
        return Map("windowId",id,"tree",nodes);
    }
    static object InspectCore(string id,int maxDepth,int maxNodes,bool guarded){if(maxDepth<0||maxDepth>20||maxNodes<1||maxNodes>5000)throw new ArgumentException("Inspection limits out of range");var h=Window(id);var root=AutomationElement.FromHandle(h);elementIndexes[Id(h)]=new Dictionary<string,AutomationElement>();indexedRoots[Id(h)]=ElementId(root);var nodes=new List<object>();var queue=new Queue<Tuple<AutomationElement,int,string>>();queue.Enqueue(Tuple.Create(root,0,(string)null));bool truncated=false;while(queue.Count>0&&nodes.Count<maxNodes){var t=queue.Dequeue();string eid;try{eid=ElementId(t.Item1);IndexElement(h,t.Item1);nodes.Add(Node(t.Item1,t.Item2,t.Item3));}catch(ElementNotAvailableException){continue;}if(guarded && t.Item2>0 && t.Item1.Current.IsOffscreen)continue;var child=TreeWalker.ControlViewWalker.GetFirstChild(t.Item1);if(t.Item2>=maxDepth){if(child!=null)truncated=true;continue;}while(child!=null){queue.Enqueue(Tuple.Create(child,t.Item2+1,eid));if(queue.Count+nodes.Count>=maxNodes){truncated=true;break;}child=TreeWalker.ControlViewWalker.GetNextSibling(child);}}if(queue.Count>0)truncated=true;return Map("window",WindowInfo(h),"tree",nodes,"truncated",truncated);}
    static readonly Dictionary<string,Dictionary<string,AutomationElement>> elementIndexes=new Dictionary<string,Dictionary<string,AutomationElement>>();
    static readonly Dictionary<string,string> indexedRoots=new Dictionary<string,string>();
    static void IndexElement(IntPtr h,AutomationElement e) {
        string window=Id(h);Dictionary<string,AutomationElement> index;
        if(!elementIndexes.TryGetValue(window,out index)){index=new Dictionary<string,AutomationElement>();elementIndexes[window]=index;}
        index[ElementId(e)]=e;
    }
    static bool CurrentDescendant(IntPtr h,AutomationElement e,string rootId) {
        // Cached references shorten lookup; current ancestry still proves the
        // control has not migrated to another window of the same process.
        for(int n=0;e!=null && n<64;n++,e=TreeWalker.ControlViewWalker.GetParent(e)){
            if(ElementId(e)==rootId)return true;var handle=new IntPtr(e.Current.NativeWindowHandle);
            if(handle!=IntPtr.Zero)return handle==h || IsChild(h,handle);
        }return false;
    }
    static AutomationElement Find(IntPtr h,string id,bool guarded=false){var root=AutomationElement.FromHandle(h);string rootId=ElementId(root),window=Id(h);if(String.IsNullOrEmpty(id)||rootId==id)return root;
        Dictionary<string,AutomationElement> index;AutomationElement known;string previous;
        if(indexedRoots.TryGetValue(window,out previous) && previous==rootId && elementIndexes.TryGetValue(window,out index) && index.TryGetValue(id,out known))try{if(ElementId(known)==id && CurrentDescendant(h,known,rootId))return known;}catch(ElementNotAvailableException){}
        // A missing/stale indexed control is refused remotely rather than
        // rediscovering a different control under an old projection token.
        if(guarded && indexedRoots.ContainsKey(window))throw new InvalidOperationException("stale_element_token");
        var queue=new Queue<AutomationElement>();queue.Enqueue(root);int count=0;while(queue.Count>0&&count++<10000){var e=queue.Dequeue();IndexElement(h,e);if(ElementId(e)==id)return e;var child=TreeWalker.ControlViewWalker.GetFirstChild(e);while(child!=null){queue.Enqueue(child);child=TreeWalker.ControlViewWalker.GetNextSibling(child);}}throw new ArgumentException("elementId is not a current descendant of the target window");}
    static T Pattern<T>(AutomationElement e,AutomationPattern pattern){object p;if(!e.TryGetCurrentPattern(pattern,out p))throw new InvalidOperationException("Requested UI Automation pattern unsupported");return (T)p;}
    static IntPtr MessageTarget(IntPtr window,AutomationElement e){var candidate=e;while(candidate!=null){var h=new IntPtr(candidate.Current.NativeWindowHandle);if(h!=IntPtr.Zero){if(h!=window&&!IsChild(window,h))throw new InvalidOperationException("Native target is outside window");return h;}candidate=TreeWalker.ControlViewWalker.GetParent(candidate);if(candidate!=null&&ElementId(candidate)==ElementId(AutomationElement.FromHandle(window)))return window;}throw new InvalidOperationException("No native handle for background message target");}
    static void Post(IntPtr h,uint msg,int w,int l){if(!PostMessage(h,msg,new IntPtr(w),new IntPtr(l)))throw new InvalidOperationException("PostMessage failed: "+Marshal.GetLastWin32Error());}
    static string ClassName(IntPtr h){var s=new StringBuilder(256);GetClassName(h,s,s.Capacity);return s.ToString();}
    static void CheckPostedInput(IntPtr root,IntPtr target,bool keyboard){
        // Framework exclusions follow trycua/cua's MIT Windows delivery matrix:
        // https://github.com/trycua/cua/blob/main/libs/cua-driver/rust/crates/platform-windows/src/input/delivery.rs
        string c=ClassName(root), child=ClassName(target);
        if(c.StartsWith("Chrome_")||child.StartsWith("Chrome_")||c.StartsWith("TkTopLevel")||c=="WinUIDesktopWin32WindowClass"||c.StartsWith("HwndWrapper")||(!keyboard&&c.StartsWith("gdk"))||(keyboard&&c.StartsWith("SAL")))throw new InvalidOperationException("background_unavailable: target framework requires a supported UI Automation pattern");
    }
    static int Key(string key){switch((key??"").ToUpperInvariant()){case "BACKSPACE":return 8;case "TAB":return 9;case "ENTER":return 13;case "ESCAPE":return 27;case "SPACE":return 32;case "PAGEUP":return 33;case "PAGEDOWN":return 34;case "END":return 35;case "HOME":return 36;case "LEFT":return 37;case "UP":return 38;case "RIGHT":return 39;case "DOWN":return 40;case "DELETE":return 46;default:throw new ArgumentException("Only unmodified navigation and editing keys are supported");}}
    static ScrollAmount Scroll(string amount){if(String.IsNullOrEmpty(amount))return ScrollAmount.NoAmount;ScrollAmount value;if(!Enum.TryParse<ScrollAmount>(amount,true,out value))throw new ArgumentException("Invalid scroll amount");return value;}
    public static object Action(string id,string elementId,string action,string text,string value,string horizontal,string vertical,string x,string y,string key){return ActionCore(id,elementId,action,text,value,horizontal,vertical,x,y,key,false);}
    static object ActionCore(string id,string elementId,string action,string text,string value,string horizontal,string vertical,string x,string y,string key,bool guarded,AutomationElement supplied=null){if(guarded)RemoteGuard(id);var h=Window(id);if(IsIconic(h))throw new InvalidOperationException("Minimized target cannot be acted upon");var e=supplied??Find(h,elementId,guarded);if(guarded)CheckProtection(e);if(e.Current.IsPassword)throw new InvalidOperationException("protected_window");if(!e.Current.IsEnabled)throw new InvalidOperationException("Target element is disabled");var before=Status();string mechanism="uia";object result=null;switch(action){
        case "buttonClick":var bh=new IntPtr(e.Current.NativeWindowHandle);if(bh==IntPtr.Zero||!IsChild(h,bh)||!(ClassName(bh).StartsWith("WindowsForms10.BUTTON")||ClassName(bh)=="Button"))throw new InvalidOperationException("Unsupported native button message target");UIntPtr delivered;if(SendMessageTimeout(bh,0xF5,IntPtr.Zero,IntPtr.Zero,2,1000,out delivered)==IntPtr.Zero)throw new InvalidOperationException("Native button delivery uncertain: "+Marshal.GetLastWin32Error());mechanism="BM_CLICK";break;
        case "editAppend":case "editSetValue":{
            var eh=new IntPtr(e.Current.NativeWindowHandle);string ec=ClassName(eh);
            if(eh==IntPtr.Zero||!IsChild(h,eh)||!(ec.StartsWith("WindowsForms10.EDIT")||ec=="Edit"))throw new InvalidOperationException("Unsupported native edit message target");
            var evp=Pattern<ValuePattern>(e,ValuePattern.Pattern);if(evp.Current.IsReadOnly)throw new InvalidOperationException("Target value is read-only");
            string desired=(action=="editAppend"?evp.Current.Value:"")+(text??value??"");if(desired.Length>100000)throw new ArgumentException("Native edit exceeds 100000 characters");
            IntPtr memory=Marshal.StringToHGlobalUni(desired);try{UIntPtr sent;if(SendMessageTimeout(eh,0xC,IntPtr.Zero,memory,2,1000,out sent)==IntPtr.Zero)throw new InvalidOperationException("Native text delivery uncertain: "+Marshal.GetLastWin32Error());}finally{Marshal.FreeHGlobal(memory);}
            mechanism="WM_SETTEXT";result=desired;break;
        }
        case "invoke":Pattern<InvokePattern>(e,InvokePattern.Pattern).Invoke();break;
        case "value":var vp=Pattern<ValuePattern>(e,ValuePattern.Pattern);if(vp.Current.IsReadOnly)throw new InvalidOperationException("Target value is read-only");vp.SetValue(String.IsNullOrEmpty(text)?value:text);break;
        case "toggle":Pattern<TogglePattern>(e,TogglePattern.Pattern).Toggle();break;
        case "scroll":Pattern<ScrollPattern>(e,ScrollPattern.Pattern).Scroll(Scroll(horizontal),Scroll(vertical));break;
        case "select":Pattern<SelectionItemPattern>(e,SelectionItemPattern.Pattern).Select();break;
        case "expand":Pattern<ExpandCollapsePattern>(e,ExpandCollapsePattern.Pattern).Expand();break;
        case "collapse":Pattern<ExpandCollapsePattern>(e,ExpandCollapsePattern.Pattern).Collapse();break;
        case "rangeValue":Pattern<RangeValuePattern>(e,RangeValuePattern.Pattern).SetValue(Double.Parse(value,CultureInfo.InvariantCulture));break;
        case "text":result=Pattern<TextPattern>(e,TextPattern.Pattern).DocumentRange.GetText(100000);break;
        case "click":object ip;if(e.TryGetCurrentPattern(InvokePattern.Pattern,out ip)){((InvokePattern)ip).Invoke();break;}var target=MessageTarget(h,e);CheckPostedInput(h,target,false);var b=e.Current.BoundingRectangle;var point=new POINT{X=String.IsNullOrEmpty(x)?(int)(b.X+b.Width/2):Int32.Parse(x),Y=String.IsNullOrEmpty(y)?(int)(b.Y+b.Height/2):Int32.Parse(y)};if(!b.Contains(new System.Windows.Point(point.X,point.Y)))throw new ArgumentException("Click coordinate is outside selected element");if(!ScreenToClient(target,ref point))throw new InvalidOperationException("ScreenToClient failed");if(point.X<0||point.Y<0||point.X>32767||point.Y>32767)throw new ArgumentException("Client point out of range");int packed=(point.Y<<16)|(point.X&65535);Post(target,0x201,1,packed);Post(target,0x202,0,packed);mechanism="postMessage";break;
        case "key":var kh=MessageTarget(h,e);CheckPostedInput(h,kh,true);int vk=Key(key);Post(kh,0x100,vk,1);Post(kh,0x101,vk,unchecked((int)0xC0000001));mechanism="postMessage";break;
        default:throw new ArgumentException("Unknown action");}
        // Providers may run an asynchronous native handler; observe the completed immediate effect.
        if(!(action.StartsWith("edit") || action=="value" || action=="rangeValue" || action=="text" || action=="select" || action=="expand" || action=="collapse"))Thread.Sleep(75);var after=Status();var bc=(Dictionary<string,object>)before["cursor"];var ac=(Dictionary<string,object>)after["cursor"];bool foreground=Equals(before["foregroundWindowId"],after["foregroundWindowId"])&&Equals(before["foregroundGeneration"],after["foregroundGeneration"]);bool cursor=Equals(bc["x"],ac["x"])&&Equals(bc["y"],ac["y"]);string effect="unverifiable";object readback=null;try{if(guarded){RemoteGuard(id);CheckProtection(e);}if(action.StartsWith("edit")){readback=Pattern<ValuePattern>(e,ValuePattern.Pattern).Current.Value;effect=Equals(readback,result)?"confirmed":"partial";}else if(action=="value"){readback=Pattern<ValuePattern>(e,ValuePattern.Pattern).Current.Value;effect=Equals(readback,String.IsNullOrEmpty(text)?value:text)?"confirmed":"partial";}else if(action=="text"){readback=result;effect="confirmed";}else if(action=="rangeValue"){readback=Pattern<RangeValuePattern>(e,RangeValuePattern.Pattern).Current.Value;effect=Equals(readback,Double.Parse(value,CultureInfo.InvariantCulture))?"confirmed":"partial";}else if(action=="select"){readback=Pattern<SelectionItemPattern>(e,SelectionItemPattern.Pattern).Current.IsSelected;effect=(bool)readback?"confirmed":"partial";}else if(action=="expand"||action=="collapse"){readback=Pattern<ExpandCollapsePattern>(e,ExpandCollapsePattern.Pattern).Current.ExpandCollapseState.ToString();effect=Equals(readback,action=="expand"?"Expanded":"Collapsed")?"confirmed":"partial";}}catch(ElementNotAvailableException){}return Map("action",action,"elementId",elementId,"mechanism",mechanism,"effect",effect,"readback",readback,"delivery","background","result",result,"before",before,"after",after,"foregroundPreserved",foreground,"cursorPreserved",cursor);}

    // Privacy admission reads only protection flags and control metadata, never
    // Value/TextPattern. Opaque windows may be shared; typing fails closed per field.
    static void CheckProtection(AutomationElement e) {
        var c=e.Current;
        if(ProtectedField(e))throw new InvalidOperationException("protected_field");
    }
    static bool ProtectedField(AutomationElement e) {
        var c=e.Current;
        return c.IsPassword || ((c.ControlType==ControlType.Edit || c.ControlType==ControlType.Document) && System.Text.RegularExpressions.Regex.IsMatch((c.Name??"")+" "+(c.AutomationId??""),@"\b(password|passphrase|credential|secret|api.?key|access.?token|mot de passe)\b",System.Text.RegularExpressions.RegexOptions.IgnoreCase));
    }
    static void TypingGuard(IntPtr window,AutomationElement e) {
        CheckProtection(e);var c=e.Current;object pattern;
        if((c.ControlType!=ControlType.Edit && c.ControlType!=ControlType.Document) || !e.TryGetCurrentPattern(ValuePattern.Pattern,out pattern))throw new InvalidOperationException("protection_unknown");
        // A focused opaque field is never interpreted as an ordinary editor.
        uint pid;uint thread=GetWindowThreadProcessId(window,out pid);var info=new GUITHREADINFO{cbSize=(uint)Marshal.SizeOf(typeof(GUITHREADINFO))};
        if(!GetGUIThreadInfo(thread,ref info))throw new InvalidOperationException("protection_unknown");
        if(info.hwndFocus!=IntPtr.Zero && (info.hwndFocus==window || IsChild(window,info.hwndFocus))){
            var focus=AutomationElement.FromHandle(info.hwndFocus);CheckProtection(focus);var kind=focus.Current.ControlType;
            if(kind==ControlType.Custom || kind==ControlType.Pane || kind==ControlType.Window || ((kind==ControlType.Edit || kind==ControlType.Document) && !focus.TryGetCurrentPattern(ValuePattern.Pattern,out pattern)))throw new InvalidOperationException("protection_unknown");
        }
    }
    public static object RemoteGuard(string id) {
        Window(id);
        return Map("safe",true,"protection","per_field");
    }
    sealed class RemoteTree {
        public AutomationElement Root;
        public string RootId;
        public string Children;
        public Dictionary<string,object> Observation;
        public readonly object Sync=new object();
        public readonly HashSet<string> Dirty=new HashSet<string>();
        public bool StructureChanged=true;
        public AutomationPropertyChangedEventHandler PropertyHandler;
        public StructureChangedEventHandler StructureHandler;
    }
    static readonly Dictionary<string,RemoteTree> remoteTrees=new Dictionary<string,RemoteTree>();
    static string ChildIdentity(AutomationElement root) {
        var ids=new List<string>();var children=root.FindAll(TreeScope.Children,Condition.TrueCondition);
        foreach(AutomationElement child in children)try{ids.Add(ElementId(child));}catch(ElementNotAvailableException){}
        return String.Join("|",ids.ToArray());
    }
    static void RemoveRemoteTree(string id) {
        RemoteTree state;if(!remoteTrees.TryGetValue(id,out state))return;
        try{Automation.RemoveAutomationPropertyChangedEventHandler(state.Root,state.PropertyHandler);Automation.RemoveStructureChangedEventHandler(state.Root,state.StructureHandler);}catch(ElementNotAvailableException){}
        remoteTrees.Remove(id);elementIndexes.Remove(id);indexedRoots.Remove(id);
    }
    static object RemoteProjection(string id) {
        var root=AutomationElement.FromHandle(Window(id));string identity=ElementId(root);RemoteTree state;
        if(remoteTrees.TryGetValue(id,out state) && state.RootId!=identity){RemoveRemoteTree(id);state=null;}
        if(state==null){
            if(remoteTrees.Count>=32){var evict=new List<string>(remoteTrees.Keys);foreach(var key in evict)RemoveRemoteTree(key);}
            state=new RemoteTree{Root=root,RootId=identity};var owned=state;
            state.PropertyHandler=delegate(object source,AutomationPropertyChangedEventArgs change){try{string changed=ElementId((AutomationElement)source);lock(owned.Sync){if(owned.Dirty.Count>=5000){owned.Dirty.Clear();owned.StructureChanged=true;}else owned.Dirty.Add(changed);}}catch(ElementNotAvailableException){lock(owned.Sync)owned.StructureChanged=true;}};
            state.StructureHandler=delegate(object source,StructureChangedEventArgs change){lock(owned.Sync)owned.StructureChanged=true;};
            Automation.AddAutomationPropertyChangedEventHandler(root,TreeScope.Subtree,state.PropertyHandler,AutomationElement.NameProperty,AutomationElement.IsPasswordProperty,AutomationElement.IsEnabledProperty,AutomationElement.IsOffscreenProperty,AutomationElement.BoundingRectangleProperty,ValuePattern.ValueProperty);
            Automation.AddStructureChangedEventHandler(root,TreeScope.Subtree,state.StructureHandler);remoteTrees[id]=state;
        }
        // Some legacy providers omit a removal event. Validate the shallow
        // child identities instead of walking the complete tree on each frame.
        string children=ChildIdentity(root);
        bool rebuild;string[] dirty;lock(state.Sync){rebuild=state.StructureChanged || state.Children!=children;state.Children=children;state.StructureChanged=false;dirty=new List<string>(state.Dirty).ToArray();state.Dirty.Clear();}
        if(rebuild || state.Observation==null)state.Observation=(Dictionary<string,object>)InspectCore(id,8,256,true);
        else{
            var rows=(List<object>)state.Observation["tree"];var changes=new HashSet<string>(dirty);
            for(int i=0;i<rows.Count;i++){var previous=(Dictionary<string,object>)rows[i];string element=(string)previous["id"];if(!changes.Contains(element))continue;AutomationElement native;
                if(!elementIndexes[id].TryGetValue(element,out native)){lock(state.Sync)state.StructureChanged=true;continue;}
                try{rows[i]=Node(native,(int)previous["depth"],(string)previous["parentId"]);}catch(ElementNotAvailableException){lock(state.Sync)state.StructureChanged=true;}
            }
            state.Observation["window"]=WindowInfo(Window(id));
        }
        return state.Observation;
    }
    public static object RemoteObserve(string id,bool image) {
        RemoteGuard(id);var tree=(Dictionary<string,object>)RemoteProjection(id);
        object capture=image?Capture(id):null;RemoteGuard(id);
        return Map("observation",tree,"capture",capture);
    }
    public static object RemoteAction(string id,string elementId,string action,string text,string horizontal,string vertical,string x,string y,string key,string expectedName,string expectedRole,string expectedClass,long inputGeneration) {
        RemoteGuard(id);var e=Find(Window(id),elementId,true);var c=e.Current;CheckProtection(e);
        if(c.Name!=expectedName || c.ControlType.ProgrammaticName.Replace("ControlType.","")!=expectedRole || c.ClassName!=expectedClass)throw new InvalidOperationException("stale_element_token");
        if(action=="valueAppend" || action=="editAppend" || action=="value" || action=="key")TypingGuard(Window(id),e);
        if(Convert.ToInt64(Status()["inputGeneration"])!=inputGeneration)throw new InvalidOperationException("host_takeover");
        if(action=="valueAppend"){text=Pattern<ValuePattern>(e,ValuePattern.Pattern).Current.Value+(text??"");action="value";}
        var value=(Dictionary<string,object>)ActionCore(id,elementId,action,text,null,horizontal,vertical,x,y,key,true,e);
        RemoteTree tree;if(remoteTrees.TryGetValue(id,out tree))lock(tree.Sync)tree.Dirty.Add(elementId);
        RemoteGuard(id);
        // Native readback is used only to determine effect, never sent remotely.
        return Map("effect",value["effect"],"mechanism",value["mechanism"],"foregroundPreserved",value["foregroundPreserved"],"cursorPreserved",value["cursorPreserved"]);
    }
    public static object Capture(string id){var h=Window(id);if(IsIconic(h))throw new InvalidOperationException("Minimized window cannot be captured");RECT r;if(!GetWindowRect(h,out r))throw new InvalidOperationException("GetWindowRect failed");int w=r.Right-r.Left,height=r.Bottom-r.Top;if(w<1||height<1||w>16384||height>16384||(long)w*height>40000000)throw new InvalidOperationException("Capture dimensions invalid");using(var bmp=new Bitmap(w,height,PixelFormat.Format32bppArgb)){using(var g=Graphics.FromImage(bmp)){g.Clear(Color.Black);var dc=g.GetHdc();bool ok;try{ok=PrintWindow(h,dc,2);}finally{g.ReleaseHdc(dc);}if(!ok)throw new InvalidOperationException("PrintWindow unavailable for target");}int first=bmp.GetPixel(w/2,height/2).ToArgb();bool varied=false;for(int yy=0;yy<height&&!varied;yy+=Math.Max(1,height/40))for(int xx=0;xx<w;xx+=Math.Max(1,w/40))if(bmp.GetPixel(xx,yy).ToArgb()!=first){varied=true;break;}if(!varied)throw new InvalidOperationException("PrintWindow produced a blank capture");using(var stream=new MemoryStream()){bmp.Save(stream,ImageFormat.Png);return Map("windowId",id,"width",w,"height",height,"mimeType","image/png","pngBase64",Convert.ToBase64String(stream.ToArray()),"method","PrintWindow");}}}
}}
