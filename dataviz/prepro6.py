#!/usr/bin/env python3
import os
import subprocess
from pathlib import Path
import sys
import json
from pprint import pformat
import numpy as np

# Optional: import rasterio for robust CRS handling
try:
    import rasterio
    from rasterio.warp import transform_bounds
except ImportError:
    rasterio = None

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QListWidgetItem, QLabel, QFileDialog, QLineEdit, QCheckBox,
    QProgressBar, QTextEdit, QDialog
)
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWebEngineWidgets import QWebEngineView

# Ensure GDAL support
try:
    from osgeo import gdal
except ImportError:
    sys.exit("GDAL Python bindings are required. Install with 'pip install gdal' or 'conda install gdal'.")

# --- Helper Functions ---

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
        "_analytic_clip", "_analytic_udm", "_udm2_clip",
        "_visual", "_AnalyticMS_clip", "_AnalyticMS_SR_harmonized", "_pansharpened"
    ]
    for s in suffixes:
        if stem.lower().endswith(s.lower()):
            return stem[:-len(s)]
    return stem


def apply_pre_correction(source_file: Path, out_prefix: str, output_dir: Path, progress_callback=None) -> Path:
    ds = gdal.Open(str(source_file))
    if ds is None:
        raise Exception(f"Unable to open {source_file} for pre-correction.")
    cols = ds.RasterXSize
    rows = ds.RasterYSize
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
        low = np.percentile(sample, 1)
        high = np.percentile(sample, 99)
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
    # Radiance-to-reflectance
    if "AnalyticMS.tif" in scene.name and not skysat and radiance_to_reflectance:
        xml_file = scene.with_name(f"{scene.stem}_metadata.xml")
        if xml_file.exists():
            coeffs = get_xml_coeffs(xml_file)
            ds = gdal.Open(str(scene))
            temp = scene.parent / f"{scene.stem}_toar.tif"
            drv = gdal.GetDriverByName("GTiff")
            temp_ds = drv.Create(str(temp), ds.RasterXSize, ds.RasterYSize, ds.RasterCount, gdal.GDT_UInt16)
            temp_ds.SetGeoTransform(ds.GetGeoTransform())
            temp_ds.SetProjection(ds.GetProjection())
            for i in range(1, ds.RasterCount + 1):
                arr = ds.GetRasterBand(i).ReadAsArray()
                conv = (arr * coeffs[i-1] * 65535).astype('uint16')
                temp_ds.GetRasterBand(i).WriteArray(conv)
            temp_ds.FlushCache()
            ds = None; temp_ds = None
            source = temp
            out_prefix += "_toar"
    # SkySat 12->16 bit
    if skysat:
        scaled = scene.parent / f"{scene.stem}_scaled.tif"
        subprocess.run(
            ["gdal_translate", "-scale", "0", "4095", "0", "65535", str(source), str(scaled)],
            check=True, timeout=120
        )
        source = scaled
    # Pre-correction
    bands = ["-b", "3", "-b", "2", "-b", "1"]
    if pre_correction:
        pre_src = apply_pre_correction(source, out_prefix, output_dir, progress_callback)
        source = pre_src
        out_prefix += "_precorrect"
        bands = ["-b", "1", "-b", "2", "-b", "3"]
    # Build VRT & warp
    try:
        if resolution and resolution.lower() != "native":
            vrt = output_dir / f"{out_prefix}_{resolution}m_rgb.vrt"
            tif = output_dir / f"{out_prefix}_{resolution}m_rgb.tif"
            subprocess.run(
                ["gdalbuildvrt", "-r", "bilinear", "-tr", resolution, resolution] + bands + [str(vrt), str(source)],
                check=True, timeout=300
            )
            subprocess.run(
                ["gdalwarp", "-srcnodata", "0 0 0", "-dstalpha", "-co", "COMPRESS=DEFLATE",
                 "-co", "PHOTOMETRIC=RGB", "-multi", "-overwrite", str(vrt), str(tif)],
                check=True, timeout=300
            )
        else:
            vrt = output_dir / f"{out_prefix}_rgb.vrt"
            tif = output_dir / f"{out_prefix}_rgb.tif"
            subprocess.run(
                ["gdalbuildvrt"] + bands + [str(vrt), str(source)], check=True, timeout=300
            )
            subprocess.run(
                ["gdalwarp", "-srcnodata", "0 0 0", "-dstalpha", "-co", "COMPRESS=DEFLATE",
                 "-co", "PHOTOMETRIC=RGB", "-multi", "-overwrite", str(vrt), str(tif)],
                check=True, timeout=300
            )
    except Exception as e:
        return f"Error processing {scene.name}: {e}"
     # Cleanup
   # remove the temporary TOA conversion file, if any
    if 'temp' in locals() and temp.exists():
        temp.unlink()

    # remove the SkySat 12→16-bit staging file, if any
    if 'scaled' in locals() and scaled.exists():
        scaled.unlink()
    return f"Processed {scene.name}"

