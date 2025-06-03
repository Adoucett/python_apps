#!/usr/bin/env python3
"""
GeoTIFF Metadata Extraction & Batch Viewer for macOS (No GDAL)

This script extracts and displays metadata from one or more GeoTIFF files,
including spatial reference, projection information, geographic extent, band
descriptions, and region identification. You can open multiple GeoTIFFs at
once, click through their metadata in the GUI, and either view a single
extent on a Folium map or plot all loaded extents together.

Usage:
    # GUI batch mode:
    python geoinfo.py [file1.tif file2.tif ...]

    # Terminal mode (single file only):
    python geoinfo.py filename.tif -t
    (prints metadata to stdout)
"""
import os
import sys
import json
import subprocess
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk
import numpy as np
import rasterio
from rasterio.warp import transform_bounds
import pyproj
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import webbrowser
import tempfile
import geopandas as gpd
from shapely.geometry import box
from pyproj import Transformer, CRS
import math

# Optional region identification
try:
    import folium
except ImportError:
    folium = None
try:
    import reverse_geocoder as rg
except ImportError:
    rg = None
try:
    import pycountry
except ImportError:
    pycountry = None

def get_region(lat, lon):
    """Return a crude region identification given lat/lon."""
    if rg:
        try:
            result = rg.search((lat, lon))[0]
            code = result.get('cc', 'XX')
            name = pycountry.countries.get(alpha_2=code).name if pycountry and code in pycountry.countries else code
            mapping = {
                "US": "North America > United States",
                "CA": "North America > Canada",
                "RU": "Asia > Russia",
                "CN": "Asia > China",
                "IN": "Asia > India",
                "BR": "South America > Brazil",
            }
            return mapping.get(code, name)
        except:
            return "Region Unknown"
    return "Region Unknown"

def point_to_webmerc(lon, lat):
    """Convert lon/lat (EPSG:4326) to Web Mercator (EPSG:3857) manually."""
    R = 6378137.0
    x = R * math.radians(lon)
    y = R * math.log(math.tan(math.pi/4 + math.radians(lat)/2))
    return x, y

