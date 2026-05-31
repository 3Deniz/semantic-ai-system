import unittest

from core.pdf_ingestion import PDFIngestion, PDFIngestionConfig, PDFIngestionError, normalize_pdf_text


class TestNormalizePdfText(unittest.TestCase):
    def test_removes_soft_hyphen(self):
        self.assertEqual(normalize_pdf_text("sema\u00adntic"), "semantic")

    def test_dehyphenates_line_wrap(self):
        self.assertEqual(normalize_pdf_text("seman-\ntic"), "semantic")

    def test_collapses_extra_spaces(self):
        self.assertEqual(normalize_pdf_text("a    b\t\t c"), "a b c")

    def test_keeps_paragraph_breaks(self):
        text = "A\n\n\n\nB"
        self.assertEqual(normalize_pdf_text(text), "A\n\nB")


class TestPdfIngestionValidation(unittest.TestCase):
    def test_empty_payload_raises(self):
        service = PDFIngestion()
        with self.assertRaises(PDFIngestionError):
            service.extract_pages_from_bytes(b"")

    def test_size_limit_raises(self):
        service = PDFIngestion(PDFIngestionConfig(max_file_size_bytes=4))
        with self.assertRaises(PDFIngestionError):
            service.extract_pages_from_bytes(b"12345")


if __name__ == "__main__":
    unittest.main()
