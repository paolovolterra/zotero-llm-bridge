#!/usr/bin/env python3
"""ZoteroLLMBridge: model-independent access to Zotero's local API."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlparse
from urllib.request import Request, urlopen, url2pathname
from uuid import uuid4

BASE = "http://localhost:23119/api"
def default_auth_file():
    override = os.environ.get("ZOTERO_LLM_BRIDGE_AUTH_FILE") or os.environ.get("ZZOTERO_AUTH_FILE")
    if override:
        return Path(override).expanduser()
    shared_cache = Path(__file__).resolve().parent.parent / ".zotero-local-auth.json"
    if shared_cache.exists():
        return shared_cache
    if os.name == "nt":
        config_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        config_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_dir / "zotero_llm_bridge" / "auth.json"


AUTH_FILE = default_auth_file()
INDEX_FILE = AUTH_FILE.with_name(".zlb-attachment-index.json")
KEY_RE = re.compile(r"^[A-Z0-9]{8}$")


class ZoteroError(RuntimeError):
    pass


class Zotero:
    def __init__(self, base: str = BASE, auth_file: Path = AUTH_FILE):
        parsed = urlparse(base)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"} or parsed.port != 23119:
            raise ZoteroError("The local API must be http://localhost:23119/api")
        self.base = base.rstrip("/")
        self.auth_file = auth_file
        self._auth: dict | None = None
        self.server_id: str | None = None

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        url = self.base + path
        request = Request(url, data=body, method=method, headers={"Accept": "application/json", **(headers or {})})
        try:
            with urlopen(request, timeout=120) as response:
                raw = response.read()
                media = response.headers.get("Content-Type", "")
                payload = json.loads(raw) if raw and "json" in media else (raw.decode("utf-8", "replace") if raw else None)
                return response.status, dict(response.headers), payload
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise ZoteroError(f"Zotero API {method} {path}: HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise ZoteroError(f"Zotero local API unavailable: {exc.reason}") from exc

    def get(self, path: str):
        return self.request("GET", path)[2]

    def connect(self):
        _, headers, _ = self.request("GET", "/")
        self.server_id = headers.get("Zotero-Server-ID")
        if not self.server_id:
            raise ZoteroError("Zotero 10 local write API is unavailable")
        return headers

    def _cached_key(self):
        if not self.auth_file.exists():
            return None
        if os.name != "nt" and self.auth_file.stat().st_mode & 0o077:
            raise ZoteroError(f"Unsafe permissions on {self.auth_file}; expected 0600")
        data = json.loads(self.auth_file.read_text())
        return data.get("key") if data.get("server_id") == self.server_id else None

    def _save_key(self, key: str):
        self.auth_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.auth_file.with_name(self.auth_file.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w") as output:
                json.dump({"server_id": self.server_id, "key": key}, output)
            os.replace(tmp, self.auth_file)
        finally:
            if tmp.exists():
                tmp.unlink()

    def _key(self):
        if self.server_id is None:
            self.connect()
        if self._auth is None:
            cached = self._cached_key()
            if cached:
                self._auth = {"key": cached, "remember": True}
            else:
                body = json.dumps({"appName": "ZoteroLLMBridge"}).encode()
                result = self.request("POST", "/local/authorize", body, {"Content-Type": "application/json", "Zotero-Server-ID": self.server_id})[2]
                self._auth = result
                if result.get("remember"):
                    self._save_key(result["key"])
        return self._auth["key"]

    def post(self, path: str, body: bytes, content_type: str, extra: dict | None = None):
        for attempt in range(2):
            key = self._key()
            try:
                result = self.request("POST", path, body, {"Content-Type": content_type, "Zotero-Server-ID": self.server_id, "Zotero-API-Key": key, **(extra or {})})[2]
                if not self._auth.get("remember"):
                    self._auth = None
                return result
            except ZoteroError as exc:
                if "HTTP 401:" not in str(exc) or attempt:
                    raise
                self._auth = None
                if self.auth_file.exists():
                    self.auth_file.unlink()
        raise ZoteroError("Zotero authorization failed")

    def resolve_collection(self, value: str):
        if KEY_RE.fullmatch(value):
            try:
                return self.get(f"/users/0/collections/{value}")
            except ZoteroError as exc:
                if "HTTP 404:" not in str(exc):
                    raise
        matches = [x for x in self.get("/users/0/collections") if x["data"]["name"] == value]
        if len(matches) != 1:
            raise ZoteroError(f"Collection {value!r}: expected one exact match, found {len(matches)}; use its key8")
        return matches[0]

    def ensure_collection(self, name: str, parent: str | None):
        parent_key = self.resolve_collection(parent)["key"] if parent else False
        endpoint = f"/users/0/collections/{parent_key}/collections" if parent_key else "/users/0/collections/top"
        matches = [x for x in self.get(endpoint) if x["data"]["name"] == name]
        if len(matches) > 1:
            raise ZoteroError(f"Multiple collections named {name!r} under the same parent")
        if matches:
            return matches[0]["key"], False
        body = json.dumps([{"name": name, "parentCollection": parent_key}]).encode()
        result = self.post("/users/0/collections", body, "application/json", {"Zotero-Write-Token": uuid4().hex})
        if result.get("failed") or len(result.get("success", {})) != 1:
            raise ZoteroError(f"Collection creation failed: {result}")
        key = result["success"]["0"]
        if self.get(f"/users/0/collections/{key}")["data"]["name"] != name:
            raise ZoteroError("Collection verification failed")
        return key, True

    def item(self, key: str):
        if not KEY_RE.fullmatch(key):
            raise ZoteroError(f"Invalid item key: {key}")
        return self.get(f"/users/0/items/{key}")

    def canonical_item(self, key: str):
        item = self.item(key)
        parent = item["data"].get("parentItem")
        return self.item(parent) if parent else item

    def change_membership(self, keys: list[str], target: str, source: str | None = None):
        target_key = self.resolve_collection(target)["key"]
        source_key = self.resolve_collection(source)["key"] if source else None
        items = {}
        for key in keys:
            item = self.canonical_item(key)
            items[item["key"]] = item
        updates = []
        for key, item in items.items():
            data = item["data"]
            memberships = list(data.get("collections", []))
            if source_key and source_key not in memberships:
                if target_key in memberships:
                    continue
                raise ZoteroError(f"Item {key} is not in source collection {source_key}")
            if source_key:
                memberships.remove(source_key)
            if target_key not in memberships:
                memberships.append(target_key)
            if memberships != data.get("collections", []):
                updates.append({"key": key, "version": data["version"], "collections": memberships})
        if updates:
            result = self.post("/users/0/items", json.dumps(updates).encode(), "application/json")
            if result.get("failed") or len(result.get("success", {})) != len(updates):
                raise ZoteroError(f"Membership update failed: {result}")
        for key in items:
            memberships = self.item(key)["data"].get("collections", [])
            if target_key not in memberships or (source_key and source_key in memberships):
                raise ZoteroError(f"Membership verification failed for {key}")
        return {"collection": target_key, "items": list(items), "changed": len(updates)}

    def collection_items(self, collection_key: str):
        return self.get(f"/users/0/collections/{collection_key}/items?limit=1000")

    def search_items(self, collection: str | None = None, tags: list[str] | None = None,
                     query: str | None = None, qmode: str = "titleCreatorYear",
                     item_type: str | None = None, top: bool = False,
                     limit: int = 25, start: int = 0):
        if not any([collection, tags, query, item_type]):
            raise ZoteroError("Specify at least one of --collection, --tag, --q or --item-type")
        if not 1 <= limit <= 100 or start < 0:
            raise ZoteroError("--limit must be 1–100 and --start must be non-negative")
        collection_key = self.resolve_collection(collection)["key"] if collection else None
        path = f"/users/0/collections/{collection_key}/items" if collection_key else "/users/0/items"
        if top:
            path += "/top"
        params = [("limit", str(limit)), ("start", str(start))]
        if query:
            params.extend([("q", query), ("qmode", qmode)])
        if item_type:
            params.append(("itemType", item_type))
        params.extend(("tag", tag) for tag in (tags or []))
        _, headers, items = self.request("GET", path + "?" + urlencode(params))
        return {
            "collection": collection_key,
            "total": int(headers["Total-Results"]) if headers.get("Total-Results") else None,
            "start": start,
            "limit": limit,
            "items": [
                {
                    "key8": item["key"],
                    "item_type": item["data"].get("itemType"),
                    "title": item["data"].get("title"),
                    "date": item["data"].get("date"),
                    "doi": item["data"].get("DOI"),
                    "tags": [tag["tag"] for tag in item["data"].get("tags", [])],
                    "collections": item["data"].get("collections", []),
                    "parent_item": item["data"].get("parentItem"),
                }
                for item in items
            ],
        }

    def search_library(self, ref: dict):
        candidates = {}
        for query in filter(None, [ref.get("doi"), ref.get("title")]):
            path = f"/users/0/items/top?qmode=everything&q={quote(query)}&limit=100"
            for item in self.get(path):
                candidates[item["key"]] = item
            if match_reference(self, ref, list(candidates.values())):
                break
        return list(candidates.values())

    def pdf_children(self, item):
        if item["data"]["itemType"] == "attachment":
            return [item] if item["data"].get("contentType") == "application/pdf" else []
        return [x for x in self.get(f"/users/0/items/{item['key']}/children") if x["data"].get("contentType") == "application/pdf"]

    def _pdf_hash_index(self):
        if self.server_id is None:
            self.connect()
        try:
            cache = json.loads(INDEX_FILE.read_text())
            if cache.get("server_id") != self.server_id or not isinstance(cache.get("hashes"), dict):
                cache = None
        except (OSError, ValueError):
            cache = None

        _, headers, _ = self.request("GET", "/users/0/items?itemType=attachment&limit=1")
        current_version = int(headers["Last-Modified-Version"])
        if cache and cache.get("version") == current_version:
            return cache["hashes"]

        hashes = cache["hashes"] if cache and cache.get("version", -1) < current_version else {}
        initial_version = cache["version"] if cache and hashes else current_version
        if not hashes:
            start = 0
            while True:
                path = "/users/0/items?" + urlencode({"itemType": "attachment", "limit": 1000, "start": start, "sort": "dateAdded", "direction": "asc"})
                _, page_headers, page = self.request("GET", path)
                self._index_pdf_page(hashes, page)
                start += len(page)
                total = int(page_headers["Total-Results"])
                if start >= total:
                    break
                if not page:
                    raise ZoteroError("Attachment scan stopped before the last page")
                if start % 10000 == 0:
                    print(f"zlb: indexed {start}/{total} attachments", file=sys.stderr)

        # Catch additions or replacements made during the scan, then verify that
        # the library version stayed stable before trusting the index.
        version = initial_version
        for _ in range(3):
            start = 0
            while True:
                path = "/users/0/items?" + urlencode({"itemType": "attachment", "since": version, "limit": 1000, "start": start})
                _, page_headers, page = self.request("GET", path)
                self._index_pdf_page(hashes, page)
                start += len(page)
                if start >= int(page_headers["Total-Results"]):
                    break
                if not page:
                    raise ZoteroError("Attachment update scan stopped before the last page")
            seen_version = int(page_headers["Last-Modified-Version"])
            _, check_headers, _ = self.request("GET", "/users/0/items?itemType=attachment&limit=1")
            if seen_version == int(check_headers["Last-Modified-Version"]):
                cache = {"server_id": self.server_id, "version": seen_version, "hashes": hashes}
                INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
                tmp = INDEX_FILE.with_name(INDEX_FILE.name + ".tmp")
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as output:
                    json.dump(cache, output)
                os.replace(tmp, INDEX_FILE)
                return hashes
            version = seen_version
        raise ZoteroError("Zotero library changed repeatedly during duplicate check; upload cancelled")

    @staticmethod
    def _index_pdf_page(hashes, page):
        for item in page:
            data = item["data"]
            if data.get("contentType") != "application/pdf" or not data.get("md5"):
                continue
            md5 = data["md5"].lower()
            keys = hashes.setdefault(md5, [])
            if item["key"] not in keys:
                keys.append(item["key"])

    def find_pdf_by_md5(self, collection_key: str, md5: str, sha256: str, parent_key: str | None = None):
        matches = []
        for key in self._pdf_hash_index().get(md5.lower(), []):
            try:
                attachment = self.item(key)
                if (attachment["data"].get("md5") or "").lower() != md5.lower():
                    continue
                stored = attachment_path(attachment)
                if not stored or hashlib.sha256(stored.read_bytes()).hexdigest() != sha256:
                    continue
                item = self.canonical_item(key)
                matches.append((item, attachment))
            except ZoteroError:
                continue
        if parent_key:
            for item, attachment in matches:
                if item["key"] == parent_key:
                    return item, attachment
        for item, attachment in matches:
            if collection_key in item["data"].get("collections", []):
                return item, attachment
        return matches[0] if matches else None

    def upload_pdf(self, path: Path, collection: str, title: str | None = None, tags: list[str] | None = None, parent_key: str | None = None):
        collection_key = self.resolve_collection(collection)["key"]
        path = path.resolve()
        if not path.is_file() or path.suffix.lower() != ".pdf":
            raise ZoteroError(f"Expected an existing PDF file: {path}")
        if path.stat().st_size > 100_000_000:
            raise ZoteroError("PDF exceeds ZoteroLLMBridge's 100 MB in-memory upload limit")
        data = path.read_bytes()
        if not data.startswith(b"%PDF-"):
            raise ZoteroError(f"File is not a PDF: {path}")
        md5 = hashlib.md5(data).hexdigest()
        sha256 = hashlib.sha256(data).hexdigest()
        parent = self.canonical_item(parent_key) if parent_key else None
        duplicate = self.find_pdf_by_md5(collection_key, md5, sha256, parent["key"] if parent else None)
        if duplicate:
            existing_item, attachment = duplicate
            if parent and existing_item["key"] != parent["key"]:
                raise ZoteroError(f"Identical PDF already exists under item {existing_item['key']}; requested parent is {parent['key']}")
            added = collection_key not in existing_item["data"].get("collections", [])
            if added:
                self.change_membership([existing_item["key"]], collection_key)
            return {"status": "added_existing_pdf" if added else "already_present", "collection": collection_key, "item_key": existing_item["key"], "attachment_key": attachment["key"], "file": str(attachment_path(attachment)), "sha256": sha256}
        if parent:
            self.change_membership([parent["key"]], collection_key)
        item = {"itemType": "attachment", "linkMode": "imported_file", "title": title or path.name, "contentType": "application/pdf", "filename": path.name, "tags": [{"tag": tag} for tag in (tags or [])]}
        if parent:
            item["parentItem"] = parent["key"]
        else:
            item["collections"] = [collection_key]
        created = self.post("/users/0/items", json.dumps([item]).encode(), "application/json", {"Zotero-Write-Token": uuid4().hex})
        if created.get("failed") or len(created.get("success", {})) != 1:
            raise ZoteroError(f"Attachment creation failed: {created}")
        key = created["success"]["0"]
        try:
            stat = path.stat()
            form = urlencode({"md5": md5, "filename": path.name, "filesize": len(data), "mtime": int(stat.st_mtime * 1000)}).encode()
            first = self.post(f"/users/0/items/{key}/file", form, "application/x-www-form-urlencoded", {"If-None-Match": "*"})
            if not first.get("exists"):
                upload_url = first["url"]
                parsed = urlparse(upload_url)
                if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"} or parsed.port != 23119:
                    raise ZoteroError(f"Unexpected upload destination: {parsed.netloc}")
                payload = first["prefix"].encode() + data + first["suffix"].encode()
                with urlopen(Request(upload_url, data=payload, method="POST", headers={"Content-Type": first["contentType"]}), timeout=120) as response:
                    if response.status != 201:
                        raise ZoteroError(f"PDF transfer returned HTTP {response.status}")
                commit = urlencode({"upload": first["uploadKey"]}).encode()
                self.post(f"/users/0/items/{key}/file", commit, "application/x-www-form-urlencoded", {"If-None-Match": "*"})
            attachment = self.item(key)
            stored = attachment_path(attachment)
            if not stored or hashlib.sha256(stored.read_bytes()).hexdigest() != sha256:
                raise ZoteroError("Stored PDF does not match the source")
            current = self.canonical_item(key)
            if collection_key not in current["data"].get("collections", []):
                raise ZoteroError("Imported PDF is not in the requested collection")
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
                raise ZoteroError("Source PDF changed during import")
            return {"status": "imported", "collection": collection_key, "item_key": current["key"], "attachment_key": key, "file": str(stored), "sha256": sha256}
        except Exception as exc:
            raise ZoteroError(f"Attachment {key} was created but PDF upload or verification failed: {exc}") from exc


def attachment_path(item):
    url = ((item.get("links") or {}).get("enclosure") or {}).get("href")
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "file":
        raise ZoteroError(f"Unexpected Zotero attachment URL: {url}")
    path = Path(url2pathname(unquote(parsed.path)))
    if not path.is_file():
        raise ZoteroError(f"Missing Zotero attachment file: {path}")
    return path


def normalize(value: str):
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def read_manifest(path: Path):
    manifest = json.loads(path.read_text())
    refs = manifest.get("references")
    if not isinstance(refs, list) or not refs:
        raise ZoteroError("Manifest must contain a non-empty references array")
    ids = [str(ref.get("id", "")) for ref in refs]
    if len(ids) != len(set(ids)) or any(not x for x in ids):
        raise ZoteroError("Each reference needs a unique non-empty id")
    for ref in refs:
        if not ref.get("title"):
            raise ZoteroError(f"Reference {ref.get('id')}: missing title")
    return manifest


def match_reference(api: Zotero, ref: dict, items: list):
    if ref.get("zotero_key"):
        return api.canonical_item(ref["zotero_key"])
    doi = (ref.get("doi") or "").lower().removeprefix("https://doi.org/")
    matches = [item for item in items if doi and (item["data"].get("DOI") or "").lower() == doi]
    if not matches:
        matches = [item for item in items if normalize(item["data"].get("title") or "") == normalize(ref["title"])]
    parents = [item for item in matches if item["data"]["itemType"] != "attachment"]
    matches = parents or matches
    unique = {item["key"]: item for item in matches}
    if len(unique) > 1:
        raise ZoteroError(f"Reference {ref['id']}: multiple matches in collection; set zotero_key explicitly")
    return next(iter(unique.values())) if unique else None


def bib_escape(value):
    return str(value).replace("\\", "\\textbackslash{} ").replace("{", "\\{").replace("}", "\\}").replace("%", "\\%").replace("&", "\\&")


def bib_entry(ref: dict, item, pdf):
    key = ref.get("citekey") or f"ref{ref['id']}"
    if not re.fullmatch(r"[A-Za-z0-9_:-]+", key):
        raise ZoteroError(f"Invalid BibTeX key: {key}")
    kind = ref.get("type") or "misc"
    if kind not in {"article", "book", "inbook", "incollection", "inproceedings", "misc", "techreport", "phdthesis", "mastersthesis", "unpublished"}:
        raise ZoteroError(f"Unsupported BibTeX type: {kind}")
    data = item["data"] if item else {}
    fields = {}
    for name in ("author", "title", "year", "journal", "booktitle", "publisher", "institution", "volume", "number", "pages", "doi", "url", "note"):
        value = ref.get(name)
        if value:
            fields[name] = value
    fields.setdefault("title", data.get("title") or ref["title"])
    if not fields.get("author") and data.get("creators"):
        names = []
        for creator in data["creators"]:
            name = creator.get("name") or " ".join(filter(None, [creator.get("firstName"), creator.get("lastName")]))
            if name:
                names.append(name)
        if names:
            fields["author"] = " and ".join(names)
    if not fields.get("year") and data.get("date"):
        year = re.search(r"\b(?:19|20)\d{2}\b", data["date"])
        if year:
            fields["year"] = year.group()
    if not fields.get("doi") and data.get("DOI"):
        fields["doi"] = data["DOI"]
    if not fields.get("url") and fields.get("doi"):
        fields["url"] = "https://doi.org/" + fields["doi"]
    if pdf:
        fields["key8"] = item["key"]
        fields["file"] = str(attachment_path(pdf))
        fields["origin"] = "Zotero"
    lines = [f"@{kind}{{{key},"]
    for name, value in fields.items():
        lines.append(f"  {name:<11} = {{{bib_escape(value)}}},")
    lines.append("}")
    return "\n".join(lines)


def build_bib(api: Zotero, manifest: dict, collection: str, output: Path):
    collection_key = api.resolve_collection(collection)["key"]
    items = api.collection_items(collection_key)
    present, missing = [], []
    for ref in manifest["references"]:
        item = match_reference(api, ref, items)
        if item and collection_key not in item["data"].get("collections", []):
            raise ZoteroError(f"Reference {ref['id']}: item {item['key']} is outside collection {collection_key}")
        pdfs = api.pdf_children(item) if item else []
        pdfs = [pdf for pdf in pdfs if attachment_path(pdf)]
        (present if pdfs else missing).append((ref, item, pdfs[0] if pdfs else None))
    source = manifest.get("source", {})
    header = f"% References for {source.get('title', 'source document')}\n% Collection {collection_key}; missing PDFs first.\n"
    text = [header, f"% Missing PDFs ({len(missing)})\n"]
    text.extend(bib_entry(*row) + "\n" for row in missing)
    text.append(f"% PDFs in Zotero ({len(present)})\n")
    text.extend(bib_entry(*row) + "\n" for row in present)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    tmp.write_text("\n".join(text))
    os.replace(tmp, output)
    return {"output": str(output), "collection": collection_key, "total": len(manifest["references"]), "with_pdf": len(present), "missing": [str(row[0]["id"]) for row in missing]}


def apply_references(api: Zotero, path: Path, collection: str, output: Path | None):
    manifest = read_manifest(path)
    collection_key = api.resolve_collection(collection)["key"]
    items = api.collection_items(collection_key)
    results = []
    for ref in manifest["references"]:
        item = match_reference(api, ref, items)
        if not item:
            item = match_reference(api, ref, api.search_library(ref))
        if item and api.pdf_children(item):
            added = collection_key not in item["data"].get("collections", [])
            if added:
                api.change_membership([item["key"]], collection_key)
            ref["zotero_key"] = item["key"]
            results.append({"id": ref["id"], "status": "added" if added else "present", "key8": item["key"]})
            continue
        if ref.get("zotero_key"):
            api.change_membership([ref["zotero_key"]], collection_key)
            item = api.canonical_item(ref["zotero_key"])
            if api.pdf_children(item):
                ref["zotero_key"] = item["key"]
                results.append({"id": ref["id"], "status": "added", "key8": item["key"]})
                continue
        source = ref.get("pdf_path") or ref.get("pdf_url")
        if not source:
            results.append({"id": ref["id"], "status": "missing"})
            continue
        try:
            if ref.get("pdf_path"):
                file_path = Path(ref["pdf_path"])
                imported = api.upload_pdf(file_path, collection_key, ref["title"], parent_key=item["key"] if item else None)
            else:
                parsed = urlparse(source)
                if parsed.scheme != "https" or not parsed.hostname:
                    raise ZoteroError("pdf_url must be an HTTPS URL")
                request = Request(source, headers={"User-Agent": "ZoteroLLMBridge/1.0"})
                with urlopen(request, timeout=90) as response:
                    data = response.read(100_000_001)
                if len(data) > 100_000_000 or not data.startswith(b"%PDF-"):
                    raise ZoteroError("Download is not a PDF under 100 MB")
                with tempfile.TemporaryDirectory(prefix="zotero_llm_bridge_") as tmp_dir:
                    safe_id = re.sub(r"[^A-Za-z0-9_-]+", "_", str(ref["id"]))[:80] or "reference"
                    downloaded = Path(tmp_dir) / f"{safe_id}.pdf"
                    downloaded.write_bytes(data)
                    imported = api.upload_pdf(downloaded, collection_key, ref["title"], parent_key=item["key"] if item else None)
            ref["zotero_key"] = imported["item_key"]
            results.append({"id": ref["id"], "status": imported["status"], "key8": imported["item_key"]})
            # Persist after each successful write so an interrupted run can resume.
            tmp_manifest = path.with_name(path.name + ".tmp")
            tmp_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            os.replace(tmp_manifest, path)
            items = api.collection_items(collection_key)
        except Exception as exc:
            results.append({"id": ref["id"], "status": "error", "detail": str(exc)})
    report = {"collection": collection_key, "results": results}
    if output:
        report["bib"] = build_bib(api, manifest, collection_key, output)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog="zlb", description="Zotero 10 local API CLI. Writes never edit SQLite directly.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Check Zotero local API and authorization cache")
    collections = sub.add_parser("collections", help="List Zotero collections")
    collections.add_argument("--parent", help="Filter to children of collection key or exact name")
    search = sub.add_parser("search", help="Search library items by collection, tag, text or item type")
    search.add_argument("--collection", help="Collection key or exact name")
    search.add_argument("--tag", action="append", default=[], help="Exact tag; repeat for AND")
    search.add_argument("--q", help="Quicksearch text")
    search.add_argument("--qmode", choices=("titleCreatorYear", "everything"), default="titleCreatorYear")
    search.add_argument("--item-type", help="Zotero item type, e.g. journalArticle or attachment")
    search.add_argument("--top", action="store_true", help="Only top-level items")
    search.add_argument("--limit", type=int, default=25, help="Results per page, 1–100")
    search.add_argument("--start", type=int, default=0, help="Zero-based result offset")
    ensure = sub.add_parser("ensure-collection", help="Create or reuse a collection")
    ensure.add_argument("--name", required=True)
    ensure.add_argument("--parent", help="Parent collection key or exact name")
    add = sub.add_parser("add", help="Add existing items to a collection without removing other memberships")
    add.add_argument("--collection", required=True)
    add.add_argument("items", nargs="+")
    move = sub.add_parser("move", help="Move items from one collection to another")
    move.add_argument("--source", required=True)
    move.add_argument("--target", required=True)
    move.add_argument("items", nargs="+")
    upload = sub.add_parser("upload", help="Copy one PDF into Zotero while preserving the source")
    upload.add_argument("--file", required=True, type=Path)
    upload.add_argument("--collection", required=True)
    upload.add_argument("--title")
    upload.add_argument("--parent-item", help="Attach PDF to an existing bibliographic item")
    upload.add_argument("--tag", action="append", default=[])
    bib = sub.add_parser("bib", help="Build BibTeX from a JSON manifest and the live collection")
    bib.add_argument("--manifest", required=True, type=Path)
    bib.add_argument("--collection", required=True)
    bib.add_argument("--output", required=True, type=Path)
    apply = sub.add_parser("apply", help="Add/import references from a JSON manifest, then optionally build BibTeX")
    apply.add_argument("--manifest", required=True, type=Path)
    apply.add_argument("--collection", required=True)
    apply.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    api = Zotero()
    try:
        headers = api.connect()
        if args.command == "status":
            result = {"version": headers.get("X-Zotero-Version"), "server_id": api.server_id, "api_version": headers.get("Zotero-API-Version"), "remembered_authorization": bool(api._cached_key())}
        elif args.command == "collections":
            endpoint = f"/users/0/collections/{api.resolve_collection(args.parent)['key']}/collections" if args.parent else "/users/0/collections"
            result = [{"key8": x["key"], "name": x["data"]["name"], "parent": x["data"].get("parentCollection")} for x in api.get(endpoint)]
        elif args.command == "search":
            result = api.search_items(args.collection, args.tag, args.q, args.qmode, args.item_type, args.top, args.limit, args.start)
        elif args.command == "ensure-collection":
            key, created = api.ensure_collection(args.name, args.parent)
            result = {"key8": key, "created": created}
        elif args.command == "add":
            result = api.change_membership(args.items, args.collection)
        elif args.command == "move":
            result = api.change_membership(args.items, args.target, args.source)
        elif args.command == "upload":
            result = api.upload_pdf(args.file, args.collection, args.title, args.tag, args.parent_item)
        elif args.command == "bib":
            result = build_bib(api, read_manifest(args.manifest), args.collection, args.output)
        else:
            result = apply_references(api, args.manifest, args.collection, args.output)
        if args.json or isinstance(result, (dict, list)):
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(result)
        return 0
    except (ZoteroError, OSError, ValueError, KeyError) as exc:
        print(f"zlb: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
