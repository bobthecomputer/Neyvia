using System;
using System.Drawing;
using System.Threading;
using System.Windows.Forms;

// Host-visible, independent of any browser. EOF or missing service heartbeat
// removes the indicator; the service treats its disappearance as revocation.
public class RemoteIndicator : Form {
    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams {
        get { var p=base.CreateParams; p.ExStyle|=0x08000000; return p; }
    }
    static long heartbeat=DateTime.UtcNow.Ticks;
    [STAThread] public static void Main() {
        var f=new RemoteIndicator { Text="Neyvia remote control", TopMost=true,
            FormBorderStyle=FormBorderStyle.FixedToolWindow, MaximizeBox=false,
            MinimizeBox=false, Size=new Size(440,115), StartPosition=FormStartPosition.Manual,
            Location=new Point(Screen.PrimaryScreen.WorkingArea.Right-460,24),
            BackColor=Color.FromArgb(125,24,30), ForeColor=Color.White };
        var label=new Label { Text="Being controlled remotely", AutoSize=true,
            Location=new Point(16,12), Font=new Font("Segoe UI",12,FontStyle.Bold) };
        var stop=new Button { Text="Stop now", AccessibleName="Stop remote control now",
            Location=new Point(16,43), Size=new Size(390,28), ForeColor=Color.Black,
            BackColor=Color.White, Font=new Font("Segoe UI",10,FontStyle.Bold) };
        stop.Click+=delegate { Console.WriteLine("STOP");Console.Out.Flush();f.Close(); };
        f.Controls.AddRange(new Control[]{label,stop});
        f.Shown+=delegate {Console.WriteLine("READY "+f.Handle.ToInt64());Console.Out.Flush();};
        f.FormClosed+=delegate {Console.WriteLine("STOP");Console.Out.Flush();};
        var timer=new System.Windows.Forms.Timer { Interval=150 };
        timer.Tick+=delegate {if(DateTime.UtcNow.Ticks-Interlocked.Read(ref heartbeat)>TimeSpan.FromSeconds(3).Ticks)f.Close();};timer.Start();
        new Thread(delegate(){while(Console.ReadLine()!=null)Interlocked.Exchange(ref heartbeat,DateTime.UtcNow.Ticks);Interlocked.Exchange(ref heartbeat,0);}){IsBackground=true}.Start();
        Application.Run(f);
    }
}
