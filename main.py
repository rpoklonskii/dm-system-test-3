"""
Точка входа. Ничего не генерирует "напрямую" — только раскладывает шаги:

  1. Роллит ОДНУ общую Era на весь мир (core/world.py).
  2. Генерирует локацию (generators/location_gen.py): профиль + карты этажей.
  3. Генерирует фракции внутри локации (generators/faction_gen.py): эндемики
     наследуют профиль локации, захватчики — нет, но обе группы роллят
     paradigm/magic_lvl/tech_lvl от той же самой Era, поэтому мир "сцеплен",
     но каждый бросок всё равно случаен.
  4. Для элитных мобов/боссов генерирует навыки (generators/skill_gen.py).
  5. Печатает отчёт и умеет сохранить/загрузить весь сгенерированный мир
     в saves/*.json (профили — это плоские dict, поэтому сериализация
     тривиальна через Profile.to_dict()/from_dict()).

Запуск:  python3 main.py
"""

import argparse
import json
import os
import random
from datetime import datetime, timezone

from core import Era, Profile
from core.world import era_paradigm_to_being
from generators import location_gen, faction_gen, skill_gen

SAVES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saves")

SKILL_ELIGIBLE_ROLES = {"Лидер/Элита", "Божество/Аномалия", "Симбионт/Инструмент"}


def generate_world(location_name: str = "Зараженный Исследовательский Бункер", num_factions: int = 3):
    era = Era.roll()

    location = location_gen.Location(
        name=location_name,
        profile=location_gen.generate_location_profile(),
        paradigm=era_paradigm_to_being(era.paradigm),
    )
    location_report = location.render()  # заодно заполняет location.sub_locations

    eco_state = faction_gen.roll_eco_state()
    factions = [faction_gen.Faction(location.profile, eco_state, era) for _ in range(num_factions)]
    faction_gen.calculate_diplomacy(factions)

    # Навыки — только для мобов с ролью, подразумевающей осознанное применение силы.
    skill_reports = []
    for f in factions:
        for mob in f.mobs:
            if mob.role_base in SKILL_ELIGIBLE_ROLES:
                caster = skill_gen.make_caster(mob.display_name, mob.profile, era, mob.paradigm, mob.mastery)
                skill_gen.generate_skills_for(caster)
                skill_reports.append((f.name, caster))

    return {
        "era": era,
        "location": location,
        "location_report": location_report,
        "eco_state": eco_state,
        "factions": factions,
        "skill_reports": skill_reports,
    }


def render_world(world: dict) -> str:
    era = world["era"]
    lines = []
    lines.append("#" * 80)
    lines.append(f" ЭПОХА МИРА: [{era.level}] {era.name}  (парадигма: {era.paradigm})")
    lines.append("#" * 80 + "\n")

    lines.append(world["location_report"])

    lines.append(f">>> ЭКОСИСТЕМА ЛОКАЦИИ: {world['eco_state']}\n")
    for f in world["factions"]:
        lines.append(f.render(world["location"].profile))

    if world["skill_reports"]:
        lines.append("#" * 80)
        lines.append(" НАВЫКИ КЛЮЧЕВЫХ СУЩЕСТВ")
        lines.append("#" * 80 + "\n")
        for faction_name, caster in world["skill_reports"]:
            lines.append(f"=== {caster.name} (фракция: {faction_name}) ===")
            lines.append(f"Парадигма: {caster.paradigm} (мастерство {caster.mastery}) | "
                         f"Ресурс: {caster.mana_pool} маны | Аффинность: {caster.affinity} | КПД: {caster.efficiency:.2f}")
            for s in caster.skills:
                lines.append(s.render())
            lines.append("")

    return "\n".join(lines)


# =========================================================
# Сохранение / загрузка (демонстрация персистентности профилей)
# =========================================================
def save_world(world: dict, path: str) -> None:
    data = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "era": {"level": world["era"].level, "paradigm": world["era"].paradigm, "name": world["era"].name},
        "location": {
            "name": world["location"].name,
            "profile": world["location"].profile.to_dict(),
        },
        "eco_state": world["eco_state"],
        "factions": [
            {
                "name": f.name,
                "is_invader": f.is_invader,
                "paradigm": f.paradigm,
                "profile": f.profile.to_dict(),
                "mobs": [
                    {
                        "name": m.display_name,
                        "role": m.role_base,
                        "profile": m.profile.to_dict(),
                        "paradigm": m.paradigm,
                        "mastery": m.mastery,
                    }
                    for m in f.mobs
                ],
            }
            for f in world["factions"]
        ],
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def load_world_raw(path: str) -> dict:
    """Загружает сырые данные сохранённого мира (без пересборки карт/навыков —
    это снимок профилей на момент сохранения, полезно для сверки/аналитики)."""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main():
    parser = argparse.ArgumentParser(description="Генератор связанного мира: локация + фракции + навыки")
    parser.add_argument("--seed", type=int, default=None, help="Фиксировать random seed для повторяемости")
    parser.add_argument("--location-name", type=str, default="Зараженный Исследовательский Бункер")
    parser.add_argument("--factions", type=int, default=3)
    parser.add_argument("--save", type=str, default=None, help="Сохранить сгенерированный мир в saves/<имя>.json")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    world = generate_world(location_name=args.location_name, num_factions=args.factions)
    print(render_world(world))

    if args.save:
        save_path = args.save if os.path.isabs(args.save) else os.path.join(SAVES_DIR, args.save)
        save_world(world, save_path)
        print(f"\n>>> Мир сохранён: {save_path}")


if __name__ == "__main__":
    main()
