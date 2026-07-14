"""
Генератор фракций и мобов. Экосистемная логика (эндемики наследуют профиль
локации, захватчики — нет; дипломатия зависит от agency/order обеих сторон)
взята из Dm_fraction.py как лучшая механика для этой задачи. Отличия от
оригинального файла:
  - Profile вместо плоского dict — наследование и мутации идут через
    Profile.inherit_from()/mutate() с распространением корреляций (core.vector),
    а не через три отдельные копии одной и той же вероятностной формулы;
  - весь текст и веса — в data/faction_tables.json;
  - каждая фракция/моб роллит paradigm/magic_lvl/tech_lvl от общей Era мира
    (core.world.roll_being_paradigm) — понадобится generators/skill_gen.py,
    чтобы навыки существа были согласованы с магией/технологией его мира.
"""

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core import Profile, Era, band_idx5, roll_being_paradigm
from core import names
from core.schema import load_json, validate_faction_tables

_T = load_json("faction_tables.json")
validate_faction_tables(_T)

DOMAIN_ID_TO_RU = {"matter": "Материя", "info": "Информация", "energy": "Энергия", "spacetime": "Пространство"}


# =========================================================
# Профили
# =========================================================
def generate_faction_profile(loc_profile: Profile, is_invader: bool) -> Tuple[Profile, str]:
    gen = _T["generation"]
    if is_invader:
        origin_status = "[ЗАХВАТЧИКИ] Чужеродная фракция, вторгшаяся в локацию."
        weights = {int(k): v for k, v in gen["invader_dominant_count_weights"].items()}
        faction_profile = Profile.generate(
            dominant_count_weights=weights,
            dominant_sigma=gen["invader_sigma"],
            background_sigma=gen["invader_background_sigma"],
        )
    else:
        origin_status = "[ЭНДЕМИКИ] Коренные обитатели/хранители локации."
        faction_profile = Profile.spawn_from(loc_profile, sigma=gen["endemic_inherit_sigma"])
        # влияние локации на эндемиков: храмы рождают фанатиков, форты - стражей
        if loc_profile["info.meaning_density"] > 0.3:
            faction_profile.nudge_axis("info.meaning_density", 0.4, 0.2)
        if loc_profile["info.order"] > 0.3:
            faction_profile.nudge_axis("info.order", 0.4, 0.2)

    # физическое ограничение: в тесноте существа чаще мельчают
    if loc_profile["spacetime.topology"] > 0.3 and faction_profile["matter.density"] > 0.2:
        faction_profile.nudge_axis("matter.density", -0.5, 0.3, propagate=False)

    # биологическая корреляция: крупные чаще одиночки, мелкие - в стае
    size_influence = faction_profile["matter.density"] * -0.7
    faction_profile["matter.cohesion"] = faction_profile["matter.cohesion"] + random.gauss(size_influence, 0.3)

    return faction_profile, origin_status


def mutate_mob(faction_profile: Profile, role: str) -> Profile:
    gen = _T["generation"]
    mob = faction_profile.mutate(volatility=gen["mob_mutation_sigma"], propagate=False)

    deltas = _T["roles"]["role_deltas"].get(role, {})
    for axis, (mean, sigma) in deltas.items():
        if axis == "random_axis_shift":
            anomaly_key = random.choice(list(mob.keys()))
            mob[anomaly_key] = mob[anomaly_key] + random.choice([-1, 1]) * random.gauss(mean, sigma)
        else:
            mob.nudge_axis(axis, mean, sigma, propagate=False)

    size_influence = mob["matter.density"] * -0.8
    mob["matter.cohesion"] = mob["matter.cohesion"] + random.gauss(size_influence, 0.3)
    return mob


def get_primary_domains(profile: Profile) -> str:
    domains = {"Материя": 0.0, "Информация": 0.0, "Энергия": 0.0, "Пространство": 0.0}
    for k, v in profile.items():
        domains[DOMAIN_ID_TO_RU[k.split(".")[0]]] += abs(v)
    sorted_doms = sorted(domains.items(), key=lambda x: x[1], reverse=True)
    if sorted_doms[1][1] > sorted_doms[0][1] * 0.8 and sorted_doms[1][1] > 0.5:
        return f"{sorted_doms[0][0]} и {sorted_doms[1][0]}"
    return sorted_doms[0][0]


