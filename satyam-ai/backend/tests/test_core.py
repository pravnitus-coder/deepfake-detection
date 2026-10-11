import os, tempfile, unittest
from dataclasses import replace
import io
import numpy as np, cv2
import soundfile as sf
from PIL import Image
from app.core.config import get_settings
from app.services import validation as v
from app.services.metadata_analysis import analyze_metadata
from app.services.image_analysis import visual_module, integrity_module
from app.services.evidence_fusion import fuse
from app.services.video_analysis import analyze_video, extract_video_audio, VideoError
from app.services.audio_analysis import analyze_audio
from app.models.model_registry import UnavailableDetector, Detector

S = get_settings()


def mod(id, status="completed", stance="inconclusive"):
    return {"id": id, "status": status, "stance": stance, "summary": "x"}


class FakeDetector(Detector):
    name, version = "test-double", "0"
    def __init__(self, flagged): self.flagged = flagged
    def status(self): return {"ready": True, "name": self.name, "version": self.version, "reason": None}
    def predict(self, image): return {"prediction": "artificial" if self.flagged else "human", "scores": {"artificial": .9, "human": .1}, "flagged": self.flagged}


class Validation(unittest.TestCase):
    def test_sniff(self):
        self.assertEqual(v.sniff(b"\xff\xd8\xff\xe0" + b"0" * 20), "image/jpeg")
        self.assertEqual(v.sniff(b"\x00\x00\x00\x18ftypmp42"), "video/mp4")
        self.assertIsNone(v.sniff(b"MZ\x90\x00" + b"0" * 20))
        self.assertEqual(v.sniff(b"RIFF" + b"\x00" * 4 + b"WAVE"), "audio/wav")
        self.assertEqual(v.sniff(b"fLaC" + b"\x00" * 20), "audio/flac")
        self.assertEqual(v.sniff(b"OggS" + b"\x00" * 20), "audio/ogg")
        self.assertEqual(v.sniff(b"\xff\xf1" + b"\x00" * 20), "audio/aac")
        self.assertEqual(v.sniff(b"\xff\xfb" + b"\x00" * 20), "audio/mpeg")
    def test_rejects_wrong_kind_empty_and_oversize(self):
        with self.assertRaises(v.ValidationError) as c: v.validate_upload("image", b"MZ" * 8, 100, S)
        self.assertEqual(c.exception.status, 415)
        with self.assertRaises(v.ValidationError) as c: v.validate_upload("image", b"", 0, S)
        self.assertEqual(c.exception.status, 400)
        with self.assertRaises(v.ValidationError) as c: v.validate_upload("image", b"\xff\xd8\xff" + b"0" * 20, 10**9, S)
        self.assertEqual(c.exception.status, 413)
        with self.assertRaises(v.ValidationError) as c: v.validate_upload("image", b"\xff\xd8\xff" + b"0" * 20, 100, S, "photo.exe")
        self.assertEqual(c.exception.status, 415)


