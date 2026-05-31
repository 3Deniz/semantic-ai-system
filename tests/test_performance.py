"""Performance smoke tests for ingestion and recall paths."""

import time
import tracemalloc
import unittest

from core.data_loader import DataLoader
from core.knowledge_graph import KnowledgeGraph
from core.tms import LiteTMS


class _LargeFakePDFExtractor:
    def __init__(self, page_count: int = 120):
        self.page_count = page_count

    def extract_pages_from_bytes(self, _payload: bytes):
        return [
            {"page_index": i, "text": "Rain causes flood. Flood causes damage."}
            for i in range(self.page_count)
        ]


class TestPerformanceSmoke(unittest.TestCase):
    def setUp(self):
        self.loader = DataLoader(tms=LiteTMS(), kg=KnowledgeGraph())
        self.loader.pdf_ingestion = _LargeFakePDFExtractor(page_count=120)

    def test_large_pdf_ingestion_smoke(self):
        tracemalloc.start()
        start = time.perf_counter()

        result = self.loader.ingest_pdf_document(
            b"large-fake-pdf",
            source_document="perf.pdf",
            stage="candidate",
        )

        elapsed = time.perf_counter() - start
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        self.assertEqual(result["pages"], 120)
        self.assertGreater(result["candidates"], 0)
        # Smoke thresholds: conservative to avoid flaky CI.
        self.assertLess(elapsed, 10.0)
        self.assertLess(peak, 150 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
