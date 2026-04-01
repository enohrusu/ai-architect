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
        project_folder = extra_args[0]
    else:
        raise ValueError("Missing project folder argument.")
else:
    raise ValueError("Project folder argument not provided.")

project_root = os.getcwd()
layout_file = os.path.join(project_folder, "layout_data.json")

# ---------- Clean scene ----------
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

with open(layout_file, "r", encoding="utf-8") as f:
    layout_data = json.load(f)

rooms = layout_data["rooms"]

wall_thickness = 0.2
wall_height = 3.0

door_height = 2.2
door_width = 1.2
door_depth = 0.5

window_height = 1.0
window_width = 1.4
window_depth = 0.5
window_z = 1.6

# ---------- Materials ----------
def get_or_create_material(name, color):
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name=name)

    if hasattr(material, "use_nodes"):
        material.use_nodes = True

    if material.node_tree:
        bsdf = material.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = color

    return material

floor_material = get_or_create_material("FloorMaterial", (0.8, 0.8, 0.8, 1.0))
wall_material = get_or_create_material("WallMaterial", (0.9, 0.9, 0.95, 1.0))
door_material = get_or_create_material("DoorMaterial", (0.45, 0.25, 0.1, 1.0))
window_material = get_or_create_material("WindowMaterial", (0.4, 0.7, 0.9, 0.5))

# ---------- Bounds ----------
min_x = min(room["x"] for room in rooms)
min_y = min(room["y"] for room in rooms)
max_x = max(room["x"] + room["w"] for room in rooms)
max_y = max(room["y"] + room["h"] for room in rooms)

floor_width = max_x - min_x
floor_depth = max_y - min_y
center_x = min_x + floor_width / 2
center_y = min_y + floor_depth / 2

corridor = next((room for room in rooms if room["name"] == "corridor"), None)

# ---------- Storage ----------
wall_objects = []
door_specs = []
window_specs = []

# ---------- Floor slab ----------
bpy.ops.mesh.primitive_cube_add(location=(center_x, center_y, -0.1))
floor = bpy.context.active_object
floor.name = "floor_slab"
floor.scale[0] = floor_width / 2
floor.scale[1] = floor_depth / 2
floor.scale[2] = 0.1
floor.data.materials.append(floor_material)

# ---------- Walls ----------
def create_wall(name, x, y, w, d, h):
    bpy.ops.mesh.primitive_cube_add(location=(x, y, h / 2))
    wall = bpy.context.active_object
    wall.name = name
    wall.scale[0] = w / 2
    wall.scale[1] = d / 2
    wall.scale[2] = h / 2
    wall.data.materials.append(wall_material)
    wall_objects.append(wall)
    return wall

# ---------- Labels ----------
def add_room_label(text, x, y, z=3.3):
    bpy.ops.object.text_add(location=(x, y, z))
    text_obj = bpy.context.active_object
    text_obj.name = f"label_{text}"
    text_obj.data.body = text
    text_obj.data.size = 0.5

# ---------- Doors ----------
def create_door_visual(name, x, y, rot_z=0):
    bpy.ops.mesh.primitive_cube_add(location=(x, y, door_height / 2))
    door = bpy.context.active_object
    door.name = name
    door.scale[0] = 0.1
    door.scale[1] = 0.6
    door.scale[2] = door_height / 2
    door.rotation_euler[2] = math.radians(rot_z)
    door.data.materials.append(door_material)
    return door

def add_door_spec(name, x, y, rot_z=0):
    door_specs.append({
        "name": name,
        "x": x,
        "y": y,
        "rot_z": rot_z
    })

# ---------- Windows ----------
def create_window_visual(name, x, y, rot_z=0):
    bpy.ops.mesh.primitive_cube_add(location=(x, y, window_z))
    window = bpy.context.active_object
    window.name = name
    window.rotation_euler[2] = math.radians(rot_z)

    if rot_z == 90:
        window.scale[0] = window_width / 2
        window.scale[1] = 0.05
    else:
        window.scale[0] = 0.05
        window.scale[1] = window_width / 2

    window.scale[2] = window_height / 2
    window.data.materials.append(window_material)
    return window

def add_window_spec(name, x, y, rot_z=0):
    window_specs.append({
        "name": name,
        "x": x,
        "y": y,
        "rot_z": rot_z
    })

# ---------- Create walls + labels ----------
for room in rooms:
    name = room["name"]
    x = room["x"]
    y = room["y"]
    w = room["w"]
    h = room["h"]

    left_x = x
    right_x = x + w
    bottom_y = y
    top_y = y + h

    room_center_x = x + w / 2
    room_center_y = y + h / 2

    create_wall(f"{name}_left_wall", left_x, room_center_y, wall_thickness, h, wall_height)
    create_wall(f"{name}_right_wall", right_x, room_center_y, wall_thickness, h, wall_height)
    create_wall(f"{name}_bottom_wall", room_center_x, bottom_y, w, wall_thickness, wall_height)
    create_wall(f"{name}_top_wall", room_center_x, top_y, w, wall_thickness, wall_height)

    add_room_label(name, room_center_x, room_center_y)

