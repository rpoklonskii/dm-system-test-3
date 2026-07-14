"""
Загрузка и валидация JSON-таблиц.

Идея: пользователь может дописывать/менять data/*.json как угодно.
Чтобы это не приводило к "ваша таблица вышла за заданные значения"
где-то в середине генерации спустя 50 вызовов функций, все проверки
делаются ОДИН раз при загрузке файла, с понятным сообщением что именно
не так и в каком файле/ключе.
"""

import json
import os
from typing import Any, Dict, List

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


class TableError(Exception):
    """Ошибка в данных, а не в коде. Сообщение всегда указывает файл и ключ."""
    pass


def _path(filename: str) -> str:
    return os.path.join(DATA_DIR, filename)


def load_json(filename: str) -> Dict[str, Any]:
    path = _path(filename)
    if not os.path.exists(path):
        raise TableError(f"[{filename}] файл не найден по пути {path}")
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            raise TableError(f"[{filename}] битый JSON: {e}") from e


def require_keys(filename: str, obj: Dict[str, Any], keys: List[str], where: str = "") -> None:
    missing = [k for k in keys if k not in obj]
    if missing:
        raise TableError(f"[{filename}]{(' ' + where) if where else ''} отсутствуют обязательные ключи: {missing}")


def require_len(filename: str, arr: List[Any], expected_len: int, where: str) -> None:
    if not isinstance(arr, list) or len(arr) != expected_len:
        raise TableError(
            f"[{filename}] {where} должен быть списком ровно из {expected_len} элементов, "
            f"а сейчас: {arr!r} (длина {len(arr) if isinstance(arr, list) else 'N/A'})"
        )


def require_range(filename: str, value: float, lo: float, hi: float, where: str) -> None:
    if not (lo <= value <= hi):
        raise TableError(f"[{filename}] {where} = {value} выходит за диапазон [{lo}, {hi}]")


# ---------------------------------------------------------------------------
# Валидация конкретных таблиц проекта. Вызывается один раз при старте (main.py
# и/или при первом импорте core/vector.py), чтобы поймать опечатки в data/*.json
# до начала генерации, а не посреди неё.
# ---------------------------------------------------------------------------

def validate_axes(axes_data: Dict[str, Any]) -> None:
    require_keys("axes.json", axes_data, ["domains", "axes", "band5_thresholds", "band7_thresholds"])
    axes = axes_data["axes"]
    if len(axes) != 12:
        raise TableError(f"[axes.json] ожидается ровно 12 осей (4 домена x 3 оси), сейчас {len(axes)}")
    for axis_key, meta in axes.items():
        require_keys("axes.json", meta, ["ru", "good_high", "description"], where=f"ось '{axis_key}'")
        for corr in meta.get("correlations", []):
            require_keys("axes.json", corr, ["target", "weight"], where=f"correlation оси '{axis_key}'")
            if corr["target"] not in axes:
                raise TableError(f"[axes.json] ось '{axis_key}' ссылается на несуществующую target '{corr['target']}'")
            require_range("axes.json", corr["weight"], -2.0, 2.0, f"вес correlation '{axis_key}' -> '{corr['target']}'")
    require_len("axes.json", axes_data["band5_thresholds"], 4, "band5_thresholds")
    require_len("axes.json", axes_data["band7_thresholds"], 6, "band7_thresholds")


def validate_band5_table(filename: str, arr: List[Any], where: str) -> None:
    require_len(filename, arr, 5, where)


def validate_names_tables(d: Dict[str, Any]) -> None:
    fn = "names_tables.json"
    require_keys(fn, d, ["mob_epithets", "axis_genitive", "axis_action", "nature_prefixes",
                          "role_nouns", "loc_forms", "matter_matrix3", "matter_hardvoid_by_paradigm"])

    from .vector import AXIS_KEYS
    for table_name in ["mob_epithets", "axis_genitive", "axis_action"]:
        table = d[table_name]
        expected_keys = {f"{axis}:{sign}" for axis in AXIS_KEYS for sign in ("+", "-")}
        missing = expected_keys - set(table.keys())
        if missing:
            raise TableError(f"[{fn}] {table_name}: отсутствуют записи для {sorted(missing)}")
        for key, words in table.items():
            if not isinstance(words, list) or not words:
                raise TableError(f"[{fn}] {table_name}.{key} должен быть непустым списком")

    for form in d["loc_forms"]:
        require_len(fn, form, 2, f"loc_forms элемент {form!r} (ожидается [слово, род])")
        if form[1] not in ("m", "f", "n", "p"):
            raise TableError(f"[{fn}] loc_forms: неизвестный род '{form[1]}' в {form!r}")

    mm = d["matter_matrix3"]
    bands = ["lo", "mid", "hi"]
    expected_mm_keys = {f"{a}.{b}.{c}" for a in bands for b in bands for c in bands}
    missing_mm = expected_mm_keys - {k for k in mm if not k.startswith("_")}
    if missing_mm:
        raise TableError(f"[{fn}] matter_matrix3: отсутствуют комбинации {sorted(missing_mm)}")

    hv = d["matter_hardvoid_by_paradigm"]
    for p in ["Технология", "Магия", "Синтез", "fallback"]:
        if p not in hv:
            raise TableError(f"[{fn}] matter_hardvoid_by_paradigm: отсутствует ключ '{p}'")


