import builtins
from contextlib import ExitStack, closing, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from src import main as pipeline


class PipelineTestCase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.output = self.root / "output"
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.stack.enter_context(patch.object(pipeline, "load_dotenv"))
        self.stack.enter_context(patch("socket.socket.connect", side_effect=AssertionError("Network access")))
        self.stack.enter_context(patch("socket.socket.connect_ex", side_effect=AssertionError("Network access")))

    def make_image(self, name="valid.png", image_format="PNG"):
        path = self.inputs / name
        with Image.new("RGB", (32, 32), "red") as image:
            image.save(path, format=image_format)
        return path

    def invoke(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = pipeline.main([
                    "--input-dir", str(self.inputs),
                    "--output-dir", str(self.output),
                    *arguments,
                ])
            except SystemExit as exc:
                code = exc.code
        return code, stdout.getvalue(), stderr.getvalue()


class CheckInputsTests(PipelineTestCase):
    def setUp(self):
        super().setUp()
        original_import = builtins.__import__

        def local_import(name, *args, **kwargs):
            if name.split(".")[0] in {"boto3", "botocore", "google"}:
                raise AssertionError(f"Cloud import attempted: {name}")
            return original_import(name, *args, **kwargs)

        self.stack.enter_context(patch("builtins.__import__", side_effect=local_import))
        for name in ("ask_vlm", "initialize_database", "save_result", "export_results"):
            self.stack.enter_context(patch.object(
                pipeline, name, side_effect=AssertionError(f"Unexpected call: {name}")
            ))
        self.stack.enter_context(patch.object(
            pipeline.sqlite3, "connect", side_effect=AssertionError("Database access")
        ))

    def test_valid_formats_case_and_mismatched_extension_without_credentials(self):
        fixtures = [
            ("a.PNG", "PNG"), ("b.jpg", "JPEG"), ("c.JPEG", "JPEG"),
            ("d.WeBp", "WEBP"), ("e.png", "JPEG"),
        ]
        for name, image_format in fixtures:
            self.make_image(name, image_format)
        before = {path.name: path.read_bytes() for path in self.inputs.iterdir()}

        code, stdout, stderr = self.invoke("--check-inputs")

        self.assertEqual(code, 0)
        self.assertIn("Checked 5 images: 5 valid, 0 invalid.", stdout)
        self.assertEqual(stderr, "")
        self.assertFalse(self.output.exists())
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.inputs.iterdir()})

    def test_mixed_batch_continues_and_reports_invalid_files_in_order(self):
        self.make_image("b-valid.png")
        (self.inputs / "a-corrupt.png").write_bytes(b"invalid image")
        self.make_image("c-unsupported.png", "GIF")

        code, stdout, stderr = self.invoke("--check-inputs")

        self.assertEqual(code, 1)
        self.assertIn("Checked 3 images: 1 valid, 2 invalid.", stdout)
        self.assertIn("INVALID a-corrupt.png:", stdout)
        self.assertIn("INVALID c-unsupported.png:", stdout)
        self.assertLess(stdout.index("a-corrupt.png"), stdout.index("c-unsupported.png"))
        self.assertEqual(stderr, "")
        self.assertFalse(self.output.exists())

    def test_check_inputs_stays_local_when_cloud_configuration_is_present(self):
        self.make_image()
        with patch.dict(os.environ, {
            "VLM_API_KEY": "test-only", "VLM_MODEL": "test-model", "S3_BUCKET": "test-bucket"
        }):
            code, stdout, stderr = self.invoke("--check-inputs")
        self.assertEqual(code, 0)
        self.assertIn("Checked 1 images: 1 valid, 0 invalid.", stdout)
        self.assertEqual(stderr, "")
        self.assertFalse(self.output.exists())

    def test_truncated_jpeg_requires_pixel_decoding(self):
        path = self.make_image("truncated.jpg", "JPEG")
        path.write_bytes(path.read_bytes()[:-2])
        # Establish that verify() alone misses this specific corruption.
        with Image.open(path) as image:
            image.verify()

        code, stdout, _ = self.invoke("--check-inputs")

        self.assertEqual(code, 1)
        self.assertIn("INVALID truncated.jpg:", stdout)
        self.assertIn("Checked 1 images: 0 valid, 1 invalid.", stdout)

    def test_unreadable_file_is_counted_and_processing_continues(self):
        unreadable = self.make_image("a-unreadable.png")
        self.make_image("b-valid.png")
        original_inspect = pipeline.inspect_image

        def inspect(path):
            if path == unreadable:
                raise PermissionError("Access denied")
            return original_inspect(path)

        with patch.object(pipeline, "inspect_image", side_effect=inspect):
            code, stdout, _ = self.invoke("--check-inputs")

        self.assertEqual(code, 1)
        self.assertIn("INVALID a-unreadable.png: PermissionError: Access denied", stdout)
        self.assertIn("Checked 2 images: 1 valid, 1 invalid.", stdout)

    def test_unsupported_extensions_subfolders_and_directories_are_skipped(self):
        self.make_image()
        (self.inputs / "ignored.txt").write_text("not an image", encoding="utf-8")
        nested = self.inputs / "nested"
        nested.mkdir()
        (nested / "corrupt.png").write_bytes(b"invalid")
        (self.inputs / "directory.png").mkdir()

        code, stdout, _ = self.invoke("--check-inputs")

        self.assertEqual(code, 0)
        self.assertIn("Checked 1 images: 1 valid, 0 invalid.", stdout)

    def test_empty_scan_reports_zero_counts_and_exits_two(self):
        for ignored_file in (False, True):
            with self.subTest(ignored_file=ignored_file):
                if ignored_file:
                    (self.inputs / "ignored.txt").write_text("text", encoding="utf-8")
                code, stdout, stderr = self.invoke("--check-inputs")
                self.assertEqual(code, 2)
                self.assertIn("Checked 0 images: 0 valid, 0 invalid.", stdout)
                self.assertIn("No PNG, JPEG, or WebP images found", stderr)
                self.assertFalse(self.output.exists())

    def test_missing_input_directory_exits_two(self):
        code, _, stderr = self.invoke("--check-inputs", "--input-dir", str(self.root / "missing"))
        self.assertEqual(code, 2)
        self.assertIn("Input directory does not exist", stderr)

    def test_unreadable_input_directory_exits_two(self):
        with patch.object(Path, "iterdir", side_effect=PermissionError("Access denied")):
            code, _, stderr = self.invoke("--check-inputs")
        self.assertEqual(code, 2)
        self.assertIn("Access denied", stderr)

    def test_view_and_check_inputs_are_mutually_exclusive(self):
        code, _, stderr = self.invoke("--check-inputs", "--view")
        self.assertEqual(code, 2)
        self.assertIn("not allowed with argument", stderr)

    def test_default_input_directory_is_assets(self):
        self.inputs = self.root / "assets"
        self.inputs.mkdir()
        self.make_image()
        stdout = io.StringIO()
        with patch.object(pipeline, "ROOT", self.root), redirect_stdout(stdout):
            code = pipeline.main(["--check-inputs"])
        self.assertEqual(code, 0)
        self.assertIn("Checked 1 images: 1 valid, 0 invalid.", stdout.getvalue())


