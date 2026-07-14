"""
Богатые словари имён и материи — источник: присланный пользователем файл
с исправленными "красивыми" названиями материи (27-комбинационная матрица
из оригинала), которые не попали в первую сборку системы, плюс большой
словарь эпитетов/родительных падежей/действий по каждой (ось, знак) с
грамматическим согласованием рода через core/inflect.py.
"""

import random
from typing import Tuple

from .vector import Profile, band3
from .inflect import inflect_adj
from .schema import load_json, validate_names_tables

_T = load_json("names_tables.json")
validate_names_tables(_T)

MOB_EPITHETS = _T["mob_epithets"]
AXIS_GENITIVE = _T["axis_genitive"]
AXIS_ACTION = _T["axis_action"]
NATURE_PREFIXES = _T["nature_prefixes"]
ROLE_NOUNS = _T["role_nouns"]
LOC_FORMS = [tuple(x) for x in _T["loc_forms"]]
MATTER_MATRIX3 = _T["matter_matrix3"]
MATTER_HARDVOID_BY_PARADIGM = _T["matter_hardvoid_by_paradigm"]


def _axis_sign_key(axis: str, value: float) -> str:
    return f"{axis}:{'+' if value >= 0 else '-'}"


def pick_epithet(axis: str, value: float) -> str:
    return random.choice(MOB_EPITHETS.get(_axis_sign_key(axis, value), ["Непостижимый"]))


def pick_genitive(axis: str, value: float) -> str:
    return random.choice(AXIS_GENITIVE.get(_axis_sign_key(axis, value), ["Тайны"]))


def pick_action(axis: str, value: float) -> str:
    return random.choice(AXIS_ACTION.get(_axis_sign_key(axis, value), ["скрывающий свою суть"]))


def describe_material(density: float, cohesion: float, plasticity: float, paradigm: str = "Синтез") -> str:
    """27-комбинационное (band3 x band3 x band3) описание материи — заменяет
    прежний более бедный 5-полосный get_material() из location_gen.py.
    paradigm нужен только для "твёрдой пустоты" (density низкая, cohesion
    высокая) — там материал буквально сделан из стабилизированного вакуума,
    и КАК он стабилизирован зависит от магии/технологии/синтеза."""
    key = f"{band3(density)}.{band3(cohesion)}.{band3(plasticity)}"
    phrase = MATTER_MATRIX3.get(key, "неописуемая плоть")
    fallback = MATTER_HARDVOID_BY_PARADIGM["fallback"]
    if phrase == "__HARDVOID__":
        return MATTER_HARDVOID_BY_PARADIGM.get(paradigm, fallback)
    elif phrase == "__HARDVOID_SOFT__":
        return MATTER_HARDVOID_BY_PARADIGM.get(paradigm, fallback) + " (податливая разновидность)"
    elif phrase == "__HARDVOID_BRITTLE__":
        return MATTER_HARDVOID_BY_PARADIGM.get(paradigm, fallback) + " (хрупкий кристалл вакуума)"
    return phrase


def generate_mob_title(profile: Profile, role_base: str) -> str:
    """5 случайных паттернов имени моба вместо единственного жёсткого
    prefix+core, который был раньше. ROLE_NOUNS куратированы как
    маскулинные (как и в присланном файле), поэтому эпитет/действие
    согласуются с родом 'm' напрямую, без отдельной таблицы родов для ролей."""
    dom = profile.dominant_domain()
    prefix = random.choice(NATURE_PREFIXES.get(dom, NATURE_PREFIXES["fallback"]))
    noun = random.choice(ROLE_NOUNS.get(role_base, ROLE_NOUNS["fallback"]))

    top = profile.top_axes(3)
    epithet = inflect_adj(pick_epithet(*top[0]), "m")
    genitive = pick_genitive(*top[1])
    action = inflect_adj(pick_action(*top[2]), "m")

    patterns = [
        f"{epithet} {prefix}-{noun} {genitive}",
        f"{prefix}-{noun} из чистого {genitive}, {action}",
        f"«{epithet}» — {prefix}-{noun}, {action}",
        f"{epithet} {prefix}-{noun} ({action})",
        f"Воплощение {genitive} — {epithet} {prefix}-{noun}",
    ]
    return random.choice(patterns)


def generate_location_name(profile: Profile) -> str:
    """Процедурное имя локации по её профилю (эпитет согласуется в роде с
    формой локации) — раньше локация получала имя только вручную."""
    form, gender = random.choice(LOC_FORMS)
    top = profile.top_axes(3)
    epithet = inflect_adj(pick_epithet(*top[0]), gender)
    genitive = pick_genitive(*top[1])
    return f"{epithet} {form} {genitive}"
