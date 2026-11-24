from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path


DEFAULT_CSV_PATH = Path(r"C:\Users\Surface\Downloads\Third Street Market Products - Sheet1.csv")

AVATAR_REWARDS = [
    "Retro Purdue Cap",
    "Classic Striped Tee",
    "Campus Sneakers",
    "Blue Hoodie",
    "Varsity Jacket",
    "Purdue Hoodie",
    "Engineering sunglasses",
    "Gold Crewneck Sweatshirt",
    "Boiler Beanie",
    "Black Cargo Pants",
    "Library Tote Bag",
    "White Canvas Shoes",
    "Gold Track Jacket",
    "Lab Coat & Goggles",
    "Striped Rugby Shirt",
    "Vintage Windbreaker",
    "Campus Backpack",
    "Golden Train Pin",
    "Athletic Shorts",
    "Flannel Overshirt",
    "Purdue Bucket Hat",
    "Slim Chino Trousers",
    "Sporty Wristbands",
    "Collegiate Scarf",
    "Corduroy Cap",
    "Mesh Running Shoes",
    "Data Nerd Glasses",
    "Puffer Vest",
    "Campus Quarter-Zip",
    "Champion Gold Hoodie",
]

ALLERGEN_ALIASES = {
    "dairy": {"dairy", "milk", "cheese", "butter", "cream", "whey", "lactose"},
    "milk": {"dairy", "milk", "cheese", "butter", "cream", "whey", "lactose"},
    "peanut": {"peanut", "peanuts"},
    "peanuts": {"peanut", "peanuts"},
}

NON_HEALTHY_ITEMS = {
    "nestle morsels",
    "hunts sp pudding vani",
    "stir fry korean bbq",
    "velveeta cheesy bowl",
    "mac and cheese",
    "yakisoba",
    "annie chun noodle bowl",
    "buldak spicy ramen",
    "sweet banana chip",
    "blue bunny ice cream",
    "pronax tray",
    "blount meals",
    "prairie farm 1/2 gal chocolate",
}


def resolve_menu_csv(docs_dir: Path, explicit_csv: str | None) -> Path:
    """Resolve the dataset CSV path from CLI arg, default Downloads path, or docs/."""
    if explicit_csv:
        custom_path = Path(explicit_csv)
        if not custom_path.exists():
            raise FileNotFoundError(f"Specified CSV file was not found: '{custom_path}'.")
        return custom_path

    if DEFAULT_CSV_PATH.exists():
        return DEFAULT_CSV_PATH

    if docs_dir.exists():
        csv_files = sorted(docs_dir.glob("*.csv"))
        if csv_files:
            return csv_files[0]

    raise FileNotFoundError(
        f"Could not find dataset at '{DEFAULT_CSV_PATH}' or any .csv file inside '{docs_dir}'."
    )


def pick_column(fieldnames: list[str], candidates: list[str]) -> str | None:
    """Find a matching column name case-insensitively."""
    lower_map = {name.strip().lower(): name for name in fieldnames}
    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    return None


def expand_allergens(raw_items: list[str]) -> set[str]:
    """Normalize allergen strings and include common aliases."""
    expanded = set()
    for item in raw_items:
        key = item.strip().lower()
        if not key:
            continue
        expanded.add(key)
        expanded.update(ALLERGEN_ALIASES.get(key, set()))
    return expanded


