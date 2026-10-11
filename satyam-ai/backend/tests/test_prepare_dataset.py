import csv
import pathlib
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image
import soundfile as sf

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from prepare_dataset import COLUMNS, build_dataset


class DatasetPreparationTests(unittest.TestCase):
    def _manifest(self, folder: pathlib.Path, paths: list[pathlib.Path], labels: list[str] | None = None,
                  media_type: str = "image") -> pathlib.Path:
        manifest = folder / "annotations.csv"
        with manifest.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=[
                "file_path", "media_type", "authenticity_label", "source_dataset",
                "source_url", "license", "label_source", "label_confidence", "split_group",
            ])
            writer.writeheader()
            for index, path in enumerate(paths):
                writer.writerow({
                    "file_path": str(path),
                    "media_type": media_type,
                    "authenticity_label": (labels or ["AUTHENTIC"] * len(paths))[index],
                    "source_dataset": "test-fixture",
                    "source_url": "https://example.invalid/fixture",
                    "license": "test-only",
                    "label_source": "unit-test annotation",
                    "label_confidence": "1",
                    "split_group": "related-fixture",
                })
        return manifest

    def test_missing_manifest_writes_empty_deliverables_without_fake_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = pathlib.Path(temp)
            count, _ = build_dataset(folder / "missing.csv", folder / "output")
            self.assertEqual(count, 0)
            with (folder / "output" / "satyam_ai_dataset.csv").open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(reader.fieldnames, COLUMNS)
                self.assertEqual(list(reader), [])
            report = (folder / "output" / "dataset_validation_report.txt").read_text(encoding="utf-8")
            self.assertIn("Shortfall to target: 10000", report)
            self.assertIn("no records were fabricated", report)

    def test_image_features_hash_labels_and_group_split_are_recorded(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = pathlib.Path(temp)
            image_path = folder / "fixture.png"
            related_path = folder / "related.png"
            Image.new("RGB", (16, 12), color=(120, 80, 40)).save(image_path)
            Image.new("RGB", (8, 8), color=(120, 80, 40)).save(related_path)
            manifest = self._manifest(folder, [image_path, related_path])
            count, _ = build_dataset(manifest, folder / "output", target_total=10)
            self.assertEqual(count, 2)
            with (folder / "output" / "satyam_ai_dataset.csv").open(encoding="utf-8-sig", newline="") as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual((row["image_width"], row["image_height"]), ("16", "12"))
            self.assertEqual(row["authenticity_label"], "AUTHENTIC")
            self.assertEqual(row["is_manipulated"], "0")
            self.assertEqual(row["is_fully_ai_generated"], "0")
            self.assertIn(row["split"], {"train", "validation", "test"})
            self.assertEqual(row["split_group"], "related-fixture")
            self.assertEqual(len(row["file_hash_sha256"]), 64)
            self.assertEqual(row["image_ai_generation_score"], "")
            self.assertEqual(row["authentic_probability"], "")
            with (folder / "output" / "satyam_ai_dataset.csv").open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["split"], rows[1]["split"])

    def test_audio_features_are_measured_from_the_wav(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = pathlib.Path(temp)
            audio_path = folder / "fixture.wav"
            samples = np.sin(np.linspace(0, 100, 16000, dtype=np.float32))
            sf.write(audio_path, samples, 16000)
            manifest = self._manifest(folder, [audio_path], media_type="audio")
            count, _ = build_dataset(manifest, folder / "output", target_total=10)
            self.assertEqual(count, 1)
            with (folder / "output" / "satyam_ai_dataset.csv").open(encoding="utf-8-sig", newline="") as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(row["audio_sample_rate"], "16000")
            self.assertGreater(float(row["rms_energy"]), 0)
            self.assertGreater(float(row["spectral_centroid"]), 0)
            self.assertEqual(row["synthetic_speech_score"], "")

    def test_exact_duplicates_are_removed_and_conflicting_labels_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = pathlib.Path(temp)
            image_path = folder / "fixture.png"
            Image.new("RGB", (8, 8), color="red").save(image_path)
            manifest = self._manifest(folder, [image_path, image_path], ["AUTHENTIC", "MANIPULATED"])
            count, issues = build_dataset(manifest, folder / "output", target_total=10)
            self.assertEqual(count, 0)
            self.assertTrue(any("conflicting authenticity labels" in issue for issue in issues))
            report = (folder / "output" / "dataset_validation_report.txt").read_text(encoding="utf-8")
            self.assertIn("Conflicting-label duplicate hashes excluded: 1", report)


if __name__ == "__main__":
    unittest.main()
