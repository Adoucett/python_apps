import geopandas as gpd
import pandas as pd
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
from tkinter import ttk
import threading
import sys

def select_file(title, filetypes):
    """Open a file dialog and return the selected file path."""
    return filedialog.askopenfilename(title=title, filetypes=filetypes)

def save_file(title, defaultextension, filetypes):
    """Open a save file dialog and return the selected file path."""
    return filedialog.asksaveasfilename(title=title, defaultextension=defaultextension, filetypes=filetypes)

def merge_files(geojson_path, csv_path, geo_join_field, csv_join_field, output_path, progress_var, progress_bar, root, buttons, force_numeric, preserve_zip):
    try:
        progress_var.set(0)
        progress_bar.update()

        # Load GeoJSON
        progress_var.set(10)
        progress_bar.update()
        gdf = gpd.read_file(geojson_path)

        # Load CSV
        progress_var.set(20)
        progress_bar.update()
        df = pd.read_csv(csv_path)

        # Ensure join fields are strings and pad with leading zeros to maintain 6-digit ZIP codes
        progress_var.set(30)
        progress_bar.update()
        gdf[geo_join_field] = gdf[geo_join_field].astype(str).str.zfill(6)
        df[csv_join_field] = df[csv_join_field].astype(str).str.zfill(6)

        # Perform the merge
        progress_var.set(50)
        progress_bar.update()
        merged_gdf = gdf.merge(df, left_on=geo_join_field, right_on=csv_join_field, how='left')

        # Drop the CSV join field if redundant
        if csv_join_field in merged_gdf.columns:
            merged_gdf = merged_gdf.drop(columns=[csv_join_field])

        # If force_numeric is True, convert all fields to numeric except join fields and geometry
        if force_numeric:
            progress_var.set(60)
            progress_bar.update()
            # Define fields to exclude from numeric conversion
            exclude_fields = [geo_join_field, merged_gdf.geometry.name]
            for column in merged_gdf.columns:
                if column not in exclude_fields:
                    # Replace "-" and other non-numeric values with '0', then convert to numeric
                    merged_gdf[column] = pd.to_numeric(
                        merged_gdf[column].replace('-', '0').fillna('0'),
                        errors='coerce'
                    ).fillna(0)
        
        # Save the merged GeoJSON
        progress_var.set(80)
        progress_bar.update()
        merged_gdf.to_file(output_path, driver='GeoJSON')

        progress_var.set(100)
        progress_bar.update()
        messagebox.showinfo("Success", f"Merged GeoJSON saved to:\n{output_path}")

    except Exception as e:
        messagebox.showerror("Error", f"An error occurred:\n{e}")
        progress_var.set(0)
        progress_bar.update()
    finally:
        # Re-enable buttons after merge completes or fails
        for btn in buttons:
            btn.config(state="normal")

def start_merge(geojson_path, csv_path, output_path, progress_var, progress_bar, root, buttons, force_numeric, preserve_zip):
    # Prompt user for join fields
    try:
        gdf = gpd.read_file(geojson_path)
        df = pd.read_csv(csv_path)
    except Exception as e:
        messagebox.showerror("Error", f"Failed to read files:\n{e}")
        return

    # Get GeoJSON columns
    geo_columns = gdf.columns.tolist()
    # Get CSV columns
    csv_columns = df.columns.tolist()

    # Prompt for join fields
    geo_join_field = simpledialog.askstring("Join Field", f"Enter the join field from GeoJSON:\nAvailable fields: {', '.join(geo_columns)}", parent=root)
    if not geo_join_field or geo_join_field not in geo_columns:
        messagebox.showerror("Invalid Input", f"Join field '{geo_join_field}' not found in GeoJSON columns.")
        return

    csv_join_field = simpledialog.askstring("Join Field", f"Enter the join field from CSV:\nAvailable fields: {', '.join(csv_columns)}", parent=root)
    if not csv_join_field or csv_join_field not in csv_columns:
        messagebox.showerror("Invalid Input", f"Join field '{csv_join_field}' not found in CSV columns.")
        return

    # Disable buttons to prevent changes during merge
    for btn in buttons:
        btn.config(state="disabled")

    # Start the merge in a separate thread to keep the GUI responsive
    threading.Thread(target=merge_files, args=(
        geojson_path, csv_path, geo_join_field, csv_join_field, output_path,
        progress_var, progress_bar, root, buttons, force_numeric, preserve_zip
    ), daemon=True).start()

