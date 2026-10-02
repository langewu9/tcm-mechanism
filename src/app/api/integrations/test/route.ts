import { NextResponse } from "next/server";
import { handleRouteError, jsonError, requireApiUser } from "@/lib/api";
import { fastApiGet, fastApiPost } from "@/lib/fastapi";

export const runtime = "nodejs";

const defaultPayloads = {
  qwen: {
    api_key: null,
    base_url: null,
    model: null
  },
  disease: {
    q: "Pulmonary fibrosis",
    limit: 20
  },
  herb: {
    q: "粳米",
    limit: 20
  },
  component: {
    q: "quercetin",
    limit: 20
  },
  chembl: {
    q: "quercetin",
    limit: 10
  },
  intersection: {
    left: ["MAPK1", "TP53", "AKT1"],
    right: ["AKT1", "IL6", "MAPK1"]
  },
  compare: {
    detected: ["quercetin", "kaempferol", "unknown sample"],
    reference: ["quercetin", "kaempferol", "beta-sitosterol"]
  },
  scientist: {
    question: "麦门冬汤是否可能通过调控炎症与纤维化相关靶点改善肺纤维化？",
    disease: "Pulmonary fibrosis",
    formula: "麦冬, 半夏, 人参, 甘草, 粳米, 大枣",
    focus: "中药复方作用机制与可验证靶点发现",
    use_qwen: false,
    qwen_api_key: null,
    qwen_base_url: null,
    qwen_model: null
  }
};

function withQuery(path: string, params: Record<string, unknown>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  }
  return `${path}?${query.toString()}`;
}

export async function POST(request: Request) {
  try {
    await requireApiUser();
    const body = await request.json();
    const target = String(body.target || "");
    const payload = body.payload && typeof body.payload === "object" ? body.payload : {};

    if (!(target in defaultPayloads)) return jsonError("未知 API 测试类型");

    const merged = {
      ...(defaultPayloads as Record<string, Record<string, unknown>>)[target],
      ...payload
    };

    const timeoutMs = target === "scientist" || target === "qwen" ? 45000 : 15000;

    if (target === "qwen") {
      return NextResponse.json({
        target,
        result: await fastApiPost("/api/qwen/test", merged, timeoutMs)
      });
    }
    if (target === "disease") {
      return NextResponse.json({
        target,
        result: await fastApiGet(withQuery("/api/search/disease", merged), timeoutMs)
      });
    }
    if (target === "herb") {
      return NextResponse.json({
        target,
        result: await fastApiGet(withQuery("/api/search/herb", merged), timeoutMs)
      });
    }
    if (target === "component") {
      return NextResponse.json({
        target,
        result: await fastApiGet(withQuery("/api/search/component", merged), timeoutMs)
      });
    }
    if (target === "chembl") {
      return NextResponse.json({
        target,
        result: await fastApiGet(withQuery("/api/chembl/molecules", merged), timeoutMs)
      });
    }
    if (target === "intersection") {
      return NextResponse.json({
        target,
        result: await fastApiPost("/api/targets/intersection", merged, timeoutMs)
      });
    }
    if (target === "compare") {
      return NextResponse.json({
        target,
        result: await fastApiPost("/api/components/compare", merged, timeoutMs)
      });
    }

    return NextResponse.json({
      target,
      result: await fastApiPost("/api/scientist/hypothesis", merged, timeoutMs)
    });
  } catch (error) {
    return handleRouteError(error);
  }
}
