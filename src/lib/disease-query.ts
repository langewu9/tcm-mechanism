export type DiseaseResolution = {
  original: string;
  queries: string[];
  matchedNames: string[];
};

const exactAliases: Array<{ patterns: RegExp[]; aliases: string[] }> = [
  { patterns: [/肺纤维化|肺間質纤维|间质性肺/], aliases: ["Pulmonary fibrosis", "Idiopathic pulmonary fibrosis", "Interstitial lung disease"] },
  { patterns: [/阿尔茨海默|老年痴呆/], aliases: ["Alzheimer's Disease", "Alzheimer"] },
  { patterns: [/帕金森/], aliases: ["Parkinson", "Parkinson's disease"] },
  { patterns: [/肌萎缩侧索硬化|渐冻症/], aliases: ["Amyotrophic lateral sclerosis"] },
  { patterns: [/中风|卒中|脑卒中/], aliases: ["Stroke", "Cerebral Infarction", "Brain ischemia", "Cerebral ischemia"] },
  { patterns: [/脑梗|脑梗死/], aliases: ["Cerebral Infarction", "Brain ischemia", "Cerebral ischemia"] },
  { patterns: [/冠心病|冠状动脉/], aliases: ["Coronary", "Acute coronary syndromes", "Cardiovascular disease"] },
  { patterns: [/心肌梗死|心梗/], aliases: ["Myocardial infarction", "Acute coronary syndromes"] },
  { patterns: [/心力衰竭|心衰/], aliases: ["Heart failure", "Cardiac failure"] },
  { patterns: [/心律失常|房颤|心房颤动/], aliases: ["Cardiac arrhythmias", "Atrial fibrillation and flutter", "Cardiac dysrhythmias"] },
  { patterns: [/动脉粥样硬化|粥样硬化/], aliases: ["Atherosclerosis"] },
  { patterns: [/高血压/], aliases: ["Hypertension"] },
  { patterns: [/糖尿病/], aliases: ["Diabetes", "Diabetes Mellitus"] },
  { patterns: [/哮喘|支气管哮喘/], aliases: ["Asthma", "Bronchial asthma", "Atopic asthma"] },
  { patterns: [/慢阻肺|慢性阻塞性肺/], aliases: ["Chronic obstructive pulmonary disease", "COPD"] },
  { patterns: [/过敏性鼻炎/], aliases: ["Allergic rhinitis"] },
  { patterns: [/类风湿/], aliases: ["Arthritis, Rheumatoid", "Rheumatoid Arthritis"] },
  { patterns: [/银屑病|牛皮癣/], aliases: ["Psoriasis"] },
  { patterns: [/特应性皮炎|异位性皮炎/], aliases: ["Atopic Dermatitis"] },
  { patterns: [/痤疮|粉刺/], aliases: ["Acne"] },
  { patterns: [/乳腺癌/], aliases: ["Breast cancer", "Breast Neoplasms"] },
  { patterns: [/肺癌/], aliases: ["Lung cancer", "Non-Small-Cell Lung", "Carcinoma, Non-Small-Cell Lung"] },
  { patterns: [/非小细胞肺癌/], aliases: ["Non-Small-Cell Lung", "Advanced or metastatic non-small cell lung cancer"] },
  { patterns: [/肝癌/], aliases: ["Liver cancer", "Hepatocellular carcinoma"] },
  { patterns: [/胃癌/], aliases: ["Gastric cancer", "Stomach cancer"] },
  { patterns: [/结直肠癌|结肠癌|直肠癌|肠癌/], aliases: ["Colorectal cancer", "Colon cancer", "Rectal cancer"] },
  { patterns: [/前列腺癌/], aliases: ["Prostate cancer"] },
  { patterns: [/前列腺增生/], aliases: ["Benign prostate hyperplasia"] },
  { patterns: [/膀胱癌/], aliases: ["Bladder cancer"] },
  { patterns: [/宫颈癌|子宫颈癌/], aliases: ["Cervical cancer"] },
  { patterns: [/卵巢癌/], aliases: ["Ovarian cancer"] },
  { patterns: [/胰腺癌/], aliases: ["Pancreatic cancer"] },
  { patterns: [/肾癌/], aliases: ["Renal cancer", "Kidney cancer"] },
  { patterns: [/脑肿瘤|脑癌/], aliases: ["Brain tumors", "Brain Cancer"] },
  { patterns: [/白血病/], aliases: ["Leukemia", "Leukaemia"] },
  { patterns: [/淋巴瘤/], aliases: ["Lymphoma"] },
  { patterns: [/黑色素瘤/], aliases: ["Melanoma"] },
  { patterns: [/抑郁/], aliases: ["Depression", "Depressive disorder"] },
  { patterns: [/焦虑/], aliases: ["Anxiety Disorders", "Anxiety disorder"] },
  { patterns: [/癫痫|惊厥|抽搐/], aliases: ["Epilepsy", "Seizure", "Childhood seizure disorders"] },
  { patterns: [/偏头痛/], aliases: ["Migraine", "Acute migraine"] },
  { patterns: [/艾滋|获得性免疫缺陷|HIV/], aliases: ["AIDS", "HIV", "AIDS related dementia"] },
  { patterns: [/贫血/], aliases: ["Anemia"] },
  { patterns: [/肥胖/], aliases: ["Obesity"] },
  { patterns: [/酒精依赖|酒精中毒/], aliases: ["Alcohol dependence", "Alcoholism"] },
  { patterns: [/黄斑变性/], aliases: ["Age-related macular degeneration"] },
  { patterns: [/中耳炎/], aliases: ["Acute otitis media"] },
  { patterns: [/普通感冒|感冒/], aliases: ["Acute nasopharyngitis", "common cold"] },
  { patterns: [/疟疾/], aliases: ["Malaria"] },
  { patterns: [/阿米巴病/], aliases: ["Amebiasis"] },
  { patterns: [/锥虫病/], aliases: ["Trypanosomiasis", "African trypanosomiasis", "Chagas"] }
];

