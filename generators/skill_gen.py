"""
Генератор навыков.

Движок (что вообще такое навык: target/direction/duration/trigger/mana_cost,
коллапс-эффекты, составные навыки "вырвать-и-выковать") — из оригинала
Dm_complex_old.py, он не тронут по существу.

Флейвор/текст навыка — из Dm_skills.py: словарь синергий (пара сильных осей
даёт название феномена вроде "Некромантия") и 5-уровневая лестница текста
на КАЖДУЮ ось отдельно (get_action_lore), вместо одной общей лестницы на
весь механизм. Это признано лучшей механикой текста, поэтому она заменяет
mechanism_intensity_phrase/flavor из оригинала при рендере.

Работает поверх core.vector.Profile — то есть навыки можно сгенерировать
ЛЮБОМУ существу с профилем: мобу из faction_gen, аномалии локации и т.д.,
а не только выделенному классу "мага".
"""

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core import Profile, Era, DOMAIN_AXES, DOMAINS, clamp, gauss_clamped, magic_title, tech_title
from core.schema import load_json, validate_skill_tables

_T = load_json("skill_tables.json")
validate_skill_tables(_T)

DIRECTIONS: List[str] = _T["directions"]
DIRECTIONS_EXCLUDED_FOR_SELF = set(_T["directions_excluded_for_self"])
DURATIONS: List[str] = _T["durations"]
TRIGGERS: List[str] = _T["triggers"]
_SYNERGY_PAIRS = {frozenset(p["axes"]): p["name"] for p in _T["synergy_phenomena"]["pairs"]}
_STRONG_AXIS_THRESHOLD = _T["synergy_phenomena"]["strong_axis_threshold"]
_ACTIVE_VECTOR_THRESHOLD = _T["active_vector_strength_threshold"]


# =========================================================
# Носитель навыков ("кастер"): любой Profile + мировой контекст
# =========================================================
@dataclass
class SkillCaster:
    name: str
    profile: Profile
    era: Era
    paradigm: str
    mastery: int
    efficiency: float
    mana_pool: float
    affinity: str
    skills: List["Skill"] = field(default_factory=list)


def compute_efficiency(profile: Profile) -> float:
    """КПД плетения: насколько структурно выверена сама 'магия/технология'
    существа (info.order его профиля)."""
    return clamp(0.4 + 0.55 * profile["info.order"], 0.15, 1.4)


def compute_resource(profile: Profile, era: Era, paradigm: str, mastery: int) -> Tuple[float, str]:
    charge_component = 4.0 * profile["energy.charge"]
    base = 2.5 + charge_component + mastery * 0.5 + era.level * 0.2
    variance = {"Магия": 1.5, "Технология": 0.6, "Синтез": 1.0}.get(paradigm, 1.0)
    pool = max(0.5, random.gauss(base, variance))

    dom = profile.dominant_domain()
    anchor_label = {"matter": "вещество/плоть", "info": "смысл/паттерн", "energy": "сила/поток", "spacetime": "пространство/время"}[dom]
    affinity = f"{anchor_label} ({paradigm.lower()})"
    return round(pool, 1), affinity


def make_caster(name: str, profile: Profile, era: Era, paradigm: str, mastery: int) -> SkillCaster:
    efficiency = compute_efficiency(profile)
    mana_pool, affinity = compute_resource(profile, era, paradigm, mastery)
    return SkillCaster(name, profile, era, paradigm, mastery, efficiency, mana_pool, affinity)


# =========================================================
# Механизм воздействия (домен -> способ) + перекос от парадигмы
# =========================================================
def choose_mechanism(domain: str, paradigm: str) -> str:
    base = _T["mechanism_base_weights"].get(domain, {})
    boost = _T["paradigm_mechanism_boost"].get(paradigm, {})
    pool, weights = [], []
    for mech in _T["mechanism_pool"]:
        w = base.get(mech, 0.3) * boost.get(mech, 1.0)
        pool.append(mech)
        weights.append(w)
    return random.choices(pool, weights=weights)[0]


def mechanism_intensity_phrase(mechanism: str, magnitude: float) -> str:
    band = min(4, int(magnitude * 5))
    ladder = _T["mechanism_ladders"].get(mechanism, _T["mechanism_ladders"]["generic_ladder"])
    return ladder[band]


# =========================================================
# Синергии осей + процедурный текст домена (флейвор из Dm_skills)
# =========================================================
def _band5(x: float) -> int:
    from core import band_idx5
    return band_idx5(x)


