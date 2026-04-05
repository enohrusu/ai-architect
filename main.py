import os
import json
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
from layout_engine import generate_layout
from blender_runner import run_blender

load_dotenv(dotenv_path=".env")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def create_project_id():
    return "project_" + datetime.now().strftime("%Y%m%d_%H%M%S")


user_prompt = input("Describe the house: ")

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

house_data = json.loads(raw_text)

os.makedirs("outputs", exist_ok=True)

project_id = create_project_id()
project_folder = os.path.join("outputs", project_id)
os.makedirs(project_folder, exist_ok=True)

house_data_path = os.path.join(project_folder, "house_data.json")
with open(house_data_path, "w", encoding="utf-8") as f:
    json.dump(house_data, f, indent=2)

layout_data = generate_layout(house_data)

layout_data_path = os.path.join(project_folder, "layout_data.json")
with open(layout_data_path, "w", encoding="utf-8") as f:
    json.dump(layout_data, f, indent=2)

print("\nSaved successfully to:")
print(f"- {house_data_path}")
print(f"- {layout_data_path}")

print("\nOpening Blender...")
run_blender(project_folder)

print("\nDone.")
print(f"Project folder: {project_folder}")