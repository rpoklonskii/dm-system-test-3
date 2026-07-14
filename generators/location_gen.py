"""
Генератор локаций. Механика карты (BSP-нарезка внутри случайной "маски"
формы, гарантия связности заливкой) взята из Dm_location.py как признанная
лучшей для этой задачи — она не тронута по существу, только:
  - профиль локации теперь core.vector.Profile, а не голый dict;
  - весь текст (материалы/атмосфера/лут) вынесен в data/location_tables.json;
  - генерация профиля идёт через Profile.generate(...) (общий механизм
    корреляций между осями), а не через собственную копию алгоритма.
"""

import random
import string
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core import Profile, band_idx5, Era, names
from core.schema import load_json, validate_location_tables

_T = load_json("location_tables.json")
validate_location_tables(_T)
_MAT = _T["material"]
_PURPOSE = _T["purpose"]
_ATMO = _T["atmosphere"]
_LOOT = _T["loot"]
_MAPCFG = _T["map_generation"]

DOMAIN_RU = {"matter": "Материя", "info": "Информация", "energy": "Энергия", "spacetime": "Пространство"}


# =========================================================
# Генерация профиля локации
# =========================================================
def generate_location_profile() -> Profile:
    return Profile.generate(
        dominant_count_weights={1: 0.40, 2: 0.45, 3: 0.15},
        dominant_sigma=0.8,
        background_sigma=0.10,
    )


# =========================================================
# Текстовые генераторы (читают profile + JSON-таблицы)
# =========================================================
def get_material(plasticity: float, cohesion: float, density: float, paradigm: str = "Синтез") -> str:
    """27-комбинационное описание материи (core.names.describe_material) —
    заменяет прежнюю бедную 5-полосную версию. paradigm нужен только для
    редкого случая 'твёрдой пустоты' (низкая density, высокая cohesion),
    оставлен параметром по умолчанию 'Синтез' для обратной совместимости
    вызовов без явного paradigm."""
    return names.describe_material(density, cohesion, plasticity, paradigm).capitalize()


def get_purpose(order: float, meaning: float) -> str:
    i_o, i_m = band_idx5(order), band_idx5(meaning)
    return f"{_PURPOSE['type_by_order'][i_o]} ({_PURPOSE['status_by_meaning'][i_m]})"


def get_atmosphere_and_danger(carrier: float, amplitude: float, charge: float, agency: float) -> str:
    i_c, i_a, i_ch, i_ag = band_idx5(carrier), band_idx5(amplitude), band_idx5(charge), band_idx5(agency)
    atmos = _ATMO["carrier_atmosphere"][i_c]
    power = _ATMO["amplitude_power"][i_a]
    danger = _ATMO["charge_danger"][i_ch]
    alive = _ATMO["agency_alive"][i_ag]
    parts = [p for p in [f"Наполнена {power} {atmos}.", danger, alive] if p]
    return " ".join(parts)


def get_loot(profile: Profile) -> str:
    dom = profile.dominant_domain()
    max_mag = max(abs(v) for v in profile.values())
    t = _LOOT["grade_thresholds"]
    grade = 0 if max_mag < t[0] else 1 if max_mag < t[1] else 2 if max_mag < t[2] else 3
    quality = _LOOT["quality_grades"]
    return f"[{quality[grade]}] {_LOOT['by_domain'][dom][grade]}"


# =========================================================
# Форма карты (маска) — без изменений по существу относительно Dm_location.py
# =========================================================
def get_largest_component(mask, w, h):
    visited = set()
    components = []
    for y in range(h):
        for x in range(w):
            if mask[y][x] and (x, y) not in visited:
                comp = set()
                q = [(x, y)]
                visited.add((x, y))
                while q:
                    cx, cy = q.pop(0)
                    comp.add((cx, cy))
                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h and mask[ny][nx] and (nx, ny) not in visited:
                            visited.add((nx, ny))
                            q.append((nx, ny))
                components.append(comp)
    if not components:
        return mask
    best_comp = max(components, key=len)
    new_mask = [[False] * w for _ in range(h)]
    for x, y in best_comp:
        new_mask[y][x] = True
    return new_mask


