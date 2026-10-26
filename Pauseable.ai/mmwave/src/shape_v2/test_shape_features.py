import unittest

import numpy as np

from legacy.features import extract_features as extract_legacy_features
from shape_features import FEATURE_NAMES, extract_features


class ShapeFeaturesTest(unittest.TestCase):
    def setUp(self):
        parameter = np.linspace(0.0, 1.0, 271)
        self.curve = np.column_stack([
            0.7 * parameter + np.cos(4.3 * np.pi * parameter),
            0.8 * np.sin(4.3 * np.pi * parameter),
        ])

    def test_legacy_prefix_exact_and_static_finite_contract(self):
        values = extract_features(self.curve)
        np.testing.assert_array_equal(values[:9], extract_legacy_features(self.curve))
        self.assertEqual(len(FEATURE_NAMES), 36)
        self.assertEqual(len(set(FEATURE_NAMES)), len(FEATURE_NAMES))
        self.assertEqual(values.shape, (len(FEATURE_NAMES),))
        self.assertTrue(np.isfinite(values).all())

    def test_rigid_transform_and_scale_invariance(self):
        values = extract_features(self.curve)
        angle = 0.791
        rotation = np.array([[np.cos(angle), -np.sin(angle)],
                             [np.sin(angle), np.cos(angle)]])
        transforms = [
            self.curve + np.array([3.7, -2.4]),
            self.curve @ rotation.T,
            self.curve * np.array([-1.0, 1.0]),
            self.curve * 0.0037,
            self.curve * 731.0,
            (self.curve @ rotation.T) * 2.5 + np.array([5.1, 0.8]),
        ]
        for transformed in transforms:
            with self.subTest(transformed=transformed[0]):
                np.testing.assert_allclose(extract_features(transformed), values,
                                           rtol=1e-8, atol=1e-8)

    def test_repetition_differs_from_straight(self):
        parameter = np.linspace(0.0, 1.0, 401)
        straight = np.column_stack([parameter, np.zeros_like(parameter)])
        repeated = np.column_stack([np.cos(6 * np.pi * parameter),
                                    np.sin(6 * np.pi * parameter)])
        straight_values = dict(zip(FEATURE_NAMES, extract_features(straight)))
        repeated_values = dict(zip(FEATURE_NAMES, extract_features(repeated)))
        self.assertEqual(straight_values["global_revisit_radius_100_fraction"], 0.0)
        self.assertGreater(repeated_values["global_revisit_radius_100_fraction"], 0.8)
        self.assertGreater(repeated_values["local_half_length_over_diameter_max"],
                           straight_values["local_half_length_over_diameter_max"])

    def test_collinear_reversals_and_reflection(self):
        backtracking = np.array([[0, 0], [1, 0], [2, 0], [1, 0],
                                 [0, 0], [1, 0], [2, 0]], dtype=float)
        values = extract_features(backtracking)
        self.assertTrue(np.isfinite(values).all())
        self.assertGreater(values[FEATURE_NAMES.index("global_opposite_nearby_fraction")], 0.2)
        np.testing.assert_allclose(extract_features(backtracking * [-1, 1]), values)

    def test_consecutive_duplicates_and_tiny_coordinate_scale(self):
        values = extract_features(self.curve)
        np.testing.assert_allclose(extract_features(np.repeat(self.curve, 3, axis=0)), values)
        np.testing.assert_allclose(extract_features(self.curve * 1e-180), values,
                                   atol=1e-8, rtol=1e-8)
        mostly_straight = [[0, 0], [1e-200, 0], [1e-150, 1e-150],
                          [0.5, 0], [1, 0], [1, 0]]
        self.assertTrue(np.isfinite(extract_features(mostly_straight)).all())

    def test_invalid_and_degenerate_rejected(self):
        bad_paths = [[], [[0, 0], [1, 1]], [[0, 0]] * 5,
                     [[0, 0], [1, 1], [0, 0]],
                     [[0, 0], [1, 1], [float("nan"), 2]],
                     [[0, 0], [1, 1], [float("inf"), 2]],
                     [[0, 0, 0], [1, 1, 1], [2, 2, 2]],
                     [[0, 0], [1, "bad"], [2, 2]],
                     [[0, 0], [1 + 2j, 1], [2, 2]]]
        for path in bad_paths:
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    extract_features(path)


if __name__ == "__main__":
    unittest.main()
