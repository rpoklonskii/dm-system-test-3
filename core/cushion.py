"""
Подушки безопасности (cushion) — сколько каждая ось МОЖЕТ сдвинуться от нуля,
прежде чем сработает её персональный летальный/выводящий из строя эффект.

Это НЕ хп-бар: 12 осей = 12 независимых порогов (ось, знак). Убить моба можно
через любой из них по отдельности (раздавить, довести до безумия,
спровоцировать самоподрыв...), и они не суммируются друг с другом.

Порог по (axis, sign) существует ТОЛЬКО если для этой пары есть эффект в
data/axes.json -> collapse_effects. Если эффекта нет — эта сторона безопасна
(например matter.plasticity:- — предельно упругое тело в принципе не рвётся).

Формула порога:
    threshold = clamp( (base + self_reinforce*|value| + Σ additive) * Π multiplicative,
                        min_threshold, max_threshold )

  - self_reinforce: существо, уже живущее на экстремуме этой же оси, органически
    адаптировано к нему — толкать его дальше в ту же сторону чуть сложнее
    (диминишинг-ретёрнс, а не "чем ты безумнее, тем безумие тебе не страшно"
    в абсолютном смысле — просто предельный запас чуть шире).
  - additive contributors: другие оси напрямую расширяют/сужают порог
    (например cohesion расширяет порог density).
  - multiplicative contributors: другие оси МАСШТАБИРУЮТ уже накопленное
    (например energy.charge сужает порог density на процент, а не на фикс. число).
"""

"""
Подушки безопасности (cushion) — сколько существо МОЖЕТ быть СДВИНУТО от
своего же естественного (базового) профиля, прежде чем сработает её
персональный летальный/выводящий из строя эффект.

ВАЖНО (исправлено по итогам разбора бага): порог мерит СМЕЩЕНИЕ от базового
профиля существа, а НЕ абсолютную позицию от нуля. Существо, которое природой
рождено с density = -1 (эфирное создание), не находится "уже на грани смерти" —
оно просто такое, это его нормальное стабильное состояние. Убить его через
density можно, только если что-то СДВИНЕТ его ещё дальше в опасную сторону
относительно ЕГО ЖЕ точки покоя (а если оно уже на самом краю диапазона —
дальше сдвигать в эту сторону физически некуда, значит с этой стороны оно
неуязвимо; уязвимо оно тогда с противоположной стороны).

Это НЕ хп-бар: 12 осей = 12 независимых порогов (ось, знак). Убить моба можно
через любой из них по отдельности, и они не суммируются друг с другом.

Порог по (axis, sign) существует ТОЛЬКО если для этой пары есть эффект в
data/axes.json -> collapse_effects. Если эффекта нет — эта сторона безопасна.

Формула порога (contributors читаются из ТЕКУЩЕГО состояния — активный заряд
здесь и сейчас сужает подушку прямо во время боя; self_reinforce читается из
БАЗОВОГО профиля — адаптация к своей природе, а не к временному состоянию):

    threshold = clamp( (base + self_reinforce*|base_value| + Σ additive(current)) * Π multiplicative(current),
                        min_threshold, max_threshold )

    displacement = current_value - base_value
    fraction_used = |displacement относительно нужного знака| / threshold
"""