def generate_macro_mask(w: int, h: int, order: float):
    mask = [[False] * w for _ in range(h)]
    cx, cy = w // 2, h // 2

    shapes = [('rect' if random.random() > 0.5 else 'circle', cx, cy, random.randint(20, 50), random.randint(15, 25))]

    num_adds = random.randint(2, 5) if order > 0 else random.randint(5, 12)
    for _ in range(num_adds):
        ref_x = cx + random.randint(-30, 30)
        ref_y = cy + random.randint(-12, 12)
        sw = random.randint(10, 30)
        sh = random.randint(8, 20)
        stype = 'rect' if random.random() > (0.7 if order < 0 else 0.3) else 'circle'
        shapes.append((stype, ref_x, ref_y, sw, sh))

    num_subs = random.randint(0, 2) if order > 0 else random.randint(2, 6)
    subs = []
    for _ in range(num_subs):
        ref_x = cx + random.randint(-25, 25)
        ref_y = cy + random.randint(-10, 10)
        sw = random.randint(8, 20)
        sh = random.randint(6, 15)
        stype = 'rect' if order > 0 else 'circle'
        subs.append((stype, ref_x, ref_y, sw, sh))

    for y in range(1, h - 1):
        for x in range(1, w - 1):
            in_add = False
            for stype, sx, sy, sw, sh in shapes:
                if sw > 0 and sh > 0:
                    if stype == 'circle' and ((x - sx) / (sw / 2)) ** 2 + ((y - sy) / (sh / 2)) ** 2 <= 1.2:
                        in_add = True; break
                    elif stype == 'rect' and abs(x - sx) <= sw / 2 and abs(y - sy) <= sh / 2:
                        in_add = True; break
            in_sub = False
            for stype, sx, sy, sw, sh in subs:
                if sw > 0 and sh > 0:
                    if stype == 'circle' and ((x - sx) / (sw / 2)) ** 2 + ((y - sy) / (sh / 2)) ** 2 <= 1.0:
                        in_sub = True; break
                    elif stype == 'rect' and abs(x - sx) <= sw / 2 and abs(y - sy) <= sh / 2:
                        in_sub = True; break
            if in_add and not in_sub:
                mask[y][x] = True

    return get_largest_component(mask, w, h)


class Rect:
    def __init__(self, x, y, w, h):
        self.x = x; self.y = y; self.w = w; self.h = h
        self.cx = x + w // 2
        self.cy = y + h // 2
        self.label = ""


class MapFloor:
    def __init__(self, width, height, floor_idx):
        self.width = width
        self.height = height
        self.floor_idx = floor_idx
        self.grid = [['#' for _ in range(width)] for _ in range(height)]
        self.rooms: List[Rect] = []
        self.walls = []


def slice_space(x, y, w, h, depth, max_depth, rooms, walls):
    min_w = min_h = _MAPCFG["min_room_w"]
    if depth >= max_depth or w < min_w * 2 + 1 or h < min_h * 2 + 1:
        rooms.append(Rect(x, y, w, h))
        return

    horiz = random.choice([True, False])
    if w < min_w * 2 + 1: horiz = True
    elif h < min_h * 2 + 1: horiz = False

    if horiz:
        split_h = random.randint(min_h, h - min_h - 1)
        walls.append(('h', x, y + split_h, w))
        slice_space(x, y, w, split_h, depth + 1, max_depth, rooms, walls)
        slice_space(x, y + split_h + 1, w, h - split_h - 1, depth + 1, max_depth, rooms, walls)
    else:
        split_w = random.randint(min_w, w - min_w - 1)
        walls.append(('v', x + split_w, y, h))
        slice_space(x, y, split_w, h, depth + 1, max_depth, rooms, walls)
        slice_space(x + split_w + 1, y, w - split_w - 1, h, depth + 1, max_depth, rooms, walls)


