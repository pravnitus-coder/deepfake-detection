"""API tests. Skipped automatically if fastapi/httpx are not installed."""
import hashlib, io, os, tempfile, unittest
import numpy as np
import soundfile as sf
try:
    from fastapi.testclient import TestClient
    HAVE = True
except Exception:
    HAVE = False
from PIL import Image
from app.services import upload_sessions


@unittest.skipUnless(HAVE, "fastapi + httpx not installed")
class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp()
        os.environ["SATYAM_DB_PATH"] = os.path.join(cls.temp_dir, "t.db")
        os.environ["SATYAM_UPLOAD_DIR"] = os.path.join(cls.temp_dir, "uploads")
        os.environ["SATYAM_UPLOAD_CHUNK_SIZE_BYTES"] = "65536"
        os.environ["SATYAM_UPLOAD_SIMULATION_ENABLED"] = "false"
        os.environ["SATYAM_HF_MODEL"] = ""
        os.environ["SATYAM_CORS_ORIGINS"] = "http://localhost:5173,null"
        from app.main import app
        cls.c = TestClient(app); cls.c.__enter__()
        response = cls.c.post("/api/auth/register", json={"username": "test-owner", "password": "test-password-123"})
        assert response.status_code == 201, response.text
        cls.owner_token = response.json()["access_token"]
        cls.c.headers.update({"Authorization": f"Bearer {cls.owner_token}"})
    def tearDown(self):
        try:
            self.c.headers.update({"Authorization": f"Bearer {self.owner_token}"})
            history = self.c.get("/api/analysis/history")
            if history.status_code == 200:
                for item in history.json():
                    self.c.delete(f"/api/analysis/{item['id']}")
        except Exception:
            pass
    def jpg(self):
        b = io.BytesIO(); Image.new("RGB", (32, 32), "red").save(b, "JPEG"); return b.getvalue()
    def wav(self):
        b = io.BytesIO(); sf.write(b, np.zeros(16000, dtype=np.float32), 16000, format="WAV"); return b.getvalue()
    def initiate(self, data=None, name="sample.jpg", kind="image", checksum=None, simulation=None):
        data = data if data is not None else self.jpg()
        return self.c.post("/api/uploads/initiate", json={
            "media_type": kind, "file_name": name, "file_size": len(data),
            "file_sha256": checksum or hashlib.sha256(data).hexdigest(),
            "mime_type": {"image": "image/jpeg", "audio": "audio/wav", "video": "video/mp4"}[kind],
            "simulation": simulation,
        })
    def put_chunks(self, session, data, indexes=None):
        chunk_size = session["chunk_size"]
        indexes = indexes or range(session["total_chunks"])
        for index in indexes:
            start = index * chunk_size
            chunk = data[start:start + chunk_size]
            response = self.c.put(
                f"/api/uploads/{session['upload_id']}/chunks/{index}",
                content=chunk,
                headers={
                    "Content-Range": f"bytes {start}-{start + len(chunk) - 1}/{len(data)}",
                    "X-Chunk-SHA256": hashlib.sha256(chunk).hexdigest(),
                    "Content-Type": "application/octet-stream",
                },
            )
            yield response
    def test_health_reports_unavailable_model(self):
        j = self.c.get("/api/health").json(); self.assertFalse(j["model"]["ready"]); self.assertEqual(j["modules"]["ai_model"], "unavailable")
    def test_file_origin_can_call_api(self):
        r = self.c.options("/api/health", headers={"Origin": "null", "Access-Control-Request-Method": "GET"})
        self.assertEqual(r.headers["access-control-allow-origin"], "null")
        put = self.c.options("/api/health", headers={"Origin": "null", "Access-Control-Request-Method": "PUT",
                                                     "Access-Control-Request-Headers": "authorization,content-range,x-chunk-sha256"})
        self.assertEqual(put.status_code, 200)
    def test_analysis_requires_authentication(self):
        self.c.headers.pop("Authorization")
        response = self.c.post("/api/analyze/image", files={"file": ("x.jpg", self.jpg(), "image/jpeg")})
        self.assertEqual(response.status_code, 401)
        self.c.headers.update({"Authorization": f"Bearer {self.owner_token}"})
    def test_image_flow_report_delete(self):
        r = self.c.post("/api/analyze/image", files={"file": ("x.jpg", self.jpg(), "image/jpeg")}); self.assertEqual(r.status_code, 200)
        j = r.json(); self.assertIsNone(j["fusion"]["calibrated_probability"]); self.assertEqual(len(j["file"]["sha256"]), 64)
        self.assertEqual(self.c.get(f"/api/analysis/{j['id']}").status_code, 200)
        self.assertIn("report_id", self.c.get(f"/api/analysis/{j['id']}/report").json())
        pdf = self.c.get(f"/api/analysis/{j['id']}/report.pdf")
        self.assertEqual(pdf.headers["content-type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertEqual(self.c.delete(f"/api/analysis/{j['id']}").status_code, 204)
        self.assertEqual(self.c.get(f"/api/analysis/{j['id']}").status_code, 404)
    def test_audio_returns_explicit_unavailable_model_and_history(self):
        r = self.c.post("/api/analyze/audio", files={"file": ("sample.wav", self.wav(), "audio/wav")})
        self.assertEqual(r.status_code, 200)
        result = r.json()
        self.assertEqual(result["kind"], "audio")
        self.assertEqual(result["modules"][0]["status"], "unavailable")
        self.assertIsNone(result["modules"][0]["score"])
        self.assertEqual(result["media_details"]["duration_s"], 1.0)
        self.assertIn(result["id"], [item["id"] for item in self.c.get("/api/analysis/history").json()])
        self.assertEqual(self.c.delete(f"/api/analysis/{result['id']}").status_code, 204)
    def test_rejects_exe_disguised_as_jpg(self):
        self.assertEqual(self.c.post("/api/analyze/image", files={"file": ("x.jpg", b"MZ" + b"0" * 50, "image/jpeg")}).status_code, 415)
    def test_rejects_truncated_image(self):
        self.assertEqual(self.c.post("/api/analyze/image", files={"file": ("x.jpg", self.jpg()[:60], "image/jpeg")}).status_code, 422)
    def test_rejects_empty(self):
        self.assertEqual(self.c.post("/api/analyze/image", files={"file": ("x.jpg", b"", "image/jpeg")}).status_code, 400)
    def test_chunked_upload_is_verified_and_analysis_is_idempotent(self):
        image = self.jpg()
        response = self.initiate(image)
        self.assertEqual(response.status_code, 201, response.text)
        session = response.json()
        self.assertEqual(session["total_chunks"], 1)
        chunk_response = next(self.put_chunks(session, image))
        self.assertEqual(chunk_response.status_code, 200, chunk_response.text)
        duplicate = next(self.put_chunks(session, image))
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertTrue(duplicate.json()["duplicate"])
        completed = self.c.post(f"/api/uploads/{session['upload_id']}/complete")
        self.assertEqual(completed.status_code, 200, completed.text)
        result = completed.json()["investigation"]
        self.assertEqual(result["file"]["sha256"], hashlib.sha256(image).hexdigest())
        repeated = self.c.post(f"/api/uploads/{session['upload_id']}/complete")
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json()["investigation"]["id"], result["id"])
        status = self.c.get(f"/api/uploads/{session['upload_id']}/status").json()
        self.assertEqual(status["status"], "complete")
        self.assertEqual(status["received_chunks"], [0])
        self.assertFalse(os.path.exists(os.path.join(os.environ["SATYAM_UPLOAD_DIR"], session["upload_id"])))
    def test_out_of_order_chunks_and_resume_keep_server_authority(self):
        rng = np.random.default_rng(17)
        image_buffer = io.BytesIO()
        Image.fromarray(rng.integers(0, 256, (512, 512, 3), dtype=np.uint8)).save(image_buffer, "JPEG", quality=98)
        image = image_buffer.getvalue()
        session = self.initiate(image).json()
        self.assertGreater(session["total_chunks"], 2)
        response = list(self.put_chunks(session, image, [1]))
        self.assertEqual(response[0].status_code, 200, response[0].text)
        status = self.c.post(f"/api/uploads/{session['upload_id']}/resume").json()
        self.assertEqual(status["received_chunks"], [1])
        self.assertEqual(status["missing_chunks"], [index for index in range(session["total_chunks"]) if index != 1])
        remaining = status["missing_chunks"]
        self.assertTrue(all(r.status_code == 200 for r in self.put_chunks(session, image, remaining)))
        result = self.c.post(f"/api/uploads/{session['upload_id']}/complete")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["investigation"]["file"]["sha256"], hashlib.sha256(image).hexdigest())
    def test_missing_chunks_and_corrupt_chunk_are_rejected(self):
        image = self.jpg()
        session = self.initiate(image).json()
        incomplete = self.c.post(f"/api/uploads/{session['upload_id']}/complete")
        self.assertEqual(incomplete.status_code, 409)
        chunk = image + b"x"
        response = self.c.put(f"/api/uploads/{session['upload_id']}/chunks/0", content=chunk, headers={
            "Content-Range": f"bytes 0-{len(chunk)-1}/{len(image)}",
            "X-Chunk-SHA256": hashlib.sha256(chunk).hexdigest(),
        })
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.c.get(f"/api/uploads/{session['upload_id']}/status").json()["received_chunks"], [])
    def test_final_checksum_mismatch_never_starts_analysis(self):
        image = self.jpg()
        session = self.initiate(image, checksum="0" * 64).json()
        self.assertTrue(all(response.status_code == 200 for response in self.put_chunks(session, image)))
        response = self.c.post(f"/api/uploads/{session['upload_id']}/complete")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.c.get(f"/api/uploads/{session['upload_id']}/status").json()["status"], "uploading")
        self.assertEqual(len(self.c.get("/api/analysis/history").json()), 0)
    def test_user_cannot_read_another_users_upload(self):
        session = self.initiate().json()
        second = self.c.post("/api/auth/register", json={"username": "second-user", "password": "second-password-123"})
        self.assertEqual(second.status_code, 201)
        self.c.headers.update({"Authorization": f"Bearer {second.json()['access_token']}"})
        self.assertEqual(self.c.get(f"/api/uploads/{session['upload_id']}/status").status_code, 404)
        self.c.headers.update({"Authorization": f"Bearer {self.owner_token}"})
        self.assertEqual(self.c.get(f"/api/uploads/{session['upload_id']}/status").status_code, 200)
    def test_invalid_type_and_cancellation_remove_chunks(self):
        response = self.initiate(b"not an image", name="invalid.jpg")
        self.assertEqual(response.status_code, 201)
        session = response.json()
        uploaded = self.c.put(f"/api/uploads/{session['upload_id']}/chunks/0", content=b"not an image", headers={
            "Content-Range": "bytes 0-11/12", "X-Chunk-SHA256": hashlib.sha256(b"not an image").hexdigest(),
        })
        self.assertEqual(uploaded.status_code, 200)
        complete = self.c.post(f"/api/uploads/{session['upload_id']}/complete")
        self.assertEqual(complete.status_code, 422)
        cancel_session = self.initiate().json()
        target = os.path.join(os.environ["SATYAM_UPLOAD_DIR"], cancel_session["upload_id"])
        self.assertTrue(os.path.isdir(target))
        self.assertEqual(self.c.delete(f"/api/uploads/{cancel_session['upload_id']}").status_code, 204)
        self.assertFalse(os.path.exists(target))
    def test_failure_simulation_injects_server_error_after_confirmed_threshold(self):
        previous = os.environ.get("SATYAM_UPLOAD_SIMULATION_ENABLED")
        os.environ["SATYAM_UPLOAD_SIMULATION_ENABLED"] = "true"
        try:
            rng = np.random.default_rng(23)
            output = io.BytesIO()
            Image.fromarray(rng.integers(0, 256, (300, 300, 3), dtype=np.uint8)).save(output, "JPEG", quality=98)
            image = output.getvalue()
            session_response = self.initiate(image, simulation={
                "fault": "http_503", "threshold_percent": 25, "recovery_seconds": 1,
            })
            self.assertEqual(session_response.status_code, 201, session_response.text)
            session = session_response.json()
            first = next(self.put_chunks(session, image, [0]))
            self.assertEqual(first.status_code, 200)
            trigger_index = session["total_chunks"] - 1
            response = next(self.put_chunks(session, image, [trigger_index]))
            self.assertEqual(response.status_code, 503)
            self.assertEqual(self.c.get(f"/api/uploads/{session['upload_id']}/status").json()["confirmed_bytes"],
                             len(image[:session["chunk_size"]]))
            self.c.delete(f"/api/uploads/{session['upload_id']}")
        finally:
            if previous is None:
                os.environ.pop("SATYAM_UPLOAD_SIMULATION_ENABLED", None)
            else:
                os.environ["SATYAM_UPLOAD_SIMULATION_ENABLED"] = previous
