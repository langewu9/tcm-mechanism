"""Fetch exact UniProtKB entries for locally stored accessions with unknown TaxID."""
import csv
import hashlib
import io
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = "https://rest.uniprot.org/uniprotkb/search"
SCHEMA = "uniprot-accession-taxonomy-v1"
MAX_ACCESSIONS_PER_REQUEST = 100
ACCESSION = re.compile(r"(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})")
FIELDS = "accession,organism_id,organism_name,gene_primary,protein_name,xref_geneid"
HEADER = ["Entry", "Organism (ID)", "Organism", "Gene Names (primary)", "Protein names", "GeneID"]


def _fetch(accessions):
    query = " OR ".join(f"accession:{value}" for value in accessions)
    params = {"query": query, "fields": FIELDS, "format": "tsv", "size": MAX_ACCESSIONS_PER_REQUEST}
    request = Request(
        f"{ROOT}?{urlencode(params)}",
        headers={"User-Agent": "TCM-Mechanism-TargetIdentity/2.0", "Accept": "text/tab-separated-values"},
    )
    with urlopen(request, timeout=60) as response:
        if not response.geturl().startswith("https://rest.uniprot.org/uniprotkb/"):
            raise ValueError("UniProt reference redirected outside the official host.")
        raw = response.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("UniProt accession batch exceeded the response size limit.")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter="\t")
    if reader.fieldnames != HEADER:
        raise ValueError("Unexpected UniProt accession reference columns.")
    rows = []
    for item in reader:
        accession = item["Entry"].strip().upper()
        taxon = item["Organism (ID)"].strip()
        if accession not in accessions or not taxon.isdigit():
            continue
        protein_name = item["Protein names"].strip()
        if not protein_name:
            continue
        genes = sorted({part.strip() for part in item["GeneID"].split(";") if part.strip().isdigit()})
        rows.append({
            "accession": accession,
            "taxon": taxon,
            "organismName": item["Organism"].strip(),
            "symbol": item["Gene Names (primary)"].strip(),
            "geneIds": genes,
            "proteinName": protein_name,
        })
    return rows


def download_reference(directory, accessions):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    identifiers = sorted({str(value).strip().upper() for value in accessions
        if ACCESSION.fullmatch(str(value).strip().upper())})
    if not identifiers:
        raise ValueError("No valid UniProt accessions with unknown source taxon were found.")
    rows = []
    for start in range(0, len(identifiers), MAX_ACCESSIONS_PER_REQUEST):
        batch = identifiers[start:start + MAX_ACCESSIONS_PER_REQUEST]
        last_error = None
        for attempt in range(3):
            try:
                rows.extend(_fetch(set(batch)))
                break
            except Exception as exc:
                last_error = exc
                if attempt == 2:
                    raise ValueError(f"UniProt lookup failed for batch beginning {batch[0]}.") from exc
                time.sleep(1.5 * (attempt + 1))
        if last_error and not rows:
            raise ValueError("UniProt lookup returned no usable entries.") from last_error
        if start + MAX_ACCESSIONS_PER_REQUEST < len(identifiers):
            time.sleep(0.25)
    rows.sort(key=lambda row: (row["taxon"], row["accession"]))
    if len({row["accession"] for row in rows}) != len(rows):
        raise ValueError("UniProt returned duplicate exact accession entries.")
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    checksum = hashlib.sha256(raw).hexdigest()
    filename = f"uniprot-accession-taxonomy-{checksum[:12]}.json"
    path = directory / filename
    if path.exists() and path.read_bytes() != raw:
        raise ValueError("Refusing to overwrite a versioned UniProt taxonomy reference.")
    path.write_bytes(raw)
    manifest = {
        "schemaVersion": SCHEMA,
        "url": ROOT,
        "fields": FIELDS,
        "sha256": checksum,
        "file": filename,
        "requestedAccessions": len(identifiers),
        "returnedRecords": len(rows),
        "unresolvedAccessions": len(identifiers) - len(rows),
        "taxa": {taxon: sum(1 for row in rows if row["taxon"] == taxon)
            for taxon in sorted({row["taxon"] for row in rows})},
        "retrievedAt": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = directory / f"uniprot-accession-taxonomy-{checksum[:12]}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def load_reference(manifest_path):
    path = Path(manifest_path).resolve(strict=True)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != SCHEMA or manifest.get("url") != ROOT or manifest.get("fields") != FIELDS:
        raise ValueError("Unsupported UniProt accession taxonomy manifest.")
    source = (path.parent / manifest["file"]).resolve(strict=True)
    if source.parent != path.parent:
        raise ValueError("UniProt reference must stay beside its manifest.")
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest.get("sha256"):
        raise ValueError("UniProt accession taxonomy checksum mismatch.")
    rows = json.loads(raw.decode("utf-8"))
    if len(rows) != manifest.get("returnedRecords"):
        raise ValueError("UniProt accession taxonomy record count mismatch.")
    return manifest, rows
