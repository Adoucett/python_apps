#!/usr/bin/env python3
import sys
import os
import json
import csv
import argparse

def find_coord_keys(obj):
    """Find the keys for latitude and longitude in a dict (case‐insensitive)."""
    lat_keys = {'lat','latitude'}
    lon_keys = {'lon','lng','long','longitude'}
    lat = next((k for k in obj if k.lower() in lat_keys), None)
    lon = next((k for k in obj if k.lower() in lon_keys), None)
    return lat, lon

def load_records(path):
    """Load list of dicts from a JSON array or from a CSV file."""
    ext = os.path.splitext(path)[1].lower()
    if ext == '.json':
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("JSON input must be an array of objects")
            return data
    elif ext == '.csv':
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            return list(reader)
    else:
        raise ValueError(f"Unsupported input format: {ext}")

def to_geojson_features(records):
    """Convert list of dict-records into GeoJSON Feature dicts."""
    features = []
    for rec in records:
        lat_key, lon_key = find_coord_keys(rec)
        if lat_key is None or lon_key is None:
            # skip records without both coords
            continue
        try:
            lat = float(rec[lat_key])
            lon = float(rec[lon_key])
        except (ValueError, TypeError):
            continue

        # build properties without the coord fields
        props = {k: v for k, v in rec.items()
                 if k not in (lat_key, lon_key) and v != ''}
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat]
            },
            "properties": props
        }
        features.append(feature)
    return features

def write_geojson(features, outpath):
    """Write a FeatureCollection to a file."""
    fc = {
        "type": "FeatureCollection",
        "features": features
    }
    with open(outpath, 'w', encoding='utf-8') as f:
        json.dump(fc, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(features)} features to {outpath}")

def main():
    p = argparse.ArgumentParser(
        description="Convert a JSON or CSV of lat/lon points into a GeoJSON Point FeatureCollection."
    )
    p.add_argument("input", help="Path to input .json or .csv file")
    p.add_argument("output", help="Path to output .geojson file")
    args = p.parse_args()

    recs = load_records(args.input)
    feats = to_geojson_features(recs)
    write_geojson(feats, args.output)

if __name__ == "__main__":
    main()
