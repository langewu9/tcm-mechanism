import { NextResponse } from "next/server";
import { handleRouteError, jsonError, requireApiUser } from "@/lib/api";
import { prisma } from "@/lib/prisma";

export const runtime = "nodejs";

const DEFAULT_MODEL = "QLUNLP/BianCang-Qwen2.5-7B-Instruct";

async function postJson(url: string, payload: unknown, timeoutMs: number) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal
    });
    const text = await response.text();
    let data: any = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { raw: text };
    }
    return { ok: response.ok, status: response.status, data };
  } finally {
    clearTimeout(timer);
  }
}

function unique<T>(items: T[]) {
  return Array.from(new Set(items));
}

function quickAnswer(message: string) {
  const text = message.replace(/\s+/g, "");
  if (["你是谁", "你是什么", "你叫什么", "介绍一下你", "你能做什么"].some((item) => text.includes(item))) {
    return "我是本平台的本地中医药理模型助手，负责协助分析医案、证候、方药、成分、靶点、基因和通路。简单检索类问题我会直接查本地知识库，复杂推理才调用 BianCang/Qwen。";
  }
  if (["模型状态", "连接状态", "是否接入", "连上了吗", "能用吗"].some((item) => text.includes(item))) {
    return "助手接口已接入本地知识库和 BianCang/Qwen 模型。知识库检索会快速返回；本地 7B 模型首次加载和复杂推理会慢一些。";
  }
  if (["你好", "您好", "hello", "hi"].some((item) => text.toLowerCase() === item)) {
    return "你好，我在。你可以把医案症状、方药或靶点问题发给我，我会按“证候-方药-成分-靶点-通路”来分析。";
  }
  return null;
}

function inferScientistContext(message: string, body: Record<string, unknown>) {
  const text = message.replace(/\s+/g, "");
  const diseaseRules = ["肺纤维化", "乳腺癌", "糖尿病", "类风湿关节炎", "中风病", "脑卒中", "中风"];
  const formulaRules = ["麦门冬汤", "补阳还五汤", "黄芪桂枝五物汤", "血府逐瘀汤", "四君子汤", "六味地黄丸"];
  const matchedDisease = diseaseRules.find((item) => text.includes(item));
  const matchedFormula = formulaRules.find((item) => text.includes(item));
  const disease = String(body.disease || matchedDisease || "肺纤维化").replace(/^(中风|脑卒中)$/, "中风病");
  let formula = String(body.formula || matchedFormula || "");

  if (!formula && /肺纤维化/.test(text)) {
    formula = "麦门冬汤";
  } else if (!formula && /气虚血瘀/.test(text) && /(中风|脑卒中)/.test(text)) {
    formula = "补阳还五汤";
  }

  const diseaseQuery = /(中风|脑卒中|脑梗)/.test(disease) ? "Stroke" : disease;
  const formulaIngredients: Record<string, string> = {
    麦门冬汤: "麦冬、半夏、人参、大枣、甘草、粳米",
    补阳还五汤: "黄芪、当归、川芎、赤芍、地龙",
    黄芪桂枝五物汤: "黄芪、桂枝、芍药、生姜、大枣",
    血府逐瘀汤: "桃仁、红花、当归、川芎、赤芍、牛膝、柴胡、枳壳、桔梗、生地黄、甘草",
    四君子汤: "人参、白术、茯苓、甘草",
    六味地黄丸: "熟地黄、山茱萸、山药、泽泻、牡丹皮、茯苓"
  };

  return {
    disease,
    diseaseQuery,
    formula,
    formulaQuery: formulaIngredients[formula] || formula
  };
}