class ExistingFunctionalityTests(PipelineTestCase):
    def test_inspect_image_returns_actual_mime_type(self):
        for image_format, mime_type in (
            ("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")
        ):
            with self.subTest(image_format=image_format):
                path = self.make_image(f"{image_format}.png", image_format)
                self.assertEqual(pipeline.inspect_image(path), mime_type)

    def test_normal_processing_still_requires_configuration(self):
        self.make_image()
        code, _, stderr = self.invoke()
        self.assertEqual(code, 2)
        self.assertIn("Set VLM_API_KEY, VLM_MODEL, and S3_BUCKET", stderr)
        self.assertFalse(self.output.exists())

    def test_view_reads_legacy_database_without_cloud_or_input_folder(self):
        self.output.mkdir()
        with closing(sqlite3.connect(self.output / "results.db")) as database, database:
            database.execute("CREATE TABLE image_results (filename TEXT, description TEXT)")
            database.execute("INSERT INTO image_results VALUES (?, ?)", ("old.png", "An old image"))
        code, stdout, stderr = self.invoke("--view", "--input-dir", str(self.root / "missing"))
        self.assertEqual(code, 0)
        self.assertIn('"filename": "old.png"', stdout)
        self.assertIn("Database records: 1", stdout)
        self.assertEqual(stderr, "")

    def test_mocked_cloud_processing_preserves_records_exports_and_failure_handling(self):
        valid = self.make_image()
        (self.inputs / "corrupt.png").write_bytes(b"invalid")
        self.output.mkdir()
        with closing(sqlite3.connect(self.output / "results.db")) as database, database:
            database.execute("CREATE TABLE image_results (filename TEXT PRIMARY KEY, s3_uri TEXT NOT NULL, description TEXT NOT NULL)")
            database.executemany("INSERT INTO image_results VALUES (?, ?, ?)", [
                ("old.png", "s3://bucket/old.png", "Legacy image"),
                (valid.name, "s3://bucket/previous.png", "Previous description"),
            ])
        attributes = pipeline.ItemAttributes(
            description="A red square.", item_type="square", color="red", brand=None,
            distinctive_features=["Solid red"],
        )
        s3, client = Mock(), Mock()
        boto3_module, google_module = ModuleType("boto3"), ModuleType("google")
        boto3_module.client = Mock(return_value=s3)
        google_module.genai = SimpleNamespace(Client=Mock(return_value=client))
        modules = {"boto3": boto3_module, "google": google_module}
        with patch.dict("sys.modules", modules), patch.dict(os.environ, {"VLM_API_KEY": "test-only"}), patch.object(
            pipeline, "ask_vlm", return_value=attributes
        ) as ask_vlm:
            code, stdout, stderr = self.invoke("--model", "test-model", "--bucket", "test-bucket")

        self.assertEqual(code, 1)
        self.assertIn("Finished: 1 succeeded, 1 failed.", stdout)
        self.assertEqual(stderr, "")
        ask_vlm.assert_called_once_with(valid, "image/png", client, "test-model")
        s3.upload_file.assert_called_once_with(
            str(valid), "test-bucket", f"vlm-demo/{valid.name}", ExtraArgs={"ContentType": "image/png"}
        )
        client.close.assert_called_once_with()
        records = json.loads((self.output / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["description"], attributes.description)
        self.assertIn(attributes.description, (self.output / "results.txt").read_text(encoding="utf-8"))
        report = json.loads((self.output / "run_report.json").read_text(encoding="utf-8"))
        self.assertEqual((report["attempted"], report["succeeded"], report["failed"]), (2, 1, 1))
        with closing(sqlite3.connect(self.output / "results.db")) as database:
            saved = database.execute("SELECT filename, description FROM image_results ORDER BY filename").fetchall()
        self.assertEqual(saved, [("old.png", "Legacy image"), (valid.name, attributes.description)])


if __name__ == "__main__":
    unittest.main()
