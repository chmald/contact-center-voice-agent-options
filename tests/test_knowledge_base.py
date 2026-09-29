from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_synthetic_corpus_is_well_formed_and_speakable():
    data = json.loads((ROOT / "config" / "knowledge-base.json").read_text(encoding="utf-8"))
    assert "SYNTHETIC" in data["_note"]
    docs = data["documents"]
    assert len(docs) >= 40
    for key in ("id", "source"):
        values = [doc[key] for doc in docs]
        assert len(values) == len(set(values)), f"duplicate {key}"
    for doc in docs:
        for field in ("id", "title", "category", "content", "source", "last_reviewed"):
            assert isinstance(doc.get(field), str) and doc[field].strip(), f"{doc.get('id')} missing {field}"
        # The RAG tool truncates to 600 characters; keep articles short enough to be spoken whole.
        assert len(doc["content"]) <= 600, doc["id"]
        assert doc["source"].startswith("kb/")
    assert len({doc["category"] for doc in docs}) >= 6


def test_synthetic_records_keep_fixed_ids_and_are_deterministic(tmp_path):
    module = _load("generate_synthetic_data", "scripts/generate-synthetic-data.py")
    first, second = module.generate(30), module.generate(30)
    assert first == second
    ids = [record["id"] for record in first]
    assert ids[:5] == ["SR-1001", "SR-1002", "SR-1003", "SR-1004", "SR-1005"]
    assert len(ids) == len(set(ids)) == 30
    shipped = json.loads((ROOT / "config" / "sample-data.json").read_text(encoding="utf-8"))["records"]
    assert shipped == first
    sources = {doc["source"] for doc in json.loads((ROOT / "config" / "knowledge-base.json").read_text(encoding="utf-8"))["documents"]}
    assert all(record.get("related_article", "kb/password-reset") in sources for record in first)


def test_index_definition_matches_corpus_fields():
    module = _load("load_knowledge_index", "scripts/load-knowledge-index.py")
    definition = module.index_definition("knowledge", "default")
    names = {field["name"] for field in definition["fields"]}
    assert {"id", "title", "content", "source", "category", "last_reviewed"} <= names
    config = definition["semantic"]["configurations"][0]
    assert config["prioritizedFields"]["titleField"] == {"fieldName": "title"}
    assert config["prioritizedFields"]["prioritizedKeywordsFields"] == [{"fieldName": "category"}]


def test_knowledge_project_contract():
    knowledge = ROOT / "knowledge"
    text = "\n".join(path.read_text(encoding="utf-8") for path in (knowledge / "infra").rglob("*.bicep"))
    assert "Microsoft.Search/searchServices@" in text
    assert "disableLocalAuth: true" in text
    assert "semanticSearch: 'free'" in text
    assert "8ebe5a00-799e-43f5-93ac-243d3dce84a7" in text  # Search Index Data Contributor (deploying user)
    assert "KNOWLEDGE_RESOURCE_GROUP" in text
    assert "run: hooks/postprovision.ps1" in (knowledge / "azure.yaml").read_text(encoding="utf-8")
    hook = (knowledge / "hooks" / "postprovision.ps1").read_text(encoding="utf-8")
    assert "load-knowledge-index.py" in hook and "--recreate" in hook
    assert (ROOT / "scripts" / "use-knowledge-base.ps1").exists()