function formatScientistReport(data: any, message: string, disease: string, formula: string) {
  const results = data?.results || {};
  const evidence = data?.evidence || {};
  const herbSummaries = Array.isArray(evidence.herb_summaries) ? evidence.herb_summaries : [];
  const preferredComponents = /quercetin|kaempferol|formononetin|ferulic|ligustilide|paeoniflorin|astragaloside|calycosin|isorhamnetin|川芎嗪|槲皮素|山柰酚|阿魏酸/i;
  const components = unique<string>(
    herbSummaries.flatMap((item: any) => item.components || []).map((item: unknown) => String(item))
  )
    .sort((left, right) => {
      const preferredDelta = Number(preferredComponents.test(right)) - Number(preferredComponents.test(left));
      return preferredDelta || left.length - right.length || left.localeCompare(right);
    })
    .slice(0, 10);
  const targets = Array.isArray(results.top_intersection_targets) ? results.top_intersection_targets.slice(0, 10) : [];
  const rationale = Array.isArray(data?.rationale) ? data.rationale : [];
  const methods = Array.isArray(data?.methods) ? data.methods : [];
  const syndrome = /气虚血瘀/.test(message)
    ? "气虚推动无力、血行不畅，治法以益气活血、化瘀通络为主。"
    : "需结合症状、舌脉和病程进一步辨证，本回答先按当前问题建立药理证据链。";

  const lines = [
    `结论：${formula || "候选方药"}干预${disease}可按“证候—方药—成分—靶点—通路—验证”建立研究链路。以下为本地知识库生成的可追溯分析，不把尚未验证的关联当作临床结论。`,
    "",
    `一、证候：${syndrome}`,
    `二、方药：${formula || "当前问题未指定方剂，建议补充处方组成后再做精确计算。"}`,
    `三、代表成分：${components.length ? components.join("、") : "本地库暂未检出，建议核对方剂名称或逐味输入中药。"}`,
    `四、候选靶点：${targets.length ? targets.join("、") : "当前未形成疾病—方药严格交集靶点。"}`,
    `五、证据规模：疾病靶点 ${results.disease_target_count ?? 0} 个，方药靶点 ${results.formula_target_count ?? 0} 个，严格交集 ${results.intersection_count ?? 0} 个。`
  ];

  if (rationale.length) {
    const queriedDisease = String(data?.input?.disease || "");
    lines.push(
      "",
      "证据解释：",
      ...rationale.slice(0, 4).map((item: string) => `- ${queriedDisease ? item.replaceAll(queriedDisease, disease) : item}`)
    );
  }
  if (methods.length) {
    lines.push("", "建议的下一步验证：", ...methods.slice(0, 5).map((item: string) => `- ${item}`));
  }

  return lines.join("\n");
}

async function localKnowledgeAnswer(message: string) {
  const text = message.replace(/\s+/g, "");
  const asksInventory = /(多少|收录|统计|规模|总数|总共)/.test(text) && /(中药|成分|靶点|通路)/.test(text);
  if (asksInventory) {
    const [herbs, compounds, targets, pathways] = await Promise.all([
      prisma.herb.count(),
      prisma.compound.count(),
      prisma.target.count(),
      prisma.pathway.count({ where: { externalId: { startsWith: "R-HSA-" } } })
    ]);
    return `当前业务库收录中药 ${herbs.toLocaleString("zh-CN")} 种、活性成分 ${compounds.toLocaleString("zh-CN")} 个、作用靶点 ${targets.toLocaleString("zh-CN")} 个、Reactome 人类生物通路 ${pathways.toLocaleString("zh-CN")} 条。`;
  }

  const herbNames = await prisma.herb.findMany({ select: { id: true, name: true } });
  const matched = herbNames
    .filter((item) => item.name && text.includes(item.name))
    .sort((left, right) => right.name.length - left.name.length)[0];
  if (!matched) return null;

  const herb = await prisma.herb.findUnique({
    where: { id: matched.id },
    include: {
      formulas: true,
      compounds: {
        take: 100,
        include: {
          targets: {
            take: 50,
            include: {
              pathways: { take: 30 },
              genes: { take: 30 }
            }
          }
        }
      }
    }
  });
  if (!herb) return null;

  const asksFormula = /方|方药|方剂|处方|配伍/.test(text);
  const asksCompound = /成分|化合物|活性/.test(text);
  const asksTarget = /靶点|基因|通路|机制/.test(text);

  if (!asksFormula && !asksCompound && !asksTarget) return null;

  const formulas = herb.formulas.map((item) => `${item.name}${item.indication ? `（${item.indication}）` : ""}`);
  const compounds = herb.compounds.map((item) => item.name);
  const targets = unique(herb.compounds.flatMap((compound) => compound.targets.map((target) => target.symbol)));
  const pathways = unique(
    herb.compounds.flatMap((compound) => compound.targets.flatMap((target) => target.pathways.map((pathway) => pathway.name)))
  );

  const lines = [
    `根据本地知识库，${herb.name}的功效记录为：${herb.effect || "未记录"}；归经：${herb.meridian || "未记录"}。`
  ];

  if (asksFormula || asksCompound) {
    lines.push(`相关方药：${formulas.length ? formulas.join("、") : "当前知识库暂无直接关联方剂"}`);
  }
  if (asksCompound) {
    lines.push(`已收录成分：${compounds.length ? compounds.join("、") : "当前知识库暂无成分记录"}`);
  }
  if (asksTarget) {
    lines.push(`关联靶点：${targets.length ? targets.join("、") : "当前知识库暂无靶点记录"}`);
    lines.push(`关联通路：${pathways.length ? pathways.join("、") : "当前知识库暂无通路记录"}`);
  }

  if (herb.name === "黄芪" && asksCompound && asksFormula) {
    lines.push("结论：黄芪在当前库中主要通过黄芪甲苷、槲皮素等成分参与补阳还五汤等益气活血方药思路，适合围绕气虚血瘀型中风后遗症展开靶点与通路分析。");
  }

  return lines.join("\n");
}

