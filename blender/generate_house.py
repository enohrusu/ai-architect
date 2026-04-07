import bpy
import json
import os
import math
import sys

# ---------- Read project folder from command line ----------
argv = sys.argv
if "--" in argv:
    extra_args = argv[argv.index("--") + 1:]
    if extra_args:
        project_folder = os.path.abspath(extra_args[0])
    else:
        raise ValueError("Missing project folder argument.")
else:
    raise ValueError("Project folder argument not provided.")

layout_file = os.path.join(project_folder, "layout_data.json")

if not os.path.exists(layout_file):
    raise FileNotFoundError(f"layout_data.json not found: {layout_file}")

# ---------- Scene setup ----------
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

bpy.context.scene.unit_settings.system = 'METRIC'
bpy.context.scene.unit_settings.scale_length = 1.0

with open(layout_file, "r", encoding="utf-8") as f:
    layout_data = json.load(f)

rooms = layout_data["rooms"]
walls = layout_data.get("walls", [])
circulation = layout_data.get("circulation", {})
door_plan = circulation.get("doors", [])

house = layout_data.get("house", {})
house_width = house.get("width", 10)
house_depth = house.get("depth", 10)

center_x = house_width / 2
center_y = house_depth / 2

exterior_wall_thickness = 0.20
if walls:
    exterior_thicknesses = [w["thickness"] for w in walls if w["type"] == "exterior"]
    if exterior_thicknesses:
        exterior_wall_thickness = max(exterior_thicknesses)

# ---------- Parameters ----------
WALL_HEIGHT = 3.0
FLOOR_THICKNESS = 0.18
CEILING_THICKNESS = 0.12
ROOF_THICKNESS = 0.18

DOOR_HEIGHT = 2.2
DOOR_WIDTH = 1.0
DOOR_DEPTH = 0.4

WINDOW_HEIGHT = 1.2
WINDOW_WIDTH = 1.6
WINDOW_DEPTH = 0.35
WINDOW_Z = 1.5

# ---------- Materials ----------
def get_or_create_material(name, base_color, roughness=0.5, metallic=0.0, transmission=0.0, alpha=1.0):
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name=name)

    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    for node in list(nodes):
        nodes.remove(node)

    output = nodes.new(type="ShaderNodeOutputMaterial")
    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    output.location = (250, 0)

    bsdf.inputs["Base Color"].default_value = (*base_color, alpha)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic

    if "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = transmission
    elif "Transmission" in bsdf.inputs:
        bsdf.inputs["Transmission"].default_value = transmission

    if alpha < 1.0:
        if hasattr(material, "blend_method"):
            material.blend_method = 'BLEND'
        if hasattr(material, "surface_render_method"):
            material.surface_render_method = 'DITHERED'
        if "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = alpha

    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    return material


floor_material = get_or_create_material("FloorConcrete", (0.82, 0.82, 0.80), roughness=0.9)
ceiling_material = get_or_create_material("CeilingWhite", (0.96, 0.96, 0.96), roughness=0.8)
wall_material = get_or_create_material("WallPlaster", (0.88, 0.88, 0.90), roughness=0.85)
door_material = get_or_create_material("DoorWood", (0.42, 0.27, 0.14), roughness=0.6)
window_material = get_or_create_material("WindowGlass", (0.72, 0.86, 0.95), roughness=0.08, transmission=1.0, alpha=0.35)
roof_material = get_or_create_material("RoofConcrete", (0.55, 0.55, 0.57), roughness=0.85)
frame_material = get_or_create_material("WindowFrame", (0.2, 0.2, 0.2), roughness=0.45)

# ---------- Collections ----------
wall_objects = []
door_specs = []
window_specs = []

# ---------- Helpers ----------
def add_material(obj, material):
    if obj.data.materials:
        obj.data.materials[0] = material
    else:
        obj.data.materials.append(material)

OPENING_CLEARANCE = 0.20
wall_reserved_spans = {}

def get_wall_by_id(wall_id):
    return next((w for w in walls if w["id"] == wall_id), None)

def get_wall_span_position(wall_data, x, y):
    if wall_data["orientation"] == "horizontal":
        return x - min(wall_data["x1"], wall_data["x2"])
    return y - min(wall_data["y1"], wall_data["y2"])


def reserve_span(wall_id, center_pos, half_size):
    span_min = center_pos - half_size - OPENING_CLEARANCE
    span_max = center_pos + half_size + OPENING_CLEARANCE
    wall_reserved_spans.setdefault(wall_id, []).append((span_min, span_max))