def _describe_domain_words(domain: str, x: float, y: float, z: float) -> str:
    cfg = _T["domain_description_words"][domain]
    noun_key, adj_y_key, adj_z_key = list(cfg.keys())
    nouns, adjs_y, adjs_z = cfg[noun_key], cfg[adj_y_key], cfg[adj_z_key]
    i_x, i_y, i_z = _band5(x), _band5(y), _band5(z)
    parts = [adjs_z[i_z], adjs_y[i_y], nouns[i_x]]
    return " ".join(p for p in parts if p).strip()


def build_hybrid_mechanism(full_profile: Profile) -> Tuple[str, str]:
    """Возвращает (процедурная_фраза, тег_механизма). Если у профиля две
    'сильные' оси образуют известную пару — используется красивое название
    феномена (Некромантия, Псионика и т.п.) вместо сухого перечисления."""
    strong_axes = full_profile.strong_axes(_STRONG_AXIS_THRESHOLD)

    found_synergy_name = None
    if len(strong_axes) >= 2:
        for i in range(len(strong_axes)):
            for j in range(i + 1, len(strong_axes)):
                pair = frozenset([strong_axes[i], strong_axes[j]])
                if pair in _SYNERGY_PAIRS:
                    found_synergy_name = _SYNERGY_PAIRS[pair]
                    break
            if found_synergy_name:
                break

    vector_strengths = {d: full_profile.magnitude(d) for d in DOMAINS}
    phrases = {d: _describe_domain_words(d, *full_profile.domain_values(d)) for d in DOMAINS}

    active = sorted([d for d in DOMAINS if vector_strengths[d] >= _ACTIVE_VECTOR_THRESHOLD], key=lambda d: vector_strengths[d], reverse=True)
    if not active:
        active = [max(vector_strengths, key=vector_strengths.get)]

    if len(active) == 1:
        procedural_phrase = f"направляя {phrases[active[0]]}"
        mech_tag = f"Моно-домен ({active[0].capitalize()})"
    elif len(active) == 2:
        procedural_phrase = f"обрушивая {phrases[active[0]]}, который пронизан {phrases[active[1]]}"
        mech_tag = f"Би-Синтез ({active[0].capitalize()} + {active[1].capitalize()})"
    else:
        procedural_phrase = f"в каскаде, где {phrases[active[0]]} сплетается с {phrases[active[1]]}"
        mech_tag = "Мульти-Резонанс"

    if found_synergy_name:
        mech_tag = f"СИНЕРГИЯ: {found_synergy_name}"
        action_verb = random.choice(["используя феномен", "применяя", "обрушивая"])
        return f"{action_verb} [{found_synergy_name}], ({procedural_phrase})", mech_tag

    return procedural_phrase, mech_tag


def get_action_lore(axis: str, direction: str, magnitude: float) -> str:
    tier = min(4, int(magnitude * 5))
    generic = _T["generic_tiers"]
    if direction in generic:
        noun = _T["axis_accusative"].get(axis, f"свойство [{axis}]")
        return generic[direction][tier] + f" {noun}"

    tiers = _T["axis_action_tiers"].get(axis, {}).get(direction)
    if not tiers:
        return {"assimilate": "постепенно подминает весь профиль цели под свой",
                "override": "принудительно фиксирует ось цели, игнорируя сопротивление"}.get(direction, "воздействует на")
    return tiers[min(tier, len(tiers) - 1)]


# =========================================================
# Цель / направление / длительность / дистанция (движок оригинала)
# =========================================================
def target_weights_for(agency: float, matter_richness: float = 0.0, near_collapse: bool = False) -> Dict[str, float]:
    cfg = _T["target_weights"]
    w = dict(cfg["base"])
    if abs(agency) >= cfg["agency_summon_threshold"]:
        w["summon"] *= (1.0 + 2.0 * abs(agency))
    if matter_richness >= cfg["matter_richness_object_threshold"]:
        w["object"] *= (1.0 + 1.5 * matter_richness)
    if near_collapse:
        for k, mult in cfg["near_collapse_multipliers"].items():
            w[k] *= mult
    return w


def pick_direction(target: str, agency: float = 0.0) -> str:
    options = [d for d in DIRECTIONS if not (target == "self" and d in DIRECTIONS_EXCLUDED_FOR_SELF)]
    weights = []
    for d in options:
        w = 1.0
        if agency <= -0.3 and d in ("override", "push_high", "push_low", "invert"):
            w = 1.8
        elif agency >= 0.3 and d in ("transfer", "assimilate"):
            w = 1.8
        weights.append(w)
    return random.choices(options, weights=weights)[0]


