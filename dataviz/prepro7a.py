#!/usr/bin/env python3
import os
import subprocess
from pathlib import Path
import sys
import json
from pprint import pformat
import numpy as np
import re

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QListWidgetItem, QLabel, QFileDialog, QLineEdit, QCheckBox,
    QProgressBar, QTextEdit, QDialog
)
from PyQt5.QtGui import QBrush, QColor, QDoubleValidator
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWebEngineWidgets import QWebEngineView

# Optional: import rasterio for robust CRS handling
try:
    import rasterio
    from rasterio.warp import transform_bounds
except ImportError:
    rasterio = None

# Ensure GDAL support
try:
    from osgeo import gdal
except ImportError:
    sys.exit("GDAL Python bindings are required. Install with 'pip install gdal' or 'conda install gdal'.")


# --- Planet's Official NDVI Color Ramp in Hex Format ---
PLANET_HEX_RAMP = [[0,"0xfffdea"],[0.00390625,"0xfefce7"],[0.0078125,"0xfefbe5"],[0.01171875,"0xfdfae3"],[0.015625,"0xfcf9e0"],[0.01953125,"0xfbf8de"],[0.0234375,"0xfaf7dc"],[0.02734375,"0xfaf6d9"],[0.03125,"0xf9f5d7"],[0.03515625,"0xf8f4d5"],[0.0390625,"0xf7f3d2"],[0.04296875,"0xf6f2d0"],[0.046875,"0xf6f1ce"],[0.05078125,"0xf5f0cb"],[0.0546875,"0xf4efc9"],[0.05859375,"0xf3eec7"],[0.0625,"0xf3edc4"],[0.06640625,"0xf2ecc2"],[0.0703125,"0xf1ebbf"],[0.07421875,"0xf0eabd"],[0.078125,"0xf0e9ba"],[0.08203125,"0xefe8b8"],[0.0859375,"0xeee7b6"],[0.08984375,"0xeee6b3"],[0.09375,"0xede4b1"],[0.09765625,"0xece3ae"],[0.1015625,"0xebe2ac"],[0.10546875,"0xebe1a9"],[0.109375,"0xeae0a7"],[0.11328125,"0xe9dfa4"],[0.1171875,"0xe9dea2"],[0.12109375,"0xe8dd9f"],[0.125,"0xe7dc9c"],[0.12890625,"0xe6db9a"],[0.1328125,"0xe6da97"],[0.13671875,"0xe5d995"],[0.140625,"0xe4d892"],[0.14453125,"0xe4d78f"],[0.1484375,"0xe3d68d"],[0.15234375,"0xe2d58a"],[0.15625,"0xe2d487"],[0.16015625,"0xe1d384"],[0.1640625,"0xe0d281"],[0.16796875,"0xe0d17f"],[0.171875,"0xdfd07d"],[0.17578125,"0xdecf7a"],[0.1796875,"0xdece77"],[0.18359375,"0xddcd74"],[0.1875,"0xdccc71"],[0.19140625,"0xdccb6e"],[0.1953125,"0xdbca6a"],[0.19921875,"0xdac967"],[0.203125,"0xdac864"],[0.20703125,"0xd9c660"],[0.2109375,"0xd8c55d"],[0.21484375,"0xd8c459"],[0.21875,"0xd8c458"],[0.22265625,"0xd6c456"],[0.2265625,"0xd5c354"],[0.23046875,"0xd3c252"],[0.234375,"0xd2c250"],[0.23828125,"0xd0c14e"],[0.2421875,"0xcec04c"],[0.24609375,"0xcdc04a"],[0.25,"0xccbf48"],[0.25390625,"0xcabe46"],[0.2578125,"0xc9be44"],[0.26171875,"0xc7bd41"],[0.265625,"0xc5bc3f"],[0.26953125,"0xc4bb3d"],[0.2734375,"0xc2bb3a"],[0.27734375,"0xc0ba38"],[0.28125,"0xbfb935"],[0.28515625,"0xbdb932"],[0.2890625,"0xbbb82f"],[0.29296875,"0xbab72d"],[0.296875,"0xb8b729"],[0.30078125,"0xb6b626"],[0.3046875,"0xb5b523"],[0.30859375,"0xb3b51f"],[0.3125,"0xb1b41b"],[0.31640625,"0xb0b317"],[0.3203125,"0xaeb311"],[0.32421875,"0xacb20a"],[0.328125,"0xaab103"],[0.33203125,"0xa9b100"],[0.3359375,"0xa7b000"],[0.33984375,"0xa5af00"],[0.34375,"0xa3af00"],[0.34765625,"0xa2ae00"],[0.3515625,"0xa0ad00"],[0.35546875,"0x9ead00"],[0.359375,"0x9cac00"],[0.36328125,"0x9bac00"],[0.3671875,"0x99ab00"],[0.37109375,"0x97aa00"],[0.375,"0x95a900"],[0.37890625,"0x93a900"],[0.3828125,"0x92a800"],[0.38671875,"0x90a700"],[0.390625,"0x8ea700"],[0.39453125,"0x8ca600"],[0.3984375,"0x8aa500"],[0.40234375,"0x89a400"],[0.40625,"0x87a400"],[0.41015625,"0x85a300"],[0.4140625,"0x83a200"],[0.41796875,"0x82a200"],[0.421875,"0x80a100"],[0.42578125,"0x7ea000"],[0.4296875,"0x7c9f00"],[0.43359375,"0x7a9f00"],[0.4375,"0x799e00"],[0.44140625,"0x779d00"],[0.4453125,"0x759c00"],[0.44921875,"0x739c00"],[0.453125,"0x729b00"],[0.45703125,"0x709a00"],[0.4609375,"0x6e9900"],[0.46484375,"0x6c9900"],[0.46875,"0x6a9800"],[0.47265625,"0x699700"],[0.4765625,"0x679600"],[0.48046875,"0x659600"],[0.484375,"0x639500"],[0.48828125,"0x619400"],[0.4921875,"0x609300"],[0.49609375,"0x5e9300"],[0.5,"0x5c9300"],[0.50390625,"0x5a9200"],[0.5078125,"0x589100"],[0.51171875,"0x579000"],[0.515625,"0x558f00"],[0.51953125,"0x538f01"],[0.5234375,"0x518e03"],[0.52734375,"0x4f8d05"],[0.53125,"0x4d8c07"],[0.53515625,"0x4b8c09"],[0.5390625,"0x498b0b"],[0.54296875,"0x478a0d"],[0.546875,"0x45890f"],[0.55078125,"0x438810"],[0.5546875,"0x418812"],[0.55859375,"0x3f8713"],[0.5625,"0x3d8614"],[0.56640625,"0x3b8516"],[0.5703125,"0x398517"],[0.57421875,"0x378418"],[0.578125,"0x358319"],[0.58203125,"0x33821a"],[0.5859375,"0x31811b"],[0.58984375,"0x2e811c"],[0.59375,"0x2c801d"],[0.59765625,"0x2a7f1d"],[0.6015625,"0x277e1e"],[0.60546875,"0x257d1f"],[0.609375,"0x227d20"],[0.61328125,"0x1f7c20"],[0.6171875,"0x1c7b21"],[0.62109375,"0x197a22"],[0.625,"0x157922"],[0.62890625,"0x117923"],[0.6328125,"0x0c7824"],[0.63671875,"0x067724"],[0.640625,"0x027625"],[0.64453125,"0x007525"],[0.6484375,"0x007526"],[0.65234375,"0x007426"],[0.65625,"0x007327"],[0.66015625,"0x007227"],[0.6640625,"0x007128"],[0.66796875,"0x007028"],[0.671875,"0x007029"],[0.67578125,"0x006f29"],[0.6796875,"0x006e29"],[0.68359375,"0x006d2a"],[0.6875,"0x006c2a"],[0.69140625,"0x006c2a"],[0.6953125,"0x006b2b"],[0.69921875,"0x006a2b"],[0.703125,"0x00692b"],[0.70703125,"0x00682c"],[0.7109375,"0x00672c"],[0.71484375,"0x00672c"],[0.71875,"0x00662c"],[0.72265625,"0x00652d"],[0.7265625,"0x00642d"],[0.73046875,"0x00632d"],[0.734375,"0x00622d"],[0.73828125,"0x00622d"],[0.7421875,"0x00612e"],[0.74609375,"0x00602e"],[0.75,"0x005f2e"],[0.75390625,"0x005e2e"],[0.7578125,"0x005d2e"],[0.76171875,"0x005d2e"],[0.765625,"0x005c2e"],[0.76953125,"0x005b2e"],[0.7734375,"0x005a2e"],[0.77734375,"0x00592f"],[0.78125,"0x00582f"],[0.78515625,"0x00582f"],[0.7890625,"0x00572f"],[0.79296875,"0x00562f"],[0.796875,"0x00552f"],[0.80078125,"0x00542f"],[0.8046875,"0x00532f"],[0.80859375,"0x00532f"],[0.8125,"0x00522f"],[0.81640625,"0x00512f"],[0.8203125,"0x00502f"],[0.82421875,"0x004f2f"],[0.828125,"0x004e2e"],[0.83203125,"0x004d2e"],[0.8359375,"0x004d2e"],[0.83984375,"0x004c2e"],[0.84375,"0x004b2e"],[0.84765625,"0x004a2e"],[0.8515625,"0x00492e"],[0.85546875,"0x00482e"],[0.859375,"0x00472e"],[0.86328125,"0x00472e"],[0.8671875,"0x00462d"],[0.87109375,"0x00452d"],[0.875,"0x00442d"],[0.87890625,"0x00432d"],[0.8828125,"0x00422d"],[0.88671875,"0x00412c"],[0.890625,"0x00412c"],[0.89453125,"0x00402c"],[0.8984375,"0x003f2c"],[0.90234375,"0x003e2c"],[0.90625,"0x003d2b"],[0.91015625,"0x003c2b"],[0.9140625,"0x003b2b"],[0.91796875,"0x003a2b"],[0.921875,"0x003a2a"],[0.92578125,"0x00392a"],[0.9296875,"0x00382a"],[0.93359375,"0x003729"],[0.9375,"0x003629"],[0.94140625,"0x003529"],[0.9453125,"0x003428"],[0.94921875,"0x003328"],[0.953125,"0x003228"],[0.95703125,"0x003127"],[0.9609375,"0x003027"],[0.96484375,"0x002f26"],[0.96875,"0x002e26"],[0.97265625,"0x002d25"],[0.9765625,"0x002c25"],[0.98046875,"0x002b24"],[0.984375,"0x002a24"],[0.98828125,"0x002923"],[0.9921875,"0x002823"],[0.99609375,"0x002622"],[1,"0x072421"]]

