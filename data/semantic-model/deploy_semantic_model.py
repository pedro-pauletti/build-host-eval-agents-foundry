#!/usr/bin/env python3
"""
Deploy the Zava Direct Lake semantic model to Fabric via the Items definition API.

Reads the TMDL folder produced by build_tmdl.py, base64-encodes every part, and calls
createItemWithDefinition (POST .../semanticModels). Handles the 201 (inline) and 202 (LRO)
responses and prints the resulting semanticModelId.

Prereqs:
    $env:FABRIC_TOKEN = az account get-access-token --resource https://api.fabric.microsoft.com --query accessToken -o tsv
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time

import requests

WS = os.environ["FABRIC_WORKSPACE_ID"]
NAME = os.environ.get("SEMANTIC_MODEL_NAME", "ZavaSemanticModel")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ZavaSemanticModel")
TOKEN = os.environ["FABRIC_TOKEN"]
API = "https://api.fabric.microsoft.com/v1"
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

PART_FILES = [
    "definition.pbism",
    "definition/database.tmdl",
    "definition/model.tmdl",
    "definition/expressions.tmdl",
    "definition/relationships.tmdl",
]
PART_FILES += [f"definition/tables/{f}" for f in sorted(os.listdir(os.path.join(ROOT, "definition", "tables")))]


def b64(path: str) -> str:
    with open(os.path.join(ROOT, path), "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


def find_model_id() -> str | None:
    r = requests.get(f"{API}/workspaces/{WS}/semanticModels", headers=H)
    r.raise_for_status()
    for m in r.json().get("value", []):
        if m["displayName"] == NAME:
            return m["id"]
    return None


def poll_lro(resp: requests.Response) -> None:
    op = resp.headers.get("Location") or f"{API}/operations/{resp.headers.get('x-ms-operation-id')}"
    for _ in range(120):
        time.sleep(resp.headers.get("Retry-After") and int(resp.headers["Retry-After"]) or 3)
        s = requests.get(op, headers=H)
        state = s.json().get("status") if s.headers.get("Content-Type", "").startswith("application/json") else None
        if s.status_code in (200, 201) and state in ("Succeeded", "Completed", None):
            print(f"  LRO {state or s.status_code}")
            return
        if state == "Failed":
            print("  LRO FAILED:", s.text)
            sys.exit(1)
        print(f"  LRO {state}...")


def main():
    existing = find_model_id()
    if existing:
        print(f"Deleting existing '{NAME}' {existing}")
        d = requests.delete(f"{API}/workspaces/{WS}/semanticModels/{existing}", headers=H)
        print("  delete status", d.status_code)
        time.sleep(3)

    parts = [{"path": p, "payload": b64(p), "payloadType": "InlineBase64"} for p in PART_FILES]
    body = {"displayName": NAME,
            "description": "Zava Direct Lake star-schema model over ZavaLakehouse for the Fabric Data Agent.",
            "definition": {"format": "TMDL", "parts": parts}}
    print(f"Creating '{NAME}' with {len(parts)} parts...")
    r = requests.post(f"{API}/workspaces/{WS}/semanticModels", headers=H, data=json.dumps(body))
    print("  POST status", r.status_code)
    if r.status_code == 202:
        poll_lro(r)
    elif r.status_code not in (200, 201):
        print("  ERROR:", r.text)
        sys.exit(1)

    mid = find_model_id()
    print(f"SEMANTIC_MODEL_ID={mid}")


if __name__ == "__main__":
    main()