# =========================================================
# Имена
# =========================================================
def generate_faction_name(profile: Profile) -> str:
    forms = _T["name_forms"]
    i_a, i_o = band_idx5(profile["info.agency"]), band_idx5(profile["info.order"])

    if i_a <= 1:
        form = random.choice(forms["low_agency"])
    elif i_a == 2:
        form = random.choice(forms["mid_agency_low_order"] if i_o <= 1 else forms["mid_agency_mid_order"] if i_o == 2 else forms["mid_agency_high_order"])
    else:
        form = random.choice(forms["high_agency_low_order"] if i_o <= 1 else forms["high_agency_high_order"])

    top_vec = max(profile.items(), key=lambda x: abs(x[1]))[0]
    essences = _T["name_essences"]
    essence = random.choice(essences.get(top_vec, essences["fallback"]))
    return f"{form} {essence}"


def generate_mob_name(profile: Profile, base_role: str) -> str:
    """УСТАРЕЛО: заменено core.names.generate_mob_title() — оставлено на
    случай, если где-то ещё используется старый скудный формат имени."""
    cfg = _T["mob_name"]
    dom = get_primary_domains(profile).split(" ")[0]
    nature = random.choice(cfg["nature_by_domain"].get(dom, cfg["nature_by_domain"]["fallback"]))

    i_a = band_idx5(profile["info.agency"])
    core = random.choice(cfg["core_low_agency"] if i_a <= 1 else cfg["core_mid_agency"] if i_a == 2 else cfg["core_high_agency"])

    prefix = random.choice(cfg["role_prefix"].get(base_role, cfg["role_prefix"]["fallback"]))
    return f"{prefix} {nature}{core.lower()}"


# =========================================================
# Флейвор
# =========================================================
def get_flesh(profile: Profile) -> str:
    cfg = _T["flesh"]
    mat_d, mat_c, mat_p = profile["matter.density"], profile["matter.cohesion"], profile["matter.plasticity"]
    if mat_d < -0.3:
        low = cfg["low_density_branch"]
        if profile["spacetime.localization"] > low["astral_localization_threshold"]:
            base_nature = low["astral"]
        elif profile["info.meaning_density"] > low["meaning_threshold"]:
            base_nature = low["concept"]
        elif profile["energy.amplitude"] > low["amplitude_threshold"]:
            base_nature = low["energy_blob"]
        else:
            base_nature = low["fallback"]
    else:
        base_nature = cfg["base_by_plasticity"][band_idx5(mat_p)]

    cohesion_mod = cfg["cohesion_modifier"][band_idx5(mat_c)]
    return f"{base_nature} {cohesion_mod}".strip()


def get_size(density: float) -> str:
    return _T["size_by_density"][band_idx5(density)]


def get_quantity(cohesion: float) -> str:
    return _T["quantity_by_cohesion"][band_idx5(cohesion)]


def get_emotions_and_mind(agency: float, order: float, meaning: float) -> Tuple[str, str]:
    cfg = _T["mind_and_emotion"]
    i_a, i_o, i_m = band_idx5(agency), band_idx5(order), band_idx5(meaning)

    if i_a <= 1:
        c = cfg["low_agency"]
        mind = c["mind_by_order"]["low"] if i_o <= 1 else c["mind_by_order"]["high"]
        if i_m >= 3: emotion = c["emotion_by_meaning"]["high"]
        elif i_m <= 1: emotion = c["emotion_by_meaning"]["low"]
        else: emotion = c["emotion_by_meaning"]["mid"]
    elif i_a == 2:
        c = cfg["mid_agency"]
        mind = c["mind_by_order"]["low"] if i_o <= 1 else c["mind_by_order"]["high"]
        if i_m >= 3: emotion = c["emotion_rules"]["high_meaning"]
        elif i_o <= 1: emotion = c["emotion_rules"]["low_order"]
        else: emotion = c["emotion_rules"]["fallback"]
    else:
        c = cfg["high_agency"]
        mind = c["mind_by_order"]["low_mid"] if i_o <= 2 else c["mind_by_order"]["high"]
        emotion = c["emotion_by_order"]["low"] if i_o <= 1 else c["emotion_by_order"]["high"]

    return mind, emotion


def get_tactics(emotion: str, agency: float, order: float) -> str:
    cfg = _T["tactics"]
    i_o = band_idx5(order)
    if "отсутствуют" in emotion:
        return cfg["no_emotion"]["low_order"] if i_o <= 1 else cfg["no_emotion"]["high_order"]
    elif "голод" in emotion or "ярость" in emotion:
        return cfg["hunger_or_rage"]
    elif "Фанатизм" in emotion or "экстаз" in emotion:
        return cfg["fanaticism"]
    elif "Садизм" in emotion or "высокомерие" in emotion:
        return cfg["sadism_or_arrogance"]
    return cfg["default"]


