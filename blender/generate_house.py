import bpy
import json
import os
import math
import sys

# ---------- Read project folder ----------
argv = sys.argv
if "--" in argv:
    project_folder = os.path.abspath(argv[argv.index("--") + 1])
else:
    raise ValueError("Missing project folder argument")

layout_file = os.path.join(project_folder, "layout_data.json")

if not os.path.exists(layout_file):
    raise FileNotFoundError(layout_file)

# ---------- Reset scene ----------
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

bpy.context.scene.unit_settings.system = 'METRIC'

# ---------- Load data ----------
with open(layout_file, "r") as f:
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

# ---------- Parameters ----------
WALL_HEIGHT = 3.0
FLOOR_THICKNESS = 0.18
CEILING_THICKNESS = 0.12
ROOF_THICKNESS = 0.18

DOOR_HEIGHT = 2.2
DOOR_WIDTH = 1.0

WINDOW_DEPTH = 0.35

# ---------- Materials ----------
def mat(name, color):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    return m

floor_mat = mat("Floor", (0.8, 0.8, 0.8))
wall_mat = mat("Wall", (0.9, 0.9, 0.9))
door_mat = mat("Door", (0.4, 0.25, 0.1))
glass_mat = mat("Glass", (0.7, 0.9, 1.0))
roof_mat = mat("Roof", (0.5, 0.5, 0.5))

# ---------- Helpers ----------
def cube(name, loc, scale, mat=None):
    bpy.ops.mesh.primitive_cube_add(location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = scale
    if mat:
        o.data.materials.append(mat)
    return o

def center(w):
    return ( (w["x1"]+w["x2"])/2, (w["y1"]+w["y2"])/2 )

def get_wall(id):
    return next((w for w in walls if w["id"] == id), None)

# ---------- Slabs ----------
cube("Floor", (center_x, center_y, -FLOOR_THICKNESS/2),
     (house_width/2, house_depth/2, FLOOR_THICKNESS/2), floor_mat)

cube("Ceiling", (center_x, center_y, WALL_HEIGHT),
     (house_width/2, house_depth/2, CEILING_THICKNESS/2), wall_mat)

cube("Roof", (center_x, center_y, WALL_HEIGHT + 0.3),
     (house_width/2+0.2, house_depth/2+0.2, ROOF_THICKNESS/2), roof_mat)

# ---------- Walls ----------
wall_objs = []

for w in walls:
    cx, cy = center(w)

    if w["orientation"] == "horizontal":
        scale = (abs(w["x2"]-w["x1"])/2, w["thickness"]/2, WALL_HEIGHT/2)
    else:
        scale = (w["thickness"]/2, abs(w["y2"]-w["y1"])/2, WALL_HEIGHT/2)

    obj = cube(w["id"], (cx, cy, WALL_HEIGHT/2), scale, wall_mat)
    wall_objs.append(obj)

# ---------- Labels ----------
for r in rooms:
    bpy.ops.object.text_add(location=(r["x"]+r["w"]/2, r["y"]+r["h"]/2, 0.02))
    t = bpy.context.object
    t.data.body = f"{r['name']}\n{r.get('surface_m2',0)} m²"
    t.rotation_euler[0] = math.radians(90)
    t.data.align_x = 'CENTER'

# ---------- Doors (ONLY FROM AI PLAN) ----------
door_cutters = []

for d in door_plan:
    w = get_wall(d["wall_id"])
    if not w:
        continue

    cx, cy = center(w)
    rot = 90 if w["orientation"] == "horizontal" else 0

    # visual
    cube(f"Door_{w['id']}", (cx, cy, DOOR_HEIGHT/2),
         (0.05, d["width"]/2, DOOR_HEIGHT/2), door_mat)

    # cutter
    cutter = cube(f"Cut_{w['id']}", (cx, cy, DOOR_HEIGHT/2),
                  (0.3, d["width"]/2, DOOR_HEIGHT/2))
    cutter.display_type = 'WIRE'
    door_cutters.append(cutter)

# ---------- Windows ----------
def win_size(type):
    return {
        "living_room": (1.2,1.8),
        "bedroom": (1.0,1.5),
        "kitchen": (1.0,1.2),
        "bathroom": (0.6,0.9)
    }.get(type, (1.0,1.4))

for w in walls:
    if w["type"] != "exterior":
        continue

    cx, cy = center(w)
    width, height = win_size("living_room")

    cube(f"Window_{w['id']}", (cx, cy, 1.5),
         (0.02, width/2, height/2), glass_mat)

    cutter = cube(f"WinCut_{w['id']}", (cx, cy, 1.5),
                  (WINDOW_DEPTH/2, width/2, height/2))
    cutter.display_type = 'WIRE'
    door_cutters.append(cutter)

# ---------- Boolean ----------
for wall in wall_objs:
    for c in door_cutters:
        mod = wall.modifiers.new("bool", 'BOOLEAN')
        mod.operation = 'DIFFERENCE'
        mod.object = c

# apply
for w in wall_objs:
    bpy.context.view_layer.objects.active = w
    for m in w.modifiers:
        bpy.ops.object.modifier_apply(modifier=m.name)

# cleanup
for o in door_cutters:
    bpy.data.objects.remove(o)

# ---------- Camera ----------
bpy.ops.object.camera_add(location=(center_x-15, center_y-15, 12))
cam = bpy.context.object
cam.rotation_euler = (math.radians(60), 0, math.radians(-45))
bpy.context.scene.camera = cam

# ---------- Light ----------
bpy.ops.object.light_add(type='SUN', location=(0,0,10))

# ---------- Export ----------
blend = os.path.join(project_folder, "generated_house.blend")
glb = os.path.join(project_folder, "generated_house.glb")

bpy.ops.wm.save_as_mainfile(filepath=blend)

bpy.ops.export_scene.gltf(
    filepath=glb,
    export_format='GLB'
)

print("✅ DONE:", glb)