def main():
    # Initialize Tkinter
    root = tk.Tk()
    root.title("GeoJSON and CSV Merger")
    root.geometry("600x500")  # Increased height to accommodate checkbox
    root.resizable(False, False)

    # Style Configuration
    style = ttk.Style(root)
    style.theme_use('clam')

    # Instructions Label
    instructions = tk.Label(
        root,
        text="Select GeoJSON and CSV files to merge.\nEnsure you have the correct join fields.",
        wraplength=580,
        justify="left"
    )
    instructions.pack(pady=10)

    # Frame for Buttons and Labels
    button_frame = tk.Frame(root)
    button_frame.pack(pady=5, padx=10, fill="x")

    # Select GeoJSON Button
    def select_geojson():
        file_path = select_file(
            "Select GeoJSON File",
            [("GeoJSON files", "*.geojson"), ("JSON files", "*.json"), ("All files", "*.*")]
        )
        if file_path:
            geojson_path.set(file_path)
            geojson_label.config(text=file_path)

    geojson_path = tk.StringVar()
    select_geojson_btn = tk.Button(
        button_frame,
        text="Select GeoJSON",
        command=select_geojson,
        width=20
    )
    select_geojson_btn.grid(row=0, column=0, padx=5, pady=5, sticky="e")

    geojson_label = tk.Label(
        button_frame,
        text="No file selected",
        wraplength=350,
        anchor="w",
        justify="left"
    )
    geojson_label.grid(row=0, column=1, padx=5, pady=5, sticky="w")

    # Select CSV Button
    def select_csv():
        file_path = select_file(
            "Select CSV File",
            [("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if file_path:
            csv_path.set(file_path)
            csv_label.config(text=file_path)

    csv_path = tk.StringVar()
    select_csv_btn = tk.Button(
        button_frame,
        text="Select CSV",
        command=select_csv,
        width=20
    )
    select_csv_btn.grid(row=1, column=0, padx=5, pady=5, sticky="e")

    csv_label = tk.Label(
        button_frame,
        text="No file selected",
        wraplength=350,
        anchor="w",
        justify="left"
    )
    csv_label.grid(row=1, column=1, padx=5, pady=5, sticky="w")

    # Select Output Button
    def select_output():
        file_path = save_file(
            "Save Merged GeoJSON As",
            ".geojson",
            [("GeoJSON files", "*.geojson"), ("JSON files", "*.json"), ("All files", "*.*")]
        )
        if file_path:
            output_path.set(file_path)
            output_label.config(text=file_path)

    output_path = tk.StringVar()
    select_output_btn = tk.Button(
        button_frame,
        text="Select Output",
        command=select_output,
        width=20
    )
    select_output_btn.grid(row=2, column=0, padx=5, pady=5, sticky="e")

    output_label = tk.Label(
        button_frame,
        text="No output selected",
        wraplength=350,
        anchor="w",
        justify="left"
    )
    output_label.grid(row=2, column=1, padx=5, pady=5, sticky="w")

    # Checkbox for Forcing Numeric Output
    force_numeric_var = tk.BooleanVar()
    force_numeric_checkbox = tk.Checkbutton(
        root,
        text="Force All Fields to Numeric (Replace non-numeric with 0)",
        variable=force_numeric_var
    )
    force_numeric_checkbox.pack(pady=10)

    # Checkbox for Preserving ZIP Code Fields
    preserve_zip_var = tk.BooleanVar()
    preserve_zip_checkbox = tk.Checkbutton(
        root,
        text="Preserve Join Fields as ZIP Codes (Maintain Leading Zeros)",
        variable=preserve_zip_var
    )
    preserve_zip_checkbox.pack(pady=5)

    # Progress Bar
    progress_var = tk.DoubleVar()
    progress_bar = ttk.Progressbar(
        root,
        variable=progress_var,
        maximum=100,
        length=580,
        mode='determinate'
    )
    progress_bar.pack(pady=10)

    # Merge Button
    def initiate_merge():
        if not geojson_path.get():
            messagebox.showerror("Missing File", "Please select a GeoJSON file.")
            return
        if not csv_path.get():
            messagebox.showerror("Missing File", "Please select a CSV file.")
            return
        if not output_path.get():
            messagebox.showerror("Missing File", "Please select an output file location.")
            return

        # Start the merge process with the state of the checkboxes
        force_numeric = force_numeric_var.get()
        preserve_zip = preserve_zip_var.get()
        start_merge(
            geojson_path.get(),
            csv_path.get(),
            output_path.get(),
            progress_var,
            progress_bar,
            root,
            buttons,
            force_numeric,
            preserve_zip
        )

    buttons = []  # To keep track of buttons to disable/enable
    merge_btn = tk.Button(
        root,
        text="Merge Files",
        command=initiate_merge,
        width=20,
        bg="green",
        fg="white"
    )
    merge_btn.pack(pady=5)
    buttons.extend([select_geojson_btn, select_csv_btn, select_output_btn, merge_btn])

    # Run the Tkinter event loop
    root.mainloop()

if __name__ == "__main__":
    main()