class Modules(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.jpg = os.path.join(self.d, "a.jpg")
        Image.fromarray((np.random.rand(64, 64, 3) * 255).astype("uint8")).save(self.jpg, "JPEG")
    def test_missing_metadata_is_inconclusive_not_manipulation(self):
        m = analyze_metadata(self.jpg)
        self.assertEqual(m["stance"], "inconclusive")
        self.assertIn("not evidence of manipulation", m["summary"])
    def test_unavailable_model_has_no_score(self):
        m = visual_module(Image.open(self.jpg), UnavailableDetector("no model"))
        self.assertEqual(m["status"], "unavailable")
        self.assertIsNone(m["score"]); self.assertIsNone(m["observation"])
    def test_failed_model_has_no_score(self):
        class Boom(FakeDetector):
            def predict(self, image): raise RuntimeError("x")
        m = visual_module(Image.open(self.jpg), Boom(True))
        self.assertEqual(m["status"], "failed"); self.assertIsNone(m["score"])
    def test_integrity_only_jpeg(self):
        self.assertEqual(integrity_module(Image.open(self.jpg))["status"], "completed")
        png = os.path.join(self.d, "a.png"); Image.new("RGB", (8, 8)).save(png)
        self.assertEqual(integrity_module(Image.open(png))["status"], "unavailable")


class Fusion(unittest.TestCase):
    def test_nothing_available_is_undetermined(self):
        f = fuse([mod("ai_model", "unavailable", "could_not_check"), mod("metadata")])
        self.assertEqual((f["assessment"], f["risk_indicator"]), ("inconclusive", "UNDETERMINED"))
        self.assertIsNone(f["calibrated_probability"])
    def test_metadata_alone_never_clears(self):
        self.assertNotEqual(fuse([mod("metadata", stance="supports_authenticity")])["assessment"], "no_strong_evidence")
    def test_model_clears(self):
        self.assertEqual(fuse([mod("ai_model", stance="supports_authenticity")])["assessment"], "no_strong_evidence")
    def test_conflict_is_reported(self):
        f = fuse([mod("ai_model", stance="supports_manipulation"), mod("x", stance="supports_authenticity")])
        self.assertEqual(f["assessment"], "inconclusive"); self.assertTrue(f["conflicts"])
    def test_model_plus_metadata_high(self):
        f = fuse([mod("ai_model", stance="supports_manipulation"), mod("metadata", stance="supports_manipulation")])
        self.assertEqual(f["risk_indicator"], "HIGH")
    def test_unavailable_listed(self):
        self.assertEqual(fuse([mod("ai_model", "unavailable", "could_not_check")])["unavailable"][0]["id"], "ai_model")


class Video(unittest.TestCase):
    def make(self, secs=3):
        p = os.path.join(tempfile.mkdtemp(), "v.mp4")
        w = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
        for i in range(10 * secs): w.write(np.full((48, 64, 3), i % 255, np.uint8))
        w.release(); return p
    def test_frames_without_model_have_no_verdict(self):
        mod_, frames, errs, meta = analyze_video(self.make(), S, UnavailableDetector("no"))
        self.assertEqual(mod_["status"], "unavailable"); self.assertGreaterEqual(len(frames), 1)
        self.assertTrue(all(f["stance"] == "could_not_check" and f["model_scores"] is None for f in frames))
        self.assertIn("not a full-video", mod_["limitations"][0])
    def test_frames_with_model(self):
        mod_, frames, _, _ = analyze_video(self.make(), S, FakeDetector(True))
        self.assertEqual(mod_["stance"], "supports_manipulation")
    def test_corrupt_video(self):
        p = os.path.join(tempfile.mkdtemp(), "bad.mp4"); open(p, "wb").write(b"\x00" * 100)
        with self.assertRaises(VideoError): analyze_video(p, S, UnavailableDetector("no"))
    def test_video_without_audio_returns_no_track(self):
        self.assertIsNone(extract_video_audio(self.make(), S.max_video_seconds))


class Audio(unittest.TestCase):
    def make(self, seconds=1):
        buffer = io.BytesIO()
        sf.write(buffer, np.zeros(16000 * seconds, dtype=np.float32), 16000, format="WAV")
        path = os.path.join(tempfile.mkdtemp(), "sample.wav")
        with open(path, "wb") as f:
            f.write(buffer.getvalue())
        return path

    def test_no_configured_model_is_explicitly_unavailable(self):
        module, segments, details = analyze_audio(self.make(), S, UnavailableDetector("no audio model"))
        self.assertEqual(module["status"], "unavailable")
        self.assertEqual(module["stance"], "could_not_check")
        self.assertIsNone(module["score"])
        self.assertEqual(segments, [])
        self.assertEqual(details["decoder"], "libsndfile")

    def test_audio_scores_are_model_outputs_and_segments_are_aggregated(self):
        class AudioModel:
            def status(self):
                return {"ready": True, "name": "test-audio-model", "version": "1", "reason": None}

            def predict(self, samples, sample_rate):
                return {"prediction": "spoof", "scores": {"spoof": 0.8, "bonafide": 0.2}}

        settings = replace(S, audio_segment_seconds=0.5)
        module, segments, _ = analyze_audio(self.make(), settings, AudioModel())
        self.assertEqual(module["stance"], "supports_manipulation")
        self.assertEqual(module["score"], {"bonafide": 0.2, "spoof": 0.8})
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["start_s"], 0.0)

    def test_audio_duration_limit_is_enforced(self):
        settings = replace(S, max_audio_seconds=0.5)
        with self.assertRaises(v.ValidationError) as error:
            analyze_audio(self.make(), settings, UnavailableDetector("no model"))
        self.assertEqual(error.exception.status, 413)


if __name__ == "__main__":
    unittest.main()
