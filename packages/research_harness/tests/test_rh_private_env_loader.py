from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = next(
    p
    for p in Path(__file__).resolve().parents
    if (p / "scripts" / "rh-env-keychain.sh").exists()
)


def _source_private_env(tmp_path: Path, content: str) -> dict[str, str]:
    private_env = tmp_path / "private.env"
    private_env.write_text(content)
    script = REPO_ROOT / "scripts" / "rh-env-keychain.sh"
    command = (
        f"RESEARCH_HARNESS_PRIVATE_ENV={private_env} "
        f"source {script} >/dev/null 2>&1; "
        "env"
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "S2_API_KEY",
            "SEMANTIC_SCHOLAR_API_KEY",
            "OPENALEX_API_KEY",
            "SCIVERSE_API_TOKEN",
            "MINERU_API_TOKEN",
            "FAL_KEY",
            "ZOTERO_API_KEY",
            "ZOTERO_LIBRARY_ID",
            "ZOTERO_LIBRARY_TYPE",
            "RESEARCH_HARNESS_FIGURE_GEMINI_MODEL",
            "RESEARCH_HARNESS_FIGURE_IMAGE_TIMEOUT_SECONDS",
            "GROK_API_KEY",
            "GPT_IMAGE_API_KEY",
        }
    }
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    result = subprocess.run(
        ["bash", "-lc", command],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return dict(
        line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
    )


def test_rh_env_keychain_loads_cross_platform_private_env(tmp_path: Path) -> None:
    loaded = _source_private_env(
        tmp_path,
        "\n".join(
            [
                "MINERU_API_TOKEN=mineru-test",
                'FAL_KEY="fal-test"',
                "RESEARCH_HARNESS_FIGURE_GEMINI_MODEL=gemini-2.5-flash-image",
                "RESEARCH_HARNESS_FIGURE_IMAGE_TIMEOUT_SECONDS=90",
                "GROK_API_KEY=grok-test",
                "GPT_IMAGE_API_KEY=gpt-image-test",
                "ZOTERO_LIBRARY_TYPE=user",
            ]
        ),
    )

    assert loaded["MINERU_API_TOKEN"] == "mineru-test"
    assert loaded["FAL_KEY"] == "fal-test"
    assert loaded["RESEARCH_HARNESS_FIGURE_GEMINI_MODEL"] == "gemini-2.5-flash-image"
    assert loaded["RESEARCH_HARNESS_FIGURE_IMAGE_TIMEOUT_SECONDS"] == "90"
    assert loaded["GROK_API_KEY"] == "grok-test"
    assert loaded["GPT_IMAGE_API_KEY"] == "gpt-image-test"
    assert loaded["ZOTERO_LIBRARY_TYPE"] == "user"
    assert loaded["OPENREVIEW_ENABLE"] == "1"


def test_rh_env_keychain_does_not_override_existing_env(tmp_path: Path) -> None:
    private_env = tmp_path / "private.env"
    private_env.write_text("S2_API_KEY=from-file\n")
    script = REPO_ROOT / "scripts" / "rh-env-keychain.sh"

    result = subprocess.run(
        [
            "bash",
            "-lc",
            (f"source {script} >/dev/null 2>&1; printf '%s' \"$S2_API_KEY\""),
        ],
        cwd=REPO_ROOT,
        env={
            "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
            "RESEARCH_HARNESS_PRIVATE_ENV": str(private_env),
            "S2_API_KEY": "from-process",
        },
        text=True,
        capture_output=True,
        check=True,
    )

    assert result.stdout == "from-process"


def test_private_env_example_contains_no_real_secret_material() -> None:
    example = REPO_ROOT / "config" / "private.env.example"
    text = example.read_text()

    assert "sk-" not in text
    assert "Bearer " not in text
    assert "39.96." not in text
    assert "http://" not in text
    assert "https://" not in text
