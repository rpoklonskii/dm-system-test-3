"""
World / Era — общий контекст, роллится ОДИН раз на весь запуск (main.py)
и передаётся во все генераторы. Это и есть "связанный мир, общая эпоха":

  - Era задаёт уровень (1..10) и парадигму (Магия/Технология/Синтез) МИРА.
  - Каждое существо/фракция дальше роллит СВОЙ paradigm/magic_lvl/tech_lvl
    через roll_being_paradigm(era) — они тяготеют к уровню эпохи (не могут
    массово быть на голову сильнее/технологичнее мира), но каждый раз это
    независимый случайный ролл, не копия эпохи.
  - era.level также используется генераторами как "громкость" случайности
    (см. location_gen/skill_gen) — на ранней эпохе профили мягче и
    эклектичнее, на поздней — острее и специализированнее.
"""

import random
from dataclasses import dataclass
from typing import Tuple

from .schema import load_json

_ERAS = load_json("eras.json")


@dataclass
class Era:
    level: int
    paradigm: str
    name: str

    @staticmethod
    def roll() -> "Era":
        levels = list(range(1, 11))
        weights = _ERAS["level_weights"]["weights"]
        level = random.choices(levels, weights=weights)[0]

        pw = _ERAS["paradigm_weights"]["weights"]
        paradigm = random.choices(list(pw.keys()), weights=list(pw.values()))[0]

        name = _ERAS["era_names"][paradigm].get(str(level), "?")
        return Era(level, paradigm, name)


def _title_from_thresholds(level: int, thresholds) -> str:
    for row in thresholds:
        if row["max"] is None or level <= row["max"]:
            return row["title"]
    return thresholds[-1]["title"]


def magic_title(level: int) -> str:
    return _title_from_thresholds(level, _ERAS["magic_titles"]["thresholds"])


def tech_title(level: int) -> str:
    return _title_from_thresholds(level, _ERAS["tech_titles"]["thresholds"])


_ERA_TO_BEING_PARADIGM = {"Технологическая": "Технология", "Магическая": "Магия", "Синтез": "Синтез"}


def era_paradigm_to_being(era_paradigm: str) -> str:
    """era.paradigm использует прилагательные формы ('Технологическая'), а
    парадигма отдельного существа/материала — существительные ('Технология').
    Нужно, например, чтобы 'твёрдая пустота' локации (core.names.describe_material)
    выбрала правильный вариант по эпохе мира."""
    return _ERA_TO_BEING_PARADIGM.get(era_paradigm, "Синтез")


def roll_being_paradigm(era: Era) -> Tuple[str, int, int]:
    """Существо получает свою парадигму/уровни, тяготеющие к уровню мира,
    но с перекосом в один полюс (обычно либо маг, либо технарь)."""

    def roll_main():
        r = random.random()
        if r < 0.85:
            return era.level
        elif r < 0.90:
            return min(10, era.level + random.randint(1, 2))
        elif r < 0.95:
            return max(1, era.level - random.randint(1, 2))
        else:
            return random.randint(1, 10)

    def roll_secondary():
        if random.random() < 0.85:
            return random.randint(0, 3)
        return random.randint(0, max(1, era.level - 1))

    bw = _ERAS["being_paradigm_weights"]["weights"]
    paradigm = random.choices(list(bw.keys()), weights=list(bw.values()))[0]

    if paradigm == "Технология":
        tech, magic = roll_main(), roll_secondary()
    elif paradigm == "Магия":
        magic, tech = roll_main(), roll_secondary()
    else:
        tech, magic = roll_main(), roll_main()
    return paradigm, magic, tech
