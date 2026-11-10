"""Small set of original starter recipes; nothing downloaded or attributed falsely."""

from .store import Store


def seed(store: Store) -> int:
    recipes = [
        (
            "Tomato and chickpea stew",
            ["vegan", "vegetarian", "dairy-free", "gluten-free", "nut-free"],
            [
                ("cooked chickpeas", 400, "g"),
                ("chopped tomatoes", 400, "g"),
                ("onion", 1, "piece"),
                ("olive oil", 15, "ml"),
                ("ground cumin", 2, "g"),
            ],
            [
                "Dice the onion. Heat oil in a saucepan and soften the onion for 5 minutes.",
                "Stir in cumin for 30 seconds. Add tomatoes and drained chickpeas.",
                "Simmer for 15 minutes, stirring occasionally. Season to taste and serve hot.",
            ],
        ),
        (
            "Lemon lentil rice",
            ["vegan", "vegetarian", "dairy-free", "gluten-free", "nut-free"],
            [
                ("rice", 150, "g"),
                ("cooked lentils", 250, "g"),
                ("lemon", 1, "piece"),
                ("spinach", 150, "g"),
                ("olive oil", 15, "ml"),
            ],
            [
                "Cook the rice following its package instructions.",
                "Heat oil in a pan, add drained lentils and spinach, and stir until "
                "hot and wilted.",
                "Fold in the rice and lemon juice. Season to taste.",
            ],
        ),
        (
            "Mushroom pasta",
            ["vegetarian", "nut-free", "italian"],
            [
                ("pasta", 180, "g"),
                ("mushrooms", 250, "g"),
                ("cream", 100, "ml"),
                ("garlic", 2, "clove"),
                ("olive oil", 15, "ml"),
            ],
            [
                "Boil pasta following package instructions, reserving a little cooking water.",
                "Slice mushrooms and mince garlic. Fry mushrooms in oil for 8 "
                "minutes; add garlic for 1 minute.",
                "Stir in cream and simmer for 2 minutes. Toss with pasta, loosening "
                "with cooking water.",
            ],
        ),
        (
            "Roasted vegetable couscous",
            ["vegan", "vegetarian", "dairy-free", "nut-free"],
            [
                ("couscous", 150, "g"),
                ("courgette", 1, "piece"),
                ("bell pepper", 1, "piece"),
                ("cooked chickpeas", 200, "g"),
                ("olive oil", 20, "ml"),
            ],
            [
                "Heat oven to 200 C. Chop vegetables and drain chickpeas.",
                "Toss vegetables and chickpeas with oil and roast on a tray for 25 "
                "minutes, turning halfway.",
                "Prepare couscous with boiling water according to its package. Fluff "
                "and combine with vegetables.",
            ],
        ),
        (
            "Potato and spinach frittata",
            ["vegetarian", "gluten-free", "nut-free"],
            [
                ("potatoes", 300, "g"),
                ("eggs", 4, "piece"),
                ("spinach", 100, "g"),
                ("milk", 50, "ml"),
                ("olive oil", 15, "ml"),
            ],
            [
                "Dice potatoes into small pieces and simmer in water until tender, "
                "about 10 minutes. Drain.",
                "Heat oil in a non-stick frying pan, add potatoes and spinach, and "
                "cook until spinach wilts.",
                "Beat eggs with milk and seasoning. Pour into the pan, cover, and "
                "cook on low heat until "
                "the egg is set throughout, about 10–15 minutes. Do not serve with "
                "liquid egg remaining.",
            ],
        ),
        (
            "Ginger tofu rice bowl",
            ["vegan", "vegetarian", "dairy-free", "nut-free"],
            [
                ("firm tofu", 300, "g"),
                ("rice", 150, "g"),
                ("broccoli", 250, "g"),
                ("soy sauce", 20, "ml"),
                ("ginger", 10, "g"),
                ("vegetable oil", 15, "ml"),
            ],
            [
                "Cook rice according to its package. Drain and cube tofu; grate ginger.",
                "Fry tofu in oil until golden, turning carefully. Add broccoli "
                "florets and a splash of water.",
                "Cover and cook until broccoli is tender. Add ginger and soy sauce, "
                "heat through, and serve on rice.",
            ],
        ),
    ]
    existing = {recipe["title"] for recipe in store.recipes()}
    count = 0
    for title, tags, ingredients, instructions in recipes:
        if title not in existing:
            store.save_recipe(
                title=title,
                servings=2,
                ingredients=[dict(name=n, quantity=q, unit=u) for n, q, u in ingredients],
                instructions=instructions,
                tags=tags,
                source_url="",
            )
            count += 1
    return count
