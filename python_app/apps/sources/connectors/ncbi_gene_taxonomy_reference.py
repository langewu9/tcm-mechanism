"""Taxonomy lookup for the project's explicit NCBI Gene identifiers.

Only stable local GeneIDs are sent to NCBI E-utilities. Original source rows
remain unchanged; this file is an immutable, checksummed identity overlay.
"""
import hashlib
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SCHEMA = "ncbi-gene-esummary-taxonomy-v1"
ROOT = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
MAX_IDS_PER_REQUEST = 200


def _request(ids):
    params = urlencode({"db": "gene", "id": ",".join(ids), "retmode": "json"})
    request = Request(
        f"{ROOT}?{params}",
        headers={"User-Agent": "TCM-Mechanism-TargetIdentity/2.0", "Accept": "application/json"},
    )
    with urlopen(request, timeout=60) as response:
        if response.geturl().split("/", 3)[2].lower() != "eutils.ncbi.nlm.nih.gov":
            raise ValueError("NCBI E-utilities redirected outside the official NCBI host.")
        raw = response.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("NCBI Gene response exceeded the 16 MiB request limit.")
    return json.loads(raw.decode("utf-8"))


def _record(gene_id, item):
    organism = item.get("organism") or {}
    taxid = organism.get("taxid")
    if taxid is None:
        return None
    aliases = [value.strip() for value in str(item.get("otheraliases") or "").split(",") if value.strip()]
    designations = [value.strip() for value in str(item.get("otherdesignations") or "").split("|") if value.strip()]
    status = str(item.get("status") or "").strip()
    current_id = str(item.get("currentid") or "").strip()
    return {
        "geneId": str(gene_id),
        "taxon": str(taxid),
        "organism": str(organism.get("scientificname") or ""),
        "commonName": str(organism.get("commonname") or ""),
        "symbol": str(item.get("nomenclaturesymbol") or item.get("name") or ""),
        "description": str(item.get("description") or ""),
        "officialSymbol": str(item.get("nomenclaturesymbol") or ""),
        "officialName": str(item.get("nomenclaturename") or item.get("description") or ""),
        "synonyms": aliases,
        "otherDesignations": designations,
        "status": status,
        "currentId": current_id,
        "identityUsable": status in {"", "0"} and not current_id,
    }


def download_reference(directory, gene_ids):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    identifiers = sorted({str(value).strip() for value in gene_ids if str(value).strip().isdigit()})
    if not identifiers:
        raise ValueError("No explicit NCBI Gene identifiers were found in active target records.")

    rows = []
    for start in range(0, len(identifiers), MAX_IDS_PER_REQUEST):
        batch = identifiers[start:start + MAX_IDS_PER_REQUEST]
        last_error = None
        for attempt in range(3):
            try:
                response = _request(batch)
                result = response.get("result") or {}
                for gene_id in batch:
                    item = result.get(gene_id)
                    if isinstance(item, dict) and str(item.get("uid", "")) == gene_id:
                        record = _record(gene_id, item)
                        if record:
                            rows.append(record)
                break
            except Exception as exc:  # transient NCBI/network response
                last_error = exc
                if attempt == 2:
                    raise ValueError(f"NCBI Gene lookup failed for batch beginning {batch[0]}.") from exc
                time.sleep(1.5 * (attempt + 1))
        if last_error and not rows:
            raise ValueError("NCBI Gene lookup returned no usable records.") from last_error
        # NCBI's documented unauthenticated request rate is limited; keep a
        # conservative interval between ESummary batches.
        if start + MAX_IDS_PER_REQUEST < len(identifiers):
            time.sleep(0.36)

    rows.sort(key=lambda row: (row["taxon"], row["geneId"]))
    if len({(row["taxon"], row["geneId"]) for row in rows}) != len(rows):
        raise ValueError("NCBI ESummary returned duplicate taxon-qualified GeneIDs.")
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    checksum = hashlib.sha256(raw).hexdigest()
    filename = f"ncbi-gene-taxonomy-{checksum[:12]}.json"
    path = directory / filename
    if path.exists() and path.read_bytes() != raw:
        raise ValueError("Refusing to overwrite a versioned NCBI Gene taxonomy reference.")
    path.write_bytes(raw)
    taxa = Counter(row["taxon"] for row in rows)
    usable_taxa = Counter(row["taxon"] for row in rows if row["identityUsable"])
    status_counts = Counter(row["status"] or ("merged" if row["currentId"] else "current") for row in rows)
    manifest = {
        "schemaVersion": SCHEMA,
        "url": ROOT,
        "sha256": checksum,
        "file": filename,
        "requestedGeneIds": len(identifiers),
        "returnedRecords": len(rows),
        "unresolvedGeneIds": len(identifiers) - len(rows),
        "usableRecords": sum(1 for row in rows if row["identityUsable"]),
        "taxa": dict(sorted(taxa.items())),
        "usableTaxa": dict(sorted(usable_taxa.items())),
        "recordStatuses": dict(sorted(status_counts.items())),
        "retrievedAt": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = directory / f"ncbi-gene-taxonomy-{checksum[:12]}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def load_reference(manifest_path):
    path = Path(manifest_path).resolve(strict=True)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != SCHEMA or manifest.get("url") != ROOT:
        raise ValueError("Unsupported NCBI Gene taxonomy manifest.")
    source = (path.parent / manifest["file"]).resolve(strict=True)
    if source.parent != path.parent:
        raise ValueError("NCBI Gene taxonomy reference must stay beside its manifest.")
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest.get("sha256"):
        raise ValueError("NCBI Gene taxonomy checksum mismatch.")
    rows = json.loads(raw.decode("utf-8"))
    if len(rows) != manifest.get("returnedRecords"):
        raise ValueError("NCBI Gene taxonomy record count mismatch.")
    return manifest, rows
