// Real disposable application for native actions and protection refusals.
using System;
using System.IO;
using System.Drawing;
using System.Windows.Forms;
public class C1Window : Form {
    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams { get { var p=base.CreateParams; p.ExStyle|=0x08000000; return p; } }
}
public class C1ScrollList : ListBox {
    public string ScrollStatePath;
    protected override void WndProc(ref Message message) {
        int kind=message.Msg;
        base.WndProc(ref message);
        if(kind==0x115 && ScrollStatePath!=null)File.WriteAllText(ScrollStatePath,TopIndex.ToString());
    }
}
public static class C1Probe {
    [STAThread] public static void Main(string[] args) {
        string state=args[0];
        var window=new C1Window { Text="C1b Native Action Probe",Size=new Size(730,440),Location=new Point(90,110),StartPosition=FormStartPosition.Manual };
        var input=new TextBox { Text="initial",AccessibleName="Task input",Name="c1TaskInput",Location=new Point(24,32),Width=390 };
        var apply=new Button { Text="Apply",Location=new Point(24,70),Size=new Size(390,30) };
        var output=new Label { Text="Waiting",Location=new Point(24,108),Size=new Size(390,28) };
        var option=new CheckBox { Text="Include heading",AccessibleName="Include heading",Location=new Point(24,144),Width=390 };
        var readOnly=new TextBox { Text="Read-only fixture",AccessibleName="Read-only fixture",ReadOnly=true,Location=new Point(24,178),Width=390 };
        var secret=new TextBox { Text="synthetic lab fixture",AccessibleName="API key",Location=new Point(24,212),Width=390 };
        var password=new TextBox { Text="synthetic lab fixture",AccessibleName="Password",UseSystemPasswordChar=true,Location=new Point(24,246),Width=390 };
        var disable=new Button { Text="Lock input",Location=new Point(24,280),Size=new Size(190,30) };
        var enable=new Button { Text="Unlock input",Location=new Point(224,280),Size=new Size(190,30) };
        var list=new C1ScrollList { ScrollStatePath=state+".scroll",AccessibleName="Preview scroll list",Location=new Point(440,32),Size=new Size(250,300) };
        for(int i=0;i<30;i++)list.Items.Add("Preview item "+i);
        apply.Click+=delegate { output.Text="Applied: "+input.Text; File.WriteAllText(state+".result",output.Text); };
        disable.Click+=delegate { input.Enabled=false; };
        enable.Click+=delegate { input.Enabled=true; };
#if C11PREVIEW
        window.Controls.AddRange(new Control[]{input,apply,output,option,disable,enable,list});
#else
        window.Controls.AddRange(new Control[]{input,apply,output,option,readOnly,secret,password,disable,enable,list});
#endif
        window.Shown+=delegate { File.WriteAllText(state+".scroll",list.TopIndex.ToString()); File.WriteAllText(state,window.Handle.ToInt64().ToString()); };
        Application.Run(window);
    }
}
