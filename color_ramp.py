import tkinter as tk
from tkinter import colorchooser, messagebox, ttk
from colormath.color_objects import sRGBColor, LabColor
from colormath.color_conversions import convert_color

def hex_to_rgb(hex_color):
    """Convert hex color to RGB tuple."""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) != 6:
        raise ValueError(f"Input {hex_color} is not in #RRGGBB format")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def rgb_to_hex(rgb):
    """Convert RGB tuple to hex color."""
    return '#{:02x}{:02x}{:02x}'.format(*rgb)

def interpolate_lab(color1, color2, steps):
    """Interpolate between two colors in LAB space."""
    color1_lab = convert_color(sRGBColor(*color1, is_upscaled=True), LabColor)
    color2_lab = convert_color(sRGBColor(*color2, is_upscaled=True), LabColor)
    
    interpolated = []
    for i in range(steps):
        ratio = i / (steps - 1)
        L = color1_lab.lab_l + (color2_lab.lab_l - color1_lab.lab_l) * ratio
        a = color1_lab.lab_a + (color2_lab.lab_a - color1_lab.lab_a) * ratio
        b = color1_lab.lab_b + (color2_lab.lab_b - color1_lab.lab_b) * ratio
        interpolated_lab = LabColor(L, a, b)
        interpolated_rgb = convert_color(interpolated_lab, sRGBColor).get_upscaled_value_tuple()
        # Clamp values between 0 and 255
        interpolated_rgb = tuple(max(0, min(255, round(c))) for c in interpolated_rgb)
        interpolated.append(interpolated_rgb)
    return interpolated

def interpolate_rgb(color1, color2, steps):
    """Linearly interpolate between two RGB colors."""
    if steps < 2:
        raise ValueError("Number of steps must be at least 2")
    interpolated = []
    for i in range(steps):
        ratio = i / (steps - 1)
        interpolated_rgb = tuple(
            round(color1[j] + (color2[j] - color1[j]) * ratio) for j in range(3)
        )
        interpolated.append(interpolated_rgb)
    return interpolated