def pick_duration(direction: str, mechanism: str, magnitude: float) -> str:
    dw = _T["duration_weights"]
    if direction == "assimilate":
        return random.choices(DURATIONS, weights=dw["assimilate"])[0]
    if mechanism in _T["coarse_mechanisms"] and magnitude >= 0.6:
        return random.choices(DURATIONS, weights=dw["coarse_high_magnitude"])[0]
    if mechanism in _T["fine_mechanisms"]:
        return random.choices(DURATIONS, weights=dw["fine_mechanism"])[0]
    return random.choices(DURATIONS, weights=dw["default"])[0]


def compute_range_tag(target: str, domain: str, mechanism: str) -> str:
    if target == "self": return "на себя"
    if target == "area": return "область (АОЕ)"
    if target == "summon": return "призыв (вне обычной дистанции)"
    if target == "object": return "контактно/предмет в руках"
    if mechanism == "Кинетика (удар/импульс)" and domain == "matter":
        return "ближний бой"
    if mechanism in ("Энергетический импульс", "Ментальное воздействие", "Социальное давление",
                     "Пространство-время (искажение)", "Информационный сбой (глюк/баг)"):
        return "дальнобойно"
    return "дистанция на усмотрение"


def classify_skill(target: str, domain: str, axis: str, direction: str, trigger: Optional[str] = None, duration: str = "") -> str:
    if target == "summon":
        return "Саммон/Призыв"
    if direction == "invert":
        return "Инверсия/Отражение"
    if direction == "assimilate":
        return "Ассимиляция/Заражение"
    if direction == "override":
        return "Материализация/Фиксация предмета" if target == "object" else "Принуждение (Доминирование)"
    if direction == "transfer":
        return "Вампиризм/Кража"
    if direction == "push_center":
        if target in ("self", "ally") and (trigger in ("on_damage", "on_targeted") or "устойчиво" in duration or "навсегда" in duration):
            return "Щит/Сопротивление"
        return "Лечение/Стабилизация" if target in ("self", "ally") else "Усмирение/Нейтрализация"
    if target == "area":
        return "АОЕ-контроль/Утилитарность"
    if target == "object":
        return "Воздействие на предмет"

    from core.vector import AXES
    good_high = AXES[axis]["good_high"]
    moves_toward_good = (direction == "push_high" and good_high is True) or (direction == "push_low" and good_high is False)

    if target == "self":
        return "Бафф (себе)" if moves_toward_good else "Риск/Жертва (себе)"
    if target == "ally":
        return "Бафф (союзнику)" if moves_toward_good else "Дружественный урон/Проклятие союзнику"
    if target == "enemy":
        if moves_toward_good:
            return "Аномалия: невольное усиление цели(?)"
        return "Атака" if domain in ("matter", "energy") else "Дебафф"
    return "Утилитарное воздействие"


