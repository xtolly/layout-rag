import unittest

from core.layout_optimizer import LayoutOptimizer


class LayoutOptimizerFallbackTemplateTests(unittest.TestCase):
    def test_use_other_templates_for_missing_part_type(self):
        optimizer = LayoutOptimizer()
        template_data = {
            "meta": {
                "panel_size": [400, 400],
                "parts": [
                    {"part_id": "tpl_a1", "part_type": "A", "part_size": [50, 50]},
                ],
            },
            "arrange": {
                "tpl_a1": {"position": [20, 20], "rotation": 0},
            },
        }
        fallback_templates = [
            {
                "uuid": "fallback-1",
                "meta": {
                    "panel_size": [400, 400],
                    "parts": [
                        {"part_id": "tpl_b1", "part_type": "B", "part_size": [40, 40]},
                    ],
                },
                "arrange": {
                    "tpl_b1": {"position": [180, 200], "rotation": 90},
                },
            }
        ]
        project_data = {
            "meta": {
                "panel_size": [400, 400],
                "parts": [
                    {"part_id": "prj_a1", "part_type": "A", "part_size": [50, 50]},
                    {"part_id": "prj_b1", "part_type": "B", "part_size": [40, 40]},
                ],
            }
        }

        result = optimizer.apply_layout_template(
            template_data,
            project_data,
            fallback_templates=fallback_templates,
        )

        self.assertAlmostEqual(result["arrange"]["prj_a1"]["position"][0], 20.0)
        self.assertAlmostEqual(result["arrange"]["prj_a1"]["position"][1], 20.0)
        self.assertAlmostEqual(result["arrange"]["prj_b1"]["position"][0], 180.0)
        self.assertAlmostEqual(result["arrange"]["prj_b1"]["position"][1], 200.0)
        self.assertEqual(result["arrange"]["prj_b1"]["rotation"], 90)


if __name__ == "__main__":
    unittest.main()