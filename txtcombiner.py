import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from datetime import datetime

class TextFileCombiner:
    def __init__(self, root):
        self.root = root
        self.root.title("Text File Combiner")
        self.root.geometry("600x400")
        
        # Variables
        self.input_dir = tk.StringVar()
        self.max_size_mb = tk.DoubleVar(value=10.0)  # Default max size: 10MB
        self.files = []
        
        # GUI Elements
        self.create_widgets()
        
    def create_widgets(self):
        # Input Directory Selection
        tk.Label(self.root, text="Input Directory:").pack(pady=5)
        tk.Entry(self.root, textvariable=self.input_dir, width=50).pack()
        tk.Button(self.root, text="Browse", command=self.browse_dir).pack(pady=5)
        
        # Max File Size
        tk.Label(self.root, text="Max Output File Size (MB):").pack(pady=5)
        tk.Entry(self.root, textvariable=self.max_size_mb, width=10).pack()
        
        # Buttons
        tk.Button(self.root, text="Scan Files", command=self.scan_files).pack(pady=10)
        tk.Button(self.root, text="Combine into Single File", command=lambda: self.combine_files(single=True)).pack(pady=5)
        tk.Button(self.root, text="Combine into Multiple Files", command=lambda: self.combine_files(single=False)).pack(pady=5)
        
        # Status
        self.status = tk.Label(self.root, text="Ready", wraplength=550)
        self.status.pack(pady=10)
        
        # Progress Bar
        self.progress = ttk.Progressbar(self.root, length=400, mode='determinate')
        self.progress.pack(pady=10)
        
    def browse_dir(self):
        directory = filedialog.askdirectory()
        if directory:
            self.input_dir.set(directory)
            self.status.config(text=f"Selected directory: {directory}")
            
    def scan_files(self):
        directory = self.input_dir.get()
        if not directory or not os.path.isdir(directory):
            messagebox.showerror("Error", "Please select a valid directory")
            return
            
        self.files = []
        self.status.config(text="Scanning files...")
        self.root.update()
        
        try:
            for filename in os.listdir(directory):
                if filename.lower().endswith('.txt'):
                    filepath = os.path.join(directory, filename)
                    size_mb = os.path.getsize(filepath) / (1024 * 1024)  # Convert to MB
                    self.files.append((filepath, size_mb))
            
            self.files.sort(key=lambda x: x[1])  # Sort by size
            total_size = sum(size for _, size in self.files)
            self.status.config(text=f"Found {len(self.files)} text files. Total size: {total_size:.2f} MB")
            
        except Exception as e:
            messagebox.showerror("Error", f"Error scanning files: {str(e)}")
            self.status.config(text="Error during scan")
            
    def combine_files(self, single=True):
        if not self.files:
            messagebox.showerror("Error", "Please scan files first")
            return
            
        output_dir = filedialog.askdirectory(title="Select Output Directory")
        if not output_dir:
            return
            
        max_size_bytes = self.max_size_mb.get() * 1024 * 1024  # Convert MB to bytes
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        self.status.config(text="Combining files...")
        self.progress['maximum'] = len(self.files)
        self.root.update()
        
        try:
            if single:
                output_file = os.path.join(output_dir, f"combined_{timestamp}.txt")
                self._write_single_file(output_file)
            else:
                self._write_multiple_files(output_dir, max_size_bytes, timestamp)
                
            messagebox.showinfo("Success", "Files combined successfully!")
            self.status.config(text="Combination complete")
            
        except Exception as e:
            messagebox.showerror("Error", f"Error combining files: {str(e)}")
            self.status.config(text="Error during combination")
            
        self.progress['value'] = 0
        
    def _write_single_file(self, output_file):
        with open(output_file, 'w', encoding='utf-8') as outfile:
            for i, (filepath, _) in enumerate(self.files):
                with open(filepath, 'r', encoding='utf-8') as infile:
                    outfile.write(f"\n=== {os.path.basename(filepath)} ===\n")
                    outfile.write(infile.read())
                self.progress['value'] = i + 1
                self.root.update()
                
    def _write_multiple_files(self, output_dir, max_size, timestamp):
        current_size = 0
        file_count = 1
        current_file = None
        
        for i, (filepath, size_mb) in enumerate(self.files):
            size_bytes = size_mb * 1024 * 1024
            
            # Start new file if current size exceeds max or first file
            if current_size + size_bytes > max_size or current_file is None:
                if current_file:
                    current_file.close()
                current_file = open(os.path.join(output_dir, f"combined_{timestamp}_{file_count}.txt"), 
                                  'w', encoding='utf-8')
                current_size = 0
                file_count += 1
                
            with open(filepath, 'r', encoding='utf-8') as infile:
                current_file.write(f"\n=== {os.path.basename(filepath)} ===\n")
                current_file.write(infile.read())
                current_size += size_bytes
                
            self.progress['value'] = i + 1
            self.root.update()
            
        if current_file:
            current_file.close()

def main():
    root = tk.Tk()
    app = TextFileCombiner(root)
    root.mainloop()

if __name__ == "__main__":
    main()