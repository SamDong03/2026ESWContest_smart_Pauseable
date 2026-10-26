

import unittest

import numpy as np

from features import FEATURE_NAMES, extract_features, path_fingerprint


class GeometryFeaturesTest(unittest.TestCase):
    def setUp(self):
        self.path = np.asarray([
            [0.0, 0.0], [1.1, 0.2], [1.7, 1.3], [0.2, 1.5],
            [-0.4, 0.6], [0.6, 0.4], [1.3, 1.0],
        ])

    def test_output_contract(self):
        features = extract_features(self.path)
        self.assertEqual(features.shape, (len(FEATURE_NAMES),))
        self.assertEqual(len(set(FEATURE_NAMES)), len(FEATURE_NAMES))
        self.assertTrue(np.isfinite(features).all())

    def test_translation_scale_rotation_reflection(self):
        theta = np.deg2rad(37.0)
        rotation = np.asarray([[np.cos(theta), -np.sin(theta)],
                               [np.sin(theta), np.cos(theta)]])
        expected = extract_features(self.path)
        fingerprint = path_fingerprint(self.path)
        for transformed in (
            self.path + [123.0, -87.0],
            self.path * 0.001,
            self.path @ rotation,
            self.path * [-1.0, 1.0],
            (self.path @ rotation) * 17.0 + [-3.0, 40.0],
        ):
            with self.subTest(transformed=transformed):
                np.testing.assert_allclose(extract_features(transformed), expected,
                                           rtol=1e-9, atol=1e-9)
                self.assertEqual(path_fingerprint(transformed), fingerprint)

    def test_point_density_and_consecutive_duplicates(self):
        dense = []
        for start, end in zip(self.path[:-1], self.path[1:]):
            dense.extend(np.linspace(start, end, 11, endpoint=False))
        dense.append(self.path[-1])
        for equivalent in (np.asarray(dense), np.repeat(self.path, 3, axis=0)):
            np.testing.assert_allclose(extract_features(equivalent),
                                       extract_features(self.path), atol=1e-10)
            self.assertEqual(path_fingerprint(equivalent), path_fingerprint(self.path))

    def test_straight_loop_and_backtracking(self):
        straight = dict(zip(FEATURE_NAMES, extract_features([[0, 0], [1, 0], [2, 0]])))
        loop = dict(zip(FEATURE_NAMES, extract_features(
            [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]])))
        backtrack = dict(zip(FEATURE_NAMES, extract_features(
            [[0, 0], [1, 0], [2, 0], [1, 0], [0, 0]])))
        self.assertAlmostEqual(straight["path_length_over_diameter"], 1.0)
        self.assertAlmostEqual(straight["net_displacement_over_length"], 1.0)
        self.assertAlmostEqual(straight["total_absolute_turn_over_pi"], 0.0)
        self.assertAlmostEqual(straight["convex_hull_area_over_diameter_squared"], 0.0)
        self.assertAlmostEqual(loop["net_displacement_over_length"], 0.0)
        self.assertAlmostEqual(loop["total_absolute_turn_over_pi"], 2.0)
        self.assertGreater(loop["convex_hull_area_over_diameter_squared"], 0.4)
        self.assertGreater(loop["pca_minor_over_major_variance"], 0.8)
        self.assertAlmostEqual(backtrack["net_displacement_over_length"], 0.0)
        self.assertAlmostEqual(backtrack["convex_hull_area_over_diameter_squared"], 0.0)
        self.assertGreater(backtrack["turn_over_90deg_fraction"], 0.0)
        self.assertGreater(backtrack["nonlocal_revisit_fraction"],
                           straight["nonlocal_revisit_fraction"] + 0.5)

    def test_fingerprint_different_shape(self):
        straight = [[0, 0], [1, 0], [2, 0]]
        triangle = [[0, 0], [1, 1], [2, 0]]
        self.assertNotEqual(path_fingerprint(straight), path_fingerprint(triangle))

    def test_invalid_and_degenerate_paths(self):
        invalid = [
            [], [[0, 0]], [[0, 0], [1, 0]],
            [[0, 0], [1, 0], [0, 0]],
            [[1, 1], [1, 1], [1, 1]],
            [[0, 0], [1, np.nan], [2, 0]],
            [[0, 0], [1, np.inf], [2, 0]],
            [[0, 0, 0], [1, 1, 1], [2, 2, 2]],
            [[0, 0], [1, 1], [2, 1j]],
        ]
        for path in invalid:
            for function in (extract_features, path_fingerprint):
                with self.subTest(path=path, function=function.__name__):
                    with self.assertRaises(ValueError):
                        function(path)


if __name__ == "__main__":
    unittest.main()