# --- Helper Functions ---

def parse_hex_color_ramp(hex_ramp_data):
    """Parses the hex color ramp list into values and RGB color tuples."""
    color_points = []
    for val, hex_str in hex_ramp_data:
        try:
            hex_val = int(hex_str, 16)
            r = (hex_val >> 16) & 0xFF
            g = (hex_val >> 8) & 0xFF
            b = hex_val & 0xFF
            color_points.append((val, r, g, b))
        except (ValueError, IndexError):
            continue
    color_points.sort(key=lambda x: x[0])
    return color_points

def get_xml_coeffs(xml_file):
    """Extract reflectance coefficients from XML using xmllint."""
    try:
        result = subprocess.run(
            ["xmllint", "--xpath", "(//*[local-name()='reflectanceCoefficient'])/text()", str(xml_file)],
            capture_output=True, text=True, check=True, timeout=120
        )
        coeffs = result.stdout.split()
        return [float(c) for c in coeffs]
    except Exception:
        return [1.0, 1.0, 1.0, 1.0]

def is_skysat(scene_path: Path) -> bool:
    return "ssc" in scene_path.name.lower()

def extract_base_id(image_path: Path) -> str:
    stem = image_path.stem
    suffixes = [
        "_composite", "_analytic_clip", "_analytic_udm", "_udm2_clip",
        "_visual", "_AnalyticMS_clip", "_AnalyticMS_SR_harmonized", "_pansharpened"
    ]
    lower_stem = stem.lower()
    for s in suffixes:
        if lower_stem.endswith(s.lower()):
            return stem[:-len(s)]
    return stem

