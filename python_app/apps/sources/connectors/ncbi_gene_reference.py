"""Download and validate NCBI's public human Gene nomenclature reference."""
import csv
import gzip
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


URL = "https://ftp.ncbi.nlm.nih.gov/gene/DATA/GENE_INFO/Mammalia/Homo_sapiens.gene_info.gz"
TAX_ID = "9606"
SCHEMA = "ncbi-gene-info-human-v1"
MAX_BYTES = 32 * 1024 * 1024
EXPECTED_COLUMNS = [
    "#tax_id", "GeneID", "Symbol", "LocusTag", "Synonyms", "dbXrefs", "chromosome",
    "map_location", "description", "type_of_gene", "Symbol_from_nomenclature_authority",
    "Full_name_from_nomenclature_authority", "Nomenclature_status", "Other_designations",
    "Modification_date", "Feature_type",
]

_AMINO_ACIDS = {
    "ala": "alanine", "arg": "arginine", "asn": "asparagine", "asp": "aspartic acid",
    "cys": "cysteine", "gln": "glutamine", "glu": "glutamic acid", "gly": "glycine",
    "his": "histidine", "ile": "isoleucine", "leu": "leucine", "lys": "lysine",
    "met": "methionine", "phe": "phenylalanine", "pro": "proline", "ser": "serine",
    "thr": "threonine", "trp": "tryptophan", "tyr": "tyrosine", "val": "valine",
}
_ROMAN = {"1": "I", "2": "II", "3": "III"}
_PLACEHOLDERS = {"", "-", "na", "n/a", "none", "null"}


def _usable_name(value):
    value = str(value or "").strip()
    return value if value.casefold() not in _PLACEHOLDERS else ""


def identity_name_variants(value):
    """Return conservative, explicit nomenclature variants for exact matching.

    Variants are used only to produce candidates. They never prove source species
    or turn a name-only record into a verified mapping.
    """
    name = _usable_name(value)
    if not name:
        return []
    variants = [name]

    # NCBI marks some canonical names with a parenthetical activity qualifier.
    stripped_qualifier = re.sub(r"\s+\([^()]*\)\s*$", "", name).strip()
    if stripped_qualifier and stripped_qualifier != name:
        variants.append(stripped_qualifier)

    # Remove the generic word “protein” only when it directly qualifies a number.
    # This covers forms such as “chloride intracellular channel protein 4”.
    without_generic_protein = re.sub(r"\bprotein\s+(?=\d)", "", name, flags=re.I)
    if without_generic_protein != name:
        variants.append(without_generic_protein)

    normalized = " ".join(name.casefold().split())
    mt_nd = re.fullmatch(
        r"mitochondrially encoded nadh\s*:\s*ubiquinone oxidoreductase core subunit\s+(\d+l?)",
        normalized,
    )
    if mt_nd:
        subunit = mt_nd.group(1).upper()
        if subunit.endswith("L"):
            variants.append(f"mitochondrially encoded NADH {subunit} dehydrogenase")
        else:
            variants.extend([
                f"mitochondrially encoded NADH dehydrogenase {subunit}",
                f"NADH dehydrogenase subunit {subunit}",
            ])

    mt_atp = re.fullmatch(r"mitochondrially encoded atp synthase membrane subunit\s+(\d+)", normalized)
    if mt_atp:
        subunit = mt_atp.group(1)
        variants.extend([
            f"mitochondrially encoded ATP synthase {subunit}",
            f"ATP synthase F0 subunit {subunit}",
        ])

    mt_cox = re.fullmatch(r"mitochondrially encoded cytochrome c oxidase subunit\s+(\d+)", normalized)
    if mt_cox and mt_cox.group(1) in _ROMAN:
        roman = _ROMAN[mt_cox.group(1)]
        variants.extend([
            f"mitochondrially encoded cytochrome c oxidase {roman}",
            f"cytochrome c oxidase subunit {roman}",
        ])

    mt_rrna = re.fullmatch(r"mitochondrially encoded\s+(12s|16s)\s+rrna", normalized)
    if mt_rrna:
        variants.append(f"mitochondrially encoded {mt_rrna.group(1)} RNA")

    mt_trna = re.fullmatch(
        r"mitochondrially encoded\s+t\s*rna\s*-\s*([a-z]{3})\s*(?:\(([^()]*)\))?\s*(\d+)?",
        normalized,
    )
    if mt_trna and mt_trna.group(1) in _AMINO_ACIDS:
        amino_acid = _AMINO_ACIDS[mt_trna.group(1)]
        codon = f" ({mt_trna.group(2)})" if mt_trna.group(2) else ""
        ordinal = f" {mt_trna.group(3)}" if mt_trna.group(3) else ""
        variants.append(f"mitochondrially encoded tRNA {amino_acid}{ordinal}{codon}")
        if not ordinal:
            variants.append(f"mitochondrially encoded tRNA {amino_acid}")

    # Established short names that are not present verbatim in this NCBI release.
    established_aliases = {
        "coagulation factor xa": ["coagulation factor X"],
        "archain 1": ["archain 1 coat protein complex I subunit delta"],
        "lysosomal associated membrane protein 3": ["lysosome associated membrane protein 3"],
        "mre11 homolog, double strand break repair nuclease": ["MRE11 double strand break repair nuclease"],
        "7sk rna": ["7SK small nuclear RNA"],
        "vertebrate telomerase rna": ["telomerase RNA component"],
        "dna topoisomerase ii": ["DNA topoisomerase II alpha", "DNA topoisomerase II beta"],
        "heat shock protein hsp 90": [
            "heat shock protein 90 alpha family class A member 1",
            "heat shock protein 90 alpha family class B member 1",
            "heat shock protein 90 beta family member 1",
        ],
    }
    variants.extend(established_aliases.get(normalized, []))

    # Keep order stable and drop case-insensitive duplicates.
    return list(dict.fromkeys(item for item in variants if _usable_name(item)))


