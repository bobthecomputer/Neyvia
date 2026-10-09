// "Invoice Builder": a small WinForms app an agent builds and then tests on the
// private agent desktop (agent view proof). Compiled per run into a token-named
// task-local folder as *probe.exe so the C11 driver admits it as a disposable
// target. It never activates itself; the window lives only on the agent desktop.
using System;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Windows.Forms;

public class InvoiceWindow : Form {
    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams { get { var p = base.CreateParams; p.ExStyle |= 0x08000000; return p; } }
}

public static class InvoiceProbe {
    static TextBox Field(Control parent, string label, string name, int top) {
        parent.Controls.Add(new Label { Text = label, Location = new Point(28, top + 4), Size = new Size(150, 26), ForeColor = Color.FromArgb(70, 84, 76) });
        var box = new TextBox { AccessibleName = name, Location = new Point(190, top), Width = 260, Font = new Font("Segoe UI", 12f) };
        parent.Controls.Add(box);
        return box;
    }

    [STAThread] public static void Main(string[] args) {
        string state = args[0];
        Application.EnableVisualStyles();
        var window = new InvoiceWindow { Text = "Invoice Builder - build 0.3 (testing)", Size = new Size(560, 420), Location = new Point(80, 80),
            StartPosition = FormStartPosition.Manual, BackColor = Color.FromArgb(250, 248, 242), Font = new Font("Segoe UI", 11f) };
        var header = new Panel { Location = new Point(0, 0), Size = new Size(560, 64), BackColor = Color.FromArgb(22, 58, 42) };
        header.Controls.Add(new Label { Text = "Invoice Builder", Location = new Point(26, 12), Size = new Size(320, 34), ForeColor = Color.White, Font = new Font("Segoe UI Semibold", 17f) });
        header.Controls.Add(new Label { Text = "build 0.3", Location = new Point(430, 22), Size = new Size(100, 24), ForeColor = Color.FromArgb(170, 214, 186) });
        window.Controls.Add(header);
        var quantity = Field(window, "Quantity", "Quantity", 92);
        var price = Field(window, "Unit price (EUR)", "Unit price", 136);
        var vat = Field(window, "VAT rate (%)", "VAT rate", 180);
        var compute = new Button { Text = "Compute total", AccessibleName = "Compute total", Location = new Point(190, 228), Size = new Size(260, 38),
            BackColor = Color.FromArgb(38, 120, 78), ForeColor = Color.White, FlatStyle = FlatStyle.Flat };
        compute.FlatAppearance.BorderSize = 0;
        var total = new Label { Text = "Total: -", AccessibleName = "Total", Location = new Point(28, 290), Size = new Size(480, 40),
            Font = new Font("Segoe UI Semibold", 18f), ForeColor = Color.FromArgb(22, 58, 42) };
        var note = new Label { Text = "Enter quantity, price and VAT, then compute.", Location = new Point(28, 334), Size = new Size(480, 24), ForeColor = Color.FromArgb(110, 120, 114) };
        compute.Click += delegate {
            decimal q, p, v;
            var culture = CultureInfo.InvariantCulture;
            if (decimal.TryParse(quantity.Text.Replace(',', '.'), NumberStyles.Number, culture, out q)
                && decimal.TryParse(price.Text.Replace(',', '.'), NumberStyles.Number, culture, out p)
                && decimal.TryParse(vat.Text.Replace(',', '.'), NumberStyles.Number, culture, out v)) {
                var sum = Math.Round(q * p * (1 + v / 100m), 2, MidpointRounding.AwayFromZero);
                total.Text = "Total: " + sum.ToString("0.00", culture) + " EUR";
                note.Text = q.ToString(culture) + " x " + p.ToString("0.00", culture) + " EUR + " + v.ToString(culture) + "% VAT";
            } else {
                total.Text = "Total: check the fields";
            }
            File.WriteAllText(state + ".result", total.Text);
        };
        window.Controls.AddRange(new Control[] { compute, total, note });
        window.Shown += delegate { File.WriteAllText(state, window.Handle.ToInt64().ToString()); };
        Application.Run(window);
    }
}
