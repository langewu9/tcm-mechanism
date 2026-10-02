import { existsSync } from "node:fs";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { NextResponse } from "next/server";
import { handleRouteError, jsonError, requireApiUser } from "@/lib/api";
import { expandDiseaseQueries, hasChinese } from "@/lib/disease-query";
import { prisma } from "@/lib/prisma";

export const runtime = "nodejs";

type ResearchAction = "disease" | "herb" | "component" | "chembl" | "intersection" | "compare" | "pathway";
type CacheRow = Record<string, unknown>;
type ComponentAlias = {
  chinese: string;
  english: string;
  latin: string;
  aliases: string[];
  fuzzy?: boolean;
  searchTerms?: string[];
};
type ComponentCandidate = { term: string; exact: boolean };

const COMPONENT_ALIASES: ComponentAlias[] = [
  { chinese: "槲皮素", english: "Quercetin", latin: "Quercetinum", aliases: ["槲皮素", "栎精", "Quercetin", "Quercetinum"] },
  { chinese: "木犀草素", english: "Luteolin", latin: "Luteolinum", aliases: ["木犀草素", "木樨草素", "Luteolin", "Luteolinum"] },
  { chinese: "山奈酚", english: "Kaempferol", latin: "Kaempferolum", aliases: ["山奈酚", "山柰酚", "Kaempferol", "Kaempferolum"] },
  { chinese: "芹菜素", english: "Apigenin", latin: "Apigeninum", aliases: ["芹菜素", "Apigenin", "Apigeninum"] },
  { chinese: "β-谷甾醇", english: "beta-sitosterol", latin: "Beta-sitosterolum", aliases: ["β-谷甾醇", "谷甾醇", "Beta-sitosterol", "beta-sitosterol", "β-sitosterol", "Beta-sitosterolum"] },
  { chinese: "豆甾醇", english: "Stigmasterol", latin: "Stigmasterolum", aliases: ["豆甾醇", "Stigmasterol", "Stigmasterolum"] },
  { chinese: "黄芩素", english: "Baicalein", latin: "Baicaleinum", aliases: ["黄芩素", "Baicalein", "Baicaleinum"] },
  { chinese: "汉黄芩素", english: "Wogonin", latin: "Wogoninum", aliases: ["汉黄芩素", "Wogonin", "Wogoninum"] },
  { chinese: "熊果酸", english: "Ursolic acid", latin: "Acidum ursolicum", aliases: ["熊果酸", "Ursolic acid", "Acidum ursolicum"] },
  { chinese: "齐墩果酸", english: "Oleanolic acid", latin: "Acidum oleanolicum", aliases: ["齐墩果酸", "Oleanolic acid", "Acidum oleanolicum"] },
  { chinese: "没食子酸", english: "Gallic acid", latin: "Acidum gallicum", aliases: ["没食子酸", "Gallic acid", "Acidum gallicum"] },
  { chinese: "咖啡酸", english: "Caffeic acid", latin: "Acidum caffeicum", aliases: ["咖啡酸", "Caffeic acid", "Acidum caffeicum"] },
  { chinese: "阿魏酸", english: "Ferulic acid", latin: "Acidum ferulicum", aliases: ["阿魏酸", "Ferulic acid", "Acidum ferulicum"] },
  { chinese: "绿原酸", english: "Chlorogenic acid", latin: "Acidum chlorogenicum", aliases: ["绿原酸", "Chlorogenic acid", "Acidum chlorogenicum"] },
  { chinese: "丹参酮IIA", english: "Tanshinone IIA", latin: "Tanshinonum IIA", aliases: ["丹参酮IIA", "丹参酮 IIA", "Tanshinone IIA", "Tanshinonum IIA"] },
  { chinese: "隐丹参酮", english: "Cryptotanshinone", latin: "Cryptotanshinonum", aliases: ["隐丹参酮", "Cryptotanshinone", "Cryptotanshinonum"] },
  { chinese: "丹酚酸B", english: "Salvianolic acid B", latin: "Acidum salvianolicum B", aliases: ["丹酚酸B", "丹酚酸 B", "Salvianolic acid B", "Acidum salvianolicum B"] },
  { chinese: "小檗碱", english: "Berberine", latin: "Berberinum", aliases: ["小檗碱", "黄连素", "Berberine", "Berberinum"] },
  { chinese: "大黄素", english: "Emodin", latin: "Emodinum", aliases: ["大黄素", "Emodin", "Emodinum"] },
  { chinese: "大黄酸", english: "Rhein", latin: "Rheinum", aliases: ["大黄酸", "Rhein", "Rheinum"] },
  { chinese: "甘草酸", english: "Glycyrrhizic acid", latin: "Acidum glycyrrhizicum", aliases: ["甘草酸", "Glycyrrhizic acid", "Acidum glycyrrhizicum"] },
  { chinese: "甘草次酸", english: "Glycyrrhetinic acid", latin: "Acidum glycyrrhetinicum", aliases: ["甘草次酸", "Glycyrrhetinic acid", "Acidum glycyrrhetinicum"] },
  { chinese: "甘草苷", english: "Liquiritin", latin: "Liquiritinum", aliases: ["甘草苷", "Liquiritin", "Liquiritinum"] },
  { chinese: "异甘草素", english: "Isoliquiritigenin", latin: "Isoliquiritigeninum", aliases: ["异甘草素", "Isoliquiritigenin", "Isoliquiritigeninum"] },
  { chinese: "芦丁", english: "Rutin", latin: "Rutinum", aliases: ["芦丁", "芸香苷", "Rutin", "Rutinum"] },
  { chinese: "白藜芦醇", english: "Resveratrol", latin: "Resveratrolum", aliases: ["白藜芦醇", "Resveratrol", "Resveratrolum"] },
  { chinese: "苦参碱", english: "Matrine", latin: "Matrinum", aliases: ["苦参碱", "Matrine", "Matrinum"] },
  { chinese: "氧化苦参碱", english: "Oxymatrine", latin: "Oxymatrinum", aliases: ["氧化苦参碱", "Oxymatrine", "Oxymatrinum"] },
  { chinese: "胡椒碱", english: "Piperine", latin: "Piperinum", aliases: ["胡椒碱", "Piperine", "Piperinum"] },
  { chinese: "桂皮醛", english: "Cinnamaldehyde", latin: "Cinnamaldehydum", aliases: ["桂皮醛", "肉桂醛", "Cinnamaldehyde", "Cinnamaldehydum"] },
  { chinese: "丁香酚", english: "Eugenol", latin: "Eugenolum", aliases: ["丁香酚", "Eugenol", "Eugenolum"] },
  { chinese: "厚朴酚", english: "Magnolol", latin: "Magnololum", aliases: ["厚朴酚", "Magnolol", "Magnololum"] },
  { chinese: "和厚朴酚", english: "Honokiol", latin: "Honokiolum", aliases: ["和厚朴酚", "Honokiol", "Honokiolum"] },
  { chinese: "黄芪甲苷", english: "Astragaloside IV", latin: "Astragalosidum IV", aliases: ["黄芪甲苷", "黄芪皂苷IV", "Astragaloside IV", "Astragalosidum IV"] },
  {
    chinese: "人参皂苷",
    english: "Ginsenoside",
    latin: "Ginsenosidum",
    aliases: [
      "人参皂苷",
      "人参总皂苷",
      "Ginsenoside",
      "Ginsenosidum",
      "Notoginsenoside",
      "Pseudoginsenoside",
      "Gypenoside",
      "Protopanaxadiol",
      "Protopanaxatriol",
      "Panaxadiol",
      "Panaxatriol"
    ],
    searchTerms: [
      "Ginsenoside",
      "Notoginsenoside",
      "Pseudoginsenoside",
      "Gypenoside",
      "Protopanaxadiol",
      "Protopanaxatriol",
      "Panaxadiol",
      "Panaxatriol"
    ],
    fuzzy: true
  },
  { chinese: "人参皂苷Rg1", english: "Ginsenoside Rg1", latin: "Ginsenosidum Rg1", aliases: ["人参皂苷Rg1", "人参皂苷 Rg1", "Ginsenoside Rg1", "Ginsenosidum Rg1"] },
  { chinese: "人参皂苷Rb1", english: "Ginsenoside Rb1", latin: "Ginsenosidum Rb1", aliases: ["人参皂苷Rb1", "人参皂苷 Rb1", "Ginsenoside Rb1", "Ginsenosidum Rb1"] }
];