class GeoTiffInfo:
    def __init__(self, filepath=None):
        self.filepath = filepath
        self.ds = None
        self.metadata = {}
        self.geojson = {}

    def load_file(self, filepath=None):
        if filepath:
            self.filepath = filepath
        if not self.filepath:
            return False
        try:
            self.ds = rasterio.open(self.filepath)
            if not self._has_geotiff_info():
                self.ds.close()
                self.ds = None
                return False
            self._extract_metadata()
            return True
        except Exception as e:
            print(f"Error loading file: {e}")
            return False

    def _has_geotiff_info(self):
        if self.ds is None:
            return False
        transform = self.ds.transform
        identity = rasterio.Affine(1, 0, 0, 0, 1, 0)
        return transform != identity and self.ds.crs is not None

    def _extract_metadata(self):
        ds = self.ds
        m = self.metadata
        m['filepath'] = self.filepath
        m['filename'] = os.path.basename(self.filepath)
        m['driver']   = ds.driver
        m['width']    = ds.width
        m['height']   = ds.height
        m['band_count'] = ds.count
        m['band_descriptions'] = ds.descriptions if ds.descriptions and any(ds.descriptions) else None

        crs = ds.crs
        m['projection'] = str(crs)
        try:
            proj = CRS.from_user_input(crs)
            m['projection_name']   = proj.name
            m['coord_system_type'] = 'Projected' if proj.is_projected else 'Geographic'
            m['datum']             = proj.datum.name if proj.datum else 'Unknown'
            m['ellipsoid']         = proj.ellipsoid.name if proj.ellipsoid else 'Unknown'
            m['proj_units']        = proj.axis_info[0].unit_name if proj.is_projected else 'Degrees'
            m['epsg_code']         = proj.to_epsg() or 'Unknown'
        except:
            m.update({
                'projection_name':'Unknown','coord_system_type':'Unknown',
                'datum':'Unknown','ellipsoid':'Unknown','proj_units':'Unknown','epsg_code':'Unknown'
            })

        try:
            m['wkt'] = crs.to_wkt()
        except:
            m['wkt'] = str(crs)

        t = ds.transform
        m['origin_x'], m['origin_y'] = t.c, t.f
        m['pixel_width'], m['pixel_height'] = t.a, abs(t.e)
        m['x_rotation'], m['y_rotation'] = t.b, t.d
        m['geotransform'] = (t.c, t.a, t.b, t.f, t.d, t.e)

        b = ds.bounds
        m['extent'] = {'minx':b.left,'miny':b.bottom,'maxx':b.right,'maxy':b.top}

        self._create_geojson_extent()
        self._calculate_geographic_bounds()

    def _create_geojson_extent(self):
        e = self.metadata['extent']
        self.geojson = {
            "type":"FeatureCollection","features":[
                {"type":"Feature","properties":{"name":self.metadata['filename']},
                 "geometry":{"type":"Polygon","coordinates":[[
                    [e['minx'],e['miny']],[e['maxx'],e['miny']],
                    [e['maxx'],e['maxy']],[e['minx'],e['maxy']],
                    [e['minx'],e['miny']]
                 ]]}
                }
            ]
        }

    def _calculate_geographic_bounds(self):
        try:
            src = self.ds.crs
            transformer = Transformer.from_crs(src, "EPSG:4326", always_xy=True)
            e = self.metadata['extent']
            corners = [(e['minx'],e['miny']),(e['maxx'],e['miny']),
                       (e['maxx'],e['maxy']),(e['minx'],e['maxy'])]
            wgs = [transformer.transform(x,y) for x,y in corners]
            lons, lats = zip(*wgs)
            mlon, Mlon = min(lons), max(lons)
            mlat, Mlat = min(lats), max(lats)
            clat, clon = (mlat+Mlat)/2,(mlon+Mlon)/2

            self.metadata['geo_bounds'] = {
                'min_lon':mlon,'min_lat':mlat,
                'max_lon':Mlon,'max_lat':Mlat,
                'center_lon':clon,'center_lat':clat
            }
            try:
                wm_x, wm_y = Transformer.from_crs("EPSG:4326","EPSG:3857",always_xy=True).transform(clon,clat)
            except:
                wm_x, wm_y = point_to_webmerc(clon, clat)
            self.metadata['center_web_mercator'] = (wm_x, wm_y)
            self.metadata['region'] = get_region(clat, clon)

            # also build a clean WGS84 geojson
            self.wgs84_geojson = {
                "type":"FeatureCollection","features":[
                    {"type":"Feature","properties":{"name":self.metadata['filename']},
                     "geometry":{"type":"Polygon","coordinates":[[
                        [mlon,mlat],[Mlon,mlat],
                        [Mlon,Mlat],[mlon,Mlat],[mlon,mlat]
                     ]]}
                    }
                ]
            }

        except Exception as e:
            print(f"Error in geographic bounds: {e}")
            self.metadata['geo_bounds'] = {
                'min_lon':0,'min_lat':0,'max_lon':0,'max_lat':0,
                'center_lon':0,'center_lat':0
            }
            self.metadata['center_web_mercator'] = (0,0)
            self.metadata['region'] = "Region Unknown"

    def create_folium_map(self):
        if folium is None:
            raise RuntimeError("Please install folium (`pip install folium`).")
        b = self.metadata.get('geo_bounds',{})
        if not b or abs(b['center_lat'])<1e-6 and abs(b['center_lon'])<1e-6:
            raise RuntimeError("Invalid geographic bounds.")
        m = folium.Map(location=[b['center_lat'],b['center_lon']], zoom_start=10)
        folium.Rectangle(
            bounds=[(b['min_lat'],b['min_lon']), (b['max_lat'],b['max_lon'])],
            color='red', fill=True, fill_opacity=0.2,
            popup=self.metadata['filename']
        ).add_to(m)
        folium.Marker([b['center_lat'],b['center_lon']], popup=self.metadata['filename']).add_to(m)
        m.fit_bounds([(b['min_lat'],b['min_lon']), (b['max_lat'],b['max_lon'])])
        return m

    def save_geojson(self, output_path=None):
        if not output_path:
            output_path = os.path.splitext(self.filepath)[0] + ".geojson"
        with open(output_path, "w") as f:
            json.dump(getattr(self, 'wgs84_geojson', self.geojson), f, indent=4)
        return output_path

    def get_formatted_metadata(self):
        m = self.metadata
        if not m:
            return "No metadata available."
        lines = [
            f"File: {m['filename']}",
            f"Path: {m['filepath']}",
            f"Driver: {m['driver']}",
            "",
            "Image Properties:",
            f"  Dimensions: {m['width']}×{m['height']} px",
            f"  Bands: {m['band_count']}"
        ]
        if m.get('band_descriptions'):
            lines.append("  Band Descriptions:")
            for i, d in enumerate(m['band_descriptions'], 1):
                lines.append(f"    {i}: {d or '–'}")
        lines += [
            "",
            "Spatial Reference:",
            f"  Type: {m['coord_system_type']}",
            f"  Projection: {m.get('projection_name','?')}",
            f"  Datum: {m.get('datum','?')}",
            f"  Ellipsoid: {m.get('ellipsoid','?')}",
            f"  Units: {m.get('proj_units','?')}",
            f"  EPSG: {m.get('epsg_code','?')}",
            "",
            "Geotransform:",
            f"  Origin: ({m['origin_x']}, {m['origin_y']})",
            f"  Pixel Size: {m['pixel_width']}×{m['pixel_height']}",
            f"  Rotation: X={m['x_rotation']}, Y={m['y_rotation']}",
            "",
            "Extent (native CRS):",
            f"  MinX: {m['extent']['minx']}",
            f"  MinY: {m['extent']['miny']}",
            f"  MaxX: {m['extent']['maxx']}",
            f"  MaxY: {m['extent']['maxy']}",
            ""
        ]
        if 'geo_bounds' in m:
            gb = m['geo_bounds']
            lines += [
                "Extent (WGS84):",
                f"  Lon: {gb['min_lon']} → {gb['max_lon']}",
                f"  Lat: {gb['min_lat']} → {gb['max_lat']}",
                f"  Center: ({gb['center_lat']}, {gb['center_lon']})",
                "",
                "Region: " + m.get('region', 'Unknown')
            ]
        return "\n".join(lines)

    def close(self):
        if self.ds:
            self.ds.close()
            self.ds = None

