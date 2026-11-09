import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from private_chef.seed import seed
from private_chef.store import Store
from private_chef.tools import Tools
from private_chef.validation import ChefError


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "chef.db")
        self.store.initialize()
        seed(self.store)
        self.one = Tools(self.store, "person-1")
        self.two = Tools(self.store, "person-2")

    def test_preferences_are_personal_persistent_and_editable(self):
        self.one.execute("set_preference", dict(kind="like", value="Mushrooms", remove=False))
        self.two.execute("set_preference", dict(kind="dislike", value="Mushrooms", remove=False))
        restarted = Store(self.store.path).household()["members"]
        self.assertEqual(restarted[0]["preferences"], [{"kind": "like", "value": "mushrooms"}])
        self.assertEqual(restarted[1]["preferences"][0]["kind"], "dislike")
        self.one.execute("set_preference", dict(kind="like", value="Mushrooms", remove=True))
        self.assertEqual(self.store.household()["members"][0]["preferences"], [])

    def test_model_cannot_impersonate_another_member(self):
        with self.assertRaises(ChefError):
            self.one.execute(
                "set_preference", dict(kind="like", value="x", remove=False, actor="person-2")
            )
        with self.assertRaises(ChefError):
            Tools(self.store, "intruder")

    def test_restrictions_apply_to_both_recommendation_and_selection(self):
        self.two.execute("set_preference", dict(kind="exclude", value="mushroom", remove=False))
        result = self.one.execute("recommend_recipes", {"count": 8})
        self.assertNotIn(3, [item["recipe"]["id"] for item in result["candidates"]])
        with self.assertRaises(ChefError):
            self.one.execute("select_recipe", dict(recipe_id=3, servings=2))
        self.two.execute("set_preference", dict(kind="diet", value="vegan", remove=False))
        result = self.one.execute("recommend_recipes", {"count": 8})
        self.assertTrue(all("vegan" in item["recipe"]["tags"] for item in result["candidates"]))

    def test_feedback_remains_separate_and_changes_rank(self):
        self.one.execute("record_feedback", dict(recipe_id=1, rating=5, comment="Loved it"))
        self.two.execute("record_feedback", dict(recipe_id=1, rating=1, comment="Too bland"))
        history = self.store.history()["feedback"]
        self.assertEqual({f["member_id"] for f in history}, {"person-1", "person-2"})
        self.assertNotEqual(self.one.recommend(1)["candidates"][0]["recipe"]["id"], 1)

    def test_shopping_scales_merges_and_rebuilds_without_duplicates(self):
        self.one.execute("select_recipe", dict(recipe_id=1, servings=4))
        self.two.execute("select_recipe", dict(recipe_id=2, servings=2))
        first = self.one.execute("build_shopping_list", {})
        chickpeas = next(item for item in first if item["name"] == "cooked chickpeas")
        self.assertEqual(chickpeas["quantity"], 800)
        oil = next(item for item in first if item["name"] == "olive oil")
        self.assertEqual(oil["quantity"], 45)
        self.two.execute("mark_shopping_item", dict(item_id=oil["id"], purchased=True))
        second = self.one.execute("build_shopping_list", {})
        self.assertEqual(len(first), len(second))
        self.assertTrue(next(item for item in second if item["id"] == oil["id"])["purchased"])
        self.assertEqual(next(item for item in second if item["id"] == oil["id"])["quantity"], 45)

    def test_cancellation_removes_only_that_meals_contribution(self):
        selected = self.one.execute("select_recipe", dict(recipe_id=1, servings=2))
        self.one.execute("build_shopping_list", {})
        self.one.execute("add_shopping_item", dict(name="Olive Oil", quantity=10, unit="ml"))
        self.two.execute(
            "set_meal_status", dict(selection_id=selected["selection_id"], status="cancelled")
        )
        self.assertEqual(len(self.store.shopping()), 1)
        self.assertEqual(self.store.shopping()[0]["quantity"], 10)

    def test_concurrent_manual_additions_are_not_lost(self):
        def add(_):
            self.store.add_shopping("tomatoes", 1, "piece")

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(add, range(20)))
        self.assertEqual(self.store.shopping()[0]["quantity"], 20)

    def test_incompatible_units_remain_separate(self):
        self.store.add_shopping("milk", 200, "ml")
        self.store.add_shopping("milk", 1, "bottle")
        self.assertEqual(len(self.store.shopping()), 2)

    def test_invalid_inputs_do_not_mutate_state(self):
        for quantity in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(quantity=quantity), self.assertRaises(ChefError):
                self.one.execute(
                    "add_shopping_item", dict(name="rice", quantity=quantity, unit="g")
                )
        with self.assertRaises(ChefError):
            self.one.execute("record_feedback", dict(recipe_id=999, rating=3, comment=""))
        self.assertEqual(self.store.shopping(), [])

    def test_request_deduplication_and_conflicts(self):
        self.assertIsNone(self.store.begin_request("r1", "person-1", "hello"))
        with self.assertRaises(ChefError):
            self.store.begin_request("r1", "person-1", "hello")
        self.store.finish_request("r1", "done")
        self.assertEqual(self.store.begin_request("r1", "person-1", "hello"), "done")
        with self.assertRaises(ChefError):
            self.store.begin_request("r1", "person-2", "hello")

    def test_seed_is_idempotent(self):
        self.assertEqual(seed(self.store), 0)
        self.assertEqual(len(self.store.recipes()), 6)

    def test_changed_taste_replaces_opposite_preference_but_preserves_exclusion(self):
        for kind in ("dislike", "exclude", "like"):
            self.one.execute("set_preference", dict(kind=kind, value="olives", remove=False))
        preferences = self.store.household()["members"][0]["preferences"]
        self.assertEqual({p["kind"] for p in preferences}, {"like", "exclude"})

    def test_additional_meal_reopens_bought_items_when_quantity_increases(self):
        self.store.select("person-1", 1, 2)
        oil = next(item for item in self.store.build_shopping() if item["name"] == "olive oil")
        self.store.mark_shopping(oil["id"], True)
        self.store.select("person-2", 2, 2)
        rebuilt = next(item for item in self.store.build_shopping() if item["id"] == oil["id"])
        self.assertFalse(rebuilt["purchased"])
        self.assertEqual(rebuilt["quantity"], 30)

    def test_removing_item_updates_shared_list(self):
        self.store.add_shopping("rice", 200, "g")
        item_id = self.store.shopping()[0]["id"]
        self.two.execute("remove_shopping_item", {"item_id": item_id})
        self.assertEqual(self.one.execute("get_shopping_list", {}), [])

    def test_preference_changes_revalidate_already_planned_meals_before_shopping(self):
        self.one.execute("select_recipe", dict(recipe_id=3, servings=2))
        # An old planned meal must still be checked after it drops out of recent history.
        for _ in range(51):
            self.store.select("person-1", 1, 2)
        self.two.execute("set_preference", dict(kind="diet", value="vegan", remove=False))
        with self.assertRaisesRegex(ChefError, "conflicts with current restrictions"):
            self.one.execute("build_shopping_list", {})
        self.assertEqual(self.store.shopping(), [])


if __name__ == "__main__":
    unittest.main()