# =========================================================
# Датакласс навыка
# =========================================================
@dataclass
class Skill:
    owner: str
    target: str
    domain: str
    axis: str
    direction: str
    duration: str
    full_profile: Profile
    own_cost: Optional[Tuple[str, str, float]] = None
    trigger: Optional[str] = None
    object_constraint: Optional[Dict] = None
    mechanism: str = ""
    category: str = ""
    mana_cost: float = 0.0
    magnitude: float = 0.5
    range_tag: str = ""

    def render(self) -> str:
        from core.vector import COLLAPSE_EFFECTS

        mech_phrase, mech_tag = build_hybrid_mechanism(self.full_profile)
        base_action = get_action_lore(self.axis, self.direction, self.magnitude)

        if self.target == "self":
            target_str = "(на себя)"
        elif self.target == "summon":
            target_str = "(призыв проекции)"
            noun = _T["axis_accusative"].get(self.axis, f"свойство [{self.axis}]")
            if self.direction == "push_center":
                base_action = f"формирует конструкт, чьё присутствие нормализует {noun} вокруг"
            elif self.direction == "invert":
                base_action = f"формирует конструкт, чьё присутствие искажает и обращает вспять {noun} вокруг"
            elif self.direction == "transfer":
                base_action = f"формирует конструкт, который поглощает {noun} из окружающей среды"
            else:
                base_action = f"формирует конструкт, чьё присутствие {base_action} вокруг"
        else:
            target_str = f"({self.target})"

        if "Щит" in self.category:
            noun = _T["axis_accusative"].get(self.axis, f"свойство [{self.axis}]")
            base_action = f"балансирует и защищает {noun}"

        trigger_text = f" [ПАССИВКА: {self.trigger}]" if self.trigger else " [АКТИВНО]"
        lore_line = f"✧ {self.owner}, {mech_phrase}, {base_action} {target_str}."

        cost_text = ""
        if self.own_cost:
            cd_ca, delta = f"{self.own_cost[0]}.{self.own_cost[1]}", self.own_cost[2]
            sign = "повышает" if delta > 0 else "понижает"
            cost_text = f"; ценой: {sign} свою ось [{cd_ca}] на {abs(delta):.2f}"

        oc_text = ""
        if self.object_constraint:
            oc = self.object_constraint
            if oc["kind"] == "create":
                oc_text = f"\n    материализует предмет с [{oc['domain']}.{oc['axis']}] = {oc['value']:+.2f}"
            else:
                oc_text = f"\n    требование к предмету: [{oc['domain']}.{oc['axis']}] >= {oc['value']:.2f}"

        raw_shift = min(1.0, self.magnitude * 1.2)
        if self.direction == "push_low":
            shift_text = f"~{-raw_shift:.2f} (по шкале -1..1, до сопротивления)"
        elif self.direction == "push_high":
            shift_text = f"~{raw_shift:+.2f} (по шкале -1..1, до сопротивления)"
        else:
            shift_text = f"~{raw_shift:.2f} (знак зависит от текущего значения оси цели; до сопротивления)"

        collapse_key = f"{self.axis}:{'+' if self.direction == 'push_high' else ('-' if self.direction == 'push_low' else '?')}"
        collapse_line = ""
        if collapse_key in COLLAPSE_EFFECTS and self.target in ("enemy", "area"):
            collapse_line = f"\n    при дожиме до предела: {COLLAPSE_EFFECTS[collapse_key]}"

        lines = [
            lore_line,
            f"  [{self.category}]{trigger_text} | Механизм: {mech_tag} ({mechanism_intensity_phrase(self.mechanism, self.magnitude)})",
            f"  Вектор: {self.axis} {self.direction} | цель: {self.target} | дистанция: {self.range_tag}",
            f"  СИЛА: {self.magnitude:.2f}/1.0 -> СДВИГ ОСИ ЦЕЛИ: {shift_text}",
            f"  длительность: {self.duration}{cost_text} -- {self.mana_cost:.2f} маны{oc_text}{collapse_line}",
        ]
        return "\n".join(lines) + "\n"


# =========================================================
# Генерация навыка
# =========================================================
def _compute_mana_cost(target: str, duration: str, magnitude: float, efficiency: float) -> float:
    cfg = _T["mana_cost"]
    base = cfg["base"]
    if target in ("area", "summon"):
        base += cfg["target_area_or_summon_add"]
    if duration == "навсегда":
        base += cfg["duration_forever_add"]
    elif "накопительно" in duration:
        base += cfg["duration_накопительно_add"]
    elif "подготовкой" in duration:
        base += cfg["duration_подготовкой_add"]
    elif "устойчиво" in duration:
        base += cfg["duration_устойчиво_add"]
    base *= (0.6 + magnitude)
    return round(base / max(0.15, efficiency), 2)


