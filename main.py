import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from layout_engine import generate_layout
from blender_runner import run_blender

load_dotenv(dotenv_path=".env")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

with open("outputs/house_data.json", "w", encoding="utf-8") as f:
    json.dump(house_data, f, indent=2)

layout_data = generate_layout(house_data)

with open("outputs/layout_data.json", "w", encoding="utf-8") as f:
    json.dump(layout_data, f, indent=2)

print("\nSaved successfully to:")
print("- outputs/house_data.json")
print("- outputs/layout_data.json")

print("\nOpening Blender...")
run_blender()

print("\nDone.")