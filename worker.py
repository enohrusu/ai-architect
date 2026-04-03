import os
import json
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
from blender_runner import run_blender

app = FastAPI()

project_root = os.path.dirname(os.path.abspath(__file__))
outputs_dir = os.path.join(project_root, "outputs")
os.makedirs(outputs_dir, exist_ok=True)


# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Force CORS headers even on static file responses
class AddCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response


app.add_middleware(AddCORSMiddleware)

app.mount("/outputs", StaticFiles(directory=outputs_dir), name="outputs")


class BlenderJobRequest(BaseModel):
    project_id: str
    house_data: dict
    layout_data: dict


@app.get("/")
def home():
    return {"status": "worker running"}


@app.post("/run-blender")
def run_blender_endpoint(data: BlenderJobRequest):
    try:
        project_folder = os.path.join(outputs_dir, data.project_id)
        os.makedirs(project_folder, exist_ok=True)

        house_data_path = os.path.join(project_folder, "house_data.json")
        layout_data_path = os.path.join(project_folder, "layout_data.json")

        with open(house_data_path, "w", encoding="utf-8") as f:
            json.dump(data.house_data, f, indent=2)

        with open(layout_data_path, "w", encoding="utf-8") as f:
            json.dump(data.layout_data, f, indent=2)

        print("🚀 RUNNING BLENDER FOR:", project_folder)

        run_blender(project_folder)

        glb_path = os.path.join(project_folder, "generated_house.glb")
        blend_path = os.path.join(project_folder, "generated_house.blend")

        return {
            "success": True,
            "message": "Blender finished",
            "files": {
                "glb_exists": os.path.exists(glb_path),
                "blend_exists": os.path.exists(blend_path),
                "glb_path": glb_path,
                "blend_path": blend_path,
                "glb_size": os.path.getsize(glb_path) if os.path.exists(glb_path) else 0,
                "blend_size": os.path.getsize(blend_path) if os.path.exists(blend_path) else 0,
            }
        }

    except Exception as e:
        print("❌ BLENDER ERROR:", str(e))
        return {"success": False, "message": str(e)}