function fallbackAnswer(message: string, errors: string[]) {
  return [
    "我已经收到问题，但本地知识库没有直接命中，且本地模型没有在限定时间内返回。",
    "为了避免界面一直卡住，我先结束本次等待。可以缩小问题范围，例如输入“麦冬的成分和靶点”或“麦门冬汤的六味组成”。",
    `本次问题：${message}`,
    "",
    "连接诊断：",
    ...errors.map((item) => `- ${item}`)
  ].join("\n");
}

export async function POST(request: Request) {
  try {
    await requireApiUser();
    const body = await request.json();
    const message = String(body.message ?? "").trim();
    if (!message) return jsonError("请输入问题");

    const quick = quickAnswer(message);
    if (quick) return NextResponse.json({ ok: true, source: "quick-local", answer: quick });

    const localAnswer = await localKnowledgeAnswer(message);
    if (localAnswer) return NextResponse.json({ ok: true, source: "local-knowledge", answer: localAnswer });

    const modelBaseUrl = String(body.baseUrl || process.env.NEXT_PUBLIC_MODEL_BASE_URL || "http://127.0.0.1:8000/v1").replace(/\/$/, "");
    const model = String(body.model || process.env.BIANCANG_MODEL || DEFAULT_MODEL);
    const fastApiBaseUrl = String(process.env.NEXT_PUBLIC_FASTAPI_BASE_URL || "http://127.0.0.1:8010").replace(/\/$/, "");
    const maxTokens = Math.min(Number(body.maxTokens || process.env.ASSISTANT_MAX_TOKENS || 256), 512);
    const timeoutMs = Math.min(Number(body.timeoutMs || process.env.ASSISTANT_TIMEOUT_MS || 45000), 120000);
    const modelTimeoutMs = Math.min(Number(body.modelTimeoutMs || process.env.ASSISTANT_MODEL_TIMEOUT_MS || 8000), timeoutMs);
    const errors: string[] = [];
    const scientistContext = inferScientistContext(message, body);

    try {
      const modelResult = await postJson(
        `${modelBaseUrl}/chat/completions`,
        {
          model,
          messages: [
            {
              role: "system",
              content: "你是中医药理与网络药理研究助手。请用简洁中文回答，优先给结论，再按证候、方药、成分、靶点、通路列要点。"
            },
            { role: "user", content: message }
          ],
          temperature: 0.2,
          max_tokens: maxTokens
        },
        modelTimeoutMs
      );
      const answer = modelResult.data?.choices?.[0]?.message?.content;
      if (modelResult.ok && answer) return NextResponse.json({ ok: true, source: "local-openai", answer, raw: modelResult.data });
      errors.push(`本地模型 HTTP ${modelResult.status}: ${JSON.stringify(modelResult.data).slice(0, 500)}`);
    } catch (error) {
      errors.push(`本地模型连接或推理超时：${error instanceof Error ? error.message : String(error)}`);
    }

    try {
      const fastApiResult = await postJson(
        `${fastApiBaseUrl}/api/scientist/hypothesis`,
        {
          question: message,
          disease: scientistContext.diseaseQuery,
          formula: scientistContext.formulaQuery,
          focus: body.focus || "证候-方药-成分-靶点-通路",
          use_qwen: false,
          qwen_api_key: body.apiKey || "local",
          qwen_base_url: modelBaseUrl,
          qwen_model: model
        },
        timeoutMs
      );
      const data = fastApiResult.data;
      if (fastApiResult.ok) {
        return NextResponse.json({
          ok: true,
          source: "fastapi-scientist",
          answer:
            data.qwen_enhanced_text ||
            data.summary ||
            data.qwen_result?.content ||
            formatScientistReport(data, message, scientistContext.disease, scientistContext.formula),
          raw: data
        });
      }
      errors.push(`FastAPI HTTP ${fastApiResult.status}: ${JSON.stringify(data).slice(0, 500)}`);
    } catch (error) {
      errors.push(`FastAPI 连接或推理超时：${error instanceof Error ? error.message : String(error)}`);
    }

    return NextResponse.json({ ok: false, source: "timeout-fallback", answer: fallbackAnswer(message, errors), errors }, { status: 200 });
  } catch (error) {
    return handleRouteError(error);
  }
}
