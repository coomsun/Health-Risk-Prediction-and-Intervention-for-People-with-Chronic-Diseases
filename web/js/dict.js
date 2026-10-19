/* =============================================================
   dict.js —— 静态字典与口径常量
   注意：这里只有「契约元数据」（字段名 / 指标白名单 / FIPS 编码），
   不含任何业务数值；页面上所有统计数字都来自 REST API 响应。
   ============================================================= */
(function (NS) {
  'use strict';

  /* ---------- FIPS → 州名（API 的 stateName 多数只回 FIPS 数字，故本地补全） ---------- */
  var FIPS = {
    '01': ['阿拉巴马州', 'AL'], '02': ['阿拉斯加州', 'AK'], '04': ['亚利桑那州', 'AZ'],
    '05': ['阿肯色州', 'AR'], '06': ['加利福尼亚州', 'CA'], '08': ['科罗拉多州', 'CO'],
    '09': ['康涅狄格州', 'CT'], '10': ['特拉华州', 'DE'], '11': ['哥伦比亚特区', 'DC'],
    '12': ['佛罗里达州', 'FL'], '13': ['佐治亚州', 'GA'], '15': ['夏威夷州', 'HI'],
    '16': ['爱达荷州', 'ID'], '17': ['伊利诺伊州', 'IL'], '18': ['印第安纳州', 'IN'],
    '19': ['艾奥瓦州', 'IA'], '20': ['堪萨斯州', 'KS'], '21': ['肯塔基州', 'KY'],
    '22': ['路易斯安那州', 'LA'], '23': ['缅因州', 'ME'], '24': ['马里兰州', 'MD'],
    '25': ['马萨诸塞州', 'MA'], '26': ['密歇根州', 'MI'], '27': ['明尼苏达州', 'MN'],
    '28': ['密西西比州', 'MS'], '29': ['密苏里州', 'MO'], '30': ['蒙大拿州', 'MT'],
    '31': ['内布拉斯加州', 'NE'], '32': ['内华达州', 'NV'], '33': ['新罕布什尔州', 'NH'],
    '34': ['新泽西州', 'NJ'], '35': ['新墨西哥州', 'NM'], '36': ['纽约州', 'NY'],
    '37': ['北卡罗来纳州', 'NC'], '38': ['北达科他州', 'ND'], '39': ['俄亥俄州', 'OH'],
    '40': ['俄克拉何马州', 'OK'], '41': ['俄勒冈州', 'OR'], '42': ['宾夕法尼亚州', 'PA'],
    '44': ['罗得岛州', 'RI'], '45': ['南卡罗来纳州', 'SC'], '46': ['南达科他州', 'SD'],
    '47': ['田纳西州', 'TN'], '48': ['得克萨斯州', 'TX'], '49': ['犹他州', 'UT'],
    '50': ['佛蒙特州', 'VT'], '51': ['弗吉尼亚州', 'VA'], '53': ['华盛顿州', 'WA'],
    '54': ['西弗吉尼亚州', 'WV'], '55': ['威斯康星州', 'WI'], '56': ['怀俄明州', 'WY'],
    '60': ['美属萨摩亚', 'AS'], '66': ['关岛', 'GU'], '69': ['北马里亚纳群岛', 'MP'],
    '72': ['波多黎各', 'PR'], '78': ['美属维尔京群岛', 'VI']
  };

  /* 地图几何里没有的 FIPS（vendor/us-states.geo.js 只含 50 州 + DC + PR） */
  var NO_GEOMETRY = ['60', '66', '69', '78'];

  function padFips(fips) {
    var s = String(fips == null ? '' : fips);
    return s.length >= 2 ? s : ('0' + s);
  }
  function stateName(fips) {
    var hit = FIPS[padFips(fips)];
    return hit ? hit[0] : ('未知州(' + padFips(fips) + ')');
  }
  function stateShort(fips) {
    var hit = FIPS[padFips(fips)];
    return hit ? hit[1] : padFips(fips);
  }
  function stateFull(fips) {
    var hit = FIPS[padFips(fips)];
    return hit ? (hit[0] + ' ' + hit[1]) : ('未知州(' + padFips(fips) + ')');
  }

  /* ---------- 趋势 / 地图 指标白名单（与 api/queries.py TREND_METRICS 一致） ---------- */
  var METRICS = [
    { key: 'multimorbidity_rate', label: '共病率', unit: 'ratio', group: '核心' },
    { key: 'chronic_avg', label: '人均慢病数', unit: 'count', group: '核心' },
    { key: 'total_samples', label: '样本量', unit: 'count', group: '核心' },
    { key: 'obese_rate', label: '肥胖率(BMI≥30)', unit: 'ratio', group: '危险因素' },
    { key: 'smoker_rate', label: '现吸烟率', unit: 'ratio', group: '危险因素' },
    { key: 'inactivity_rate', label: '缺乏运动率', unit: 'ratio', group: '危险因素' },
    { key: 'heavy_drink_rate', label: '重度饮酒率', unit: 'ratio', group: '危险因素' },
    { key: 'diabetes_rate', label: '糖尿病患病率', unit: 'ratio', group: '慢病' },
    { key: 'mi_rate', label: '心肌梗死患病率', unit: 'ratio', group: '慢病' },
    { key: 'chd_rate', label: '冠心病患病率', unit: 'ratio', group: '慢病' },
    { key: 'stroke_rate', label: '卒中患病率', unit: 'ratio', group: '慢病' },
    { key: 'copd_rate', label: '慢阻肺患病率', unit: 'ratio', group: '慢病' },
    { key: 'asthma_rate', label: '哮喘患病率', unit: 'ratio', group: '慢病' },
    { key: 'kidney_rate', label: '慢性肾病患病率', unit: 'ratio', group: '慢病' },
    { key: 'depression_rate', label: '抑郁患病率', unit: 'ratio', group: '慢病' }
  ];
  var METRIC_BY_KEY = {};
  METRICS.forEach(function (m) { METRIC_BY_KEY[m.key] = m; });

  /* 慢病 key（/chronic/prevalence 的 items[].key）→ 趋势指标 */
  var DISEASE_TO_METRIC = {
    diabetes: 'diabetes_rate', mi: 'mi_rate', chd: 'chd_rate', stroke: 'stroke_rate',
    copd: 'copd_rate', asthma: 'asthma_rate', kidney: 'kidney_rate', depression: 'depression_rate'
  };

  /* 危险因素 key（/risk/factors 的 items[].key）→ 趋势指标；无对应者不在表中。
     后端在不同阶段的 key 命名有别名（如 no_physical_activity / no_phys_activity），
     这里同时登记，避免契约微调导致联动静默失效。 */
  var FACTOR_TO_METRIC = {
    obese: 'obese_rate',
    current_smoker: 'smoker_rate',
    no_physical_activity: 'inactivity_rate',
    no_phys_activity: 'inactivity_rate',
    heavy_drink: 'heavy_drink_rate'
  };

  /* 危险因素 key 别名（历史命名 → 当前契约命名），仅用于把接口返回的 key 归一到规则里用的名字 */
  var FACTOR_ALIAS = {
    no_phys_activity: 'no_physical_activity',
    diff_walk: 'walking_difficulty',
    fair_poor_health: 'fair_or_poor_health',
    checkup_over_1y: 'never_checkup'
  };

  /* ---------- 图表色板（与 CSS 变量同源，供 ECharts 使用） ---------- */
  var PALETTE = {
    primary: '#4f8cff', cyan: '#22d3ee', teal: '#2dd4bf', green: '#34d399',
    amber: '#f5a524', rose: '#fb7185', violet: '#a78bfa', fuchsia: '#e879f9',
    low: '#34d399', mid: '#f5a524', high: '#fb7185',
    text: '#e8eefb', text2: '#a7b6d1', dim: '#7b8cae',
    axis: '#a7b6d1', line: 'rgba(120,152,200,0.18)', lineStrong: 'rgba(120,152,200,0.34)',
    panel: '#101a2c', bg: '#0b1322'
  };
  /* 8 类慢病固定配色，保证与其他区块联动时颜色语义一致 */
  var DISEASE_COLOR = {
    diabetes: PALETTE.rose, mi: PALETTE.amber, chd: PALETTE.violet, stroke: PALETTE.teal,
    copd: PALETTE.cyan, asthma: PALETTE.green, kidney: PALETTE.primary, depression: PALETTE.fuchsia
  };

  /* 指标 → 展示色（与慢病/因素条形同一语义色，联动时颜色一致） */
  var METRIC_COLOR = {
    multimorbidity_rate: PALETTE.primary,
    chronic_avg: PALETTE.green,
    total_samples: PALETTE.cyan,
    obese_rate: PALETTE.violet,
    smoker_rate: PALETTE.fuchsia,
    inactivity_rate: PALETTE.teal,
    heavy_drink_rate: PALETTE.cyan
  };
  Object.keys(DISEASE_TO_METRIC).forEach(function (key) {
    METRIC_COLOR[DISEASE_TO_METRIC[key]] = DISEASE_COLOR[key];
  });
  function metricColor(metric) {
    return METRIC_COLOR[metric] || PALETTE.primary;
  }

  /* ---------- 数值格式化 ---------- */
  function pct(ratio, digits) {
    if (ratio == null || isNaN(ratio)) return '—';
    return (Number(ratio) * 100).toFixed(digits == null ? 2 : digits) + '%';
  }
  function int(n) {
    if (n == null || isNaN(n)) return '—';
    return Number(n).toLocaleString('en-US');
  }
  function compact(n) {
    if (n == null || isNaN(n)) return '—';
    var v = Number(n);
    if (v >= 1e8) return (v / 1e8).toFixed(2) + ' 亿';
    if (v >= 1e4) return (v / 1e4).toFixed(1) + ' 万';
    return int(v);
  }
  function metricValue(metric, value) {
    var def = METRIC_BY_KEY[metric];
    if (value == null || isNaN(value)) return '—';
    if (!def) return String(value);
    if (def.unit === 'ratio') return pct(value);
    return def.key === 'chronic_avg' ? Number(value).toFixed(3) + ' 种/人' : int(value) + ' 人';
  }
  function metricUnit(metric) {
    var def = METRIC_BY_KEY[metric];
    if (!def) return '';
    return def.unit === 'ratio' ? '率(%)' : (def.key === 'chronic_avg' ? '种/人' : '人');
  }

  /* ---------- 在线预测：字段口径字典（与 api/main.py PredictRequest 一致） ---------- */
  var AGE_GROUPS = [
    [1, '18-24'], [2, '25-29'], [3, '30-34'], [4, '35-39'], [5, '40-44'], [6, '45-49'],
    [7, '50-54'], [8, '55-59'], [9, '60-64'], [10, '65-69'], [11, '70-74'], [12, '75-79'], [13, '80+']
  ];
  var PREDICT_FIELDS = [
    { name: 'age_grp', label: '年龄组（_AGEG5YR）', type: 'select', options: AGE_GROUPS.map(function (g) { return [g[0], g[1] + ' 岁']; }), default: 8 },
    { name: 'sex', label: '性别（_SEX）', type: 'select', options: [[1, '男'], [2, '女']], default: 1 },
    { name: 'bmi', label: 'BMI（bmi）', type: 'number', min: 10, max: 70, step: 0.1, default: 26.5 },
    { name: 'smoker3', label: '吸烟状态（_SMOKER3）', type: 'select', options: [[1, '每日吸'], [2, '部分日吸'], [3, '曾经吸'], [4, '从不吸']], default: 4 },
    { name: 'phys_activity', label: '体育锻炼（_TOTINDA）', type: 'select', options: [[1, '有锻炼'], [0, '无锻炼']], default: 1 },
    { name: 'genhlth', label: '自评健康（GENHLTH）', type: 'select', options: [[1, '优'], [2, '很好'], [3, '好'], [4, '一般'], [5, '差']], default: 3 },
    { name: 'diffwalk', label: '行走困难（DIFFWALK）', type: 'select', options: [[1, '是'], [0, '否']], default: 0 },
    { name: 'medcost', label: '费用障碍（MEDCOST）', type: 'select', options: [[1, '是'], [0, '否']], default: 0 },
    { name: 'menthlth', label: '心理不良天数（0-30）', type: 'number', min: 0, max: 30, step: 1, default: 0 },
    { name: 'educa', label: '教育（EDUCA）', type: 'select', options: [[1, '未上学'], [2, '小学'], [3, '初中'], [4, '高中'], [5, '大学肄业'], [6, '大学毕业']], default: 4 },
    { name: 'income_grp', label: '收入组（_INCOMG）', type: 'select', options: [[1, '<1.5万$'], [2, '1.5-2万$'], [3, '2-2.5万$'], [4, '2.5-3.5万$'], [5, '3.5-5万$'], [6, '5-7.5万$'], [7, '7.5-10万$'], [8, '≥10万$']], default: 5 },
    { name: 'checkup', label: '常规体检（CHECKUP1）', type: 'select', options: [[1, '1 年内'], [2, '2 年内'], [3, '5 年内'], [8, '从未']], default: 1 }
  ];

  /* ---------- 干预建议规则（依据输入特征命中；暴露率由接口回填） ---------- */
  var ADVICE_RULES = [
    {
      id: 'smoking', match: function (v) { return v.smoker3 === 1 || v.smoker3 === 2; },
      tier: '高优先级', factorKey: 'current_smoker',
      text: '戒烟干预：转介戒烟门诊 / 尼古丁替代疗法，重点降低心血管与慢阻肺风险'
    },
    {
      id: 'inactivity', match: function (v) { return v.phys_activity === 0; },
      tier: '高优先级', factorKey: 'no_physical_activity',
      text: '运动处方：从每周 3×20 分钟快走起步，逐步达到每周 ≥150 分钟中等强度活动'
    },
    {
      id: 'obesity', match: function (v) { return v.bmi != null && v.bmi >= 30; },
      tier: '高优先级', factorKey: 'obese',
      text: '体重管理：以减重 5%–10% 为 6 个月目标，配合营养师随访与腰围监测'
    },
    {
      id: 'poor_health', match: function (v) { return v.genhlth != null && v.genhlth >= 4; },
      tier: '中优先级', factorKey: 'fair_or_poor_health',
      text: '自评健康偏差：安排综合健康评估（含慢病并发症筛查）并缩短随访间隔'
    },
    {
      id: 'diffwalk', match: function (v) { return v.diffwalk === 1 || v.diffwalk === 2; },
      tier: '中优先级', factorKey: 'walking_difficulty',
      text: '行走受限：转康复科做运动能力评估，制定低冲击训练与跌倒预防方案'
    },
    {
      id: 'menthlth', match: function (v) { return v.menthlth != null && v.menthlth >= 14; },
      tier: '中优先级', factorKey: 'frequent_mental_distress',
      text: '心理干预：PHQ-9 / GAD-7 筛查，必要时转介心理科并纳入共病管理'
    },
    {
      id: 'medcost', match: function (v) { return v.medcost === 1; },
      tier: '中优先级', factorKey: 'cost_barrier',
      text: '费用障碍：对接医保补助与社区免费筛查，避免因费用中断长期用药'
    },
    {
      id: 'checkup', match: function (v) { return v.checkup === 8; },
      tier: '中优先级', factorKey: 'never_checkup',
      text: '无体检记录：建立年度常规体检流程，优先覆盖血压、血糖、血脂三项'
    },
    {
      id: 'age', match: function (v) { return v.age_grp != null && v.age_grp >= 10; },
      tier: '基础', factorKey: null,
      text: '年龄 ≥65 岁：按老年共病管理路径提高筛查频次，关注多重用药风险'
    }
  ];

  NS.dict = {
    FIPS: FIPS, NO_GEOMETRY: NO_GEOMETRY,
    padFips: padFips, stateName: stateName, stateShort: stateShort, stateFull: stateFull,
    METRICS: METRICS, METRIC_BY_KEY: METRIC_BY_KEY,
    DISEASE_TO_METRIC: DISEASE_TO_METRIC, FACTOR_TO_METRIC: FACTOR_TO_METRIC, FACTOR_ALIAS: FACTOR_ALIAS,
    PALETTE: PALETTE, DISEASE_COLOR: DISEASE_COLOR,
    AGE_GROUPS: AGE_GROUPS, PREDICT_FIELDS: PREDICT_FIELDS, ADVICE_RULES: ADVICE_RULES,
    pct: pct, int: int, compact: compact, metricValue: metricValue, metricUnit: metricUnit,
    METRIC_COLOR: METRIC_COLOR, metricColor: metricColor
  };
})(window.BRFSS = window.BRFSS || {});
