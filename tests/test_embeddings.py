import math
import unittest

from memory.embeddings import _tokenize, embed_text


class EmbeddingTests(unittest.TestCase):
    def test_tokenize_handles_mixed_case_and_symbols(self):
        self.assertEqual(_tokenize("Hello, WORLD! 123"), ["hello", "world", "123"])

    def test_embed_text_validates_dimensions(self):
        with self.assertRaises(ValueError):
            embed_text("hello", 0)

    def test_embed_text_normalizes_vectors(self):
        vector = embed_text("hello hello world", 8)
        magnitude = math.sqrt(sum(value * value for value in vector))
        self.assertAlmostEqual(magnitude, 1.0)

    def test_embed_text_handles_empty_input(self):
        self.assertEqual(embed_text("", 4), [0.0, 0.0, 0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
