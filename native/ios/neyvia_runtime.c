/*
 * Neyvia clean-room iOS runtime.
 *
 * This file intentionally imports no Apple SDK headers. It uses the public
 * Objective-C runtime ABI and UIKit's documented application entry point to
 * host a bundled web UI in WKWebView. The executable is compiled as a real
 * arm64 Mach-O target by LLVM on the local Windows machine through WSL.
 */

typedef void *NObject;
typedef void *NClass;
typedef void *NSelector;
typedef signed char NBool;
typedef unsigned long NUnsigned;

typedef struct {
    double x;
    double y;
} NPoint;

typedef struct {
    double width;
    double height;
} NSize;

typedef struct {
    NPoint origin;
    NSize size;
} NRect;

extern NClass objc_getClass(const char *name);
extern NClass objc_allocateClassPair(NClass superclass, const char *name, unsigned long extra_bytes);
extern void objc_registerClassPair(NClass cls);
extern NSelector sel_registerName(const char *name);
extern NBool class_addMethod(NClass cls, NSelector selector, void *implementation, const char *types);
extern void objc_msgSend(void);
#if defined(__x86_64__)
extern void objc_msgSend_stret(void);
#endif
extern int UIApplicationMain(int argc, char **argv, NObject principal_class_name, NObject delegate_class_name);
extern void *dlopen(const char *path, int mode);

static NSelector n_selector(const char *name) {
    return sel_registerName(name);
}

static NObject n_send0(NObject receiver, const char *selector) {
    return ((NObject (*)(NObject, NSelector))objc_msgSend)(receiver, n_selector(selector));
}

static NObject n_send1(NObject receiver, const char *selector, NObject value) {
    return ((NObject (*)(NObject, NSelector, NObject))objc_msgSend)(receiver, n_selector(selector), value);
}

static NObject n_send_rect(NObject receiver, const char *selector, NRect value) {
    return ((NObject (*)(NObject, NSelector, NRect))objc_msgSend)(receiver, n_selector(selector), value);
}

static NObject n_send_rect_object(NObject receiver, const char *selector, NRect rect, NObject value) {
    return ((NObject (*)(NObject, NSelector, NRect, NObject))objc_msgSend)(
        receiver,
        n_selector(selector),
        rect,
        value
    );
}

static NRect n_send_rect_result(NObject receiver, const char *selector) {
#if defined(__x86_64__)
    return ((NRect (*)(NObject, NSelector))objc_msgSend_stret)(receiver, n_selector(selector));
#else
    return ((NRect (*)(NObject, NSelector))objc_msgSend)(receiver, n_selector(selector));
#endif
}

static void n_send_void0(NObject receiver, const char *selector) {
    ((void (*)(NObject, NSelector))objc_msgSend)(receiver, n_selector(selector));
}

static void n_send_void1(NObject receiver, const char *selector, NObject value) {
    ((void (*)(NObject, NSelector, NObject))objc_msgSend)(receiver, n_selector(selector), value);
}

static void n_send_unsigned(NObject receiver, const char *selector, NUnsigned value) {
    ((void (*)(NObject, NSelector, NUnsigned))objc_msgSend)(receiver, n_selector(selector), value);
}

static NObject n_string(const char *value) {
    return ((NObject (*)(NObject, NSelector, const char *))objc_msgSend)(
        (NObject)objc_getClass("NSString"),
        n_selector("stringWithUTF8String:"),
        value
    );
}

static NBool neyvia_did_finish_launching(
    NObject self,
    NSelector command,
    NObject application,
    NObject launch_options
) {
    NObject screen;
    NRect bounds;
    NObject window;
    NObject controller;
    NObject root_view;
    NObject configuration;
    NObject web_view;
    NObject bundle;
    NObject resources;
    NObject web_root;
    NObject index_url;
    NObject background;

    (void)self;
    (void)command;
    (void)application;
    (void)launch_options;

    dlopen("/System/Library/Frameworks/WebKit.framework/WebKit", 1);

    screen = n_send0((NObject)objc_getClass("UIScreen"), "mainScreen");
    bounds = n_send_rect_result(screen, "bounds");
    window = n_send_rect(
        n_send0((NObject)objc_getClass("UIWindow"), "alloc"),
        "initWithFrame:",
        bounds
    );
    controller = n_send0(n_send0((NObject)objc_getClass("UIViewController"), "alloc"), "init");
    root_view = n_send0(controller, "view");
    background = n_send0((NObject)objc_getClass("UIColor"), "systemBackgroundColor");
    n_send_void1(root_view, "setBackgroundColor:", background);

    configuration = n_send0(
        n_send0((NObject)objc_getClass("WKWebViewConfiguration"), "alloc"),
        "init"
    );
    web_view = n_send_rect_object(
        n_send0((NObject)objc_getClass("WKWebView"), "alloc"),
        "initWithFrame:configuration:",
        bounds,
        configuration
    );
    n_send_unsigned(web_view, "setAutoresizingMask:", (1UL << 1) | (1UL << 4));
    n_send_void1(root_view, "addSubview:", web_view);

    bundle = n_send0((NObject)objc_getClass("NSBundle"), "mainBundle");
    resources = n_send0(bundle, "resourceURL");
    web_root = n_send1(resources, "URLByAppendingPathComponent:", n_string("www"));
    index_url = n_send1(web_root, "URLByAppendingPathComponent:", n_string("index.html"));
    ((NObject (*)(NObject, NSelector, NObject, NObject))objc_msgSend)(
        web_view,
        n_selector("loadFileURL:allowingReadAccessToURL:"),
        index_url,
        web_root
    );

    n_send_void1(window, "setRootViewController:", controller);
    n_send_void0(window, "makeKeyAndVisible");
    return 1;
}

__attribute__((visibility("default")))
int main(int argc, char **argv) {
    const char *delegate_name = "NeyviaAppDelegate";
    NClass delegate = objc_allocateClassPair(objc_getClass("NSObject"), delegate_name, 0);
    class_addMethod(
        delegate,
        n_selector("application:didFinishLaunchingWithOptions:"),
        (void *)&neyvia_did_finish_launching,
        "B@:@@"
    );
    objc_registerClassPair(delegate);
    return UIApplicationMain(argc, argv, (NObject)0, n_string(delegate_name));
}
