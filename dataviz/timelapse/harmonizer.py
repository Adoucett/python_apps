import os
import numpy as np
import rasterio
from skimage.exposure import match_histograms
from multiprocessing import Pool
import logging

# Suppress NotGeoreferencedWarning from rasterio
logging.getLogger('rasterio').setLevel(logging.ERROR)

def compute_histogram(image, channel, bins, range_min, range_max):
    """Compute histogram for a single channel."""
    return np.histogram(image[channel], bins=bins, range=(range_min, range_max))[0]

def get_valid_folder(prompt, must_exist=True):
    """Prompt for a folder path and validate it."""
    while True:
        folder = input(prompt).strip()
        if not folder:
            print("Error: Folder path cannot be empty.")
            continue
        folder = os.path.abspath(folder)  # Convert to absolute path
        if must_exist:
            if not os.path.exists(folder):
                print(f"Error: Folder '{folder}' does not exist.")
                continue
            if not os.path.isdir(folder):
                print(f"Error: '{folder}' is not a directory.")
                continue
        return folder

def get_tif_files(input_folder):
    """Get list of TIF files in the input folder."""
    tif_files = [f for f in os.listdir(input_folder) if f.lower().endswith('.tif')]
    if not tif_files:
        raise ValueError(f"No TIF files found in '{input_folder}'.")
    return tif_files

def process_image(args):
    """Process a single image: read, match histograms, and save."""
    input_path, output_path, ref_image, dtype = args
    try:
        with rasterio.open(input_path) as src:
            image = src.read()
            meta = src.meta.copy()
            # Verify 3 bands (RGB)
            if image.shape[0] != 3:
                raise ValueError(f"Image {os.path.basename(input_path)} has {image.shape[0]} bands, expected 3 (RGB).")
            # Apply histogram matching
            corrected_image = match_histograms(
                image, ref_image, channel_axis=0
            ).astype(dtype)
            # Verify output has 3 bands
            if corrected_image.shape[0] != 3:
                raise ValueError(f"Corrected image {os.path.basename(input_path)} has {corrected_image.shape[0]} bands, expected 3 (RGB).")
            # Update metadata to ensure RGB
            meta.update(photometric='RGB', count=3)
            with rasterio.open(output_path, 'w', **meta) as dst:
                dst.write(corrected_image)
        return os.path.basename(input_path)
    except Exception as e:
        return f"Error processing {os.path.basename(input_path)}: {str(e)}"

def main(input_folder, output_folder, num_workers=10):
    # Step 1: List all TIF files
    tif_files = get_tif_files(input_folder)
    file_paths = [os.path.join(input_folder, f) for f in tif_files]
    num_images = len(file_paths)
    print(f"Found {num_images} TIF files.")

    # Step 2: Validate first image and determine data type
    with rasterio.open(file_paths[0]) as src:
        sample_image = src.read()
        num_channels = sample_image.shape[0]
        if num_channels != 3:
            raise ValueError(f"First image {os.path.basename(file_paths[0])} has {num_channels} bands, expected 3 (RGB).")
        print(f"Confirmed {num_channels}-band (RGB) images.")
        dtype = sample_image.dtype
        if dtype == np.uint8:
            bins = 256
            hist_range = (0, 255)
        elif dtype == np.uint16:
            bins = 256  # Reduced for efficiency; adjust if needed
            hist_range = (0, 65535)
        else:
            raise ValueError(f"Unsupported data type: {dtype}")

    # Step 3: Compute histograms for each image and channel (sequential)
    histograms = {c: [] for c in range(num_channels)}
    for path in file_paths:
        with rasterio.open(path) as src:
            image = src.read()
            if image.shape[0] != 3:
                raise ValueError(f"Image {os.path.basename(path)} has {image.shape[0]} bands, expected 3 (RGB).")
            for c in range(num_channels):
                hist = compute_histogram(image, c, bins, *hist_range)
                histograms[c].append(hist)

    # Step 4: Compute average histogram for each channel
    avg_histograms = {}
    for c in range(num_channels):
        avg_histograms[c] = np.mean(histograms[c], axis=0)

    # Step 5: Find the reference image (closest to average histogram)
    distances = []
    for idx, path in enumerate(file_paths):
        dist = 0
        for c in range(num_channels):
            hist = histograms[c][idx]
            avg_hist = avg_histograms[c]
            dist += np.sum((hist - avg_hist) ** 2)  # L2 distance
        distances.append(dist)
    
    ref_idx = np.argmin(distances)
    ref_path = file_paths[ref_idx]
    print(f"Selected reference image: {os.path.basename(ref_path)}")

    # Step 6: Read the reference image
    with rasterio.open(ref_path) as src:
        ref_image = src.read()
        if ref_image.shape[0] != 3:
            raise ValueError(f"Reference image {os.path.basename(ref_path)} has {ref_image.shape[0]} bands, expected 3 (RGB).")

    # Step 7: Create output folder if it doesn't exist
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        print(f"Created output folder: {output_folder}")

    # Step 8: Prepare tasks for parallel processing
    tasks = [
        (
            path,
            os.path.join(output_folder, os.path.basename(path)),
            ref_image,
            dtype
        )
        for path in file_paths
    ]

    # Step 9: Process images in parallel
    print(f"Processing {num_images} images using {num_workers} workers...")
    with Pool(processes=num_workers) as pool:
        results = pool.map(process_image, tasks)
    
    # Step 10: Report results
    for result in results:
        print(f"Processed and saved: {result}" if not result.startswith("Error") else result)

    print("Color harmonization completed.")

if __name__ == "__main__":
    # Prompt for input and output folders
    input_folder = get_valid_folder(
        "Enter the path to the input folder containing TIF files: ",
        must_exist=True
    )
    output_folder = get_valid_folder(
        "Enter the path to the output folder for corrected images: ",
        must_exist=False
    )
    # Adjust num_workers based on system (default 10, max = cpu_count)
    max_workers = os.cpu_count() or 10
    num_workers = min(10, max_workers)
    main(input_folder, output_folder, num_workers)