def generate_skill(caster: SkillCaster) -> Skill:
    weights = {d: max(caster.profile.richness(d), 0) + 0.4 for d in DOMAINS}
    domain = random.choices(list(weights), weights=list(weights.values()))[0]
    axis = random.choice([a for a in DOMAIN_AXES[domain] if not a.endswith(".carrier")])

    agency = caster.profile["info.agency"]
    matter_richness = max(caster.profile.richness("matter"), 0)
    dom_axis, dom_val = caster.profile.dominant_axis()
    collapse = caster.profile.is_near_collapse(dom_axis, dom_val) is not None

    tw = target_weights_for(agency, matter_richness, collapse)
    target = random.choices(list(tw), weights=list(tw.values()))[0]
    direction = pick_direction(target, agency)
    mechanism = choose_mechanism(domain, caster.paradigm)

    magnitude_mean = 0.25 + 0.05 * caster.mastery + 0.15 * abs(dom_val)
    magnitude = clamp(random.gauss(magnitude_mean, 0.2), 0.05, 1.0)
    duration = pick_duration(direction, mechanism, magnitude)

    own_cost = None
    if target != "self" and random.random() < 0.35:
        cd = random.choice(DOMAINS)
        ca = random.choice([a for a in DOMAIN_AXES[cd] if not a.endswith(".carrier")])
        own_cost = (cd, ca.split(".")[1], round(random.uniform(0.1, 0.4), 2) * random.choice([-1, 1]))

    object_constraint = None
    if target == "object":
        if direction == "override":
            cd = random.choice(DOMAINS)
            ca = random.choice([a for a in DOMAIN_AXES[cd] if not a.endswith(".carrier")])
            object_constraint = {"kind": "create", "domain": cd, "axis": ca.split(".")[1],
                                  "value": round(random.uniform(0.5, 1.0) * random.choice([-1, 1]), 2)}
        elif random.random() < 0.4:
            cd = random.choice(DOMAINS)
            ca = random.choice([a for a in DOMAIN_AXES[cd] if not a.endswith(".carrier")])
            object_constraint = {"kind": "require", "domain": cd, "axis": ca.split(".")[1],
                                  "value": round(random.uniform(0.4, 1.0), 2)}

    trigger = None
    if direction == "invert" and target in ("object", "enemy"):
        trigger = "on_targeted" if random.random() < 0.7 else None
    elif direction == "push_center" and target in ("self", "ally") and random.random() < 0.4:
        trigger = random.choice(["on_damage", "on_targeted"])
    elif random.random() < 0.20:
        trigger = random.choice(TRIGGERS)

    category = classify_skill(target, domain, axis, direction, trigger, duration)
    range_tag = compute_range_tag(target, domain, mechanism)
    mana_cost = _compute_mana_cost(target, duration, magnitude, caster.efficiency)

    return Skill(caster.name, target, domain, axis, direction, duration, caster.profile,
                 own_cost, trigger, object_constraint, mechanism, category, mana_cost, magnitude, range_tag)


def generate_compound_skill(caster: SkillCaster) -> Skill:
    """Композиция transfer(enemy)+override(object): рвёт кусок вектора у врага
    и прессует вырванное в предмет — не новый примитив, а связка двух."""
    cd = random.choice(DOMAINS)
    ca = random.choice([a for a in DOMAIN_AXES[cd] if not a.endswith(".carrier")])
    mechanism = choose_mechanism(cd, caster.paradigm)
    magnitude = clamp(random.gauss(0.35 + 0.05 * caster.mastery, 0.2), 0.1, 1.0)
    stolen_value = round(magnitude * random.choice([-1, 1]), 2)

    object_constraint = {"kind": "create", "domain": cd, "axis": ca.split(".")[1], "value": stolen_value}
    mana_cost = round((2.0 + magnitude) / max(0.15, caster.efficiency), 2)

    return Skill(caster.name, "object", cd, ca, "transfer", "навсегда", caster.profile,
                 mechanism=mechanism, category="Похищение и Ковка (составной)",
                 mana_cost=mana_cost, magnitude=magnitude, range_tag=compute_range_tag("object", cd, mechanism),
                 object_constraint=object_constraint)


def generate_skill_entry(caster: SkillCaster) -> Skill:
    if random.random() < _T["compound_skill_chance"]:
        return generate_compound_skill(caster)
    return generate_skill(caster)


def generate_skills_for(caster: SkillCaster, count: Optional[int] = None) -> List[Skill]:
    if count is None:
        total_power = sum(max(v, 0) for v in caster.profile.richness_by_domain().values())
        count = 2 + (1 if total_power > 1.0 else 0) + (1 if total_power > 2.0 else 0)
        count = max(2, count)
    skills = [generate_skill_entry(caster) for _ in range(count)]
    caster.skills = skills
    return skills


if __name__ == "__main__":
    from core import Profile as _P

    era = Era.roll()
    print(f">>> ЭПОХА МИРА: {era.name} (уровень {era.level}, {era.paradigm})\n")

    for anchor_name in ["Маг материи", "Маг информации", "Маг энергии"]:
        profile = Profile.generate(dominant_count_weights={1: 0.6, 2: 0.4}, dominant_sigma=0.85, background_sigma=0.1)
        paradigm, magic_lvl, tech_lvl = "Магия", random.randint(1, 10), random.randint(0, 3)
        mastery = magic_lvl
        caster = make_caster(anchor_name, profile, era, paradigm, mastery)
        generate_skills_for(caster)

        print("=" * 70)
        print(f"МАГ: {caster.name} | Парадигма: {caster.paradigm} (мастерство {caster.mastery}) "
              f"| Магия:[{magic_lvl}] {magic_title(magic_lvl)}")
        print(f"Ресурс: {caster.mana_pool} маны | Аффинность: {caster.affinity} | КПД: {caster.efficiency:.2f}")
        print("-" * 70)
        for s in caster.skills:
            print(s.render())
        print("=" * 70 + "\n")
