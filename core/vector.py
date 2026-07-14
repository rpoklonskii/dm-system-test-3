"""
Profile — единый носитель 12-осевого вектора (matter/info/energy/spacetime x 3 оси).

Почему не плоский словарь (как было в трёх аутсорс-файлах) и не "чистый" датакласс
Vector3 x4 (как в оригинале)?

  - Наружу Profile выглядит и ведёт себя как словарь {"domain.axis": float} —
    его так же легко сохранить в JSON (save/load миров) и так же легко читали
    старые функции (get_material(profile["matter.plasticity"], ...) и т.п.).
  - Внутри он ЗНАЕТ метаданные каждой оси (описание, good_high, кто на кого
    влияет) из data/axes.json и умеет:
      * валидировать/клэмпить значения (никогда не вылезет за [-1, 1]);
      * считать richness/magnitude по домену;
      * мутировать/наследовать С УЧЁТОМ корреляций между осями — то есть если
        поднимается matter.density, он сам (по весам из axes.json) слегка
        толкает matter.cohesion, spacetime.topology и т.д. Это и есть тот
        "вектора сильно влияют друг на друга" механизм, который в дальнейшем
        должен стать ключевым, поэтому вынесен в одно место, а не размазан
        по трём копипастам mutate_profile/generate_faction_profile/mutate_mob.

Правило простое: одна ось меняется -> по declared correlations в axes.json
слегка толкаются другие -> ВСЁ клэмпится -> и только потом ложится фоновый шум.
Ничего не происходит "магически" вне этого файла.
"""

import random
from typing import Dict, Iterable, List, Optional, Tuple

from .schema import load_json, validate_axes, TableError

_AXES_DATA = load_json("axes.json")
validate_axes(_AXES_DATA)

AXES: Dict[str, dict] = _AXES_DATA["axes"]
AXIS_KEYS: List[str] = list(AXES.keys())
DOMAINS: List[str] = _AXES_DATA["domains"]
DOMAIN_AXES: Dict[str, List[str]] = {d: [a for a in AXIS_KEYS if a.startswith(d + ".")] for d in DOMAINS}
BAND5_THRESHOLDS: List[float] = _AXES_DATA["band5_thresholds"]
BAND7_THRESHOLDS: List[float] = _AXES_DATA["band7_thresholds"]
BAND3_THRESHOLD: float = _AXES_DATA["band3_threshold"]
COLLAPSE_EFFECTS: Dict[str, str] = _AXES_DATA["collapse_effects"]


def clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def gauss_clamped(mean: float, sigma: float) -> float:
    return clamp(random.gauss(mean, sigma))


def band_idx5(value: float) -> int:
    """0..4 по тем же порогам, что использовались во всех трёх аутсорс-файлах."""
    t = BAND5_THRESHOLDS
    if value <= t[0]: return 0
    if value <= t[1]: return 1
    if value < t[2]: return 2
    if value < t[3]: return 3
    return 4


def band_idx7(value: float) -> int:
    """-3..3 по порогам оригинала (используется для 'школьных' описаний info/energy)."""
    t = BAND7_THRESHOLDS
    if value <= t[0]: return -3
    if value <= t[1]: return -2
    if value <= t[2]: return -1
    if value < t[3]: return 0
    if value < t[4]: return 1
    if value < t[5]: return 2
    return 3


def band3(value: float) -> str:
    if value <= -BAND3_THRESHOLD: return "lo"
    if value >= BAND3_THRESHOLD: return "hi"
    return "mid"


def axis_good_high(axis: str) -> Optional[bool]:
    return AXES[axis]["good_high"]


