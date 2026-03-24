import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from hydrai_memory.identity_state import IdentityStore
from hydrai_memory.skillset import SkillManager, TrustedSkillHub


class SkillManagerTests(unittest.TestCase):
    def _make_identity(self, storage_root: str, config: dict | None = None) -> IdentityStore:
        store = IdentityStore(storage_root, "alpha")
        store.create_identity("athena", "Strategist", "Core self", config or {})
        return store

    def _make_hub(self, tmp: str) -> TrustedSkillHub:
        archive_root = Path(tmp) / "archive-src" / "demo-skill"
        archive_root.mkdir(parents=True, exist_ok=True)
        (archive_root / "SKILL.md").write_text(
            "---\nname: demo-skill\ndescription: Installed demo skill.\n---\n\n# Demo\nUse this installed skill.\n",
            encoding="utf-8",
        )
        archive_path = Path(tmp) / "demo-skill.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            for current_root, _dirnames, filenames in os.walk(archive_root.parent):
                for filename in filenames:
                    full = Path(current_root) / filename
                    archive.write(full, full.relative_to(archive_root.parent))
        index_path = Path(tmp) / "index.json"
        index_path.write_text(
            json.dumps(
                {
                    "skills": [
                        {
                            "name": "demo-skill",
                            "summary": "Installed demo skill.",
                            "archive_url": archive_path.as_uri(),
                            "version": "1.0.0",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return TrustedSkillHub(
            hub_id="trusted",
            index_url=index_path.as_uri(),
            site_url="https://skills.example.test/",
            description="Trusted test hub",
        )

    def test_initialize_and_brain_skill_apis(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = os.path.join(tmp, "memory")
            self._make_identity(storage_root, {"skills": {"blacklist": ["email"]}})
            manager = SkillManager(storage_root, "alpha")

            init = manager.initialize_defaults()
            self.assertIn("shortlist", init["created"])
            self.assertIn("builtin", init["created"])

            listing = manager.skill_list("athena")["results"]
            names = {(item["category"], item["name"]) for item in listing}
            self.assertIn(("shortlist", "context"), names)
            self.assertNotIn(("builtin", "email"), names)

            search = manager.skill_search("athena", "context", limit=5)["results"]
            self.assertTrue(any(item["name"] == "context" for item in search))

            read = manager.skill_read("athena", "context")
            self.assertEqual(read["results"][0]["category"], "shortlist")
            self.assertIn("<skill name=\"context\"", read["results"][0]["prompt_text"])

    def test_skill_whitelist_filters_visible_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = os.path.join(tmp, "memory")
            self._make_identity(storage_root, {"skills": {"whitelist": ["context"]}})
            manager = SkillManager(storage_root, "alpha")
            manager.initialize_defaults()

            listing = manager.skill_list("athena")["results"]
            self.assertEqual({item["name"] for item in listing}, {"context"})
            self.assertEqual(manager.skill_search("athena", "attachments")["results"], [])
            self.assertEqual(manager.skill_read("athena", "attachments")["results"], [])

    def test_install_skill_from_trusted_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root = os.path.join(tmp, "memory")
            self._make_identity(storage_root)
            hub = self._make_hub(tmp)
            manager = SkillManager(storage_root, "alpha", trusted_hubs=(hub,))
            manager.initialize_defaults()

            sites = manager.list_trusted_sites()
            self.assertEqual(sites[0]["id"], "trusted")

            installed = manager.install_skill("athena", "trusted", "demo-skill")
            self.assertEqual(installed["name"], "demo-skill")
            self.assertEqual(installed["category"], "user")
            self.assertTrue(os.path.isfile(os.path.join(installed["path"], "SKILL.md")))
            self.assertTrue(os.path.isfile(os.path.join(installed["path"], ".INSTALL.json")))

            listing = manager.skill_list("athena")["results"]
            self.assertTrue(any(item["category"] == "user" and item["name"] == "demo-skill" for item in listing))

            with self.assertRaises(FileExistsError):
                manager.install_skill("athena", "trusted", "demo-skill")


if __name__ == "__main__":
    unittest.main()
