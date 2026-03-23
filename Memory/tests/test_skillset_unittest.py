import os
import tempfile
import unittest
from unittest import mock

from hydrai_memory.contexttree import ContexTree
from hydrai_memory.skillset import SkillSet


class _FakeEmbedder:
    def embed(self, text: str) -> str:
        if "diagram" in text.lower():
            return "AACAPw=="
        return "AAAAPw=="

    def decode(self, vec_b64: str):
        import base64
        import numpy as np

        return np.frombuffer(base64.b64decode(vec_b64), dtype=np.float32)

    def similarity(self, vec_a, vec_b) -> float:
        import numpy as np

        if np.array_equal(vec_a, vec_b):
            return 1.0
        return 0.4


def _write_skill(tree: ContexTree, rel_dir: str, skill_md: str, summary: str = "") -> None:
    tree.write_text(f"{rel_dir}/SKILL.md", skill_md, summary=summary)


class SkillSetTests(unittest.TestCase):
    def test_list_skills_returns_skill_roots_and_summaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "skills")
            os.mkdir(root)
            tree = ContexTree(root)
            _write_skill(
                tree,
                "github",
                "---\nname: github\ndescription: Work with GitHub.\n---\n\n# GitHub\nUse gh.\n",
                summary="GitHub workflow helper",
            )
            _write_skill(
                tree,
                "video-frames",
                "---\nname: video-frames\ndescription: Extract video frames.\n---\n\n# Frames\n",
            )

            skills = SkillSet().list_skills(root)

            self.assertEqual(
                skills,
                [
                    {
                        "name": "github",
                        "path": os.path.realpath(os.path.join(root, "github")),
                        "summary": "GitHub workflow helper",
                    },
                    {
                        "name": "video-frames",
                        "path": os.path.realpath(os.path.join(root, "video-frames")),
                        "summary": "Extract video frames.",
                    },
                ],
            )

    def test_search_skills_maps_hits_back_to_enclosing_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "skills")
            os.mkdir(root)
            tree = ContexTree(root, embedder=_FakeEmbedder())
            _write_skill(
                tree,
                "diagram-helper",
                "---\nname: diagram-helper\ndescription: Understand diagrams.\n---\n\n# Diagram Helper\n",
                summary="Diagram analysis helper",
            )
            tree.write_text(
                "diagram-helper/references/guide.md",
                "Use this to inspect architecture diagram labels.",
                summary="diagram guide",
            )
            _write_skill(
                tree,
                "shell-helper",
                "---\nname: shell-helper\ndescription: Run shell tasks.\n---\n\n# Shell Helper\n",
                summary="General shell helper",
            )

            skills = SkillSet(embedder=_FakeEmbedder()).search_skills(root, "diagram", limit=5, min_score=0.3)

            self.assertEqual(skills[0]["name"], "diagram-helper")
            self.assertEqual(skills[0]["path"], os.path.realpath(os.path.join(root, "diagram-helper")))
            self.assertTrue(skills[0]["matched_path"].endswith(("SKILL.md", "guide.md")))
            self.assertGreaterEqual(skills[0]["score"], 0.4)

    def test_search_skills_requires_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "skills")
            os.mkdir(root)
            self.assertEqual(SkillSet().search_skills(root, ""), [])

    def test_render_prompt_uses_skill_body_without_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "skills")
            os.mkdir(root)
            tree = ContexTree(root)
            _write_skill(
                tree,
                "openai-image-gen",
                "---\nname: openai-image-gen\ndescription: Generate images.\n---\n\n# Image Generation\nUse this skill to generate images.\n",
            )

            prompt = SkillSet().render_prompt([os.path.join(root, "openai-image-gen")])

            self.assertIn('<skill name="openai-image-gen"', prompt)
            self.assertIn("Description: Generate images.", prompt)
            self.assertIn("# Image Generation", prompt)
            self.assertNotIn("name: openai-image-gen", prompt)

    def test_list_skills_parses_yaml_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "skills")
            os.mkdir(root)
            tree = ContexTree(root)
            _write_skill(
                tree,
                "quoted",
                """---
name: 'quoted-skill'
description: "Quoted description"
metadata:
  homepage: https://example.com
---

# Quoted
""",
            )

            skills = SkillSet().list_skills(root)

            self.assertEqual(
                skills,
                [
                    {
                        "name": "quoted-skill",
                        "path": os.path.realpath(os.path.join(root, "quoted")),
                        "summary": "Quoted description",
                    }
                ],
            )

    def test_deploy_defaults_copies_shipped_shortlist_and_builtin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "installed-skills")
            result = SkillSet().deploy_defaults(root)

            self.assertEqual(result["root"], os.path.realpath(root))
            self.assertEqual(result["created"], ["shortlist", "builtin"])
            self.assertEqual(result["skipped"], [])
            self.assertTrue(os.path.isfile(os.path.join(root, "shortlist", "context", "SKILL.md")))
            self.assertTrue(os.path.isfile(os.path.join(root, "shortlist", "attachments", "SKILL.md")))
            self.assertTrue(os.path.isfile(os.path.join(root, "builtin", "git", "SKILL.md")))
            self.assertTrue(os.path.isfile(os.path.join(root, "builtin", "email", "SKILL.md")))

    def test_initialize_skips_existing_category_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "installed-skills")
            os.makedirs(os.path.join(root, "shortlist"))
            with open(os.path.join(root, "shortlist", "custom.txt"), "w", encoding="utf-8") as handle:
                handle.write("keep")

            result = SkillSet().initialize(root)

            self.assertEqual(result["created"], ["builtin"])
            self.assertEqual(result["skipped"], ["shortlist"])
            with open(os.path.join(root, "shortlist", "custom.txt"), "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "keep")
            self.assertTrue(os.path.isfile(os.path.join(root, "builtin", "bash", "SKILL.md")))

    def test_deployed_shortlist_root_can_be_listed_and_rendered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "installed-skills")
            skillset = SkillSet()
            skillset.deploy_defaults(root)

            shortlist = skillset.list_skills(os.path.join(root, "shortlist"))

            self.assertEqual(
                [entry["name"] for entry in shortlist],
                ["attachments", "context", "read-file", "web-search"],
            )

            prompt = skillset.render_prompt(
                [os.path.join(root, "shortlist", "context"), os.path.join(root, "shortlist", "attachments")]
            )

            self.assertIn('<skill name="context"', prompt)
            self.assertIn('<skill name="attachments"', prompt)
            self.assertIn("latest_attachments", prompt)

    def test_search_skills_without_embedder_uses_text_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "skills")
            os.mkdir(root)
            tree = ContexTree(root)
            _write_skill(
                tree,
                "diagram-helper",
                "---\nname: diagram-helper\ndescription: Understand diagrams.\n---\n\n# Diagram Helper\n",
                summary="Diagram analysis helper",
            )

            hits = SkillSet().search_skills(root, "diagram")

            self.assertEqual(hits[0]["name"], "diagram-helper")
            self.assertEqual(hits[0]["path"], os.path.realpath(os.path.join(root, "diagram-helper")))

    def test_list_skills_fallback_scans_nested_category_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "skills")
            os.makedirs(os.path.join(root, "builtin", "git"))
            with open(os.path.join(root, "builtin", "git", "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write("---\nname: git\ndescription: Use git safely.\n---\n\n# Git\n")

            skillset = SkillSet()
            with mock.patch.object(skillset, "_make_tree", side_effect=RuntimeError("force fallback")):
                skills = skillset.list_skills(root)

            self.assertEqual(
                skills,
                [
                    {
                        "name": "git",
                        "path": os.path.realpath(os.path.join(root, "builtin", "git")),
                        "summary": "Use git safely.",
                    }
                ],
            )

    def test_render_default_prompt_works_without_contextree_access(self):
        prompt = SkillSet().render_default_prompt("shortlist", ["context", "attachments"])

        self.assertIn('<skill name="context"', prompt)
        self.assertIn('<skill name="attachments"', prompt)
        self.assertIn("latest_attachments", prompt)


if __name__ == "__main__":
    unittest.main()
