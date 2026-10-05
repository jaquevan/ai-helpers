import importlib.util
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
VISUAL_ANALYZER = SKILL_DIR / "scripts" / "visual_analyze.py"
SPEC = importlib.util.spec_from_file_location("consistency_visual_analyze", VISUAL_ANALYZER)
VISUAL_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VISUAL_MODULE)


class ProjectFeltVisualTests(unittest.TestCase):
    def test_pill_controls_and_red_primary_accent_pass(self):
        report = VISUAL_MODULE.analyze_project_felt_dom({
            "root_classes": ["pf-v6-theme-felt"],
            "controls": [
                {
                    "tag_name": "button",
                    "classes": ["pf-v6-c-button", "pf-m-primary"],
                    "height": 40,
                    "border_top_left_radius": "999px",
                    "border_top_right_radius": "999px",
                    "background_color": "rgb(238, 0, 0)",
                },
                {
                    "tag_name": "button",
                    "classes": [],
                    "height": 40,
                    "border_top_left_radius": "20px",
                    "border_top_right_radius": "20px",
                    "background_color": "rgb(255, 255, 255)",
                },
            ],
        })
        self.assertEqual(report["status"], "passed")
        self.assertTrue(all(check["passed"] for check in report["checks"].values()))

    def test_square_form_fields_do_not_replace_button_shape_evidence(self):
        report = VISUAL_MODULE.analyze_project_felt_dom({
            "root_classes": ["pf-v6-theme-felt"],
            "controls": [
                {
                    "tag_name": "button",
                    "classes": ["pf-m-primary"],
                    "height": 40,
                    "border_top_left_radius": "999px",
                    "border_top_right_radius": "999px",
                    "background_color": "#ee0000",
                },
                {
                    "tag_name": "input",
                    "classes": [],
                    "height": 36,
                    "border_top_left_radius": "4px",
                    "border_top_right_radius": "4px",
                    "background_color": "rgb(255, 255, 255)",
                },
            ],
        })
        self.assertTrue(report["checks"]["pill_shaped_controls"]["passed"])

    def test_default_shape_or_blue_primary_fails(self):
        report = VISUAL_MODULE.analyze_project_felt_dom({
            "root_classes": ["pf-v6-theme-felt"],
            "controls": [{
                "classes": ["pf-m-primary"],
                "height": 40,
                "border_top_left_radius": "4px",
                "border_top_right_radius": "4px",
                "background_color": "rgb(0, 102, 204)",
            }],
        })
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["checks"]["pill_shaped_controls"]["passed"])
        self.assertFalse(report["checks"]["red_hat_red_primary_accent"]["passed"])

    def test_missing_controls_and_theme_are_not_silent_passes(self):
        report = VISUAL_MODULE.analyze_project_felt_dom({"root_classes": [], "controls": []})
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["checks"]["felt_root_class"]["passed"])
        self.assertFalse(report["checks"]["pill_shaped_controls"]["passed"])


if __name__ == "__main__":
    unittest.main()
