from __future__ import annotations

from pathlib import Path

from flask import Flask, render_template, request

from main import (
    calculate_weekly_budget,
    filter_allergens,
    load_menu,
    resolve_menu_csv,
    select_items_within_budget,
    split_healthy_and_cheat_items,
)

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DOCS_DIR = BASE_DIR / "docs"


def run_optimizer(dollars: float, weeks: int, allergies_raw: str) -> dict:
    """Compute healthy items within budget using existing logic from main.py."""
    csv_path = resolve_menu_csv(DOCS_DIR, None)
    menu = load_menu(csv_path)

    weekly_budget = calculate_weekly_budget(dollars, weeks)
    budget_for_period = dollars if weeks == 1 else weekly_budget

    allergy_list = [a.strip() for a in allergies_raw.split(",") if a.strip()]
    safe_items = filter_allergens(menu, allergy_list)
    healthy_pool, cheat_day_pool = split_healthy_and_cheat_items(safe_items)

    selected_items, total_spent = select_items_within_budget(healthy_pool, budget_for_period)
    remaining_budget = round(budget_for_period - total_spent, 2)

    return {
        "csv_name": csv_path.name,
        "total_menu_items": len(menu),
        "dollars": dollars,
        "weeks": weeks,
        "allergies": allergy_list,
        "weekly_budget": weekly_budget,
        "budget_for_period": budget_for_period,
        "total_spent": total_spent,
        "remaining_budget": remaining_budget,
        "items": selected_items,
        "cheat_day_count": len(cheat_day_pool),
    }


@app.route("/", methods=["GET", "POST"])
def index():
    form_values = {
        "dollars": "50",
        "weeks": "1",
        "allergies": "",
    }
    result = None
    error = None

    if request.method == "POST":
        form_values["dollars"] = (request.form.get("dollars") or "").strip()
        form_values["weeks"] = (request.form.get("weeks") or "").strip()
        form_values["allergies"] = (request.form.get("allergies") or "").strip()

        try:
            dollars = float(form_values["dollars"])
            weeks = int(form_values["weeks"])
            if dollars < 0:
                raise ValueError("Dining Dollars cannot be negative.")
            if weeks <= 0:
                raise ValueError("Remaining weeks must be greater than 0.")

            result = run_optimizer(dollars, weeks, form_values["allergies"])
        except ValueError as exc:
            error = str(exc)
        except FileNotFoundError as exc:
            error = str(exc)

    return render_template(
        "index.html",
        dollars=form_values["dollars"],
        weeks=form_values["weeks"],
        allergies=form_values["allergies"],
        result=result,
        error=error,
    )


if __name__ == "__main__":
    app.run(debug=True)
