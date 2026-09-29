from __future__ import annotations

import json

EXAMPLES = ("voice-live-api", "realtime-api", "foundry-voice-agent")
APP_ENV_CONTRACT = (
    "AZURE_SEARCH_ENDPOINT",
    "AZURE_SEARCH_INDEX",
    "AZURE_SEARCH_SEMANTIC_CONFIG",
    "TELEPHONY_PROVIDERS",
    "TELEPHONY_WEBHOOK_SECRET",
    "ACS_EVENTGRID_SECRET",
    "TELEPHONY_OVERFLOW_NUMBER",
    "PUBLIC_BASE_URL",
    "ACS_ENDPOINT",
    "TWILIO_AUTH_TOKEN",
)


def _bicep_text(path) -> str:
    return "\n".join(file.read_text(encoding="utf-8") for file in path.rglob("*.bicep"))


def test_platform_owns_single_endpoint_deployment_search_and_acs(repo_root):
    platform = repo_root / "platform"
    text = _bicep_text(platform / "infra")

    assert (platform / "azure.yaml").exists()
    assert "services:" not in (platform / "azure.yaml").read_text(encoding="utf-8")
    assert text.count("kind: 'AIServices'") == 1
    assert "GlobalStandard" in text
    assert "disableLocalAuth: true" in text
    assert "semanticSearch: 'free'" in text
    assert "Microsoft.Communication/communicationServices" in text
    assert "'centralus'" in text
    params = json.loads((platform / "infra" / "main.parameters.json").read_text(encoding="utf-8"))
    assert params["parameters"]["location"]["value"] == "${AZURE_LOCATION=centralus}"


def test_examples_share_identical_access_module_and_env_contract(repo_root):
    modules = [
        (repo_root / "examples" / name / "infra" / "modules" / "shared-access.bicep").read_text(encoding="utf-8")
        for name in EXAMPLES
    ]
    assert all(module == modules[0] for module in modules)
    assert "1407120a-92aa-4202-b7e9-c0e197c71c8f" in modules[0]  # Search Index Data Reader
    assert "b24988ac-6180-42a0-ab88-20f7382dd24c" in modules[0]  # Contributor on ACS only

    python_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in (repo_root / "shared" / "voiceagent_core").rglob("*.py")
    )
    for name in EXAMPLES:
        infra = repo_root / "examples" / name / "infra"
        text = _bicep_text(infra)
        assert "if (!useSharedFoundry)" in text
        assert "module sharedAccess 'shared-access.bicep'" in text
        assert "secretRef: 'telephony-webhook-secret'" in text
        assert "@secure()" in text
        parameters = (infra / "main.parameters.json").read_text(encoding="utf-8")
        for key in ("SHARED_RESOURCE_GROUP", "SHARED_FOUNDRY_NAME", "AZURE_SEARCH_SERVICE_NAME", "ACS_RESOURCE_NAME"):
            assert key in parameters
        for env_name in APP_ENV_CONTRACT:
            assert f"'{env_name}'" in text, f"{name} Bicep does not set {env_name}"
            assert f'"{env_name}"' in python_sources, f"shared code does not read {env_name}"


def test_app_tier_region_is_independent_of_ai_region(repo_root):
    for name in EXAMPLES:
        infra = repo_root / "examples" / name / "infra"
        resources = (infra / "modules" / "resources.bicep").read_text(encoding="utf-8")
        main = (infra / "main.bicep").read_text(encoding="utf-8")
        parameters = (infra / "main.parameters.json").read_text(encoding="utf-8")

        assert "param appLocation string = location" in resources
        assert "appLocation: empty(appLocation) ? location : appLocation" in main
        assert "${AZURE_APP_LOCATION=}" in parameters
        # Only the Foundry account (and its project) stay pinned to the AI region; the app tier follows appLocation.
        ai_blocks = [b for b in ("resource foundry ", "resource project ") if b in resources]
        pinned = sum(resources.split(b, 1)[1].split("\nresource ", 1)[0].count("location: location") for b in ai_blocks)
        assert pinned >= 1 and resources.count("location: location") == pinned
        for resource in ("resource logs ", "resource managedEnvironment ", "resource acr ", "resource uami ", "resource web "):
            block = resources.split(resource, 1)[1].split("\nresource ", 1)[0]
            assert "location: appLocation" in block, f"{name}: {resource.strip()} should use appLocation"


def test_secrets_are_never_bicep_outputs(repo_root):
    for folder in [repo_root / "platform" / "infra"] + [repo_root / "examples" / n / "infra" for n in EXAMPLES]:
        for line in _bicep_text(folder).splitlines():
            if line.strip().startswith("output "):
                assert "Secret" not in line and "AuthToken" not in line
