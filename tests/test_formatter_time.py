import unittest
from datetime import datetime, timezone

from config import DISPLAY_TZ, format_local_datetime
from formatter import _format_list_time


class FormatterTimeTests(unittest.TestCase):
    def test_unix_utc_to_minsk(self):
        # 01.06.2026 07:50 UTC = 10:50 в Минске (UTC+3)
        ts = datetime(2026, 6, 1, 7, 50, tzinfo=timezone.utc).timestamp()
        self.assertEqual(_format_list_time(ts), "01.06.2026 10:50")
        self.assertEqual(format_local_datetime(ts), "01.06.2026 10:50")

    def test_iso_z_to_minsk(self):
        self.assertEqual(
            _format_list_time("2026-06-01T07:50:00Z"),
            "01.06.2026 10:50",
        )

    def test_millis(self):
        ts = datetime(2026, 6, 1, 7, 50, tzinfo=timezone.utc).timestamp() * 1000
        self.assertEqual(_format_list_time(ts), "01.06.2026 10:50")

    def test_display_tz_is_minsk(self):
        self.assertEqual(str(DISPLAY_TZ), "Europe/Minsk")


if __name__ == "__main__":
    unittest.main()
