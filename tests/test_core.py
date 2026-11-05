"""The change test, config loading, the matrix, and the CLI's wiring."""

import argparse
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from product_view import config, matrix as mx
from product_view.cli import build_parser
from product_view.matching.run import open_embedder, open_llm
from product_view.periods import Period, Series

ROOT = Path(__file__).resolve().parents[1]
END = datetime(2026, 9, 23, tzinfo=timezone.utc)


def series(*counts: int) -> Series:
    """A series with `counts[k]` reviews in period k (0 = this period)."""
    s = Series(Period(END, 28, 3))
    for k, n in enumerate(counts):
        for i in range(n):
            s.add(END - timedelta(days=28 * k + 1), f"r{k}-{i}")
    return s


class ChangeTest(unittest.TestCase):
    def test_quiet_new_steady(self):
        self.assertEqual(series(0, 0, 0, 0).change, "quiet")
        self.assertEqual(series(3, 0, 0, 0).change, "new")
        self.assertEqual(series(2, 0, 0, 0).change, "steady")   # under MIN_CHANGE
        self.assertEqual(series(5, 4, 5, 6).change, "steady")

    def test_up_and_down(self):
        self.assertEqual(series(15, 3, 4, 3).change, "up")
        self.assertEqual(series(0, 9, 10, 11).change, "down")

    def test_buckets(self):
        p = Period(END, 28, 3)
        self.assertEqual(p.bucket(END - timedelta(days=1)), 0)
        self.assertEqual(p.bucket(END - timedelta(days=29)), 1)
        self.assertIsNone(p.bucket(END))
        self.assertIsNone(p.bucket(END - timedelta(days=28 * p.n_buckets + 1)))
        self.assertEqual(series(1, 2, 3).usual, (2 + 3 + 0) / 3)


class ConfigTest(unittest.TestCase):
    def test_unknown_key_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.yaml"
            path.write_text("report:\n  period_dayz: 7\n", encoding="utf-8")
            with self.assertRaises(config.ConfigError):
                config.load(path)

    def test_flag_beats_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.yaml"
            path.write_text("report:\n  period_days: 7\n", encoding="utf-8")
            cfg = config.load(path)
        args = argparse.Namespace(period_days=None, baseline_periods=5)
        config.apply(args, cfg)
        self.assertEqual((args.period_days, args.baseline_periods), (7, 5))


class MatrixTest(unittest.TestCase):
    def test_sample_loads(self):
        m = mx.load(ROOT / "matrix.sample.yaml")
        self.assertTrue(m.is_sample)
        self.assertTrue(m.topics and m.teams)
        owned = {t for team in m.teams.values() for mem in team.members for t in mem.topics}
        self.assertEqual(owned, set(m.topics))

    def test_problems_are_listed(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "matrix.yaml"
            path.write_text("topics:\n  Bad_Id: {name: X}\nteams: {}\n", encoding="utf-8")
            with self.assertRaises(mx.MatrixError) as err:
                mx.load(path)
        self.assertIn("lowercase", str(err.exception))
        self.assertIn("description", str(err.exception))


class WiringTest(unittest.TestCase):
    def test_every_command_parses(self):
        parser = build_parser()
        for argv in (["fetch"], ["export"], ["info"], ["langs"], ["db", "build"],
                     ["translate"], ["match"], ["matrix"], ["check-matching"], ["report"],
                     ["cycle"], ["publish", "page.html"]):
            self.assertTrue(callable(parser.parse_args(argv).func), argv)

    def test_models_open(self):
        """Opening the model clients touches config, .env and cache.db, but no server."""
        with tempfile.TemporaryDirectory() as d:
            args = argparse.Namespace(config=config.load(None), data_dir=d)
            llm, emb = open_llm(args), open_embedder(args)
            self.assertTrue(llm.describe() and emb.describe())
            llm.close()
            emb.close()


if __name__ == "__main__":
    unittest.main()
