import pandas as pd
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import threading
import decimal
import json
import os
import sys

class CSVPreprocessorApp:
    def __init__(self, master):
        self.master = master
        master.title("CSV Preprocessor for GeoJSON Merge")
        master.geometry("1200x800")
        
        # Initialize variables
        self.input_csv_path = tk.StringVar()
        self.output_csv_path = tk.StringVar()
        self.sample_rows = tk.IntVar(value=5)  # Default 5 rows
        
        # Initialize field selection variables
        self.fields = []
        self.field_vars = {}
        self.total_rows = 0
        self.field_byte_sizes = {}  # To store average byte size per field
        
        # Create GUI elements
        self.create_widgets()
    
    def create_widgets(self):
        padding_options = {'padx': 10, 'pady': 5}
        
        # Input CSV
        tk.Label(self.master, text="Input CSV File (.csv):").grid(row=0, column=0, sticky='e', **padding_options)
        tk.Entry(self.master, textvariable=self.input_csv_path, width=70).grid(row=0, column=1, **padding_options)
        tk.Button(self.master, text="Browse", command=self.browse_input_csv).grid(row=0, column=2, **padding_options)
        
        # Output CSV
        tk.Label(self.master, text="Output CSV File (.csv):").grid(row=1, column=0, sticky='e', **padding_options)
        tk.Entry(self.master, textvariable=self.output_csv_path, width=70).grid(row=1, column=1, **padding_options)
        tk.Button(self.master, text="Browse", command=self.browse_output_csv).grid(row=1, column=2, **padding_options)
        
        # Number of Sample Rows
        tk.Label(self.master, text="Number of Sample Rows to Preview:").grid(row=2, column=0, sticky='e', **padding_options)
        tk.Spinbox(self.master, from_=1, to=10000, textvariable=self.sample_rows, width=10, command=self.update_preview).grid(row=2, column=1, sticky='w', **padding_options)
        
        # Load CSV Button
        self.load_csv_button = tk.Button(self.master, text="Load CSV and Preview", command=self.load_csv)
        self.load_csv_button.grid(row=3, column=1, sticky='w', **padding_options)
        
        # Frame for Field Checkboxes
        self.fields_frame = ttk.LabelFrame(self.master, text="Select Fields to Keep/Exclude")
        self.fields_frame.grid(row=4, column=0, columnspan=3, sticky='nsew', padx=10, pady=10)
        
        # Make the fields_frame expandable
        self.master.grid_rowconfigure(4, weight=1)
        self.master.grid_columnconfigure(1, weight=1)
        
        # Canvas and Scrollbar for Fields
        self.canvas = tk.Canvas(self.fields_frame)
        self.scrollbar = ttk.Scrollbar(self.fields_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")
            )
        )
        
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor='nw')
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        
        # Sample Data Preview
        self.preview_frame = ttk.LabelFrame(self.master, text="Data Preview")
        self.preview_frame.grid(row=5, column=0, columnspan=3, sticky='nsew', padx=10, pady=10)
        
        # Make the preview_frame expandable
        self.master.grid_rowconfigure(5, weight=2)
        
        self.preview_text = tk.Text(self.preview_frame, height=20, wrap='none')
        self.preview_text.pack(side="left", fill="both", expand=True)
        
        self.preview_scrollbar_y = ttk.Scrollbar(self.preview_frame, orient="vertical", command=self.preview_text.yview)
        self.preview_scrollbar_y.pack(side="right", fill="y")
        self.preview_text.configure(yscrollcommand=self.preview_scrollbar_y.set)
        
        self.preview_scrollbar_x = ttk.Scrollbar(self.master, orient="horizontal", command=self.preview_text.xview)
        self.preview_scrollbar_x.grid(row=6, column=0, columnspan=3, sticky='we', padx=10, pady=(0,10))
        self.preview_text.configure(xscrollcommand=self.preview_scrollbar_x.set)
        
        # Estimated File Size
        self.estimate_label = tk.Label(self.master, text="Estimated Final CSV Size: Calculating...")
        self.estimate_label.grid(row=7, column=0, columnspan=3, **padding_options)
        
        # Start Preprocessing Button
        self.start_button = tk.Button(self.master, text="Start Preprocessing", command=self.start_preprocessing)
        self.start_button.grid(row=8, column=1, **padding_options)
        
        # Progress Bar
        self.progress = ttk.Progressbar(self.master, orient='horizontal', length=1000, mode='determinate')
        self.progress.grid(row=9, column=0, columnspan=3, **padding_options)
        
        # Status Label
        self.status_label = tk.Label(self.master, text="Status: Ready")
        self.status_label.grid(row=10, column=0, columnspan=3, **padding_options)
    
    def browse_input_csv(self):
        filepath = filedialog.askopenfilename(
            title="Select Input CSV File",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if filepath:
            self.input_csv_path.set(filepath)
    
    def browse_output_csv(self):
        filepath = filedialog.asksaveasfilename(
            title="Select Output CSV File",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if filepath:
            self.output_csv_path.set(filepath)
    
    def load_csv(self):
        if not self.input_csv_path.get():
            messagebox.showerror("Input Error", "Please select an input CSV file.")
            return
        if not self.output_csv_path.get():
            messagebox.showerror("Input Error", "Please select an output CSV file.")
            return
        
        # Disable the Load CSV button to prevent multiple clicks
        self.load_csv_button.config(state='disabled')
        self.update_status("Loading CSV and extracting fields...")
        self.progress['value'] = 0
        
        # Start loading CSV in a separate thread
        threading.Thread(target=self.extract_fields_and_preview, daemon=True).start()
    
    def extract_fields_and_preview(self):
        try:
            input_path = self.input_csv_path.get()
            
            # First, determine the total number of rows
            self.update_status("Counting total number of rows in CSV...")
            with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
                self.total_rows = sum(1 for _ in f) - 1  # Subtract header
            self.update_status(f"Total Rows: {self.total_rows}")
            
            # Read a sample of the CSV to extract fields
            self.update_status("Reading sample rows from CSV...")
            sample_df = pd.read_csv(input_path, nrows=self.sample_rows.get(), dtype=str)
            self.fields = list(sample_df.columns)
            
            # Update the GUI with checkboxes
            self.display_field_checkboxes()
            
            # Display sample data
            self.display_sample_data(sample_df)
            
            # Estimate final file size
            self.estimate_file_size(selected_fields=self.fields)
            
            self.update_status(f"CSV loaded with {len(self.fields)} fields and {self.sample_rows.get()} sample rows.")
        
        except Exception as e:
            self.update_status(f"Error: {str(e)}")
            messagebox.showerror("Error", f"An error occurred while loading the CSV:\n{str(e)}")
        finally:
            # Re-enable the Load CSV button
            self.load_csv_button.config(state='normal')
            self.progress['value'] = 100
    
    def display_field_checkboxes(self):
        # Clear any existing checkboxes
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        
        # Create checkboxes for each field
        self.field_vars = {}
        for field in self.fields:
            var = tk.BooleanVar(value=True)
            chk = tk.Checkbutton(self.scrollable_frame, text=field, variable=var, command=self.update_preview)
            chk.pack(anchor='w')
            self.field_vars[field] = var
    
    def display_sample_data(self, df):
        # Clear the preview text
        self.preview_text.config(state='normal')
        self.preview_text.delete('1.0', tk.END)
        
        # Display the DataFrame as a table
        self.preview_text.insert(tk.END, df.to_string(index=False))
        self.preview_text.config(state='disabled')
    
    def update_preview(self):
        if not self.input_csv_path.get():
            return
        if not self.fields:
            return
        
        try:
            # Get selected fields
            selected_fields = [field for field, var in self.field_vars.items() if var.get()]
            if not selected_fields:
                self.preview_text.config(state='normal')
                self.preview_text.delete('1.0', tk.END)
                self.preview_text.insert(tk.END, "No fields selected.")
                self.preview_text.config(state='disabled')
                self.estimate_label.config(text="Estimated Final CSV Size: N/A")
                return
            
            # Read the specified number of sample rows with selected fields
            sample_df = pd.read_csv(self.input_csv_path.get(), nrows=self.sample_rows.get(), usecols=selected_fields, dtype=str)
            
            # Display the sample data
            self.display_sample_data(sample_df)
            
            # Re-estimate file size
            self.estimate_file_size(selected_fields)
        
        except Exception as e:
            self.update_status(f"Error during preview update: {str(e)}")
            messagebox.showerror("Error", f"An error occurred while updating the preview:\n{str(e)}")
    
    def estimate_file_size(self, selected_fields):
        """
        Estimate the final CSV file size based on selected fields.
        """
        try:
            input_path = self.input_csv_path.get()
            output_path = self.output_csv_path.get()
            
            if not os.path.exists(input_path):
                self.estimate_label.config(text="Estimated Final CSV Size: N/A")
                return
            
            # Estimate based on average bytes per field from sample rows
            sample_size = self.sample_rows.get()
            if sample_size == 0:
                sample_size = 1  # Avoid division by zero
            
            # Read a larger sample for better estimation (e.g., 1000 rows)
            large_sample_size = min(1000, self.total_rows)
            if large_sample_size <= 0:
                large_sample_size = 1
            sample_df = pd.read_csv(input_path, nrows=large_sample_size, usecols=selected_fields, dtype=str)
            
            # Calculate average bytes per field
            self.field_byte_sizes = {}
            for field in selected_fields:
                # Calculate average byte size for the field
                bytes_sizes = sample_df[field].dropna().apply(lambda x: len(str(x).encode('utf-8')))
                average_size = bytes_sizes.mean() if not bytes_sizes.empty else 0
                self.field_byte_sizes[field] = average_size
            
            # Sum the average bytes for selected fields per row
            average_bytes_per_row = sum(self.field_byte_sizes.values()) + (len(selected_fields) - 1) * 1 + 2  # commas and newline
            
            # Estimate total size
            estimated_size_bytes = average_bytes_per_row * self.total_rows
            estimated_size_mb = estimated_size_bytes / (1024 ** 2)
            
            # Update the estimate label
            self.estimate_label.config(text=f"Estimated Final CSV Size: {estimated_size_mb:.2f} MB")
        
        except Exception as e:
            self.estimate_label.config(text="Estimated Final CSV Size: N/A")
            self.update_status(f"Error during size estimation: {str(e)}")
            messagebox.showerror("Error", f"An error occurred while estimating file size:\n{str(e)}")
    
    def start_preprocessing(self):
        if not self.input_csv_path.get() or not self.output_csv_path.get():
            messagebox.showerror("Input Error", "Please select both input and output CSV files.")
            return
        if not any(var.get() for var in self.field_vars.values()):
            messagebox.showerror("Selection Error", "Please select at least one field to keep.")
            return
        
        # Disable the Start button to prevent multiple clicks
        self.start_button.config(state='disabled')
        self.update_status("Starting preprocessing...")
        self.progress['value'] = 0
        
        # Gather selected fields
        selected_fields = [field for field, var in self.field_vars.items() if var.get()]
        
        # Start preprocessing in a separate thread
        threading.Thread(target=self.preprocess_csv, args=(selected_fields,), daemon=True).start()
    
    def preprocess_csv(self, selected_fields):
        try:
            input_path = self.input_csv_path.get()
            output_path = self.output_csv_path.get()
            
            # Read the entire CSV with selected fields
            self.update_status("Reading the entire CSV with selected fields...")
            # To handle large CSVs, read in chunks
            chunk_size = 100000  # Adjust based on memory constraints
            reader = pd.read_csv(input_path, usecols=selected_fields, dtype=str, chunksize=chunk_size)
            
            # Prepare to write to the output CSV
            with open(output_path, 'w', encoding='utf-8', newline='') as f_out:
                for i, chunk in enumerate(reader):
                    self.update_status(f"Processing chunk {i+1}...")
                    
                    # Convert data types
                    chunk = chunk.applymap(self.convert_types)
                    
                    # Write header only once
                    if i == 0:
                        chunk.to_csv(f_out, index=False, header=True)
                    else:
                        chunk.to_csv(f_out, index=False, header=False)
                    
                    # Update progress (assuming uniform chunks)
                    self.progress['value'] = min((i+1) / (self.total_rows / chunk_size) * 100, 100)
                    self.master.update_idletasks()
            
            self.update_status(f"Cleaned CSV saved to {output_path}.")
            messagebox.showinfo("Success", f"CSV Preprocessing completed.\nOutput saved to:\n{output_path}")
        
        except Exception as e:
            self.update_status(f"Error: {str(e)}")
            messagebox.showerror("Error", f"An error occurred during preprocessing:\n{str(e)}")
        finally:
            # Re-enable the Start button
            self.start_button.config(state='normal')
            self.progress['value'] = 100
    
    def convert_types(self, value):
        """
        Convert the value to a JSON-compatible data type.
        Attempts to convert numeric strings to numbers.
        """
        if pd.isnull(value):
            return None
        # Attempt to convert to integer
        try:
            int_val = int(value)
            return int_val
        except ValueError:
            pass
        # Attempt to convert to float
        try:
            float_val = float(value)
            return float_val
        except ValueError:
            pass
        # Return as string
        return value.strip()
    
    def update_progress(self, value):
        self.progress['value'] = value
        self.master.update_idletasks()
    
    def update_status(self, message):
        self.status_label.config(text=f"Status: {message}")
        self.master.update_idletasks()

def main():
    root = tk.Tk()
    app = CSVPreprocessorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
