import unittest

from acc_marshal import commands


class CommandTests(unittest.TestCase):
    def test_build(self):
        self.assertEqual(commands.build_command("tp5", 12), "/tp5 12")
        self.assertEqual(commands.build_command("dt", 7), "/dt 7")
        self.assertIsNone(commands.build_command("grid", 12))
        self.assertIsNone(commands.build_command("tp5", None))

    def test_custom_template(self):
        self.assertEqual(commands.build_command("tp5", 3, {"tp5": "/penalty5 {num}"}), "/penalty5 3")

    def test_undo(self):
        self.assertEqual(commands.undo_command(5), "/clear 5")

    def test_describe(self):
        self.assertEqual(commands.describe_decision({"kind": "grid", "value": 3}), "−3 мест на решётке")
        self.assertEqual(commands.describe_decision({"kind": "post_time", "value": 10}), "+10 сек к итогам")
        self.assertEqual(commands.describe_decision({"kind": "tp5"}), "+5 сек")

    def test_render_missing_fields(self):
        out = commands.render("#{num} {name}: {reason}", num=5)
        self.assertEqual(out, "#5 :")
        self.assertEqual(commands.render("a {broken"), "a {broken")

    def test_translit(self):
        self.assertEqual(commands.translit("Штраф 5"), "Shtraf 5")
        self.assertEqual(commands.translit("/tp5 12"), "/tp5 12")

    def test_all_kinds_have_labels(self):
        self.assertEqual(len(commands.KIND_BY_LABEL), len(commands.KINDS))


if __name__ == "__main__":
    unittest.main()