# ---------- Front door ----------
add_door_spec("front_door", center_x, min_y, 90)
create_door_visual("front_door_visual", center_x, min_y, 90)

# ---------- Interior doors ----------
for room in rooms:
    name = room["name"]

    if name == "corridor":
        continue

    x = room["x"]
    y = room["y"]
    w = room["w"]
    h = room["h"]

    room_center_x = x + w / 2
    room_center_y = y + h / 2

    if name == "living_room":
        add_door_spec(f"{name}_door", room_center_x, y + h, 90)
        create_door_visual(f"{name}_door_visual", room_center_x, y + h, 90)

    elif name == "kitchen":
        add_door_spec(f"{name}_door", x, room_center_y, 0)
        create_door_visual(f"{name}_door_visual", x, room_center_y, 0)

    elif name == "garage":
        add_door_spec(f"{name}_door", x, room_center_y, 0)
        create_door_visual(f"{name}_door_visual", x, room_center_y, 0)

    elif corridor:
        corridor_center_x = corridor["x"] + corridor["w"] / 2

        if room_center_x < corridor_center_x:
            add_door_spec(f"{name}_door", x + w, room_center_y, 0)
            create_door_visual(f"{name}_door_visual", x + w, room_center_y, 0)
        else:
            add_door_spec(f"{name}_door", x, room_center_y, 0)
            create_door_visual(f"{name}_door_visual", x, room_center_y, 0)

    else:
        add_door_spec(f"{name}_door", room_center_x, y, 90)
        create_door_visual(f"{name}_door_visual", room_center_x, y, 90)

# ---------- Outer windows ----------
outer_windows = [
    ("window_front_left", min_x + 2, min_y + 0.05, 90),
    ("window_front_right", max_x - 2, min_y + 0.05, 90),
    ("window_back_left", min_x + 2, max_y - 0.05, 90),
    ("window_back_right", max_x - 2, max_y - 0.05, 90),
    ("window_left_side", min_x + 0.05, center_y, 0),
    ("window_right_side", max_x - 0.05, center_y, 0),
]

for name, x, y, rot_z in outer_windows:
    add_window_spec(name, x, y, rot_z)
    create_window_visual(f"{name}_visual", x, y, rot_z)

# ---------- Door cutters ----------
def create_door_cutter(spec):
    x = spec["x"]
    y = spec["y"]
    rot_z = spec["rot_z"]

    bpy.ops.mesh.primitive_cube_add(location=(x, y, door_height / 2))
    cutter = bpy.context.active_object
    cutter.name = f"{spec['name']}_cutter"

    if rot_z == 90:
        cutter.scale[0] = door_width / 2
        cutter.scale[1] = door_depth / 2
    else:
        cutter.scale[0] = door_depth / 2
        cutter.scale[1] = door_width / 2

    cutter.scale[2] = door_height / 2
    cutter.display_type = 'WIRE'
    cutter.hide_render = True
    return cutter

# ---------- Window cutters ----------
def create_window_cutter(spec):
    x = spec["x"]
    y = spec["y"]
    rot_z = spec["rot_z"]

    bpy.ops.mesh.primitive_cube_add(location=(x, y, window_z))
    cutter = bpy.context.active_object
    cutter.name = f"{spec['name']}_cutter"

    if rot_z == 90:
        cutter.scale[0] = window_width / 2
        cutter.scale[1] = window_depth / 2
    else:
        cutter.scale[0] = window_depth / 2
        cutter.scale[1] = window_width / 2

    cutter.scale[2] = window_height / 2
    cutter.display_type = 'WIRE'
    cutter.hide_render = True
    return cutter

# ---------- Apply booleans ----------
for spec in door_specs:
    cutter = create_door_cutter(spec)
    for wall in wall_objects:
        modifier = wall.modifiers.new(name=f"bool_{cutter.name}", type='BOOLEAN')
        modifier.operation = 'DIFFERENCE'
        modifier.object = cutter

for spec in window_specs:
    cutter = create_window_cutter(spec)
    for wall in wall_objects:
        modifier = wall.modifiers.new(name=f"bool_{cutter.name}", type='BOOLEAN')
        modifier.operation = 'DIFFERENCE'
        modifier.object = cutter

# ---------- Camera ----------
bpy.ops.object.camera_add(location=(center_x - 12, center_y - 12, 14))
camera = bpy.context.active_object
camera.name = "MainCamera"
camera.rotation_euler = (math.radians(60), 0, math.radians(-45))
bpy.context.scene.camera = camera

# ---------- Light ----------
bpy.ops.object.light_add(type='SUN', location=(center_x, center_y, 10))
sun = bpy.context.active_object
sun.name = "SunLight"
sun.data.energy = 3.0


# ---------- Save Blender file ----------
output_blend = os.path.join(project_folder, "generated_house.blend")
bpy.ops.wm.save_as_mainfile(filepath=output_blend)

# ---------- Export GLB ----------
glb_path = os.path.join(project_folder, "generated_house.glb")
bpy.ops.export_scene.gltf(
    filepath=glb_path,
    export_format='GLB'
)

print(f"Blender file saved to: {output_blend}")
print(f"GLB exported to: {glb_path}")
print("Blender house generation complete.")