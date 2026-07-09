"""macOS and Linux binary builder — packages the entire Python application
and all its dependencies into a single, standalone Unix executable.

    .venv/bin/python tools/package_mac.py

Outputs the compiled binary to:
    dist/theia-player
"""

from __future__ import annotations

import os
import sys
import subprocess
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)

VENV_PIP = REPO / ".venv" / "bin" / "pip"
VENV_PYINSTALLER = REPO / ".venv" / "bin" / "pyinstaller"


def install_pyinstaller() -> None:
    """Ensure PyInstaller is installed in the local virtual environment."""
    print("Checking for PyInstaller in the local virtual environment...")
    if not VENV_PYINSTALLER.exists():
        print("Installing PyInstaller inside the local venv...")
        subprocess.run([str(VENV_PIP), "install", "pyinstaller"], check=True)
    else:
        print("✅ PyInstaller is already available.")


def build_binary() -> None:
    """Execute PyInstaller with optimal settings for a robust, standalone terminal binary."""
    print("\n--- Starting Compilation of Statement-driven Python Binary ---")
    
    # We define PyInstaller CLI arguments to package all local packages
    # and crucial non-code static assets (like Textual's CSS rules).
    cmd = [
        str(VENV_PYINSTALLER),
        "--onefile",                   # Package into a single executable binary
        "--name", "theia-player",       # Name of the output binary
        "--clean",                     # Clean cache before building
        # Include non-code resource files (CSS stylesheets) of Textualize framework
        "--collect-data", "textual",
        # Explicitly collect submodules to prevent missing imports at runtime
        "--collect-submodules", "theiaplayer",
        "--collect-submodules", "ricekit",
        # Point to the app startup script
        "theiaplayer/__main__.py"
    ]
    
    print(f"Running command: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    
    # Verify the output binary exists
    output_bin = REPO / "dist" / "theia-player"
    if output_bin.exists():
        size_mb = output_bin.stat().st_size / (1024 * 1024)
        print(f"\n✅ SUCCESS!Stand-alone executable successfully compiled!")
        print(f"Binary path:  {output_bin}")
        print(f"Binary size:  {size_mb:.2f} MB")
        print("\nHow to distribute:")
        print(f"  Share the '{output_bin.name}' file directly. Users only need to run:")
        print("    ./theia-player")
    else:
        print("❌ Error: PyInstaller completed but output binary was not found.")
        sys.exit(1)


def clean_build_artifacts() -> None:
    """Clean up build/ directory and spec files to keep the workspace pristine."""
    print("\nCleaning up temporary build artifacts...")
    spec_file = REPO / "theia-player.spec"
    build_dir = REPO / "build"
    
    if spec_file.exists():
        spec_file.unlink()
        print("  - Removed spec file.")
    if build_dir.exists():
        shutil.rmtree(build_dir)
        print("  - Removed build directory.")
    print("✅ Workspace is clean.")


def main() -> None:
    try:
        install_pyinstaller()
        build_binary()
        clean_build_artifacts()
    except Exception as e:
        print(f"\n❌ Compilation failed with error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
