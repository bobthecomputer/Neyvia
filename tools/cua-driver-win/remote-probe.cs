// Disposable real native app, never substituted for Zen/other product proof.
using System;
using System.IO;
using System.Drawing;
using System.Windows.Forms;
public class RemoteProbeForm : Form {
    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams {get {var p=base.CreateParams;p.ExStyle|=0x08000000;return p;}}
}
public static class RemoteProbe {
    [STAThread] public static void Main(string[] args) {
        string state=args[0];bool masked=args.Length>1 && args[1]=="masked";bool large=args.Length>1 && args[1]=="large";
        var f=new RemoteProbeForm{Text=masked?"T19 Private Native Probe":"T19 Allowed Native Probe",
            Size=new Size(large?1800:480,large?450:300), Location=new Point(masked?610:90,200),StartPosition=FormStartPosition.Manual};
        var input=new TextBox{Text=masked?"DISPOSABLE_MASKED_SENTINEL":"initial",UseSystemPasswordChar=masked,
            AccessibleName=masked?"Private entry":"Task input",Name="t19Input",Location=new Point(20,30),Width=420};
        var apply=new Button{Text="Apply",Name="t19Apply",Location=new Point(20,80),Size=new Size(420,34)};
        var output=new Label{Text="Waiting",Name="t19Result",Location=new Point(20,135),Size=new Size(420,70)};
        apply.Click+=delegate{output.Text="Applied: "+input.Text;File.WriteAllText(state+".result",output.Text);};
        var timer=new Timer{Interval=100};timer.Tick+=delegate{
            input.UseSystemPasswordChar=masked || File.Exists(state+".protect");
            apply.Text=File.Exists(state+".rename")?"Delete":"Apply";
        };timer.Start();
        f.Controls.AddRange(new Control[]{input,apply,output});
        f.Shown+=delegate{File.WriteAllText(state,f.Handle.ToInt64().ToString());};Application.Run(f);
    }
}
