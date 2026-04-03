import json
import math
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

GRID = 0.5  # 50 cm grid
INTERIOR_WALL_THICKNESS = 0.10
EXTERIOR_WALL_THICKNESS = 0.20


def snap(value, step=GRID):
    return round(value / step) * step


def clamp(value, min_v, max_v):
    return max(min_v, min(value, max_v))


def get_room_rules():
    return {
        "living_room": {"min": 20, "ideal_min": 25, "ideal_max": 35, "max": 999},
        "kitchen": {"min": 8, "ideal_min": 12, "ideal_max": 20, "max": 30},
        "master_bedroom": {"min": 12, "ideal_min": 14, "ideal_max": 18, "max": 25},
        "secondary_bedroom": {"min": 9, "ideal_min": 10, "ideal_max": 12, "max": 16},
        "bathroom": {"min": 4, "ideal_min": 5, "ideal_max": 8, "max": 12},
        "wc": {"min": 1.2, "ideal_min": 1.5, "ideal_max": 2, "max": 3},
        "laundry": {"min": 3, "ideal_min": 4, "ideal_max": 6, "max": 10},
        "storage": {"min": 2, "ideal_min": 4, "ideal_max": 6, "max": 10},
        "garage": {"min": 15, "ideal_min": 18, "ideal_max": 20, "max": 25},
        "corridor": {"min": 3, "ideal_min": 4, "ideal_max": 8, "max": 20},
    }


def choose_area(room_type, fallback_area):
    rules = get_room_rules().get(room_type)
    if not rules:
        return snap(max(4, fallback_area))

    if rules["max"] == 999:
        return snap(max(rules["ideal_min"], fallback_area))

    area = clamp(fallback_area, rules["min"], rules["max"])
    return snap(area)


def estimate_house_rectangle(total_area):
    # compact rectangle, snapped to grid
    width = math.sqrt(total_area * 1.2)
    depth = total_area / width

    width = snap(width)
    depth = snap(depth)

    # keep reasonable proportions
    if width < depth:
        width, depth = depth, width

    return width, depth


def build_room_program(house_data):
    bedrooms = int(house_data.get("bedrooms", 3))
    bathrooms = int(house_data.get("bathrooms", 2))
    garage = bool(house_data.get("garage", False))
    total_area = float(house_data.get("area_m2", 120))

    rooms = []

    rooms.append({"type": "living_room", "count": 1})
    rooms.append({"type": "kitchen", "count": 1})
    rooms.append({"type": "master_bedroom", "count": 1})

    secondary_count = max(0, bedrooms - 1)
    if secondary_count > 0:
        rooms.append({"type": "secondary_bedroom", "count": secondary_count})

    main_bath_count = min(1, bathrooms)
    extra_bath_count = max(0, bathrooms - 1)

    if main_bath_count > 0:
        rooms.append({"type": "bathroom", "count": 1})

    if extra_bath_count > 0:
        rooms.append({"type": "wc", "count": 1})
        if extra_bath_count > 1:
            rooms.append({"type": "bathroom", "count": extra_bath_count - 1})

    rooms.append({"type": "laundry", "count": 1})
    rooms.append({"type": "storage", "count": 1})
    rooms.append({"type": "corridor", "count": 1})

    if garage:
        rooms.append({"type": "garage", "count": 1})

    expanded = []
    for item in rooms:
        for i in range(item["count"]):
            expanded.append({"type": item["type"], "index": i + 1})

    # rough target areas
    remaining = total_area
    targets = []

    for room in expanded:
        rt = room["type"]

        if rt == "living_room":
            area = choose_area(rt, total_area * 0.22)
        elif rt == "kitchen":
            area = choose_area(rt, total_area * 0.12)
        elif rt == "master_bedroom":
            area = choose_area(rt, 16)
        elif rt == "secondary_bedroom":
            area = choose_area(rt, 11)
        elif rt == "bathroom":
            area = choose_area(rt, 6)
        elif rt == "wc":
            area = choose_area(rt, 1.8)
        elif rt == "laundry":
            area = choose_area(rt, 4.5)
        elif rt == "storage":
            area = choose_area(rt, 4)
        elif rt == "garage":
            area = choose_area(rt, 18)
        elif rt == "corridor":
            area = choose_area(rt, total_area * 0.06)
        else:
            area = choose_area(rt, 6)

        remaining -= area
        targets.append(
            {
                "name": room_name(room["type"], room["index"], expanded),
                "type": room["type"],
                "target_area": area,
            }
        )

    # living room absorbs remaining common area
    if remaining > 0:
        for r in targets:
            if r["type"] == "living_room":
                r["target_area"] = snap(r["target_area"] + remaining)
                break

    return targets


def room_name(room_type, index, all_rooms):
    same_type_count = sum(1 for r in all_rooms if r["type"] == room_type)

    if room_type == "master_bedroom":
        return "master_bedroom"
    if same_type_count == 1:
        return room_type
    return f"{room_type}_{index}"


