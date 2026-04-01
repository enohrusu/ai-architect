def generate_layout(house_data):
    bedrooms = house_data["bedrooms"]
    bathrooms = house_data["bathrooms"]
    area_m2 = house_data["area_m2"]
    garage = house_data["garage"]
    floors = house_data["floors"]
    style = house_data["style"]

    rooms = []

    # ---------- Standard prototype sizes ----------
    living_w = 6
    living_h = 5

    kitchen_w = 4
    kitchen_h = 4

    bedroom_w = 4
    bedroom_h = 4

    bathroom_w = 2.5
    bathroom_h = 3

    garage_w = 5
    garage_h = 5

    corridor_w = 2
    corridor_h = 8

    # ---------- Front zone ----------
    rooms.append({
        "name": "living_room",
        "x": 0,
        "y": 0,
        "w": living_w,
        "h": living_h
    })

    rooms.append({
        "name": "kitchen",
        "x": living_w,
        "y": 0,
        "w": kitchen_w,
        "h": kitchen_h
    })

    # ---------- Corridor ----------
    corridor_x = 4
    corridor_y = living_h
    rooms.append({
        "name": "corridor",
        "x": corridor_x,
        "y": corridor_y,
        "w": corridor_w,
        "h": corridor_h
    })

    # ---------- Bedroom zone ----------
    bedroom_start_y = living_h + 1
    left_side_x = 0
    right_side_x = corridor_x + corridor_w + 0.5

    for i in range(bedrooms):
        if i % 2 == 0:
            rooms.append({
                "name": f"bedroom_{i+1}",
                "x": left_side_x,
                "y": bedroom_start_y + (i // 2) * (bedroom_h + 0.5),
                "w": bedroom_w,
                "h": bedroom_h
            })
        else:
            rooms.append({
                "name": f"bedroom_{i+1}",
                "x": right_side_x,
                "y": bedroom_start_y + (i // 2) * (bedroom_h + 0.5),
                "w": bedroom_w,
                "h": bedroom_h
            })

    # ---------- Bathroom zone ----------
    bath_start_y = bedroom_start_y + ((bedrooms + 1) // 2) * (bedroom_h + 0.5)

    for i in range(bathrooms):
        rooms.append({
            "name": f"bathroom_{i+1}",
            "x": right_side_x,
            "y": bath_start_y + i * (bathroom_h + 0.5),
            "w": bathroom_w,
            "h": bathroom_h
        })

    # ---------- Garage ----------
    if garage:
        garage_x = living_w + kitchen_w + 1
        rooms.append({
            "name": "garage",
            "x": garage_x,
            "y": 0,
            "w": garage_w,
            "h": garage_h
        })

    layout = {
        "meta": {
            "style": style,
            "area_m2": area_m2,
            "floors": floors
        },
        "rooms": rooms
    }

    return layout