def apply_pre_correction(source_file: Path, out_prefix: str, output_dir: Path, progress_callback=None) -> Path:
    ds = gdal.Open(str(source_file))
    if ds is None:
        raise Exception(f"Unable to open {source_file} for pre-correction.")
    cols, rows = ds.RasterXSize, ds.RasterYSize
    driver = gdal.GetDriverByName("GTiff")
    pre_file = output_dir / f"{out_prefix}_precorrect.tif"
    out_ds = driver.Create(
        str(pre_file), cols, rows, 3, gdal.GDT_UInt16,
        options=["COMPRESS=DEFLATE", "PHOTOMETRIC=RGB", "TILED=YES", "BIGTIFF=IF_NEEDED"]
    )
    out_ds.SetGeoTransform(ds.GetGeoTransform())
    out_ds.SetProjection(ds.GetProjection())
    subsample = 10
    band_map = {1: 3, 2: 2, 3: 1}
    for idx, in_band in band_map.items():
        band = ds.GetRasterBand(in_band)
        arr = band.ReadAsArray()
        sample = arr[::subsample, ::subsample]
        low, high = np.percentile(sample, 1), np.percentile(sample, 99)
        if high > low:
            scale = 65535.0 / (high - low)
            stretched = np.clip((arr - low) * scale, 0, 65535).astype('uint16')
        else:
            stretched = arr.astype('uint16')
        out_ds.GetRasterBand(idx).WriteArray(stretched)
        if progress_callback:
            progress_callback(f"Pre-correction: band {idx}/{len(band_map)} done")
    out_ds.FlushCache()
    ds = None
    return pre_file