async function parseResponse(response: Response) {
  const text = await response.text();
  try {
    return text ? JSON.parse(text) : null;
  } catch {
    return { message: text };
  }
}

function uniqueValues(values: unknown[]) {
  return Array.from(new Set(values.map((value) => String(value ?? "").trim()).filter(Boolean)));
}

function clean(value: unknown) {
  return String(value ?? "").trim();
}

function normalizeName(value: unknown) {
  return clean(value)
    .normalize("NFKC")
    .toLowerCase()
    .replace(/[βΒ]/g, "beta")
    .replace(/[αΑ]/g, "alpha")
    .replace(/[γΓ]/g, "gamma")
    .replace(/[Ⅰ]/g, "i")
    .replace(/[Ⅱ]/g, "ii")
    .replace(/[Ⅲ]/g, "iii")
    .replace(/[\s_\-]+/g, " ")
    .trim();
}

function splitInputList(value: unknown) {
  return Array.from(
    new Set(
      String(value ?? "")
        .split(/[\s,，、;；|\/]+/)
        .map((item) => item.trim())
        .filter(Boolean)
    )
  );
}

function splitQueryList(value: unknown) {
  return Array.from(
    new Set(
      String(value ?? "")
        .split(/[,，、;；|\n\r]+/)
        .map((item) => item.trim())
        .filter(Boolean)
    )
  );
}

