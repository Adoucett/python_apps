import os
import subprocess
from pathlib import Path
import shutil

def strip_alpha_from_tiffs(input_dir, destructive=False):
    input_dir = Path(input_dir).expanduser().resolve()

    if not input_dir.exists():
        print(f"❌ Directory does not exist: {input_dir}")
        return

    tif_files = list(input_dir.rglob("*.tif"))
    print(f"\n🔍 Found {len(tif_files)} .tif files to process in:\n{input_dir}\n")

    if not tif_files:
        print("No .tif files found.")
        return

    for tif in tif_files:
        temp_file = tif.with_stem(tif.stem + "_rgb")

        # Skip if already processed
        if temp_file.exists() and not destructive:
            print(f"⏭ Skipping {tif.name} (fixed version already exists)")
            continue

        cmd = [
            "gdal_translate",
            "-b", "1",
            "-b", "2",
            "-b", "3",
            str(tif),
            str(temp_file)
        ]

        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            if destructive:
                shutil.move(str(temp_file), str(tif))  # overwrite original
                print(f"💣 Overwritten: {tif.name} (destructive mode)")
            else:
                print(f"✔ Fixed: {tif.name} → {temp_file.name}")

        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to process {tif.name}: {e}")

if __name__ == "__main__":
    input_path = input("📂 Enter the full path to the folder containing .tif files: ").strip()
    destructive_input = input("💥 Enable DESTRUCTIVE MODE (overwrite original files)? (y/N): ").strip().lower()
    destructive = destructive_input == "y"

    strip_alpha_from_tiffs(input_path, destructive=destructive)
