// Disposable native app for the real build -> launch -> agent/Paul test loop.
using System;
using System.IO;
using System.Drawing;
using System.Windows.Forms;

public class T16BackgroundForm : Form {
    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams {
        get { var p = base.CreateParams; p.ExStyle |= 0x08000000; return p; }
    }
}

public static class T16NativeProbe {
    [STAThread]
    public static void Main(string[] args) {
        string state = args[0];
        var window = new T16BackgroundForm { Text = "T16 Built Native Probe", Size = new Size(460, 270),
            Location = new Point(90, 110), StartPosition = FormStartPosition.Manual };
        var input = new TextBox { Text = "initial", AccessibleName = "Task input", Name = "t16TaskInput",
            Location = new Point(24, 32), Width = 390 };
        var button = new Button { Text = "Apply", Name = "t16Apply", Location = new Point(24, 82), Size = new Size(390, 36) };
        var output = new Label { Text = "Waiting", Name = "t16Output", Location = new Point(24, 144), Size = new Size(390, 64) };
        button.Click += delegate { output.Text = "Applied: " + input.Text; File.WriteAllText(state + ".result", output.Text); };
        window.Controls.AddRange(new Control[] { input, button, output });
        window.Shown += delegate { File.WriteAllText(state, window.Handle.ToInt64().ToString()); };
        Application.Run(window);
    }
}
