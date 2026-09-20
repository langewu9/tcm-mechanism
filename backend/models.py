from pydantic import BaseModel, Field


class IntersectionRequest(BaseModel):
    left: list[str] = Field(default_factory=list)
    right: list[str] = Field(default_factory=list)


class CompareRequest(BaseModel):
    detected: list[str] = Field(default_factory=list)
    reference: list[str] = Field(default_factory=list)


class ScientistRequest(BaseModel):
    question: str = "麦门冬汤是否可能通过调控炎症与纤维化相关靶点改善肺纤维化？"
    disease: str = "Pulmonary fibrosis"
    formula: str = "麦冬, 半夏, 人参, 甘草, 粳米, 大枣"
    focus: str = "中药复方作用机制与可验证靶点发现"
    use_qwen: bool = False
    qwen_api_key: str | None = None
    qwen_base_url: str | None = None
    qwen_model: str | None = None


class QwenTestRequest(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
