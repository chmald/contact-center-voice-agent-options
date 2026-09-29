"""Create (or update) the knowledge index in Azure AI Search and upload documents.

Uses your Entra ID sign-in (DefaultAzureCredential / ``az login``) - the platform
Bicep grants the deploying user Search Service Contributor + Search Index Data
Contributor, and the search service has key auth disabled.

    python scripts/load-knowledge-index.py --endpoint https://<search>.search.windows.net

The index schema matches the ``search_knowledge_base`` tool's handler_config in
config/agent-profile.json (id, title, content, source + a semantic configuration),
so both example apps retrieve from it without code changes.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from azure.identity import DefaultAzureCredential

ROOT = Path(__file__).resolve().parents[1]
API_VERSION = "2024-07-01"
SCOPE = "https://search.azure.com/.default"


def index_definition(name: str, semantic_config: str) -> dict:
    return {
        "name": name,
        "fields": [
            {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
            {"name": "title", "type": "Edm.String", "searchable": True},
            {"name": "content", "type": "Edm.String", "searchable": True},
            {"name": "source", "type": "Edm.String", "filterable": True},
        ],
        "semantic": {
            "configurations": [
                {
                    "name": semantic_config,
                    "prioritizedFields": {
                        "titleField": {"fieldName": "title"},
                        "prioritizedContentFields": [{"fieldName": "content"}],
                    },
                }
            ]
        },
    }


def _request(method: str, url: str, token: str, body: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise SystemExit(f"{method} {url} failed: HTTP {exc.code} {detail}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--endpoint", required=True, help="https://<search-service>.search.windows.net")
    parser.add_argument("--index", default="knowledge")
    parser.add_argument("--semantic-config", default="default")
    parser.add_argument("--file", default=str(ROOT / "config" / "knowledge-base.json"))
    parser.add_argument("--collection", default="documents")
    args = parser.parse_args()

    documents = json.loads(Path(args.file).read_text(encoding="utf-8"))
    if isinstance(documents, dict):
        documents = documents.get(args.collection, [])
    if not isinstance(documents, list) or not documents:
        raise SystemExit(f"No documents found in {args.file} ({args.collection})")

    endpoint = args.endpoint.rstrip("/")
    token = DefaultAzureCredential(exclude_interactive_browser_credential=False).get_token(SCOPE).token

    _request(
        "PUT",
        f"{endpoint}/indexes/{args.index}?api-version={API_VERSION}",
        token,
        index_definition(args.index, args.semantic_config),
    )
    actions = [
        {
            "@search.action": "mergeOrUpload",
            "id": str(doc["id"]),
            "title": str(doc.get("title", "")),
            "content": str(doc.get("content", "")),
            "source": str(doc.get("source", "")),
        }
        for doc in documents
        if isinstance(doc, dict) and doc.get("id")
    ]
    result = _request(
        "POST",
        f"{endpoint}/indexes/{args.index}/docs/index?api-version={API_VERSION}",
        token,
        {"value": actions},
    )
    failed = [item for item in result.get("value", []) if not item.get("status")]
    print(f"Index '{args.index}': uploaded {len(actions) - len(failed)} of {len(actions)} documents.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
