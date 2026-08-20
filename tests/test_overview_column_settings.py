from __future__ import annotations

import json
import unittest

from ozon_app.overview_column_settings import (
    ColumnPreference,
    default_column_preferences,
    normalize_column_preferences,
    serialize_column_preferences,
    visible_column_ids,
)
from ozon_app.ui import OVERVIEW_COLUMN_SPECS, SCENARIO_COLUMN_SPECS


class OverviewColumnSettingsTests(unittest.TestCase):
    def test_invalid_setting_restores_all_default_columns(self) -> None:
        preferences = normalize_column_preferences("not-json")

        self.assertEqual(preferences, default_column_preferences())
        self.assertEqual(
            visible_column_ids(preferences),
            tuple(column_id for column_id, _heading, _width in OVERVIEW_COLUMN_SPECS),
        )

    def test_saved_order_and_visibility_are_preserved_and_new_columns_are_added(self) -> None:
        raw = json.dumps(
            {
                "version": 1,
                "columns": [
                    {"id": "revenue", "visible": True},
                    {"id": "article", "visible": False},
                    {"id": "unknown", "visible": True},
                    {"id": "revenue", "visible": False},
                ],
            }
        )

        preferences = normalize_column_preferences(raw)

        self.assertEqual(preferences[0], ColumnPreference("revenue", True))
        self.assertEqual(preferences[1], ColumnPreference("article", False))
        self.assertEqual(preferences[-1].column_id, "net_margin")
        self.assertNotIn("unknown", [item.column_id for item in preferences])
        self.assertEqual(len(preferences), len(OVERVIEW_COLUMN_SPECS))

    def test_serialization_round_trip_keeps_user_choice(self) -> None:
        preferences = default_column_preferences()
        moved = preferences.pop(-1)
        preferences.insert(0, moved)
        preferences[1] = ColumnPreference(preferences[1].column_id, False)

        restored = normalize_column_preferences(serialize_column_preferences(preferences))

        self.assertEqual(restored, preferences)

    def test_all_hidden_corrupt_setting_falls_back_to_safe_default(self) -> None:
        raw = [
            {"id": column_id, "visible": False}
            for column_id, _heading, _width in OVERVIEW_COLUMN_SPECS
        ]

        self.assertEqual(normalize_column_preferences(raw), default_column_preferences())

    def test_scenario_preferences_have_independent_order_and_visibility(self) -> None:
        preferences = default_column_preferences(SCENARIO_COLUMN_SPECS)
        moved = preferences.pop(-1)
        preferences.insert(0, moved)
        preferences[1] = ColumnPreference(preferences[1].column_id, False)

        restored = normalize_column_preferences(
            serialize_column_preferences(preferences, SCENARIO_COLUMN_SPECS),
            SCENARIO_COLUMN_SPECS,
        )

        self.assertEqual(restored, preferences)
        self.assertEqual(restored[0].column_id, "net_total")
        self.assertEqual(len(restored), len(SCENARIO_COLUMN_SPECS))
        self.assertNotEqual(
            [item.column_id for item in restored],
            [item.column_id for item in default_column_preferences()],
        )


if __name__ == "__main__":
    unittest.main()
