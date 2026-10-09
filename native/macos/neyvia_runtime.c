/* Clean-room AppKit host. Public Objective-C ABI; no Apple SDK headers.
 * Both architectures use a fixed initial content rectangle. Avoid x86_64's
 * struct-return objc_msgSend ABI by never querying CGRect/NSRect results. */
typedef void *Object;
typedef void *Selector;
typedef unsigned long UInteger;
typedef signed char Bool;
typedef struct { double x, y, width, height; } Rect;
extern Object objc_getClass(const char *);
extern Object objc_allocateClassPair(Object, const char *, unsigned long);
extern void objc_registerClassPair(Object);
extern Selector sel_registerName(const char *);
extern Bool class_addMethod(Object, Selector, void *, const char *);
extern void objc_msgSend(void);
extern void *dlopen(const char *, int);
static Object window, webview, delegate;
static Selector sel(const char *s) { return sel_registerName(s); }
static Object send(Object o, const char *s) {
    return ((Object (*)(Object, Selector))objc_msgSend)(o, sel(s));
}
static Object send1(Object o, const char *s, Object a) {
    return ((Object (*)(Object, Selector, Object))objc_msgSend)(o, sel(s), a);
}
static void integer(Object o, const char *s, UInteger a) {
    ((void (*)(Object, Selector, UInteger))objc_msgSend)(o, sel(s), a);
}
static Object string(const char *s) {
    return ((Object (*)(Object, Selector, const char *))objc_msgSend)(objc_getClass("NSString"), sel("stringWithUTF8String:"), s);
}
static Bool close_last(Object self, Selector cmd, Object app) {
    (void)self; (void)cmd; (void)app; return 1;
}
static void launched(Object self, Selector cmd, Object notification) {
    (void)self; (void)cmd; (void)notification;
    Rect rect = {0, 0, 1120, 760};
    window = ((Object (*)(Object, Selector, Rect, UInteger, UInteger, Bool))objc_msgSend)(
        send(objc_getClass("NSWindow"), "alloc"), sel("initWithContentRect:styleMask:backing:defer:"),
        rect, 1 | 2 | 4 | 8, 2, 0);
    integer(window, "setReleasedWhenClosed:", 0);
    send1(window, "setTitle:", send1(send(objc_getClass("NSBundle"), "mainBundle"), "objectForInfoDictionaryKey:", string("CFBundleDisplayName")));
    Object config = send(send(objc_getClass("WKWebViewConfiguration"), "alloc"), "init");
    webview = ((Object (*)(Object, Selector, Rect, Object))objc_msgSend)(
        send(objc_getClass("WKWebView"), "alloc"), sel("initWithFrame:configuration:"), rect, config);
    integer(webview, "setAutoresizingMask:", 2 | 16);
    send1(window, "setContentView:", webview);
    Object resources = send(send(objc_getClass("NSBundle"), "mainBundle"), "resourceURL");
    Object webroot = send1(resources, "URLByAppendingPathComponent:", string("www"));
    Object index = send1(webroot, "URLByAppendingPathComponent:", string("index.html"));
    ((Object (*)(Object, Selector, Object, Object))objc_msgSend)(webview, sel("loadFileURL:allowingReadAccessToURL:"), index, webroot);
    send(window, "center");
    send1(window, "makeKeyAndOrderFront:", (Object)0);
    integer(send(objc_getClass("NSApplication"), "sharedApplication"), "activateIgnoringOtherApps:", 1);
}
int main(void) {
    dlopen("/System/Library/Frameworks/AppKit.framework/AppKit", 2);
    dlopen("/System/Library/Frameworks/WebKit.framework/WebKit", 2);
    Object pool = send(send(objc_getClass("NSAutoreleasePool"), "alloc"), "init");
    Object app = send(objc_getClass("NSApplication"), "sharedApplication");
    integer(app, "setActivationPolicy:", 0);
    Object cls = objc_allocateClassPair(objc_getClass("NSObject"), "NeyviaMacDelegate", 0);
    class_addMethod(cls, sel("applicationDidFinishLaunching:"), (void *)launched, "v@:@");
    class_addMethod(cls, sel("applicationShouldTerminateAfterLastWindowClosed:"), (void *)close_last, "c@:@");
    objc_registerClassPair(cls);
    delegate = send(send(cls, "alloc"), "init");
    send1(app, "setDelegate:", delegate);
    /* A standard application menu supplies Quit and WebKit copy/paste keys. */
    Object menu = send(send(objc_getClass("NSMenu"), "alloc"), "init");
    Object item = send(send(objc_getClass("NSMenuItem"), "alloc"), "init");
    Object submenu = send(send(objc_getClass("NSMenu"), "alloc"), "init");
    send1(menu, "addItem:", item); send1(item, "setSubmenu:", submenu);
    const char *titles[] = {"Quit", "Cut", "Copy", "Paste", "Select All"};
    const char *actions[] = {"terminate:", "cut:", "copy:", "paste:", "selectAll:"};
    const char *keys[] = {"q", "x", "c", "v", "a"};
    for (int i = 0; i < 5; ++i) {
        Object entry = ((Object (*)(Object, Selector, Object, Selector, Object))objc_msgSend)(
            send(objc_getClass("NSMenuItem"), "alloc"), sel("initWithTitle:action:keyEquivalent:"), string(titles[i]), sel(actions[i]), string(keys[i]));
        send1(submenu, "addItem:", entry);
    }
    send1(app, "setMainMenu:", menu);
    send(app, "run"); send(pool, "drain"); return 0;
}
