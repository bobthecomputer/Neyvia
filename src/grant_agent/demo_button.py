from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

from .subprocess_utils import hidden_windows_subprocess_kwargs


def launch_demo_button(root: Path, preset: str, objective: str) -> int:
    try:
        import tkinter as tk
        from tkinter import messagebox
    except Exception as exc:  # pragma: no cover - GUI availability is environment-dependent
        print(json.dumps({"error": f"tkinter unavailable: {exc}"}, indent=2))
        return 1

    app = tk.Tk()
    app.title("Grant Agent One-Click Demo")
    app.geometry("520x260")

    status = tk.StringVar(value="Ready. Press the button to run the full demo bundle.")
    output = tk.StringVar(value="")

    title = tk.Label(app, text="One-Click Demo Run", font=("Segoe UI", 16, "bold"))
    title.pack(pady=10)

    details = tk.Label(
        app,
        text=f"Preset: {preset} | Objective: {objective}",
        wraplength=480,
        justify="left",
    )
    details.pack(pady=4)

    status_label = tk.Label(app, textvariable=status, fg="#1f3a6b", wraplength=480, justify="left")
    status_label.pack(pady=8)

    output_label = tk.Label(app, textvariable=output, fg="#184f2f", wraplength=480, justify="left")
    output_label.pack(pady=8)

    def run_demo() -> None:
        status.set("Running navigator + training comparison + adversarial probe...")
        command = [
            "python",
            "-m",
            "grant_agent.cli",
            "demo-run",
            "--root",
            str(root),
            "--preset",
            preset,
            "--objective",
            objective,
            "--export-zip",
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False, **hidden_windows_subprocess_kwargs())
        if completed.returncode != 0:
            status.set("Demo run failed.")
            messagebox.showerror("Demo run failed", completed.stderr or completed.stdout)
            return

        try:
            payload = json.loads(completed.stdout)
            bundle = payload.get("bundle_path", "")
            status.set("Demo run completed successfully.")
            output.set(f"Bundle: {bundle}")
        except json.JSONDecodeError:
            status.set("Demo run completed. Could not parse output JSON.")
            output.set(completed.stdout.strip())

    def on_click() -> None:
        threading.Thread(target=run_demo, daemon=True).start()

    button = tk.Button(app, text="Run One-Click Demo", command=on_click, padx=18, pady=10)
    button.pack(pady=10)

    app.mainloop()
    return 0
