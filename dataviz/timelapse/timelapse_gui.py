# timelapse_gui.py
"""
GUI module for Satellite Timelapse Generator.
Imports processing routines from timelapse_processor.py and builds a Tkinter interface.
Run with: python timelapse_gui.py
"""
import os
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from glob import glob
from PIL import Image, ImageTk
from typing import Dict, List, Tuple, Optional
import threading

from timelapse_processor import (
    load_metadata, compute_quality_score, detect_outliers,
    process_frame, create_timelapse
)

# Resolution presets
RESOLUTION_PRESETS = {
    "Custom": None,
    "720p (1280×720)": (1280, 720),
    "1080p (1920×1080)": (1920, 1080),
    "4K (3840×2160)": (3840, 2160),
    "Original Size": "original"
}

class SatelliteTimelapseApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Satellite Timelapse Generator")
        self.geometry("1200x820")
        self.metadata_map: Dict[str, Dict] = {}
        self.image_files: List[str] = []
        self.filtered_files: List[str] = []
        self.quality_scores: List[float] = []
        self.tkimg = None
        self.setup_vars()
        self.build_ui()
        self.bind_events()

    def setup_vars(self):
        self.input_dir = tk.StringVar()
        self.output_file = tk.StringVar()
        self.fps = tk.IntVar(value=30)
        self.resolution = tk.StringVar(value="1080p (1920×1080)")
        # Quality thresholds
        self.cloud_th = tk.DoubleVar(value=0.1)
        self.haze_th = tk.DoubleVar(value=0.0)
        self.shadow_th = tk.DoubleVar(value=0.0)
        self.snow_th = tk.DoubleVar(value=0.0)
        self.anom_th = tk.DoubleVar(value=0.0)
        self.clear_th = tk.DoubleVar(value=80.0)
        self.vis_th = tk.DoubleVar(value=80.0)
        self.angle_th = tk.DoubleVar(value=5.0)
        # Outliers
        self.enable_out = tk.BooleanVar(value=True)
        self.outlier_std = tk.DoubleVar(value=1.5)
        # Processing flags
        self.stabilize = tk.BooleanVar(value=False)
        self.hist_match = tk.BooleanVar(value=True)
        self.white_bal = tk.BooleanVar(value=False)
        self.contrast = tk.BooleanVar(value=False)
        self.meta_overlay = tk.BooleanVar(value=True)
        self.overlay_pos = tk.StringVar(value="bottom")
        self.font_size = tk.IntVar(value=24)
        self.max_workers = tk.IntVar(value=os.cpu_count())
        self.use_all = tk.BooleanVar(value=False)
        # Frame & length info
        self.frame_count = tk.IntVar(value=0)
        self.estimated_length = tk.DoubleVar(value=0.0)
        self.final_length = tk.DoubleVar(value=0.0)

    def build_ui(self):
        # Input/Output
        f = ttk.Frame(self)
        f.pack(fill="x", pady=5)
        ttk.Label(f, text="Input Folder:").pack(side="left")
        ttk.Entry(f, textvariable=self.input_dir, width=60).pack(side="left", padx=5)
        ttk.Button(f, text="Browse", command=self.browse_input).pack(side="left")
        ttk.Label(f, text="Output File:").pack(side="left", padx=10)
        ttk.Entry(f, textvariable=self.output_file, width=30).pack(side="left", padx=5)
        ttk.Button(f, text="Save As", command=self.browse_output).pack(side="left")

        # Quality Filters
        qf = ttk.Labelframe(self, text="Quality Filters")
        qf.pack(fill="x", pady=5)
        labels = ["Max Cloud %:", "Max Haze %:", "Max Shadow %:"]
        vars = [self.cloud_th, self.haze_th, self.shadow_th]
        for i,(lbl,var) in enumerate(zip(labels,vars)):
            ttk.Label(qf, text=lbl).grid(row=0, column=2*i, padx=5)
            ttk.Entry(qf, textvariable=var, width=6).grid(row=0, column=2*i+1)
        labels2 = ["Max Snow/Ice %:", "Max Anom Pixels %:", "Min Clear %:"]
        vars2 = [self.snow_th, self.anom_th, self.clear_th]
        for i,(lbl,var) in enumerate(zip(labels2,vars2)):
            ttk.Label(qf, text=lbl).grid(row=1, column=2*i, padx=5)
            ttk.Entry(qf, textvariable=var, width=6).grid(row=1, column=2*i+1)
        ttk.Label(qf, text="Min Visible %:").grid(row=2, column=0, padx=5)
        ttk.Entry(qf, textvariable=self.vis_th, width=6).grid(row=2, column=1)
        ttk.Label(qf, text="Max Angle°:").grid(row=2, column=2, padx=5)
        ttk.Entry(qf, textvariable=self.angle_th, width=6).grid(row=2, column=3)
        ttk.Checkbutton(qf, text="Use All Frames", variable=self.use_all, command=self.update_filters).grid(
            row=3, column=0, columnspan=4, sticky="w", padx=5)

        # Outlier Detection
        of = ttk.Labelframe(self, text="Outlier Detection")
        of.pack(fill="x", pady=5)
        ttk.Checkbutton(of, text="Enable Outliers", variable=self.enable_out,
                        command=self.update_filters).grid(row=0, column=0, padx=5)
        ttk.Label(of, text="Std Dev:").grid(row=0, column=1, padx=5)
        ttk.Entry(of, textvariable=self.outlier_std, width=6).grid(row=0, column=2)

        # Processing Options
        pf = ttk.Labelframe(self, text="Processing Options")
        pf.pack(fill="x", pady=5)
        opts = [("Stabilize", self.stabilize),
                ("Hist Match", self.hist_match),
                ("White Balance", self.white_bal),
                ("Contrast", self.contrast)]
        for i,(t,v) in enumerate(opts):
            ttk.Checkbutton(pf, text=t, variable=v).grid(row=0, column=i, padx=5)
        ttk.Checkbutton(pf, text="Metadata Overlay", variable=self.meta_overlay).grid(row=1, column=0, padx=5)
        ttk.Label(pf, text="Pos:").grid(row=1, column=1, padx=5)
        ttk.Combobox(pf, textvariable=self.overlay_pos,
                     values=["top","bottom"], width=8).grid(row=1, column=2)
        ttk.Label(pf, text="Font:").grid(row=1, column=3, padx=5)
        ttk.Entry(pf, textvariable=self.font_size, width=4).grid(row=1, column=4)
        ttk.Label(pf, text="Workers:").grid(row=1, column=5, padx=5)
        ttk.Entry(pf, textvariable=self.max_workers, width=4).grid(row=1, column=6)

        # Video Settings + Frame/Length info
        vf = ttk.Labelframe(self, text="Video Settings")
        vf.pack(fill="x", pady=5)
        ttk.Label(vf, text="FPS:").grid(row=0, column=0, padx=5)
        ttk.Entry(vf, textvariable=self.fps, width=6).grid(row=0, column=1)
        ttk.Label(vf, text="Res:").grid(row=0, column=2, padx=5)
        ttk.Combobox(vf, textvariable=self.resolution,
                     values=list(RESOLUTION_PRESETS.keys()), width=14).grid(row=0, column=3)
        ttk.Button(vf, text="Create", command=self.on_create).grid(row=0, column=4, padx=10)
        # Live frame count & estimate
        ttk.Label(vf, text="Frames:").grid(row=1, column=0, pady=5)
        ttk.Label(vf, textvariable=self.frame_count).grid(row=1, column=1)
        ttk.Label(vf, text="Est. Sec:").grid(row=1, column=2)
        ttk.Label(vf, textvariable=self.estimated_length).grid(row=1, column=3)
        ttk.Label(vf, text="Final Length (s):").grid(row=1, column=4)
        ttk.Entry(vf, textvariable=self.final_length, width=6).grid(row=1, column=5)

        # Frames list
        lf = ttk.Labelframe(self, text="Frames")
        lf.pack(fill="both", expand=False, pady=5)
        self.listbox = tk.Listbox(lf, height=8)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.listbox.yview)
        sb.pack(side="right", fill="y")
        self.listbox.config(yscrollcommand=sb.set)

        # Preview
        prf = ttk.Labelframe(self, text="Preview")
        prf.pack(fill="both", expand=True, pady=5)
        self.canvas = tk.Canvas(prf, bg="black")
        self.canvas.pack(fill="both", expand=True)
        ttk.Button(prf, text="Preview", command=self.preview).pack(pady=5)

    def bind_events(self):
        self.input_dir.trace_add('write', lambda *a: self.scan_dir())
        for v in [self.cloud_th, self.haze_th, self.shadow_th, self.snow_th,
                  self.anom_th, self.clear_th, self.vis_th, self.angle_th,
                  self.enable_out, self.outlier_std, self.use_all]:
            v.trace_add('write', lambda *a: self.update_filters())
        # Recompute estimate on FPS change
        self.fps.trace_add('write', lambda *a: self.update_estimate())
        # Adjust FPS on final length change
        self.final_length.trace_add('write', lambda *a: self.update_fps_from_length())
        self.listbox.bind('<<ListboxSelect>>', lambda e: self.preview())

    def browse_input(self):
        d = filedialog.askdirectory()
        if d: self.input_dir.set(d)

    def browse_output(self):
        f = filedialog.asksaveasfilename(defaultextension=".mp4",
                                         filetypes=[("MP4","*.mp4"),("All","*.*")])
        if f: self.output_file.set(f)

    def scan_dir(self):
        d = self.input_dir.get()
        if not os.path.isdir(d): return
        self.metadata_map.clear()
        self.quality_scores.clear()
        tifs = sorted(glob(os.path.join(d, '*.tif')))
        for tif in tifs:
            md = load_metadata(tif.replace('.tif','_metadata.json'))
            if md is not None:
                self.metadata_map[tif] = md
                self.quality_scores.append(compute_quality_score(md))
        self.image_files = tifs
        self.update_filters()

    def update_filters(self):
        if self.use_all.get():
            self.filtered_files = self.image_files.copy()
        else:
            ths = (
                self.cloud_th.get()*100, self.haze_th.get()*100,
                self.shadow_th.get()*100, self.snow_th.get()*100,
                self.anom_th.get()*100, self.clear_th.get(),
                self.vis_th.get(), self.angle_th.get()
            )
            out_flags = detect_outliers(self.quality_scores, self.outlier_std.get()) if self.enable_out.get() else [False]*len(self.image_files)
            sel = []
            for i,f in enumerate(self.image_files):
                p = self.metadata_map.get(f, {})
                cond = (
                    p.get('cloud_percent',0) <= ths[0] and
                    (p.get('heavy_haze_percent',0)+p.get('light_haze_percent',0)) <= ths[1] and
                    p.get('shadow_percent',0) <= ths[2] and
                    p.get('snow_ice_percent',0) <= ths[3] and
                    p.get('anomalous_pixels',0) <= ths[4] and
                    p.get('clear_confidence_percent',100) >= ths[5] and
                    p.get('visible_confidence_percent',100) >= ths[6] and
                    p.get('view_angle',0) <= ths[7]
                )
                if cond and not out_flags[i]: sel.append(f)
            self.filtered_files = sel
        self.listbox.delete(0, 'end')
        for f in self.image_files:
            self.listbox.insert('end', os.path.basename(f))
            self.listbox.itemconfig('end', fg='black' if f in self.filtered_files else 'gray')
        # Update frame count and estimate
        self.frame_count.set(len(self.filtered_files))
        self.update_estimate()

    def update_estimate(self):
        fc = self.frame_count.get()
        fps = self.fps.get()
        if fps > 0:
            est = round(fc / fps, 2)
        else:
            est = 0.0
        self.estimated_length.set(est)

    def update_fps_from_length(self):
        fl = self.final_length.get()
        fc = self.frame_count.get()
        if fl > 0 and fc > 0:
            new_fps = int(round(fc / fl))
            if new_fps > 0:
                self.fps.set(new_fps)

    def preview(self):
        sel = self.listbox.curselection()
        if not sel or not self.filtered_files: return
        idx = sel[0]
        path = self.image_files[idx]
        params = self.get_params()
        params['metadata'] = self.metadata_map.get(path, {})
        ref = self.filtered_files[0]
        ref_img = process_frame((ref,0,params,None))['frame']
        out = process_frame((path,1,params,ref_img))['frame']
        img = Image.fromarray(ImageTk.PhotoImage(out).zoom(1))
        img = Image.fromarray(out)
        img = Image.fromarray(out)
        # Convert and display
        img = Image.fromarray(out)
        img = img.resize((self.canvas.winfo_width(), self.canvas.winfo_height()), Image.ANTIALIAS)
        self.tkimg = ImageTk.PhotoImage(img)
        self.canvas.delete('all')
        self.canvas.create_image(0,0,anchor='nw',image=self.tkimg)

    def get_params(self) -> Dict:
        return {
            'fps': self.fps.get(),
            'output_size': RESOLUTION_PRESETS[self.resolution.get()],
            'filtered_files': self.filtered_files,
            'stabilize': self.stabilize.get(),
            'histogram_matching': self.hist_match.get(),
            'white_balance': self.white_bal.get(),
            'contrast_enhance': self.contrast.get(),
            'metadata_overlay': self.meta_overlay.get(),
            'overlay_position': self.overlay_pos.get(),
            'font_size': self.font_size.get(),
            'max_workers': self.max_workers.get()
        }

    def on_create(self):
        if not self.filtered_files:
            messagebox.showwarning("No Frames","No frames to process")
            return
        if not self.output_file.get():
            messagebox.showerror("Output","Specify output file")
            return
        self.progress = ttk.Progressbar(self, mode='determinate',
                                        maximum=len(self.filtered_files))
        self.progress.pack(fill='x', pady=5)
        def job():
            stats = create_timelapse(self.input_dir.get(),
                                      self.output_file.get(),
                                      self.get_params())
            messagebox.showinfo("Done",
                f"Processed {stats['processed_frames']} frames with {stats['errors']} errors in {stats['time']:.1f}s")
            self.progress.destroy()
        threading.Thread(target=job, daemon=True).start()

if __name__ == "__main__":
    SatelliteTimelapseApp().mainloop()
