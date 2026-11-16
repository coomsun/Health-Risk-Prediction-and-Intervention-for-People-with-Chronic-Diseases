/* =============================================================
   data.js —— 数据中枢：快照加载 + 在线 API 双模 + 预测推理
   · 离线：读取 pipeline/12_export_screen.py 导出的真实聚合快照
     （http 服务下 fetch JSON；file:// 下回退到内嵌 snapshots.js）
   · 在线：探测 /api/v1/health 成功后，核心 KPI 走 REST 实时查询，
     预测走 JWT 保护的 /api/v1/predict（LightGBM 服务端推理）
   · 离线预测：浏览器内用导出的 Logistic 回归系数做真实推理（非假数据）
   ============================================================= */
(function (NS) {
  'use strict';
  var Store = NS.store, D = NS.dict;

  var FILES = ['meta', 'overview', 'diseases', 'trends', 'geo', 'factors', 'association', 'population', 'model', 'predict_offline'];
  var KEY_MAP = { predict_offline: 'predictOffline' };

  function resolveBase() {
    var q = null;
    try { q = new URLSearchParams(location.search).get('api'); } catch (e) {}
    var ls = null;
    try { ls = localStorage.getItem('brfss.screen.apiBase'); } catch (e) {}
    var base = q || ls || ((location.protocol === 'http:' || location.protocol === 'https:') ? location.origin : 'http://127.0.0.1:8000');
    if (q) { try { localStorage.setItem('brfss.screen.apiBase', q); } catch (e) {} }
    return String(base).replace(/\/+$/, '');
  }

  function fetchJson(url, timeoutMs, body, method) {
    var ctl = new AbortController();
    var t = setTimeout(function () { ctl.abort(); }, timeoutMs || 8000);
    var init = { signal: ctl.signal, cache: 'no-store', headers: { Accept: 'application/json' }, method: method || (body !== undefined ? 'POST' : 'GET') };
    if (body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
    return fetch(url, init)
      .then(function (r) { clearTimeout(t); if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .catch(function (e) { clearTimeout(t); throw e; });
  }

  var Hub = {
    /* ---------------- 快照加载 ---------------- */
    loadSnapshots: function () {
      Store.apiBase = resolveBase();
      var embedded = window.BRFSS_SNAPSHOTS || null;
      var tasks = FILES.map(function (name) {
        var key = KEY_MAP[name] || name;
        return fetchJson('data/' + name + '.json', 8000)
          .then(function (json) { Store.data[key] = json; })
          .catch(function () {
            if (embedded && embedded[name]) { Store.data[key] = embedded[name]; }
            else throw new Error('快照 ' + name + ' 加载失败');
          })
          .then(function () { Store.loadedCount++; });
      });
      return Promise.all(tasks).then(function () {
        Store.ready = true;
        Store.dataSource = '快照';
      }).catch(function (err) {
        Store.loadError = '数据快照加载失败：' + err.message + '。请通过 HTTP 服务打开（如 python -m http.server 5500 -d web），或先运行 pipeline/12_export_screen.py 生成快照。';
        throw err;
      });
    },

    /* ---------------- 在线探测 ---------------- */
    probeApi: function () {
      var t0 = performance.now();
      return fetchJson(Store.apiBase + '/api/v1/health', 3000)
        .then(function (env) {
          if (!env || env.code !== 0) throw new Error('信封异常');
          Store.apiLatency = Math.round(performance.now() - t0);
          Store.health = env.data;
          Store.mode = 'online';
          Store.dataSource = 'REST API';
          return Hub.refreshOnline();
        })
        .catch(function () {
          Store.mode = 'offline';
          Store.dataSource = '快照';
          Store.health = null;
        });
    },

    apiGet: function (path, params) {
      var url = Store.apiBase + path;
      if (params) {
        var qs = Object.keys(params).filter(function (k) { return params[k] != null && params[k] !== ''; })
          .map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]); }).join('&');
        if (qs) url += '?' + qs;
      }
      var t0 = performance.now();
      return fetchJson(url, 12000).then(function (env) {
        Store.apiLatency = Math.round(performance.now() - t0);
        if (!env || env.code !== 0) throw new Error((env && env.message) || '业务错误');
        return env.data;
      });
    },

    /* 在线模式：用实时 API 覆盖核心聚合（扩展维度仍用管道快照） */
    refreshOnline: function () {
      if (Store.mode !== 'online') return Promise.resolve();
      var f = Store.filters;
      var jobs = [
        Hub.apiGet('/api/v1/overview').then(function (d) {
          var ov = Store.data.overview || {};
          Store.data.overview = Object.assign({}, ov, d, { riskLevels: ov.riskLevels, chronicDist: ov.chronicDist, topStates: ov.topStates });
        }),
        Hub.apiGet('/api/v1/chronic/prevalence', { year: f.year, state: f.state }).then(function (d) {
          var ds = Store.data.diseases; if (!ds) return;
          var ci = {}; ds.items.forEach(function (x) { ci[x.key] = x.ci95; });
          ds.items = d.items.map(function (x) { return Object.assign({}, x, { ci95: ci[x.key] }); })
            .sort(function (a, b) { return (b.prevalence || 0) - (a.prevalence || 0); });
        }),
        Hub.apiGet('/api/v1/risk/factors', { year: f.year }).then(function (d) {
          if (Store.data.factors && d.items) Store.data.factors.items = d.items;
        }),
        Hub.apiGet('/api/v1/risk/stratify').then(function (d) {
          var ov = Store.data.overview, pp = Store.data.population;
          if (ov && d.levels) ov.riskLevels = d.levels;
          if (ov && d.distribution) ov.chronicDist = d.distribution;
          if (pp) { if (d.levels) pp.riskLevels = d.levels; if (d.distribution) pp.chronicDist = d.distribution; if (d.byAge) pp.byAge = d.byAge; }
        })
      ];
      return Promise.all(jobs.map(function (p) { return p.catch(function (e) { console.warn('[screen] 在线刷新降级:', e.message); }); }));
    },

    onFilterChange: function () {
      if (Store.mode === 'online') Hub.refreshOnline();
    },
    onGeoMetricChange: function (metric) {
      if (Store.mode !== 'online') return;
      Hub.apiGet('/api/v1/geo/states', { metric: metric }).then(function (d) {
        var geo = Store.data.geo; if (!geo) return;
        var hit = geo.metrics.find(function (m) { return m.key === metric; });
        if (hit) hit.items = d.items; else geo.metrics.push(d);
      }).catch(function () {});
    },

    retryApi: function () {
      Store.mode = 'loading';
      return Hub.probeApi().then(function () {
        Store.toast(Store.mode === 'online' ? '已连接后端 API（实时模式）' : '后端不可达，使用离线快照模式');
      });
    },

    /* ---------------- 预测 ---------------- */
    predict: function () {
      var form = Store.predict.form;
      Store.predict.loading = true; Store.predict.error = null; Store.predict.result = null;
      var p = Store.mode === 'online' ? Hub.predictOnline(form) : Promise.resolve(Hub.predictOffline(form));
      return p.then(function (res) { Store.predict.result = res; Store.predict.loading = false; })
        .catch(function (err) {
          Store.predict.loading = false;
          Store.predict.error = err.message || '预测失败';
          /* 在线失败时降级到浏览器离线模型，保证演示不中断 */
          if (Store.mode === 'online' && Store.data.predictOffline) {
            try {
              var res = Hub.predictOffline(form);
              res.degraded = true;
              Store.predict.result = res;
              Store.predict.error = '在线预测失败（' + err.message + '），已降级为浏览器离线模型';
            } catch (e2) { /* 保留原错误 */ }
          }
        });
    },

    predictOnline: function (form) {
      var body = {};
      Object.keys(form).forEach(function (k) { if (form[k] != null && form[k] !== '') body[k] = Number(form[k]); });
      if (Store.filters.year) body.year = Store.filters.year;
      if (Store.filters.state) body.state_fips = Store.filters.state;
      /* 与离线路径同口径：age_grp（1..13 档）换算成连续年龄，obese 由 bmi 派生 */
      var off = Store.data.predictOffline;
      if (off && off.ageMid) {
        var mid = off.ageMid[body.age_grp];
        if (mid != null) body.age = Math.min(80, Math.max(0, mid));
      }
      if (body.bmi != null) body.obese = body.bmi >= 30 ? 1 : 0;
      return Hub.login().then(function (tk) {
        var t0 = performance.now();
        return fetch(Store.apiBase + '/api/v1/predict', {
          method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json', Authorization: 'Bearer ' + tk },
          body: JSON.stringify(body)
        }).then(function (r) { return r.json().then(function (env) { return { env: env, ms: Math.round(performance.now() - t0) }; }); })
          .then(function (o) {
            if (!o.env || o.env.code !== 0) throw new Error((o.env && o.env.message) || ('HTTP 错误'));
            var d = o.env.data;
            return {
              probability: d.probability, prediction: d.prediction, riskLevel: d.riskLevel,
              thresholds: d.thresholds, source: 'online', latencyMs: d.latencyMs != null ? d.latencyMs : o.ms,
              modelName: (d.model && d.model.fileName) || 'LightGBM', modelFeatures: d.model && d.model.featureNames,
              missingFeatures: d.missingFeatures || [], features: d.features
            };
          });
      });
    },

    _token: null, _tokenExp: 0,
    login: function () {
      if (Hub._token && Date.now() < Hub._tokenExp - 60000) return Promise.resolve(Hub._token);
      return fetchJson(Store.apiBase + '/api/v1/auth/login', 6000, { username: 'demo', password: 'demo12345' }, 'POST')
        .then(function (env) {
          if (!env || env.code !== 0) throw new Error('登录失败');
          Hub._token = env.data.accessToken;
          Hub._tokenExp = Date.now() + (env.data.expiresIn || 3600) * 1000;
          return Hub._token;
        });
    },

    /* 浏览器内真实 Logistic 回归推理（系数由 12_export_screen.py 训练导出） */
    predictOffline: function (form) {
      var m = Store.data.predictOffline;
      if (!m) throw new Error('离线模型未加载');
      var t0 = performance.now();
      var raw = {};
      m.features.forEach(function (f) { raw[f] = m.medians[f]; });
      raw.sex = Number(form.sex); raw.age = m.ageMid[form.age_grp] != null ? m.ageMid[form.age_grp] : m.medians.age;
      raw.bmi = Number(form.bmi); raw.obese = Number(form.bmi) >= 30 ? 1 : 0;
      raw.smoker3 = Number(form.smoker3); raw.phys_activity = Number(form.phys_activity);
      raw.educa = Number(form.educa); raw.income_grp = Number(form.income_grp);
      raw.medcost = Number(form.medcost); raw.checkup = Number(form.checkup);
      if (Store.filters.year) raw.year = Store.filters.year;
      if (Store.filters.state) raw.state_fips = Store.filters.state;
      var z = 0, used = [];
      m.features.forEach(function (f, i) {
        var x = raw[f];
        if (x == null || isNaN(x)) x = m.medians[f];
        if (x == null) x = m.mean[i];
        var scale = m.scale[i] || 1;
        z += m.coef[i] * ((x - m.mean[i]) / scale);
        used.push(f);
      });
      var prob = 1 / (1 + Math.exp(-(z + m.intercept)));
      var th = m.thresholds || { low: 0.10, high: 0.30 };
      var level = prob >= th.high ? '高风险' : prob >= th.low ? '中风险' : '低风险';
      return {
        probability: Math.round(prob * 1e6) / 1e6, prediction: prob >= 0.5 ? 1 : 0, riskLevel: level,
        thresholds: th, source: 'offline', latencyMs: Math.round((performance.now() - t0) * 100) / 100,
        modelName: m.name, modelFeatures: m.features, missingFeatures: [], features: raw,
        auc: m.aucRoc
      };
    }
  };

  NS.dataHub = Hub;
})(window.BRFSS = window.BRFSS || {});