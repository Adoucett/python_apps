import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from PIL import Image, ExifTags, ImageOps # Ensure Pillow is installed: pip install Pillow
import os
import threading
import queue
import itertools # For unique file additions

# --- Configuration ---
SUPPORTED_INPUT_FORMATS = ('.png', '.tif', '.tiff', '.bmp', '.gif', '.webp', '.jpeg', '.jpg') # Added jpeg, jpg for completeness if one wants to re-process
DEFAULT_JPG_QUALITY = 85
DEFAULT_MAX_WIDTH = 0 # 0 means no resizing by width

# --- Core Conversion Logic (mostly unchanged, but output_folder logic will be more dynamic) ---
def convert_image(image_path, output_path_final, jpg_quality, max_width):
    """Converts a single image to JPG, optionally resizes, and saves it to output_path_final."""
    try:
        img = Image.open(image_path)
        # original_format = img.format # Not strictly needed anymore

        # Preserve orientation from EXIF data
        try:
            for orientation in ExifTags.TAGS.keys():
                if ExifTags.TAGS[orientation] == 'Orientation':
                    break
            exif = dict(img._getexif().items())
            if exif[orientation] == 3:
                img = img.rotate(180, expand=True)
            elif exif[orientation] == 6:
                img = img.rotate(270, expand=True)
            elif exif[orientation] == 8:
                img = img.rotate(90, expand=True)
        except (AttributeError, KeyError, IndexError, TypeError): # Added TypeError for some images
            pass # No EXIF data or 'Orientation' tag

        if img.mode == 'RGBA' or img.mode == 'P':
            img = img.convert('RGB')

        if max_width > 0 and img.width > max_width:
            ratio = max_width / float(img.width)
            new_height = int(float(img.height) * float(ratio))
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
            # print(f"Resized '{os.path.basename(image_path)}' to {max_width}x{new_height}")

        # Ensure output directory for the specific file exists
        output_dir = os.path.dirname(output_path_final)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        img.save(output_path_final, "JPEG", quality=int(jpg_quality), optimize=True)
        # print(f"Successfully converted '{os.path.basename(image_path)}' to '{output_path_final}'")
        return True, f"Converted: {os.path.basename(image_path)} -> {os.path.basename(output_path_final)}"

    except FileNotFoundError:
        return False, f"Error: File not found - {os.path.basename(image_path)}"
    except Exception as e:
        return False, f"Error converting {os.path.basename(image_path)}: {e}"