def process_scene(scene, resolution, radiance_to_reflectance, pre_correction, progress_callback=None):
    scene = Path(scene)
    out_prefix = scene.stem
    output_dir = scene.parent / "rgb"
    output_dir.mkdir(exist_ok=True)
    skysat = is_skysat(scene)
    source = scene
    if "AnalyticMS.tif" in scene.name and not skysat and radiance_to_reflectance:
        xml_file = scene.with_name(f"{scene.stem}_metadata.xml")
        if xml_file.exists():
            coeffs = get_xml_coeffs(xml_file)
            ds = gdal.Open(str(scene))
            temp = scene.parent / f"{scene.stem}_toar.tif"
            drv = gdal.GetDriverByName("GTiff")
            temp_ds = drv.Create(str(temp), ds.RasterXSize, ds.RasterYSize, ds.RasterCount, gdal.GDT_UInt16)
            temp_ds.SetGeoTransform(ds.GetGeoTransform()); temp_ds.SetProjection(ds.GetProjection())
            for i in range(1, ds.RasterCount + 1):
                arr = ds.GetRasterBand(i).ReadAsArray()
                conv = (arr * coeffs[i - 1] * 65535).astype('uint16')
                temp_ds.GetRasterBand(i).WriteArray(conv)
            temp_ds.FlushCache()
            ds, temp_ds = None, None
            source, out_prefix = temp, out_prefix + "_toar"
    if skysat:
        scaled = scene.parent / f"{scene.stem}_scaled.tif"
        subprocess.run(["gdal_translate", "-scale", "0", "4095", "0", "65535", str(source), str(scaled)], check=True, timeout=120)
        source = scaled
    bands = ["-b", "3", "-b", "2", "-b", "1"]
    if pre_correction:
        source, out_prefix, bands = apply_pre_correction(source, out_prefix, output_dir, progress_callback), out_prefix + "_precorrect", ["-b", "1", "-b", "2", "-b", "3"]
    try:
        if resolution and resolution.lower() != "native":
            vrt, tif = output_dir / f"{out_prefix}_{resolution}m_rgb.vrt", output_dir / f"{out_prefix}_{resolution}m_rgb.tif"
            subprocess.run(["gdalbuildvrt", "-r", "bilinear", "-tr", resolution, resolution] + bands + [str(vrt), str(source)], check=True, timeout=300)
            subprocess.run(["gdalwarp", "-srcnodata", "0 0 0", "-dstalpha", "-co", "COMPRESS=DEFLATE", "-co", "PHOTOMETRIC=RGB", "-multi", "-overwrite", str(vrt), str(tif)], check=True, timeout=300)
        else:
            vrt, tif = output_dir / f"{out_prefix}_rgb.vrt", output_dir / f"{out_prefix}_rgb.tif"
            subprocess.run(["gdalbuildvrt"] + bands + [str(vrt), str(source)], check=True, timeout=300)
            subprocess.run(["gdalwarp", "-srcnodata", "0 0 0", "-dstalpha", "-co", "COMPRESS=DEFLATE", "-co", "PHOTOMETRIC=RGB", "-multi", "-overwrite", str(vrt), str(tif)], check=True, timeout=300)
    except Exception as e:
        return f"Error processing {scene.name}: {e}"
    if 'temp' in locals() and temp.exists(): temp.unlink()
    if 'scaled' in locals() and scaled.exists(): scaled.unlink()
    return f"Processed {scene.name}"

