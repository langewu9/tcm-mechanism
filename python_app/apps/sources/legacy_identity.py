"""Validate source assertions without promoting them to canonical identifiers."""
import json
import math
import re


SCHEMA = "legacy-source-identity-1"
IDENTITY_POLICY = "source-identifier-namespace-1"
IDENTITY_FIELDS = {"herbId", "compoundId", "targetId", "targetSymbol", "uniprot", "pubchem", "chembl"}


def read_identity_record(value, row_id):
    if not isinstance(value, str) or len(value.encode("utf-8")) > 65536:
        raise ValueError("来源身份元数据必须是至多 64 KB 的 JSON 文本。")
    def invalid_constant(_):
        raise ValueError("来源元数据不能包含非有限数值。")
    try:
        data = json.loads(value, parse_constant=invalid_constant)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("来源身份元数据不是有效 JSON。") from exc
    if not isinstance(data, dict) or data.get("schemaVersion") != SCHEMA:
        raise ValueError("来源身份元数据版本不受支持。")
    pending = [data]
    while pending:
        item = pending.pop()
        if isinstance(item, str) and "\x00" in item:
            raise ValueError("来源字段不能包含 NUL 字符。")
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    if (not isinstance(data.get("workbookSha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", data["workbookSha256"])
            or not isinstance(data.get("sheet"), str) or not 1 <= len(data["sheet"]) <= 120
            or type(data.get("sourceRow")) is not int or data["sourceRow"] != row_id):
        raise ValueError("来源文件、工作表或原行号依据无效。")
    identity = data.get("identity")
    if not isinstance(identity, dict) or set(identity) - IDENTITY_FIELDS:
        raise ValueError("来源身份字段不受支持。")
    if any(not isinstance(item, str) or len(item) > 160 for item in identity.values()):
        raise ValueError("来源身份字段必须是至多 160 字符的文本。")
    if any(not identity.get(key, "").strip() for key in ("herbId", "compoundId", "targetId")):
        raise ValueError("来源身份模式要求每行保留中药、成分和靶点的原始编号。")
    raw = data.get("rawFields")
    if (not isinstance(raw, dict) or len(raw) > 64
            or any(not isinstance(key, str) or len(key) > 160 for key in raw)
            or any(item is not None and type(item) not in (str, int, float, bool) for item in raw.values())
            or any(type(item) is float and not math.isfinite(item) for item in raw.values())):
        raise ValueError("原始字段必须是有界的单层 JSON 对象。")
    return data


def check_identity_consistency(entity, seen):
    """One source ID cannot silently acquire two incompatible assertions."""
    if "sourceEntityId" not in entity["metadata"]:
        return
    key = (entity["entity_type"], entity["stable_id"])
    proof = (entity["label"], entity["metadata"])
    if key in seen and seen[key] != proof:
        raise ValueError("同一来源编号的名称或标识断言存在冲突，请先核对原表；未自动合并。")
    seen[key] = proof
