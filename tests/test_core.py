import unittest

from acc_marshal import core
from tests import helpers


class CoreTests(unittest.TestCase):
    def cars(self):
        return core.parse_session(core.loads_acc_json(helpers.session_bytes(helpers.quali_lines())))

    def test_parse_utf16(self):
        cars = self.cars()
        self.assertEqual([c["num"] for c in cars], [10, 11, 12, 13, 14])
        self.assertIsNone(cars[4]["best"])
        self.assertEqual(cars[0]["steams"], ["S10"])
        self.assertEqual(cars[0]["name"], "Ann A")

    def test_parse_bad_file(self):
        with self.assertRaises(ValueError):
            core.parse_session({"foo": 1})

    def test_roundtrip_bytes(self):
        obj = {"entries": [{"raceNumber": 5}], "forceEntryList": 1}
        self.assertEqual(core.loads_acc_json(core.dumps_acc_json(obj)), obj)

    def nums(self, grid):
        return [g["row"]["num"] for g in grid]

    def test_no_penalties(self):
        self.assertEqual(self.nums(core.compute_grid(self.cars(), {})), [10, 11, 12, 13, 14])

    def test_sequential_penalties(self):
        pen = {10: {"penalty": 2, "pit": False}, 11: {"penalty": 1, "pit": False}}
        g = core.compute_grid(self.cars(), pen)
        self.assertEqual(self.nums(g), [12, 11, 10, 13, 14])

    def test_single_penalty(self):
        g = core.compute_grid(self.cars(), {10: {"penalty": 2, "pit": False}})
        self.assertEqual(self.nums(g), [11, 12, 10, 13, 14])
        self.assertEqual(g[2]["delta"], 2)

    def test_penalty_beyond_end(self):
        g = core.compute_grid(self.cars(), {13: {"penalty": 9, "pit": False}})
        self.assertEqual(self.nums(g), [10, 11, 12, 14, 13])

    def test_pit_goes_last(self):
        g = core.compute_grid(self.cars(), {11: {"penalty": 0, "pit": True}})
        self.assertEqual(self.nums(g), [10, 12, 13, 14, 11])
        self.assertTrue(g[-1]["pit"])

    def test_reverse_top3(self):
        g = core.compute_grid(self.cars(), {}, reverse_n=3)
        self.assertEqual(self.nums(g), [12, 11, 10, 13, 14])

    def test_rule107(self):
        # 100000*1.07 = 107000; у машины 14 нет времени
        g = core.compute_grid(self.cars(), {}, rule107=True)
        self.assertEqual(self.nums(g)[-1], 14)
        self.assertTrue(g[-1]["rule107"])

    def test_pen_from_decisions(self):
        decs = [{"kind": "grid", "num": 10, "value": 2}, {"kind": "grid", "num": 10, "value": 1},
                {"kind": "pit", "num": 11}, {"kind": "tp5", "num": 12}]
        pen = core.grid_pen_from_decisions(decs)
        self.assertEqual(pen[10]["penalty"], 3)
        self.assertTrue(pen[11]["pit"])
        self.assertNotIn(12, pen)

    def test_entrylist_new(self):
        g = core.compute_grid(self.cars(), {10: {"penalty": 1, "pit": False}})
        obj, missing = core.build_entrylist(g)
        self.assertEqual(missing, 0)
        pos = {e["raceNumber"]: e["defaultGridPosition"] for e in obj["entries"]}
        self.assertEqual(pos[11], 1)
        self.assertEqual(pos[10], 2)
        self.assertEqual(obj["entries"][0]["drivers"][0]["playerID"][0], "S")

    def test_entrylist_match_by_steam_then_number(self):
        g = core.compute_grid(self.cars(), {10: {"penalty": 1, "pit": False}})
        existing = {"entries": [
            {"drivers": [{"playerID": "S10"}], "raceNumber": -1, "ballastKg": 10},
            {"drivers": [{"playerID": "S99"}], "raceNumber": 11},
            {"drivers": [{"playerID": "S77"}], "raceNumber": 77},
        ], "forceEntryList": 0}
        obj, missing = core.build_entrylist(g, existing)
        self.assertEqual(obj["entries"][0]["defaultGridPosition"], 2)
        self.assertEqual(obj["entries"][0]["ballastKg"], 10)
        self.assertEqual(obj["entries"][1]["defaultGridPosition"], 1)
        self.assertNotIn("defaultGridPosition", obj["entries"][2])
        self.assertEqual(missing, 1)
        self.assertNotIn("defaultGridPosition", existing["entries"][0])  # исходник не тронут

    def race(self):
        return core.parse_session(core.loads_acc_json(helpers.session_bytes(helpers.race_lines(), "R")))

    def test_classify_plain(self):
        rows = core.classify(self.race(), [])
        self.assertEqual([r["row"]["num"] for r in rows], [10, 11, 12, 13])

    def test_classify_time_penalty(self):
        decs = [{"kind": "post_time", "num": 10, "value": 6}]
        rows = core.classify(self.race(), decs)
        self.assertEqual([r["row"]["num"] for r in rows], [11, 10, 12, 13])
        self.assertEqual(rows[1]["penalty_s"], 6)
        self.assertEqual(rows[1]["total_final"], 3606000)
        self.assertEqual(rows[0]["delta"], 1)

    def test_classify_dsq_and_ingame_ignored(self):
        decs = [{"kind": "post_dsq", "num": 10}, {"kind": "tp5", "num": 11, "value": None}]
        rows = core.classify(self.race(), decs)
        self.assertEqual([r["row"]["num"] for r in rows], [11, 12, 13, 10])
        self.assertTrue(rows[-1]["dsq"])
        self.assertEqual(rows[0]["penalty_s"], 0)
        self.assertIn("DSQ", core.classification_text(rows))
        self.assertEqual(core.classification_rows_csv(rows)[-1][6], "да")

    def test_fmt(self):
        self.assertEqual(core.fmt_lap(107500), "1:47.500")
        self.assertEqual(core.fmt_total(3605000), "1:00:05.000")
        self.assertEqual(core.fmt_lap(None), "—")


if __name__ == "__main__":
    unittest.main()
