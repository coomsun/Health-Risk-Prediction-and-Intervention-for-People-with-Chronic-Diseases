/* =============================================================
   app.js —— 页面编排：加载、筛选联动、下钻、预测表单、异常兜底
   ============================================================= */
(function (NS) {
  'use strict';

  var D = NS.dict;
  var P = D.PALETTE;
  var API = NS.api;
  var C = NS.charts;

  var MAP_NAME = 'brfss-usa';

  var state = {
    filters: { year: null, state: null },
    trendMetric: 'multimorbidity_rate',
    geoMetric: 'multimorbidity_rate',
    drill: null,          /* 当前下钻的州 FIPS（两位字符串） */
    cache: {},            /* 最近一次成功响应，供交叉引用（如干预建议里的暴露率） */
    errors: 0
  };

  /* ============================================================
     基础工具
     ============================================================ */
  function $(sel) { return document.querySelector(sel); }
  function byId(id) { return document.getElementById(id); }

  function toArray(nodes) { return Array.prototype.slice.call(nodes); }

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  /* 全局异常上报：任何未捕获错误都显性化，绝不静默 */
  function reportError(message) {
    state.errors += 1;
    var banner = byId('js-error-banner');
    if (banner) {
      banner.hidden = false;
      banner.textContent = '⚠ 页面脚本异常（' + state.errors + '）：' + message + '\n请打开浏览器控制台查看堆栈；数据区可能显示不完整。';
    }
    document.body.setAttribute('data-js-errors', String(state.errors));
    if (window.console && console.error) console.error('[brfss] ' + message);
  }

  function toast(message) {
    var host = $('.toast-host');
    if (!host) {
      host = document.createElement('div');
      host.className = 'toast-host';
      document.body.appendChild(host);
    }
    var node = document.createElement('div');
    node.className = 'toast';
    node.textContent = message;
    host.appendChild(node);
    window.setTimeout(function () {
      node.style.opacity = '0';
      node.style.transition = 'opacity .25s';
      window.setTimeout(function () { if (node.parentNode) node.parentNode.removeChild(node); }, 260);
    }, 3200);
  }

  function debounce(fn, wait) {
    var timer = null;
    return function () {
      var args = arguments, self = this;
      window.clearTimeout(timer);
      timer = window.setTimeout(function () { fn.apply(self, args); }, wait);
    };
  }

  /* 同一接口的并发去重 + 成功结果缓存（/risk/stratify 在大库上较慢，被两个面板共用） */
  var inflight = {};
  function fetchOnce(key, factory) {
    var cached = state.cache[key];
    if (cached) return Promise.resolve(cached);
    if (inflight[key]) return inflight[key];
    inflight[key] = factory().then(function (data) {
      state.cache[key] = data;
      delete inflight[key];
      return data;
    }, function (err) {
      delete inflight[key];
      throw err;
    });
    return inflight[key];
  }

  function bodyOf(panelId) {
    var panel = byId(panelId);
    return panel ? panel.querySelector('[data-body]') : null;
  }

  function chartHost(panelId, chartId) {
    var body = bodyOf(panelId);
    if (!body) return null;
    var existing = body.querySelector('.chart-host');
    if (existing) return existing;
    var host = document.createElement('div');
    host.className = 'chart chart-host';
    host.id = chartId;
    body.appendChild(host);
    return host;
  }

  /* 统一的图表渲染入口：登记 hover 联动索引 + 事件只绑定一次（避免重复加载后处理器叠加） */
  var latest = {};      /* chartId -> 最近一次渲染所用数据（供只绑定一次的事件处理器读取） */
  var boundKeys = {};   /* chartId:event -> { chart, handler } */
  var linkIndex = {};   /* chartId -> { panelId, entries:[{seriesIndex,dataIndex,topics}] } */

  function bindOnce(chartId, eventName, handler) {
    var chart = C.ensure(chartId);
    if (!chart) return null;
    var key = chartId + ':' + eventName;
    var rec = boundKeys[key];
    if (rec && rec.chart === chart) return chart;   /* 同一实例只绑定一次，容器重建后重新绑定 */
    chart.on(eventName, handler);
    boundKeys[key] = { chart: chart, handler: handler };
    return chart;
  }

  function chartPanel(panelId, chartId, option) {
    chartHost(panelId, chartId);
    var chart = C.ensure(chartId);
    if (!chart) return null;
    linkIndex[chartId] = { panelId: panelId, entries: option.linkEntries || [], peak: option.linkPeak };
    delete option.linkEntries;
    delete option.linkPeak;
    chart.setOption(option, true);
    bindOnce(chartId, 'mouseover', function (p) { hoverLink(chartId, p); });
    bindOnce(chartId, 'globalout', function () { clearHover(); });
    return chart;
  }

  /* ============================================================
     跨图 hover 联动：悬停类目 → 相关图 dispatchAction highlight，离开即 downplay
     ============================================================ */
  var hoverKeys = null;   /* 当前悬停项标识，避免同一项重复派发 */
  var hoverAudit = 0;     /* 已派发的高亮次数（联调断言用的只读计数） */

  function clearHover() {
    if (hoverKeys == null) return;
    Object.keys(linkIndex).forEach(function (cid) {
      var chart = C.ensure(cid);
      if (chart) { try { chart.dispatchAction({ type: 'downplay' }); } catch (e) { /* noop */ } }
    });
    toArray(document.querySelectorAll('.is-hover-linked, .is-linked')).forEach(function (n) {
      n.classList.remove('is-hover-linked');
      n.classList.remove('is-linked');
    });
    document.body.removeAttribute('data-hover-link');
    document.body.removeAttribute('data-hover-topics');
    hoverKeys = null;
  }

  function topicHit(a, b) {
    for (var i = 0; i < a.length; i++) {
      for (var j = 0; j < b.length; j++) { if (a[i] === b[j]) return true; }
    }
    return false;
  }

  function hoverLink(chartId, param) {
    try {
      var slot = linkIndex[chartId];
      if (!slot || !param || param.componentType !== 'series') return;
      var entry = slot.entries.filter(function (e) {
        return e.seriesIndex === param.seriesIndex && e.dataIndex === param.dataIndex;
      })[0];
      if (!entry) { clearHover(); return; }
      var key = chartId + '|' + param.seriesIndex + '|' + param.dataIndex;
      if (key === hoverKeys) return;
      clearHover();
      var topics = entry.topics || [];
      var itemTopics = topics.filter(function (t) { return t.indexOf('metric:') !== 0; });
      var dispatched = {};
      Object.keys(linkIndex).forEach(function (cid) {
        if (cid === chartId) return;
        var matched = linkIndex[cid].entries.filter(function (e) { return topicHit(e.topics || [], topics); });
        if (!matched.length) return;
        var panel = byId(linkIndex[cid].panelId);
        if (panel) panel.classList.add('is-hover-linked');       /* 面板级：相关图描边提示 */
        var chart = C.ensure(cid);
        if (!chart) return;
        matched.forEach(function (e) {
          try {
            var target = { seriesIndex: e.seriesIndex, dataIndex: e.dataIndex };
            if (itemTopics.length && !topicHit(e.topics || [], itemTopics)) {
              var series = (chart.getOption().series || [])[e.seriesIndex] || {};
              if (series.type === 'map') {
                /* 地图不做整块系列高亮（整块变蓝反而干扰读数），改为高亮该指标的极值州 */
                if (linkIndex[cid].peak == null) return;
                target = { seriesIndex: e.seriesIndex, dataIndex: linkIndex[cid].peak };
              } else {
                target = { seriesIndex: e.seriesIndex };      /* 整条系列高亮 */
              }
            }
            var sig = cid + '|' + target.seriesIndex + '|' + (target.dataIndex == null ? '*' : target.dataIndex);
            if (dispatched[sig]) return;
            dispatched[sig] = true;
            chart.dispatchAction({ type: 'highlight', seriesIndex: target.seriesIndex, dataIndex: target.dataIndex });
            hoverAudit += 1;
          } catch (err) { /* 单个图表高亮失败不影响其它图 */ }
        });
      });
      /* 同一语义的 HTML 条目（下钻明细行 / 预测风险标签）同步高亮 */
      toArray(document.querySelectorAll('[data-link-topics]')).forEach(function (node) {
        if (topicHit(String(node.getAttribute('data-link-topics')).split(/\s+/), topics)) {
          node.classList.add('is-linked');
          hoverAudit += 1;
        }
      });
      document.body.setAttribute('data-hover-link', entry.name || param.name || '');
      document.body.setAttribute('data-hover-topics', topics.join(','));
      hoverKeys = key;
    } catch (e) { /* 联动异常绝不影响图表本身 */ }
  }

  function clearOverlay(body) {
    if (!body) return;
    toArray(body.querySelectorAll('.skeleton, .state-box')).forEach(function (n) { n.remove(); });
  }

  function showSkeleton(panelId) {
    var body = bodyOf(panelId);
    if (!body) return;
    clearOverlay(body);
    var wrap = document.createElement('div');
    wrap.className = 'skeleton';
    wrap.innerHTML =
      '<div class="skeleton-line w-45"></div>' +
      '<div class="skeleton-line w-90"></div>' +
      '<div class="skeleton-block"></div>' +
      '<div class="skeleton-line w-70"></div>';
    body.appendChild(wrap);
  }

  function showState(panelId, kind, title, message, retry) {
    var body = bodyOf(panelId);
    if (!body) return;
    clearOverlay(body);
    var box = document.createElement('div');
    box.className = 'state-box ' + (kind === 'error' ? 'is-error' : 'is-empty');
    var icon = kind === 'error' ? '⚠' : '∅';
    box.innerHTML =
      '<div class="state-icon">' + icon + '</div>' +
      '<div class="state-title">' + escapeHtml(title) + '</div>' +
      '<div class="state-msg">' + escapeHtml(message || '') + '</div>';
    if (retry) {
      var actions = document.createElement('div');
      actions.className = 'state-actions';
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-sm';
      btn.textContent = '重试';
      btn.addEventListener('click', retry);
      actions.appendChild(btn);
      box.appendChild(actions);
    }
    body.appendChild(box);
  }

  function showError(panelId, err, retry) {
    var code = err && err.code != null ? '（code ' + err.code + '）' : '';
    var attempts = err && err.attempts ? '，已尝试 ' + err.attempts + ' 次' : '';
    var trace = err && err.traceId ? '\ntraceId：' + err.traceId : '';
    showState(panelId, 'error', '数据加载失败', (err && err.message ? err.message : '未知错误') + code + attempts + trace, retry);
  }

  /* ============================================================
     顶栏：后端连通状态
     ============================================================ */
  function renderHealth(ok, data, err) {
    var el = byId('api-status');
    if (!el) return;
    if (ok) {
      /* 顶栏只留连通结论，版本/行数/耗时等细节收进 title 悬浮可见 */
      var rows = data && data.factRows != null ? D.compact(data.factRows) : '—';
      el.innerHTML = '<span class="dot dot-ok"></span><span class="status-text">后端正常</span>';
      el.title = 'version ' + (data.version || '—') + ' · fact_brfss ' + rows + ' 行' +
        (API.state.lastResponseTime ? ' · ' + API.state.lastResponseTime + 'ms' : '') +
        '\ndbPath: ' + (data.dbPath || '') + '\nmodelReady: ' + data.modelReady;
    } else {
      el.innerHTML = '<span class="dot dot-bad"></span><span class="status-text">后端未连接：' + escapeHtml(err && err.message || '') + '</span>';
      el.title = '请先启动后端：\n.venv\\Scripts\\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000\n然后刷新页面';
    }
  }

  function loadHealth() {
    return API.health().then(function (data) {
      state.cache.health = data;
      renderHealth(true, data);
      return data;
    }).catch(function (err) {
      renderHealth(false, null, err);
      throw err;
    });
  }

  /* ============================================================
     各面板加载器（统一：骨架 → 成功/空/错误）
     ============================================================ */
  function run(panelId, fetchFn, onData, isEmpty, emptyText) {
    showSkeleton(panelId);
    return fetchFn().then(function (data) {
      clearOverlay(bodyOf(panelId));
      if (isEmpty && isEmpty(data)) {
        showState(panelId, 'empty', '暂无数据', emptyText || '接口返回空结果（当前筛选条件下没有记录）');
        return data;
      }
      onData(data);
      return data;
    }).catch(function (err) {
      showError(panelId, err, function () { run(panelId, fetchFn, onData, isEmpty, emptyText); });
      if (window.console && console.warn) console.warn('[brfss] ' + panelId + ' 加载失败：', err && err.message);
      return null;
    });
  }

  /* ============================================================
     当前联动/下钻：顶栏显眼 chip + 一键清除（恢复全量）
     ============================================================ */
  var DEFAULT_METRIC = 'multimorbidity_rate';

  function metricLabel(metric) {
    var def = D.METRIC_BY_KEY[metric];
    return def ? def.label : metric;
  }

  function renderChips() {
    var bar = byId('chip-bar');
    if (!bar) return;
    var chips = [];
    if (state.trendMetric !== DEFAULT_METRIC || state.geoMetric !== DEFAULT_METRIC) {
      chips.push('<span class="chip" data-chip="metric">趋势/地图指标：' + escapeHtml(metricLabel(state.trendMetric)) +
        '<button class="chip-x" type="button" data-chip-clear="metric" aria-label="清除指标联动" title="清除后回到默认指标">×</button></span>');
    }
    if (state.drill) {
      chips.push('<span class="chip" data-chip="drill">下钻州：' + escapeHtml(D.stateFull(state.drill)) +
        '<button class="chip-x" type="button" data-chip-clear="drill" aria-label="清除下钻" title="清除后回到全部州">×</button></span>');
    }
    if (!chips.length) {
      bar.hidden = true;
      bar.innerHTML = '';
      return;
    }
    bar.hidden = false;
    bar.innerHTML = '<span class="chip-bar-label">当前选择</span>' + chips.join('');
  }

  function clearMetricLink(silent) {
    if (state.trendMetric === DEFAULT_METRIC && state.geoMetric === DEFAULT_METRIC) {
      if (!silent) toast('当前没有指标联动');
      return false;
    }
    state.trendMetric = DEFAULT_METRIC;
    state.geoMetric = DEFAULT_METRIC;
    var ts = byId('trend-metric');
    var gs = byId('geo-metric');
    if (ts) ts.value = DEFAULT_METRIC;
    if (gs) gs.value = DEFAULT_METRIC;
    if (!silent) toast('已清除指标联动，趋势图与地图恢复「' + metricLabel(DEFAULT_METRIC) + '」');
    loadTrend();
    loadGeo();
    renderChips();
    return true;
  }

  function clearDrill(silent) {
    if (!state.drill) {
      if (!silent) toast('当前没有下钻的州');
      return false;
    }
    state.drill = null;
    state.filters.state = null;
    var sel = byId('filter-state');
    if (sel) sel.value = '';
    if (!silent) toast('已清除下钻，恢复全部州');
    loadPrevalence();
    loadFactors();
    loadGeo();
    showState('panel-drill', 'empty', '未选择州', '点击左侧地图中的任一州，这里显示该州 8 类慢病患病率明细');
    renderChips();
    return true;
  }

  /* ---------------- 1. KPI ---------------- */
  function renderKpi(d) {
    var body = bodyOf('panel-kpi');
    if (!body) return;
    var span = d.yearSpan || {};
    var cards = [
      {
        label: '总样本量',
        value: D.compact(d.totalSamples),
        unit: '',
        foot: 'n = ' + D.int(d.totalSamples) + ' 条记录'
      },
      {
        label: '慢病种类数',
        value: String(d.chronicTypes == null ? '—' : d.chronicTypes),
        unit: '类',
        foot: '标志位求和 = chronic_count'
      },
      {
        label: '共病率（≥2 种）',
        value: d.multimorbidityRate == null ? '—' : (d.multimorbidityRate * 100).toFixed(2),
        unit: '%',
        foot: '病例 ' + D.int(d.multimorbidityCases) + ' / 有效 ' + D.int(d.multimorbidityValid),
        accent: true
      },
      {
        label: '年份跨度',
        value: (span.min == null ? '—' : span.min) + '–' + (span.max == null ? '—' : span.max),
        unit: '年',
        foot: (span.years == null ? '—' : span.years) + ' 个调查年度'
      },
      {
        label: '覆盖州 / 地区',
        value: String(d.stateCount == null ? '—' : d.stateCount),
        unit: '个',
        foot: '基于 _STATE 编码统计'
      },
      {
        label: '人均慢病数',
        value: d.avgChronicCount == null ? '—' : Number(d.avgChronicCount).toFixed(3),
        unit: '种/人',
        foot: '糖尿病患病率 ' + D.pct(d.diabetesPrevalence)
      }
    ];
    body.innerHTML = '<div class="kpi-grid">' + cards.map(function (c) {
      return '<div class="kpi' + (c.accent ? ' kpi-accent' : '') + '">' +
        '<div class="kpi-label">' + escapeHtml(c.label) + '</div>' +
        '<div class="kpi-value">' + escapeHtml(c.value) + (c.unit ? '<small>' + escapeHtml(c.unit) + '</small>' : '') + '</div>' +
        '<div class="kpi-foot">' + escapeHtml(c.foot) + '</div>' +
        '</div>';
    }).join('') + '</div>';
  }

  function loadOverview() {
    return run('panel-kpi', function () { return API.get('/api/v1/overview', null, { label: '总览 KPI' }); },
      function (d) { state.cache.overview = d; renderKpi(d); });
  }

  /* ---------------- 2. 各慢病患病率 ---------------- */
  function onPrevalenceClick(p) {
    var d = latest['chart-prevalence'];
    var item = ((d && d.items) || []).filter(function (x) { return x.name === p.name; })[0];
    if (!item) return;
    var metric = D.DISEASE_TO_METRIC[item.key];
    if (!metric) { toast('「' + item.name + '」在契约中没有对应的趋势指标'); return; }
    applyMetricLink(metric, '慢病条形图「' + item.name + '」');
  }

  function loadPrevalence() {
    var params = { year: state.filters.year, state: state.filters.state };
    return run('panel-prevalence',
      function () { return API.get('/api/v1/chronic/prevalence', params, { label: '慢病患病率' }); },
      function (d) {
        state.cache.prevalence = d;
        latest['chart-prevalence'] = d;
        chartPanel('panel-prevalence', 'chart-prevalence', C.prevalenceOption(d));
        bindOnce('chart-prevalence', 'click', onPrevalenceClick);
      },
      function (d) { return !d || !d.items || d.items.length === 0; },
      '当前筛选条件下没有慢病患病率记录');
  }

  /* ---------------- 3. 年度趋势 ---------------- */
  function loadTrend() {
    return run('panel-trend',
      function () { return API.get('/api/v1/trend', { metric: state.trendMetric }, { label: '年度趋势' }); },
      function (d) {
        state.cache.trend = d;
        chartPanel('panel-trend', 'chart-trend', C.trendOption(d));
      },
      function (d) { return !d || !d.series || d.series.length === 0; },
      '该指标没有年度序列（接口返回空数组）');
  }

  /* ---------------- 4. 地图 ---------------- */
  function onGeoClick(p) {
    if (!p || !p.name) return;
    drillInto(D.padFips(p.name));
  }

  function loadGeo() {
    return run('panel-geo',
      function () { return API.get('/api/v1/geo/states', { metric: state.geoMetric }, { label: '州级指标' }); },
      function (d) {
        state.cache.geo = d;
        chartPanel('panel-geo', 'chart-geo', C.geoOption(d, state.geoMetric, state.drill));
        if (state.drill) {
          try {
            C.ensure('chart-geo').dispatchAction({ type: 'select', seriesIndex: 0, name: state.drill });
          } catch (e) { /* 选中态失败不影响主流程 */ }
        }
        bindOnce('chart-geo', 'click', onGeoClick);
      },
      function (d) { return !d || !d.items || d.items.length === 0; },
      '该指标没有州级数据');
  }

  /* ---------------- 5. 危险因素 ---------------- */
  function onFactorsClick(p) {
    var d = latest['chart-factors'];
    var item = ((d && d.items) || []).filter(function (x) { return x.name === p.name; })[0];
    if (!item) return;
    var metric = D.FACTOR_TO_METRIC[item.key];
    if (!metric) {
      toast('「' + item.name + '」在冻结契约中没有独立年度趋势指标，已保持当前趋势图');
      return;
    }
    applyMetricLink(metric, '危险因素「' + item.name + '」');
  }

  function loadFactors() {
    return run('panel-factors',
      function () { return API.get('/api/v1/risk/factors', { year: state.filters.year }, { label: '危险因素' }); },
      function (d) {
        state.cache.factors = d;
        latest['chart-factors'] = d;
        chartPanel('panel-factors', 'chart-factors', C.factorOption(d));
        bindOnce('chart-factors', 'click', onFactorsClick);
      },
      function (d) { return !d || !d.items || d.items.length === 0; },
      '该年份没有危险因素数据');
  }

  /* ---------------- 6. 风险分层 + 慢病数分布 ---------------- */
  function onStratifyClick(p) {
    var d = latest['chart-stratify-level'];
    var lv = ((d && d.levels) || []).filter(function (x) { return x.level === p.seriesName; })[0];
    if (!lv) return;
    toast(lv.level + '：' + lv.rule + ' · 样本 ' + D.int(lv.samples) + ' · 占比 ' + D.pct(lv.share));
  }

  function loadStratify() {
    return run('panel-stratify',
      function () { return fetchOnce('stratify', function () { return API.get('/api/v1/risk/stratify', null, { label: '风险分层' }); }); },
      function (d) {
        var body = bodyOf('panel-stratify');
        body.innerHTML =
          '<div class="split-2">' +
          '<div class="chart" id="chart-stratify-level"></div>' +
          '<div class="chart" id="chart-chronic-dist"></div>' +
          '</div>';
        latest['chart-stratify-level'] = d;
        chartPanel('panel-stratify', 'chart-stratify-level', C.stratifyLevelOption(d));
        chartPanel('panel-stratify', 'chart-chronic-dist', C.chronicDistOption(d));
        bindOnce('chart-stratify-level', 'click', onStratifyClick);
      },
      function (d) { return !d || !d.levels || d.levels.length === 0; },
      '没有风险分层数据');
  }

  /* ---------------- 7. 模型指标 ---------------- */
  function loadMetrics() {
    return run('panel-metrics',
      function () { return API.get('/api/v1/model/metrics', null, { label: '模型指标' }); },
      function (d) {
        state.cache.metrics = d;
        chartPanel('panel-metrics', 'chart-metrics', C.modelMetricOption(d));
      },
      function (d) { return !d || !d.items || d.items.length === 0; },
      'model_metrics 表暂无记录（需先运行 pipeline/05_train.py）');
  }

  /* ---------------- 8. 年龄组（复用 stratify 响应，不重复请求） ---------------- */
  function renderAge(d) {
    chartPanel('panel-age', 'chart-age', C.ageOption(d));
  }

  function loadAge() {
    return run('panel-age',
      function () {
        return fetchOnce('stratify', function () { return API.get('/api/v1/risk/stratify', null, { label: '年龄组共病率' }); });
      },
      function (d) {
        renderAge(d);
      },
      function (d) { return !d || !d.byAge || d.byAge.length === 0; },
      '没有年龄组分层数据');
  }

  /* ============================================================
     筛选器
     ============================================================ */
  function fillYearSelect(years) {
    var sel = byId('filter-year');
    if (!sel) return;
    var html = '<option value="">全部年份</option>';
    (years || []).slice().sort(function (a, b) { return b.year - a.year; }).forEach(function (y) {
      html += '<option value="' + y.year + '">' + y.year + '（n=' + D.int(y.samples) + '）</option>';
    });
    sel.innerHTML = html;
    sel.value = state.filters.year == null ? '' : String(state.filters.year);
  }

  function fillStateSelect(items) {
    var sel = byId('filter-state');
    if (!sel) return;
    var sorted = (items || []).slice().sort(function (a, b) {
      return D.stateName(a.stateFips).localeCompare(D.stateName(b.stateFips), 'zh-Hans-CN');
    });
    var html = '<option value="">全部州（全国）</option>';
    sorted.forEach(function (it) {
      var fips = D.padFips(it.stateFips);
      html += '<option value="' + fips + '">' + escapeHtml(D.stateFull(fips)) + '</option>';
    });
    sel.innerHTML = html;
    sel.value = state.filters.state == null ? '' : D.padFips(state.filters.state);
  }

  function loadFilterOptions() {
    var yearTask = API.get('/api/v1/overview', null, { label: '筛选器年份' })
      .then(function (d) { state.cache.overview = d; fillYearSelect(d.years); return d; })
      .catch(function (err) { fillYearSelect([{ year: new Date().getFullYear(), samples: 0 }]); return null; });
    var stateTask = API.get('/api/v1/geo/states', { metric: 'multimorbidity_rate' }, { label: '筛选器州列表' })
      .then(function (d) { fillStateSelect(d.items); return d; })
      .catch(function () { fillStateSelect([]); return null; });
    return Promise.all([yearTask, stateTask]);
  }

  function onFilterChange() {
    var yearSel = byId('filter-year');
    var stateSel = byId('filter-state');
    state.filters.year = yearSel && yearSel.value ? Number(yearSel.value) : null;
    state.filters.state = stateSel && stateSel.value ? D.padFips(stateSel.value) : null;
    var affected = [];
    affected.push(loadPrevalence());
    affected.push(loadFactors());
    if (state.filters.state) affected.push(loadDrill(state.filters.state));
    patchFilterNote();
    renderChips();
    return Promise.all(affected);
  }

  function patchFilterNote() {
    var note = byId('filter-note');
    var text = '年份/州筛选：影响「慢病患病率」（year+state）与「危险因素」（仅 year，契约未提供州参数）';
    if (!note) return text;
    note.textContent = text;
    return text;
  }

  /* ============================================================
     联动与下钻
     ============================================================ */
  function applyMetricLink(metric, sourceLabel) {
    if (!metric || !D.METRIC_BY_KEY[metric]) return;
    state.trendMetric = metric;
    state.geoMetric = metric;
    var ts = byId('trend-metric');
    var gs = byId('geo-metric');
    if (ts) ts.value = metric;
    if (gs) gs.value = metric;
    var label = D.METRIC_BY_KEY[metric].label;
    toast('已由' + sourceLabel + '联动：趋势图与地图指标 → ' + label);
    loadTrend();
    loadGeo();
    renderChips();
  }

  function drillInto(fips) {
    fips = D.padFips(fips);
    state.drill = fips;
    state.filters.state = fips;
    var sel = byId('filter-state');
    if (sel) sel.value = fips;
    toast('下钻：' + D.stateFull(fips));
    loadPrevalence();
    loadFactors();
    loadDrill(fips);
    loadGeo();
    renderChips();
  }

  function loadDrill(fips) {
    var year = state.filters.year;
    return run('panel-drill',
      function () { return API.get('/api/v1/chronic/prevalence', { year: year, state: fips }, { label: '下钻明细' }); },
      function (d) {
        renderDrill(fips, d);
      },
      function (d) { return !d || !d.items || d.items.length === 0; },
      '该州在当前年份没有记录');
  }

  function renderDrill(fips, d) {
    var body = bodyOf('panel-drill');
    if (!body) return;
    var items = (d.items || []).slice().sort(function (a, b) { return b.prevalence - a.prevalence; });
    var maxP = items.length ? Math.max.apply(null, items.map(function (x) { return x.prevalence; })) : 1;
    var rows = items.map(function (it) {
      var w = maxP > 0 ? (it.prevalence / maxP * 100) : 0;
      return '<li class="drill-row" data-link-topics="disease:' + escapeHtml(it.key) + '">' +
        '<span class="drill-name">' + escapeHtml(it.name) + '</span>' +
        '<span class="drill-bar"><i style="width:' + w.toFixed(1) + '%;background:' + (D.DISEASE_COLOR[it.key] || P.primary) + '"></i></span>' +
        '<span class="drill-val">' + D.pct(it.prevalence) + '</span>' +
        '</li>';
    }).join('');
    body.innerHTML =
      '<div class="drill-wrap" data-link-topics="fips:' + escapeHtml(fips) + '">' +
      '<div class="drill-title"><strong>' + escapeHtml(D.stateFull(fips)) + '</strong>' +
      '<span class="drill-meta">' + (state.filters.year ? state.filters.year + ' 年 · ' : '全部年份 · ') +
      '样本 n = ' + D.int(d.totalSamples) + '</span></div>' +
      '<ul class="drill-list">' + rows + '</ul>' +
      '<div class="drill-actions">' +
      '<button class="btn btn-sm" type="button" id="drill-apply-global">把该州应用到全局筛选</button>' +
      '<button class="btn btn-sm btn-ghost" type="button" id="drill-clear">清除下钻</button>' +
      '</div>';
    var applyBtn = byId('drill-apply-global');
    if (applyBtn) applyBtn.addEventListener('click', function () { onFilterChange(); });
    var clearBtn = byId('drill-clear');
    if (clearBtn) clearBtn.addEventListener('click', function () { clearDrill(); });
  }

  /* ============================================================
     在线风险预测
     ============================================================ */
  function buildPredictForm() {
    var body = bodyOf('panel-predict');
    if (!body) return;
    var fields = D.PREDICT_FIELDS.map(function (f) {
      var control;
      if (f.type === 'select') {
        control = '<select name="' + f.name + '" id="pf-' + f.name + '">' +
          f.options.map(function (o) {
            return '<option value="' + o[0] + '"' + (o[0] === f.default ? ' selected' : '') + '>' + escapeHtml(o[1]) + '</option>';
          }).join('') + '</select>';
      } else {
        control = '<input type="number" name="' + f.name + '" id="pf-' + f.name + '" value="' + f.default +
          '" min="' + f.min + '" max="' + f.max + '" step="' + f.step + '">';
      }
      return '<label class="field"><span>' + escapeHtml(f.label) + '</span>' + control +
        '<span class="field-err" id="pfe-' + f.name + '"></span></label>';
    }).join('');
    body.innerHTML =
      '<div class="predict">' +
      '<form class="predict-form" id="predict-form" novalidate>' + fields +
      '<div class="predict-actions">' +
      '<button class="btn btn-primary" type="submit" id="predict-submit">预测共病风险</button>' +
      '<button class="btn btn-ghost" type="button" id="predict-reset">重置表单</button>' +
      '<span class="form-msg" id="predict-msg">特征全部可选，提交后由后端模型给出阳性概率</span>' +
      '</div>' +
      '</form>' +
      '<div class="predict-result" id="predict-result">' +
      '<div class="predict-gauge" id="chart-gauge"></div>' +
      '<p class="gauge-caption" id="gauge-caption">共病阳性预测概率（%）</p>' +
      '<div id="predict-lines">' +
      '<p class="form-msg" id="predict-placeholder">尚未预测：填写左侧特征后点击「预测共病风险」，结果与概率仪表将显示在此处。</p>' +
      '</div>' +
      '</div>' +
      '<div class="advice" id="predict-advice"><h3>干预建议</h3>' +
      '<p class="form-msg">提交后依据模型风险等级与命中的可干预因素生成建议（暴露率取自 /api/v1/risk/factors）</p></div>' +
      '</div>';

    var form = byId('predict-form');
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      submitPredict();
    });
    /* 用户一改动就清掉该字段的越界提示 */
    form.addEventListener('input', onPredictFieldEdit);
    form.addEventListener('change', onPredictFieldEdit);
    byId('predict-reset').addEventListener('click', function () {
      D.PREDICT_FIELDS.forEach(function (f) {
        var node = byId('pf-' + f.name);
        if (node) node.value = String(f.default);
        clearFieldError(f.name);
      });
      var msg = byId('predict-msg');
      msg.className = 'form-msg';
      msg.textContent = '已重置为默认画像';
    });
  }

  function collectPredict() {
    var payload = {};
    D.PREDICT_FIELDS.forEach(function (f) {
      var node = byId('pf-' + f.name);
      if (!node) return;
      var raw = node.value;
      if (raw === '' || raw == null) return;
      var num = Number(raw);
      if (isNaN(num)) return;
      payload[f.name] = num;
    });
    return payload;
  }

  function onPredictFieldEdit(ev) {
    var t = ev.target;
    if (t && t.id && t.id.indexOf('pf-') === 0) clearFieldError(t.id.slice(3));
  }

  function clearFieldError(name) {
    var node = byId('pf-' + name);
    var err = byId('pfe-' + name);
    if (node && node.classList) node.classList.remove('is-invalid');
    if (err) err.textContent = '';
  }

  /* 就地校验：越界/非数值直接拦在表单里，不发请求 */
  function validatePredict() {
    var firstBad = null;
    D.PREDICT_FIELDS.forEach(function (f) {
      clearFieldError(f.name);
      if (f.type !== 'number') return;
      var node = byId('pf-' + f.name);
      if (!node) return;
      var raw = String(node.value == null ? '' : node.value).trim();
      if (raw === '') return;              /* 留空按缺失特征处理，交给后端 */
      var num = Number(raw);
      var why = isNaN(num) ? '请填写数字' : ((num < f.min || num > f.max) ? ('允许区间 ' + f.min + '–' + f.max) : '');
      if (!why) return;
      var err = byId('pfe-' + f.name);
      if (node.classList) node.classList.add('is-invalid');
      if (err) err.textContent = why;
      if (!firstBad) firstBad = '「' + f.label + '」' + why + '，未发出请求，请修改后重试';
    });
    return firstBad;
  }

  var predictBusy = false;   /* in-flight 守卫：连点只发一次请求 */

  function submitPredict() {
    var submit = byId('predict-submit');
    var msg = byId('predict-msg');
    if (predictBusy) {
      msg.className = 'form-msg';
      msg.textContent = '上一次预测仍在进行，请稍候…';
      return;
    }
    var bad = validatePredict();
    if (bad) {
      msg.className = 'form-msg is-error';
      msg.textContent = bad;
      return;
    }
    var payload = collectPredict();
    if (!Object.keys(payload).length) {
      msg.className = 'form-msg is-error';
      msg.textContent = '请至少填写一项特征';
      return;
    }
    predictBusy = true;
    submit.disabled = true;
    msg.className = 'form-msg';
    msg.textContent = '正在请求 /api/v1/predict …';
    /* /predict 受 JWT 保护：postAuth 先自动登录拿令牌再带 Bearer 请求；
       timeoutMs=20000 / retries=1：失败时不再空转 4 轮，兼顾成功率与等待时间 */
    API.postAuth('/api/v1/predict', payload, { label: '在线预测', timeoutMs: 20000, retries: 1 }).then(function (data) {
      state.cache.predict = data;
      msg.className = 'form-msg is-ok';
      msg.textContent = '预测完成 · 延迟 ' + (data.latencyMs == null ? '—' : Math.round(Number(data.latencyMs))) + ' ms';
      /* 渲染异常不得伪装成「预测失败」：成功结论已先行给出 */
      try {
        renderPredictResult(data);
      } catch (e) {
        msg.className = 'form-msg is-error';
        msg.textContent = '预测已成功返回，但结果渲染异常：' + (e && e.message ? e.message : e) + '（详见页首错误条）';
        reportError('预测结果渲染异常：' + (e && e.message ? e.message : e));
      }
    }).catch(function (err) {
      msg.className = 'form-msg is-error';
      var hint = '';
      if (err && err.code === 1001) {
        hint = '（模型文件未生成，请先运行 pipeline/05_train.py 产出 artifacts/model/model.joblib）';
      } else if (err && err.code === 401) {
        hint = '（需要登录：演示账号为 demo / demo12345）';
      } else if (err && err.code === 400) {
        hint = '（特征取值超出契约允许范围）';
      } else if (err && err.name === 'AuthError') {
        hint = '（自动登录失败，请检查后端 AUTH_USERS 配置或令牌服务是否可用）';
      }
      msg.textContent = '预测失败：' + (err && err.message || '未知错误') + ' code=' + (err && err.code) + hint;
      /* 失败不改动表单：已填数值原样保留，便于修改后重试 */
      renderPredictError(err);
    }).then(function () {
      predictBusy = false;
      submit.disabled = false;
    });
  }

  function renderPredictError(err) {
    var gauge = byId('chart-gauge');
    if (gauge) gauge.style.display = 'none';
    var caption = byId('gauge-caption');
    if (caption) caption.style.display = 'none';
    var lines = byId('predict-lines');
    if (!lines) return;
    lines.innerHTML =
      '<div class="state-box is-error" style="position:static;margin-top:8px">' +
      '<div class="state-title">预测接口返回错误 code=' + escapeHtml(String(err && err.code)) + '</div>' +
      '<div class="state-msg">' + escapeHtml(err && err.message || '') +
      (err && err.traceId ? '（traceId：' + escapeHtml(err.traceId) + '）' : '') + '</div>' +
      '<div class="state-actions"><button class="btn btn-sm" type="button" onclick="document.getElementById(\'predict-submit\').click()">重试</button></div>' +
      '</div>';
    var adv = byId('predict-advice');
    if (adv) adv.innerHTML = '<h3>干预建议</h3><p class="form-msg">预测未成功，暂无建议。</p>';
  }

  function renderPredictResult(data) {
    var body = bodyOf('panel-predict');
    if (!body) return;
    var host = byId('chart-gauge');
    if (host) {
      host.style.display = '';
      var captionNode = byId('gauge-caption');
      if (captionNode) captionNode.style.display = '';
      var chart = C.ensure('chart-gauge');
      if (!chart) {
        host.innerHTML = '';
      }
      C.render('chart-gauge', C.gaugeOption(data.probability, data.riskLevel));
    }
    var levelClass = data.riskLevel === '高风险' ? 'risk-high' : (data.riskLevel === '中风险' ? 'risk-mid' : 'risk-low');
    var thr = data.thresholds || {};
    var lines = byId('predict-lines');
    if (lines) {
      var ph = byId('predict-placeholder');
      if (ph) ph.remove();
      lines.innerHTML =
        '<div class="result-line"><span>风险等级</span><b><span class="risk-tag ' + levelClass + '" data-link-topics="level:' + escapeHtml(data.riskLevel) + '">' + escapeHtml(data.riskLevel) + '</span></b></div>' +
        '<div class="result-line"><span>阳性概率</span><b>' + D.pct(data.probability, 2) + '</b></div>' +
        '<div class="result-line"><span>预测标签（0.5 判定）</span><b>' + (data.prediction === 1 ? '共病阳性' : '共病阴性') + '</b></div>' +
        '<div class="result-line"><span>判定阈值</span><b>中 ≥ ' + D.pct(thr.low, 0) + ' · 高 ≥ ' + D.pct(thr.high, 0) + '</b></div>' +
        '<div class="result-line"><span>模型文件</span><b>' + escapeHtml((data.model && data.model.fileName) || '—') + '</b></div>' +
        '<div class="result-line"><span>缺失特征</span><b>' + ((data.missingFeatures && data.missingFeatures.length) ? escapeHtml(data.missingFeatures.length + ' 个（已按缺失值处理）') : '无') + '</b></div>' +
        '<div class="result-line"><span>接口延迟</span><b>' + (data.latencyMs == null ? '—' : data.latencyMs) + ' ms</b></div>' +
        '<p class="drill-meta" style="margin-top:6px">口径：风险等级按后端阈值（中 ≥ ' + D.pct(thr.low, 0) + '、高 ≥ ' + D.pct(thr.high, 0) + '）分档，' +
        '与"预测标签"的 0.5 判定是两个不同口径，可能同时出现"高风险 + 标签阴性"。</p>';
    }
    renderAdvice(data);
  }

  function renderAdvice(data) {
    var adv = byId('predict-advice');
    if (!adv) return;
    var features = data.features || {};
    var hits = D.ADVICE_RULES.filter(function (rule) {
      try { return rule.match(features); } catch (e) { return false; }
    });
    var factorIndex = {};
    var factors = (state.cache.factors && state.cache.factors.items) || [];
    factors.forEach(function (it) {
      factorIndex[it.key] = it;
      var alias = D.FACTOR_ALIAS[it.key];
      if (alias) factorIndex[alias] = it;   /* 兼容后端 key 命名调整 */
    });

    var base = [];
    if (data.riskLevel === '高风险') {
      base.push({ tier: '分层路径', text: '高风险个体：建议 1 个月内完成专科评估，纳入多学科共病管理并每 3 个月复评' });
    } else if (data.riskLevel === '中风险') {
      base.push({ tier: '分层路径', text: '中风险个体：建议 6 个月内复查关键指标，优先干预下列可改变因素' });
    } else {
      base.push({ tier: '分层路径', text: '低风险个体：维持现有生活方式，按年度常规体检随访' });
    }

    var items = base.concat(hits.map(function (h) {
      var line = { tier: h.tier, text: h.text };
      var f = h.factorKey ? factorIndex[h.factorKey] : null;
      if (f) {
        line.exposure = '人群暴露率 ' + D.pct(f.rate) + '（暴露 ' + D.int(f.exposed) + ' / 有效 n=' + D.int(f.validSamples) + '）';
      }
      return line;
    }));

    adv.innerHTML = '<h3>干预建议 <span class="form-msg">（命中 ' + hits.length + ' 条可干预因素规则）</span></h3>' +
      '<ul>' + items.map(function (it) {
        return '<li><span class="tier">[' + escapeHtml(it.tier) + ']</span> <b>' + escapeHtml(it.text) + '</b>' +
          (it.exposure ? '<br/><span class="drill-meta">' + escapeHtml(it.exposure) + '</span>' : '') + '</li>';
      }).join('') + '</ul>' +
      '<p class="drill-meta" style="margin-top:8px">规则为课程项目设定的干预路径模板，非临床指南；风险概率来自后端模型，建议仅供参考。</p>';
  }

  /* ============================================================
     初始化
     ============================================================ */
  function registerMap() {
    if (!window.echarts) throw new Error('ECharts 未加载（vendor/echarts.min.js 缺失）');
    if (!window.BRFSS_US_MAP) throw new Error('美国州界数据未加载（vendor/us-states.geo.js 缺失）');
    window.echarts.registerMap(MAP_NAME, window.BRFSS_US_MAP);
  }

  function fillMetricSelects() {
    var options = D.METRICS.map(function (m) {
      return '<option value="' + m.key + '"' + (m.key === state.trendMetric ? ' selected' : '') + '>' +
        escapeHtml(m.label) + '</option>';
    }).join('');
    var ts = byId('trend-metric');
    if (ts) ts.innerHTML = options;
    var gs = byId('geo-metric');
    if (gs) {
      gs.innerHTML = D.METRICS.map(function (m) {
        return '<option value="' + m.key + '"' + (m.key === state.geoMetric ? ' selected' : '') + '>' +
          escapeHtml(m.label) + '</option>';
      }).join('');
    }
  }

  function bindEvents() {
    var yearSel = byId('filter-year');
    if (yearSel) yearSel.addEventListener('change', onFilterChange);
    var stateSel = byId('filter-state');
    if (stateSel) stateSel.addEventListener('change', function () {
      var v = stateSel.value;
      state.filters.state = v ? D.padFips(v) : null;
      state.drill = v ? D.padFips(v) : null;
      onFilterChange();
      loadGeo();
    });
    var reset = byId('btn-reset');
    if (reset) reset.addEventListener('click', function () {
      state.filters.year = null;
      state.filters.state = null;
      state.drill = null;
      if (yearSel) yearSel.value = '';
      if (stateSel) stateSel.value = '';
      showState('panel-drill', 'empty', '未选择州', '点击左侧地图中的任一州，这里显示该州 8 类慢病患病率明细');
      renderChips();
      onFilterChange();
      loadGeo();
    });
    var trendSel = byId('trend-metric');
    if (trendSel) trendSel.addEventListener('change', function () {
      state.trendMetric = trendSel.value;
      loadTrend();
    });
    var geoSel = byId('geo-metric');
    if (geoSel) geoSel.addEventListener('change', function () {
      state.geoMetric = geoSel.value;
      loadGeo();
    });
    var chipBar = byId('chip-bar');
    if (chipBar) chipBar.addEventListener('click', function (ev) {
      var btn = ev.target && ev.target.closest ? ev.target.closest('[data-chip-clear]') : null;
      if (!btn) return;
      var what = btn.getAttribute('data-chip-clear');
      if (what === 'drill') clearDrill();
      else if (what === 'metric') clearMetricLink();
    });
    /* Esc：清除当前联动与下钻，恢复默认视图 */
    document.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Escape' && ev.key !== 'Esc') return;
      var did = false;
      if (state.drill) did = clearDrill(true) || did;
      if (state.trendMetric !== DEFAULT_METRIC || state.geoMetric !== DEFAULT_METRIC) did = clearMetricLink(true) || did;
      if (did) toast('已按 Esc 清除联动与下钻，恢复默认视图');
    });
    window.addEventListener('resize', debounce(function () { C.resizeAll(); }, 160));
    window.addEventListener('error', function (ev) {
      reportError((ev && ev.message ? ev.message : '未知脚本错误') + (ev && ev.filename ? ' @ ' + ev.filename + ':' + ev.lineno : ''));
    });
    window.addEventListener('unhandledrejection', function (ev) {
      var reason = ev && ev.reason;
      reportError('未处理的 Promise 拒绝：' + (reason && reason.message ? reason.message : String(reason)));
    });
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) window.setTimeout(function () { C.resizeAll(); }, 60);
    });
  }

  function init() {
    try {
      registerMap();
    } catch (e) {
      reportError(e.message);
      ['panel-geo'].forEach(function (id) {
        showState(id, 'error', '地图组件不可用', e.message);
      });
    }
    fillMetricSelects();
    buildPredictForm();
    bindEvents();
    patchFilterNote();
    renderChips();
    /* 预取登录令牌：首次预测不必等登录，缩短端到端延迟 */
    API.ensureToken().catch(function () { return null; });
    showSkeleton('panel-drill');
    showState('panel-drill', 'empty', '未选择州', '点击左侧地图中的任一州，这里显示该州 8 类慢病患病率明细');

    var jobs = [
      loadFilterOptions(),
      loadOverview(),
      loadPrevalence(),
      loadTrend(),
      loadFactors(),
      loadStratify(),
      loadGeo(),
      loadMetrics(),
      loadAge(),
      loadHealth().catch(function () { return null; })
    ];
    return Promise.all(jobs).then(function () {
      renderChips();
      if (window.console && console.info) {
        console.info('[brfss] 初始化完成 · API ' + API.state.base + ' · 脚本异常数 ' + state.errors);
      }
    });
  }

  /* 供联调脚本/自动化断言使用的最小只读接口 */
  NS.app = {
    state: state,
    init: init,
    reloadAll: function () { return onFilterChange(); },
    drillInto: drillInto,
    applyMetricLink: applyMetricLink,
    clearDrill: clearDrill,
    clearMetricLink: clearMetricLink,
    renderChips: renderChips,
    hoverAudit: function () { return hoverAudit; }
  };

  document.addEventListener('DOMContentLoaded', function () {
    init().catch(function (err) {
      reportError('初始化失败：' + (err && err.message ? err.message : String(err)));
    });
  });
})(window.BRFSS = window.BRFSS || {});