def parse_reference(raw):
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("NCBI Gene reference is empty or exceeds the size limit.")
    try:
        content = gzip.decompress(raw).decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError("NCBI Gene reference is not a valid UTF-8 gzip file.") from exc

    reader = csv.DictReader(io.StringIO(content), delimiter="\t")
    if reader.fieldnames != EXPECTED_COLUMNS:
        raise ValueError("Unexpected NCBI Gene reference columns.")

    rows, seen = [], set()
    for row in reader:
        if row["#tax_id"] != TAX_ID:
            continue
        gene_id = row["GeneID"].strip()
        if not gene_id.isdigit() or gene_id == "0" or gene_id in seen:
            raise ValueError("NCBI human reference contains an invalid or duplicate GeneID.")
        seen.add(gene_id)
        rows.append({
            "geneId": gene_id,
            "symbol": row["Symbol"].strip(),
            "synonyms": [value.strip() for value in row["Synonyms"].split("|") if value.strip()],
            "description": row["description"].strip(),
            "geneType": row["type_of_gene"].strip(),
            "officialSymbol": row["Symbol_from_nomenclature_authority"].strip(),
            "officialName": row["Full_name_from_nomenclature_authority"].strip(),
            "otherDesignations": [value.strip() for value in row["Other_designations"].split("|") if value.strip()],
        })
    if len(rows) < 10000:
        raise ValueError("NCBI human Gene reference appears incomplete.")
    return rows


def select_matching_rows(rows, requested_names):
    """Keep only NCBI records whose exact official name or alias is used locally."""
    requested = set()
    requested_loose = set()
    requested_gene_ids = set()
    for name in requested_names:
        if not _usable_name(name):
            continue
        for variant in identity_name_variants(name):
            requested.add(" ".join(variant.casefold().split()))
            requested_loose.add("".join(char for char in variant.casefold() if char.isalnum()))
        requested_gene_ids.update(re.findall(r"\bLOC([1-9][0-9]*)\b", name, flags=re.I))
    selected = []
    for row in rows:
        names = [row["symbol"], row["description"], row["officialSymbol"], row["officialName"],
            *row["synonyms"], *row["otherDesignations"]]
        if row["geneId"] in requested_gene_ids or any(
                " ".join(variant.casefold().split()) in requested or
                "".join(char for char in variant.casefold() if char.isalnum()) in requested_loose
                for name in names if _usable_name(name)
                for variant in identity_name_variants(name)):
            selected.append(row)
    return selected


def _get(url):
    request = Request(url, headers={"User-Agent": "TCM-Target-Identity/2.0", "Accept": "application/gzip"})
    with urlopen(request, timeout=60) as response:
        if response.geturl().split("/", 3)[2].lower() != "ftp.ncbi.nlm.nih.gov":
            raise ValueError("NCBI reference redirected outside the official NCBI host.")
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("NCBI Gene reference exceeds the size limit.")
    return raw


def download_reference(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    raw = _get(URL)
    rows = parse_reference(raw)
    source_record_count = sum(1 for line in gzip.decompress(raw).splitlines()
        if line and not line.startswith(b"#"))
    checksum = hashlib.sha256(raw).hexdigest()
    filename = f"ncbi-gene-info-human-{checksum[:12]}.gz"
    path = directory / filename
    if path.exists() and path.read_bytes() != raw:
        raise ValueError("Refusing to overwrite a versioned NCBI reference.")
    path.write_bytes(raw)
    manifest = {
        "schemaVersion": SCHEMA,
        "taxId": TAX_ID,
        "url": URL,
        "file": filename,
        "sha256": checksum,
        "recordCount": len(rows),
        "sourceRecordCount": source_record_count,
        "excludedNonHumanRecords": source_record_count - len(rows),
        "retrievedAt": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = directory / f"ncbi-gene-info-human-{checksum[:12]}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def load_reference(manifest_path):
    path = Path(manifest_path).resolve(strict=True)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (manifest.get("schemaVersion") != SCHEMA or manifest.get("taxId") != TAX_ID
            or manifest.get("url") != URL):
        raise ValueError("Unsupported NCBI Gene reference manifest.")
    source = (path.parent / manifest["file"]).resolve(strict=True)
    if source.parent != path.parent:
        raise ValueError("NCBI reference file must stay beside its manifest.")
    if source.stat().st_size > MAX_BYTES:
        raise ValueError("NCBI Gene reference exceeds the size limit.")
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest.get("sha256"):
        raise ValueError("NCBI Gene reference checksum mismatch.")
    rows = parse_reference(raw)
    if len(rows) != manifest.get("recordCount"):
        raise ValueError("NCBI Gene reference record count mismatch.")
    return manifest, rows
