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

# ---------- Parameters ----------
WALL_THICKNESS = 0.22
WALL_HEIGHT = 3.0
FLOOR_THICKNESS = 0.18
CEILING_THICKNESS = 0.12
DOOR_HEIGHT = 2.2
DOOR_WIDTH = 1.0
DOOR_DEPTH = 0.4
WINDOW_HEIGHT = 1.2
WINDOW_WIDTH = 1.6
WINDOW_DEPTH = 0.35
WINDOW_Z = 1.5
ROOF_THICKNESS = 0.18
LABEL_HEIGHT = WALL_HEIGHT + 0.15

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

# ---------- Bounds ----------
min_x = min(room["x"] for room in rooms)
min_y = min(room["y"] for room in rooms)
max_x = max(room["x"] + room["w"] for room in rooms)
max_y = max(room["y"] + room["h"] for room in rooms)

house_width = max_x - min_x
house_depth = max_y - min_y
center_x = min_x + house_width / 2
center_y = min_y + house_depth / 2

corridor = next((room for room in rooms if room["name"] == "corridor"), None)

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

def create_box(name, location, scale, material=None):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    if material:
        add_material(obj, material)
    return obj

def add_room_label(text, surface, x, y, z=0.02):
    bpy.ops.object.text_add(location=(x, y, z))
    text_obj = bpy.context.active_object
    text_obj.name = f"Label_{text}"
    text_obj.data.body = f"{text.replace('_', ' ')}\\n{surface:.1f} m²"
    text_obj.data.size = 0.28
    text_obj.rotation_euler[0] = math.radians(90)
    text_obj.rotation_euler[2] = 0

def create_wall(name, x, y, w, d, h):
    wall = create_box(
        name=name,
        location=(x, y, h / 2),
        scale=(w / 2, d / 2, h / 2),
        material=wall_material
    )
    wall_objects.append(wall)
    return wall

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

def create_window_visual(name, x, y, rot_z=0):
    # Glass
    glass = create_box(
        name=name,
        location=(x, y, WINDOW_Z),
        scale=(0.03, WINDOW_WIDTH / 2, WINDOW_HEIGHT / 2),
        material=window_material
    )
    glass.rotation_euler[2] = math.radians(rot_z)

    # Simple frame
    frame = create_box(
        name=f"{name}_frame",
        location=(x, y, WINDOW_Z),
        scale=(0.04, WINDOW_WIDTH / 2 + 0.03, WINDOW_HEIGHT / 2 + 0.03),
        material=frame_material
    )
    frame.rotation_euler[2] = math.radians(rot_z)

    # Make inner glass visible in front
    return glass

def add_window_spec(name, x, y, rot_z=0):
    window_specs.append({
        "name": name,
        "x": x,
        "y": y,
        "rot_z": rot_z
    })

def create_door_cutter(spec):
    x = spec["x"]
    y = spec["y"]
    rot_z = spec["rot_z"]

    cutter = create_box(
        name=f"{spec['name']}_cutter",
        location=(x, y, DOOR_HEIGHT / 2),
        scale=(DOOR_DEPTH / 2, DOOR_WIDTH / 2, DOOR_HEIGHT / 2)
    )
    cutter.rotation_euler[2] = math.radians(rot_z)
    cutter.display_type = 'WIRE'
    cutter.hide_render = True
    return cutter

def create_window_cutter(spec):
    x = spec["x"]
    y = spec["y"]
    rot_z = spec["rot_z"]

    cutter = create_box(
        name=f"{spec['name']}_cutter",
        location=(x, y, WINDOW_Z),
        scale=(WINDOW_DEPTH / 2, WINDOW_WIDTH / 2, WINDOW_HEIGHT / 2)
    )
    cutter.rotation_euler[2] = math.radians(rot_z)
    cutter.display_type = 'WIRE'
    cutter.hide_render = True
    return cutter

