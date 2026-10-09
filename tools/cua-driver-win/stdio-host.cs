// GUI-subsystem host prevents console allocation, while retaining real MCP pipes.
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

public static class T16StdioHost {
    [StructLayout(LayoutKind.Sequential)] struct Limits {
        public long ProcessTime, JobTime; public uint Flags;
        public UIntPtr Minimum, Maximum; public uint Active; public UIntPtr Affinity;
        public uint Priority, Scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] struct IoCounters { public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes; }
    [StructLayout(LayoutKind.Sequential)] struct ExtendedLimits {
        public Limits Basic; public IoCounters Io;
        public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] static extern IntPtr CreateJobObject(IntPtr attrs, string name);
    [DllImport("kernel32.dll")] static extern bool SetInformationJobObject(IntPtr job, int kind, ref ExtendedLimits value, uint size);
    [DllImport("kernel32.dll")] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    static Thread Copy(Stream input, Stream output, bool close) {
        var thread = new Thread(delegate() {
            try { var buffer=new byte[16384]; int count; while((count=input.Read(buffer,0,buffer.Length))>0){output.Write(buffer,0,count);output.Flush();} }
            catch(IOException) {} finally { if(close) output.Close(); }
        }); thread.IsBackground=true; thread.Start(); return thread;
    }
    public static int Main(string[] args) {
        if(args.Length!=1) return 2;
        IntPtr job=CreateJobObject(IntPtr.Zero,null);
        var limits=new ExtendedLimits(); limits.Basic.Flags=0x2000; // Kill owned Python if the host is terminated.
        if(job==IntPtr.Zero || !SetInformationJobObject(job,9,ref limits,(uint)Marshal.SizeOf(typeof(ExtendedLimits)))) return 3;
        Process child=null;
        try {
            var start=new ProcessStartInfo(args[0],"-B -m grant_agent.neyvia_cua_mcp") {
                UseShellExecute=false, CreateNoWindow=true, RedirectStandardInput=true,
                RedirectStandardOutput=true, RedirectStandardError=true
            };
            child=Process.Start(start);
            if(!AssignProcessToJobObject(job,child.Handle)){child.Kill();return 4;}
            Copy(Console.OpenStandardInput(),child.StandardInput.BaseStream,true);
            var output=Copy(child.StandardOutput.BaseStream,Console.OpenStandardOutput(),false);
            var error=Copy(child.StandardError.BaseStream,Console.OpenStandardError(),false);
            child.WaitForExit(); output.Join(3000); error.Join(3000); return child.ExitCode;
        } finally { CloseHandle(job); if(child!=null)child.Dispose(); }
    }
}