class GUIApp:
    def __init__(self, root, filepaths=None):
        self.root = root
        self.root.title("GeoTIFF Metadata Viewer — Batch Mode")
        self.loaded_infos = {}   # name → GeoTiffInfo
        self.map_file = None

        # Layout: PanedWindow with Listbox on left, metadata on right
        pw = ttk.Panedwindow(root, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True)

        # Left frame: buttons + listbox + map-buttons
        lf = ttk.Frame(pw, width=200, padding=5)
        pw.add(lf, weight=1)
        ttk.Button(lf, text="Open Files…", command=self.browse_files).pack(fill=tk.X, pady=2)
        self.listbox = tk.Listbox(lf, height=20)
        self.listbox.pack(fill=tk.BOTH, expand=True, pady=2)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)
        mf = ttk.Frame(lf)
        mf.pack(fill=tk.X, pady=5)
        ttk.Button(mf, text="Show Selected", command=self.show_selected_map).pack(side=tk.LEFT, expand=True)
        ttk.Button(mf, text="Show All",      command=self.show_all_map).pack(side=tk.LEFT, expand=True)

        # Right frame: metadata display + save/copy buttons
        rf = ttk.Frame(pw, padding=5)
        pw.add(rf, weight=4)
        bf = ttk.Frame(rf)
        bf.pack(fill=tk.X, pady=2)
        ttk.Button(bf, text="Save GeoJSON", command=self.save_geojson).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="Copy GeoJSON", command=self.copy_geojson).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="Exit",         command=root.destroy).pack(side=tk.RIGHT, padx=2)

        self.metadata_text = scrolledtext.ScrolledText(rf, wrap=tk.WORD)
        self.metadata_text.pack(fill=tk.BOTH, expand=True, pady=5)

        # Load any initial paths
        if filepaths:
            self.load_files(filepaths)

    def browse_files(self):
        ftypes = [("GeoTIFF","*.tif *.tiff"),("All","*.*")]
        paths = filedialog.askopenfilenames(title="Select GeoTIFFs", filetypes=ftypes)
        if paths:
            self.load_files(paths)

    def load_files(self, paths):
        for p in paths:
            name = os.path.basename(p)
            if name in self.loaded_infos:
                continue
            info = GeoTiffInfo()
            if info.load_file(p):
                self.loaded_infos[name] = info
                self.listbox.insert(tk.END, name)
        # auto-select first if nothing selected
        if self.listbox.size() and not self.listbox.curselection():
            self.listbox.selection_set(0)
            self.on_select()

    def on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        name = self.listbox.get(sel[0])
        meta = self.loaded_infos[name].get_formatted_metadata()
        self.metadata_text.delete(1.0, tk.END)
        self.metadata_text.insert(tk.END, meta)

    def save_geojson(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning("No selection", "Select a file first.")
            return
        name = self.listbox.get(sel[0])
        info = self.loaded_infos[name]
        out = filedialog.asksaveasfilename(
            title="Save GeoJSON", defaultextension=".geojson",
            initialfile=name.replace('.tif','.geojson'),
            filetypes=[("GeoJSON","*.geojson"),("All","*.*")]
        )
        if out:
            try:
                path = info.save_geojson(out)
                messagebox.showinfo("Saved", f"GeoJSON saved to:\n{path}")
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def copy_geojson(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning("No selection", "Select a file first.")
            return
        info = self.loaded_infos[self.listbox.get(sel[0])]
        gj = getattr(info, 'wgs84_geojson', info.geojson)
        txt = json.dumps(gj, indent=4)
        self.root.clipboard_clear()
        self.root.clipboard_append(txt)
        messagebox.showinfo("Copied", "GeoJSON copied to clipboard.")

    def show_selected_map(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning("No selection", "Select a file first.")
            return
        self._open_map_for([ self.loaded_infos[self.listbox.get(sel[0])] ])

    def show_all_map(self):
        if not self.loaded_infos:
            messagebox.showwarning("No files", "Load at least one GeoTIFF.")
            return
        self._open_map_for(self.loaded_infos.values())

    def _open_map_for(self, infos):
        if folium is None:
            messagebox.showerror("Missing Dependency", "Install folium (`pip install folium`).")
            return

        # gather all lat/lon corners
        all_lats, all_lons = [], []
        for info in infos:
            b = info.metadata.get('geo_bounds',{})
            all_lats += [b.get('min_lat',0), b.get('max_lat',0)]
            all_lons += [b.get('min_lon',0), b.get('max_lon',0)]

        # center on midpoint
        ctr = [(max(all_lats)+min(all_lats))/2, (max(all_lons)+min(all_lons))/2]
        m = folium.Map(location=ctr, zoom_start=5)

        for info in infos:
            b = info.metadata['geo_bounds']
            folium.Rectangle(
                bounds=[(b['min_lat'],b['min_lon']), (b['max_lat'],b['max_lon'])],
                color='red', fill=True, fill_opacity=0.2,
                popup=info.metadata['filename']
            ).add_to(m)
            folium.Marker(
                [b['center_lat'], b['center_lon']],
                popup=info.metadata['filename']
            ).add_to(m)

        m.fit_bounds([(min(all_lats), min(all_lons)), (max(all_lats), max(all_lons))])

        # write & open
        if self.map_file and os.path.exists(self.map_file):
            try: os.unlink(self.map_file)
            except: pass
        fd, self.map_file = tempfile.mkstemp(suffix=".html")
        os.close(fd)
        m.save(self.map_file)
        webbrowser.open(f"file://{self.map_file}")

def print_metadata_to_terminal(info):
    print(info.get_formatted_metadata())

def main():
    terminal = False
    files = []
    for arg in sys.argv[1:]:
        if arg == "-t":
            terminal = True
        else:
            files.append(arg)

    if terminal:
        if not files:
            print("Error: In terminal mode, supply one GeoTIFF file.")
            sys.exit(1)
        info = GeoTiffInfo()
        if info.load_file(files[0]):
            print_metadata_to_terminal(info)
            info.close()
        else:
            print(f"Error: {files[0]} is not a valid GeoTIFF with geospatial info.")
        sys.exit(0)

    root = tk.Tk()
    GUIApp(root, files)
    root.mainloop()

if __name__ == "__main__":
    main()
