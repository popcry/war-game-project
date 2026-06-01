"""Phase 3: 부흘레다르 확장 bbox(1200×875)에 신규 편성을 배치하는 YAML 생성.

구도:
  RED (러, 남측): y=500~800
  BLUE (우, 북측): y=50~350
각 squad/team은 anchor 좌표 1개로 표현하고, 같은 anchor를 squad_size번 반복.
(Phase 4의 진형 오프셋이 활성화되면 unit들이 anchor 주변으로 자동 분산됨.)
"""

def evenly_spaced(n, x_min, x_max):
    if n == 1:
        return [(x_min + x_max) // 2]
    step = (x_max - x_min) / (n - 1)
    return [int(round(x_min + i * step)) for i in range(n)]


# RED (러)
RED = {
    "RIFLE":           {"squads": 10, "size": 9, "y_anchor": 650, "x_min": 100, "x_max": 1100},
    "TANK":            {"squads": 15, "size": 1, "y_anchor": 570, "x_min": 100, "x_max": 1100},
    "DRONE":           {"squads": 3,  "size": 2, "y_anchor": 780, "x_min": 300, "x_max": 900},
    "SELF_DEST_DRONE": {"squads": 3,  "size": 3, "y_anchor": 530, "x_min": 300, "x_max": 900},
    "COMMAND_POST":    {"squads": 1,  "size": 1, "y_anchor": 820, "x_min": 600, "x_max": 600},
}

# BLUE (우크라)
BLUE = {
    "RIFLE":           {"squads": 6,  "size": 9, "y_anchor": 250, "x_min": 200, "x_max": 950},
    "TANK":            {"squads": 4,  "size": 1, "y_anchor": 150, "x_min": 300, "x_max": 900},
    "ANTI_TANK":       {"squads": 8,  "size": 2, "y_anchor": 220, "x_min": 100, "x_max": 1100},
    "ARTILLERY":       {"squads": 4,  "size": 1, "y_anchor": 50,  "x_min": 200, "x_max": 950},
    "DRONE":           {"squads": 3,  "size": 3, "y_anchor": 120, "x_min": 300, "x_max": 900},
    "SELF_DEST_DRONE": {"squads": 3,  "size": 5, "y_anchor": 330, "x_min": 300, "x_max": 900},
    "COMMAND_POST":    {"squads": 1,  "size": 1, "y_anchor": 80,  "x_min": 600, "x_max": 600},
}


def build_positions(spec):
    xs = evenly_spaced(spec["squads"], spec["x_min"], spec["x_max"])
    positions = []
    for x in xs:
        # 같은 anchor를 squad_size 번 반복 (Phase 4가 진형 오프셋으로 분산)
        for _ in range(spec["size"]):
            positions.append([x, spec["y_anchor"]])
    return positions


def format_yaml_list(positions, indent=6):
    pad = " " * indent
    lines = []
    line = pad + "["
    for i, (x, y) in enumerate(positions):
        token = f"[{x},{y}]"
        if i > 0:
            token = "," + token
        line += token
        if len(line) > 100:
            lines.append(line)
            line = pad + " "
    if line.strip():
        lines.append(line)
    lines[-1] += "]"
    return "\n".join(lines)


def emit_team(name, spec_dict):
    out = [f"  {name}:"]
    for unit_type, spec in spec_dict.items():
        positions = build_positions(spec)
        out.append(f"    {unit_type}: # {spec['squads']} 팀 × {spec['size']}대 = {len(positions)}")
        out.append(format_yaml_list(positions))
    return "\n".join(out)


def emit_counts():
    lines = []
    map_count = {
        ("RED", "ARTILLERY"): "num_artillery_red",
        ("BLUE", "ARTILLERY"): "num_artillery_blue",
        ("RED", "DRONE"): "num_drone_red",
        ("BLUE", "DRONE"): "num_drone_blue",
        ("RED", "TANK"): "num_tank_red",
        ("BLUE", "TANK"): "num_tank_blue",
        ("RED", "ANTI_TANK"): "num_at_red",
        ("BLUE", "ANTI_TANK"): "num_at_blue",
        ("RED", "RIFLE"): "num_infantry_red",
        ("BLUE", "RIFLE"): "num_infantry_blue",
        ("RED", "COMMAND_POST"): "num_cp_red",
        ("BLUE", "COMMAND_POST"): "num_cp_blue",
        ("RED", "SELF_DEST_DRONE"): "num_self_dest_drone_red",
        ("BLUE", "SELF_DEST_DRONE"): "num_self_dest_drone_blue",
    }
    for team_name, spec_dict in [("RED", RED), ("BLUE", BLUE)]:
        for ut, key in [(ut, map_count[(team_name, ut)]) for ut in
                        ["ARTILLERY", "DRONE", "TANK", "ANTI_TANK", "RIFLE",
                         "COMMAND_POST", "SELF_DEST_DRONE"]]:
            if ut in spec_dict:
                total = spec_dict[ut]["squads"] * spec_dict[ut]["size"]
            else:
                total = 0
            lines.append(f"{key}: {total}")
    return "\n".join(lines)


def emit_squad_sizes():
    out = ["squad_sizes:"]
    for team_name, spec_dict in [("RED", RED), ("BLUE", BLUE)]:
        out.append(f"  {team_name}:")
        for ut, spec in spec_dict.items():
            out.append(f"    {ut}: {spec['size']}")
    return "\n".join(out)


if __name__ == "__main__":
    print("# === initial_positions ===")
    print("initial_positions:")
    print(emit_team("RED", RED))
    print(emit_team("BLUE", BLUE))
    print()
    print("# === counts ===")
    print(emit_counts())
    print()
    print("# === squad_sizes ===")
    print(emit_squad_sizes())
