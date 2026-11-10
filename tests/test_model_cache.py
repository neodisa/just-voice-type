import os
import tempfile
import unittest

import model_cache

REPO = "mlx-community/parakeet-tdt-0.6b-v3"


class TestModelCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _snapshot(self, files, incomplete=False):
        d = model_cache.repo_dir(REPO, self.cache)
        snap = os.path.join(d, "snapshots", "abc123")
        os.makedirs(snap)
        os.makedirs(os.path.join(d, "blobs"))
        for name in files:
            open(os.path.join(snap, name), "w").close()
        if incomplete:
            open(os.path.join(d, "blobs", "deadbeef.incomplete"), "w").close()

    def test_repo_dir_layout(self):
        self.assertEqual(
            model_cache.repo_dir(REPO, "/c"),
            "/c/models--mlx-community--parakeet-tdt-0.6b-v3",
        )

    def test_missing_repo_is_not_cached(self):
        self.assertFalse(model_cache.is_cached(REPO, self.cache))

    def test_weights_present_is_cached(self):
        self._snapshot(["config.json", "model.safetensors"])
        self.assertTrue(model_cache.is_cached(REPO, self.cache))

    def test_only_config_is_not_cached(self):
        self._snapshot(["config.json"])
        self.assertFalse(model_cache.is_cached(REPO, self.cache))

    def test_incomplete_download_is_not_cached(self):
        self._snapshot(["model.safetensors"], incomplete=True)
        self.assertFalse(model_cache.is_cached(REPO, self.cache))

    def test_non_hub_names_count_as_cached(self):
        # CPU-движок: «large-v3»; локальный путь к модели
        self.assertTrue(model_cache.is_cached("large-v3", self.cache))
        self.assertTrue(model_cache.is_cached(self.cache, self.cache))

    def test_hub_cache_dir_env(self):
        old = {k: os.environ.get(k) for k in ("HF_HUB_CACHE", "HF_HOME")}
        try:
            os.environ.pop("HF_HUB_CACHE", None)
            os.environ["HF_HOME"] = "/hf"
            self.assertEqual(model_cache.hub_cache_dir(), "/hf/hub")
            os.environ["HF_HUB_CACHE"] = "/direct"
            self.assertEqual(model_cache.hub_cache_dir(), "/direct")
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class TestDownloadedBytes(unittest.TestCase):
    def test_counts_blobs_including_incomplete(self):
        with tempfile.TemporaryDirectory() as cache:
            self.assertEqual(model_cache.downloaded_bytes(REPO, cache), 0)
            blobs = os.path.join(model_cache.repo_dir(REPO, cache), "blobs")
            os.makedirs(blobs)
            with open(os.path.join(blobs, "a"), "wb") as f:
                f.write(b"x" * 10)
            with open(os.path.join(blobs, "b.incomplete"), "wb") as f:
                f.write(b"x" * 5)
            self.assertEqual(model_cache.downloaded_bytes(REPO, cache), 15)