def load_menu(csv_path: Path) -> list[dict]:
    """Load menu items from a CSV file and normalize fields."""
    items = []
    with open(csv_path, mode="r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return items

        col_id = pick_column(reader.fieldnames, ["id", "item_id", "code", "sku"])
        col_name = pick_column(
            reader.fieldnames, ["name", "item", "item_name", "food", "product", "title"]
        )
        col_price = pick_column(reader.fieldnames, ["price", "cost", "amount", "unit_price"])
        col_allergens = pick_column(
            reader.fieldnames, ["allergens", "allergen", "allergy", "allergies"]
        )

        for idx, row in enumerate(reader, start=1):
            raw_name = (row.get(col_name) or "").strip() if col_name else f"Item {idx}"
            if not raw_name:
                continue

            item_id = (row.get(col_id) or "").strip() if col_id else f"ITEM_{idx}"

            raw_price = (row.get(col_price) or "0").strip().replace("$", "")
            try:
                price = float(raw_price)
            except ValueError:
                price = 0.0

            raw_allergens = (row.get(col_allergens) or "") if col_allergens else ""
            raw_parts = [
                a.strip().lower()
                for a in raw_allergens.replace(";", ",").split(",")
                if a.strip() and a.strip().lower() not in {"none", "n/a", "-", "no"}
            ]
            allergens = expand_allergens(raw_parts)

            items.append({
                "id": item_id,
                "name": raw_name,
                "price": price,
                "allergens": allergens,
            })
    return items


def calculate_weekly_budget(dollars: float, weeks: int) -> float:
    """Calculate the average weekly Dining Dollars budget."""
    if weeks <= 0:
        raise ValueError("--weeks must be greater than 0.")
    if dollars <= 0:
        return 0.0
    return round(dollars / weeks, 2)


def filter_allergens(items: list[dict], allergies: list[str]) -> list[dict]:
    """Exclude menu items that contain any of the user's allergens."""
    blocked = expand_allergens(allergies)
    if not blocked:
        return list(items)
    return [item for item in items if item["allergens"].isdisjoint(blocked)]


def classify_health(item: dict) -> dict:
    """Classify an item as healthy or non-healthy (Cheat Day candidate)."""
    name_lower = item["name"].strip().lower()
    is_healthy = name_lower not in NON_HEALTHY_ITEMS

    updated = dict(item)
    updated["is_healthy"] = is_healthy
    return updated


def split_healthy_and_cheat_items(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split safe items into Healthy recommendations and Non-Healthy Cheat Day options."""
    tagged = [classify_health(x) for x in items]
    healthy_items = [x for x in tagged if x["is_healthy"]]
    cheat_day_items = [x for x in tagged if not x["is_healthy"]]
    return healthy_items, cheat_day_items


def filter_variety(items: list[dict], recent_ids: list[str]) -> list[dict]:
    """Avoid repeating items from recent history (up to 2 weeks)."""
    recent_set = set(recent_ids)
    filtered = [item for item in items if item["id"] not in recent_set]
    return filtered if filtered else list(items)


def select_items_within_budget(candidates: list[dict], budget: float) -> tuple[list[dict], float]:
    """Select items whose cumulative price fits within the given budget."""
    if budget <= 0:
        return [], 0.0

    selected: list[dict] = []
    spent = 0.0
    for item in candidates:
        price = item["price"]
        if price < 0:
            continue
        if round(spent + price, 2) <= round(budget, 2):
            selected.append(item)
            spent = round(spent + price, 2)
    return selected, spent


def load_state(state_path: Path) -> dict:
    """Load persisted user points, unlocked items, and recent week history."""
    if state_path.exists():
        with open(state_path, mode="r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "points": 0,
        "unlocked_items": [],
        "recent_weeks_ids": [],
    }


def save_state(state_path: Path, state: dict) -> None:
    """Save updated application state to disk."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, mode="w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Dining Dollars Health Optimizer")
    parser.add_argument("--dollars", type=float, required=True, help="Current Dining Dollars")
    parser.add_argument("--weeks", type=int, required=True, help="Remaining weeks in semester")
    parser.add_argument(
        "--allergies",
        type=str,
        default="",
        help="Comma-separated allergies, e.g. peanuts,dairy",
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Optional override path to the dataset CSV file",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Skip interactive Cheat Day prompt (useful for quick testing)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent
    docs_dir = base_dir / "docs"
    state_path = base_dir / "data" / "state.json"

    csv_path = resolve_menu_csv(docs_dir, args.csv)
    menu = load_menu(csv_path)
    state = load_state(state_path)

    weekly_budget = calculate_weekly_budget(args.dollars, args.weeks)
    budget_for_period = args.dollars if args.weeks == 1 else weekly_budget
    allergy_list = [a.strip() for a in args.allergies.split(",") if a.strip()]

    recent_2_weeks_ids = [
        item_id for week_ids in state["recent_weeks_ids"][-2:] for item_id in week_ids
    ]

    safe_items = filter_allergens(menu, allergy_list)
    healthy_pool, cheat_day_pool = split_healthy_and_cheat_items(safe_items)

    recommended = filter_variety(healthy_pool, recent_2_weeks_ids)
    top_picks, total_spent = select_items_within_budget(recommended, budget_for_period)
    remaining_budget = round(budget_for_period - total_spent, 2)
    avg_rec_price = (
        sum(x["price"] for x in top_picks) / len(top_picks) if top_picks else budget_for_period
    )

    print("\n=== DINING DOLLARS HEALTH OPTIMIZER ===")
    print(f"Dataset:          {csv_path} ({len(menu)} items)")
    print(f"Dining Dollars:   ${args.dollars:.2f} | Remaining Weeks: {args.weeks}")
    print(f"Weekly Budget:    ${weekly_budget:.2f}")
    print(
        f"Period Budget:    ${budget_for_period:.2f} | Selected Total: ${total_spent:.2f} | Left: ${remaining_budget:.2f}"
    )
    print(f"Allergies:        {', '.join(allergy_list) if allergy_list else 'None'}")
    print(f"\n--- Recommended Healthy Items ({len(top_picks)} items within budget) ---")
    if not top_picks:
        print("  No healthy items fit within the current budget.")
    for i, item in enumerate(top_picks, start=1):
        print(f"  {i}. [{item['id']}] {item['name']} - ${item['price']:.2f} (HEALTHY)")

    current_week_ids = [x["id"] for x in top_picks]
    state["recent_weeks_ids"] = (state["recent_weeks_ids"] + [current_week_ids])[-2:]

    if not args.no_prompt:
        if not cheat_day_pool:
            print("\nNo allergy-safe Cheat Day items available for your current allergy filter.")
        else:
            choice = input("\nUse Cheat Day swap this week? (y/n): ").strip().lower()
            if choice == "y":
                print("\n--- Cheat Day List (Non-Healthy Treats) ---")
                for idx, item in enumerate(cheat_day_pool, start=1):
                    print(f"  {idx}. {item['name']} (${item['price']:.2f})")

                raw_pick = input("Pick item number to swap (or Enter to skip): ").strip()
                if raw_pick.isdigit():
                    pick_idx = int(raw_pick) - 1
                    if 0 <= pick_idx < len(cheat_day_pool):
                        swap_item = cheat_day_pool[pick_idx]
                        if swap_item["price"] <= avg_rec_price:
                            state["points"] += 1
                            print(
                                f"Swap accepted: {swap_item['name']} (${swap_item['price']:.2f} <= ${avg_rec_price:.2f}). +1 Point!"
                            )
                        else:
                            print(
                                f"Swap accepted: {swap_item['name']} (${swap_item['price']:.2f} > ${avg_rec_price:.2f}). +0 Point."
                            )

                        if state["points"] >= 4:
                            reward = random.choice(AVATAR_REWARDS)
                            state["unlocked_items"].append(reward)
                            state["points"] -= 4
                            print(f"4 Points reached! Unlocked avatar item: {reward}")

    save_state(state_path, state)
    print(f"\nCurrent Points: {state['points']} | Unlocked Avatar Items: {state['unlocked_items']}")


if __name__ == "__main__":
    main()