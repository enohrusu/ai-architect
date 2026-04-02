import os
import json
import requests
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI

BLENDER_WORKER_URL = os.getenv("BLENDER_WORKER_URL")

from auth import create_user, authenticate_user
from database import get_connection, init_db
from layout_engine import generate_layout
from blender_runner import run_blender

load_dotenv(dotenv_path=".env")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MAX_FREE_GENERATIONS = 3

app = FastAPI()
init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("outputs", exist_ok=True)
app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")


class HouseRequest(BaseModel):
    prompt: str
    user_id: int | None = None


class UserRequest(BaseModel):
    email: str
    password: str


def parse_house_prompt(user_prompt: str):
    response = client.responses.create(
        model="gpt-4.1-mini",
        input=f"""
Convert this house description into JSON.

Return ONLY JSON like this:
{{
  "style": "string",
  "bedrooms": number,
  "bathrooms": number,
  "area_m2": number,
  "floors": number,
  "garage": true_or_false
}}

Description: {user_prompt}
"""
    )

    raw_text = response.output_text.strip()
    raw_text = raw_text.replace("```json", "").replace("```", "").strip()

    return json.loads(raw_text), response.usage


def create_project_id():
    return "project_" + datetime.now().strftime("%Y%m%d_%H%M%S")


@app.get("/")
def home():
    return {"message": "AI Architect API is running"}


@app.post("/signup")
def signup(request: UserRequest):
    success, message = create_user(request.email, request.password)

    if success:
        return {"success": True, "message": message}

    return {"success": False, "message": message}


@app.post("/login")
def login(request: UserRequest):
    user = authenticate_user(request.email, request.password)

    if not user:
        return {"success": False, "message": "Invalid email or password"}

    return {
        "success": True,
        "message": "Login successful",
        "user": user
    }


@app.post("/generate-house")
def generate_house(request: HouseRequest):
    user_id = request.user_id or 0

    generation_count = 0
    is_pro = False

    if user_id:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT is_pro, generation_count FROM users WHERE id = %s",
            (user_id,)
        )
        user_row = cursor.fetchone()

        if not user_row:
            cursor.close()
            conn.close()
            raise HTTPException(status_code=404, detail="User not found")

        is_pro, generation_count = user_row

        if not is_pro and generation_count >= MAX_FREE_GENERATIONS:
            cursor.close()
            conn.close()
            raise HTTPException(status_code=403, detail="Free limit reached. Upgrade to continue.")

        cursor.close()
        conn.close()

    project_id = create_project_id()
    project_folder = os.path.join("outputs", project_id)
    os.makedirs(project_folder, exist_ok=True)

    house_data, usage = parse_house_prompt(request.prompt)

    house_data_path = os.path.join(project_folder, "house_data.json")
    with open(house_data_path, "w", encoding="utf-8") as f:
        json.dump(house_data, f, indent=2)

    layout_data = generate_layout(house_data)

    layout_data_path = os.path.join(project_folder, "layout_data.json")
    with open(layout_data_path, "w", encoding="utf-8") as f:
        json.dump(layout_data, f, indent=2)
   
    blender_result = {"success": False, "message": "Blender worker not configured"}
    worker_glb_url = None

    if BLENDER_WORKER_URL:
        print("➡️ Calling Blender worker:", BLENDER_WORKER_URL)

        try:
            response = requests.post(
                f"{BLENDER_WORKER_URL}/run-blender",
                json={
                    "project_id": project_id,
                    "house_data": house_data,
                    "layout_data": layout_data
                },
                timeout=120
            )

            print("✅ Worker status:", response.status_code)

            try:
                blender_result = response.json()
            except Exception:
                blender_result = {
                    "success": False,
                    "message": f"Invalid worker response: {response.text}"
                }

            if blender_result.get("success"):
                worker_glb_url = f"{BLENDER_WORKER_URL}/outputs/{project_id}/generated_house.glb"

        except Exception as e:
            print("❌ Blender error:", str(e))
            blender_result = {"success": False, "message": str(e)}
    else:
        print("❌ BLENDER_WORKER_URL not set")


    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO projects (user_id, project_id, prompt, house_data, layout_data) VALUES (%s, %s, %s, %s, %s)",
        (
            user_id,
            project_id,
            request.prompt,
            json.dumps(house_data),
            json.dumps(layout_data)
        )
    )

    if user_id:
        cursor.execute(
            "UPDATE users SET generation_count = generation_count + 1 WHERE id = %s",
            (user_id,)
        )
        generation_count += 1

    conn.commit()
    cursor.close()
    conn.close()

    return {
        "success": True,
        "project_id": project_id,
        "project_folder": project_folder,
        "house_data": house_data,
        "layout_data": layout_data,
        "blender_result": blender_result,
        "usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens
        },
        "user_usage": {
            "generation_count": generation_count,
            "max_free_generations": MAX_FREE_GENERATIONS
        },
        "files": {
    "house_data_json": f"https://ai-architect-ow3t.onrender.com/outputs/{project_id}/house_data.json",
    "layout_data_json": f"https://ai-architect-ow3t.onrender.com/outputs/{project_id}/layout_data.json",
    "glb_file": worker_glb_url
}
    }

@app.get("/my-projects/{user_id}")
def get_user_projects(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT project_id, prompt, house_data, layout_data, created_at FROM projects WHERE user_id = %s ORDER BY created_at DESC",
        (user_id,)
    )

    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    projects = []
    for row in rows:
        projects.append({
            "project_id": row[0],
            "prompt": row[1],
            "house_data": json.loads(row[2]) if row[2] else None,
            "layout_data": json.loads(row[3]) if row[3] else None,
            "created_at": str(row[4])
        })

    return {"projects": projects}