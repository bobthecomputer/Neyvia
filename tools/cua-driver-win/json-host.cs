// Hidden JSONL host for the Windows UI Automation worker.
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using System.Web.Script.Serialization;
using System.Threading;

internal static class CuaJsonHost {
    private const int MaxLine = 16 * 1024 * 1024;
    private static Type worker;
    private static readonly JavaScriptSerializer json = new JavaScriptSerializer {
        MaxJsonLength = MaxLine, RecursionLimit = 100
    };

    private static object Arg(Dictionary<string, object> args, string key) {
        object value;
        return args.TryGetValue(key, out value) ? value : null;
    }

    private static string Str(Dictionary<string, object> args, string key) {
        object value = Arg(args, key);
        return value == null ? "" : Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture);
    }

    private static object Call(string method, params object[] args) {
        try {
            return worker.GetMethod(method, BindingFlags.Public | BindingFlags.Static).Invoke(null, args);
        } catch (TargetInvocationException error) {
            throw error.InnerException ?? error;
        }
    }

    private static object Dispatch(string op, Dictionary<string, object> args) {
        switch (op) {
            case "windows": return Call("Windows");
            case "window": return Call("WindowMetadata", Str(args, "windowId"));
            case "status": return Call("Status");
            case "desktopStatus": return Call("DesktopStatus");
            case "inspect": return Call("Inspect", Str(args, "windowId"),
                Arg(args, "maxDepth") == null ? 8 : Convert.ToInt32(Arg(args, "maxDepth")),
                Arg(args, "maxNodes") == null ? 500 : Convert.ToInt32(Arg(args, "maxNodes")));
            case "inspectElements": {
                var ids = Arg(args, "elementIds") as object[];
                if (ids == null) throw new ArgumentException("elementIds must be an array");
                var current = new string[ids.Length];
                for (int i = 0; i < ids.Length; i++) current[i] = ids[i] as string;
                return Call("InspectElements", Str(args, "windowId"), current);
            }
            case "remoteGuard": return Call("RemoteGuard", Str(args, "windowId"));
            case "remoteObserve": return Call("RemoteObserve", Str(args, "windowId"),
                Arg(args, "image") != null && Convert.ToBoolean(Arg(args, "image")));
            case "remoteAction": return Call("RemoteAction", Str(args, "windowId"), Str(args, "elementId"),
                Str(args, "action"), Str(args, "text"), Str(args, "horizontal"), Str(args, "vertical"),
                Str(args, "x"), Str(args, "y"), Str(args, "key"), Str(args, "expectedName"),
                Str(args, "expectedRole"), Str(args, "expectedClass"),
                Arg(args, "inputGeneration") == null ? 0L : Convert.ToInt64(Arg(args, "inputGeneration")));
            case "capture": return Call("Capture", Str(args, "windowId"));
            case "action": return Call("Action", Str(args, "windowId"), Str(args, "elementId"),
                Str(args, "action"), Str(args, "text"), Str(args, "value"), Str(args, "horizontal"),
                Str(args, "vertical"), Str(args, "x"), Str(args, "y"), Str(args, "key"));
            default: throw new ArgumentException("Unknown operation");
        }
    }

    // Keep UIA on a non-UI MTA thread; this transport remains opt-in.
    [MTAThread]
    private static int Main(string[] argv) {
        if (argv.Length != 1) return 2;
        // Use inherited pipe handles directly, including under CREATE_NO_WINDOW.
        var input = new StreamReader(Console.OpenStandardInput(), new UTF8Encoding(false));
        var output = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false));
        output.AutoFlush = true;
        try {
            string framework = Path.GetDirectoryName(typeof(object).Assembly.Location);
            foreach (string name in new [] { "UIAutomationClient", "UIAutomationTypes", "WindowsBase" })
                Assembly.LoadFrom(Path.Combine(framework, "WPF", name + ".dll"));
            worker = Assembly.LoadFrom(argv[0]).GetType("T16.NativeWorker", true);
            Call("StartHooks");
        } catch (Exception error) {
            var stderr = new StreamWriter(Console.OpenStandardError(), new UTF8Encoding(false));
            stderr.WriteLine("Native worker initialization failed: " + error.Message);
            stderr.Flush();
            return 1;
        }
        string line;
        while ((line = input.ReadLine()) != null) {
            object id = null;
            object response;
            try {
                if (line.Length > MaxLine) throw new ArgumentException("Native request exceeds 16 MiB");
                var request = json.DeserializeObject(line) as Dictionary<string, object>;
                if (request == null) throw new ArgumentException("Invalid native request");
                request.TryGetValue("id", out id);
                var args = Arg(request, "args") as Dictionary<string, object>;
                response = new Dictionary<string, object> {
                    {"id", id}, {"ok", true}, {"data", Dispatch(Str(request, "op"), args ?? new Dictionary<string, object>())}
                };
            } catch (Exception error) {
                response = new Dictionary<string, object> {
                    {"id", id}, {"ok", false}, {"error", error.Message}
                };
            }
            try {
                string encoded = json.Serialize(response);
                if (Encoding.UTF8.GetByteCount(encoded) > MaxLine) throw new ArgumentException("Native response exceeds 16 MiB");
                output.WriteLine(encoded);
            } catch (Exception error) {
                output.WriteLine(json.Serialize(new Dictionary<string, object> {
                    {"id", id}, {"ok", false}, {"error", error.Message}
                }));
            }
        }
        return 0;
    }
}