def calculate_ndvi(scene: Path, colorize: bool = False, scale_min: float = 0.0, scale_max: float = 1.0, progress_callback=None, **kwargs):
    try:
        source_file = Path(scene)
        if progress_callback: progress_callback(f"Starting NDVI for {source_file.name}")
        output_dir = source_file.parent / "ndvi"
        output_dir.mkdir(exist_ok=True)
        ds = gdal.Open(str(source_file))
        if ds is None: raise Exception(f"Unable to open {source_file}.")
        if ds.RasterCount < 4: return f"Skipped {source_file.name}: requires at least 4 bands."

        is_composite = "_composite" in source_file.name.lower()
        coeffs = [1.0, 1.0, 1.0, 1.0]
        if not is_composite:
            xml_file = source_file.with_name(f"{extract_base_id(source_file)}_metadata.xml")
            if xml_file.exists():
                coeffs = get_xml_coeffs(xml_file)
            else:
                if progress_callback: progress_callback(f"Warning: XML for {source_file.name} not found. Calculating from raw DNs.")
        else:
            if progress_callback: progress_callback(f"Info: {source_file.name} is a composite. Calculating from raw DNs.")

        red_arr, nir_arr = ds.GetRasterBand(3).ReadAsArray().astype(np.float32), ds.GetRasterBand(4).ReadAsArray().astype(np.float32)
        red_reflectance, nir_reflectance = red_arr * coeffs[2], nir_arr * coeffs[3]
        np.seterr(divide='ignore', invalid='ignore')
        denominator = nir_reflectance + red_reflectance
        ndvi = np.divide(nir_reflectance - red_reflectance, denominator, where=denominator != 0, out=np.full_like(denominator, -9999))
        
        out_prefix = source_file.stem
        ndvi_file = output_dir / f"{out_prefix}_ndvi_data.tif"
        driver = gdal.GetDriverByName("GTiff")
        out_ds = driver.Create(str(ndvi_file), ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Float32, options=["COMPRESS=DEFLATE", "TILED=YES"])
        out_ds.SetGeoTransform(ds.GetGeoTransform()); out_ds.SetProjection(ds.GetProjection())
        out_band = out_ds.GetRasterBand(1); out_band.WriteArray(ndvi); out_band.SetNoDataValue(-9999); out_band.FlushCache()

        if colorize:
            if progress_callback: progress_callback(f"Colorizing NDVI for {source_file.name} with scale [{scale_min}, {scale_max}]")
            try:
                ramp_points = parse_hex_color_ramp(PLANET_HEX_RAMP)
                if not ramp_points: raise Exception("Color ramp is empty or could not be parsed.")
                
                xp = [p[0] for p in ramp_points]
                fp_r, fp_g, fp_b = [p[1] for p in ramp_points], [p[2] for p in ramp_points], [p[3] for p in ramp_points]

                if scale_max == scale_min:
                    normalized_ndvi = np.full_like(ndvi, 0.5)
                else:
                    clipped_ndvi = np.clip(ndvi, scale_min, scale_max)
                    normalized_ndvi = (clipped_ndvi - scale_min) / (scale_max - scale_min)

                r_chan, g_chan, b_chan = np.interp(normalized_ndvi, xp, fp_r).astype(np.uint8), np.interp(normalized_ndvi, xp, fp_g).astype(np.uint8), np.interp(normalized_ndvi, xp, fp_b).astype(np.uint8)
                
                nodata_mask = (ndvi == -9999)
                r_chan[nodata_mask], g_chan[nodata_mask], b_chan[nodata_mask] = 0, 0, 0
                
                color_file = output_dir / f"{out_prefix}_ndvi_color.tif"
                color_ds = driver.Create(str(color_file), ds.RasterXSize, ds.RasterYSize, 3, gdal.GDT_Byte, options=["COMPRESS=DEFLATE", "PHOTOMETRIC=RGB", "TILED=YES"])
                color_ds.SetGeoTransform(ds.GetGeoTransform()); color_ds.SetProjection(ds.GetProjection())
                color_ds.GetRasterBand(1).WriteArray(r_chan); color_ds.GetRasterBand(2).WriteArray(g_chan); color_ds.GetRasterBand(3).WriteArray(b_chan)
                for i in range(1, 4): color_ds.GetRasterBand(i).SetNoDataValue(0)
                color_ds.FlushCache()
                if progress_callback: progress_callback(f"Saved colorized NDVI to {color_file.name}")
            except Exception as e:
                if progress_callback: progress_callback(f"ERROR: Could not colorize NDVI: {e}")
        
        ds, out_ds = None, None
        return f"Processed NDVI for {source_file.name}"
    except Exception as e:
        return f"Error processing NDVI for {scene.name}: {e}"

