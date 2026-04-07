import json
import math
import os
import random
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

def room_min_dimensions():
    return {
        "living_room": (3.0, 3.0),
        "kitchen": (3.0, 3.0),
        "master_bedroom": (2.5, 2.5),
        "secondary_bedroom": (2.5, 2.5),
        "bathroom": (2.0, 2.0),
        "wc": (1.0, 1.0),
        "laundry": (1.5, 1.5),
        "storage": (2.0, 2.0),
        "garage": (3.65, 3.65),
        "corridor": (1.2, 2.5),
    }


def room_target_dimensions(room_type, target_area):
    min_w, min_h = room_min_dimensions().get(room_type, (2.0, 2.0))

    # Prefer compact near-square rooms but obey minimums
    w = max(min_w, math.sqrt(target_area))
    h = max(min_h, target_area / max(w, 0.1))

    return w, h


def fits_inside(x, y, w, h, house_width, house_depth):
    return x >= 0 and y >= 0 and x + w <= house_width and y + h <= house_depth


def overlaps_any(candidate, rooms):
    for r in rooms:
        if rectangles_overlap(candidate, r):
            return True
    return False


def room_has_min_dimensions(room):
    mins = room_min_dimensions()
    min_w, min_h = mins.get(room["type"], (1.0, 1.0))
    return room["w"] >= min_w and room["h"] >= min_h


def expand_living_room_to_fill(layout, house_width, house_depth):
    rooms = layout["rooms"]
    living = next((r for r in rooms if r["type"] == "living_room"), None)

    if not living:
        return layout

    def can_expand(new_room):
        for r in rooms:
            if r["name"] == living["name"]:
                continue
            if rectangles_overlap(new_room, r):
                return False
        return fits_inside(new_room["x"], new_room["y"], new_room["w"], new_room["h"], house_width, house_depth)

    # try expanding in 4 directions step-by-step
    step = 0.5

    # expand right
    while True:
        candidate = {
            **living,
            "w": living["w"] + step
        }
        if can_expand(candidate):
            living["w"] += step
        else:
            break


    # expand up
    while True:
        candidate = {
            **living,
            "h": living["h"] + step
        }
        if can_expand(candidate):
            living["h"] += step
        else:
            break

    return layout

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

def rooms_touch(a, b):
    x_overlap = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    y_overlap = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])

    # share a vertical wall
    if abs((a["x"] + a["w"]) - b["x"]) < 0.01 or abs((b["x"] + b["w"]) - a["x"]) < 0.01:
        return y_overlap > 0.01

    # share a horizontal wall
    if abs((a["y"] + a["h"]) - b["y"]) < 0.01 or abs((b["y"] + b["h"]) - a["y"]) < 0.01:
        return x_overlap > 0.01

    return False

def validate_adjacency(layout):
    rooms = layout["rooms"]

    living = next((r for r in rooms if r["type"] == "living_room"), None)
    kitchen = next((r for r in rooms if r["type"] == "kitchen"), None)
    corridor = next((r for r in rooms if r["type"] == "corridor"), None)
    bedrooms = [r for r in rooms if r["type"] in ["master_bedroom", "secondary_bedroom"]]

    if living and kitchen and not rooms_touch(living, kitchen):
        return False, "Living room must touch kitchen"

    if living and corridor and not rooms_touch(living, corridor):
        return False, "Living room must touch corridor"

    for bedroom in bedrooms:
        if not corridor or not rooms_touch(bedroom, corridor):
            return False, f"{bedroom['name']} must touch corridor"

    return True, "OK"

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

