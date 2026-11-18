"""The current Negativa abstract must not be shadowed by its first edition."""
import json
import re
import unittest
from pathlib import Path
import build_site_metadata as metadata

ROOT = Path(__file__).resolve().parents[1]


class CurrentNegativa(unittest.TestCase):
    def test_current_abstract_and_status(self):
        source = (ROOT / 'papers/sae-negativa.html').read_text()
        item = next(x for x in metadata.load_catalogue() if x['href'] == 'papers/sae-negativa.html')
        article = next(json.loads(x) for x in re.findall(r'<script type="application/ld\+json">(.*?)</script>', source, re.S) if json.loads(x).get('@type') == 'ScholarlyArticle')
        self.assertEqual(article['abstract'], metadata.extract_abstract(source))
        self.assertTrue(article['abstract'].startswith('This paper registers the sole axiom'))
        self.assertIn('Everything else is a postulate or theorem within its series.', article['abstract'])
        self.assertNotIn('Original abstract:', article['abstract'])
        self.assertEqual(article['creativeWorkStatus'], item['status'])
        self.assertEqual(item['status'], 'current revised edition')
        self.assertEqual(article['version'], '2')
        self.assertEqual(source.count('<h2>Abstract</h2>'), 1)
        self.assertEqual(source.count('<h2>摘要</h2>'), 1)
        self.assertIn('The sole axiom of SAE, across all its series:', source)
        self.assertIn('SAE 唯一公理：非。其余皆各系列内之公设与定理。', source)
        self.assertIn('19544620', source)  # First-edition record remains in the comparison.
        self.assertIn('与第一版及《第一批判》的关系', source)


if __name__ == '__main__':
    unittest.main()
