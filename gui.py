#!/usr/bin/env python3
"""FeedFix desktop shell (tkinter). Pick a feed file -> audit, fix & re-check."""
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from feed_fix import run_feedfix


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FeedFix — Feed Audit, Fix & Re-Check")
        self.geometry("680x520")
        self.src = tk.StringVar()
        tk.Label(self, text="Google Shopping feed file (.csv / .tsv):").pack(anchor="w", padx=12, pady=(12, 2))
        row = tk.Frame(self)
        row.pack(fill="x", padx=12)
        tk.Entry(row, textvariable=self.src).pack(side="left", fill="x", expand=True)
        tk.Button(row, text="Browse…", command=self.pick).pack(side="left", padx=6)
        self.btn = tk.Button(self, text="Audit, Fix & Re-Check", command=self.run, height=2)
        self.btn.pack(pady=12)
        self.log = scrolledtext.ScrolledText(self, wrap="word")
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.write("FeedFix audits your product feed, repairs the formatting errors,\n"
                   "then re-audits the repaired file to prove it.\n"
                   "Everything runs locally — your feed data never leaves this computer.\n")

    def write(self, s):
        self.log.insert("end", s)
        self.log.see("end")

    def pick(self):
        p = filedialog.askopenfilename(filetypes=[("Feed files", "*.csv *.tsv *.txt"), ("All files", "*.*")])
        if p:
            self.src.set(p)

    def run(self):
        src = self.src.get().strip()
        if not src or not os.path.isfile(src):
            messagebox.showerror("FeedFix", "Choose a feed file first.")
            return
        self.btn.config(state="disabled")
        threading.Thread(target=self._work, args=(src,), daemon=True).start()

    def _work(self, src):
        try:
            outdir = os.path.join(os.path.dirname(src), "feedfix_output")
            s = run_feedfix(src, outdir)
            self.write(f"\nDone. Products: {s['products']} · problems found: {s['found'] + s['fixed']} · "
                       f"auto-fixed: {s['fixed']} · remaining: {s['remaining']} "
                       f"({s['errors_remaining']} blocking errors)\n"
                       f"Repaired feed: {s['fixed_path']}\nReport: {s['report_path']}\n")
            if s["errors_remaining"]:
                self.write("Verdict: NOT READY — the report lists what still needs your input.\n")
            else:
                self.write("Verdict: PASS — no blocking errors remain.\n")
        except Exception as e:  # surface, never crash silently
            self.write(f"\nError: {e}\n")
        finally:
            self.btn.config(state="normal")


if __name__ == "__main__":
    App().mainloop()