class ColorPaletteGenerator:
    def __init__(self, root):
        self.root = root
        self.root.title("Advanced Diverging Color Palette Generator")
        self.create_widgets()

    def create_widgets(self):
        padding = {'padx': 10, 'pady': 5}

        # Preset Options
        preset_frame = ttk.LabelFrame(self.root, text="Presets")
        preset_frame.grid(row=0, column=0, sticky='EW', **padding)

        ttk.Label(preset_frame, text="Select Preset:").grid(row=0, column=0, sticky='W', padx=(5,0))
        self.preset_var = tk.StringVar()
        presets = self.get_presets()
        preset_names = list(presets.keys())
        self.preset_combo = ttk.Combobox(preset_frame, values=preset_names, state="readonly", textvariable=self.preset_var, width=30)
        self.preset_combo.grid(row=0, column=1, sticky='W', padx=(5,0))
        self.preset_combo.bind("<<ComboboxSelected>>", self.apply_preset)
        self.preset_combo.set("Custom")

        # Color Selection
        color_frame = ttk.LabelFrame(self.root, text="Color Selection")
        color_frame.grid(row=1, column=0, sticky='EW', **padding)

        # Far Left Color
        ttk.Label(color_frame, text="Far Left Color:").grid(row=0, column=0, sticky='W')
        self.left_color_var = tk.StringVar(value="#FF0000")
        self.left_entry = ttk.Entry(color_frame, textvariable=self.left_color_var, width=10)
        self.left_entry.grid(row=0, column=1, sticky='W', padx=(5, 0))
        self.left_button = ttk.Button(color_frame, text="Choose", command=self.choose_left_color)
        self.left_button.grid(row=0, column=2, sticky='W', padx=(5,0))

        # Midpoint Color
        ttk.Label(color_frame, text="Midpoint Color:").grid(row=1, column=0, sticky='W')
        self.mid_color_var = tk.StringVar(value="#CCCCCC")
        self.mid_entry = ttk.Entry(color_frame, textvariable=self.mid_color_var, width=10)
        self.mid_entry.grid(row=1, column=1, sticky='W', padx=(5, 0))
        self.mid_button = ttk.Button(color_frame, text="Choose", command=self.choose_mid_color)
        self.mid_button.grid(row=1, column=2, sticky='W', padx=(5,0))

        # Far Right Color
        ttk.Label(color_frame, text="Far Right Color:").grid(row=2, column=0, sticky='W')
        self.right_color_var = tk.StringVar(value="#0000FF")
        self.right_entry = ttk.Entry(color_frame, textvariable=self.right_color_var, width=10)
        self.right_entry.grid(row=2, column=1, sticky='W', padx=(5, 0))
        self.right_button = ttk.Button(color_frame, text="Choose", command=self.choose_right_color)
        self.right_button.grid(row=2, column=2, sticky='W', padx=(5,0))

        # Number of Colors and Interpolation Method
        options_frame = ttk.Frame(self.root)
        options_frame.grid(row=2, column=0, sticky='EW', **padding)

        # Number of Colors
        ttk.Label(options_frame, text="Number of Colors:").grid(row=0, column=0, sticky='W')
        self.num_colors_var = tk.IntVar(value=7)
        self.num_spinbox = ttk.Spinbox(options_frame, from_=3, to=100, textvariable=self.num_colors_var, width=5)
        self.num_spinbox.grid(row=0, column=1, sticky='W', padx=(5,0))

        # Interpolation Method
        ttk.Label(options_frame, text="Interpolation Method:").grid(row=0, column=2, sticky='W', padx=(20,0))
        self.interp_var = tk.StringVar(value="LAB")
        interp_methods = ["LAB", "RGB"]
        self.interp_combo = ttk.Combobox(options_frame, values=interp_methods, state="readonly", textvariable=self.interp_var, width=10)
        self.interp_combo.current(0)
        self.interp_combo.grid(row=0, column=3, sticky='W', padx=(5,0))

        # Generate Button
        generate_frame = ttk.Frame(self.root)
        generate_frame.grid(row=3, column=0, sticky='EW', **padding)
        self.generate_button = ttk.Button(generate_frame, text="Generate Palette", command=self.generate_palette)
        self.generate_button.pack()

        # Separator
        separator = ttk.Separator(self.root, orient='horizontal')
        separator.grid(row=4, column=0, sticky='EW', **padding)

        # Palette Display
        display_frame = ttk.LabelFrame(self.root, text="Generated Palette")
        display_frame.grid(row=5, column=0, sticky='EW', **padding)

        self.palette_canvas = tk.Canvas(display_frame, height=100)
        self.palette_canvas.pack(fill='x')

        # Hex Codes
        codes_frame = ttk.Frame(self.root)
        codes_frame.grid(row=6, column=0, sticky='EW', **padding)

        ttk.Label(codes_frame, text="Hex Codes:").grid(row=0, column=0, sticky='W')
        self.codes_text = tk.Text(codes_frame, height=2, width=50)
        self.codes_text.grid(row=1, column=0, columnspan=3, sticky='W', pady=(5,0))

        self.copy_button = ttk.Button(codes_frame, text="Copy to Clipboard", command=self.copy_to_clipboard)
        self.copy_button.grid(row=1, column=3, sticky='W', padx=(5,0))

    def get_presets(self):
        """Define a dictionary of 30 presets with left, mid, and right colors."""
        presets = {
            "Custom": {"left": "#FF0000", "mid": "#CCCCCC", "right": "#0000FF"},
            # Classic Diverging
            "Red-Grey-Blue": {"left": "#FF0000", "mid": "#CCCCCC", "right": "#0000FF"},
            "Purple-Grey-Green": {"left": "#800080", "mid": "#CCCCCC", "right": "#008000"},
            "Orange-Grey-Teal": {"left": "#FFA500", "mid": "#CCCCCC", "right": "#008080"},
            "Brown-Grey-Purple": {"left": "#A52A2A", "mid": "#CCCCCC", "right": "#800080"},
            "Pink-Grey-Blue": {"left": "#FFC0CB", "mid": "#CCCCCC", "right": "#0000FF"},
            # Modern Diverging
            "Coral-Gray-Cobalt": {"left": "#FF7F50", "mid": "#BEBEBE", "right": "#0047AB"},
            "Crimson-Silver-Sky": {"left": "#DC143C", "mid": "#C0C0C0", "right": "#87CEEB"},
            "Magenta-Gray-Cyan": {"left": "#FF00FF", "mid": "#808080", "right": "#00FFFF"},
            "Amber-Gray-Navy": {"left": "#FFBF00", "mid": "#A9A9A9", "right": "#000080"},
            "Turquoise-Gray-Lavender": {"left": "#40E0D0", "mid": "#D3D3D3", "right": "#E6E6FA"},
            # ColorBrewer Schemes
            "BrBG": {"left": "#D8B365", "mid": "#F5F5F5", "right": "#5AB4AC"},
            "RdBu": {"left": "#D73027", "mid": "#FFFFFF", "right": "#4575B4"},
            "PiYG": {"left": "#D01C8B", "mid": "#F7F7F7", "right": "#2C7BB6"},
            "PRGn": {"left": "#AD494A", "mid": "#F7F7F7", "right": "#74ADD1"},
            "RdYlBu": {"left": "#D73027", "mid": "#FFFFBF", "right": "#4575B4"},
            "Spectral": {"left": "#D53E4F", "mid": "#FEE08B", "right": "#3288BD"},
            # Viridis and Others
            "Viridis": {"left": "#440154", "mid": "#FDE725", "right": "#21908C"},
            "Plasma": {"left": "#0D0887", "mid": "#F0F921", "right": "#CC4778"},
            "Magma": {"left": "#000004", "mid": "#F0F921", "right": "#F768A1"},
            "Inferno": {"left": "#000004", "mid": "#F0F921", "right": "#F7D130"},
            "Cividis": {"left": "#00204F", "mid": "#F2F1F1", "right": "#B2182B"},
            # Tableau Schemes
            "Tableau 10": {"left": "#1F77B4", "mid": "#AAAAAA", "right": "#FF7F0E"},
            "Tableau 20": {"left": "#9467BD", "mid": "#C5C5C5", "right": "#2CA02C"},
            "Tableau Color Blind": {"left": "#377EB8", "mid": "#CCCCCC", "right": "#4DAF4A"},
            # Wes Anderson Palettes
            "BottleRocket1": {"left": "#BE0032", "mid": "#F2A900", "right": "#8F7700"},
            "Rushmore1": {"left": "#4B4E6D", "mid": "#FC642D", "right": "#FFFF66"},
            "Zissou1": {"left": "#2E5894", "mid": "#CC7722", "right": "#228B22"},
            "Moonrise1": {"left": "#A23E48", "mid": "#FFD700", "right": "#008000"},
            "IsleofDogs1": {"left": "#034C3C", "mid": "#FC4C02", "right": "#F9E900"},
            # Tol Palettes
            "Tol YlOrBr": {"left": "#FFFFCC", "mid": "#FFEDA0", "right": "#D73027"},
            "Tol PuRd": {"left": "#F1EEF6", "mid": "#BDC9E1", "right": "#762A83"},
            "Tol RdBu": {"left": "#D7191C", "mid": "#FDE725", "right": "#2C7BB6"},
            "Tol Spectral": {"left": "#FC8D59", "mid": "#FFFFBF", "right": "#91BFDB"},
            "Tol PuBu": {"left": "#F7FCFD", "mid": "#BFD3E6", "right": "#08589E"},
            # Additional Popular Schemes
            "Earth": {"left": "#3B8686", "mid": "#FFFFFF", "right": "#FFB400"},
            "Geyser": {"left": "#636363", "mid": "#F0F0F0", "right": "#D4B9DA"},
            "Temps": {"left": "#762A83", "mid": "#FFFFBF", "right": "#1B7837"},
            "TealRose": {"left": "#A6CEE3", "mid": "#F7F7F7", "right": "#B2DF8A"},
            "Broc": {"left": "#543005", "mid": "#F7F7F7", "right": "#004529"},
            "Lisbon": {"left": "#7F3B08", "mid": "#F7F7F7", "right": "#0868AC"},
            "Sunset": {"left": "#FF7F00", "mid": "#FFFFFF", "right": "#6A51A3"},
            "Roma": {"left": "#88419D", "mid": "#FFFFFF", "right": "#01665E"},
            "Cork": {"left": "#E66101", "mid": "#FFFFFF", "right": "#5E3C99"},
            "Teal": {"left": "#008080", "mid": "#C0C0C0", "right": "#800000"},
        }
        return presets

    def apply_preset(self, event=None):
        preset = self.preset_var.get()
        presets = self.get_presets()
        if preset == "Custom":
            return
        if preset in presets:
            self.left_color_var.set(presets[preset]["left"])
            self.mid_color_var.set(presets[preset]["mid"])
            self.right_color_var.set(presets[preset]["right"])

    def choose_left_color(self):
        color_code = colorchooser.askcolor(title="Choose Far Left Color", initialcolor=self.left_color_var.get())
        if color_code[1]:
            self.left_color_var.set(color_code[1])

    def choose_mid_color(self):
        color_code = colorchooser.askcolor(title="Choose Midpoint Color", initialcolor=self.mid_color_var.get())
        if color_code[1]:
            self.mid_color_var.set(color_code[1])

    def choose_right_color(self):
        color_code = colorchooser.askcolor(title="Choose Far Right Color", initialcolor=self.right_color_var.get())
        if color_code[1]:
            self.right_color_var.set(color_code[1])

    def generate_palette(self):
        try:
            left_hex = self.left_color_var.get()
            mid_hex = self.mid_color_var.get()
            right_hex = self.right_color_var.get()
            n = self.num_colors_var.get()
            interp_method = self.interp_var.get()

            # Validate hex codes
            left_rgb = hex_to_rgb(left_hex)
            mid_rgb = hex_to_rgb(mid_hex)
            right_rgb = hex_to_rgb(right_hex)

            if interp_method == "LAB":
                # Interpolate left to mid and mid to right in LAB space
                half = (n + 1) // 2
                left_to_mid = interpolate_lab(left_rgb, mid_rgb, half)
                mid_to_right = interpolate_lab(mid_rgb, right_rgb, n - half + 1)[1:]
                palette_rgb = left_to_mid + mid_to_right
            else:
                # Interpolate in RGB space
                half = (n + 1) // 2
                left_to_mid = interpolate_rgb(left_rgb, mid_rgb, half)
                mid_to_right = interpolate_rgb(mid_rgb, right_rgb, n - half + 1)[1:]
                palette_rgb = left_to_mid + mid_to_right

            palette_hex = [rgb_to_hex(color) for color in palette_rgb]

            # Update palette display
            self.display_palette(palette_hex)

            # Update hex codes text
            self.codes_text.delete('1.0', tk.END)
            self.codes_text.insert(tk.END, ', '.join(palette_hex))

        except ValueError as ve:
            messagebox.showerror("Invalid Input", str(ve))
        except Exception as e:
            messagebox.showerror("Error", f"An unexpected error occurred: {e}")

    def display_palette(self, palette_hex):
        self.palette_canvas.delete("all")
        width = self.palette_canvas.winfo_width()
        height = 100
        if width < 100:  # Initial width before rendering
            width = 600
        step = width / len(palette_hex)
        for i, color in enumerate(palette_hex):
            x0 = i * step
            y0 = 0
            x1 = (i + 1) * step
            y1 = height
            self.palette_canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline='')
            # Optional: Display hex code on swatch
            # self.palette_canvas.create_text(x0 + step/2, y1/2, text=color, fill='white' if self.is_dark(color) else 'black')

    def copy_to_clipboard(self):
        hex_codes = self.codes_text.get("1.0", tk.END).strip()
        if hex_codes:
            self.root.clipboard_clear()
            self.root.clipboard_append(hex_codes)
            messagebox.showinfo("Copied", "Hex codes copied to clipboard!")

def main():
    root = tk.Tk()
    app = ColorPaletteGenerator(root)
    root.mainloop()

if __name__ == "__main__":
    main()
