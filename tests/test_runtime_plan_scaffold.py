from __future__ import annotations

from tests.runtime_test_support import *


class PlanScaffoldTests(unittest.TestCase):
    def test_plan_scaffold_creates_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)

            light = create_plan_scaffold("修复登录错误提示", config=config, level="light")
            standard = create_plan_scaffold("实现 runtime skeleton", config=config, level="standard")
            full = create_plan_scaffold("设计 runtime architecture plugin bridge", config=config, level="full")

            self.assertTrue((workspace / light.path / "plan.md").exists())
            self.assertTrue((workspace / standard.path / "background.md").exists())
            self.assertTrue((workspace / standard.path / "design.md").exists())
            self.assertTrue((workspace / standard.path / "tasks.md").exists())
            self.assertTrue((workspace / full.path / "adr").is_dir())
            self.assertTrue((workspace / full.path / "diagrams").is_dir())

    def test_plan_scaffold_writes_knowledge_sync_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)

            light = create_plan_scaffold("修复登录错误提示", config=config, level="light")
            standard = create_plan_scaffold("实现 runtime skeleton", config=config, level="standard")
            full = create_plan_scaffold("设计 runtime architecture plugin bridge", config=config, level="full")

            light_text = (workspace / light.path / "plan.md").read_text(encoding="utf-8")
            standard_text = (workspace / standard.path / "tasks.md").read_text(encoding="utf-8")
            full_text = (workspace / full.path / "tasks.md").read_text(encoding="utf-8")

            self.assertIn("knowledge_sync:", light_text)
            self.assertIn("  project: skip", light_text)
            self.assertIn("  design: review", light_text)
            self.assertNotIn("blueprint_obligation:", light_text)

            self.assertIn("knowledge_sync:", standard_text)
            self.assertIn("  project: review", standard_text)
            self.assertIn("  background: review", standard_text)
            self.assertIn("  design: review", standard_text)
            self.assertIn("  tasks: review", standard_text)
            self.assertNotIn("blueprint_obligation:", standard_text)

            self.assertIn("knowledge_sync:", full_text)
            self.assertIn("  background: required", full_text)
            self.assertIn("  design: required", full_text)
            self.assertIn("  tasks: review", full_text)
            self.assertNotIn("blueprint_obligation:", full_text)

    def test_plan_scaffold_avoids_directory_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)

            first = create_plan_scaffold("补 runtime 骨架", config=config, level="standard")
            second = create_plan_scaffold("补 runtime 骨架", config=config, level="standard")

            self.assertNotEqual(first.path, second.path)
            self.assertTrue(second.path.endswith("-2"))

    def test_plan_scaffold_persists_topic_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)

            artifact = create_plan_scaffold("补 runtime 骨架", config=config, level="standard")
            tasks_text = (workspace / artifact.path / "tasks.md").read_text(encoding="utf-8")

            self.assertEqual(artifact.topic_key, "runtime")
            self.assertIn("feature_key: runtime", tasks_text)

    def test_explicit_new_plan_patterns_ignore_ambiguous_other_plan_phrase(self) -> None:
        self.assertFalse(request_explicitly_wants_new_plan("分析这个方案和其他 plan 的差异"))
        self.assertTrue(request_explicitly_wants_new_plan("请新建一个 plan 处理这个问题"))

    def test_explicit_new_plan_patterns_respect_local_negation_without_global_blocking(self) -> None:
        self.assertFalse(request_explicitly_wants_new_plan("不要新建新的 plan 包，直接在当前 plan 上继续细化"))
        self.assertTrue(request_explicitly_wants_new_plan("不要复用当前 plan，直接新建 plan"))
        self.assertTrue(request_explicitly_wants_new_plan("不是不要新建 plan，而是要新建 plan"))
        self.assertTrue(request_explicitly_wants_new_plan("do not create a new plan; create a new plan now"))
