import json
import math
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(dotenv_path=".env")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

GRID = 0.5
INTERIOR_WALL_THICKNESS = 0.10
EXTERIOR_WALL_THICKNESS = 0.20


def snap(value, step=GRID):
    return round(value / step) * step


def clamp(value, min_v, max_v):
    return max(min_v, min(value, max_v))


def room_rules():
    return {
        "living_room": {"min": 20, "ideal_min": 25, "ideal_max": 35, "max": 999},
        "kitchen": {"min": 8, "ideal_min": 12, "ideal_max": 18, "max": 25},
        "master_bedroom": {"min": 12, "ideal_min": 14, "ideal_max": 18, "max": 25},
        "secondary_bedroom": {"min": 9, "ideal_min": 10, "ideal_max": 12, "max": 16},
        "bathroom": {"min": 4, "ideal_min": 5, "ideal_max": 8, "max": 12},
        "wc": {"min": 1.2, "ideal_min": 1.5, "ideal_max": 2.0, "max": 3},
        "laundry": {"min": 3, "ideal_min": 4, "ideal_max": 6, "max": 8},
        "storage": {"min": 2, "ideal_min": 3, "ideal_max": 5, "max": 8},
        "garage": {"min": 15, "ideal_min": 18, "ideal_max": 20, "max": 25},
        "corridor": {"min": 3, "ideal_min": 4, "ideal_max": 6, "max": 10},
    }


def choose_area(room_type, fallback_area):
    rules = room_rules().get(room_type)
    if not rules:
        return snap(max(4, fallback_area))

    if rules["max"] == 999:
        return snap(max(rules["ideal_min"], fallback_area))

    area = clamp(fallback_area, rules["min"], rules["max"])
    return snap(area)


def room_name(room_type, index, all_rooms):
    same_type_count = sum(1 for r in all_rooms if r["type"] == room_type)

    if room_type == "master_bedroom":
        return "master_bedroom"
    if same_type_count == 1:
        return room_type
    return f"{room_type}_{index}"


def estimate_house_rectangle(total_area):
    width = math.sqrt(total_area * 1.18)
    depth = total_area / max(width, 1)

    width = snap(width)
    depth = snap(depth)

    if width < depth:
        width, depth = depth, width

    return width, depth


def build_room_program(house_data):
    bedrooms = int(house_data.get("bedrooms", 3))
    bathrooms = int(house_data.get("bathrooms", 2))
    garage = bool(house_data.get("garage", False))
    total_area = float(house_data.get("area_m2", 120))

    rooms = [
        {"type": "living_room", "count": 1},
        {"type": "kitchen", "count": 1},
        {"type": "master_bedroom", "count": 1},
        {"type": "secondary_bedroom", "count": max(0, bedrooms - 1)},
        {"type": "bathroom", "count": min(1, bathrooms)},
        {"type": "wc", "count": 1 if bathrooms > 1 else 0},
        {"type": "bathroom", "count": max(0, bathrooms - 2)},
        {"type": "laundry", "count": 1},
        {"type": "storage", "count": 1},
        {"type": "corridor", "count": 1},
        {"type": "garage", "count": 1 if garage else 0},
    ]

    expanded = []
    for item in rooms:
        for i in range(item["count"]):
            expanded.append({"type": item["type"], "index": i + 1})

    targets = []
    remaining = total_area

    for room in expanded:
        rt = room["type"]

        if rt == "living_room":
            area = choose_area(rt, total_area * 0.24)
        elif rt == "kitchen":
            area = choose_area(rt, total_area * 0.11)
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
            area = choose_area(rt, 3.5)
        elif rt == "garage":
            area = choose_area(rt, 18)
        elif rt == "corridor":
            area = choose_area(rt, total_area * 0.04)
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

    if remaining > 0:
        for r in targets:
            if r["type"] == "living_room":
                r["target_area"] = snap(r["target_area"] + remaining)
                break

    return targets


def classify_room_groups(room_program):
    day_zone = []
    night_zone = []
    service_zone = []

    for room in room_program:
        rt = room["type"]
        if rt in ["living_room", "kitchen"]:
            day_zone.append(room)
        elif rt in ["master_bedroom", "secondary_bedroom"]:
            night_zone.append(room)
        else:
            service_zone.append(room)

    return {
        "day_zone": day_zone,
        "night_zone": night_zone,
        "service_zone": service_zone,
    }