def span_is_free(wall_id, center_pos, half_size, wall_length):
    span_min = center_pos - half_size - OPENING_CLEARANCE
    span_max = center_pos + half_size + OPENING_CLEARANCE

    if span_min < OPENING_CLEARANCE or span_max > wall_length - OPENING_CLEARANCE:
        return False

    for reserved_min, reserved_max in wall_reserved_spans.get(wall_id, []):
        if not (span_max <= reserved_min or span_min >= reserved_max):
            return False

    return True

def create_box(name, location, scale, material=None):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    if material:
        add_material(obj, material)
    return obj

def add_room_label(text, surface, x, y, z=0.03):
    bpy.ops.object.text_add(location=(x, y, z))
    text_obj = bpy.context.active_object
    text_obj.name = f"Label_{text}"
    text_obj.data.body = f"{text.replace('_', ' ')}\\n{surface:.1f} m²"
    text_obj.data.size = 0.28
    text_obj.data.align_x = 'CENTER'
    text_obj.data.align_y = 'CENTER'
    text_obj.rotation_euler[0] = math.radians(90)   # flat on floor
    text_obj.rotation_euler[1] = 0
    text_obj.rotation_euler[2] = 0

def create_wall_from_segment(wall_data):
    x1 = wall_data["x1"]
    y1 = wall_data["y1"]
    x2 = wall_data["x2"]
    y2 = wall_data["y2"]
    thickness = wall_data["thickness"]

    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2

    if wall_data["orientation"] == "horizontal":
        length = abs(x2 - x1)
        scale = (length / 2, thickness / 2, WALL_HEIGHT / 2)
    else:
        length = abs(y2 - y1)
        scale = (thickness / 2, length / 2, WALL_HEIGHT / 2)

    wall = create_box(
        name=wall_data["id"],
        location=(cx, cy, WALL_HEIGHT / 2),
        scale=scale,
        material=wall_material
    )
    wall_objects.append(wall)
    return wall

def create_garage_door_visual(name, x, y, rot_z=0):
    garage_door = create_box(
        name=name,
        location=(x, y, 1.1),
        scale=(0.08, 1.4, 1.1),
        material=door_material
    )
    garage_door.rotation_euler[2] = math.radians(rot_z)
    return garage_door


def add_garage_door_spec(name, x, y, rot_z=0):
    door_specs.append({
        "name": name,
        "x": x,
        "y": y,
        "rot_z": rot_z,
        "width": 2.6,
        "height": 2.2,
        "depth": 0.5
    })

def create_door_visual(name, x, y, rot_z=0):
    door = create_box(
        name=name,
        location=(x, y, DOOR_HEIGHT / 2),
        scale=(0.06, DOOR_WIDTH / 2, DOOR_HEIGHT / 2),
        material=door_material
    )
    door.rotation_euler[2] = math.radians(rot_z)
    return door

def add_door_spec(name, x, y, rot_z=0):
    door_specs.append({
        "name": name,
        "x": x,
        "y": y,
        "rot_z": rot_z
    })

def create_window_visual(name, x, y, rot_z=0, room_type=None, width=None, height=None, z_pos=None):
    if width is None or height is None or z_pos is None:
        width = 1.0
        height = 1.6
        z_pos = 1.5

        if room_type in ["bathroom", "wc"]:
            width = 0.6
            height = 0.9
            z_pos = 1.8
        elif room_type in ["master_bedroom", "secondary_bedroom"]:
            width = 1.0
            height = 1.5
            z_pos = 1.4
        elif room_type == "kitchen":
            width = 0.9
            height = 1.3
            z_pos = 1.5
        elif room_type == "living_room":
            width = 1.2
            height = 1.8
            z_pos = 1.3

    glass = create_box(
        name=name,
        location=(x, y, z_pos),
        scale=(0.03, width / 2, height / 2),
        material=window_material
    )
    glass.rotation_euler[2] = math.radians(rot_z)

    frame = create_box(
        name=f"{name}_frame",
        location=(x, y, z_pos),
        scale=(0.04, width / 2 + 0.03, height / 2 + 0.03),
        material=frame_material
    )
    frame.rotation_euler[2] = math.radians(rot_z)

    return glass

def add_window_spec(name, x, y, rot_z=0, width=1.0, height=1.6, z_pos=1.5, wall_id=None):
    window_specs.append({
        "name": name,
        "x": x,
        "y": y,
        "rot_z": rot_z,
        "width": width,
        "height": height,
        "z_pos": z_pos,
        "wall_id": wall_id,
    })

