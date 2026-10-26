

import unittest

import numpy as np

from scenarios import (
    FAMILY_LABELS,
    LABELLED_FAMILIES,
    generate_ambiguous,
    generate_split,
)


class ScenarioContractTest(unittest.TestCase):
    def test_deterministic_independent_groups_and_finite_points(self):
        first = generate_split("train", 4, 4101)
        again = generate_split("train", 4, 4101)
        self.assertEqual(len(first), 40)
        self.assertEqual(len({s.group_id for s in first}), len(first))
        for a, b in zip(first, again):
            self.assertEqual(a.path_id, b.path_id)
            self.assertEqual(a.metadata, b.metadata)
            np.testing.assert_array_equal(a.points, b.points)
            self.assertEqual(a.points.shape[1], 2)
            self.assertTrue(96 <= len(a.points) <= 220)
            self.assertTrue(np.isfinite(a.points).all())
            self.assertGreater(np.ptp(a.points, axis=0).max(), 0)
            self.assertEqual(a.label, FAMILY_LABELS[a.family])
            self.assertEqual(a.metadata["label_scope"], "entire_trajectory")
            self.assertIsNone(a.metadata["clinical_label"])

    def test_different_splits_and_seeds_change_base_geometry(self):
        train = generate_split("train", 2, 4101)
        test = generate_split("test", 2, 4101)
        reseeded = generate_split("train", 2, 4102)
        self.assertTrue({s.group_id for s in train}.isdisjoint(s.group_id for s in test))
        for a, b, c in zip(train, test, reseeded):
            self.assertNotEqual(a.metadata["geometry_seed"], b.metadata["geometry_seed"])
            self.assertNotEqual(a.metadata["geometry_seed"], c.metadata["geometry_seed"])

    def test_nuisance_distribution_is_exactly_balanced_across_families(self):
        cases = generate_split("train", 12, 4101)
        for index in range(12):
            rows = [s for s in cases if s.metadata["index"] == index]
            self.assertEqual(len(rows), len(LABELLED_FAMILIES))
            self.assertEqual(sum(s.label for s in rows), len(rows) // 2)
            for row in rows[1:]:
                self.assertEqual(rows[0].metadata["nuisance"], row.metadata["nuisance"])

    def test_preregistered_route_semantics(self):
        for split in ("train", "challenge"):
            for row in generate_split(split, 10, 4500):
                construction = row.metadata["construction"]
                self.assertEqual(row.metadata["challenge_construction"], split == "challenge")
                if row.family in {"bent_transit", "corridor_detour", "meandering_transit"}:
                    self.assertTrue(construction["forward_axis_monotonic"])
                    self.assertEqual(row.label, 0)
                elif row.family == "single_return":
                    self.assertEqual(construction["outward_traversals"], 1)
                    self.assertEqual(construction["return_traversals"], 1)
                    self.assertTrue(0 < construction["returned_fraction"] < 1)
                    self.assertEqual(row.label, 0)
                elif row.family == "open_arc":
                    self.assertLess(construction["sweep_radians"], 2 * np.pi)
                    self.assertEqual(row.label, 0)
                elif row.family == "repeated_shuttle":
                    self.assertGreaterEqual(construction["route_traversals"], 4)
                    self.assertEqual(row.label, 1)
                elif row.family == "repeat_figure8":
                    self.assertGreaterEqual(construction["complete_figure8_traversals"], 2)
                    self.assertEqual(row.label, 1)
                else:
                    self.assertGreaterEqual(construction["complete_circuits"], 2)
                    self.assertEqual(row.label, 1)

    def test_ambiguous_probes_have_no_truth_labels_and_context_pair_is_identical(self):
        cases = generate_ambiguous(4201)
        self.assertEqual(len(cases), 35)
        self.assertTrue(all(s.label is None for s in cases))
        pairs = [s for s in cases if s.family == "same_geometry_different_intent"]
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[0].group_id, pairs[1].group_id)
        np.testing.assert_array_equal(pairs[0].points, pairs[1].points)
        self.assertNotEqual(pairs[0].metadata["parameters"], pairs[1].metadata["parameters"])
        weak = [s for s in cases if s.family == "prior_weak_loop"]
        u = np.linspace(0, 1, 300)
        t = 3 * np.pi * u
        np.testing.assert_allclose(weak[-1].points[:, 0], 2 * np.cos(t) + 2 * u)
        np.testing.assert_allclose(weak[-1].points[:, 1], 2 * np.sin(t))

    def test_invalid_configuration_rejected(self):
        for bad in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                generate_split("train", bad, 4101)
        with self.assertRaises(ValueError):
            generate_split("", 1, 4101)
        with self.assertRaises(ValueError):
            generate_split("train", 1, -1)


if __name__ == "__main__":
    unittest.main()
