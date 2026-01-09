"""
Build script for creating Windows executable
"""
import PyInstaller.__main__
import os
import sys
from pathlib import Path


def build():
    """Build the application"""
    # Get the project root
    project_root = Path(__file__).parent
    src_dir = project_root / "src"
    
    # Ensure we're in the right directory
    os.chdir(project_root)
    
    # PyInstaller arguments
    args = [
        str(src_dir / "main.py"),
        "--name=BacklinkEngine",
        "--onedir",
        "--windowed",
        "--noconfirm",
        
        # Add data files
        f"--add-data={src_dir / 'ui'};ui",
        
        # Hidden imports
        "--hidden-import=PyQt6.QtCharts",
        "--hidden-import=PyQt6.sip",
        "--hidden-import=anthropic",
        "--hidden-import=openai",
        "--hidden-import=httpx",
        "--hidden-import=playwright",
        
        # Collect all
        "--collect-all=playwright",
        "--collect-all=anthropic",
        
        # Exclude unnecessary
        "--exclude-module=matplotlib",
        "--exclude-module=numpy.testing",
        "--exclude-module=scipy",
        "--exclude-module=PIL",
        
        # Output directory
        f"--distpath={project_root / 'dist'}",
        f"--workpath={project_root / 'build'}",
        f"--specpath={project_root}",
    ]
    
    # Add icon if exists
    icon_path = project_root / "resources" / "icons" / "app_icon.ico"
    if icon_path.exists():
        args.append(f"--icon={icon_path}")
    
    print("Building Backlink Strategy Engine...")
    print(f"Source: {src_dir / 'main.py'}")
    print(f"Output: {project_root / 'dist'}")
    
    PyInstaller.__main__.run(args)
    
    print("\nBuild complete!")
    print(f"Executable: {project_root / 'dist' / 'BacklinkEngine' / 'BacklinkEngine.exe'}")


if __name__ == "__main__":
    build()