def get_faction_hierarchy(agency: float, order: float) -> str:
    cfg = _T["hierarchy"]
    if random.random() < cfg["madness_theocracy_chance"]:
        return cfg["madness_theocracy"]
    return cfg["by_order"][band_idx5(order)]


def get_faction_goal(fac_profile: Profile, loc_profile: Profile, is_invader: bool) -> str:
    cfg = _T["goals"]
    loc_m = band_idx5(loc_profile["info.meaning_density"])
    fac_m, fac_o = band_idx5(fac_profile["info.meaning_density"]), band_idx5(fac_profile["info.order"])

    loc_context = cfg["loc_context_by_meaning"]["low"] if loc_m <= 1 else cfg["loc_context_by_meaning"]["high"] if loc_m >= 3 else cfg["loc_context_by_meaning"]["mid"]

    if is_invader:
        key = "low_meaning" if fac_m <= 1 else "mid_meaning" if fac_m == 2 else "high_meaning"
        return cfg["invader"][key].format(loc=loc_context)
    else:
        if fac_m <= 1:
            return cfg["endemic"]["low_meaning"].format(loc=loc_context)
        elif fac_m == 2:
            return cfg["endemic"]["mid_meaning"].format(loc=loc_context)
        else:
            if fac_o <= 1:
                return cfg["endemic"]["high_meaning_low_order"].format(loc=loc_context)
            elif loc_m >= 3:
                return cfg["endemic"]["high_meaning_high_loc_meaning"].format(loc=loc_context)
            return cfg["endemic"]["high_meaning_fallback"].format(loc=loc_context)


def get_top_vectors(profile: Profile, count: int = 3) -> str:
    ru_names = {
        "matter.density": "Масса", "matter.cohesion": "Связи", "matter.plasticity": "Пластичность",
        "info.order": "Логика", "info.meaning_density": "Смысл", "info.agency": "Воля",
        "energy.carrier": "Спектр", "energy.amplitude": "Мощность", "energy.charge": "Заряд",
        "spacetime.topology": "Топология", "spacetime.chronology": "Время", "spacetime.localization": "Мерность",
    }
    return ", ".join(f"{ru_names.get(k, k)} ({v:+.2f})" for k, v in profile.top_axes(count))


def get_hierarchy_status(role: str) -> str:
    return _T["roles"]["hierarchy_status"].get(role, _T["roles"]["hierarchy_status"]["fallback"])


def roll_eco_state() -> str:
    cfg = _T["eco_states"]
    return random.choices(cfg["options"], weights=cfg["weights"])[0]


# =========================================================
# Дипломатия
# =========================================================
def calculate_diplomacy(factions: List["Faction"]) -> None:
    cfg = _T["diplomacy"]
    for f1 in factions:
        f1.diplomacy_lines = []
        for f2 in factions:
            if f1 is f2:
                continue
            is_f1_dumb = f1.profile["info.agency"] < cfg["dumb_threshold"]
            is_f2_dumb = f2.profile["info.agency"] < cfg["dumb_threshold"]
            diff_order = abs(f1.profile["info.order"] - f2.profile["info.order"])

            if is_f1_dumb:
                d = cfg["dumb_relations"]
                rel = random.choices(d["options"], weights=d["weights"])[0]
                reason = d["reason"]
            elif is_f2_dumb:
                d = cfg["vs_dumb_relations"]
                rel = random.choices(d["options"], weights=d["weights"])[0]
                reason = d["reason"]
            else:
                d = cfg["smart_vs_smart"]
                rel_prefix = random.choices(d["prefixes"], weights=d["prefix_weights"])[0]
                if diff_order > cfg["order_diff_war_threshold"]:
                    status = d["status_by_order_diff"]["war"]
                elif diff_order > cfg["order_diff_feud_threshold"]:
                    status = d["status_by_order_diff"]["feud"]
                else:
                    status = random.choice(d["status_by_order_diff"]["mild"])

                if max(f1.profile["info.meaning_density"], f2.profile["info.meaning_density"]) > d["reason_meaning_threshold"]:
                    reason = d["reasons"]["ideology"]
                elif max(f1.profile["matter.density"], f2.profile["matter.density"]) > d["reason_density_threshold"]:
                    reason = d["reasons"]["space"]
                else:
                    reason = d["reasons"]["resources"]

                rel = f"{rel_prefix} {status}"

            f1.diplomacy_lines.append(f"  └ К [{f2.name}]: {rel} из-за {reason}.")


