"""
Механика атаки: ЧЕМ бьём / КАК бьём / С КАКОЙ СИЛОЙ бьём.

Не путать с generators/skill_gen.Skill — тот описывает полноценные НАВЫКИ
(триггеры, длительность, мана). Attack — примитив для обычного столкновения
("голем ударил дубиной"), из которого потом можно строить и навыки.

СПЛЕШ-УРОН ПО СВЯЗАННЫМ ВЕКТОРАМ ВЗЯТ НЕ ИЗ НОВОЙ ТАБЛИЦЫ, А ИЗ УЖЕ
СУЩЕСТВУЮЩИХ data/cushion_table.json → contributors: если ось уже связана с
другими для расчёта СОПРОТИВЛЕНИЯ, она связана и для распространения
ПОВРЕЖДЕНИЯ — незачем вести вторую независимую сеть связей.

ГАРАНТИЯ (по вашему требованию): сплеш не добавляется СВЕРХ основного урона.
Вся magnitude атаки делится между основной осью и её соседями по contributors
— сумма всех сдвигов по построению равна magnitude, никогда не больше.

МЕХАНИЗМ КАК МОДИФИКАТОР: чем бьём — масштабирует, сколько силы достаётся
каждой из затронутых осей (включая саму основную), через УЖЕ существующую
data/skill_tables.json → mechanism_base_weights[domain] — ту же таблицу,
что уже описывает тематическую близость механизма к домену. Поэтому урон
концентрируется в "родном" для механизма домене: кинетика бьёт по density и
почти не задевает info-оси, ментальное воздействие — наоборот.

ЭТО ПЕРВЫЙ ЧЕРНОВОЙ ПРОХОД. Конкретно инферентный момент, который стоит
сверить с вами: направление сплеша берётся из ЗНАКА веса contributor'а
(положительный вес -> сосед сдвигается в ТУ ЖЕ сторону, что и основная ось;
отрицательный -> в ПРОТИВОПОЛОЖНУЮ). Это разумная попытка переиспользовать
существующие данные, а не 100% гарантированно то, что вы имели в виду.
"""

from dataclasses import dataclass
from typing import Dict, Optional

from .schema import load_json

_CUSHION_CFG = load_json("cushion_table.json")
_SKILL_CFG = load_json("skill_tables.json")
_MECHANISM_BASE_WEIGHTS = _SKILL_CFG["mechanism_base_weights"]
_MECHANISM_DEFAULT_AFFINITY = 0.3  # тот же дефолт, что и в generators/skill_gen.py::choose_mechanism


@dataclass
class Attack:
    mechanism: str    # ЧЕМ — например "Кинетика (удар/импульс)", из data/skill_tables.json → mechanism_pool
    axis: str         # ЧТО — полное имя оси, например "matter.density"
    direction: str     # КАК — "push_high" | "push_low" (главные направления для базового столкновения)
    magnitude: float   # С КАКОЙ СИЛОЙ — 0..1, это ВСЯ сила удара целиком, не "ещё сверху"


def mechanism_affinity(mechanism: str, domain: str) -> float:
    """Насколько механизм 'свой' для домена — берём прямо из таблицы, которая
    уже это описывает, ничего нового не считаем."""
    return _MECHANISM_BASE_WEIGHTS.get(domain, {}).get(mechanism, _MECHANISM_DEFAULT_AFFINITY)


def resolve_attack(attack: Attack) -> Dict[str, float]:
    """Возвращает {ось: сдвиг(со знаком)}: основная ось + её 'сплеш'-соседи из
    contributors той же оси в cushion_table.json. Сумма |сдвигов| эквивалентна
    magnitude — сплеш вычитается из основного урона, не добавляется сверху."""
    main_axis = attack.axis
    main_sign = 1.0 if attack.direction == "push_high" else -1.0

    cfg = _CUSHION_CFG["axes"].get(main_axis, {})
    contributors = cfg.get("contributors", [])

    # сырые веса ДО учёта механизма: 1.0 для основной оси, |weight| для каждого 'соседа'
    # (если один и тот же сосед указан дважды с affects=plus/minus — берём оба вклада)
    raw_weights: Dict[str, float] = {main_axis: 1.0}
    contrib_sign: Dict[str, float] = {main_axis: 1.0}
    for c in contributors:
        src = c["source"]
        raw_weights[src] = raw_weights.get(src, 0.0) + abs(c["weight"])
        # если веса разного знака при affects plus/minus — берём знак последнего
        # (для сплеша это не так критично, как для сопротивления)
        contrib_sign[src] = 1.0 if c["weight"] >= 0 else -1.0

    # механизм-модификатор: масштабирует вес каждой оси по близости её ДОМЕНА к механизму
    scaled_weights: Dict[str, float] = {}
    for axis_key, w in raw_weights.items():
        domain = axis_key.split(".")[0]
        scaled_weights[axis_key] = w * mechanism_affinity(attack.mechanism, domain)

    total = sum(scaled_weights.values())
    if total <= 0:
        return {main_axis: attack.magnitude * main_sign}

    shifts: Dict[str, float] = {}
    for axis_key, w in scaled_weights.items():
        share = w / total
        sign = main_sign if axis_key == main_axis else main_sign * contrib_sign[axis_key]
        shifts[axis_key] = attack.magnitude * share * sign

    return shifts