# --- GUI Class ---
class ImageConverterApp:
    def __init__(self, root_window):
        self.root = root_window
        self.root.title("Advanced Image to JPG Converter 🖼️")
        self.root.geometry("800x700") # Increased size for new elements

        self.found_files_map = {} # Stores full_path: {var_for_checkbox (not used with Treeview), any_other_meta}
                                 # For Treeview, selection will be handled by tree.selection()
        self.progress_queue = queue.Queue()

        # Styling
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TButton", padding=6, relief="flat", font=('Helvetica', 10))
        style.configure("TLabel", padding=5, font=('Helvetica', 10))
        style.configure("TEntry", padding=5, font=('Helvetica', 10))
        style.configure("Header.TLabel", font=('Helvetica', 14, 'bold'))
        style.configure("Accent.TButton", foreground="white", background="#0078D7", font=('Helvetica', 11, 'bold'))
        style.configure("Warning.TButton", foreground="white", background="#E81123", font=('Helvetica', 10, 'bold'))


        # --- UI Elements ---
        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.pack(expand=True, fill=tk.BOTH)

        # Input Selection Frame
        input_frame = ttk.LabelFrame(main_frame, text="📁 Input Sources", padding="10")
        input_frame.pack(fill=tk.X, pady=(0,10))

        self.add_folder_button = ttk.Button(input_frame, text="Add Folder(s) (Recursive)", command=self.add_folders_recursive)
        self.add_folder_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.add_files_button = ttk.Button(input_frame, text="Add File(s)", command=self.add_files)
        self.add_files_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.scan_sources_button = ttk.Button(input_frame, text="🔍 Scan Sources & List Files", command=self.scan_sources_and_populate_tree)
        self.scan_sources_button.pack(side=tk.LEFT, padx=10, pady=5)


        # File List (Treeview)
        file_list_frame = ttk.LabelFrame(main_frame, text="📄 Files Found (Select to Convert)", padding="10")
        file_list_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        tree_scroll_y = ttk.Scrollbar(file_list_frame, orient="vertical")
        tree_scroll_x = ttk.Scrollbar(file_list_frame, orient="horizontal")

        self.file_tree = ttk.Treeview(
            file_list_frame,
            columns=("fullpath",),
            displaycolumns=(), # Hide the 'fullpath' data column from view
            yscrollcommand=tree_scroll_y.set,
            xscrollcommand=tree_scroll_x.set,
            selectmode="extended" # Allows multiple selections
        )
        self.file_tree.heading("#0", text="File Path", anchor=tk.W)
        # self.file_tree.column("fullpath", width=0, stretch=tk.NO) # Hide data column

        tree_scroll_y.config(command=self.file_tree.yview)
        tree_scroll_x.config(command=self.file_tree.xview)

        tree_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        tree_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.file_tree.pack(expand=True, fill=tk.BOTH)

        tree_actions_frame = ttk.Frame(file_list_frame)
        tree_actions_frame.pack(fill=tk.X, pady=(5,0))
        self.select_all_button = ttk.Button(tree_actions_frame, text="Select All", command=self.select_all_files_in_tree)
        self.select_all_button.pack(side=tk.LEFT, padx=5)
        self.deselect_all_button = ttk.Button(tree_actions_frame, text="Deselect All", command=self.deselect_all_files_in_tree)
        self.deselect_all_button.pack(side=tk.LEFT, padx=5)
        self.clear_list_button = ttk.Button(tree_actions_frame, text="Clear List & Sources", command=self.clear_file_list_and_sources, style="Warning.TButton")
        self.clear_list_button.pack(side=tk.LEFT, padx=5)


        # Export Path Frame
        export_path_frame = ttk.LabelFrame(main_frame, text="➡️ Export Options", padding="10")
        export_path_frame.pack(fill=tk.X, pady=10)

        custom_path_label = ttk.Label(export_path_frame, text="Custom Export Path (Optional):")
        custom_path_label.grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.custom_export_path_var = tk.StringVar()
        self.custom_export_entry = ttk.Entry(export_path_frame, textvariable=self.custom_export_path_var, width=40)
        self.custom_export_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        self.browse_export_button = ttk.Button(export_path_frame, text="Browse...", command=self.browse_export_path)
        self.browse_export_button.grid(row=0, column=2, padx=5, pady=5)
        ttk.Label(export_path_frame, text="(Leave blank to save in './JPG/' subfolder of original)").grid(row=1, column=0, columnspan=3, padx=5, sticky=tk.W, pady=(0,5))
        export_path_frame.columnconfigure(1, weight=1)


        # Conversion Options Frame (JPG Quality, Max Width)
        options_frame = ttk.LabelFrame(main_frame, text="⚙️ Conversion Parameters", padding="10")
        options_frame.pack(fill=tk.X, pady=5)

        quality_label = ttk.Label(options_frame, text="JPG Quality (1-100):")
        quality_label.grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.quality_var = tk.IntVar(value=DEFAULT_JPG_QUALITY)
        self.quality_scale = ttk.Scale(options_frame, from_=1, to=100, orient=tk.HORIZONTAL, variable=self.quality_var, length=200)
        self.quality_scale.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        self.quality_value_label = ttk.Label(options_frame, text=str(DEFAULT_JPG_QUALITY))
        self.quality_value_label.grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        self.quality_var.trace_add("write", self.update_quality_label)

        resize_label = ttk.Label(options_frame, text="Max Width (pixels, 0 for original):")
        resize_label.grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.resize_var = tk.IntVar(value=DEFAULT_MAX_WIDTH)
        self.resize_entry = ttk.Entry(options_frame, textvariable=self.resize_var, width=8)
        self.resize_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)
        ttk.Label(options_frame, text="px").grid(row=1, column=2, padx=0, pady=5, sticky=tk.W)
        options_frame.columnconfigure(1, weight=1)


        # Action Button
        self.convert_button = ttk.Button(main_frame, text="🚀 Start Conversion of Selected Files", command=self.start_conversion_thread, style="Accent.TButton")
        self.convert_button.pack(pady=15, ipady=8, fill=tk.X)

        # Progress and Log Area
        progress_log_frame = ttk.Frame(main_frame)
        progress_log_frame.pack(fill=tk.BOTH, expand=True, pady=(5,0))

        self.progress_bar = ttk.Progressbar(progress_log_frame, orient=tk.HORIZONTAL, length=300, mode='determinate')
        self.progress_bar.pack(pady=5, fill=tk.X)
        self.progress_label = ttk.Label(progress_log_frame, text="Waiting for task...")
        self.progress_label.pack(pady=5, fill=tk.X)

        self.log_text = tk.Text(progress_log_frame, height=8, wrap=tk.WORD, state=tk.DISABLED, relief="solid", borderwidth=1, font=('Courier New', 9))
        log_scrollbar = ttk.Scrollbar(progress_log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.input_sources = [] # List of folders and files to scan
        self.processing_thread = None
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def update_quality_label(self, *args):
        self.quality_value_label.config(text=str(self.quality_var.get()))

    def add_folders_recursive(self):
        folders = filedialog.askdirectory(title="Select Folder(s) to Scan Recursively (can select multiple in some OS dialogs, or add one by one)")
        if folders: # askdirectory can return multiple if underlying OS supports it (rare)
            if isinstance(folders, str): # Usually a single string
                folders = [folders]
            for folder in folders:
                if folder not in self.input_sources:
                    self.input_sources.append(folder)
                    self.log_message(f"Added folder source: {folder}")
            self.log_message("Hint: Click 'Scan Sources' to populate the file list.")


    def add_files(self):
        files = filedialog.askopenfilenames(
            title="Select Image File(s)",
            filetypes=[("Image Files", [f"*{ext}" for ext in SUPPORTED_INPUT_FORMATS]), ("All Files", "*.*")]
        )
        if files:
            for file_path in files:
                if file_path not in self.input_sources and file_path.lower().endswith(SUPPORTED_INPUT_FORMATS):
                    self.input_sources.append(file_path)
                    self.log_message(f"Added file source: {file_path}")
                elif not file_path.lower().endswith(SUPPORTED_INPUT_FORMATS):
                    self.log_message(f"Skipped non-image file: {file_path}")
            self.log_message("Hint: Click 'Scan Sources' to populate/update the file list.")


    def scan_sources_and_populate_tree(self):
        self.file_tree.delete(*self.file_tree.get_children()) # Clear existing tree
        self.found_files_map.clear()
        self.log_message("Scanning sources for image files...", clear_current_log=True)

        scanned_file_paths = set() # To avoid duplicates if sources overlap

        for source_path in self.input_sources:
            if os.path.isdir(source_path):
                for dirpath, _, filenames in os.walk(source_path):
                    for filename in filenames:
                        if filename.lower().endswith(SUPPORTED_INPUT_FORMATS):
                            full_path = os.path.join(dirpath, filename)
                            if full_path not in scanned_file_paths:
                                self.file_tree.insert("", tk.END, text=full_path, values=(full_path,))
                                scanned_file_paths.add(full_path)
            elif os.path.isfile(source_path): # Direct file path
                 if source_path.lower().endswith(SUPPORTED_INPUT_FORMATS):
                    if source_path not in scanned_file_paths:
                        self.file_tree.insert("", tk.END, text=source_path, values=(source_path,))
                        scanned_file_paths.add(source_path)
        
        if not scanned_file_paths:
            self.log_message("No image files found in the specified sources.")
            messagebox.showinfo("Scan Complete", "No image files found matching supported formats.")
        else:
            self.log_message(f"Scan complete. Found {len(scanned_file_paths)} image file(s). Select files from the list to convert.")
        self.progress_label.config(text=f"{len(scanned_file_paths)} files listed. Select files and click convert.")


    def select_all_files_in_tree(self):
        for item in self.file_tree.get_children():
            self.file_tree.selection_add(item)

    def deselect_all_files_in_tree(self):
        for item in self.file_tree.get_children():
            self.file_tree.selection_remove(item)

    def clear_file_list_and_sources(self):
        if messagebox.askokcancel("Confirm Clear", "This will clear the list of found files and all added input sources. Continue?"):
            self.file_tree.delete(*self.file_tree.get_children())
            self.found_files_map.clear()
            self.input_sources.clear()
            self.custom_export_path_var.set("")
            self.log_message("File list and input sources cleared.", clear_current_log=True)
            self.progress_label.config(text="Waiting for task...")
            self.progress_bar["value"] = 0


    def browse_export_path(self):
        path = filedialog.askdirectory(title="Select Custom Export Folder")
        if path:
            self.custom_export_path_var.set(path)

    def log_message(self, message, clear_current_log=False):
        self.log_text.config(state=tk.NORMAL)
        if clear_current_log:
            self.log_text.delete(1.0, tk.END)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def start_conversion_thread(self):
        selected_item_ids = self.file_tree.selection()
        if not selected_item_ids:
            messagebox.showwarning("No Files Selected", "Please select at least one file from the list to convert.")
            return

        files_to_convert = [self.file_tree.item(item_id, "values")[0] for item_id in selected_item_ids]

        if not files_to_convert: # Should not happen if selected_item_ids is populated, but as a safeguard
            messagebox.showwarning("No Files", "No valid file paths selected for conversion.")
            return

        if self.processing_thread and self.processing_thread.is_alive():
            messagebox.showinfo("In Progress", "A conversion process is already running.")
            return

        self.log_message("--- Starting Conversion ---", clear_current_log=True)
        self._toggle_ui_elements_state(tk.DISABLED)

        self.progress_bar["value"] = 0
        self.progress_label.config(text="Preparing...")

        quality = self.quality_var.get()
        try:
            max_width = int(self.resize_var.get())
            if max_width < 0: max_width = 0
        except ValueError:
            messagebox.showerror("Invalid Input", "Max width must be a valid number.")
            self._toggle_ui_elements_state(tk.NORMAL)
            return

        custom_export_root = self.custom_export_path_var.get()
        if custom_export_root and not os.path.isdir(custom_export_root):
            if messagebox.askyesno("Create Folder?", f"The custom export path '{custom_export_root}' does not exist. Create it?"):
                try:
                    os.makedirs(custom_export_root)
                except Exception as e:
                    messagebox.showerror("Error", f"Could not create custom export path: {e}")
                    self._toggle_ui_elements_state(tk.NORMAL)
                    return
            else:
                self._toggle_ui_elements_state(tk.NORMAL)
                return


        self.processing_thread = threading.Thread(
            target=self.worker_process_files,
            args=(files_to_convert, quality, max_width, custom_export_root, self.progress_queue),
            daemon=True
        )
        self.processing_thread.start()
        self.root.after(100, self.check_queue)

    def _toggle_ui_elements_state(self, state):
        """Helper to enable/disable UI elements during processing."""
        self.add_folder_button.config(state=state)
        self.add_files_button.config(state=state)
        self.scan_sources_button.config(state=state)
        self.select_all_button.config(state=state)
        self.deselect_all_button.config(state=state)
        self.clear_list_button.config(state=state)
        self.browse_export_button.config(state=state)
        self.custom_export_entry.config(state=state)
        self.quality_scale.config(state=state)
        self.resize_entry.config(state=state)
        self.convert_button.config(state=state)
        # Treeview itself doesn't have a simple 'disabled' state for selection,
        # but other interactions are blocked.

    def worker_process_files(self, file_paths, jpg_quality, max_width, custom_export_root_path, progress_q):
        total_to_convert = len(file_paths)
        converted_count = 0
        error_count = 0

        for i, src_path in enumerate(file_paths):
            progress_q.put({
                "type": "progress",
                "current": i + 1,
                "total": total_to_convert,
                "message": f"Processing: {os.path.basename(src_path)}"
            })

            base_name = os.path.splitext(os.path.basename(src_path))[0]
            output_filename = f"{base_name}.jpg"

            if custom_export_root_path:
                # All files go into the flat custom export directory
                final_output_path = os.path.join(custom_export_root_path, output_filename)
            else:
                # Save in JPG subfolder of original image's directory
                original_dir = os.path.dirname(src_path)
                jpg_subfolder = os.path.join(original_dir, "JPG")
                final_output_path = os.path.join(jpg_subfolder, output_filename)

            success, message = convert_image(src_path, final_output_path, jpg_quality, max_width)
            if success:
                converted_count += 1
            else:
                error_count += 1
            progress_q.put({"type": "log", "message": message})

        progress_q.put({
            "type": "done",
            "converted": converted_count,
            "total_processed": total_to_convert, # Renamed from 'total' for clarity
            "errors": error_count
        })


    def check_queue(self):
        try:
            while True:
                message_data = self.progress_queue.get_nowait()
                msg_type = message_data["type"]

                if msg_type == "progress":
                    self.progress_bar["maximum"] = message_data["total"]
                    self.progress_bar["value"] = message_data["current"]
                    self.progress_label.config(text=f"Processing: {message_data['current']}/{message_data['total']} - {message_data['message']}")
                elif msg_type == "log":
                    self.log_message(message_data["message"])
                elif msg_type == "done":
                    self.progress_bar["value"] = self.progress_bar["maximum"] # Ensure it reaches 100%
                    summary_msg = (f"--- Conversion Complete! ---\n"
                                   f"Successfully converted: {message_data['converted']}\n"
                                   f"Attempted to process: {message_data['total_processed']}\n"
                                   f"Errors: {message_data['errors']}")
                    self.progress_label.config(text=f"Conversion complete. Converted: {message_data['converted']}/{message_data['total_processed']}")
                    self.log_message(summary_msg)
                    messagebox.showinfo("Complete", summary_msg.replace("\n", " | "))
                    self.reset_ui_after_processing()
                    return # Stop checking once "done" is received

        except queue.Empty:
            pass # No new messages

        if self.processing_thread and self.processing_thread.is_alive():
            self.root.after(100, self.check_queue) # Reschedule
        elif not (self.processing_thread and self.processing_thread.is_alive()) and self.convert_button['state'] == 'disabled':
             self.reset_ui_after_processing()
             if self.progress_label.cget("text").startswith("Processing"):
                 self.log_message("Processing might have been interrupted or finished unexpectedly.")
                 self.progress_label.config(text="Processing ended.")


    def reset_ui_after_processing(self):
        self._toggle_ui_elements_state(tk.NORMAL)
        # Final status message if not fully complete (though 'done' message should cover this)
        if self.progress_bar["value"] < self.progress_bar["maximum"] and not self.progress_label.cget("text").startswith("Conversion complete"):
            self.progress_label.config(text=f"Finished. Processed {self.progress_bar['value']}/{self.progress_bar['maximum']}.")


    def on_closing(self):
        if self.processing_thread and self.processing_thread.is_alive():
            if messagebox.askokcancel("Quit", "Conversion in progress. Are you sure you want to quit? This may leave files unprocessed."):
                self.root.destroy()
            else:
                return
        self.root.destroy()


# --- Main Execution ---
if __name__ == "__main__":
    root = tk.Tk()
    app = ImageConverterApp(root)
    root.mainloop()