def ask_openai_for_layout(house_data, room_program, house_width, house_depth):
    grouped = classify_room_groups(room_program)

    prompt = f"""
You are an architectural layout planner.

Generate a UNIQUE realistic house plan every time.

Hard rules:
- The house perimeter must be one rectangle only.
- All rooms must fit completely inside the perimeter.
- Snap all room coordinates and dimensions to a 0.5 m grid.
- Use mostly rectangular rooms.
- Keep the plan compact and realistic.
- Avoid long oversized corridors.
- Interior partition logic should be simple and buildable.
- Windows will only be placed on exterior walls.
- Return only rooms; wall generation happens later.

Zoning rules:
- DAY ZONE: living_room and kitchen should be adjacent or directly connected.
- Living room should be on an exterior facade.
- Kitchen should also touch an exterior wall if possible.
- NIGHT ZONE: bedrooms should be grouped together in a quieter area.
- SERVICE ZONE: bathroom, wc, laundry, storage should be close to each other.
- Garage, if present, should touch an exterior edge and ideally be near service spaces.
- Corridor should be minimal and practical, not oversized.
- Avoid isolated rooms.
- Try to create a clear entrance sequence from front door toward day zone.
- Prefer plans that feel like a real house, not random rectangles.

House rectangle:
width = {house_width}
depth = {house_depth}

Room program:
{json.dumps(room_program, indent=2)}

Grouped zones:
{json.dumps(grouped, indent=2)}

Return ONLY JSON in this exact format:
{{
  "house": {{
    "width": {house_width},
    "depth": {house_depth}
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


def snap_room(room):
    room["x"] = snap(room["x"])
    room["y"] = snap(room["y"])
    room["w"] = snap(room["w"])
    room["h"] = snap(room["h"])
    return room


def inside_perimeter(room, width, depth):
    return (
        room["x"] >= 0
        and room["y"] >= 0
        and room["x"] + room["w"] <= width
        and room["y"] + room["h"] <= depth
    )


def rectangles_overlap(a, b):
    return not (
        a["x"] + a["w"] <= b["x"]
        or b["x"] + b["w"] <= a["x"]
        or a["y"] + a["h"] <= b["y"]
        or b["y"] + b["h"] <= a["y"]
    )


def ensure_minimums(rooms):
    rules = room_rules()

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
        if not all(k in room for k in ["name", "type", "x", "y", "w", "h"]):
            return False, f"Invalid room: {room}"

        if room["w"] <= 0 or room["h"] <= 0:
            return False, f"Invalid room size: {room['name']}"

        if not inside_perimeter(room, house_width, house_depth):
            return False, f"Room outside perimeter: {room['name']}"

    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            if rectangles_overlap(rooms[i], rooms[j]):
                return False, f"Overlap: {rooms[i]['name']} and {rooms[j]['name']}"

    return True, "OK"


def fallback_grid_layout(room_program, house_width, house_depth):
    day = [r for r in room_program if r["type"] in ["living_room", "kitchen"]]
    night = [r for r in room_program if r["type"] in ["master_bedroom", "secondary_bedroom"]]
    service = [r for r in room_program if r["type"] not in ["living_room", "kitchen", "master_bedroom", "secondary_bedroom"]]

    rooms = []

    day_band_depth = snap(house_depth * 0.42)
    night_band_depth = snap(house_depth * 0.38)
    service_band_depth = snap(house_depth - day_band_depth - night_band_depth)

    # Day zone on south/front
    x = 0.0
    for room in day:
        if room["type"] == "living_room":
            w = snap(max(house_width * 0.55, math.sqrt(room["target_area"] * 1.3)))
        else:
            w = snap(max(house_width * 0.25, math.sqrt(room["target_area"] * 1.1)))

        h = snap(room["target_area"] / max(w, GRID))
        h = min(day_band_depth, max(GRID, h))

        if x + w > house_width:
            w = snap(house_width - x)

        rooms.append({
            "name": room["name"],
            "type": room["type"],
            "x": x,
            "y": 0.0,
            "w": w,
            "h": h
        })
        x += w

    # Night zone in middle
    x = 0.0
    row_y = day_band_depth
    row_height = 0.0

    for room in night:
        w = snap(math.sqrt(room["target_area"] * 1.15))
        h = snap(room["target_area"] / max(w, GRID))

        if x + w > house_width:
            x = 0.0
            row_y += row_height
            row_height = 0.0

        if row_y + h > day_band_depth + night_band_depth:
            h = snap((day_band_depth + night_band_depth) - row_y)

        rooms.append({
            "name": room["name"],
            "type": room["type"],
            "x": x,
            "y": row_y,
            "w": w,
            "h": h
        })

        x += w
        row_height = max(row_height, h)

    # Service zone at back
    x = 0.0
    row_y = day_band_depth + night_band_depth
    row_height = 0.0

    for room in service:
        if room["type"] == "garage":
            w = snap(max(5.5, math.sqrt(room["target_area"] * 1.2)))
        elif room["type"] == "corridor":
            w = snap(max(1.5, math.sqrt(room["target_area"] * 0.8)))
        else:
            w = snap(math.sqrt(room["target_area"] * 1.0))

        h = snap(room["target_area"] / max(w, GRID))

        if x + w > house_width:
            x = 0.0
            row_y += row_height
            row_height = 0.0

        if row_y + h > house_depth:
            h = snap(house_depth - row_y)

        rooms.append({
            "name": room["name"],
            "type": room["type"],
            "x": x,
            "y": row_y,
            "w": w,
            "h": h
        })

        x += w
        row_height = max(row_height, h)

    return {"house": {"width": house_width, "depth": house_depth}, "rooms": rooms}


def add_surface_labels(layout):
    for room in layout["rooms"]:
        room["surface_m2"] = round(room["w"] * room["h"], 2)
    return layout


def normalize_segment(x1, y1, x2, y2):
    x1, y1, x2, y2 = snap(x1), snap(y1), snap(x2), snap(y2)

    if (x1, y1) <= (x2, y2):
        return (x1, y1, x2, y2)
    return (x2, y2, x1, y1)


def room_edges(room):
    x = room["x"]
    y = room["y"]
    w = room["w"]
    h = room["h"]

    return [
        ("bottom", normalize_segment(x, y, x + w, y)),
        ("top", normalize_segment(x, y + h, x + w, y + h)),
        ("left", normalize_segment(x, y, x, y + h)),
        ("right", normalize_segment(x + w, y, x + w, y + h)),
    ]


def segment_orientation(seg):
    x1, y1, x2, y2 = seg
    return "horizontal" if y1 == y2 else "vertical"


def segment_length(seg):
    x1, y1, x2, y2 = seg
    return round(math.hypot(x2 - x1, y2 - y1), 3)


def on_outer_perimeter(seg, house_width, house_depth):
    x1, y1, x2, y2 = seg

    if y1 == 0 and y2 == 0:
        return True, "south"
    if y1 == house_depth and y2 == house_depth:
        return True, "north"
    if x1 == 0 and x2 == 0:
        return True, "west"
    if x1 == house_width and x2 == house_width:
        return True, "east"

    return False, None


def build_shared_walls(layout):
    house_width = layout["house"]["width"]
    house_depth = layout["house"]["depth"]

    edge_map = {}

    for room in layout["rooms"]:
        for side, seg in room_edges(room):
            edge_map.setdefault(seg, []).append(
                {
                    "room_name": room["name"],
                    "room_type": room["type"],
                    "side": side,
                }
            )

    walls = []

    for seg, owners in edge_map.items():
        x1, y1, x2, y2 = seg
        is_exterior, facade = on_outer_perimeter(seg, house_width, house_depth)

        if is_exterior:
            walls.append(
                {
                    "id": f"wall_{len(walls)+1}",
                    "type": "exterior",
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "orientation": segment_orientation(seg),
                    "length": segment_length(seg),
                    "thickness": EXTERIOR_WALL_THICKNESS,
                    "rooms": [o["room_name"] for o in owners],
                    "facade": facade,
                    "window_allowed": True,
                }
            )
        elif len(owners) >= 2:
            walls.append(
                {
                    "id": f"wall_{len(walls)+1}",
                    "type": "interior",
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "orientation": segment_orientation(seg),
                    "length": segment_length(seg),
                    "thickness": INTERIOR_WALL_THICKNESS,
                    "rooms": [o["room_name"] for o in owners[:2]],
                    "facade": None,
                    "window_allowed": False,
                }
            )
        else:
            walls.append(
                {
                    "id": f"wall_{len(walls)+1}",
                    "type": "interior",
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "orientation": segment_orientation(seg),
                    "length": segment_length(seg),
                    "thickness": INTERIOR_WALL_THICKNESS,
                    "rooms": [o["room_name"] for o in owners],
                    "facade": None,
                    "window_allowed": False,
                }
            )

    return layout | {"walls": walls}


def add_metadata(layout):
    layout["wall_rules"] = {
        "interior_wall_thickness_m": INTERIOR_WALL_THICKNESS,
        "exterior_wall_thickness_m": EXTERIOR_WALL_THICKNESS,
        "shared_interior_walls_only_once": True,
        "house_perimeter_rectangle": True,
    }
    layout["window_rules"] = {
        "windows_only_on_exterior_walls": True
    }
    return layout


def generate_layout(house_data):
    total_area = float(house_data.get("area_m2", 120))
    house_width, house_depth = estimate_house_rectangle(total_area)
    room_program = build_room_program(house_data)

    layout = None

    for _ in range(3):
        try:
            candidate = ask_openai_for_layout(house_data, room_program, house_width, house_depth)
            candidate["house"]["width"] = house_width
            candidate["house"]["depth"] = house_depth
            candidate["rooms"] = [snap_room(r) for r in candidate["rooms"]]
            candidate["rooms"] = ensure_minimums(candidate["rooms"])

            valid, _ = validate_layout(candidate, room_program, house_width, house_depth)
            if valid:
                layout = candidate
                break
        except Exception:
            pass

    if layout is None:
        layout = fallback_grid_layout(room_program, house_width, house_depth)

    layout = add_surface_labels(layout)
    layout = build_shared_walls(layout)
    layout = add_metadata(layout)

    return layout