"""
Подушки безопасности (cushion) — сколько существо МОЖЕТ быть СДВИНУТО от
своего же естественного (базового) профиля, прежде чем сработает её
персональный летальный/выводящий из строя эффект.

МОДЕЛЬ ОБЩЕГО ПУЛА (по итогам разбора дисбаланса): раньше каждая из 16 подушек
считалась НЕЗАВИСИМО — можно было накачать контрибьюторами сразу все 16, и
никто за это не платил. Теперь формулы (base_threshold, self_reinforce,
contributors) считают не абсолютный порог, а СЫРОЙ ВЕС ("насколько эта сторона
в принципе хочет быть широкой" при таком профиле). Все 16 сырых весов затем
нормализуются на ОДИН фиксированный бюджет (`total_resist_pool` в
cushion_table.json) — то есть архитектура вектора не увеличивает суммарную
живучесть, а лишь ПЕРЕРАСПРЕДЕЛЯЕТ фиксированный пул между 16 подушками.
Закачал вес в density+ — забрал его у чего-то из оставшихся 15.

ВАЖНО: порог мерит СМЕЩЕНИЕ от базового профиля существа, а НЕ абсолютную
позицию от нуля (см. предыдущий фикс с density=-1).

Формула сырого веса (contributors читаются из ТЕКУЩЕГО состояния,
self_reinforce — из БАЗОВОГО):

    raw(axis,sign) = (base + self_reinforce*|base_value| + Σ additive(current)) * Π multiplicative(current)
    threshold(axis,sign) = clamp( total_resist_pool * raw(axis,sign) / Σ_всех_16 raw(*,*), min_threshold, max_threshold )
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .vector import Profile, AXIS_KEYS, COLLAPSE_EFFECTS, clamp
from .schema import load_json, TableError

_CFG = load_json("cushion_table.json")
_DEFAULTS = _CFG["defaults"]
_AXES_CFG = _CFG["axes"]
_TOTAL_POOL = _CFG["total_resist_pool"]
_POOL_MIN_THRESHOLD = _CFG["pool_min_threshold"]
_POOL_MAX_THRESHOLD = _CFG["pool_max_threshold"]

# Оси, участвующие в системе подушек. spacetime сознательно исключён (см. обсуждение:
# либо не влияет, либо влияет через разницу атакующий/цель — не через абсолютную позицию).
# info.meaning_density тоже исключена — зарезервирована под будущую механику "легенда переживает тело".
IN_SCOPE_AXES: List[str] = [
    "matter.density", "matter.cohesion", "matter.plasticity",
    "info.order", "info.agency", "info.meaning_density",
    "energy.charge", "energy.carrier", "energy.amplitude",
]
ALL_SLOTS: List[Tuple[str, str]] = [(axis, sign) for axis in IN_SCOPE_AXES for sign in ("plus", "minus")]


def validate_cushion_table(d: Dict) -> None:
    fn = "cushion_table.json"
    if "defaults" not in d or "axes" not in d:
        raise TableError(f"[{fn}] должны быть ключи 'defaults' и 'axes'")
    req = ["base_threshold", "self_reinforce"]
    missing = [k for k in req if k not in d["defaults"]]
    if missing:
        raise TableError(f"[{fn}] defaults: отсутствуют {missing}")
    for key in ["total_resist_pool", "pool_min_threshold", "pool_max_threshold"]:
        if key not in d:
            raise TableError(f"[{fn}] отсутствует обязательный ключ '{key}'")
    for axis, cfg in d["axes"].items():
        if axis.startswith("_"):
            continue
        if axis not in AXIS_KEYS:
            raise TableError(f"[{fn}] неизвестная ось '{axis}'")
        for c in cfg.get("contributors", []):
            if c["source"] not in AXIS_KEYS:
                raise TableError(f"[{fn}] ось '{axis}': contributor ссылается на неизвестную ось '{c['source']}'")
            if c["mode"] not in ("additive", "multiplicative"):
                raise TableError(f"[{fn}] ось '{axis}': mode должен быть additive/multiplicative, получено '{c['mode']}'")


validate_cushion_table(_CFG)


@dataclass
class AxisCushion:
    axis: str
    sign: str            # "plus" | "minus"
    base_value: float     # естественное (базовое) значение оси — точка отсчёта
    current_value: float  # текущее значение (после гипотетического удара/эффекта)
    threshold: Optional[float]   # None = эта сторона в принципе безопасна
    collapse_text: Optional[str]

    @property
    def displacement(self) -> float:
        return self.current_value - self.base_value

    @property
    def distance_left(self) -> Optional[float]:
        if self.threshold is None:
            return None
        relevant = self.displacement if self.sign == "plus" else -self.displacement
        return max(0.0, self.threshold - max(relevant, 0.0))

    @property
    def fraction_used(self) -> float:
        if self.threshold is None or self.threshold <= 0:
            return 0.0
        relevant = self.displacement if self.sign == "plus" else -self.displacement
        return clamp(max(relevant, 0.0) / self.threshold, 0.0, 1.0)


def _raw_score(current_profile: Profile, base_profile: Profile, axis: str, sign: str) -> float:
    """Сырой вес одной подушки — ДО нормализации на общий пул. Не путать с
    итоговым threshold: это просто 'насколько сильно эта сторона хочет быть
    широкой' при данном профиле, единицы условные, важны только относительно
    друг друга."""
    key = f"{axis}:{'+' if sign == 'plus' else '-'}"
    if key not in COLLAPSE_EFFECTS:
        return 0.0

    cfg = _AXES_CFG.get(axis, {})
    base = cfg.get("base_threshold", _DEFAULTS["base_threshold"])
    self_w = cfg.get("self_reinforce", _DEFAULTS["self_reinforce"])

    own_base_value = base_profile[axis]
    additive = self_w * abs(own_base_value)
    multiplier = 1.0

    for c in cfg.get("contributors", []):
        if c.get("affects", "both") not in ("both", sign):
            continue
        src_val = current_profile[c["source"]]
        transformed = src_val if c.get("transform", "signed") == "signed" else abs(src_val)
        if c["mode"] == "additive":
            additive += c["weight"] * transformed
        else:
            multiplier *= max(0.05, 1.0 + c["weight"] * transformed)

    return max(0.02, (base + additive) * multiplier)  # пол, чтобы не уйти в 0/отрицательное при нормализации


def compute_all_raw_scores(current_profile: Profile, base_profile: Profile) -> Dict[Tuple[str, str], float]:
    return {(axis, sign): _raw_score(current_profile, base_profile, axis, sign) for axis, sign in ALL_SLOTS}


def compute_threshold(current_profile: Profile, base_profile: Profile, axis: str, sign: str) -> Optional[float]:
    key = f"{axis}:{'+' if sign == 'plus' else '-'}"
    if key not in COLLAPSE_EFFECTS:
        return None
    if (axis, sign) not in ALL_SLOTS:
        # ось вне текущей области видимости пула (например spacetime) — не участвует в перераспределении
        return None

    raw_scores = compute_all_raw_scores(current_profile, base_profile)
    total = sum(raw_scores.values())
    if total <= 0:
        return _POOL_MIN_THRESHOLD
    share = raw_scores[(axis, sign)] / total
    return clamp(_TOTAL_POOL * share, _POOL_MIN_THRESHOLD, _POOL_MAX_THRESHOLD)


def compute_cushion(current_profile: Profile, axis: str, sign: str, base_profile: Optional[Profile] = None) -> AxisCushion:
    """Если base_profile не передан — считаем, что удара ещё не было
    (current == base), т.е. существо в своём естественном состоянии."""
    if base_profile is None:
        base_profile = current_profile

    key = f"{axis}:{'+' if sign == 'plus' else '-'}"
    threshold = compute_threshold(current_profile, base_profile, axis, sign)
    return AxisCushion(
        axis=axis, sign=sign,
        base_value=base_profile[axis], current_value=current_profile[axis],
        threshold=threshold,
        collapse_text=COLLAPSE_EFFECTS.get(key),
    )


def compute_all_cushions(current_profile: Profile, base_profile: Optional[Profile] = None) -> Dict[str, Dict[str, AxisCushion]]:
    result: Dict[str, Dict[str, AxisCushion]] = {}
    for axis in AXIS_KEYS:
        result[axis] = {
            "plus": compute_cushion(current_profile, axis, "plus", base_profile),
            "minus": compute_cushion(current_profile, axis, "minus", base_profile),
        }
    return result