def build_map_features(floor: MapFloor, order: float, topology: float):
    mask = generate_macro_mask(floor.width, floor.height, order)

    active_rooms = []
    for r in floor.rooms:
        overlap = sum(1 for y in range(r.y, r.y + r.h) for x in range(r.x, r.x + r.w) if mask[y][x])
        if overlap > (r.w * r.h) * 0.15:
            active_rooms.append(r)
    floor.rooms = active_rooms

    for r in floor.rooms:
        for y in range(r.y, r.y + r.h):
            for x in range(r.x, r.x + r.w):
                if mask[y][x]:
                    floor.grid[y][x] = '.'

    for w_type, wx, wy, length in floor.walls:
        valid_spots = []
        if w_type == 'h':
            for x in range(wx + 1, wx + length - 1):
                if floor.grid[wy - 1][x] == '.' and floor.grid[wy + 1][x] == '.':
                    valid_spots.append((x, wy))
        else:
            for y in range(wy + 1, wy + length - 1):
                if floor.grid[y][wx - 1] == '.' and floor.grid[y][wx + 1] == '.':
                    valid_spots.append((wx, y))

        if valid_spots:
            num_doors = 1 if len(valid_spots) < 6 else random.randint(1, 2)
            for spot in random.sample(valid_spots, num_doors):
                floor.grid[spot[1]][spot[0]] = '+'

    crampedness = max(0, topology)
    if crampedness > 0.1:
        for r in floor.rooms:
            num_internal_walls = int(crampedness * 3)
            for _ in range(num_internal_walls):
                if random.random() > 0.5 and r.w > 6:
                    ix = r.x + random.randint(2, r.w - 3)
                    for iy in range(r.y, r.y + r.h):
                        if floor.grid[iy][ix] == '.' and random.random() < 0.7:
                            floor.grid[iy][ix] = '#'
                elif r.h > 6:
                    iy = r.y + random.randint(2, r.h - 3)
                    for ix in range(r.x, r.x + r.w):
                        if floor.grid[iy][ix] == '.' and random.random() < 0.7:
                            floor.grid[iy][ix] = '#'

            furn_density = crampedness * 0.45
            for y in range(r.y, r.y + r.h):
                for x in range(r.x, r.x + r.w):
                    if floor.grid[y][x] == '.' and random.random() < furn_density:
                        if not any(floor.grid[y + dy][x + dx] == '+' for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]):
                            floor.grid[y][x] = '='

    labels = string.ascii_uppercase + string.ascii_lowercase
    for i, r in enumerate(floor.rooms):
        r.label = labels[i % len(labels)]
        placed = False
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                cy, cx = r.cy + dy, r.cx + dx
                if 0 <= cx < floor.width and 0 <= cy < floor.height:
                    if floor.grid[cy][cx] == '.':
                        floor.grid[cy][cx] = r.label
                        placed = True
                        break
            if placed:
                break


def guarantee_connectivity(floor: MapFloor):
    components = []
    visited = set()
    for y in range(floor.height):
        for x in range(floor.width):
            if floor.grid[y][x] != '#' and (x, y) not in visited:
                comp = set()
                q = [(x, y)]
                visited.add((x, y))
                while q:
                    cx, cy = q.pop(0)
                    comp.add((cx, cy))
                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < floor.width and 0 <= ny < floor.height:
                            if floor.grid[ny][nx] != '#' and (nx, ny) not in visited:
                                visited.add((nx, ny))
                                q.append((nx, ny))
                components.append(comp)

    if not components:
        return
    best_comp = max(components, key=len)
    for y in range(floor.height):
        for x in range(floor.width):
            if floor.grid[y][x] != '#' and (x, y) not in best_comp:
                floor.grid[y][x] = '#'