def validate_total_area_usage(layout, target_area):
    rooms = layout["rooms"]
    total_room_area = sum(r["w"] * r["h"] for r in rooms)

    if total_room_area < target_area * 0.90:
        return False, f"Plan uses too little area: {total_room_area:.2f} < {target_area * 0.90:.2f}"

    return True, "OK"

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

    variation_hint = random.choice([
        "Use a wider day zone and compact bedroom cluster.",
        "Use a compact central corridor with day zone on the south side.",
        "Use a balanced left-right split between day and night zones.",
        "Use a slightly asymmetric but realistic arrangement.",
        "Use a compact plan with the corridor centrally placed and rooms around it.",
    ])

    prompt = f"""
You are an architectural layout planner.

Generate a UNIQUE realistic single-floor house plan every time.

Hard rules:
- The house perimeter must be one rectangle only.
- All rooms must fit completely inside the perimeter.
- Rooms must not overlap.
- Snap to a 0.5 m grid as much as possible, but logical access is more important than perfect snapping.
- Use mostly rectangular rooms.
- The corridor must be as small as possible while still giving logical access.
- The corridor must be placed in the middle area of the house.
- Bedrooms must access the corridor.
- Bedrooms should have only one door access to the corridor later, so each bedroom should touch the corridor along one clear side.
- The corridor should have walls around it except for the connection between living room and corridor.
- Living room and corridor must connect directly.
- Living room and kitchen must be adjacent or directly connected.
- Living room should touch the front facade.
- Bedrooms should be grouped together in a quieter zone.
- Bathroom, wc, laundry, storage should be grouped near bedrooms.
- Garage, if present, must touch an exterior edge.
- All rooms together should fill the floor slab as much as possible.
- If some surface remains, the living room should absorb it.

Minimum dimensions:
- Bedrooms: at least 2.5 m x 2.5 m
- Kitchen: at least 3.0 m x 3.0 m
- Garage: at least 3.65 m x 3.65 m
- Bathroom: at least 2.0 m x 2.0 m
- WC: at least 1.0 m x 1.0 m
- Laundry: at least 1.5 m x 1.5 m
- Storage: at least 2.0 m x 2.0 m

House rectangle:
width = {house_width}
depth = {house_depth}

Room program:
{json.dumps(room_program, indent=2)}

Grouped zones:
{json.dumps(grouped, indent=2)}

Variation target:
- {variation_hint}
- Produce a different valid plan than a standard grid layout.

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
    min_dims = room_min_dimensions()

    for room in rooms:
        room = snap_room(room)

        # area minimum
        area = room["w"] * room["h"]
        min_area = rules.get(room["type"], {}).get("min", 4)

        if area < min_area:
            factor = math.sqrt(min_area / max(area, 0.1))
            room["w"] = snap(room["w"] * factor)
            room["h"] = snap(room["h"] * factor)

        # dimension minimums
        min_w, min_h = min_dims.get(room["type"], (1.0, 1.0))
        room["w"] = snap(max(room["w"], min_w))
        room["h"] = snap(max(room["h"], min_h))

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

        if room["w"] < GRID or room["h"] < GRID:
            return False, f"Invalid room size: {room['name']}"

        if not room_has_min_dimensions(room):
            return False, f"Room below minimum dimensions: {room['name']}"

        if not inside_perimeter(room, house_width, house_depth):
            return False, f"Room outside perimeter: {room['name']}"

    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            if rectangles_overlap(rooms[i], rooms[j]):
                return False, f"Overlap: {rooms[i]['name']} and {rooms[j]['name']}"

    return True, "OK"

def validate_no_overlap_strict(layout):
    rooms = layout["rooms"]
    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            if rectangles_overlap(rooms[i], rooms[j]):
                return False, f"Overlap between {rooms[i]['name']} and {rooms[j]['name']}"
    return True, "OK"

def validate_corridor_position(layout, house_width, house_depth):
    corridor = next((r for r in layout["rooms"] if r["type"] == "corridor"), None)
    if not corridor:
        return False, "Missing corridor"

    # hard size cap
    if corridor["w"] >= 1.5 or corridor["h"] >= 3.0:
        return False, "Corridor too large"

    cx = corridor["x"] + corridor["w"] / 2
    cy = corridor["y"] + corridor["h"] / 2

    house_cx = house_width / 2
    house_cy = house_depth / 2

    if abs(cx - house_cx) > house_width * 0.2:
        return False, "Corridor not central enough"
    if abs(cy - house_cy) > house_depth * 0.2:
        return False, "Corridor not central enough"

    return True, "OK"

def fallback_grid_layout(room_program, house_width, house_depth):
    rooms = []

    # corridor: hard-limited, central
    corridor_w = random.choice([1.2, 1.3, 1.4])
    corridor_h = random.choice([2.5, 2.75])

    corridor_x = (house_width - corridor_w) / 2
    corridor_y = (house_depth - corridor_h) / 2

    corridor = {
        "name": "corridor",
        "type": "corridor",
        "x": corridor_x,
        "y": corridor_y,
        "w": corridor_w,
        "h": corridor_h,
    }
    rooms.append(corridor)

    # sort rooms by priority and size
    non_corridor = [r for r in room_program if r["type"] != "corridor"]
    non_corridor.sort(
        key=lambda r: (
            0 if r["type"] == "living_room" else
            1 if r["type"] == "kitchen" else
            2 if r["type"] in ["master_bedroom", "secondary_bedroom"] else
            3
        ,
            -r["target_area"]
        )
    )

    # candidate zones around corridor: left, right, top, bottom
    # each room must touch corridor if possible
    placed = [corridor]

    def try_place_room(room, side):
        target_area = room["target_area"]
        min_w, min_h = room_min_dimensions().get(room["type"], (2.0, 2.0))
        w, h = room_target_dimensions(room["type"], target_area)

        # if not enough space later, fall back to minimum dims
        w = max(w, min_w)
        h = max(h, min_h)

        candidates = []

        if side == "left":
            x = corridor["x"] - w
            y = corridor["y"] + (corridor["h"] - h) / 2
            candidates.append((x, y, w, h))
        elif side == "right":
            x = corridor["x"] + corridor["w"]
            y = corridor["y"] + (corridor["h"] - h) / 2
            candidates.append((x, y, w, h))
        elif side == "top":
            x = corridor["x"] + (corridor["w"] - w) / 2
            y = corridor["y"] + corridor["h"]
            candidates.append((x, y, w, h))
        elif side == "bottom":
            x = corridor["x"] + (corridor["w"] - w) / 2
            y = corridor["y"] - h
            candidates.append((x, y, w, h))

        # try slight shifts to fit around corridor without overlap
        for base_x, base_y, base_w, base_h in list(candidates):
            for dx in [0, -0.5, 0.5, -1.0, 1.0, -1.5, 1.5, -2.0, 2.0]:
                for dy in [0, -0.5, 0.5, -1.0, 1.0, -1.5, 1.5, -2.0, 2.0]:
                    candidate = {
                        "name": room["name"],
                        "type": room["type"],
                        "x": base_x + dx,
                        "y": base_y + dy,
                        "w": base_w,
                        "h": base_h,
                    }

                    if not fits_inside(candidate["x"], candidate["y"], candidate["w"], candidate["h"], house_width, house_depth):
                        continue
                    if overlaps_any(candidate, placed):
                        continue
                    if room["type"] in ["master_bedroom", "secondary_bedroom", "bathroom", "wc", "laundry", "storage", "kitchen", "living_room"]:
                        if not rooms_touch(candidate, corridor):
                            continue

                    return candidate

        # minimum-size fallback
        for side_try in ["left", "right", "top", "bottom"]:
            if side_try == "left":
                x = corridor["x"] - min_w
                y = corridor["y"] + (corridor["h"] - min_h) / 2
            elif side_try == "right":
                x = corridor["x"] + corridor["w"]
                y = corridor["y"] + (corridor["h"] - min_h) / 2
            elif side_try == "top":
                x = corridor["x"] + (corridor["w"] - min_w) / 2
                y = corridor["y"] + corridor["h"]
            else:
                x = corridor["x"] + (corridor["w"] - min_w) / 2
                y = corridor["y"] - min_h

            candidate = {
                "name": room["name"],
                "type": room["type"],
                "x": x,
                "y": y,
                "w": min_w,
                "h": min_h,
            }

            if fits_inside(candidate["x"], candidate["y"], candidate["w"], candidate["h"], house_width, house_depth) and not overlaps_any(candidate, placed):
                if rooms_touch(candidate, corridor):
                    return candidate

        return None

    side_cycle = ["left", "right", "top", "bottom"]
    living = next((r for r in non_corridor if r["type"] == "living_room"), None)
    kitchen = next((r for r in non_corridor if r["type"] == "kitchen"), None)

    if living:
        non_corridor.remove(living)
        candidate = try_place_room(living, random.choice(["left", "right", "bottom"]))
        if candidate:
            rooms.append(candidate)
            placed.append(candidate)
        else:
            raise ValueError(f"Could not place room: {room['name']}")

    if kitchen:
        non_corridor.remove(kitchen)
        candidate = None
        if living:
            # prefer kitchen on another side but still corridor-connected
            for side in ["left", "right", "top", "bottom"]:
                candidate = try_place_room(kitchen, side)
                if candidate:
                    break
        else:
            candidate = try_place_room(kitchen, "right")
        if candidate:
            rooms.append(candidate)
            placed.append(candidate)
        else:
            raise ValueError(f"Could not place room: {room['name']}")

    side_index = 0
    for room in non_corridor:
        candidate = None
        for _ in range(4):
            side = side_cycle[side_index % 4]
            side_index += 1
            candidate = try_place_room(room, side)
            if candidate:
                break

        if candidate:
            rooms.append(candidate)
            placed.append(candidate)
        else:
            raise ValueError(f"Could not place room: {room['name']}")

    # final cleanup
    rooms = [snap_room(r) for r in rooms if r["w"] > 0 and r["h"] > 0]

    return {
        "house": {"width": house_width, "depth": house_depth},
        "rooms": rooms
    }

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

def build_circulation_plan(layout):
    rooms = layout["rooms"]
    walls = layout["walls"]

    room_by_name = {r["name"]: r for r in rooms}
    corridor = next((r for r in rooms if r["type"] == "corridor"), None)

    circulation = {
        "doors": []
    }

    if not corridor:
        return layout | {"circulation": circulation}

    # front door: exterior wall belonging to living room on south facade if possible
    south_living_walls = [
        w for w in walls
        if w["type"] == "exterior"
        and w.get("facade") == "south"
        and "living_room" in w.get("rooms", [])
        and w["length"] >= 1.2
    ]

    if south_living_walls:
        wall = max(south_living_walls, key=lambda w: w["length"])
        circulation["doors"].append({
            "type": "front",
            "wall_id": wall["id"],
            "rooms": ["living_room"],
            "width": 1.0
        })

    # interior doors: one per bedroom/service room touching corridor
    allowed_private_types = {
        "master_bedroom",
        "secondary_bedroom",
        "bathroom",
        "wc",
        "laundry",
        "storage",
        "garage",
    }

    added_room_doors = set()

    for wall in walls:
        if wall["type"] != "interior":
            continue

        connected = wall.get("rooms", [])
        if len(connected) != 2:
            continue

        a, b = connected[0], connected[1]
        room_a = room_by_name.get(a)
        room_b = room_by_name.get(b)

        if not room_a or not room_b:
            continue

        types = {room_a["type"], room_b["type"]}
        names = {room_a["name"], room_b["name"]}

        # one side must be corridor
        if "corridor" not in types:
            continue

        other_room = room_a if room_b["type"] == "corridor" else room_b

        if other_room["name"] in added_room_doors:
            continue

        if other_room["type"] in allowed_private_types:
            circulation["doors"].append({
                "type": "interior",
                "wall_id": wall["id"],
                "rooms": [room_a["name"], room_b["name"]],
                "width": 0.9
            })
            added_room_doors.add(other_room["name"])

    # living room ↔ corridor door/opening
    living_corridor_walls = [
        w for w in walls
        if w["type"] == "interior"
        and set(w.get("rooms", [])) == {"living_room", "corridor"}
        and w["length"] >= 1.2
    ]

    if living_corridor_walls:
        wall = max(living_corridor_walls, key=lambda w: w["length"])
        circulation["doors"].append({
            "type": "interior",
            "wall_id": wall["id"],
            "rooms": ["living_room", "corridor"],
            "width": 1.1
        })

    # kitchen ↔ living or kitchen ↔ corridor, one only
    kitchen_links = [
        w for w in walls
        if w["type"] == "interior"
        and "kitchen" in w.get("rooms", [])
        and (
            "living_room" in w.get("rooms", [])
            or "corridor" in w.get("rooms", [])
        )
        and w["length"] >= 1.0
    ]

    if kitchen_links:
        wall = max(kitchen_links, key=lambda w: w["length"])
        circulation["doors"].append({
            "type": "interior",
            "wall_id": wall["id"],
            "rooms": wall["rooms"],
            "width": 0.9
        })
        unique = []
    seen = set()

    for door in circulation["doors"]:
        key = (door["wall_id"], tuple(sorted(door["rooms"])), door["type"])
        if key not in seen:
            seen.add(key)
            unique.append(door)

    circulation["doors"] = unique

    return layout | {"circulation": circulation}

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

def has_all_required_rooms(layout, room_program):
    actual_names = sorted(r["name"] for r in layout.get("rooms", []))
    expected_names = sorted(r["name"] for r in room_program)
    return actual_names == expected_names

def generate_layout(house_data):
    total_area = float(house_data.get("area_m2", 120))
    house_width, house_depth = estimate_house_rectangle(total_area)
    room_program = build_room_program(house_data)

    layout = None

    for _ in range(5):
        try:
            candidate = ask_openai_for_layout(house_data, room_program, house_width, house_depth)

            if "house" not in candidate:
                candidate["house"] = {}

            candidate["house"]["width"] = house_width
            candidate["house"]["depth"] = house_depth

            candidate["rooms"] = [snap_room(r) for r in candidate["rooms"]]
            candidate["rooms"] = ensure_minimums(candidate["rooms"])
            candidate = expand_living_room_to_fill(candidate, house_width, house_depth)

            if not has_all_required_rooms(candidate, room_program):
                continue

            valid, msg = validate_layout(candidate, room_program, house_width, house_depth)

            if valid:
                valid_adj, adj_msg = validate_adjacency(candidate)
                corridor_ok, corridor_msg = validate_corridor_position(candidate, house_width, house_depth)
                area_ok, area_msg = validate_total_area_usage(candidate, total_area)
                overlap_ok, overlap_msg = validate_no_overlap_strict(candidate)

                if valid_adj and corridor_ok and area_ok and overlap_ok:
                    layout = candidate
                    break

        except Exception:
            pass

    if layout is None:
        layout = fallback_grid_layout(room_program, house_width, house_depth)
        layout["rooms"] = ensure_minimums(layout["rooms"])
        layout = expand_living_room_to_fill(layout, house_width, house_depth)

        valid, msg = validate_layout(layout, room_program, house_width, house_depth)
        overlap_ok, overlap_msg = validate_no_overlap_strict(layout)
        corridor_ok, corridor_msg = validate_corridor_position(layout, house_width, house_depth)
        valid_adj, adj_msg = validate_adjacency(layout)

        if not (valid and overlap_ok and corridor_ok and valid_adj):
            raise ValueError(
                f"Fallback layout invalid: {msg}, {overlap_msg}, {corridor_msg}, {adj_msg}"
            )

    layout = add_surface_labels(layout)
    layout = build_shared_walls(layout)
    layout = build_circulation_plan(layout)
    layout = add_metadata(layout)

    return layout