def _check_weighted_pair(filename: str, options: List[Any], weights: List[Any], where: str) -> None:
    if len(options) != len(weights):
        raise TableError(f"[{filename}] {where}: options ({len(options)}) и weights ({len(weights)}) разной длины")


def validate_location_tables(d: Dict[str, Any]) -> None:
    fn = "location_tables.json"
    require_keys(fn, d, ["material", "purpose", "atmosphere", "loot", "map_generation"])

    mat = d["material"]
    validate_band5_table(fn, mat["base_by_plasticity"], "material.base_by_plasticity")
    validate_band5_table(fn, mat["cohesion_modifier"], "material.cohesion_modifier")
    validate_band5_table(fn, mat["density_modifier"], "material.density_modifier")

    purp = d["purpose"]
    validate_band5_table(fn, purp["type_by_order"], "purpose.type_by_order")
    validate_band5_table(fn, purp["status_by_meaning"], "purpose.status_by_meaning")

    atmo = d["atmosphere"]
    validate_band5_table(fn, atmo["carrier_atmosphere"], "atmosphere.carrier_atmosphere")
    validate_band5_table(fn, atmo["amplitude_power"], "atmosphere.amplitude_power")
    validate_band5_table(fn, atmo["charge_danger"], "atmosphere.charge_danger")
    validate_band5_table(fn, atmo["agency_alive"], "atmosphere.agency_alive")

    loot = d["loot"]
    require_len(fn, loot["quality_grades"], 4, "loot.quality_grades")
    require_len(fn, loot["grade_thresholds"], 3, "loot.grade_thresholds")
    for domain, items in loot["by_domain"].items():
        require_len(fn, items, 4, f"loot.by_domain.{domain}")


def validate_faction_tables(d: Dict[str, Any]) -> None:
    fn = "faction_tables.json"
    require_keys(fn, d, ["flesh", "size_by_density", "quantity_by_cohesion", "name_forms",
                          "name_essences", "mob_name", "roles", "mind_and_emotion", "tactics",
                          "hierarchy", "goals", "diplomacy", "eco_states", "generation"])

    validate_band5_table(fn, d["flesh"]["base_by_plasticity"], "flesh.base_by_plasticity")
    validate_band5_table(fn, d["flesh"]["cohesion_modifier"], "flesh.cohesion_modifier")
    validate_band5_table(fn, d["size_by_density"], "size_by_density")
    validate_band5_table(fn, d["quantity_by_cohesion"], "quantity_by_cohesion")
    validate_band5_table(fn, d["hierarchy"]["by_order"], "hierarchy.by_order")

    eco = d["eco_states"]
    _check_weighted_pair(fn, eco["options"], eco["weights"], "eco_states")

    dip = d["diplomacy"]
    _check_weighted_pair(fn, dip["dumb_relations"]["options"], dip["dumb_relations"]["weights"], "diplomacy.dumb_relations")
    _check_weighted_pair(fn, dip["vs_dumb_relations"]["options"], dip["vs_dumb_relations"]["weights"], "diplomacy.vs_dumb_relations")
    _check_weighted_pair(fn, dip["smart_vs_smart"]["prefixes"], dip["smart_vs_smart"]["prefix_weights"], "diplomacy.smart_vs_smart")

    for role, deltas in d["roles"]["role_deltas"].items():
        if role.startswith("_"):
            continue
        for axis, pair in deltas.items():
            if axis.startswith("_"):
                continue
            require_len(fn, pair, 2, f"roles.role_deltas.{role}.{axis} (ожидается [mean, sigma])")


def validate_skill_tables(d: Dict[str, Any]) -> None:
    fn = "skill_tables.json"
    require_keys(fn, d, ["directions", "durations", "triggers", "target_weights", "mechanism_pool",
                          "mechanism_base_weights", "synergy_phenomena", "domain_description_words",
                          "axis_action_tiers", "generic_tiers", "mechanism_ladders", "mana_cost"])

    n_durations = len(d["durations"])
    for name, weights in d["duration_weights"].items():
        if name.startswith("_"):
            continue
        require_len(fn, weights, n_durations, f"duration_weights.{name} (должно совпадать по длине с durations={n_durations})")

    for axis, dirs in d["axis_action_tiers"].items():
        if axis.startswith("_"):
            continue
        for direction, ladder in dirs.items():
            if direction.startswith("_"):
                continue
            require_len(fn, ladder, 5, f"axis_action_tiers.{axis}.{direction}")

    for direction, ladder in d["generic_tiers"].items():
        if direction.startswith("_"):
            continue
        require_len(fn, ladder, 5, f"generic_tiers.{direction}")

    for mech, ladder in d["mechanism_ladders"].items():
        if mech.startswith("_"):
            continue
        require_len(fn, ladder, 5, f"mechanism_ladders.{mech}")

    for dom, words in d["domain_description_words"].items():
        if dom.startswith("_"):
            continue
        for key, arr in words.items():
            if key.startswith("_"):
                continue
            require_len(fn, arr, 5, f"domain_description_words.{dom}.{key}")

    for pair in d["synergy_phenomena"]["pairs"]:
        require_len(fn, pair["axes"], 2, f"synergy_phenomena pair {pair.get('name')}")
