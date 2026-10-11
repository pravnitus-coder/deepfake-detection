"""Tests for the Challenge Card 2 Feedback collection API."""
import os
import tempfile
import unittest
try:
    from fastapi.testclient import TestClient
    HAVE = True
except Exception:
    HAVE = False


@unittest.skipUnless(HAVE, "fastapi + httpx not installed")
class FeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp()
        os.environ["SATYAM_DB_PATH"] = os.path.join(cls.temp_dir, "fb_test.db")
        from app.main import app
        cls.client = TestClient(app)
        cls.client.__enter__()
        resp = cls.client.post("/api/auth/register", json={"username": "reviewer-1", "password": "password-123456"})
        assert resp.status_code == 201, resp.text
        cls.token = resp.json()["access_token"]
        cls.user_id = resp.json()["user_id"]

    def test_anonymous_feedback_submission(self):
        payload = {
            "name": "Alex",
            "role": "Researcher",
            "rating": 5,
            "worked_as_expected": "yes",
            "liked": "Explainable uncertainty reporting and clear distinction of unavailable models.",
            "confusing": "None.",
            "feature_to_improve": "Interactive audio spectrogram visualization.",
            "bugs": "No bugs found.",
            "suggestions": "Add batch checking in the future.",
            "consent_to_publish": True,
        }
        res = self.client.post("/api/feedback", json=payload)
        self.assertEqual(res.status_code, 201, res.text)
        data = res.json()
        self.assertIn("id", data)
        self.assertIn("recorded", data["message"])

    def test_authenticated_feedback_records_user_id(self):
        payload = {
            "name": "Dev User",
            "role": "Developer",
            "rating": 4,
            "worked_as_expected": "yes",
            "liked": "Clean architecture and modular detector adapters.",
            "consent_to_publish": False,
        }
        res = self.client.post(
            "/api/feedback",
            json=payload,
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(res.status_code, 201)

        # Retrieve feedback list
        list_res = self.client.get(
            "/api/feedback",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(list_res.status_code, 200)
        items = list_res.json()
        self.assertTrue(any(item["name"] == "Dev User" and item["user_id"] == self.user_id for item in items))

    def test_invalid_rating_bounds_rejected(self):
        res_zero = self.client.post("/api/feedback", json={"rating": 0})
        self.assertEqual(res_zero.status_code, 422)
        res_six = self.client.post("/api/feedback", json={"rating": 6})
        self.assertEqual(res_six.status_code, 422)

    def test_list_feedback_requires_authentication(self):
        res = self.client.get("/api/feedback")
        self.assertEqual(res.status_code, 401)
