#!/usr/bin/env python3
import argparse
import subprocess
import os
import sys

def mb_to_bytes(mb):
    """Convert megabytes to bytes."""
    return mb * 1024 * 1024

def compress_pdf(input_file, output_file, quality):
    """
    Compress the PDF using Ghostscript with custom downsampling parameters.
    
    quality: a dictionary with keys:
        - pdf_setting: one of Ghostscript's PDF quality presets (e.g. /ebook, /screen)
        - color_res: target resolution (dpi) for color images
        - gray_res: target resolution (dpi) for grayscale images
        - mono_res: target resolution (dpi) for monochrome images
    """
    gs_command = [
        "gs",  # Ensure Ghostscript is installed and in your PATH.
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        f"-dPDFSETTINGS={quality['pdf_setting']}",
        # Downsampling parameters for color images:
        "-dDownsampleColorImages=true",
        "-dColorImageDownsampleType=/Bicubic",
        f"-dColorImageResolution={quality['color_res']}",
        # Downsampling parameters for grayscale images:
        "-dDownsampleGrayImages=true",
        "-dGrayImageDownsampleType=/Bicubic",
        f"-dGrayImageResolution={quality['gray_res']}",
        # Downsampling parameters for monochrome images:
        "-dDownsampleMonoImages=true",
        "-dMonoImageDownsampleType=/Bicubic",
        f"-dMonoImageResolution={quality['mono_res']}",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        f"-sOutputFile={output_file}",
        input_file
    ]
    try:
        subprocess.run(gs_command, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error: Ghostscript failed with error: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print("Error: Ghostscript (gs) is not installed or not found in PATH.")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description="Compress a PDF by downsampling high-res images to keep the file size under a specified limit."
    )
    parser.add_argument("input_file", help="Path to the input PDF file")
    parser.add_argument("output_file", nargs="?", default="output_compressed.pdf",
                        help="Path to the output PDF file (default: output_compressed.pdf)")
    parser.add_argument("--max-size-mb", type=int, default=8,
                        help="Maximum allowed file size in MB (default: 8 MB)")
    args = parser.parse_args()

    max_size = mb_to_bytes(args.max_size_mb)

    # Define a list of quality settings to try.
    # Each setting includes a PDFSETTINGS preset and target resolutions for images.
    quality_settings = [
        {"pdf_setting": "/ebook", "color_res": 150, "gray_res": 150, "mono_res": 150},
        {"pdf_setting": "/screen", "color_res": 72, "gray_res": 72, "mono_res": 72},
    ]

    for quality in quality_settings:
        print(f"Trying compression with quality settings: {quality}")
        compress_pdf(args.input_file, args.output_file, quality)
        try:
            size = os.path.getsize(args.output_file)
        except OSError as e:
            print(f"Error reading output file: {e}")
            sys.exit(1)
        print(f"Resulting file size: {size} bytes")
        if size <= max_size:
            print("Success: Compressed PDF is under the desired file size.")
            break
        else:
            print("Compressed file is still too large. Trying a lower quality setting...\n")
    else:
        print("Warning: Could not compress the PDF below the desired file size "
              "with the available quality settings.")
        sys.exit(1)

if __name__ == "__main__":
    main()
