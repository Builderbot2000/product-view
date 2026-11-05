"""The page tree, built from a small made-up matching run on the sample matrix."""

import contextlib
import io
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from product_view import matrix as mx
from product_view.matching.store import TopicStore
from product_view.report import data
from product_view.report.build import pages, write
from product_view.store import Store

ROOT = Path(__file__).resolve().parents[1]
END = datetime(2026, 9, 23, tzinfo=timezone.utc)   # the day after the newest review
DAYS, BASELINE = 28, 3


class ReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        cls.matrix = mx.load(ROOT / "matrix.sample.yaml")
        cls.spiked, cls.steady = list(cls.matrix.topics)[:2]

        # Two reviews a period on each of two topics, then a spike on one this
        # period; one review a period on no topic.
        reviews, units, matches = [], [], []

        def review(k: int, i: int, topic: str | None) -> None:
            rid = f"p{k}-{topic or 'none'}-{i}"
            created = END - timedelta(days=DAYS * k + 1, hours=i)
            reviews.append({"review_id": rid, "app_id": "app", "content":
                            f"Complaint {rid} about the app, long enough to keep.",
                            "score": 1, "thumbs_up": i, "created_at": created.isoformat(),
                            "app_version": "4.66"})
            units.append((rid, 0, "sure" if topic else "misc", topic or cls.steady, 0.9,
                          "the complaint", f"quote for {rid}"))
            if topic:
                matches.append((rid, 0, topic, "sure"))

        for k in range(12):
            for i in range(12 if (k == 0) else 2):
                review(k, i, cls.spiked)
            for i in range(2):
                review(k, i, cls.steady)
            review(k, 0, None)

        cls.store = Store(d / "reviews.db")
        cls.store.upsert_reviews(reviews)
        with TopicStore(d / "topics.db") as ts:
            ts.start("run1", matrix="sample", topic_hash=cls.matrix.topic_hash,
                     window_start=(END - timedelta(days=DAYS * 12)).isoformat(),
                     window_end=END.isoformat(), reviews=len(reviews))
            ts.finish("run1", units, matches, units=len(units))
        cls.report = data.load(cls.store, d / "topics.db", cls.matrix, DAYS, BASELINE)
        cls.specs = pages(cls.store, cls.report, "Overview", "app")

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        cls.tmp.cleanup()

    def test_counts(self):
        r = self.report
        self.assertEqual(r.topics[self.spiked].now, 12)
        self.assertEqual(r.topics[self.spiked].change, "up")
        self.assertEqual(r.topics[self.steady].change, "steady")
        self.assertEqual(r.no_topic.now, 1)
        self.assertEqual(r.total.now, 15)

    def test_tree(self):
        teams = self.matrix.teams.values()
        self.assertEqual(len(self.specs),
                         1 + len(teams) + sum(len(t.members) for t in teams))
        titles = {s.title for s in self.specs}
        self.assertEqual(len(titles), len(self.specs))           # unique per space
        self.assertIsNone(self.specs[0].parent)
        for s in self.specs[1:]:
            self.assertIn(s.parent, titles)

    def test_overview_names_the_spike(self):
        body = self.specs[0].page.body
        name = self.matrix.topics[self.spiked].name.replace("&", "&amp;")
        self.assertIn(name, body)
        self.assertIn("↑ UP", body)
        self.assertIn("Did not fit a topic: 1 review", body)

    def test_write(self):
        with tempfile.TemporaryDirectory() as d:
            with contextlib.redirect_stdout(io.StringIO()):
                write(self.specs, Path(d))
            for s in self.specs:
                folder = Path(d) / s.key
                self.assertTrue((folder / "page.storage.xhtml").read_text(encoding="utf-8"))
                self.assertEqual(len(list(folder.glob("*.svg"))), len(s.page.attachments))


if __name__ == "__main__":
    unittest.main()
