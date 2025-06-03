import os
import sys
import numpy as np
import rasterio
from rasterio.enums import Photometric # For JPEG
from skimage.exposure import match_histograms
# from skimage.color import rgb2hsv, hsv2rgb, rgb2lab, lab2rgb # Imports depend on process_image
from multiprocessing import Pool, cpu_count
from tqdm import tqdm
import logging
import shutil # For copying reference image if needed

# Suppress NotGeoreferencedWarning from rasterio
logging.getLogger('rasterio').setLevel(logging.ERROR)

# --- Placeholder for functions you mentioned as unchanged ---
def get_valid_folder(prompt, must_exist=True):
    """Placeholder: Gets and validates a folder path from user input."""
    while True:
        folder_path = input(prompt).strip()
        if not folder_path:
            print("Path cannot be empty.")
            continue
        if must_exist and not os.path.isdir(folder_path):
            print(f"Folder not found: {folder_path}")
            continue
        # For output folder, os.makedirs in main will handle creation
        return folder_path

def get_image_files(folder_path):
    """
    Placeholder: Lists all TIF, TIFF, PNG files in the given folder.
    """
    supported_extensions = ('.tif', '.tiff', '.png') # Input can still be TIF or PNG
    return [f for f in os.listdir(folder_path)
            if f.lower().endswith(supported_extensions)]

def compute_histogram(image_data, channel, bins, hist_min, hist_max):
    """Placeholder: Computes histogram for a given channel."""
    # Actual implementation: hist, _ = np.histogram(image_data[channel, ...].ravel(), bins=bins, range=(hist_min, hist_max))
    # print(f"Placeholder: Computing histogram for channel {channel}")
    return np.zeros(bins)

def select_reference_image(file_paths, histograms, num_channels, bins, hist_range):
    """Placeholder: Selects a reference image."""
    # print(f"Placeholder: Selecting reference image. Consider a more robust strategy.")
    if not file_paths:
        raise ValueError("No image files provided to select a reference from.")
    return 0, file_paths[0]

def apply_color_grading(image_data, params):
    """Placeholder for applying color grading adjustments."""
    # This function would modify image_data based on hue_shift, sat_scale, val_scale
    # For example, convert to HSV, adjust channels, convert back to RGB
    # For simplicity, this placeholder just returns the image as is.
    # print(f"Placeholder: Applying color grading with params: {params}")
    return image_data

def scale_to_uint8(image_data_float, original_max_val):
    """Scales float image data (0-1 range typically) to uint8 (0-255)."""
    # Or if image_data is uint16, scale from original_max_val (e.g., 65535)
    if image_data_float.dtype == np.uint16:
        scaled_data = (image_data_float / original_max_val * 255)
    elif image_data_float.dtype == np.float32 or image_data_float.dtype == np.float64:
         # Assuming float data is already in a sensible range (e.g. 0-1 or 0-255)
         # If it was 0-1 from skimage operations:
        if image_data_float.max() <= 1.0 and image_data_float.min() >=0.0:
            scaled_data = image_data_float * 255.0
        else: # Assume it might be other float ranges, clip and scale
            scaled_data = np.clip(image_data_float, 0, original_max_val) / original_max_val * 255.0
    else: # Already uint8 or other, just ensure it's in range.
        scaled_data = image_data_float

    return np.clip(scaled_data, 0, 255).astype(np.uint8)