class Profile:
    """12-осевой вектор. Ведёт себя как словарь: profile["matter.density"]."""

    __slots__ = ("_v",)

    def __init__(self, values: Optional[Dict[str, float]] = None):
        base = {k: 0.0 for k in AXIS_KEYS}
        if values:
            for k, v in values.items():
                if k not in AXES:
                    raise TableError(f"Неизвестная ось профиля: '{k}' (нет в data/axes.json)")
                base[k] = clamp(float(v))
        self._v = base

    # --- словарное поведение (совместимость со старым кодом-аутсорсом) ---
    def __getitem__(self, key: str) -> float:
        return self._v[key]

    def __setitem__(self, key: str, value: float) -> None:
        if key not in AXES:
            raise TableError(f"Неизвестная ось профиля: '{key}'")
        self._v[key] = clamp(float(value))

    def __contains__(self, key: str) -> bool:
        return key in self._v

    def items(self):
        return self._v.items()

    def keys(self):
        return self._v.keys()

    def values(self):
        return self._v.values()

    def get(self, key: str, default: float = 0.0) -> float:
        return self._v.get(key, default)

    def to_dict(self) -> Dict[str, float]:
        return dict(self._v)

    @classmethod
    def from_dict(cls, d: Dict[str, float]) -> "Profile":
        return cls(d)

    def copy(self) -> "Profile":
        return Profile(dict(self._v))

    # --- агрегаты по домену ---
    def domain_values(self, domain: str) -> Tuple[float, float, float]:
        a, b, c = DOMAIN_AXES[domain]
        return self._v[a], self._v[b], self._v[c]

    def richness(self, domain: str) -> float:
        """Проекция на 'полезный' полюс (не сырая длина вектора — фикс бага
        из оригинала: пустая оболочка в анти-полюсах больше не 'богата')."""
        total = 0.0
        for axis in DOMAIN_AXES[domain]:
            good = axis_good_high(axis)
            v = self._v[axis]
            if good is True:
                total += v
            elif good is False:
                total += -v
            # None (категориальная ось вроде carrier) не участвует
        return total

    def magnitude(self, domain: str) -> float:
        return sum(abs(self._v[a]) for a in DOMAIN_AXES[domain]) / 3.0

    def richness_by_domain(self) -> Dict[str, float]:
        return {d: self.richness(d) for d in DOMAINS}

    def dominant_domain(self) -> str:
        weighted = {d: sum(abs(v) for v in self.domain_values(d)) for d in DOMAINS}
        return max(weighted, key=weighted.get)

    def dominant_axis(self, within_domain: Optional[str] = None, exclude: Iterable[str] = ()) -> Tuple[str, float]:
        """Ось с максимальным |значением|, опционально только внутри домена."""
        candidates = DOMAIN_AXES[within_domain] if within_domain else AXIS_KEYS
        best_axis, best_val = None, -1.0
        for a in candidates:
            if a in exclude:
                continue
            v = self._v[a]
            if abs(v) >= best_val:
                best_axis, best_val = a, abs(v)
        return best_axis, self._v[best_axis]

    def top_axes(self, count: int = 3) -> List[Tuple[str, float]]:
        return sorted(self._v.items(), key=lambda kv: abs(kv[1]), reverse=True)[:count]

    def strong_axes(self, threshold: float = 0.4) -> List[str]:
        return [k for k, v in self._v.items() if abs(v) > threshold]

    def is_near_collapse(self, axis: str, value: Optional[float] = None) -> Optional[str]:
        v = self._v[axis] if value is None else value
        if abs(v) < 0.65:
            return None
        sign = "+" if v > 0 else "-"
        return COLLAPSE_EFFECTS.get(f"{axis}:{sign}")

    # --- генерация / мутация / наследование, ОБЩИЕ для локаций/фракций/мобов ---
    @staticmethod
    def generate(
        dominant_count_weights: Dict[int, float],
        dominant_sigma: float = 0.8,
        background_sigma: float = 0.10,
        propagate_correlations: bool = True,
        propagation_factor: float = 0.5,
    ) -> "Profile":
        """Единый генератор 'с нуля', заменяющий generate_location_profile /
        generate_faction_profile(is_invader) / generate_spiky_profile — они
        отличались только весами (dominant_sigma/background_sigma/кол-во
        доминант), сама механика была одна и та же."""
        counts = list(dominant_count_weights.keys())
        weights = list(dominant_count_weights.values())
        num_dominant = random.choices(counts, weights=weights)[0]
        dominant_domains = random.sample(DOMAINS, min(num_dominant, len(DOMAINS)))

        values: Dict[str, float] = {}
        for d in DOMAINS:
            is_dom = d in dominant_domains
            for axis in DOMAIN_AXES[d]:
                values[axis] = gauss_clamped(0.0, dominant_sigma if is_dom else background_sigma)

        profile = Profile(values)
        if propagate_correlations:
            profile._propagate(dominant_domains, propagation_factor)
        return profile

    def _propagate(self, source_domains: Iterable[str], factor: float) -> None:
        """Однократный проход: для каждой оси из 'сработавших' доменов толкаем
        связанные оси согласно весам correlations из axes.json. Так домены не
        живут в вакууме — толчок в matter слегка отзывается в spacetime и т.д.,
        но исход всё равно случаен (сила толчка регулируется, а не жёстко
        задаётся) и почти всегда меньше, чем собственный шум оси."""
        source_axes = set()
        for d in source_domains:
            source_axes.update(DOMAIN_AXES[d])
        for axis in source_axes:
            val = self._v[axis]
            if abs(val) < 0.2:
                continue
            for corr in AXES[axis].get("correlations", []):
                target = corr["target"]
                nudge = val * corr["weight"] * factor
                self._v[target] = clamp(self._v[target] + nudge)

    def mutate(self, volatility: float = 0.2, propagate: bool = True, propagation_factor: float = 0.3) -> "Profile":
        """Аналог mutate_profile()/mutate_mob(): дрожание вокруг текущих значений."""
        new_values = {k: clamp(v + random.gauss(0, volatility)) for k, v in self._v.items()}
        result = Profile(new_values)
        if propagate:
            touched = [d for d in DOMAINS if result.magnitude(d) > 0.3]
            result._propagate(touched, propagation_factor)
        return result

    @staticmethod
    def spawn_from(parent: "Profile", sigma: float = 0.25, propagate: bool = True) -> "Profile":
        """Аналог 'эндемики наследуют профиль локации' из Dm_fraction: новый
        профиль = профиль родителя + случайное отклонение. Используется и для
        локация -> фракция, и для фракция -> моб — единая функция вместо двух
        похожих кусков кода в разных файлах."""
        new_values = {k: gauss_clamped(v, sigma) for k, v in parent.items()}
        result = Profile(new_values)
        if propagate:
            touched = [d for d in DOMAINS if result.magnitude(d) > 0.3]
            result._propagate(touched, 0.3)
        return result

    def nudge_axis(self, axis: str, mean: float, sigma: float, propagate: bool = True) -> None:
        """Точечный сдвиг одной оси (роль моба, влияние локации и т.п.),
        с опциональным распространением по корреляциям."""
        self._v[axis] = gauss_clamped(self._v[axis] + mean, sigma)
        if propagate:
            self._propagate([axis.split(".")[0]], 0.3)

    def __repr__(self) -> str:
        parts = ", ".join(f"{k}={v:+.2f}" for k, v in self._v.items())
        return f"Profile({parts})"
