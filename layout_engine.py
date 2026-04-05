import json
import os
import random
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generate_layout(house_data):
    for attempt in range(3):
        try:
            layout = generate_with_ai(house_data)
            layout = build_walls(layout)
            if validate_layout(layout):
                return layout
        except Exception as e:
            print("AI layout failed:", e)

    print("⚠️ Falling back to basic layout")
    return fallback_layout(house_data)

def build_walls(layout):
    rooms = layout["rooms"]
    walls = []

    for room in rooms:
        x = room["x"]
        y = room["y"]
        w = room["w"]
        h = room["h"]

        walls.append({
            "id": f"{room['name']}_bottom",
            "type": "exterior",
            "x1": x,
            "y1": y,
            "x2": x + w,
            "y2": y,
            "orientation": "horizontal",
            "length": w,
            "rooms": [room["name"]],
            "window_allowed": True,
            "facade": "south"
        })

        walls.append({
            "id": f"{room['name']}_top",
            "type": "exterior",
            "x1": x,
            "y1": y + h,
            "x2": x + w,
            "y2": y + h,
            "orientation": "horizontal",
            "length": w,
            "rooms": [room["name"]],
            "window_allowed": True,
            "facade": "north"
        })

        walls.append({
            "id": f"{room['name']}_left",
            "type": "exterior",
            "x1": x,
            "y1": y,
            "x2": x,
            "y2": y + h,
            "orientation": "vertical",
            "length": h,
            "rooms": [room["name"]],
            "window_allowed": True,
            "facade": "west"
        })

        walls.append({
            "id": f"{room['name']}_right",
            "type": "exterior",
            "x1": x + w,
            "y1": y,
            "x2": x + w,
            "y2": y + h,
            "orientation": "vertical",
            "length": h,
            "rooms": [room["name"]],
            "window_allowed": True,
            "facade": "east"
        })

    layout["walls"] = walls
    return layout

def generate_with_ai(house_data):
    prompt = f"""
Generate a realistic house floor plan.

Constraints:
- rectangular perimeter
- all rooms inside perimeter
- rooms aligned on a grid (no overlaps)
- shared walls only (no gaps)
- exterior walls = 0.2m
- interior walls = 0.1m
- minimize corridor space
- each layout MUST be different

Room requirements:
- Living room: 25–35 m²
- Kitchen: 10–20 m²
- Bedrooms: based on input
- Bathrooms: based on input
- Garage if requested

Zoning:
- living + kitchen together
- bedrooms grouped
- bathrooms near bedrooms

Return JSON ONLY:

{{
  "width": number,
  "height": number,
  "rooms": [
    {{
      "name": "string",
      "type": "living_room | kitchen | bedroom | bathroom | wc | garage | corridor | storage",
      "x": number,
      "y": number,
      "w": number,
      "h": number
    }}
  ]
}}

Input:
{json.dumps(house_data)}
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt
    )

    text = response.output_text.strip()
    text = text.replace("```json", "").replace("```", "").strip()

    return json.loads(text)

def validate_layout(layout):
    rooms = layout.get("rooms", [])

    # Check no overlaps
    for i, r1 in enumerate(rooms):
        for j, r2 in enumerate(rooms):
            if i >= j:
                continue

            if (
                r1["x"] < r2["x"] + r2["w"] and
                r1["x"] + r1["w"] > r2["x"] and
                r1["y"] < r2["y"] + r2["h"] and
                r1["y"] + r1["h"] > r2["y"]
            ):
                return False

    # Check inside perimeter
    width = layout["width"]
    height = layout["height"]

    for r in rooms:
        if r["x"] < 0 or r["y"] < 0:
            return False
        if r["x"] + r["w"] > width:
            return False
        if r["y"] + r["h"] > height:
            return False

    return True

def fallback_layout(house_data):
    rooms = []

    width = 12
    height = 10

    rooms.append({"name": "living_room", "type": "living_room", "x": 0, "y": 0, "w": 6, "h": 5})
    rooms.append({"name": "kitchen", "type": "kitchen", "x": 6, "y": 0, "w": 6, "h": 5})

    for i in range(house_data["bedrooms"]):
        rooms.append({
            "name": f"bedroom_{i+1}",
            "type": "secondary_bedroom",
            "x": i * 3,
            "y": 5,
            "w": 3,
            "h": 3
        })

    return {
        "width": width,
        "height": height,
        "rooms": rooms
    }