# =========================================================
# Класс локации
# =========================================================
@dataclass
class Location:
    name: str
    profile: Profile
    paradigm: str = "Синтез"
    num_floors: int = 0
    floors: List[MapFloor] = field(default_factory=list)
    surviving_rooms: Dict[str, tuple] = field(default_factory=dict)
    stair_links: Dict[str, list] = field(default_factory=dict)
    sub_locations: Dict[str, dict] = field(default_factory=dict)

    def generate_maps(self):
        weights = _MAPCFG["num_floors_weights"]
        self.num_floors = random.choices([int(k) for k in weights], weights=list(weights.values()))[0]
        self.floors = []

        order = self.profile["info.order"]
        topology = self.profile["spacetime.topology"]
        base_w, base_h = _MAPCFG["base_width"], _MAPCFG["base_height"]

        for f_idx in range(self.num_floors):
            f = MapFloor(base_w, base_h, f_idx)
            slice_space(1, 1, f.width - 2, f.height - 2, 0, _MAPCFG["bsp_max_depth"], f.rooms, f.walls)
            build_map_features(f, order, topology)
            guarantee_connectivity(f)
            if not any(c != '#' for row in f.grid for c in row):
                continue
            self.floors.append(f)

        self.surviving_rooms = {}
        for f in self.floors:
            for r in f.rooms:
                for row in f.grid:
                    if r.label in row:
                        self.surviving_rooms[r.label] = (f, r)
                        break

        self.stair_links = {}
        for i in range(len(self.floors) - 1):
            f1, f2 = self.floors[i], self.floors[i + 1]
            f1_rooms = [r for r in f1.rooms if r.label in self.surviving_rooms]
            f2_rooms = [r for r in f2.rooms if r.label in self.surviving_rooms]
            if f1_rooms and f2_rooms:
                r1 = random.choice(f1_rooms)
                r2 = random.choice(f2_rooms)

                placed_down = False
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        cy, cx = r1.cy + dy, r1.cx + dx
                        if 0 <= cy < f1.height and 0 <= cx < f1.width and f1.grid[cy][cx] == '.':
                            f1.grid[cy][cx] = '>'; placed_down = True; break
                    if placed_down:
                        break

                placed_up = False
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        cy, cx = r2.cy + dy, r2.cx + dx
                        if 0 <= cy < f2.height and 0 <= cx < f2.width and f2.grid[cy][cx] == '.':
                            f2.grid[cy][cx] = '<'; placed_up = True; break
                    if placed_up:
                        break

                if placed_down:
                    self.stair_links.setdefault(r1.label, []).append(f"Спуск на Этаж {i + 2}")
                if placed_up:
                    self.stair_links.setdefault(r2.label, []).append(f"Подъем на Этаж {i + 1}")

        self.sub_locations = {}
        for label, (f, r) in sorted(self.surviving_rooms.items()):
            sub_prof = self.profile.mutate(volatility=0.25)
            self.sub_locations[label] = {
                "floor": f.floor_idx + 1,
                "w": r.w, "h": r.h,
                "purpose": get_purpose(sub_prof["info.order"], sub_prof["info.meaning_density"]),
                "material": get_material(sub_prof["matter.plasticity"], sub_prof["matter.cohesion"], sub_prof["matter.density"], self.paradigm),
                "atmosphere": get_atmosphere_and_danger(sub_prof["energy.carrier"], sub_prof["energy.amplitude"], sub_prof["energy.charge"], sub_prof["info.agency"]),
                "loot": get_loot(sub_prof),
                "anomaly": random.random() > 0.7,
                "stairs": self.stair_links.get(label, []),
                "profile": sub_prof,
            }

    def render(self) -> str:
        self.generate_maps()
        if not self.floors:
            return f"Локация {self.name} полностью уничтожена аномалией (Пустота)."

        main_purpose = get_purpose(self.profile["info.order"], self.profile["info.meaning_density"])
        main_mat = get_material(self.profile["matter.plasticity"], self.profile["matter.cohesion"], self.profile["matter.density"], self.paradigm)

        lines = [
            f"╔{'═'*78}╗",
            f"║ ЛОКАЦИЯ: {self.name.upper():<67} ║",
            f"╠{'═'*78}╣",
            f"  Домен:        {main_purpose}",
            f"  Материал:     {main_mat}",
            f"  Масштаб:      ОГРОМНЫЙ (Этажей: {len(self.floors)}, Сублокаций: {len(self.sub_locations)})",
            f"  Теснота:      {'Клаустрофобная (Завалы и стены)' if self.profile['spacetime.topology'] > 0.2 else 'Свободная (Просторные залы)'}",
            f"  Архитектура:  {'Строгая/Симметричная' if self.profile['info.order'] > 0 else 'Хаотичная/Органическая (Рваные края)'}",
            f"╚{'═'*78}╝\n",
        ]

        for f in self.floors:
            lines.append(f"--- ЭТАЖ {f.floor_idx + 1} ---")
            for row in f.grid:
                lines.append(f"  {''.join(row).replace('#', '█')}")
            lines.append("")

        lines.append(f"╔{'═'*78}╗")
        lines.append("║ ДЕТАЛИЗАЦИЯ СУБЛОКАЦИЙ (█=Стена, .=Пол, +=Дверь, ==Укрытия, </>=Лестницы)  ║")
        lines.append(f"╚{'═'*78}╝")

        for label, data in sorted(self.sub_locations.items()):
            anom_text = "[! АНОМАЛИЯ !] " if data["anomaly"] else ""
            area = data["w"] * data["h"]
            if area > 180: size_desc = f"Огромный зал ({data['w']}x{data['h']})"
            elif area > 100: size_desc = f"Просторное помещение ({data['w']}x{data['h']})"
            elif area > 50: size_desc = f"Средняя комната ({data['w']}x{data['h']})"
            else: size_desc = f"Тесный сектор ({data['w']}x{data['h']})"

            lines.append(f" ❖ ЗОНА [{label}] (Этаж {data['floor']}): {anom_text}{data['purpose']}")
            lines.append(f"   ├ Архитектура: {size_desc}. {data['material']}")
            lines.append(f"   ├ Атмосфера:   {data['atmosphere']}")
            lines.append(f"   ├ Лут:         {data['loot']}")
            lines.append(f"   └ [!] ПЕРЕХОД: {', '.join(data['stairs'])}" if data["stairs"] else "   └")
            lines.append("")

        return "\n".join(lines)


if __name__ == "__main__":
    loc = Location(name="Зараженный Исследовательский Бункер", profile=generate_location_profile())
    print(loc.render())
