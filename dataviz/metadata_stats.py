#!/usr/bin/env python3
"""
Enhanced Metadata Analysis

Loads JSON metadata files, computes detailed distributions for each variable,
ranks images by composite quality score, and outputs per-frame quality
percentiles for filtering decisions.
"""
import os
import json
import argparse
import pandas as pd
import numpy as np
from glob import glob

# Key numeric fields
NUMERIC_FIELDS = [
    'clear_percent',
    'visible_confidence_percent',
    'cloud_percent',
    'heavy_haze_percent',
    'light_haze_percent',
    'snow_ice_percent',
    'shadow_percent',
    'anomalous_pixels',
    'view_angle',
    'sun_elevation'
]

# Composite quality score weights
# Higher clear and visible -> positive, higher cloud/haze -> negative
WEIGHTS = {
    'clear_percent': 0.3,
    'visible_confidence_percent': 0.3,
    'cloud_percent': -0.2,
    'heavy_haze_percent': -0.1,
    'light_haze_percent': -0.05,
    'shadow_percent': -0.05
}


def load_metadata(folder):
    records = []
    for jf in glob(os.path.join(folder, '*_metadata.json')):
        try:
            with open(jf) as f:
                data = json.load(f)
            props = data.get('properties', {})
            rec = {k: props.get(k, np.nan) for k in NUMERIC_FIELDS}
            rec['filename'] = os.path.basename(jf)
            records.append(rec)
        except Exception:
            print(f"Warning: could not parse {jf}")
    df = pd.DataFrame(records)
    return df.set_index('filename')


def compute_quality_score(df):
    norm = {}
    for field, weight in WEIGHTS.items():
        series = df[field].astype(float)
        # normalize to 0-1
        minv, maxv = series.min(), series.max()
        if maxv - minv < 1e-6:
            norm[field] = series.copy().fillna(1.0)
        else:
            scaled = (series - minv) / (maxv - minv)
            if weight < 0:
                scaled = 1 - scaled
            norm[field] = scaled
    norm_df = pd.DataFrame(norm)
    score = pd.Series(0.0, index=df.index)
    for field, weight in WEIGHTS.items():
        score += norm_df[field] * abs(weight)
    # rescale 0-100
    min_s, max_s = score.min(), score.max()
    if max_s - min_s < 1e-6:
        score = pd.Series(100.0, index=df.index)
    else:
        score = 100 * (score - min_s) / (max_s - min_s)
    return score


def analyze_distributions(df):
    desc = df.describe().T
    percentiles = [0, 5, 25, 50, 75, 95, 100]
    pct = df.quantile([p / 100 for p in percentiles]).T
    pct.columns = [f'p{int(p)}' for p in percentiles]
    return desc, pct


def main():
    parser = argparse.ArgumentParser(description='Enhanced metadata analysis for timelapse filtering')
    parser.add_argument('folder', help='Folder containing metadata JSONs')
    parser.add_argument('--top', type=int, default=5, help='Number of best/worst images to list')
    parser.add_argument('--output_csv', help='Output CSV path for detailed results', default=None)
    args = parser.parse_args()

    df = load_metadata(args.folder)
    if df.empty:
        print("No metadata files found.")
        return

    df['quality_score'] = compute_quality_score(df)
    desc, pct = analyze_distributions(df[NUMERIC_FIELDS])

    pd.set_option('display.float_format', lambda x: f"{x:.2f}")
    print("--- Variable Distributions (Descriptive) ---")
    print(desc[['mean', 'std', 'min', 'max']])

    print("--- Key Percentiles ---")
    print(pct)

    print(f"--- Top {args.top} Highest-Quality Frames ---")
    print(df['quality_score'].sort_values(ascending=False).head(args.top))

    print(f"--- Top {args.top} Lowest-Quality Frames ---")
    print(df['quality_score'].sort_values(ascending=True).head(args.top))

    if args.output_csv:
        df.to_csv(args.output_csv)
        print(f"Detailed results written to {args.output_csv}")

if __name__ == '__main__':
    main()
