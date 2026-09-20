from __future__ import annotations

import sqlite3

from .config import CHEMBL_DB


def available() -> bool:
    return CHEMBL_DB.exists()


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(CHEMBL_DB)
    con.row_factory = sqlite3.Row
    return con


def search_molecules(q: str, limit: int = 30) -> dict:
    if not available():
        return {"available": False, "items": []}
    q_like = f"%{q.strip()}%"
    if not q.strip():
        return {"available": True, "items": []}
    sql = """
    select distinct md.molregno, md.pref_name, md.chembl_id, md.molecule_type,
           md.max_phase, md.natural_product, cs.canonical_smiles
    from molecule_dictionary md
    left join molecule_synonyms ms on ms.molregno = md.molregno
    left join compound_structures cs on cs.molregno = md.molregno
    where md.pref_name like ? or md.chembl_id like ? or ms.synonyms like ?
    order by md.pref_name is null, md.pref_name
    limit ?
    """
    with connect() as con:
        rows = [dict(r) for r in con.execute(sql, (q_like, q_like, q_like, limit))]
    return {"available": True, "query": q, "items": rows}


def molecule_activities(chembl_id: str, limit: int = 50) -> dict:
    if not available():
        return {"available": False, "items": []}
    sql = """
    select md.chembl_id as molecule_chembl_id, md.pref_name as molecule_name,
           td.chembl_id as target_chembl_id, td.pref_name as target_name,
           td.organism, a.standard_type, a.standard_relation, a.standard_value,
           a.standard_units, a.pchembl_value, ass.description as assay_description
    from molecule_dictionary md
    join activities a on a.molregno = md.molregno
    join assays ass on ass.assay_id = a.assay_id
    left join target_dictionary td on td.tid = ass.tid
    where md.chembl_id = ?
      and (a.standard_value is not null or a.pchembl_value is not null)
    order by a.pchembl_value desc nulls last
    limit ?
    """
    with connect() as con:
        rows = [dict(r) for r in con.execute(sql, (chembl_id.strip(), limit))]
    return {"available": True, "chembl_id": chembl_id, "items": rows}

