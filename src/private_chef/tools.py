"""Bounded model tools. Identity comes from the caller, never from model arguments."""

from urllib.parse import urlsplit

from .store import Store, normalized
from .validation import ChefError, validate


def text(maximum=200, minimum=1):
    return {"type": "string", "minLength": minimum, "maxLength": maximum}


def integer(minimum=1, maximum=1000000):
    return {"type": "integer", "minimum": minimum, "maximum": maximum}


def choice(*values):
    return {"type": "string", "enum": list(values)}


def array(items, minimum=0, maximum=50):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


def obj(**properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


NUMBER = {"type": "number", "minimum": 0.001, "maximum": 100000}
INGREDIENT = obj(name=text(), quantity=NUMBER, unit=text(40))
DIETS = ("vegetarian", "vegan", "gluten-free", "dairy-free", "nut-free")
SCHEMAS = {
    "get_household": ("Read both people's preferences.", obj()),
    "set_preference": (
        "Add or remove a lasting preference for the current person only. "
        "exclude is an ingredient exclusion; diet requires a supported dietary tag. "
        "Temporary requests and one-off preparation feedback are not lasting preferences.",
        obj(
            kind=choice("like", "dislike", "exclude", "cuisine", "diet"),
            value=text(),
            remove={"type": "boolean"},
        ),
    ),
    "list_recipes": ("List saved recipes with IDs, ingredients and instructions.", obj()),
    "get_recipe": ("Read a saved recipe.", obj(recipe_id=integer())),
    "save_recipe": (
        "Save a complete recipe before recommending it. Use only justified dietary tags; "
        "source_url must be empty for an original/generated recipe. Ingredients use grams, "
        "millilitres or pieces where possible. Never invent a source URL.",
        obj(
            title=text(),
            servings=integer(1, 20),
            ingredients=array(INGREDIENT, 1),
            instructions=array(text(1500), 1, 30),
            tags=array(text(80), 0, 20),
            source_url=text(2000, 0),
        ),
    ),
    "recommend_recipes": (
        "Rank saved recipes for BOTH people, excluding recorded restrictions and accounting "
        "for separate ratings and recent meals. Recipes are not certified allergen-safe.",
        obj(count=integer(1, 8)),
    ),
    "record_feedback": (
        "Save the current person's 1–5 rating and comment on a saved recipe. "
        "Ask for a rating if one was not provided; do not invent the partner's feedback.",
        obj(recipe_id=integer(), rating=integer(1, 5), comment=text(2000, 0)),
    ),
    "get_history": ("Read selected meals, cooked meals, and each person's feedback.", obj()),
    "select_recipe": (
        "Add a meal to the household plan ONLY when the user chooses it. "
        "Use two servings unless the user asks otherwise. Does not yet change shopping.",
        obj(recipe_id=integer(), servings=integer(1, 20)),
    ),
    "set_meal_status": (
        "Mark a selected meal cooked or cancelled. Cancel removes its shopping contribution.",
        obj(selection_id=integer(), status=choice("cooked", "cancelled")),
    ),
    "build_shopping_list": (
        "Generate/update the shared shopping list from planned meals. Repeated calls do not "
        "duplicate quantities. Existing bought flags and manual additions are retained.",
        obj(),
    ),
    "get_shopping_list": ("Read the shared list, including bought flags and item IDs.", obj()),
    "add_shopping_item": (
        "Add an explicit extra item. Same name and unit merge; different units stay separate.",
        obj(name=text(), quantity=NUMBER, unit=text(40)),
    ),
    "mark_shopping_item": (
        "Mark a specific shared shopping item bought or unbought.",
        obj(item_id=integer(), purchased={"type": "boolean"}),
    ),
    "clear_shopping_list": (
        "Clear the entire list ONLY if the user explicitly requests clearing it. "
        "Planned meals remain and can be used to build another list.",
        obj(),
    ),
    "remove_shopping_item": (
        "Remove an item from the current shared list. Building the list again from planned "
        "meals can re-add it; explain this when relevant.",
        obj(item_id=integer()),
    ),
}


def definitions() -> list[dict]:
    return [
        {
            "type": "function",
            "name": name,
            "description": description,
            "parameters": schema,
            "strict": True,
        }
        for name, (description, schema) in SCHEMAS.items()
    ]


def blocked_reasons(recipe: dict, household: dict) -> list[str]:
    """Conservative text/tag checks, not a substitute for ingredient-label verification."""
    ingredients = " ".join(item["name"] for item in recipe["ingredients"])
    haystack = normalized(recipe["title"] + " " + ingredients + " " + " ".join(recipe["tags"]))
    reasons = []
    for member in household["members"]:
        for preference in member["preferences"]:
            kind, value = preference["kind"], preference["value"]
            if kind == "exclude" and value in haystack:
                reasons.append(f"Excluded ingredient for {member['name']}: {value}")
            if kind == "diet" and value not in recipe["tags"]:
                reasons.append(f"Missing {value} tag required by {member['name']}")
    return reasons


class Tools:
    def __init__(self, store: Store, actor: str):
        store.check_member(actor)
        self.store = store
        self.actor = actor

    def execute(self, name: str, arguments: dict) -> dict | list:
        if name not in SCHEMAS:
            raise ChefError("Unknown tool")
        validate(arguments, SCHEMAS[name][1])
        s = self.store
        match name:
            case "get_household":
                return s.household()
            case "set_preference":
                if arguments["kind"] == "diet" and normalized(arguments["value"]) not in DIETS:
                    raise ChefError(f"Supported diets: {', '.join(DIETS)}")
                return s.preference(self.actor, **arguments)
            case "list_recipes":
                return s.recipes()
            case "get_recipe":
                return s.recipe(**arguments)
            case "save_recipe":
                url = arguments["source_url"]
                if url and (
                    urlsplit(url).scheme not in {"http", "https"} or not urlsplit(url).netloc
                ):
                    raise ChefError("Recipe source must be an http(s) URL or empty")
                return s.save_recipe(**arguments)
            case "recommend_recipes":
                return self.recommend(arguments["count"])
            case "record_feedback":
                return s.feedback(self.actor, **arguments)
            case "get_history":
                return s.history()
            case "select_recipe":
                reasons = blocked_reasons(s.recipe(arguments["recipe_id"]), s.household())
                if reasons:
                    raise ChefError("Cannot select this recipe: " + "; ".join(reasons))
                return s.select(self.actor, **arguments)
            case "set_meal_status":
                return s.set_selection_status(**arguments)
            case "build_shopping_list":
                household = s.household()
                for meal in s.planned_meals():
                    reasons = blocked_reasons(s.recipe(meal["recipe_id"]), household)
                    if reasons:
                        raise ChefError(
                            f"Planned meal {meal['id']} conflicts with current restrictions. "
                            "Cancel it or choose a suitable replacement before building the list"
                        )
                return s.build_shopping()
            case "get_shopping_list":
                return s.shopping()
            case "add_shopping_item":
                return s.add_shopping(**arguments)
            case "mark_shopping_item":
                return s.mark_shopping(**arguments)
            case "clear_shopping_list":
                return s.clear_shopping()
            case "remove_shopping_item":
                return s.remove_shopping(**arguments)
        raise ChefError("Unknown tool")

    def recommend(self, count: int) -> dict:
        household, history = self.store.household(), self.store.history()
        ratings = self.store.rating_summary()
        candidates = []
        for recipe in self.store.recipes():
            if blocked_reasons(recipe, household):
                continue
            haystack = normalized(
                recipe["title"]
                + " "
                + " ".join(recipe["tags"])
                + " "
                + " ".join(item["name"] for item in recipe["ingredients"])
            )
            scores, reasons = [], []
            for member in household["members"]:
                score = 0.0
                for preference in member["preferences"]:
                    if preference["value"] in haystack:
                        if preference["kind"] in {"like", "cuisine"}:
                            score += 1
                            reasons.append(
                                f"Matches {member['name']}'s {preference['value']} preference"
                            )
                        elif preference["kind"] == "dislike":
                            score -= 2
                rating = ratings.get((member["id"], recipe["id"]))
                if rating is not None:
                    score += rating - 3
                    reasons.append(f"{member['name']}'s average rating: {rating:.1f}/5")
                scores.append(score)
            repeated = any(
                meal["recipe_id"] == recipe["id"] and meal["status"] != "cancelled"
                for meal in history["selections"][:7]
            )
            # Favour the less enthusiastic partner before using total enthusiasm to break ties.
            score = min(scores) * 2 + sum(scores) - (2 if repeated else 0)
            if repeated:
                reasons.append("Recently selected; reduced priority for variety")
            candidates.append({"recipe": recipe, "score": score, "reasons": reasons})
        candidates.sort(key=lambda item: (-item["score"], item["recipe"]["id"]))
        return {
            "candidates": candidates[:count],
            "eligible_count": len(candidates),
            "note": "Ingredient text/tag checks cannot certify allergen safety. "
            "Review labels and substitutions for allergies.",
        }