def create_door_cutter(spec):
    x = spec["x"]
    y = spec["y"]
    rot_z = spec["rot_z"]
    width = spec.get("width", DOOR_WIDTH)
    height = spec.get("height", DOOR_HEIGHT)
    depth = spec.get("depth", DOOR_DEPTH)

    cutter = create_box(
        name=f"{spec['name']}_cutter",
        location=(x, y, height / 2),
        scale=(depth / 2, width / 2, height / 2)
    )
    cutter.rotation_euler[2] = math.radians(rot_z)
    cutter.display_type = 'WIRE'
    cutter.hide_render = True
    return cutter

def create_window_cutter(spec):
    x = spec["x"]
    y = spec["y"]
    rot_z = spec["rot_z"]
    width = spec.get("width", 1.0)
    height = spec.get("height", 1.6)
    z_pos = spec.get("z_pos", 1.5)

    cutter = create_box(
        name=f"{spec['name']}_cutter",
        location=(x, y, z_pos),
        scale=(WINDOW_DEPTH / 2, width / 2, height / 2)
    )
    cutter.rotation_euler[2] = math.radians(rot_z)
    cutter.display_type = 'WIRE'
    cutter.hide_render = True
    return cutter

def point_on_segment_center(wall_data, offset=0.0):
    x1 = wall_data["x1"]
    y1 = wall_data["y1"]
    x2 = wall_data["x2"]
    y2 = wall_data["y2"]

    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2

    if wall_data["orientation"] == "horizontal":
        return cx, cy + offset
    return cx + offset, cy



# ---------- Structural slabs ----------
floor = create_box(
    name="FloorSlab",
    location=(center_x, center_y, -FLOOR_THICKNESS / 2),
    scale=((house_width - exterior_wall_thickness) / 2, (house_depth - exterior_wall_thickness) / 2, FLOOR_THICKNESS / 2),
    material=floor_material
)

ceiling = create_box(
    name="CeilingSlab",
    location=(center_x, center_y, WALL_HEIGHT + CEILING_THICKNESS / 2),
    scale=((house_width - exterior_wall_thickness) / 2, (house_depth - exterior_wall_thickness) / 2, CEILING_THICKNESS / 2),
    material=ceiling_material
)

roof = create_box(
    name="RoofSlab",
    location=(center_x, center_y, WALL_HEIGHT + CEILING_THICKNESS + ROOF_THICKNESS / 2),
    scale=(house_width / 2 + 0.15, house_depth / 2 + 0.15, ROOF_THICKNESS / 2),
    material=roof_material
)

# ---------- Room labels ----------
for room in rooms:
    room_center_x = room["x"] + room["w"] / 2
    room_center_y = room["y"] + room["h"] / 2
    add_room_label(room["name"], room.get("surface_m2", room["w"] * room["h"]), room_center_x, room_center_y)

# ---------- Shared walls ----------
for wall_data in walls:
    create_wall_from_segment(wall_data)

# ---------- Doors from circulation plan ----------
for door in door_plan:
    wall_data = get_wall_by_id(door["wall_id"])
    if not wall_data:
        continue

    door_width = door.get("width", DOOR_WIDTH)
    dx, dy = point_on_segment_center(wall_data, offset=0.0)
    rot = 90 if wall_data["orientation"] == "horizontal" else 0

    spec = {
        "name": f"{door['wall_id']}_door",
        "x": dx,
        "y": dy,
        "rot_z": rot,
        "width": door_width,
        "height": DOOR_HEIGHT,
        "depth": DOOR_DEPTH,
    }

    door_specs.append(spec)

    if door["type"] == "front":
        create_door_visual("Door_front", dx, dy, rot)
    elif "garage" in door.get("rooms", []):
        create_garage_door_visual(f"Door_{door['wall_id']}", dx, dy, rot)
    else:
        create_door_visual(f"Door_{door['wall_id']}", dx, dy, rot)

    local_pos = get_wall_span_position(wall_data, dx, dy)
    reserve_span(wall_data["id"], local_pos, door_width / 2)


# ---------- Windows only on exterior walls ----------
def window_dimensions_for_room_type(room_type):
    if room_type in ["bathroom", "wc"]:
        return 0.6, 0.9, 1.8
    if room_type in ["master_bedroom", "secondary_bedroom"]:
        return 1.0, 1.5, 1.4
    if room_type == "kitchen":
        return 0.9, 1.3, 1.5
    if room_type == "living_room":
        return 1.2, 1.8, 1.3
    return 0.9, 1.4, 1.5


def window_count_for_room_type(room_type, wall_length):
    if wall_length < 2.0:
        return 0
    if room_type == "living_room":
        return 2 if wall_length >= 4.8 else 1
    if room_type == "kitchen":
        return 1
    if room_type in ["master_bedroom", "secondary_bedroom"]:
        return 1
    if room_type in ["bathroom", "wc"]:
        return 1
    if room_type in ["laundry", "storage", "garage"]:
        return 0
    return 1