# =========================================================
# Классы
# =========================================================
class Mob:
    def __init__(self, role: str, faction_profile: Profile, era: Era):
        self.role_base = role
        self.profile = mutate_mob(faction_profile, role)
        self.primary_domain = get_primary_domains(self.profile)
        self.display_name = names.generate_mob_title(self.profile, role)
        self.paradigm, self.magic_lvl, self.tech_lvl = roll_being_paradigm(era)
        self.mastery = self.magic_lvl if self.paradigm == "Магия" else (self.tech_lvl if self.paradigm == "Технология" else round((self.magic_lvl + self.tech_lvl) / 2))

    def render(self) -> str:
        flesh = get_flesh(self.profile)
        size = get_size(self.profile["matter.density"])
        quantity = get_quantity(self.profile["matter.cohesion"])
        mind, emotion = get_emotions_and_mind(self.profile["info.agency"], self.profile["info.order"], self.profile["info.meaning_density"])
        tactics = get_tactics(emotion, self.profile["info.agency"], self.profile["info.order"])
        status = get_hierarchy_status(self.role_base)
        br = sum(abs(v) for v in self.profile.values()) / 12 * 100

        return (f" ❖ [{self.display_name}] (База: {self.role_base}) | БР: {br:.0f} | Домен: {self.primary_domain} "
                f"| {self.paradigm} (мастерство {self.mastery})\n"
                f"   ├ Статус:  {status}\n"
                f"   ├ Габарит: {size} | Количество: {quantity}\n"
                f"   ├ Характер: {emotion}\n"
                f"   ├ Тактика:  {tactics}\n"
                f"   └ Тело:     {flesh}\n")


class Faction:
    def __init__(self, loc_profile: Profile, eco_state: str, era: Era):
        opts = _T["eco_states"]["options"]
        if eco_state == opts[0]:
            is_invader = False
        elif eco_state == opts[1]:
            is_invader = True
        else:
            is_invader = random.random() > 0.5

        self.profile, self.origin = generate_faction_profile(loc_profile, is_invader)
        self.primary_domain = get_primary_domains(self.profile)
        self.name = generate_faction_name(self.profile)
        self.is_invader = is_invader
        self.diplomacy_lines: List[str] = []
        self.paradigm, self.magic_lvl, self.tech_lvl = roll_being_paradigm(era)

        roles = list(_T["roles"]["base_roles"])
        if random.random() < _T["roles"]["deity_chance"]:
            roles.append(_T["roles"]["deity_role"])
        lo, hi = _T["roles"]["roles_per_faction"]["min"], _T["roles"]["roles_per_faction"]["max"]
        selected_roles = random.sample(roles, random.randint(lo, min(hi, len(roles))))
        if "Рядовой/Пехота" not in selected_roles:
            selected_roles[0] = "Рядовой/Пехота"
        self.mobs = [Mob(role, self.profile, era) for role in selected_roles]

    def render(self, loc_profile: Profile) -> str:
        flesh = get_flesh(self.profile)
        mind, emotion = get_emotions_and_mind(self.profile["info.agency"], self.profile["info.order"], self.profile["info.meaning_density"])
        hierarchy = get_faction_hierarchy(self.profile["info.agency"], self.profile["info.order"])
        goal = get_faction_goal(self.profile, loc_profile, self.is_invader)
        top_vectors = get_top_vectors(self.profile)

        lines = [
            f"╔{'═'*78}╗",
            f"║ ФРАКЦИЯ: {self.name:<68} ║",
            f"╠{'═'*78}╣",
            f"  Происхождение: {self.origin}",
            f"  Домен Силы:    {self.primary_domain}. Топ-векторы: {top_vectors}",
            f"  Парадигма:     {self.paradigm} (магия {self.magic_lvl} / технологии {self.tech_lvl})",
            f"  Физиология:    {flesh}",
            f"  Разум:         {mind}. Эмоции: {emotion}",
            f"  Иерархия:      {hierarchy}",
            f"  Цель:          {goal}",
            f"  Дипломатия:",
        ]
        lines.extend(self.diplomacy_lines)
        lines.append(f"╚{'═'*78}╝\n")
        lines.append("--- БЕСТИАРИЙ ---")
        for mob in self.mobs:
            lines.append(mob.render())
        return "\n".join(lines)


if __name__ == "__main__":
    from generators.location_gen import generate_location_profile

    era = Era.roll()
    loc_profile = generate_location_profile()
    eco_state = roll_eco_state()

    print(f">>> ЭПОХА МИРА: {era.name} (уровень {era.level}, {era.paradigm})")
    print(f">>> ЭКОСИСТЕМА: {eco_state}\n")

    factions = [Faction(loc_profile, eco_state, era) for _ in range(3)]
    calculate_diplomacy(factions)
    for f in factions:
        print(f.render(loc_profile))