def process_image(args):
    """
    Placeholder: Processes a single image, including format-specific saving.
    """
    (image_path, output_path, ref_image_data, input_dtype,
     color_space_method, match_independent, color_grading_params,
     output_format, jpeg_quality) = args

    try:
        with rasterio.open(image_path) as src:
            src_profile = src.profile.copy() # Get profile of the source image
            img_data = src.read() # Reads as (bands, height, width)

            # Ensure consistent band count with reference for matching
            if img_data.shape[0] != ref_image_data.shape[0]:
                # This case should ideally be handled before even attempting to process
                # or by only matching common bands. For simplicity, we assume they match here.
                # Or, one might select only the first min(img_data.shape[0], ref_image_data.shape[0]) bands.
                # For Planet Labs, if input is 4-band and reference is 3-band (or vice-versa),
                # a strategy is needed (e.g. match only RGB).
                # For this placeholder, we'll assume band counts are compatible for matching.
                pass


        # 1. Simulate Histogram Matching (skimage.exposure.match_histograms)
        # Ensure data is in a format suitable for match_histograms (e.g. C, H, W or H, W, C)
        # match_histograms expects image and reference to have same number of channels if multichannel=True (older skimage)
        # or uses channel_axis for newer skimage.
        # For Planet Labs, if using 4-band (RGBNir), decide if you match all or just RGB.
        # Assuming ref_image_data and img_data are (bands, height, width)
        # And that match_histograms is called appropriately.
        # If img_data could have an alpha channel but ref_image doesn't, handle this.
        # e.g., img_to_match = img_data[:ref_image_data.shape[0], :, :]
        
        # This is a very simplified placeholder for matching:
        # matched_image = img_data # In reality: match_histograms(img_data, ref_image_data, channel_axis=0)
        # Let's assume match_histograms preserves the original data type of `img_data`
        
        # If skimage functions converted to float (0-1 range), store max value for scaling back
        original_max = 1.0 if img_data.dtype in [np.float32, np.float64] and img_data.max() <=1.0 else (255 if input_dtype == np.uint8 else 65535)

        # Placeholder for matching - this would be your skimage.exposure.match_histograms call
        # Ensure that 'img_data' and 'ref_image_data' are correctly prepared for this function
        # e.g., if ref_image_data has fewer bands, select corresponding bands from img_data
        num_bands_to_match = min(img_data.shape[0], ref_image_data.shape[0])
        img_to_match = img_data[:num_bands_to_match, :, :]
        ref_to_match = ref_image_data[:num_bands_to_match, :, :]

        # skimage.exposure.match_histograms returns a float array [0,1] if input is integer
        # or preserves float range if input is float. We need to handle this.
        matched_image_float = match_histograms(img_to_match, ref_to_match, channel_axis=0)


        # 2. Simulate Color Grading
        # graded_image_float = apply_color_grading(matched_image_float, color_grading_params)
        graded_image_float = matched_image_float # Placeholder returns as is

        # 3. Prepare data for saving based on output format
        final_profile = src_profile # Start with source profile and modify
        final_profile['count'] = graded_image_float.shape[0] # Number of bands in matched image


        if output_format == 'jpg':
            # JPEG is typically 3-band (RGB) and 8-bit.
            if graded_image_float.shape[0] == 4: # If RGBA, take RGB
                final_image_data = graded_image_float[:3, :, :]
                final_profile['count'] = 3
            elif graded_image_float.shape[0] == 1: # If grayscale
                # Need to handle grayscale JPEG correctly. For now, assume we are working with RGB.
                 final_image_data = graded_image_float
            else:
                final_image_data = graded_image_float

            # Scale to uint8
            final_image_data = scale_to_uint8(final_image_data, original_max_val=original_max)
            final_profile['dtype'] = rasterio.uint8
            final_profile['driver'] = 'JPEG'
            final_profile['photometric'] = 'RGB' # or 'YCBCR'
            # Remove compression tags not applicable to JPEG or set JPEG specific ones
            for key in ['compress', 'predictor', 'photometric', 'nodata', 'blockxsize', 'blockysize', 'tiled']:
                final_profile.pop(key, None)
            # No specific creation options needed for quality here for basic rasterio save,
            # but can be passed to dst.write with some drivers/versions or as creation options

        elif output_format == 'png':
            final_profile['driver'] = 'PNG'
            # PNG can be uint8 or uint16. Preserve input bit depth if possible.
            if input_dtype == np.uint16:
                # Scale float [0,1] back to uint16 [0, 65535]
                final_image_data = (np.clip(graded_image_float, 0, 1) * 65535.0).astype(np.uint16)
                final_profile['dtype'] = rasterio.uint16
            else: # uint8
                final_image_data = scale_to_uint8(graded_image_float, original_max_val=original_max)
                final_profile['dtype'] = rasterio.uint8
            # Remove GeoTIFF specific tags
            for key in ['compress', 'predictor', 'blockxsize', 'blockysize', 'tiled']:
                 final_profile.pop(key, None)


        elif output_format == 'tif': # GeoTIFF
            final_profile['driver'] = 'GTiff'
            # Preserve input bit depth if possible, or target_dtype
            if input_dtype == np.uint16:
                final_image_data = (np.clip(graded_image_float, 0, 1) * 65535.0).astype(np.uint16)
                final_profile['dtype'] = rasterio.uint16
                final_profile.setdefault('compress', 'lzw') # Sensible default for TIFF
                final_profile.setdefault('predictor', 2)
            else: # uint8
                final_image_data = scale_to_uint8(graded_image_float, original_max_val=original_max)
                final_profile['dtype'] = rasterio.uint8
                final_profile.setdefault('compress', 'deflate')
        else:
            return False, f"Unsupported output format '{output_format}' for {os.path.basename(image_path)}"

        # Ensure count matches data
        final_profile['count'] = final_image_data.shape[0]

        # Clean up nodata if not appropriate for the output format or if it's problematic
        if output_format == 'jpg' and 'nodata' in final_profile:
            del final_profile['nodata']

        # Write the processed image
        with rasterio.open(output_path, 'w', **final_profile) as dst:
            if output_format == 'jpg':
                # For JPEG, some rasterio versions/GDAL need specific write params
                # This is a common way to set quality for JPEG driver
                dst.write(final_image_data, GDX_バンド書き込み順序='RGB', JPEG_QUALITY=jpeg_quality)
            else:
                dst.write(final_image_data)

        return True, output_path

    except Exception as e:
        return False, f"Error processing {os.path.basename(image_path)}: {str(e)} (Line: {e.__traceback__.tb_lineno})"
