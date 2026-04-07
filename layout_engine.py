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

def room_has_min_area(room):
    rules = room_rules()
    min_area = rules.get(room["type"], {}).get("min", 0)
    return room["w"] * room["h"] >= min_area


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


def estimate_house_rectangles(total_area):
    width = math.sqrt(total_area * 1.18)
    depth = total_area / max(width, 1)

    width = snap(width)
    depth = snap(depth)

    if width < depth:
        width, depth = depth, width

    return [(width, depth)]


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

def resolve_overlaps(layout, house_width, house_depth, max_passes=20):
    rooms = layout["rooms"]

    for _ in range(max_passes):
        changed = False

        for i in range(len(rooms)):
            for j in range(i + 1, len(rooms)):
                a = rooms[i]
                b = rooms[j]

                if not rectangles_overlap(a, b):
                    continue

                changed = True

                overlap_x = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
                overlap_y = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])

                if overlap_x <= 0 or overlap_y <= 0:
                    continue

                # Prefer moving the room that is not corridor/living room
                movable = b
                anchor = a

                if a["type"] not in ["corridor", "living_room"] and b["type"] in ["corridor", "living_room"]:
                    movable = a
                    anchor = b

                # Shift in the smallest-overlap direction
                if overlap_x < overlap_y:
                    if movable["x"] >= anchor["x"]:
                        movable["x"] = snap(movable["x"] + overlap_x)
                    else:
                        movable["x"] = snap(movable["x"] - overlap_x)
                else:
                    if movable["y"] >= anchor["y"]:
                        movable["y"] = snap(movable["y"] + overlap_y)
                    else:
                        movable["y"] = snap(movable["y"] - overlap_y)

                # Clamp back inside slab
                movable["x"] = snap(max(0, min(movable["x"], house_width - movable["w"])))
                movable["y"] = snap(max(0, min(movable["y"], house_depth - movable["h"])))

        if not changed:
            break

    return layout

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

    if not room_has_min_area(room):
        return False, f"Room below minimum area: {room['name']}"

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
    if corridor["w"] > 1.5 or corridor["h"] > 3.0:
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

    # Compact corridor, strictly within your target
    corridor_w = 1.3
    corridor_h = 2.5
    corridor_x = snap((house_width - corridor_w) / 2)
    corridor_y = snap((house_depth - corridor_h) / 2)

    corridor = {
        "name": "corridor",
        "type": "corridor",
        "x": corridor_x,
        "y": corridor_y,
        "w": corridor_w,
        "h": corridor_h,
    }
    rooms.append(corridor)

    living = next(r for r in room_program if r["type"] == "living_room")
    kitchen = next(r for r in room_program if r["type"] == "kitchen")
    bedrooms = [r for r in room_program if r["type"] in ["master_bedroom", "secondary_bedroom"]]
    services = [r for r in room_program if r["type"] in ["bathroom", "wc", "laundry", "storage"]]
    garage = next((r for r in room_program if r["type"] == "garage"), None)

    def make_room(name, room_type, x, y, w, h):
        min_w, min_h = room_min_dimensions()[room_type]
        return {
            "name": name,
            "type": room_type,
            "x": snap(x),
            "y": snap(y),
            "w": snap(max(w, min_w)),
            "h": snap(max(h, min_h)),
        }

    # South band: living + kitchen, both touching corridor band
    south_h = corridor_y
    kitchen_w = 3.5
    living_w = house_width - kitchen_w

    rooms.append(make_room(living["name"], "living_room", 0, 0, living_w, south_h))
    rooms.append(make_room(kitchen["name"], "kitchen", living_w, 0, kitchen_w, south_h))

    # North band: all bedrooms, all touching corridor
    north_y = corridor_y + corridor_h
    north_h = house_depth - north_y

    bedroom_count = len(bedrooms)
    if bedroom_count > 0:
        bw = house_width / bedroom_count
        for i, b in enumerate(bedrooms):
            rooms.append(
                make_room(
                    b["name"],
                    b["type"],
                    i * bw,
                    north_y,
                    bw,
                    north_h
                )
            )

    # West side of corridor: bathroom + wc stacked vertically, touching corridor
    west_w = corridor_x
    west_x = 0
    west_y = corridor_y

    west_services = [r for r in services if r["type"] in ["bathroom", "wc"]]
    if west_services:
        heights = []
        remaining_h = corridor_h
        for idx, r in enumerate(west_services):
            min_w, min_h = room_min_dimensions()[r["type"]]
            if idx == len(west_services) - 1:
                h = remaining_h
            else:
                h = max(min_h, snap(corridor_h / len(west_services)))
                remaining_h -= h
            heights.append((r, h))

        y_cursor = west_y
        for r, h in heights:
            rooms.append(make_room(r["name"], r["type"], west_x, y_cursor, west_w, h))
            y_cursor += snap(h)

    # East side of corridor: laundry + storage stacked in corridor band, garage above them
    east_x = corridor_x + corridor_w
    east_w = house_width - east_x

    east_services = [r for r in services if r["type"] in ["laundry", "storage"]]

    y_cursor = corridor_y
    for r in east_services:
        min_w, min_h = room_min_dimensions()[r["type"]]
        h = min_h
        rooms.append(make_room(r["name"], r["type"], east_x, y_cursor, east_w, h))
        y_cursor += snap(h)

    if garage:
        garage_y = max(y_cursor, north_y)
        garage_h = house_depth - garage_y
        rooms.append(make_room(garage["name"], "garage", east_x, garage_y, east_w, garage_h))

    # Clamp to slab
    cleaned = []
    for r in rooms:
        min_w, min_h = room_min_dimensions()[r["type"]]
        r["w"] = snap(max(r["w"], min_w))
        r["h"] = snap(max(r["h"], min_h))
        r["x"] = snap(max(0, min(r["x"], house_width - r["w"])))
        r["y"] = snap(max(0, min(r["y"], house_depth - r["h"])))
        cleaned.append(r)

    return {
        "house": {"width": house_width, "depth": house_depth},
        "rooms": cleaned
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

    rooms = layout["rooms"]

    # ---------- Collect raw room edges ----------
    raw_edges = []
    for room in rooms:
        for side, seg in room_edges(room):
            x1, y1, x2, y2 = seg
            raw_edges.append({
                "room_name": room["name"],
                "room_type": room["type"],
                "side": side,
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "orientation": segment_orientation(seg),
            })

    # ---------- Collect split points ----------
    horizontal_lines = {}
    vertical_lines = {}

    for e in raw_edges:
        if e["orientation"] == "horizontal":
            y = e["y1"]
            horizontal_lines.setdefault(y, set()).update([e["x1"], e["x2"]])
        else:
            x = e["x1"]
            vertical_lines.setdefault(x, set()).update([e["y1"], e["y2"]])

    # Add overlap split points from collinear edges
    for e1 in raw_edges:
        for e2 in raw_edges:
            if e1 is e2:
                continue
            if e1["orientation"] != e2["orientation"]:
                continue

            if e1["orientation"] == "horizontal" and e1["y1"] == e2["y1"]:
                y = e1["y1"]
                a1, a2 = sorted([e1["x1"], e1["x2"]])
                b1, b2 = sorted([e2["x1"], e2["x2"]])
                if max(a1, b1) < min(a2, b2):
                    horizontal_lines[y].update([a1, a2, b1, b2])

            if e1["orientation"] == "vertical" and e1["x1"] == e2["x1"]:
                x = e1["x1"]
                a1, a2 = sorted([e1["y1"], e1["y2"]])
                b1, b2 = sorted([e2["y1"], e2["y2"]])
                if max(a1, b1) < min(a2, b2):
                    vertical_lines[x].update([a1, a2, b1, b2])

    # ---------- Split each edge into atomic segments ----------
    atomic_segments = []

    for e in raw_edges:
        if e["orientation"] == "horizontal":
            y = e["y1"]
            x_start, x_end = sorted([e["x1"], e["x2"]])
            xs = sorted(horizontal_lines[y])

            for i in range(len(xs) - 1):
                sx1 = xs[i]
                sx2 = xs[i + 1]
                if sx1 >= x_start and sx2 <= x_end and sx2 > sx1:
                    atomic_segments.append({
                        "seg": normalize_segment(sx1, y, sx2, y),
                        "room_name": e["room_name"],
                        "room_type": e["room_type"],
                    })
        else:
            x = e["x1"]
            y_start, y_end = sorted([e["y1"], e["y2"]])
            ys = sorted(vertical_lines[x])

            for i in range(len(ys) - 1):
                sy1 = ys[i]
                sy2 = ys[i + 1]
                if sy1 >= y_start and sy2 <= y_end and sy2 > sy1:
                    atomic_segments.append({
                        "seg": normalize_segment(x, sy1, x, sy2),
                        "room_name": e["room_name"],
                        "room_type": e["room_type"],
                    })

    # ---------- Group owners per atomic segment ----------
    edge_map = {}
    for a in atomic_segments:
        edge_map.setdefault(a["seg"], []).append({
            "room_name": a["room_name"],
            "room_type": a["room_type"],
        })

    # ---------- Build final walls ----------
    walls = []

    for seg, owners in edge_map.items():
        x1, y1, x2, y2 = seg
        is_exterior, facade = on_outer_perimeter(seg, house_width, house_depth)

        unique_rooms = []
        seen = set()
        for o in owners:
            if o["room_name"] not in seen:
                seen.add(o["room_name"])
                unique_rooms.append(o)

        if is_exterior:
            walls.append({
                "id": f"wall_{len(walls)+1}",
                "type": "exterior",
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "orientation": segment_orientation(seg),
                "length": segment_length(seg),
                "thickness": EXTERIOR_WALL_THICKNESS,
                "rooms": [o["room_name"] for o in unique_rooms],
                "facade": facade,
                "window_allowed": True,
            })
        elif len(unique_rooms) >= 2:
            walls.append({
                "id": f"wall_{len(walls)+1}",
                "type": "interior",
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "orientation": segment_orientation(seg),
                "length": segment_length(seg),
                "thickness": INTERIOR_WALL_THICKNESS,
                "rooms": [o["room_name"] for o in unique_rooms[:2]],
                "facade": None,
                "window_allowed": False,
            })
        else:
            walls.append({
                "id": f"wall_{len(walls)+1}",
                "type": "interior",
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "orientation": segment_orientation(seg),
                "length": segment_length(seg),
                "thickness": INTERIOR_WALL_THICKNESS,
                "rooms": [o["room_name"] for o in unique_rooms],
                "facade": None,
                "window_allowed": False,
            })

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

        # front door: prefer south living-room wall only
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

def validate_required_corridor_contacts(layout):
    rooms = layout["rooms"]
    corridor = next((r for r in rooms if r["type"] == "corridor"), None)
    if not corridor:
        return False, "Missing corridor"

    required_types = {
        "master_bedroom",
        "secondary_bedroom",
        "bathroom",
        "wc",
        "laundry",
        "storage",
        "garage",
    }

    for room in rooms:
        if room["type"] in required_types:
            if not rooms_touch(room, corridor):
                return False, f"{room['name']} must touch corridor"

    return True, "OK"

def build_corridor_shapes(house_width, house_depth, shape_type="straight"):
    cx = house_width / 2
    cy = house_depth / 2

    if shape_type == "straight":
        parts = [
            {"x": snap(cx - 0.65), "y": snap(cy - 1.25), "w": 1.3, "h": 2.5}
        ]
    elif shape_type == "L":
        parts = [
            {"x": snap(cx - 0.65), "y": snap(cy - 1.25), "w": 1.3, "h": 2.5},
            {"x": snap(cx - 0.65), "y": snap(cy - 1.25), "w": 3.0, "h": 1.3}
        ]
    elif shape_type == "T":
        parts = [
            {"x": snap(cx - 0.65), "y": snap(cy - 1.25), "w": 1.3, "h": 2.5},
            {"x": snap(cx - 1.5), "y": snap(cy + 0.2), "w": 3.0, "h": 1.3}
        ]
    else:
        parts = [
            {"x": snap(cx - 0.65), "y": snap(cy - 1.25), "w": 1.3, "h": 2.5}
        ]

    return parts

SIM_GRID = 0.1
CIRCLE_RADIUS = 0.3


def point_in_room(px, py, room):
    return (
        room["x"] <= px <= room["x"] + room["w"]
        and room["y"] <= py <= room["y"] + room["h"]
    )


def room_center(room):
    return (
        room["x"] + room["w"] / 2,
        room["y"] + room["h"] / 2
    )


def to_cell(x, y):
    return (int(round(x / SIM_GRID)), int(round(y / SIM_GRID)))


def to_world(i, j):
    return (i * SIM_GRID, j * SIM_GRID)

def build_blocked_cells(layout):
    blocked = set()
    walls = layout.get("walls", [])
    house = layout["house"]

    inflate = CIRCLE_RADIUS

    for wall in walls:
        x1, y1, x2, y2 = wall["x1"], wall["y1"], wall["x2"], wall["y2"]
        t = wall["thickness"]

        if wall["orientation"] == "horizontal":
            min_x = min(x1, x2)
            max_x = max(x1, x2)
            min_y = y1 - t / 2
            max_y = y1 + t / 2
        else:
            min_x = x1 - t / 2
            max_x = x1 + t / 2
            min_y = min(y1, y2)
            max_y = max(y1, y2)

        # inflate by circle radius
        min_x -= inflate
        max_x += inflate
        min_y -= inflate
        max_y += inflate

        i1, j1 = to_cell(min_x, min_y)
        i2, j2 = to_cell(max_x, max_y)

        for i in range(i1, i2 + 1):
            for j in range(j1, j2 + 1):
                blocked.add((i, j))

    return blocked

def carve_doors_from_blocked(blocked, layout):
    walls_by_id = {w["id"]: w for w in layout.get("walls", [])}
    circulation = layout.get("circulation", {})
    doors = circulation.get("doors", [])

    for door in doors:
        wall = walls_by_id.get(door["wall_id"])
        if not wall:
            continue

        width = door.get("width", 0.9)
        cx = (wall["x1"] + wall["x2"]) / 2
        cy = (wall["y1"] + wall["y2"]) / 2

        if wall["orientation"] == "horizontal":
            min_x = cx - width / 2 - CIRCLE_RADIUS
            max_x = cx + width / 2 + CIRCLE_RADIUS
            min_y = cy - wall["thickness"] / 2 - CIRCLE_RADIUS
            max_y = cy + wall["thickness"] / 2 + CIRCLE_RADIUS
        else:
            min_x = cx - wall["thickness"] / 2 - CIRCLE_RADIUS
            max_x = cx + wall["thickness"] / 2 + CIRCLE_RADIUS
            min_y = cy - width / 2 - CIRCLE_RADIUS
            max_y = cy + width / 2 + CIRCLE_RADIUS

        i1, j1 = to_cell(min_x, min_y)
        i2, j2 = to_cell(max_x, max_y)

        for i in range(i1, i2 + 1):
            for j in range(j1, j2 + 1):
                blocked.discard((i, j))

    return blocked

def build_walkable_cells(layout):
    house = layout["house"]
    rooms = layout["rooms"]

    walkable = set()

    i_max = int(math.ceil(house["width"] / SIM_GRID))
    j_max = int(math.ceil(house["depth"] / SIM_GRID))

    for i in range(i_max + 1):
        for j in range(j_max + 1):
            x, y = to_world(i, j)

            if x < 0 or y < 0 or x > house["width"] or y > house["depth"]:
                continue

            for room in rooms:
                if point_in_room(x, y, room):
                    walkable.add((i, j))
                    break

    blocked = build_blocked_cells(layout)
    blocked = carve_doors_from_blocked(blocked, layout)

    return walkable - blocked

from collections import deque


def bfs_path_exists(walkable, start, goal):
    if start not in walkable or goal not in walkable:
        return False

    q = deque([start])
    seen = {start}

    directions = [(1,0), (-1,0), (0,1), (0,-1)]

    while q:
        cur = q.popleft()
        if cur == goal:
            return True

        for dx, dy in directions:
            nxt = (cur[0] + dx, cur[1] + dy)
            if nxt in walkable and nxt not in seen:
                seen.add(nxt)
                q.append(nxt)

    return False

def validate_circle_circulation(layout):
    rooms = layout["rooms"]
    living = next((r for r in rooms if r["type"] == "living_room"), None)

    if not living:
        return False, "Missing living room"

    walkable = build_walkable_cells(layout)
    start = to_cell(*room_center(living))

    for room in rooms:
        if room["name"] == living["name"]:
            continue

        target = to_cell(*room_center(room))

        if not bfs_path_exists(walkable, start, target):
            return False, f"0.6 m circle cannot reach {room['name']} from living room"

    return True, "OK"

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
    layout["corridor_rules"] = {
        "max_width_m": 1.5,
        "max_length_m": 3.0,
        "must_be_central": True,
        "required_room_types_touching_corridor": [
            "master_bedroom",
            "secondary_bedroom",
            "bathroom",
            "wc",
            "laundry",
            "storage"
        ]
    }
    return layout

def has_all_required_rooms(layout, room_program):
    actual_names = sorted(r["name"] for r in layout.get("rooms", []))
    expected_names = sorted(r["name"] for r in room_program)
    return actual_names == expected_names

def fallback_corridor_compact_layout(room_program, house_width, house_depth):
    rooms = []

    corridor = {
        "name": "corridor",
        "type": "corridor",
        "x": snap((house_width - 1.5) / 2),
        "y": snap((house_depth - 2.5) / 2),
        "w": 1.5,
        "h": 2.5,
    }
    rooms.append(corridor)

    def make_room(name, room_type, x, y, w, h):
        min_w, min_h = room_min_dimensions()[room_type]
        return {
            "name": name,
            "type": room_type,
            "x": snap(x),
            "y": snap(y),
            "w": snap(max(w, min_w)),
            "h": snap(max(h, min_h)),
        }

    living = next(r for r in room_program if r["type"] == "living_room")
    kitchen = next(r for r in room_program if r["type"] == "kitchen")
    bedrooms = [r for r in room_program if r["type"] in ["master_bedroom", "secondary_bedroom"]]
    services = [r for r in room_program if r["type"] in ["bathroom", "wc", "laundry", "storage"]]
    garage = next((r for r in room_program if r["type"] == "garage"), None)

    # South: living + kitchen
    south_h = corridor["y"]
    kitchen_w = 3.5
    living_w = house_width - kitchen_w

    rooms.append(make_room(living["name"], "living_room", 0, 0, living_w, south_h))
    rooms.append(make_room(kitchen["name"], "kitchen", living_w, 0, kitchen_w, south_h))

    # West corridor side: bathroom + wc
    west_x = 0
    west_w = corridor["x"]
    west_y = corridor["y"]

    west_services = [r for r in services if r["type"] in ["bathroom", "wc"]]
    y_cursor = west_y
    for r in west_services:
        min_w, min_h = room_min_dimensions()[r["type"]]
        rooms.append(make_room(r["name"], r["type"], west_x, y_cursor, west_w, min_h))
        y_cursor += snap(min_h)

    # East corridor side: laundry + storage
    east_x = corridor["x"] + corridor["w"]
    east_w = house_width - east_x

    east_services = [r for r in services if r["type"] in ["laundry", "storage"]]
    y_cursor = corridor["y"]
    for r in east_services:
        min_w, min_h = room_min_dimensions()[r["type"]]
        rooms.append(make_room(r["name"], r["type"], east_x, y_cursor, east_w, min_h))
        y_cursor += snap(min_h)

    # North: bedrooms across full width, all touching corridor
    north_y = corridor["y"] + corridor["h"]
    north_h = house_depth - north_y

    if bedrooms:
        bw = house_width / len(bedrooms)
        for i, b in enumerate(bedrooms):
            rooms.append(make_room(b["name"], b["type"], i * bw, north_y, bw, north_h))

    # Garage: east side, directly below/above east service strip and touching circulation side
    if garage:
        garage_w = max(room_min_dimensions()["garage"][0], east_w)
        garage_h = max(room_min_dimensions()["garage"][1], house_depth - (corridor["y"] + corridor["h"] + 0.5))
        rooms.append(
            make_room(
                garage["name"],
                "garage",
                east_x,
                max(north_y, y_cursor),
                east_w,
                house_depth - max(north_y, y_cursor),
            )
        )

    return {
        "house": {"width": house_width, "depth": house_depth},
        "rooms": rooms
    }

def generate_layout(house_data):
    total_area = float(house_data.get("area_m2", 120))
    slab_candidates = estimate_house_rectangles(total_area)
    room_program = build_room_program(house_data)

    house_width, house_depth = slab_candidates[0]
    layout = None

    try:
        candidate = ask_openai_for_layout(house_data, room_program, house_width, house_depth)

        if "house" not in candidate:
            candidate["house"] = {}

        candidate["house"]["width"] = house_width
        candidate["house"]["depth"] = house_depth

        candidate["rooms"] = [snap_room(r) for r in candidate["rooms"]]
        candidate["rooms"] = ensure_minimums(candidate["rooms"])
        candidate = resolve_overlaps(candidate, house_width, house_depth)

        if has_all_required_rooms(candidate, room_program):
            layout = candidate

    except Exception as e:
        valid, msg = validate_layout(layout, room_program, house_width, house_depth)
        valid_adj, adj_msg = validate_adjacency(layout)
        corridor_ok, corridor_msg = validate_corridor_position(layout, house_width, house_depth)
        area_ok, area_msg = validate_total_area_usage(layout, total_area)
        overlap_ok, overlap_msg = validate_no_overlap_strict(layout)
        required_corridor_ok, required_corridor_msg = validate_required_corridor_contacts(layout)

        layout = add_surface_labels(layout)
        layout = build_shared_walls(layout)
        layout = build_circulation_plan(layout)

        circle_ok, circle_msg = validate_circle_circulation(layout)

        if not (valid and valid_adj and corridor_ok and area_ok and overlap_ok and required_corridor_ok and circle_ok):
            layout = fallback_corridor_compact_layout(room_program, house_width, house_depth)
            layout["rooms"] = ensure_minimums(layout["rooms"])
            layout = resolve_overlaps(layout, house_width, house_depth)
            layout = add_surface_labels(layout)
            layout = build_shared_walls(layout)
            layout = build_circulation_plan(layout)
            circle_ok, circle_msg = validate_circle_circulation(layout)

    if layout is None:
        layout = fallback_grid_layout(room_program, house_width, house_depth)
        layout["rooms"] = ensure_minimums(layout["rooms"])
        layout = resolve_overlaps(layout, house_width, house_depth)

    layout = add_surface_labels(layout)
    layout = build_shared_walls(layout)
    layout = build_circulation_plan(layout)

    circle_ok, circle_msg = validate_circle_circulation(layout)
    layout["circulation_check"] = {
        "circle_diameter_m": 0.6,
        "success": circle_ok,
        "message": circle_msg
    }

    layout = add_metadata(layout)
    return layout