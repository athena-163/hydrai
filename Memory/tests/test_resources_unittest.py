import os
import tempfile
import unittest

from hydrai_memory.contexttree import ContexTree
from hydrai_memory.resources import MemorySandboxAPI, ResourceRegistry
from hydrai_memory.identity_state import IdentityState
from hydrai_memory.sessionbook import SessionBook


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


class ResourceRegistryTests(unittest.TestCase):
    def test_register_list_and_unregister_resource(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = os.path.join(tmp, "sandboxes", "alpha")
            os.makedirs(sandbox_root, exist_ok=True)
            resource_root = os.path.join(tmp, "sandbox-home", "workspace")
            os.makedirs(resource_root, exist_ok=True)
            tree = ContexTree(resource_root)
            tree.set_folder_summary("", "Workspace summary")

            registry = ResourceRegistry(sandbox_root)
            item = registry.register_resource(
                "workspace-main",
                resource_root,
                config_path="/tmp/context.json",
                maintain_interval_sec=None,
            )

            self.assertEqual(item["id"], "workspace-main")
            self.assertEqual(item["type"], "context_tree")
            self.assertEqual(item["root"], os.path.realpath(resource_root))
            self.assertEqual(item["summary"], "Workspace summary")

            listed = registry.list_resources()
            self.assertEqual([entry["id"] for entry in listed], ["workspace-main"])

            removed = registry.unregister_resource("workspace-main")
            self.assertEqual(removed["id"], "workspace-main")
            self.assertEqual(registry.list_resources(), [])

    def test_reconcile_maintenance_starts_and_stops_threads(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = os.path.join(tmp, "sandboxes", "alpha")
            os.makedirs(sandbox_root, exist_ok=True)
            resource_root = os.path.join(tmp, "sandbox-home", "workspace")
            os.makedirs(resource_root, exist_ok=True)

            registry = ResourceRegistry(sandbox_root)
            registry.register_resource("workspace-main", resource_root, maintain_interval_sec=0.05)
            try:
                started = registry.reconcile_maintenance("workspace-main")[0]
                self.assertEqual(started["action"], "started")
                self.assertTrue(started["maintenance"]["running"])

                registry.register_resource("workspace-main", resource_root, maintain_interval_sec=0)
                stopped = registry.reconcile_maintenance("workspace-main")[0]
                self.assertIn(stopped["action"], {"stopped", "disabled"})
                self.assertFalse(stopped["maintenance"]["running"])
            finally:
                registry.stop_all_maintenance()

    def test_resource_map_for_brain_uses_registered_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = os.path.join(tmp, "sandboxes", "alpha")
            os.makedirs(sandbox_root, exist_ok=True)
            resource_root = os.path.join(tmp, "sandbox-home", "workspace")
            os.makedirs(resource_root, exist_ok=True)
            registry = ResourceRegistry(sandbox_root)
            registry.register_resource("workspace-main", resource_root)

            mapping = registry.resource_map_for_brain()

            self.assertEqual(
                mapping,
                {
                    "workspace-main": {
                        "type": "context_tree",
                        "path": os.path.realpath(resource_root),
                        "summary": "",
                    }
                },
            )


class MemorySandboxAPITests(unittest.TestCase):
    def _make_layout(self, tmp: str) -> tuple[str, str, str]:
        storage_root = os.path.join(tmp, "memory")
        sandbox_root = os.path.join(storage_root, "sandboxes", "alpha")
        sandbox_home = os.path.join(tmp, "sandbox-home")
        os.makedirs(os.path.join(sandbox_root, "identities"), exist_ok=True)
        os.makedirs(os.path.join(sandbox_root, "sessions"), exist_ok=True)
        os.makedirs(os.path.join(sandbox_root, "human"), exist_ok=True)
        os.makedirs(os.path.join(sandbox_root, "native"), exist_ok=True)
        os.makedirs(sandbox_home, exist_ok=True)
        return storage_root, sandbox_root, sandbox_home

    def test_api_handles_resource_identity_and_session_trees(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root, sandbox_root, sandbox_home = self._make_layout(tmp)
            resource_root = os.path.join(sandbox_home, "workspace")
            os.makedirs(resource_root, exist_ok=True)
            registry = ResourceRegistry(sandbox_root)
            registry.register_resource("workspace-main", resource_root)

            ident_root = os.path.join(sandbox_root, "identities", "athena")
            IdentityState.create(ident_root, embedder=_FakeEmbedder())
            session_root = os.path.join(sandbox_root, "sessions", "chat-1")
            SessionBook.create(session_root, embedder=_FakeEmbedder())

            api = MemorySandboxAPI(
                storage_root,
                "alpha",
                sandbox_space_root=sandbox_home,
                embedder=_FakeEmbedder(),
            )

            api.write(
                target_type="resource",
                target_id="workspace-main",
                path="notes.md",
                content="diagram notes",
                summary="diagram reference",
            )
            api.append(
                target_type="resource",
                target_id="workspace-main",
                path="notes.md",
                content="\nextra",
                summary="diagram reference",
            )
            read_result = api.read(target_type="resource", target_id="workspace-main", paths=["notes.md"])
            self.assertIn("diagram notes", read_result["notes.md"])
            self.assertIn("extra", read_result["notes.md"])

            search_result = api.search(target_type="resource", target_id="workspace-main", query_text="diagram")
            self.assertTrue(search_result["results"])

            api.write(
                target_type="identity",
                target_id="athena",
                path="dynamics/self.md",
                content="focused",
                summary="self state",
            )
            identity_read = api.read(target_type="identity", target_id="athena", paths=["dynamics/self.md"])
            self.assertEqual(identity_read["dynamics/self.md"], "focused")

            api.write(
                target_type="session",
                target_id="chat-1",
                path="notes.md",
                content="session note",
                summary="session state",
            )
            session_view = api.view(target_type="session", target_id="chat-1", depth=1, summary_depth=1)
            self.assertTrue(any(item["path"] == "notes.md" for item in session_view))

            delete_result = api.delete(target_type="resource", target_id="workspace-main", path="notes.md")
            self.assertEqual(delete_result, {"ok": True, "path": "notes.md"})

    def test_brain_access_cannot_escape_sandbox_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root, sandbox_root, sandbox_home = self._make_layout(tmp)
            outsider_root = os.path.join(tmp, "outside-root")
            os.makedirs(outsider_root, exist_ok=True)
            ResourceRegistry(sandbox_root).register_resource("outside", outsider_root)

            api = MemorySandboxAPI(storage_root, "alpha", sandbox_space_root=sandbox_home)

            with self.assertRaises(PermissionError):
                api.view(target_type="resource", target_id="outside")

    def test_system_access_can_read_outside_registered_resource(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage_root, sandbox_root, sandbox_home = self._make_layout(tmp)
            outsider_root = os.path.join(tmp, "outside-root")
            os.makedirs(outsider_root, exist_ok=True)
            ContexTree(outsider_root).write_text("public.md", "hello", summary="public note")
            ResourceRegistry(sandbox_root).register_resource("outside", outsider_root)

            api = MemorySandboxAPI(
                storage_root,
                "alpha",
                sandbox_space_root=sandbox_home,
                system_access=True,
                embedder=_FakeEmbedder(),
            )

            result = api.read(target_type="resource", target_id="outside", paths=["public.md"])
            self.assertEqual(result["public.md"], "hello")


if __name__ == "__main__":
    unittest.main()
