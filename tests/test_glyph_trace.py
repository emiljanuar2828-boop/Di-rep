import io
import time
import unittest

import cv2
import numpy as np

import app as federwerk


class GlyphTraceTests(unittest.TestCase):
    def setUp(self):
        self.client = federwerk.app.test_client()
        self.token = "test-glyph-trace-session"
        self.sample = {"contours": [[[55, 0], [150, 600], [260, 0]]], "advance": 500}
        federwerk.SAMPLES[self.token] = {
            "created": time.monotonic(),
            "glyphs": {
                "A": {"char": "A", "sourceChar": "A", "variants": [self.sample, self.sample]},
            },
        }
        image = np.full((180, 180, 3), 255, dtype=np.uint8)
        cv2.line(image, (45, 150), (90, 30), (30, 30, 30), 8, cv2.LINE_AA)
        cv2.line(image, (90, 30), (140, 150), (30, 30, 30), 8, cv2.LINE_AA)
        cv2.line(image, (65, 105), (118, 105), (30, 30, 30), 8, cv2.LINE_AA)
        ok, encoded = cv2.imencode(".png", image)
        self.assertTrue(ok)
        self.image = encoded.tobytes()

    def tearDown(self):
        federwerk.SAMPLES.pop(self.token, None)

    def post_trace(self):
        return self.client.post(
            "/api/glyph/trace",
            data={
                "image": (io.BytesIO(self.image), "letter.png"),
                "id": self.token,
                "char": "A",
            },
            content_type="multipart/form-data",
        )

    def test_redraw_adds_third_variant_but_never_a_fourth(self):
        added = self.post_trace()
        self.assertEqual(added.status_code, 200, added.get_data(as_text=True))
        self.assertEqual(added.json["variantCount"], 3)
        self.assertEqual(len(federwerk.SAMPLES[self.token]["glyphs"]["A"]["variants"]), 3)

        rejected = self.post_trace()
        self.assertEqual(rejected.status_code, 422)
        self.assertIn("drei", rejected.json["error"])
        self.assertEqual(len(federwerk.SAMPLES[self.token]["glyphs"]["A"]["variants"]), 3)

    def test_expired_session_cannot_be_changed(self):
        federwerk.SAMPLES[self.token]["created"] = time.monotonic() - federwerk.SAMPLE_TTL - 1
        response = self.post_trace()
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json["error"], "Die Sitzung ist abgelaufen. Bitte scanne deine Vorlage erneut.")


if __name__ == "__main__":
    unittest.main()