# --- Worker Thread ---
class ProcessWorker(QThread):
    progress_update = pyqtSignal(int, str)
    finished = pyqtSignal(str)

    def __init__(self, files, resolution, rad2ref, pre):
        super().__init__()
        self.files = files
        self.resolution = resolution
        self.rad2ref = rad2ref
        self.pre = pre

    def run(self):
        total = len(self.files)
        if total == 0:
            self.finished.emit("No files to process.")
            return
        for idx, path in enumerate(self.files, start=1):
            msg = process_scene(path, self.resolution, self.rad2ref, self.pre,
                                progress_callback=lambda m: self.progress_update.emit(0, m))
            self.progress_update.emit(int(idx/total*100), msg)
        self.finished.emit("Processing complete.")

# --- Map Dialog ---
class MapDialog(QDialog):
    def __init__(self, feature_collection, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Imagery Footprints")
        self.resize(800, 600)
        layout = QVBoxLayout(self)
        self.web = QWebEngineView()
        layout.addWidget(self.web)
        html = self._gen_html(feature_collection)
        self.web.setHtml(html)

    def _gen_html(self, fc):
        return f"""
<!DOCTYPE html><html><head><meta charset='utf-8'/><link rel='stylesheet' href='https://unpkg.com/leaflet/dist/leaflet.css'/><style>#map{{height:100%;width:100%}}html,body{{margin:0;padding:0;height:100%}}</style></head><body><div id='map'></div><script src='https://unpkg.com/leaflet/dist/leaflet.js'></script><script>var map=L.map('map').setView([0,0],2);L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:'© OSM'}}).addTo(map);var layer=L.geoJSON({json.dumps(fc)},{{onEachFeature:(f,l)=>l.bindPopup(f.properties.name)}}).addTo(map);map.fitBounds(layer.getBounds());</script></body></html>"""

# --- Metadata Dialog ---
class MetadataDialog(QDialog):
    def __init__(self, metadata, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Image Metadata")
        self.resize(600, 400)
        layout = QVBoxLayout(self)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text)
        self.text.setText(pformat(metadata, indent=4))

# --- Main Window ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Converter & Mapper")
        self.resize(900, 700)
        self.folders = []
        central = QWidget()
        self.setCentralWidget(central)
        main = QVBoxLayout(central)
        # Folder list
        fl = QHBoxLayout()
        self.folder_list = QListWidget()
        fl.addWidget(self.folder_list)
        btns = QVBoxLayout()
        self.btn_add = QPushButton("Add Folder")
        self.btn_remove = QPushButton("Remove Folder")
        btns.addWidget(self.btn_add)
        btns.addWidget(self.btn_remove)
        btns.addStretch()
        fl.addLayout(btns)
        main.addLayout(fl)
        # File list
        cl = QVBoxLayout()
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Candidate Files:"))
        self.btn_all = QPushButton("Select All")
        hdr.addWidget(self.btn_all)
        cl.addLayout(hdr)
        self.file_list = QListWidget()
        cl.addWidget(self.file_list)
        main.addLayout(cl)
        self.label_scan = QLabel("No scan yet.")
        main.addWidget(self.label_scan)
        # Options
        opt = QHBoxLayout()
        self.chk_rad = QCheckBox("Convert TOA to Reflectance")
        opt.addWidget(self.chk_rad)
        opt.addWidget(QLabel("Resolution:"))
        self.txt_res = QLineEdit()
        self.txt_res.setPlaceholderText("native or meters")
        opt.addWidget(self.txt_res)
        self.chk_pre = QCheckBox("Apply Pre-correction")
        opt.addWidget(self.chk_pre)
        opt.addStretch()
        main.addLayout(opt)
        # Progress & log
        self.pb = QProgressBar()
        self.pb.setRange(0, 100)
        main.addWidget(self.pb)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        main.addWidget(self.log)
        # Actions
        act = QHBoxLayout()
        self.btn_scan = QPushButton("Scan Folders")
        self.btn_process = QPushButton("Process Files")
        self.btn_show_map = QPushButton("Show Footprints")
        self.btn_read_meta = QPushButton("Read Metadata")
        self.btn_reset = QPushButton("Reset")
        act.addWidget(self.btn_scan)
        act.addWidget(self.btn_process)
        act.addWidget(self.btn_show_map)
        act.addWidget(self.btn_read_meta)
        act.addWidget(self.btn_reset)
        act.addStretch()
        main.addLayout(act)
        # Connect signals
        self.btn_add.clicked.connect(self.add_folder)
        self.btn_remove.clicked.connect(self.remove_folder)
        self.btn_scan.clicked.connect(self.scan_folders)
        self.btn_all.clicked.connect(self.select_all)
        self.btn_process.clicked.connect(self.start_processing)
        self.btn_show_map.clicked.connect(self.show_footprints)
        self.btn_read_meta.clicked.connect(self.read_metadata)
        self.btn_reset.clicked.connect(self.reset_app)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select Folder")
        if d:
            self.folders.append(d)
            self.folder_list.addItem(d)

    def remove_folder(self):
        for it in self.folder_list.selectedItems():
            self.folders.remove(it.text())
            self.folder_list.takeItem(self.folder_list.row(it))

    def scan_folders(self):
        self.file_list.clear()
        count = 0
        for folder in self.folders:
            for tif in Path(folder).rglob("*.tif"):
                if "udm" in tif.name.lower():
                    continue
                typ = "SkySatCollect" if is_skysat(tif) else "PSScene"
                item = QListWidgetItem(f"{tif} ({typ})")
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                color = "lightblue" if is_skysat(tif) else "lightgreen"
                item.setBackground(QBrush(QColor(color)))
                self.file_list.addItem(item)
                count += 1
        self.label_scan.setText(f"Found {count} files in {len(self.folders)} folders.")
        self.log.append(self.label_scan.text())

    def select_all(self):
        for i in range(self.file_list.count()):
            self.file_list.item(i).setCheckState(Qt.Checked)
        self.log.append("All files selected.")

    def start_processing(self):
        files = []
        for i in range(self.file_list.count()):
            it = self.file_list.item(i)
            if it.checkState() == Qt.Checked:
                path = Path(it.text().split(' (')[0])
                files.append(path)
        if not files:
            self.log.append("No files selected.")
            return
        res = self.txt_res.text().strip() or None
        rad = self.chk_rad.isChecked()
        pre = self.chk_pre.isChecked()
        self.log.append("Starting processing...")
        self.worker = ProcessWorker(files, res, rad, pre)
        self.worker.progress_update.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.btn_process.setEnabled(False)
        self.worker.start()

    def on_progress(self, val, msg):
        self.pb.setValue(val)
        self.log.append(msg)

    def on_finished(self, msg):
        self.log.append(msg)
        self.btn_process.setEnabled(True)

    def show_footprints(self):
        features = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.checkState() != Qt.Checked:
                continue
            path = Path(item.text().split(' (')[0])
            # First try reading geometry directly from metadata JSON
            meta_file = path.with_name(f"{extract_base_id(path)}_metadata.json")
            if meta_file.exists():
                try:
                    with open(meta_file, 'r') as mf:
                        data = json.load(mf)
                    geom = data.get('geometry') or data.get('geojson', {}).get('features', [{}])[0].get('geometry')
                    if geom and 'coordinates' in geom:
                        features.append({
                            'type': 'Feature',
                            'properties': {'name': path.name},
                            'geometry': geom
                        })
                        continue
                except Exception as e:
                    self.log.append(f"Error reading geometry from metadata for {path.name}: {e}")
            # Fallback: compute bounds via rasterio or GDAL
            try:
                if rasterio:
                    with rasterio.open(path) as ds:
                        left, bottom, right, top = ds.bounds
                        try:
                            w_left, w_bottom, w_right, w_top = transform_bounds(
                                ds.crs, 'EPSG:4326', left, bottom, right, top, densify_pts=21
                            )
                        except Exception:
                            w_left, w_bottom, w_right, w_top = left, bottom, right, top
                else:
                    ds = gdal.Open(str(path))
                    gt = ds.GetGeoTransform()
                    w, h = ds.RasterXSize, ds.RasterYSize
                    left, top = gt[0], gt[3]
                    right = gt[0] + gt[1]*w + gt[2]*h
                    bottom = gt[3] + gt[4]*w + gt[5]*h
                    w_left, w_bottom, w_right, w_top = left, bottom, right, top
                coords = [[w_left, w_top], [w_right, w_top], [w_right, w_bottom], [w_left, w_bottom], [w_left, w_top]]
                features.append({
                    'type': 'Feature',
                    'properties': {'name': path.name},
                    'geometry': {'type': 'Polygon', 'coordinates': [coords]}
                })
            except Exception as e:
                self.log.append(f"Error computing footprint for {path.name}: {e}")
        if not features:
            self.log.append("No footprints found.")
            return
        feature_collection = {'type': 'FeatureCollection', 'features': features}
        dlg = MapDialog(feature_collection, parent=self)
        dlg.exec_()

    def read_metadata(self):
        paths = []
        for i in range(self.file_list.count()):
            it = self.file_list.item(i)
            if it.checkState() == Qt.Checked:
                paths.append(Path(it.text().split(' (')[0]))
        if not paths:
            self.log.append("No file selected for metadata.")
            return
        path = paths[0]
        meta_file = path.with_name(f"{extract_base_id(path)}_metadata.json")
        if not meta_file.exists():
            self.log.append(f"Metadata JSON not found for {path.name}")
            return
        try:
            with open(meta_file, 'r') as f:
                metadata = json.load(f)
            dlg = MetadataDialog(metadata, parent=self)
            dlg.exec_()
        except Exception as e:
            self.log.append(f"Error reading metadata: {e}")

    def reset_app(self):
        self.folders.clear()
        self.folder_list.clear()
        self.file_list.clear()
        self.label_scan.setText("No scan yet.")
        self.log.clear()
        self.pb.setValue(0)
        self.txt_res.clear()
        self.chk_rad.setChecked(False)
        self.chk_pre.setChecked(False)
        self.log.append("Application reset.")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
