import subprocess
import os

def run_blender(project_folder):
    blender_path = r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
    script_path = os.path.join("blender", "generate_house.py")

    command = [
        blender_path,
        "--background",
        "--python",
        script_path,
        "--",
        project_folder
    ]

    subprocess.run(command, check=True)