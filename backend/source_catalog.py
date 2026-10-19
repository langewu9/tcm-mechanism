"""Workbook columns mirrored from frozen main data_service.py; checked by regression."""

SOURCE_FILES = {
    "batman": {
        "file": "Batman全部数据.xlsx",
        "columns": ["中文名", "Compound Name", "Gene Name", "Score"],
        "herb": "中文名",
        "component": "Compound Name",
        "target": "Gene Name",
    },
    "herb": {
        "file": "Herb数据库全部.xlsx",
        "columns": ["Herb_cn_name", "Ingredient name", "Gene name"],
        "herb": "Herb_cn_name",
        "component": "Ingredient name",
        "target": "Gene name",
    },
    "hit": {
        "file": "HIT数据库全部.xlsx",
        "columns": ["Chinese Character", "Compound Name", "Target ID", "Symbol", "Chembl ID", "Smiles"],
        "herb": "Chinese Character",
        "component": "Compound Name",
        "target": "Symbol",
    },
    "tcmip": {
        "file": "TCMIP全部数据.xlsx",
        "columns": ["中药", "成分名称", "靶标", "相似得分", "Activity"],
        "herb": "中药",
        "component": "成分名称",
        "target": "靶标",
    },
    "tcmsp": {
        "file": "tcmsp全部数据.xlsx",
        "columns": ["中药", "成分", "靶点基因"],
        "herb": "中药",
        "component": "成分",
        "target": "靶点基因",
    },
}
