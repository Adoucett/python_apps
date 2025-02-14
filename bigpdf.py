#!/usr/bin/env python3
import argparse
import concurrent.futures
import os
import subprocess
import sys
import tempfile

import fitz  # PyMuPDF
from PyPDF2 import PdfMerger

def mb_to_bytes(mb):
    """Convert megabytes to bytes."""
    return mb * 1024 * 1024

def compress_page(input_page, output_page, quality):
    """
    Compress a single-page PDF using Ghostscript with downsampling parameters.
    
    quality: dict with keys:
       - pdf_setting: e.g. "/ebook" or "/screen"
       - color_res: target dpi for color images
       - gray_res: target dpi for grayscale images
       - mono_res: target dpi for monochrome images
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
        f"-sOutputFile={output_page}",
        input_page
    ]
    try:
        subprocess.run(gs_command, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error: Ghostscript failed on {input_page} with error: {e}")
        raise
    except FileNotFoundError:
        print("Error: Ghostscript (gs) is not installed or not found in PATH.")
        raise

def process_page(page_index, input_file, quality, temp_dir):
    """
    Extract a single page from the PDF, compress it with Ghostscript, and return the path to the compressed page.
    """
    # Open the source PDF and extract the page
    doc = fitz.open(input_file)
    page = doc.load_page(page_index)
    single_page_pdf = os.path.join(temp_dir, f"page_{page_index}.pdf")
    # Create a new PDF containing just this page.
    single_doc = fitz.open()  # new empty PDF
    single_doc.insert_pdf(doc, from_page=page_index, to_page=page_index)
    single_doc.save(single_page_pdf)
    single_doc.close()
    doc.close()

    # Define output filename for the compressed page
    compressed_pdf = os.path.join(temp_dir, f"page_{page_index}_compressed.pdf")
    compress_page(single_page_pdf, compressed_pdf, quality)
    return compressed_pdf

def merge_pages(compressed_files, output_file):
    """
    Merge a list of single-page PDFs into one PDF.
    """
    merger = PdfMerger()
    # Ensure pages are in the correct order based on the page index in the filename.
    for pdf in sorted(compressed_files, key=lambda f: int(os.path.basename(f).split('_')[1])):
        merger.append(pdf)
    merger.write(output_file)
    merger.close()

def run_compression(input_file, output_file, quality, max_size_bytes):
    """
    Process each page in parallel, merge the compressed pages, and check file size.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        # Determine number of pages in the source PDF.
        doc = fitz.open(input_file)
        num_pages = doc.page_count
        doc.close()

        print(f"Processing {num_pages} pages in parallel...")
        compressed_files = []
        with concurrent.futures.ProcessPoolExecutor() as executor:
            # Schedule each page for processing.
            futures = {
                executor.submit(process_page, i, input_file, quality, temp_dir): i
                for i in range(num_pages)
            }
            for future in concurrent.futures.as_completed(futures):
                page_num = futures[future]
                try:
                    compressed_file = future.result()
                    compressed_files.append(compressed_file)
                    print(f"Page {page_num} compressed.")
                except Exception as exc:
                    print(f"Page {page_num} generated an exception: {exc}")
                    sys.exit(1)

        # Merge all compressed pages.
        merge_pages(compressed_files, output_file)
        final_size = os.path.getsize(output_file)
        print(f"Final merged file size: {final_size} bytes")
        return final_size

def main():
    parser = argparse.ArgumentParser(
        description="Compress a PDF in parallel by processing each page concurrently."
    )
    parser.add_argument("input_file", help="Path to the input PDF file")
    parser.add_argument("output_file", nargs="?", default="output_compressed.pdf",
                        help="Path to the output PDF file (default: output_compressed.pdf)")
    parser.add_argument("--max-size-mb", type=int, default=8,
                        help="Maximum allowed file size in MB (default: 8 MB)")
    args = parser.parse_args()
    max_size_bytes = mb_to_bytes(args.max_size_mb)

    # List of quality settings to try in order.
    quality_settings = [
        {"pdf_setting": "/ebook", "color_res": 150, "gray_res": 150, "mono_res": 150},
        {"pdf_setting": "/screen", "color_res": 72, "gray_res": 72, "mono_res": 72},
    ]

    for quality in quality_settings:
        print(f"\nTrying compression with quality settings: {quality}")
        final_size = run_compression(args.input_file, args.output_file, quality, max_size_bytes)
        if final_size <= max_size_bytes:
            print("Success: Compressed PDF is under the desired file size.")
            return
        else:
            print("Resulting file is still too large. Trying a lower quality setting...")
    print("Warning: Could not compress the PDF below the desired file size with the available quality settings.")
    sys.exit(1)

if __name__ == "__main__":
    main()
