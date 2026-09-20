import { PrismaClient } from "@prisma/client";
import { hashPassword } from "../src/lib/password";

const prisma = new PrismaClient();

async function main() {
  const admin = await prisma.user.upsert({
    where: { email: "admin@qihuang.local" },
    update: {},
    create: {
      name: "平台管理员",
      email: "admin@qihuang.local",
      passwordHash: hashPassword("Admin123!"),
      role: "ADMIN"
    }
  });

  const researcher = await prisma.user.upsert({
    where: { email: "user@qihuang.local" },
    update: {},
    create: {
      name: "研究员",
      email: "user@qihuang.local",
      passwordHash: hashPassword("User123!"),
      role: "RESEARCHER"
    }
  });

  const pathways = await Promise.all(
    [
      ["PI3K-Akt signaling pathway", "细胞存活、炎症和血管新生相关通路"],
      ["TNF signaling pathway", "炎症反应和免疫调控通路"],
      ["HIF-1 signaling pathway", "缺血缺氧适应和血管保护通路"],
      ["Neuroactive ligand-receptor interaction", "神经递质和受体调控网络"]
    ].map(([name, description]) =>
      prisma.pathway.upsert({ where: { name }, update: {}, create: { name, description } })
    )
  );

  const genes = await Promise.all(
    [
      ["AKT1", "AKT serine/threonine kinase 1"],
      ["TNF", "Tumor necrosis factor"],
      ["IL6", "Interleukin 6"],
      ["VEGFA", "Vascular endothelial growth factor A"],
      ["MAPK1", "Mitogen-activated protein kinase 1"],
      ["PTGS2", "Prostaglandin-endoperoxide synthase 2"]
    ].map(([symbol, name]) => prisma.gene.upsert({ where: { symbol }, update: {}, create: { symbol, name } }))
  );

  const targetData = [
    ["AKT1", "AKT1", ["PI3K-Akt signaling pathway", "HIF-1 signaling pathway"]],
    ["TNF", "TNF", ["TNF signaling pathway"]],
    ["IL6", "IL6", ["TNF signaling pathway", "HIF-1 signaling pathway"]],
    ["VEGFA", "VEGFA", ["PI3K-Akt signaling pathway", "HIF-1 signaling pathway"]],
    ["MAPK1", "MAPK1", ["PI3K-Akt signaling pathway", "TNF signaling pathway"]],
    ["PTGS2", "PTGS2", ["TNF signaling pathway", "Neuroactive ligand-receptor interaction"]]
  ];

  const targets = await Promise.all(
    targetData.map(([symbol, geneSymbol, pathwayNames]) =>
      prisma.target.upsert({
        where: { symbol: String(symbol) },
        update: {},
        create: {
          symbol: String(symbol),
          name: String(geneSymbol),
          genes: { connect: [{ symbol: String(geneSymbol) }] },
          pathways: { connect: (pathwayNames as string[]).map((name) => ({ name })) }
        }
      })
    )
  );

  const compounds = await Promise.all(
    [
      ["槲皮素", "5280343", ["AKT1", "TNF", "IL6", "PTGS2"]],
      ["黄芪甲苷", "13943297", ["AKT1", "VEGFA", "MAPK1"]],
      ["丹参酮IIA", "164676", ["TNF", "MAPK1", "PTGS2"]],
      ["川芎嗪", "5317", ["AKT1", "VEGFA"]],
      ["阿魏酸", "445858", ["IL6", "MAPK1", "PTGS2"]],
      ["芍药苷", "442534", ["TNF", "IL6"]]
    ].map(([name, pubchemId, targetSymbols]) =>
      prisma.compound.upsert({
        where: { name: String(name) },
        update: {},
        create: {
          name: String(name),
          pubchemId: String(pubchemId),
          targets: { connect: (targetSymbols as string[]).map((symbol) => ({ symbol })) }
        }
      })
    )
  );

  const herbs = await Promise.all(
    [
      ["黄芪", "脾、肺", "补气升阳、益卫固表", ["黄芪甲苷", "槲皮素"]],
      ["当归", "肝、心、脾", "补血活血、调经止痛", ["阿魏酸", "槲皮素"]],
      ["川芎", "肝、胆、心包", "活血行气、祛风止痛", ["川芎嗪", "阿魏酸"]],
      ["丹参", "心、肝", "活血祛瘀、通经止痛", ["丹参酮IIA", "阿魏酸"]],
      ["赤芍", "肝", "清热凉血、散瘀止痛", ["芍药苷", "槲皮素"]],
      ["地龙", "肝、脾、膀胱", "通络、平喘、利尿", ["槲皮素"]],
      ["天麻", "肝", "息风止痉、平抑肝阳", ["阿魏酸"]],
      ["半夏", "脾、胃、肺", "燥湿化痰、降逆止呕", ["槲皮素"]]
    ].map(([name, meridian, effect, compoundNames]) =>
      prisma.herb.upsert({
        where: { name: String(name) },
        update: {},
        create: {
          name: String(name),
          meridian: String(meridian),
          effect: String(effect),
          compounds: { connect: (compoundNames as string[]).map((compoundName) => ({ name: compoundName })) }
        }
      })
    )
  );

  const formulas = await Promise.all(
    [
      ["补阳还五汤", "气虚血瘀型中风后遗症", ["黄芪", "当归", "川芎", "赤芍", "地龙"]],
      ["温胆汤加减", "痰瘀阻络、痰热扰神", ["半夏", "丹参", "川芎", "地龙"]],
      ["天麻钩藤饮", "肝阳上亢、风阳上扰", ["天麻", "丹参", "赤芍"]],
      ["大定风珠", "阴虚风动、筋脉失养", ["当归", "赤芍", "天麻"]]
    ].map(([name, indication, herbNames]) =>
      prisma.formula.upsert({
        where: { name: String(name) },
        update: {},
        create: {
          name: String(name),
          indication: String(indication),
          herbs: { connect: (herbNames as string[]).map((herbName) => ({ name: herbName })) }
        }
      })
    )
  );

  await Promise.all(
    [
      ["气虚血瘀", "正气亏虚、瘀血阻络", ["补阳还五汤"]],
      ["痰瘀阻络", "痰浊与瘀血互结，阻滞脑络", ["温胆汤加减"]],
      ["肝阳上亢", "肝肾阴虚，风阳上扰", ["天麻钩藤饮"]],
      ["阴虚风动", "阴液不足，虚风内动", ["大定风珠"]]
    ].map(([name, description, formulaNames]) =>
      prisma.syndrome.upsert({
        where: { name: String(name) },
        update: {},
        create: {
          name: String(name),
          description: String(description),
          formulas: { connect: (formulaNames as string[]).map((formulaName) => ({ name: formulaName })) }
        }
      })
    )
  );

  const sampleCase = await prisma.medicalCase.upsert({
    where: { id: "seed-stroke-case" },
    update: {},
    create: {
      id: "seed-stroke-case",
      title: "中风后偏瘫气虚血瘀医案",
      patientInfo: "男，68 岁，中风后左侧肢体活动不利",
      symptoms: "半身不遂，气短乏力，口眼歪斜，舌暗有瘀斑，脉细涩",
      tonguePulse: "舌暗，脉涩",
      diagnosis: "气虚血瘀",
      source: "TCMPS 示例医案",
      ownerId: researcher.id
    }
  });

  const existingTask = await prisma.analysisTask.findFirst({ where: { name: "示例中风病网络药理分析" } });
  if (!existingTask) {
    await prisma.analysisTask.create({
      data: {
        name: "示例中风病网络药理分析",
        query: `${sampleCase.symptoms}。诊断：${sampleCase.diagnosis}`,
        ownerId: researcher.id,
        caseId: sampleCase.id,
        result: {
          create: {
            summary: "根据示例医案，系统匹配为气虚血瘀，推荐从补阳还五汤展开黄芪、当归、川芎、赤芍、地龙及其成分-靶点-通路分析。",
            evidenceJson: JSON.stringify({
              syndrome: "气虚血瘀",
              formula: ["补阳还五汤"],
              herbs: ["黄芪", "当归", "川芎", "赤芍", "地龙"],
              compounds: compounds.slice(0, 5).map((item) => item.name),
              targets: targets.slice(0, 5).map((item) => item.symbol),
              genes: genes.slice(0, 5).map((item) => item.symbol),
              pathways: pathways.slice(0, 3).map((item) => item.name)
            }),
            networkJson: JSON.stringify({
              nodes: [
                { id: "气虚血瘀", label: "气虚血瘀", type: "syndrome" },
                { id: "补阳还五汤", label: "补阳还五汤", type: "formula" },
                ...herbs.slice(0, 5).map((item) => ({ id: item.name, label: item.name, type: "herb" })),
                ...compounds.slice(0, 5).map((item) => ({ id: item.name, label: item.name, type: "compound" })),
                ...targets.slice(0, 5).map((item) => ({ id: item.symbol, label: item.symbol, type: "target" })),
                ...pathways.slice(0, 3).map((item) => ({ id: item.name, label: item.name, type: "pathway" }))
              ],
              links: [
                { source: "气虚血瘀", target: "补阳还五汤", relation: "推荐方剂" },
                ...herbs.slice(0, 5).map((item) => ({ source: "补阳还五汤", target: item.name, relation: "组成" })),
                ...compounds.slice(0, 5).map((item, index) => ({ source: herbs[index % herbs.length].name, target: item.name, relation: "含有" })),
                ...targets.slice(0, 5).map((item, index) => ({ source: compounds[index % compounds.length].name, target: item.symbol, relation: "作用" }))
              ]
            })
          }
        }
      }
    });
  }

  await prisma.databaseSource.upsert({
    where: { name: "本地药理缓存库" },
    update: {},
    create: {
      name: "本地药理缓存库",
      driver: "SQLITE",
      connectionUrl: "data_cache.db",
      mappingJson: JSON.stringify({
        table: "herb_component_target",
        herbColumn: "herb",
        compoundColumn: "component",
        targetColumn: "target"
      })
    }
  });

  console.log(`Seed completed: admin=${admin.email}, researcher=${researcher.email}`);
}

main()
  .catch((error) => {
    console.error(error);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