function splitTargets(value: unknown) {
  return clean(value)
    .split(/[;,，；/|]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function objectRows(value: unknown) {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
    : [];
}

function asRows(statementRows: unknown[]) {
  return statementRows.map((row) => ({ ...(row as CacheRow) }));
}

function aliasForName(value: unknown) {
  const normalized = normalizeName(value);
  return COMPONENT_ALIASES.find((entry) => entry.aliases.some((alias) => normalizeName(alias) === normalized));
}

function aliasForComponent(value: unknown) {
  const exact = aliasForName(value);
  if (exact) return exact;
  const normalized = normalizeName(value);
  return COMPONENT_ALIASES.find((entry) =>
    entry.fuzzy && entry.aliases.some((alias) => {
      const normalizedAlias = normalizeName(alias);
      return normalizedAlias && normalized.includes(normalizedAlias);
    })
  );
}

function resolveComponentNames(query: string) {
  const queries = splitQueryList(query).slice(0, 12);
  const candidates = new Map<string, ComponentCandidate>();
  const profiles = new Map<string, ComponentAlias & { query: string; matchedTerms: string }>();

  for (const item of queries) {
    const normalized = normalizeName(item);
    const alias = COMPONENT_ALIASES.find((entry) => entry.aliases.some((term) => normalizeName(term) === normalized));
    if (alias) {
      const searchTerms = alias.searchTerms?.length ? alias.searchTerms : [alias.english];
      for (const term of searchTerms) {
        candidates.set(`${normalizeName(term)}:${alias.fuzzy ? "like" : "exact"}`, { term, exact: !alias.fuzzy });
      }
      profiles.set(alias.english, { ...alias, query: item, matchedTerms: alias.aliases.join("、") });
    } else {
      candidates.set(`${normalizeName(item)}:like`, { term: item, exact: false });
    }
  }

  return { queries, candidates: Array.from(candidates.values()), profiles: Array.from(profiles.values()) };
}

function mergeDiseaseResults(query: string, queries: string[], results: unknown[]) {
  const objects = results.filter((item): item is Record<string, unknown> => !!item && typeof item === "object");
  const herbs = uniqueValues(objects.flatMap((item) => Array.isArray(item.herbs) ? item.herbs : []));
  const targets = uniqueValues(objects.flatMap((item) => Array.isArray(item.targets) ? item.targets : []));
  const links = objects.flatMap((item, index) =>
    Array.isArray(item.links)
      ? item.links.map((row) => (row && typeof row === "object" ? { ...(row as Record<string, unknown>), sourceQuery: queries[index] } : { value: row, sourceQuery: queries[index] }))
      : []
  );
  return {
    query,
    expandedQueries: queries,
    herbs,
    targets,
    links,
    counts: { herbs: herbs.length, targets: targets.length, links: links.length }
  };
}

function mergeHerbResults(query: string, queries: string[], results: unknown[]) {
  const objects = results.filter((item): item is Record<string, unknown> => !!item && typeof item === "object");
  const links: Record<string, unknown>[] = objects.flatMap((item, index) =>
    objectRows(item.links).map((row) => ({ ...row, sourceQuery: queries[index] }))
  );
  const seenLinks = new Set<string>();
  const uniqueLinks = links.filter((row) => {
    const signature = ["sourceQuery", "source", "herb", "component", "target", "targets"]
      .map((key) => JSON.stringify(row[key] ?? ""))
      .join("\u001f");
    if (seenLinks.has(signature)) return false;
    seenLinks.add(signature);
    return true;
  });
  const matchedHerbs = uniqueValues([
    ...queries,
    ...uniqueLinks.map((row) => row.herb)
  ]);
  const components = uniqueValues(objects.flatMap((item) => Array.isArray(item.components) ? item.components : []));
  const targets = uniqueValues(objects.flatMap((item) => Array.isArray(item.targets) ? item.targets : []));
  const summaries = objects.map((item, index) => {
    const counts = item.counts && typeof item.counts === "object" ? item.counts as Record<string, unknown> : {};
    return {
      herb: queries[index],
      components: Number(counts.components ?? 0),
      targets: Number(counts.targets ?? 0),
      links: Number(counts.links ?? 0)
    };
  });
  return {
    query,
    queries,
    herbs: matchedHerbs,
    components,
    targets,
    links: uniqueLinks,
    summaries,
    counts: { herbs: matchedHerbs.length, components: components.length, targets: targets.length, links: uniqueLinks.length }
  };
}

function searchLocalHerbs(query: string, queries: string[]) {
  const cachePath = join(process.cwd(), "data_cache.db");
  if (!existsSync(cachePath)) return null;

  const db = new DatabaseSync(cachePath, { readOnly: true });
  const statement = db.prepare(
    "select source, herb, component, target from herb_component_target where herb like ? and herb <> '' and (component <> '' or target <> '')"
  );
  const seenLinks = new Set<string>();
  const links: Record<string, unknown>[] = [];
  const herbs = new Set<string>();
  const components = new Set<string>();
  const targets = new Set<string>();
  const summaries: Array<{ herb: string; matchedHerbs: string; components: number; targets: number; links: number }> = [];

  try {
    for (const item of queries) {
      const rows = asRows(statement.all(`%${item}%`));
      const rowHerbs = new Set<string>();
      const rowComponents = new Set<string>();
      const rowTargets = new Set<string>();
      let rowLinks = 0;

      for (const row of rows) {
        const source = clean(row.source);
        const herb = clean(row.herb);
        const component = clean(row.component);
        const rowTargetValues = splitTargets(row.target);
        const targetText = rowTargetValues.join("; ");
        const signature = [item, source, herb, component, targetText].join("\u001f");

        if (!seenLinks.has(signature)) {
          seenLinks.add(signature);
          rowLinks += 1;
          links.push({ sourceQuery: item, source, herb, component, targets: rowTargetValues });
        }

        if (herb) {
          herbs.add(herb);
          rowHerbs.add(herb);
        }
        if (component) {
          components.add(component);
          rowComponents.add(component);
        }
        for (const target of rowTargetValues) {
          targets.add(target);
          rowTargets.add(target);
        }
      }

      summaries.push({
        herb: item,
        matchedHerbs: Array.from(rowHerbs).slice(0, 12).join("、"),
        components: rowComponents.size,
        targets: rowTargets.size,
        links: rowLinks
      });
    }
  } finally {
    db.close();
  }

  return {
    query,
    queries,
    herbs: Array.from(herbs).sort((a, b) => a.localeCompare(b, "zh-CN")),
    components: Array.from(components).sort((a, b) => a.localeCompare(b, "zh-CN")),
    targets: Array.from(targets).sort((a, b) => a.localeCompare(b, "zh-CN")),
    links,
    summaries,
    counts: { herbs: herbs.size, components: components.size, targets: targets.size, links: links.length }
  };
}

function searchLocalComponents(query: string) {
  const cachePath = join(process.cwd(), "data_cache.db");
  if (!existsSync(cachePath)) return null;

  const resolution = resolveComponentNames(query);
  if (!resolution.queries.length) return null;

  const db = new DatabaseSync(cachePath, { readOnly: true });
  const likeStatement = db.prepare(
    "select source, herb, component, target from herb_component_target where component like ? and component <> '' and target <> ''"
  );
  const exactStatement = db.prepare(
    "select source, herb, component, target from herb_component_target where component = ? and component <> '' and target <> ''"
  );
  const seenLinks = new Set<string>();
  const links: Record<string, unknown>[] = [];
  const components = new Set<string>();
  const targets = new Set<string>();
  const nameProfiles = new Map<string, ComponentAlias & { query: string; matchedTerms: string; hitCount: number }>();

  for (const profile of resolution.profiles) {
    nameProfiles.set(profile.english, { ...profile, hitCount: 0 });
  }

  try {
    for (const candidate of resolution.candidates) {
      const rows = asRows(candidate.exact ? exactStatement.all(candidate.term) : likeStatement.all(`%${candidate.term}%`));
      for (const row of rows) {
        const source = clean(row.source);
        const herb = clean(row.herb);
        const component = clean(row.component);
        const rowTargets = splitTargets(row.target);
        if (!component || !rowTargets.length || ["Compound Name", "成分名称", "成分"].includes(component)) continue;

        const alias = aliasForComponent(component);
        const componentEnglish = alias?.fuzzy ? component : alias?.english ?? component;
        const profileKey = alias?.english ?? component;
        const existingProfile = nameProfiles.get(profileKey);
        if (alias && existingProfile) {
          existingProfile.hitCount += 1;
          nameProfiles.set(profileKey, existingProfile);
        } else if (alias) {
          nameProfiles.set(profileKey, { ...alias, query, matchedTerms: alias.aliases.join("、"), hitCount: 1 });
        } else if (!existingProfile) {
          nameProfiles.set(profileKey, {
            chinese: "",
            english: component,
            latin: "",
            aliases: [component],
            query,
            matchedTerms: component,
            hitCount: 1
          });
        } else {
          existingProfile.hitCount += 1;
          nameProfiles.set(profileKey, existingProfile);
        }

        components.add(component);
        for (const target of rowTargets) targets.add(target);

        const signature = [source, herb, component, rowTargets.join("; ")].join("\u001f");
        if (seenLinks.has(signature)) continue;
        seenLinks.add(signature);
        links.push({
          sourceQuery: query,
          source,
          herb,
          componentChinese: alias?.chinese ?? "",
          componentEnglish,
          componentLatin: alias?.latin ?? "",
          component,
          targets: rowTargets
        });
      }
    }
  } finally {
    db.close();
  }

  const nameMatches = Array.from(nameProfiles.values())
    .filter((item) => item.hitCount > 0 || resolution.profiles.some((profile) => profile.english === item.english))
    .sort((a, b) => b.hitCount - a.hitCount || a.english.localeCompare(b.english));

  return {
    query,
    queries: resolution.queries,
    resolvedQueries: resolution.candidates.map((candidate) => candidate.term),
    nameMatches,
    components: Array.from(components).sort((a, b) => a.localeCompare(b)),
    targets: Array.from(targets).sort((a, b) => a.localeCompare(b)),
    links,
    counts: { components: components.size, targets: targets.size, links: seenLinks.size, previewLinks: Math.min(links.length, 180) }
  };
}

function chemblItems(data: unknown) {
  if (!data || typeof data !== "object") return [];
  const record = data as Record<string, unknown>;
  return objectRows(record.items ?? record.records ?? record.molecules);
}

function chemblItemKey(row: Record<string, unknown>) {
  return clean(row.chembl_id) || clean(row.molregno) || clean(row.pref_name) || JSON.stringify(row);
}

async function searchChemblMultilingual(baseUrl: string, path: string, query: string) {
  const resolution = resolveComponentNames(query);
  const fallbackCandidates = splitQueryList(query).map((term) => ({ term, exact: false }));
  const candidates = (resolution.candidates.length ? resolution.candidates : fallbackCandidates).slice(0, 20);
  const profileHits = new Map<string, number>();
  const seenItems = new Set<string>();
  const items: Record<string, unknown>[] = [];
  let okResponses = 0;
  let lastError = "";

  for (const candidate of candidates) {
    const response = await fetch(`${baseUrl}${path}?q=${encodeURIComponent(candidate.term)}&limit=100`, { cache: "no-store" });
    const data = await parseResponse(response);
    if (!response.ok) {
      lastError = data?.detail || data?.error || `ChEMBL returned ${response.status}`;
      continue;
    }

    okResponses += 1;
    const candidateAlias = aliasForName(candidate.term);
    if (candidateAlias) {
      profileHits.set(candidateAlias.english, (profileHits.get(candidateAlias.english) ?? 0) + chemblItems(data).length);
    }

    for (const row of chemblItems(data)) {
      const key = chemblItemKey(row);
      if (seenItems.has(key)) continue;
      seenItems.add(key);
      items.push({
        sourceQuery: candidate.term,
        componentChinese: candidateAlias?.chinese ?? "",
        componentEnglish: candidateAlias?.english ?? candidate.term,
        componentLatin: candidateAlias?.latin ?? "",
        ...row
      });
    }
  }

  if (!okResponses) {
    throw new Error(lastError || "ChEMBL 查询失败");
  }

  const nameMatches = resolution.profiles
    .map((profile) => ({ ...profile, hitCount: profileHits.get(profile.english) ?? 0 }))
    .filter((profile) => profile.hitCount > 0 || resolution.profiles.some((item) => item.english === profile.english));

  return {
    available: true,
    query,
    queries: resolution.queries.length ? resolution.queries : splitQueryList(query),
    resolvedQueries: candidates.map((candidate) => candidate.term),
    nameMatches,
    items,
    counts: { molecules: items.length, queriedTerms: candidates.length }
  };
}

function resolveCompareComponent(raw: string, side: "detected" | "reference") {
  const value = clean(raw);
  const exactAlias = aliasForName(value);
  const familyAlias = aliasForComponent(value);
  const alias = exactAlias ?? familyAlias;
  const canonicalName = exactAlias?.english ?? value;
  const normalizedKey = normalizeName(canonicalName);
  const familyKey = alias?.fuzzy ? normalizeName(alias.english) : normalizedKey;

  return {
    side,
    input: value,
    normalizedKey,
    familyKey,
    chinese: alias?.chinese ?? "",
    english: exactAlias?.english ?? value,
    latin: alias?.latin ?? "",
    matchedTerms: alias?.aliases.join("、") ?? value,
    exactAlias: Boolean(exactAlias),
    familyAlias: Boolean(familyAlias?.fuzzy)
  };
}

function uniqueResolvedComponents(values: string[], side: "detected" | "reference") {
  const seen = new Set<string>();
  const rows: ReturnType<typeof resolveCompareComponent>[] = [];
  for (const value of values) {
    const row = resolveCompareComponent(value, side);
    if (!row.normalizedKey || seen.has(row.normalizedKey)) continue;
    seen.add(row.normalizedKey);
    rows.push(row);
  }
  return rows;
}

function compareComponentsMultilingual(detectedValues: string[], referenceValues: string[]) {
  const detected = uniqueResolvedComponents(detectedValues, "detected");
  const reference = uniqueResolvedComponents(referenceValues, "reference");
  const detectedByKey = new Map(detected.map((row) => [row.normalizedKey, row]));
  const referenceByKey = new Map(reference.map((row) => [row.normalizedKey, row]));
  const exactKeys = Array.from(detectedByKey.keys()).filter((key) => referenceByKey.has(key));
  const detectedOnly = detected.filter((row) => !referenceByKey.has(row.normalizedKey));
  const referenceOnly = reference.filter((row) => !detectedByKey.has(row.normalizedKey));
  const exactMatches = exactKeys.map((key) => {
    const detectedRow = detectedByKey.get(key)!;
    const referenceRow = referenceByKey.get(key)!;
    return {
      normalizedKey: key,
      detectedInput: detectedRow.input,
      referenceInput: referenceRow.input,
      chinese: detectedRow.chinese || referenceRow.chinese,
      english: detectedRow.english || referenceRow.english,
      latin: detectedRow.latin || referenceRow.latin,
      status: "精确匹配"
    };
  });

  const familyMatches: Record<string, unknown>[] = [];
  for (const detectedRow of detectedOnly) {
    const relatedReferences = referenceOnly.filter((row) => row.familyKey && row.familyKey === detectedRow.familyKey && row.normalizedKey !== detectedRow.normalizedKey);
    for (const referenceRow of relatedReferences) {
      familyMatches.push({
        familyKey: detectedRow.familyKey,
        detectedInput: detectedRow.input,
        referenceInput: referenceRow.input,
        detectedEnglish: detectedRow.english,
        referenceEnglish: referenceRow.english,
        familyName: detectedRow.chinese || referenceRow.chinese || detectedRow.english || referenceRow.english,
        status: "同家族候选"
      });
    }
  }

  const rows = [
    ...exactMatches.map((row) => ({ ...row, group: "交集" })),
    ...detectedOnly.map((row) => ({
      group: "仅检测",
      normalizedKey: row.normalizedKey,
      input: row.input,
      chinese: row.chinese,
      english: row.english,
      latin: row.latin,
      status: "参考库未见"
    })),
    ...referenceOnly.map((row) => ({
      group: "仅参考",
      normalizedKey: row.normalizedKey,
      input: row.input,
      chinese: row.chinese,
      english: row.english,
      latin: row.latin,
      status: "检测值未见"
    }))
  ];
  const matchRate = reference.length ? Number(((exactMatches.length / reference.length) * 100).toFixed(2)) : 0;

  return {
    detected,
    reference,
    exactMatches,
    detectedOnly,
    referenceOnly,
    familyMatches,
    rows,
    counts: {
      detected: detected.length,
      reference: reference.length,
      matched: exactMatches.length,
      detectedOnly: detectedOnly.length,
      referenceOnly: referenceOnly.length,
      familyMatches: familyMatches.length,
      matchRate
    }
  };
}

export async function POST(request: Request) {
  try {
    await requireApiUser();
    const body = await request.json();
    const action = String(body.action || "") as ResearchAction;
    const baseUrl = String(process.env.NEXT_PUBLIC_FASTAPI_BASE_URL || "http://127.0.0.1:8010").replace(/\/$/, "");
    let url = "";
    let init: RequestInit = { cache: "no-store" };

    if (action === "pathway") {
      const query = String(body.query || "").trim();
      const catalogWhere = {
        externalId: { startsWith: "R-HSA-" },
        ...(query ? {
          OR: [
            { name: { contains: query } },
            { externalId: { contains: query.toUpperCase() } }
          ]
        } : {})
      };
      const startedAt = Date.now();
      const [items, catalogTotal, latest] = await Promise.all([
        prisma.pathway.findMany({
          where: catalogWhere,
          orderBy: { name: "asc" },
          take: 100,
          select: {
            name: true,
            externalId: true,
            species: true,
            sourceUrl: true,
            lastSyncedAt: true,
            _count: { select: { targets: true, enrichmentItems: true } }
          }
        }),
        prisma.pathway.count({ where: { externalId: { startsWith: "R-HSA-" } } }),
        prisma.pathway.findFirst({
          where: { externalId: { startsWith: "R-HSA-" } },
          orderBy: { lastSyncedAt: "desc" },
          select: { lastSyncedAt: true }
        })
      ]);
      return NextResponse.json({
        ok: true,
        action,
        elapsedMs: Date.now() - startedAt,
        data: {
          query,
          catalogTotal,
          sourceVersion: latest?.lastSyncedAt ? "97" : null,
          items: items.map((item) => ({
            stableId: item.externalId,
            name: item.name,
            species: item.species,
            sourceUrl: item.sourceUrl,
            lastSyncedAt: item.lastSyncedAt,
            targetAnnotations: item._count.targets,
            enrichmentRecords: item._count.enrichmentItems
          }))
        }
      });
    }

    if (["disease", "herb", "component", "chembl"].includes(action)) {
      const query = String(body.query || "").trim();
      if (!query) return jsonError("请输入检索词");
      const paths: Record<string, string> = {
        disease: "/api/search/disease",
        herb: "/api/search/herb",
        component: "/api/search/component",
        chembl: "/api/chembl/molecules"
      };
      if (action === "disease" && hasChinese(query)) {
        const queries = expandDiseaseQueries(query);
        const startedAt = Date.now();
        const results: unknown[] = [];
        for (const item of queries) {
          const response = await fetch(`${baseUrl}${paths[action]}?q=${encodeURIComponent(item)}&limit=100`, { cache: "no-store" });
          if (response.ok) results.push(await parseResponse(response));
        }
        if (!results.length) {
          return NextResponse.json({ ok: false, error: "中文疾病名未匹配到可用疾病记录，请换一个疾病名称或检查 FastAPI 数据服务" }, { status: 502 });
        }
        return NextResponse.json({ ok: true, action, elapsedMs: Date.now() - startedAt, data: mergeDiseaseResults(query, queries, results) });
      }
      if (action === "herb") {
        const queries = splitInputList(query).slice(0, 20);
        if (!queries.length) return jsonError("请输入中药名称");
        const startedAt = Date.now();
        const localData = searchLocalHerbs(query, queries);
        if (localData) {
          return NextResponse.json({ ok: true, action, elapsedMs: Date.now() - startedAt, data: localData });
        }
        const results: unknown[] = [];
        for (const item of queries) {
          const response = await fetch(`${baseUrl}${paths[action]}?q=${encodeURIComponent(item)}&limit=120`, { cache: "no-store" });
          if (response.ok) results.push(await parseResponse(response));
        }
        if (!results.length) {
          return NextResponse.json({ ok: false, error: "未检索到可用的中药记录，请更换中药名称或检查 FastAPI 数据服务" }, { status: 502 });
        }
        return NextResponse.json({ ok: true, action, elapsedMs: Date.now() - startedAt, data: mergeHerbResults(query, queries, results) });
      }
      if (action === "component") {
        const startedAt = Date.now();
        const localData = searchLocalComponents(query);
        if (localData) {
          return NextResponse.json({ ok: true, action, elapsedMs: Date.now() - startedAt, data: localData });
        }
      }
      if (action === "chembl") {
        const startedAt = Date.now();
        const data = await searchChemblMultilingual(baseUrl, paths[action], query);
        return NextResponse.json({ ok: true, action, elapsedMs: Date.now() - startedAt, data });
      }
      url = `${baseUrl}${paths[action]}?q=${encodeURIComponent(query)}&limit=100`;
    } else if (action === "intersection") {
      const left = splitInputList(body.left);
      const right = splitInputList(body.right);
      if (!left.length || !right.length) return jsonError("请分别输入两组靶点");
      url = `${baseUrl}/api/targets/intersection`;
      init = { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ left, right }) };
    } else if (action === "compare") {
      const detected = splitQueryList(body.detected);
      const reference = splitQueryList(body.reference);
      if (!detected.length || !reference.length) return jsonError("请分别输入检测成分和参考成分");
      const startedAt = Date.now();
      const data = compareComponentsMultilingual(detected, reference);
      return NextResponse.json({ ok: true, action, elapsedMs: Date.now() - startedAt, data });
    } else {
      return jsonError("不支持的检索类型");
    }

    const startedAt = Date.now();
    const response = await fetch(url, init);
    const data = await parseResponse(response);
    if (!response.ok) {
      return NextResponse.json({ ok: false, error: data?.detail || data?.error || `后端返回 ${response.status}` }, { status: 502 });
    }
    return NextResponse.json({ ok: true, action, elapsedMs: Date.now() - startedAt, data });
  } catch (error) {
    const message = error instanceof Error && error.message.includes("fetch failed")
      ? new Error("FastAPI 数据服务未启动，请先运行 start_fullstack.bat")
      : error;
    return handleRouteError(message);
  }
}
