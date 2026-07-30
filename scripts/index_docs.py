#!/usr/bin/env python3
"""
Index the Zava knowledge-base documents (data/docs/*.md) into Azure AI Search with
vector + semantic + keyword search, and an integrated Azure OpenAI vectorizer so the
Foundry IQ / Azure AI Search agent tool can run vector_semantic_hybrid queries.

Auth: DefaultAzureCredential for Search (your user has Search Index Data Contributor +
Search Service Contributor). Embeddings use the Foundry account key (fetched via az).

Run (from repo root, with the venv):
    .venv\\Scripts\\python.exe scripts/index_docs.py
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex, SimpleField, SearchableField, SearchField, SearchFieldDataType,
    VectorSearch, HnswAlgorithmConfiguration, VectorSearchProfile,
    AzureOpenAIVectorizer, AzureOpenAIVectorizerParameters,
    SemanticSearch, SemanticConfiguration, SemanticPrioritizedFields, SemanticField,
)
from openai import AzureOpenAI

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(REPO, "data", "docs")
load_dotenv(os.path.join(REPO, ".env"))

SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
INDEX_NAME = os.environ.get("AZURE_SEARCH_INDEX_NAME", "zava-docs")
ACCOUNT_ENDPOINT = os.environ["AZURE_AI_ACCOUNT_ENDPOINT"]
ACCOUNT_NAME = os.environ["AZURE_AI_ACCOUNT_NAME"]
RG = os.environ.get("AZURE_RESOURCE_GROUP", "rg-zava-demo")
EMBED_DEPLOYMENT = os.environ.get("EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-large")
EMBED_MODEL = "text-embedding-3-large"
EMBED_DIM = 3072

VECTORIZER_NAME = "zava-openai-vectorizer"
PROFILE_NAME = "zava-vector-profile"
ALGO_NAME = "zava-hnsw"
SEMANTIC_NAME = "zava-semantic"


def get_account_key() -> str:
    out = subprocess.run(
        f"az cognitiveservices account keys list -g {RG} -n {ACCOUNT_NAME} --query key1 -o tsv",
        shell=True, capture_output=True, text=True,
    )
    key = out.stdout.strip()
    if not key:
        sys.exit(f"Could not fetch account key: {out.stderr}")
    return key


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "section"


def chunk_markdown(path: str):
    """Split a doc into (title, section, content) chunks by ## headings, dropping the
    trailing metadata block. Long sections are split further by paragraphs."""
    raw = open(path, encoding="utf-8").read()
    raw = re.split(r"\n---\s*\n\*\*Document metadata\*\*", raw)[0]
    m = re.search(r"^#\s+(.+)$", raw, re.MULTILINE)
    title = m.group(1).strip() if m else os.path.basename(path)
    # remove the H1 title line
    body = raw[m.end():] if m else raw
    parts = re.split(r"\n(?=##\s+)", body)
    chunks = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        hm = re.match(r"##\s+(.+)", part)
        section = hm.group(1).strip() if hm else "Overview"
        text = part[hm.end():].strip() if hm else part
        text = f"{section}\n\n{text}".strip()
        # split long sections (~1500 chars) on blank lines
        if len(text) <= 1600:
            chunks.append((title, section, text))
        else:
            buf = ""
            for para in text.split("\n\n"):
                if len(buf) + len(para) > 1400 and buf:
                    chunks.append((title, section, buf.strip()))
                    buf = ""
                buf += para + "\n\n"
            if buf.strip():
                chunks.append((title, section, buf.strip()))
    return title, chunks


def build_documents(embed_client: AzureOpenAI):
    docs = []
    files = sorted(glob.glob(os.path.join(DOCS_DIR, "*.md")))
    files = [f for f in files if os.path.basename(f).lower() != "readme.md"]
    to_embed, meta = [], []
    for path in files:
        fname = os.path.splitext(os.path.basename(path))[0]
        title, chunks = chunk_markdown(path)
        for i, (t, section, content) in enumerate(chunks):
            meta.append({
                "id": f"{slug(fname)}--{i:02d}",
                "doc_id": fname,
                "title": t,
                "section": section,
                "category": fname.split("-")[0],
                "url": f"https://docs.zava.example/{fname}#{slug(section)}",
                "content": content,
            })
            to_embed.append(content)
    # embed in batches
    print(f"Embedding {len(to_embed)} chunks from {len(files)} documents ...")
    vectors = []
    for i in range(0, len(to_embed), 64):
        batch = to_embed[i:i + 64]
        resp = embed_client.embeddings.create(model=EMBED_DEPLOYMENT, input=batch)
        vectors.extend([d.embedding for d in resp.data])
    for d, v in zip(meta, vectors):
        d["content_vector"] = v
        docs.append(d)
    return docs


def build_index() -> SearchIndex:
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SimpleField(name="doc_id", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SearchableField(name="title", type=SearchFieldDataType.String),
        SearchableField(name="section", type=SearchFieldDataType.String),
        SimpleField(name="category", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="url", type=SearchFieldDataType.String),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True, vector_search_dimensions=EMBED_DIM,
            vector_search_profile_name=PROFILE_NAME,
        ),
    ]
    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name=ALGO_NAME)],
        profiles=[VectorSearchProfile(
            name=PROFILE_NAME,
            algorithm_configuration_name=ALGO_NAME,
            vectorizer_name=VECTORIZER_NAME,
        )],
        vectorizers=[AzureOpenAIVectorizer(
            vectorizer_name=VECTORIZER_NAME,
            parameters=AzureOpenAIVectorizerParameters(
                resource_url=ACCOUNT_ENDPOINT,
                deployment_name=EMBED_DEPLOYMENT,
                model_name=EMBED_MODEL,
            ),
        )],
    )
    semantic = SemanticSearch(configurations=[SemanticConfiguration(
        name=SEMANTIC_NAME,
        prioritized_fields=SemanticPrioritizedFields(
            title_field=SemanticField(field_name="title"),
            content_fields=[SemanticField(field_name="content")],
            keywords_fields=[SemanticField(field_name="section")],
        ),
    )])
    return SearchIndex(name=INDEX_NAME, fields=fields,
                       vector_search=vector_search, semantic_search=semantic)


def main():
    cred = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(cred, "https://cognitiveservices.azure.com/.default")
    embed_client = AzureOpenAI(azure_endpoint=ACCOUNT_ENDPOINT,
                               azure_ad_token_provider=token_provider,
                               api_version="2024-10-21")

    index = build_index()
    idx_client = SearchIndexClient(endpoint=SEARCH_ENDPOINT, credential=cred)
    idx_client.create_or_update_index(index)
    print(f"Index '{INDEX_NAME}' created/updated on {SEARCH_ENDPOINT}")

    docs = build_documents(embed_client)
    client = SearchClient(endpoint=SEARCH_ENDPOINT, index_name=INDEX_NAME, credential=cred)
    result = client.upload_documents(documents=docs)
    ok = sum(1 for r in result if r.succeeded)
    print(f"Uploaded {ok}/{len(docs)} chunks to index '{INDEX_NAME}'.")


if __name__ == "__main__":
    main()