# --- Worker Threads ---
class ProcessWorker(QThread):
    progress_update, finished = pyqtSignal(int, str), pyqtSignal(str)
    def __init__(self, files, resolution, rad2ref, pre):
        super().__init__()
        self.files, self.resolution, self.rad2ref, self.pre = files, resolution, rad2ref, pre
    def run(self):
        total = len(self.files)
        if total == 0: self.finished.emit("No files to process."); return
        for idx, path in enumerate(self.files, start=1):
            msg = process_scene(path, self.resolution, self.rad2ref, self.pre, progress_callback=lambda m: self.progress_update.emit(0, m))
            self.progress_update.emit(int(idx / total * 100), msg)
        self.finished.emit("Processing complete.")

class NdivWorker(QThread):
    progress_update, finished = pyqtSignal(int, str), pyqtSignal(str)
    def __init__(self, files, colorize, scale_min, scale_max):
        super().__init__()
        self.files, self.colorize, self.scale_min, self.scale_max = files, colorize, scale_min, scale_max
    def run(self):
        total = len(self.files)
        if total == 0: self.finished.emit("No files for NDVI."); return
        for idx, path in enumerate(self.files, start=1):
            msg = calculate_ndvi(path, colorize=self.colorize, scale_min=self.scale_min, scale_max=self.scale_max, progress_callback=lambda m: self.progress_update.emit(0, m))
            self.progress_update.emit(int(idx / total * 100), msg)
        self.finished.emit("NDVI processing complete.")