# ---------- Structural slabs ----------
floor = create_box(
    name="FloorSlab",
    location=(center_x, center_y, -FLOOR_THICKNESS / 2),
    scale=(house_width / 2, house_depth / 2, FLOOR_THICKNESS / 2),
    material=floor_material
)

ceiling = create_box(
    name="CeilingSlab",
    location=(center_x, center_y, WALL_HEIGHT + CEILING_THICKNESS / 2),
    scale=(house_width / 2, house_depth / 2, CEILING_THICKNESS / 2),
    material=ceiling_material
)

roof = create_box(
    name="RoofSlab",
    location=(center_x, center_y, WALL_HEIGHT + CEILING_THICKNESS + ROOF_THICKNESS / 2),
    scale=(house_width / 2 + 0.15, house_depth / 2 + 0.15, ROOF_THICKNESS / 2),
    material=roof_material
)

# ---------- Room walls + labels ----------
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

    create_wall(f"Wall_{name}_left", left_x, room_center_y, WALL_THICKNESS, h, WALL_HEIGHT)
    create_wall(f"Wall_{name}_right", right_x, room_center_y, WALL_THICKNESS, h, WALL_HEIGHT)
    create_wall(f"Wall_{name}_bottom", room_center_x, bottom_y, w, WALL_THICKNESS, WALL_HEIGHT)
    create_wall(f"Wall_{name}_top", room_center_x, top_y, w, WALL_THICKNESS, WALL_HEIGHT)

    add_room_label(name, room.get("surface_m2", w * h), room_center_x, room_center_y)

# ---------- Front door ----------
add_door_spec("front_door", center_x, min_y, 90)
create_door_visual("Door_front", center_x, min_y, 90)

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
        create_door_visual(f"Door_{name}", room_center_x, y + h, 90)

    elif name == "kitchen":
        add_door_spec(f"{name}_door", x, room_center_y, 0)
        create_door_visual(f"Door_{name}", x, room_center_y, 0)

    elif name == "garage":
        add_door_spec(f"{name}_door", x, room_center_y, 0)
        create_door_visual(f"Door_{name}", x, room_center_y, 0)

    elif corridor:
        corridor_center_x = corridor["x"] + corridor["w"] / 2

        if room_center_x < corridor_center_x:
            add_door_spec(f"{name}_door", x + w, room_center_y, 0)
            create_door_visual(f"Door_{name}", x + w, room_center_y, 0)
        else:
            add_door_spec(f"{name}_door", x, room_center_y, 0)
            create_door_visual(f"Door_{name}", x, room_center_y, 0)

    else:
        add_door_spec(f"{name}_door", room_center_x, y, 90)
        create_door_visual(f"Door_{name}", room_center_x, y, 90)

# ---------- Outer windows ----------
outer_windows = [
    ("window_front_left", min_x + 2, min_y + 0.02, 90),
    ("window_front_right", max_x - 2, min_y + 0.02, 90),
    ("window_back_left", min_x + 2, max_y - 0.02, 90),
    ("window_back_right", max_x - 2, max_y - 0.02, 90),
    ("window_left_side", min_x + 0.02, center_y, 0),
    ("window_right_side", max_x - 0.02, center_y, 0),
]

for name, x, y, rot_z in outer_windows:
    add_window_spec(name, x, y, rot_z)
    create_window_visual(f"Window_{name}", x, y, rot_z)

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
for obj in bpy.data.objects:
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

# Remove text labels before export
for obj in list(bpy.data.objects):
    if obj.type == 'FONT':
        bpy.data.objects.remove(obj, do_unlink=True)

mesh_objs = [obj for obj in bpy.data.objects if obj.type == 'MESH']

bpy.ops.object.select_all(action='DESELECT')

for obj in mesh_objs:
    obj.select_set(True)

if mesh_objs:
    bpy.context.view_layer.objects.active = mesh_objs[0]
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

print("Number of objects in scene:", len(bpy.data.objects))

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
print("Blender house generation complete.")