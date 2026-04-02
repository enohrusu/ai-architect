import subprocess
import os


def run_blender(project_folder):
    project_root = os.path.dirname(os.path.abspath(__file__))
    project_folder = os.path.abspath(project_folder)

    blender_path = r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
    script_path = os.path.join(project_root, "blender", "generate_house.py")

    command = [
        blender_path,
        "--background",
        "--python",
        script_path,
        "--",
        project_folder
    ]

    subprocess.run(command, check=True)