# --- UI Dialogs ---
class MapDialog(QDialog):
    def __init__(self, feature_collection, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Imagery Footprints"); self.resize(800, 600)
        layout = QVBoxLayout(self); self.web = QWebEngineView(); layout.addWidget(self.web)
        html = f"""<!DOCTYPE html><html><head><meta charset='utf-8'/><link rel='stylesheet' href='https://unpkg.com/leaflet/dist/leaflet.css'/><style>#map{{height:100%;width:100%}}html,body{{margin:0;padding:0;height:100%}}</style></head><body><div id='map'></div><script src='https://unpkg.com/leaflet/dist/leaflet.js'></script><script>var map=L.map('map').setView([0,0],2);L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:'© OSM'}}).addTo(map);var layer=L.geoJSON({json.dumps(feature_collection)},{{onEachFeature:(f,l)=>l.bindPopup(f.properties.name)}}).addTo(map);map.fitBounds(layer.getBounds());</script></body></html>"""
        self.web.setHtml(html)

class MetadataDialog(QDialog):
    def __init__(self, metadata, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Image Metadata"); self.resize(600, 400)
        layout = QVBoxLayout(self); self.text = QTextEdit(); self.text.setReadOnly(True); layout.addWidget(self.text)
        self.text.setText(pformat(metadata, indent=4))

# --- Main Application Window ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Converter & Mapper"); self.resize(900, 700)
        self.folders = []
        central = QWidget(); self.setCentralWidget(central)
        main = QVBoxLayout(central)
        
        fl = QHBoxLayout(); self.folder_list = QListWidget(); fl.addWidget(self.folder_list)
        btns = QVBoxLayout(); self.btn_add = QPushButton("Add Folder"); self.btn_remove = QPushButton("Remove Folder")
        btns.addWidget(self.btn_add); btns.addWidget(self.btn_remove); btns.addStretch(); fl.addLayout(btns); main.addLayout(fl)
        
        cl = QVBoxLayout(); hdr = QHBoxLayout(); hdr.addWidget(QLabel("Candidate Files:")); self.btn_all = QPushButton("Select All")
        hdr.addWidget(self.btn_all); cl.addLayout(hdr); self.file_list = QListWidget(); cl.addWidget(self.file_list); main.addLayout(cl)
        self.label_scan = QLabel("No scan yet."); main.addWidget(self.label_scan)
        
        opt = QHBoxLayout(); self.chk_rad = QCheckBox("Convert TOA to Reflectance"); opt.addWidget(self.chk_rad)
        opt.addWidget(QLabel("Resolution:")); self.txt_res = QLineEdit(); self.txt_res.setPlaceholderText("native or meters"); opt.addWidget(self.txt_res)
        self.chk_pre = QCheckBox("Apply Pre-correction"); opt.addWidget(self.chk_pre); opt.addStretch(); main.addLayout(opt)
        
        ndvi_opt = QHBoxLayout(); self.chk_colorize_ndvi = QCheckBox("Create Colorized NDVI"); self.chk_colorize_ndvi.setChecked(True)
        self.txt_scale_min = QLineEdit("0.0"); self.txt_scale_min.setValidator(QDoubleValidator(-1.0, 1.0, 4)); self.txt_scale_min.setFixedWidth(60)
        self.txt_scale_max = QLineEdit("1.0"); self.txt_scale_max.setValidator(QDoubleValidator(-1.0, 1.0, 4)); self.txt_scale_max.setFixedWidth(60)
        ndvi_opt.addWidget(self.chk_colorize_ndvi); ndvi_opt.addWidget(QLabel("Scale:")); ndvi_opt.addWidget(self.txt_scale_min); ndvi_opt.addWidget(QLabel("to")); ndvi_opt.addWidget(self.txt_scale_max); ndvi_opt.addStretch(); main.addLayout(ndvi_opt)
        
        self.pb = QProgressBar(); self.pb.setRange(0, 100); main.addWidget(self.pb)
        self.log = QTextEdit(); self.log.setReadOnly(True); main.addWidget(self.log)
        
        act = QHBoxLayout(); self.btn_scan = QPushButton("Scan Folders"); self.btn_process = QPushButton("Process RGB"); self.btn_calculate_ndvi = QPushButton("Calculate NDVI")
        self.btn_show_map = QPushButton("Show Footprints"); self.btn_read_meta = QPushButton("Read Metadata"); self.btn_reset = QPushButton("Reset")
        act.addWidget(self.btn_scan); act.addWidget(self.btn_process); act.addWidget(self.btn_calculate_ndvi); act.addWidget(self.btn_show_map); act.addWidget(self.btn_read_meta); act.addWidget(self.btn_reset); act.addStretch(); main.addLayout(act)
        
        self.btn_add.clicked.connect(self.add_folder); self.btn_remove.clicked.connect(self.remove_folder)
        self.btn_scan.clicked.connect(self.scan_folders); self.btn_all.clicked.connect(self.select_all)
        self.btn_process.clicked.connect(self.start_processing); self.btn_calculate_ndvi.clicked.connect(self.start_ndvi_processing)
        self.btn_show_map.clicked.connect(self.show_footprints); self.btn_read_meta.clicked.connect(self.read_metadata)
        self.btn_reset.clicked.connect(self.reset_app); self.chk_colorize_ndvi.toggled.connect(self.toggle_scale_inputs)

    def toggle_scale_inputs(self, checked):
        self.txt_scale_min.setEnabled(checked); self.txt_scale_max.setEnabled(checked)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select Folder");
        if d: self.folders.append(d); self.folder_list.addItem(d)

    def remove_folder(self):
        for it in self.folder_list.selectedItems(): self.folders.remove(it.text()); self.folder_list.takeItem(self.folder_list.row(it))

    def scan_folders(self):
        self.file_list.clear(); count = 0
        for folder in self.folders:
            for tif in Path(folder).rglob("*.tif"):
                if "udm" in tif.name.lower(): continue
                typ = "SkySatCollect" if is_skysat(tif) else "PSScene"
                item = QListWidgetItem(f"{tif} ({typ})"); item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked); item.setBackground(QBrush(QColor("lightblue" if is_skysat(tif) else "lightgreen")))
                self.file_list.addItem(item); count += 1
        self.label_scan.setText(f"Found {count} files in {len(self.folders)} folders."); self.log.append(self.label_scan.text())

    def select_all(self):
        for i in range(self.file_list.count()): self.file_list.item(i).setCheckState(Qt.Checked)
        self.log.append("All files selected.")

    def start_processing(self):
        files = [Path(self.file_list.item(i).text().split(' (')[0]) for i in range(self.file_list.count()) if self.file_list.item(i).checkState() == Qt.Checked]
        if not files: self.log.append("No files selected."); return
        res, rad, pre = self.txt_res.text().strip() or None, self.chk_rad.isChecked(), self.chk_pre.isChecked()
        self.log.append("Starting RGB processing..."); self.worker = ProcessWorker(files, res, rad, pre)
        self.worker.progress_update.connect(self.on_progress); self.worker.finished.connect(self.on_finished)
        self.btn_process.setEnabled(False); self.btn_calculate_ndvi.setEnabled(False); self.worker.start()

    def start_ndvi_processing(self):
        files = [Path(self.file_list.item(i).text().split(' (')[0]) for i in range(self.file_list.count()) if self.file_list.item(i).checkState() == Qt.Checked]
        if not files: self.log.append("No files for NDVI."); return
        colorize = self.chk_colorize_ndvi.isChecked()
        try:
            scale_min, scale_max = float(self.txt_scale_min.text()), float(self.txt_scale_max.text())
            if scale_min >= scale_max: self.log.append("Warning: Scale Min must be less than Scale Max. Using defaults."),; scale_min, scale_max = 0.0, 1.0
        except ValueError: self.log.append("Warning: Invalid scale values. Using defaults."); scale_min, scale_max = 0.0, 1.0
        self.log.append("Starting NDVI calculation...")
        self.ndvi_worker = NdivWorker(files, colorize, scale_min, scale_max)
        self.ndvi_worker.progress_update.connect(self.on_progress); self.ndvi_worker.finished.connect(self.on_finished)
        self.btn_process.setEnabled(False); self.btn_calculate_ndvi.setEnabled(False); self.ndvi_worker.start()

    def on_progress(self, val, msg):
        if val > 0: self.pb.setValue(val)
        self.log.append(msg)

    def on_finished(self, msg):
        self.log.append(msg); self.pb.setValue(100)
        self.btn_process.setEnabled(True); self.btn_calculate_ndvi.setEnabled(True)

    def show_footprints(self):
        features = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.checkState() != Qt.Checked: continue
            path = Path(item.text().split(' (')[0]); meta_file = path.with_name(f"{extract_base_id(path)}_metadata.json")
            if meta_file.exists():
                try:
                    with open(meta_file, 'r') as mf: data = json.load(mf)
                    geom = data.get('geometry') or data.get('geojson', {}).get('features', [{}])[0].get('geometry')
                    if geom and 'coordinates' in geom: features.append({'type': 'Feature', 'properties': {'name': path.name}, 'geometry': geom}); continue
                except Exception as e: self.log.append(f"Error reading geometry from metadata for {path.name}: {e}")
            try:
                if rasterio:
                    with rasterio.open(path) as ds:
                        left, bottom, right, top = ds.bounds
                        try: w_left, w_bottom, w_right, w_top = transform_bounds(ds.crs, 'EPSG:4326', left, bottom, right, top, densify_pts=21)
                        except Exception: w_left, w_bottom, w_right, w_top = left, bottom, right, top
                else:
                    ds = gdal.Open(str(path)); gt, w, h = ds.GetGeoTransform(), ds.RasterXSize, ds.RasterYSize
                    left, top = gt[0], gt[3]; right, bottom = gt[0] + gt[1] * w + gt[2] * h, gt[3] + gt[4] * w + gt[5] * h
                    w_left, w_bottom, w_right, w_top = left, bottom, right, top
                coords = [[w_left, w_top], [w_right, w_top], [w_right, w_bottom], [w_left, w_bottom], [w_left, w_top]]
                features.append({'type': 'Feature', 'properties': {'name': path.name}, 'geometry': {'type': 'Polygon', 'coordinates': [coords]}})
            except Exception as e: self.log.append(f"Error computing footprint for {path.name}: {e}")
        if not features: self.log.append("No footprints found."); return
        dlg = MapDialog({'type': 'FeatureCollection', 'features': features}, parent=self); dlg.exec_()

    def read_metadata(self):
        paths = [Path(self.file_list.item(i).text().split(' (')[0]) for i in range(self.file_list.count()) if self.file_list.item(i).checkState() == Qt.Checked]
        if not paths: self.log.append("No file selected for metadata."); return
        path = paths[0]; meta_file = path.with_name(f"{extract_base_id(path)}_metadata.json")
        if not meta_file.exists(): self.log.append(f"Metadata JSON not found for {path.name}"); return
        try:
            with open(meta_file, 'r') as f: metadata = json.load(f)
            dlg = MetadataDialog(metadata, parent=self); dlg.exec_()
        except Exception as e: self.log.append(f"Error reading metadata: {e}")

    def reset_app(self):
        self.folders.clear(); self.folder_list.clear(); self.file_list.clear()
        self.label_scan.setText("No scan yet."); self.log.clear(); self.pb.setValue(0)
        self.txt_res.clear(); self.chk_rad.setChecked(False); self.chk_pre.setChecked(False)
        self.txt_scale_min.setText("0.0"); self.txt_scale_max.setText("1.0"); self.chk_colorize_ndvi.setChecked(True)
        self.log.append("Application reset.")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())