import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEGACY_ROOT = PROJECT_ROOT / "中药-疾病-靶点数据库构建及可视化分析系统设计与实现" / "2425_33_10344_080910T_202112214801009_BS_002" / "最新"
LEGACY_ROOT = Path(os.getenv("TCM_LEGACY_ROOT", str(DEFAULT_LEGACY_ROOT)))
DATABASE_DIR = Path(os.getenv("TCM_DATABASE_DIR", str(LEGACY_ROOT / "database")))
VALIDATION_DIR = Path(os.getenv("TCM_VALIDATION_DIR", str(LEGACY_ROOT / "系统验证所需数据")))
APP_DB = Path(os.getenv("TCM_APP_DB", str(LEGACY_ROOT / "app.db")))
CHEMBL_DB = Path(os.getenv("TCM_CHEMBL_DB", r"D:\chembl\chembl_36\chembl_36_sqlite\chembl_36.db"))
FRONTEND_DIR = PROJECT_ROOT / "tcm_pharmacology_platform" / "frontend"
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-plus")
QWEN_API_KEY = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY") or ""