for wall_data in walls:
    if wall_data["type"] != "exterior":
        continue
    if not wall_data.get("window_allowed", False):
        continue

    wall_rooms = wall_data.get("rooms", [])
    if not wall_rooms:
        continue

    room_name = wall_rooms[0]
    room_data = next((r for r in rooms if r["name"] == room_name), None)
    if not room_data:
        continue

    room_type = room_data["type"]
    count = window_count_for_room_type(room_type, wall_data["length"])

    if count == 0:
        continue

    width, height, z_pos = window_dimensions_for_room_type(room_type)
    half_size = width / 2

    x1, y1, x2, y2 = wall_data["x1"], wall_data["y1"], wall_data["x2"], wall_data["y2"]
    rot = 90 if wall_data["orientation"] == "horizontal" else 0

    placed = 0
    attempts = max(3, count + 2)

    for i in range(attempts):
        if placed >= count:
            break

        t = (i + 1) / (attempts + 1)
        wx = x1 + (x2 - x1) * t
        wy = y1 + (y2 - y1) * t

        local_pos = get_wall_span_position(wall_data, wx, wy)

        if not span_is_free(wall_data["id"], local_pos, half_size, wall_data["length"]):
            continue

        add_window_spec(
            f"{wall_data['id']}_window_{placed+1}",
            wx,
            wy,
            rot,
            width=width,
            height=height,
            z_pos=z_pos,
            wall_id=wall_data["id"],
        )
        create_window_visual(
            f"Window_{wall_data['id']}_{placed+1}",
            wx,
            wy,
            rot,
            room_type=room_type,
            width=width,
            height=height,
            z_pos=z_pos,
        )

        reserve_span(wall_data["id"], local_pos, half_size)
        placed += 1

# ---------- Apply boolean cutters ----------
for spec in door_specs:
    cutter = create_door_cutter(spec)
    for wall in wall_objects:
        modifier = wall.modifiers.new(name=f"Bool_{cutter.name}", type='BOOLEAN')
        modifier.operation = 'DIFFERENCE'
        modifier.object = cutter

for spec in window_specs:
    cutter = create_window_cutter(spec)
    for wall in wall_objects:
        modifier = wall.modifiers.new(name=f"Bool_{cutter.name}", type='BOOLEAN')
        modifier.operation = 'DIFFERENCE'
        modifier.object = cutter

# ---------- Apply modifiers ----------
for wall in wall_objects:
    bpy.context.view_layer.objects.active = wall
    for mod in list(wall.modifiers):
        try:
            bpy.ops.object.modifier_apply(modifier=mod.name)
        except Exception:
            pass

# ---------- Cleanup cutters ----------
for obj in list(bpy.data.objects):
    if obj.name.endswith("_cutter"):
        bpy.data.objects.remove(obj, do_unlink=True)

# ---------- Camera ----------
bpy.ops.object.camera_add(location=(center_x - 16, center_y - 16, 14))
camera = bpy.context.active_object
camera.name = "MainCamera"
camera.rotation_euler = (math.radians(62), 0, math.radians(-45))
bpy.context.scene.camera = camera

# ---------- Light ----------
bpy.ops.object.light_add(type='SUN', location=(center_x, center_y, 12))
sun = bpy.context.active_object
sun.name = "SunLight"
sun.data.energy = 4.0

# ---------- Keep floor labels in .blend, remove from GLB ----------
for obj in list(bpy.data.objects):
    if obj.type == 'FONT':
        obj.hide_render = True

mesh_objs = [obj for obj in bpy.data.objects if obj.type == 'MESH']

bpy.ops.object.select_all(action='DESELECT')
for obj in mesh_objs:
    obj.select_set(True)

if mesh_objs:
    bpy.context.view_layer.objects.active = mesh_objs[0]
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

print("Number of objects in scene:", len(bpy.data.objects))
print("Number of walls:", len(walls))

# ---------- Save Blender file ----------
output_blend = os.path.join(project_folder, "generated_house.blend")
bpy.ops.wm.save_as_mainfile(filepath=output_blend)

# ---------- Export GLB ----------
glb_path = os.path.join(project_folder, "generated_house.glb")
bpy.ops.export_scene.gltf(
    filepath=glb_path,
    export_format='GLB',
    use_selection=False,
    export_apply=True,
    export_texcoords=True,
    export_normals=True,
    export_materials='EXPORT',
    export_cameras=False,
    export_lights=False
)

print(f"Blender file saved to: {output_blend}")
print(f"GLB exported to: {glb_path}")
print("Shared-wall Blender house generation complete.")