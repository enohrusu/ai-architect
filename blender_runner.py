import subprocess
import os


def run_blender(project_folder):
    project_root = os.path.dirname(os.path.abspath(__file__))
    project_folder = os.path.abspath(project_folder)

    blender_path = r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
    script_path = os.path.join(project_root, "blender", "generate_house.py")

    print("\n🚀 RUNNING BLENDER")
    print("PROJECT FOLDER:", project_folder)
    print("BLENDER PATH:", blender_path)
    print("SCRIPT PATH:", script_path)

    # 🔍 Safety checks
    if not os.path.exists(blender_path):
        raise FileNotFoundError(f"Blender not found at: {blender_path}")

    if not os.path.exists(script_path):
        raise FileNotFoundError(f"Script not found at: {script_path}")

    if not os.path.exists(project_folder):
        raise FileNotFoundError(f"Project folder not found: {project_folder}")

    command = [
        blender_path,
        "--background",
        "--python",
        script_path,
        "--",
        project_folder
    ]

    print("COMMAND:", command)

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True
        )

        print("\n--- BLENDER STDOUT ---")
        print(result.stdout)

        print("\n--- BLENDER STDERR ---")
        print(result.stderr)

        if result.returncode != 0:
            raise RuntimeError(f"Blender failed with code {result.returncode}")

        print("\n✅ BLENDER FINISHED SUCCESSFULLY")

    except Exception as e:
        print("\n❌ BLENDER EXECUTION FAILED")
        print(str(e))
        raise