# --- End of placeholders ---


DEFAULT_COLOR_GRADING = {
    'hue_shift': 0.0, # Usually safer to keep hue_shift at 0 unless specifically needed
    'sat_scale': 1.0,
    'val_scale': 1.0
}

def main(input_folder, output_folder, output_format='tif', jpeg_quality=90,
         num_workers=None, verbose=False, color_grading_params=None):
    """
    Main function for harmonizing a series of images.
    """
    if color_grading_params is None:
        color_grading_params = DEFAULT_COLOR_GRADING

    output_format = output_format.lower().replace('.', '') # Normalize (e.g. .jpg -> jpg)
    valid_formats = ['tif', 'tiff', 'png', 'jpg', 'jpeg']
    if output_format not in valid_formats:
        logging.error(f"Unsupported output format: {output_format}. Choose from {valid_formats}.")
        return

    if output_format == "jpeg": output_format = "jpg" # standardize
    if output_format == "tiff": output_format = "tif" # standardize


    log_file_path = os.path.join(output_folder, 'harmonization_log.txt')
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        print(f"Created output folder: {output_folder}")

    logging.basicConfig(
        filename=log_file_path,
        level=logging.DEBUG if verbose else logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        force=True
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    if not any(isinstance(h, logging.StreamHandler) for h in logging.getLogger().handlers):
        logging.getLogger().addHandler(console_handler)


    logging.info(f"Starting image harmonization process...")
    logging.info(f"Input folder: {input_folder}")
    logging.info(f"Output folder: {output_folder}")
    logging.info(f"Output format: {output_format.upper()}")
    if output_format == 'jpg':
        logging.info(f"JPEG Quality: {jpeg_quality}")


    image_filenames = get_image_files(input_folder)
    if not image_filenames:
        logging.error(f"No supported image files (TIF, PNG) found in {input_folder}.")
        return

    file_paths = [os.path.join(input_folder, f) for f in image_filenames]
    num_images = len(file_paths)
    logging.info(f"Found {num_images} image files for processing.")


    logging.info("Validating first image to determine properties...")
    input_dtype = None # Store the predominant input data type
    initial_num_channels = None # Store band count from first image
    try:
        with rasterio.open(file_paths[0]) as src:
            sample_image = src.read()
            initial_num_channels = sample_image.shape[0]

            if initial_num_channels not in [1, 3, 4]: # Grayscale, RGB, RGBA/RGBNir
                logging.warning(
                    f"First image {os.path.basename(file_paths[0])} has {initial_num_channels} bands. "
                    f"Expected 1 (Grayscale), 3 (RGB) or 4 (e.g. RGBA/RGBNir). Processing will attempt to continue."
                )
            else:
                logging.info(f"Images are assumed to be {initial_num_channels}-band (e.g., Grayscale, RGB or RGBNir).")

            input_dtype = sample_image.dtype
            if input_dtype == np.uint8:
                bins = 256
                hist_range = (0, 255)
            elif input_dtype == np.uint16:
                bins = 1024
                hist_range = (0, 65535)
            else:
                # For other float types from rasterio, histogram matching often works on the direct values.
                # However, the script is geared towards uint8/uint16.
                # If supporting float directly, hist_range might need to be data-dependent.
                raise ValueError(f"Unsupported input data type for explicit histogram binning: {input_dtype}. Expected uint8 or uint16.")
        logging.info(f"Predominant input data type: {input_dtype}, Histogram bins: {bins}, Histogram range: {hist_range}")
    except Exception as e:
        logging.error(f"Failed to validate first image: {e}")
        return


    logging.info("Computing histograms for all images (for reference selection)...")
    histograms_by_channel = {c: [] for c in range(initial_num_channels)} # Use initial_num_channels
    valid_file_paths_for_hist = [] # Store paths for which histograms were successfully computed

    for path in tqdm(file_paths, desc="Computing histograms", disable=not verbose, unit="image"):
        try:
            with rasterio.open(path) as src:
                image = src.read()
                # Only compute hist for common bands if image has more than reference
                # For simplicity, assume consistency for now or that select_reference_image handles it.
                # We use initial_num_channels as the basis.
                current_bands = image.shape[0]
                if current_bands < initial_num_channels:
                    logging.warning(f"Image {os.path.basename(path)} has {current_bands} bands, fewer than "
                                    f"reference type ({initial_num_channels}). Skipping its histogram.")
                    # Add None for each channel to maintain structure, or handle this in select_reference_image
                    for c_idx in range(initial_num_channels):
                        histograms_by_channel[c_idx].append(None)
                    continue

                for c in range(initial_num_channels): # Compute for the number of channels determined initially
                    hist = compute_histogram(image, c, bins, *hist_range)
                    histograms_by_channel[c].append(hist)
                valid_file_paths_for_hist.append(path) # Add path if hist computed
            if verbose:
                logging.debug(f"Computed histogram for {os.path.basename(path)}")
        except Exception as e:
            logging.error(f"Error computing histogram for {os.path.basename(path)}: {e}")
            for c_idx in range(initial_num_channels):
                histograms_by_channel[c_idx].append(None)

    if not valid_file_paths_for_hist:
        logging.error("No valid histograms could be computed. Cannot select a reference image.")
        return

    logging.info("Selecting reference image...")
    try:
        # Pass only valid paths and their corresponding histograms to select_reference_image
        # This requires select_reference_image to be robust or data to be filtered.
        # For now, we pass all file_paths, but select_reference_image should use histograms_by_channel
        # and potentially ignore images where histograms are None.
        ref_idx, ref_path = select_reference_image(file_paths, histograms_by_channel, initial_num_channels, bins, hist_range)
        logging.info(f"Selected reference image: {os.path.basename(ref_path)}")
    except Exception as e:
        logging.error(f"Could not select reference image: {e}. Exiting.")
        return


    logging.info("Reading reference image data...")
    try:
        with rasterio.open(ref_path) as src:
            ref_image_data_full = src.read()
            # Reference image should match the initial channel count, or take common subset
            ref_image_data = ref_image_data_full[:initial_num_channels, :, :]
            if ref_image_data.shape[0] != initial_num_channels:
                 raise ValueError(f"Reference image {os.path.basename(ref_path)} after band selection has "
                                 f"{ref_image_data.shape[0]} bands, expected {initial_num_channels}.")
        logging.info(f"Reference image data loaded ({ref_image_data.shape[0]} bands).")
    except Exception as e:
        logging.error(f"Failed to read reference image {ref_path}: {e}")
        return

    tasks = []
    for path in file_paths:
        base, _ = os.path.splitext(os.path.basename(path))
        output_filename = f"{base}.{output_format}"
        output_path = os.path.join(output_folder, output_filename)

        # If the current image is the reference image, option to copy directly or still process
        if path == ref_path and output_format == 'tif': # Assuming TIF reference is fine as is
            try:
                # We need to ensure the reference also has the target bit depth if not TIF
                # For simplicity now, if it's the ref and output is TIF, copy. Otherwise process.
                # More robust: process reference image too if output is not TIF or if color grading is active.
                logging.info(f"Copying reference image {os.path.basename(path)} to {output_path} as it is the reference.")
                shutil.copy(path, output_path)
                continue # Skip adding to processing tasks
            except Exception as e:
                logging.warning(f"Could not copy reference image {path}: {e}. It will be processed instead.")


        tasks.append((
            path,
            output_path,
            ref_image_data,
            input_dtype, # Original input dtype, process_image handles scaling based on output_format
            'rgb_independent', # Placeholder for color space method
            True,              # Placeholder for match_independent
            color_grading_params,
            output_format,
            jpeg_quality
        ))


    batch_size = 50
    actual_num_workers = cpu_count() if num_workers is None else num_workers
    actual_num_workers = min(actual_num_workers, os.cpu_count() or 1)
    if not tasks:
        logging.info("No images to process after preparing tasks (e.g., reference image was the only one).")
    else:
        logging.info(f"Processing {len(tasks)} images using {actual_num_workers} workers in batches of up to {batch_size}...")
        with Pool(processes=actual_num_workers) as pool:
            for i in range(0, len(tasks), batch_size):
                batch_tasks = tasks[i:i + batch_size]
                current_batch_num = (i // batch_size) + 1
                logging.info(f"Starting batch {current_batch_num} ({len(batch_tasks)} images)...")

                results = []
                for result in tqdm(pool.imap_unordered(process_image, batch_tasks),
                                   total=len(batch_tasks),
                                   desc=f"Batch {current_batch_num}",
                                   disable=not verbose,
                                   unit="image"):
                    results.append(result)

                for success, message_or_path in results:
                    if success:
                        logging.info(f"Successfully processed and saved: {os.path.basename(message_or_path)}")
                    else:
                        logging.error(message_or_path)
                sys.stdout.flush()

    logging.info("Color harmonization completed.")


if __name__ == "__main__":
    input_f = get_valid_folder(
        "Enter the path to the input folder containing TIF/PNG files: ",
        must_exist=True
    )
    output_f = get_valid_folder(
        "Enter the path to the output folder for corrected images: ",
        must_exist=False
    )

    while True:
        out_format = input("Enter desired output format (tif, png, jpg): ").strip().lower()
        if out_format in ['tif', 'tiff', 'png', 'jpg', 'jpeg']:
            if out_format == 'jpeg': out_format = 'jpg'
            if out_format == 'tiff': out_format = 'tif'
            break
        print("Invalid format. Please choose 'tif', 'png', or 'jpg'.")

    jpeg_q = 90
    if out_format == 'jpg':
        while True:
            try:
                jpeg_q_str = input("Enter JPEG quality (1-100, default 90): ").strip()
                if not jpeg_q_str:
                    jpeg_q = 90
                    break
                jpeg_q = int(jpeg_q_str)
                if 1 <= jpeg_q <= 100:
                    break
                print("JPEG quality must be between 1 and 100.")
            except ValueError:
                print("Invalid input for JPEG quality.")

    verbose_logging = input("Enable verbose logging? (y/n): ").strip().lower() == 'y'

    max_sys_workers = os.cpu_count() or 4
    default_workers = min(10, max_sys_workers)
    try:
        num_w_str = input(f"Enter number of worker processes (default: {default_workers}, max: {max_sys_workers}): ").strip()
        num_w = int(num_w_str) if num_w_str else default_workers
        num_w = max(1, min(num_w, max_sys_workers))
    except ValueError:
        print(f"Invalid number for workers, using default: {default_workers}")
        num_w = default_workers

    custom_grading_params = DEFAULT_COLOR_GRADING.copy()

    main(input_f, output_f, output_format=out_format, jpeg_quality=jpeg_q,
         num_workers=num_w, verbose=verbose_logging,
         color_grading_params=custom_grading_params)