def ask_openai_for_layout(house_data, room_program, house_width, house_depth):
    prompt = f"""
You are an architectural layout planner.

Create a UNIQUE rectangular house plan every time.

Rules:
- The house perimeter must be a single rectangle.
- All rooms must fit inside the perimeter.
- Place rooms on a grid.
- Prefer compact rectangular rooms.
- Adjacent rooms share only one interior wall of 0.10 m thickness.
- Exterior walls are 0.20 m thickness.
- Windows must only be possible on exterior walls.
- Living room should be placed on an exterior edge.
- Kitchen should be near the living room.
- Bathrooms/WC/laundry/storage can be more internal.
- Garage should be on an exterior side if present.
- Corridor width should be around 1.0 to 1.2 m.
- Keep the plan practical and realistic.
- Return DIFFERENT valid room arrangements each time.
- Coordinates are inside the house rectangle only.
- Use meters.

House rectangle:
width = {house_width}
depth = {house_depth}

Requested room program:
{json.dumps(room_program, indent=2)}

Return ONLY valid JSON in this exact format:
{{
  "house": {{
    "width": number,
    "depth": number
  }},
  "rooms": [
    {{
      "name": "living_room",
      "type": "living_room",
      "x": 0,
      "y": 0,
      "w": 5.0,
      "h": 6.0
    }}
  ]
}}
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
    )

    text = response.output_text.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


def validate_room(room):
    return all(k in room for k in ["name", "type", "x", "y", "w", "h"])


def rectangles_overlap(a, b):
    return not (
        a["x"] + a["w"] <= b["x"]
        or b["x"] + b["w"] <= a["x"]
        or a["y"] + a["h"] <= b["y"]
        or b["y"] + b["h"] <= a["y"]
    )


def inside_perimeter(room, width, depth):
    return (
        room["x"] >= 0
        and room["y"] >= 0
        and room["x"] + room["w"] <= width
        and room["y"] + room["h"] <= depth
    )


def snap_room(room):
    room["x"] = snap(room["x"])
    room["y"] = snap(room["y"])
    room["w"] = snap(room["w"])
    room["h"] = snap(room["h"])
    return room


def ensure_minimums(rooms):
    rules = get_room_rules()

    for room in rooms:
        room = snap_room(room)
        area = room["w"] * room["h"]
        min_area = rules.get(room["type"], {}).get("min", 4)

        if area < min_area:
            factor = math.sqrt(min_area / max(area, 0.1))
            room["w"] = snap(room["w"] * factor)
            room["h"] = snap(room["h"] * factor)

    return rooms


def validate_layout(layout, room_program, house_width, house_depth):
    if "rooms" not in layout:
        return False, "Missing rooms"

    rooms = layout["rooms"]

    if len(rooms) != len(room_program):
        return False, "Wrong number of rooms"

    names_expected = sorted(r["name"] for r in room_program)
    names_actual = sorted(r["name"] for r in rooms)

    if names_expected != names_actual:
        return False, "Room names mismatch"

    for room in rooms:
        if not validate_room(room):
            return False, f"Invalid room object: {room}"

        if not inside_perimeter(room, house_width, house_depth):
            return False, f"Room outside perimeter: {room['name']}"

    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            if rectangles_overlap(rooms[i], rooms[j]):
                return False, f"Rooms overlap: {rooms[i]['name']} and {rooms[j]['name']}"

    return True, "OK"


def add_surface_labels(layout):
    for room in layout["rooms"]:
        room["surface_m2"] = round(room["w"] * room["h"], 2)
    return layout


def add_wall_metadata(layout):
    layout["wall_rules"] = {
        "interior_wall_thickness_m": INTERIOR_WALL_THICKNESS,
        "exterior_wall_thickness_m": EXTERIOR_WALL_THICKNESS,
    }
    return layout


def add_window_rules(layout):
    layout["window_rules"] = {
        "windows_only_on_exterior_walls": True
    }
    return layout


def fallback_grid_layout(room_program, house_width, house_depth):
    rooms = []
    x = 0.0
    y = 0.0
    row_height = 0.0

    for room in room_program:
        target_area = room["target_area"]
        w = snap(math.sqrt(target_area * 1.2))
        h = snap(target_area / max(w, GRID))

        if x + w > house_width:
            x = 0.0
            y += row_height
            row_height = 0.0

        if y + h > house_depth:
            h = max(GRID, snap(house_depth - y))

        rooms.append(
            {
                "name": room["name"],
                "type": room["type"],
                "x": x,
                "y": y,
                "w": w,
                "h": h,
            }
        )

        x += w
        row_height = max(row_height, h)

    return {
        "house": {"width": house_width, "depth": house_depth},
        "rooms": rooms,
    }


def generate_layout(house_data):
    total_area = float(house_data.get("area_m2", 120))
    house_width, house_depth = estimate_house_rectangle(total_area)
    room_program = build_room_program(house_data)

    last_error = None
    layout = None

    # try several times to get unique valid plans from OpenAI
    for _ in range(3):
        try:
            candidate = ask_openai_for_layout(house_data, room_program, house_width, house_depth)

            candidate["house"]["width"] = house_width
            candidate["house"]["depth"] = house_depth

            candidate["rooms"] = [snap_room(r) for r in candidate["rooms"]]
            candidate["rooms"] = ensure_minimums(candidate["rooms"])

            valid, message = validate_layout(candidate, room_program, house_width, house_depth)
            if valid:
                layout = candidate
                break
            last_error = message
        except Exception as e:
            last_error = str(e)

    if layout is None:
        layout = fallback_grid_layout(room_program, house_width, house_depth)

    layout = add_surface_labels(layout)
    layout = add_wall_metadata(layout)
    layout = add_window_rules(layout)

    return layout