const tokenGroups: Array<{ pattern: RegExp; terms: string[] }> = [
  { pattern: /肺|支气管|气道|呼吸/, terms: ["pulmonary", "lung", "bronchial", "airway", "respiratory"] },
  { pattern: /心|冠状|房颤|心肌/, terms: ["cardiac", "heart", "coronary", "atrial", "cardiovascular"] },
  { pattern: /脑|神经|中枢|认知/, terms: ["brain", "cerebral", "central nervous", "neurological", "cognitive"] },
  { pattern: /肝/, terms: ["liver", "hepatic"] },
  { pattern: /肾/, terms: ["kidney", "renal", "nephro"] },
  { pattern: /胃/, terms: ["gastric", "stomach"] },
  { pattern: /肠|结肠|直肠|肠道/, terms: ["intestinal", "colon", "rectal", "colorectal", "bowel"] },
  { pattern: /乳腺|乳房/, terms: ["breast"] },
  { pattern: /前列腺/, terms: ["prostate"] },
  { pattern: /膀胱/, terms: ["bladder"] },
  { pattern: /宫颈|子宫颈/, terms: ["cervical"] },
  { pattern: /卵巢/, terms: ["ovarian"] },
  { pattern: /皮肤|皮炎/, terms: ["skin", "dermatitis", "atopic"] },
  { pattern: /骨|软骨/, terms: ["bone", "chondro"] },
  { pattern: /眼|视网膜|黄斑/, terms: ["ocular", "macular", "retinal"] },
  { pattern: /耳|听力/, terms: ["otitis", "hearing", "sensorineural"] },
  { pattern: /血|血小板/, terms: ["blood", "platelet", "hematological"] },
  { pattern: /癌|肿瘤|瘤|恶性/, terms: ["cancer", "neoplasm", "tumor", "tumour", "carcinoma", "sarcoma", "malignan"] },
  { pattern: /白血病/, terms: ["leukemia", "leukaemia"] },
  { pattern: /淋巴瘤/, terms: ["lymphoma"] },
  { pattern: /炎|炎症/, terms: ["inflammation", "inflammatory", "itis"] },
  { pattern: /纤维化/, terms: ["fibrosis"] },
  { pattern: /硬化/, terms: ["sclerosis"] },
  { pattern: /缺血/, terms: ["ischemia", "ischaemia"] },
  { pattern: /梗死/, terms: ["infarction"] },
  { pattern: /栓塞/, terms: ["embolism"] },
  { pattern: /血栓/, terms: ["thrombosis"] },
  { pattern: /增生/, terms: ["hyperplasia"] },
  { pattern: /过敏|变态反应/, terms: ["allergic", "allergy", "atopy", "anaphylaxis"] },
  { pattern: /感染/, terms: ["infection", "infections"] },
  { pattern: /变性/, terms: ["degeneration", "degenerative"] },
  { pattern: /疼痛|痛|绞痛/, terms: ["pain", "analgesic", "colic"] },
  { pattern: /高血压/, terms: ["hypertension"] },
  { pattern: /糖尿病/, terms: ["diabetes"] },
  { pattern: /贫血/, terms: ["anemia", "anaemia"] },
  { pattern: /免疫|自身免疫/, terms: ["immune", "autoimmune"] }
];

function unique(values: string[]) {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
}

export function hasChinese(value: string) {
  return /[\u3400-\u9fff]/.test(value);
}

export function expandDiseaseQueries(query: string) {
  const original = query.trim();
  const aliases: string[] = [original];
  for (const entry of exactAliases) {
    if (entry.patterns.some((pattern) => pattern.test(original))) aliases.push(...entry.aliases);
  }

  const groups = tokenGroups.filter((group) => group.pattern.test(original));
  if (!aliases.some((item) => item !== original) && groups.length) {
    aliases.push(...groups.flatMap((group) => group.terms));
    if (groups.length >= 2) {
      for (const left of groups[0].terms.slice(0, 3)) {
        for (const right of groups[1].terms.slice(0, 4)) aliases.push(`${left} ${right}`);
      }
    }
  }

  return unique(aliases).slice(0, 40);
}

export function resolveDiseaseQueries(query: string, availableNames: string[] = []): DiseaseResolution {
  const original = query.trim();
  const aliases = expandDiseaseQueries(original);
  const groups = tokenGroups.filter((group) => group.pattern.test(original));
  const lowerAvailable = availableNames.map((name) => ({ name, lower: name.toLowerCase() }));
  const matchedNames = lowerAvailable
    .filter(({ lower }) => {
      if (!groups.length) return aliases.some((alias) => lower.includes(alias.toLowerCase()));
      const required = Math.min(groups.length, 2);
      const score = groups.reduce((total, group) => total + (group.terms.some((term) => lower.includes(term)) ? 1 : 0), 0);
      return score >= required || aliases.some((alias) => alias !== original && lower.includes(alias.toLowerCase()));
    })
    .map((item) => item.name);

  return {
    original,
    matchedNames: unique(matchedNames).slice(0, 80),
    queries: unique([...matchedNames, ...aliases]).slice(0, 120)
  };
}
