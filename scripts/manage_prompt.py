"""Quản lý prompt `day13-chat` trên project Langfuse cá nhân: tạo v1/v2, promote và rollback.

    python scripts/manage_prompt.py status
    python scripts/manage_prompt.py init
    python scripts/manage_prompt.py promote --version 2
    python scripts/manage_prompt.py promote --version 1   # rollback production về v1
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio

# v1 giữ nguyên template local; v2 chỉ đổi nhỏ về format/độ dài câu trả lời.
PROMPT_V1 = "Feature={{feature}}\nDocs={{docs}}\nQuestion={{message}}"
PROMPT_V2 = (
    "Feature={{feature}}\n"
    "Docs={{docs}}\n"
    "Question={{message}}\n"
    "Answer in at most 3 short bullet points, using only the docs above."
)
VERSIONS = [
    (PROMPT_V1, ["baseline", "production"], "v1: baseline template"),
    (PROMPT_V2, ["candidate"], "v2: concise bullet-point answer"),
]


def get_client():
    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        sys.exit("Thiếu LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY trong .env")
    from langfuse import get_client as langfuse_client

    return langfuse_client()


def existing_versions(client, name: str) -> list[int]:
    listing = client.api.prompts.list(name=name)
    return sorted(v for meta in listing.data if meta.name == name for v in meta.versions)


def print_status(client, name: str) -> None:
    versions = existing_versions(client, name)
    if not versions:
        print(f"Prompt '{name}' chưa có version nào.")
        return
    print(f"Prompt '{name}':")
    for version in versions:
        prompt = client.get_prompt(name, version=version, type="text", cache_ttl_seconds=0)
        labels = ", ".join(sorted(prompt.labels)) or "-"
        last_line = prompt.prompt.splitlines()[-1]
        print(f"  v{version}: labels=[{labels}]  last line: {last_line!r}")


def init(client, name: str) -> None:
    if existing_versions(client, name):
        print(f"Prompt '{name}' đã tồn tại, không tạo thêm version.")
        return
    for text, labels, message in VERSIONS:
        created = client.create_prompt(
            name=name, prompt=text, labels=labels, type="text", commit_message=message
        )
        print(f"Tạo v{created.version} với labels {labels}")


def promote(client, name: str, version: int, label: str) -> None:
    current = client.get_prompt(name, version=version, type="text", cache_ttl_seconds=0)
    # "latest" is managed by Langfuse and cannot be assigned manually.
    labels = sorted((set(current.labels) - {"latest"}) | {label})
    client.update_prompt(name=name, version=version, new_labels=labels)
    print(f"Gắn label '{label}' cho v{version} (Langfuse tự gỡ label này khỏi version cũ)")


def main() -> None:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["status", "init", "promote"])
    parser.add_argument("--version", type=int, help="Version cần gắn label (promote)")
    parser.add_argument("--label", default="production")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    name = os.getenv("LANGFUSE_PROMPT_NAME", "day13-chat")
    client = get_client()
    if args.command == "init":
        init(client, name)
    elif args.command == "promote":
        if args.version is None:
            parser.error("promote cần --version")
        promote(client, name, args.version, args.label)
    print_status(client, name)


if __name__ == "__main__":
    main()
