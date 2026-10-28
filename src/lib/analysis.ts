import { prisma } from "@/lib/prisma";

export type AnalysisInput = {
  name: string;
  query: string;
  caseId?: string | null;
};

const syndromeRules = [
  { name: "气虚血瘀", keywords: ["乏力", "偏瘫", "舌暗", "脉涩", "中风"] },
  { name: "痰瘀阻络", keywords: ["痰", "眩晕", "麻木", "语言不利", "苔腻"] },
  { name: "肝阳上亢", keywords: ["头痛", "眩晕", "急躁", "血压", "肝阳"] },
  { name: "阴虚风动", keywords: ["手足震颤", "口干", "失眠", "舌红", "风动"] }
];

function scoreRule(query: string, keywords: string[]) {
  return keywords.reduce((total, keyword) => total + (query.includes(keyword) ? 1 : 0), 0);
}

export async function runAnalysis(input: AnalysisInput) {
  const selected =
    syndromeRules
      .map((rule) => ({ ...rule, score: scoreRule(input.query, rule.keywords) }))
      .sort((a, b) => b.score - a.score)[0] ?? syndromeRules[0];

  const syndrome = await prisma.syndrome.findUnique({
    where: { name: selected.name },
    include: {
      formulas: {
        include: {
          herbs: {
            include: {
              compounds: {
                include: { targets: { include: { genes: true, pathways: true } } }
              }
            }
          }
        }
      }
    }
  });

  const fallback = await prisma.syndrome.findFirst({
    include: {
      formulas: {
        include: {
          herbs: {
            include: {
              compounds: {
                include: { targets: { include: { genes: true, pathways: true } } }
              }
            }
          }
        }
      }
    }
  });

  const result = syndrome ?? fallback;
  if (!result) throw new Error("基础知识库尚未初始化，请先运行 seed 脚本");

  const formulas = result.formulas;
  const herbs = formulas.flatMap((formula) => formula.herbs);
  const compounds = herbs.flatMap((herb) => herb.compounds);
  const targets = compounds.flatMap((compound) => compound.targets);
  const genes = targets.flatMap((target) => target.genes);
  const pathways = targets.flatMap((target) => target.pathways);

  const unique = <T extends { id: string }>(items: T[]) =>
    Array.from(new Map(items.map((item) => [item.id, item])).values());

  const uHerbs = unique(herbs);
  const uCompounds = unique(compounds);
  const uTargets = unique(targets);
  const uGenes = unique(genes);
  const uPathways = unique(pathways);

  const network = {
    nodes: [
      { id: result.name, label: result.name, type: "syndrome" },
      ...formulas.map((item) => ({ id: item.name, label: item.name, type: "formula" })),
      ...uHerbs.map((item) => ({ id: item.name, label: item.name, type: "herb" })),
      ...uCompounds.map((item) => ({ id: item.name, label: item.name, type: "compound" })),
      ...uTargets.map((item) => ({ id: item.symbol, label: item.symbol, type: "target" })),
      ...uPathways.map((item) => ({ id: item.name, label: item.name, type: "pathway" }))
    ],
    links: [
      ...formulas.map((item) => ({ source: result.name, target: item.name, relation: "推荐方剂" })),
      ...formulas.flatMap((formula) =>
        formula.herbs.map((herb) => ({ source: formula.name, target: herb.name, relation: "组成" }))
      ),
      ...uHerbs.flatMap((herb) =>
        herb.compounds.map((compound) => ({ source: herb.name, target: compound.name, relation: "含有" }))
      ),
      ...uCompounds.flatMap((compound) =>
        compound.targets.map((target) => ({ source: compound.name, target: target.symbol, relation: "作用" }))
      ),
      ...uTargets.flatMap((target) =>
        target.pathways.map((pathway) => ({ source: target.symbol, target: pathway.name, relation: "通路" }))
      )
    ]
  };

  const evidence = {
    syndrome: result.name,
    formula: formulas.map((item) => item.name),
    herbs: uHerbs.map((item) => item.name),
    compounds: uCompounds.map((item) => item.name),
    targets: uTargets.map((item) => item.symbol),
    genes: uGenes.map((item) => item.symbol),
    pathways: uPathways.map((item) => item.name)
  };

  const summary = `根据输入信息，系统优先匹配为“${result.name}”。建议从 ${formulas
    .map((item) => item.name)
    .join("、")} 展开证候-方剂-药物-成分-靶点-通路分析，重点关注 ${uTargets
    .slice(0, 5)
    .map((item) => item.symbol)
    .join("、")} 等靶点与 ${uPathways
    .slice(0, 3)
    .map((item) => item.name)
    .join("、")} 等通路。`;

  return { summary, evidence, network };
}
