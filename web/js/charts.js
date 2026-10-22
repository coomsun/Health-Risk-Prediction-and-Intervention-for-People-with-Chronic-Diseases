/* =============================================================
   charts.js —— ECharts 实例管理 + 各图表 Option 构造器
   所有图表共用一套色板/字号/坐标轴样式，只在此处集中定义
   ============================================================= */
(function (NS) {
  'use strict';

  var D = NS.dict;
  var P = D.PALETTE;
  var instances = {};   /* id -> { chart, container } */

  /* 图表调色板：全部取自 CSS 令牌（与 :root 的 --c-* 同源），
     替换 ECharts 出厂浅色默认色板 #5470c6 系列，8 个实例统一生效。 */
  var CHART_COLORS = [P.primary, P.teal, P.amber, P.violet, P.rose, P.cyan, P.green, P.fuchsia];
  var THEME_NAME = 'brfss-dark';
  var THEME = null;
  if (window.echarts && typeof window.echarts.registerTheme === 'function') {
    window.echarts.registerTheme(THEME_NAME, { color: CHART_COLORS });
    THEME = THEME_NAME;
  }

  var AXIS_LABEL = { color: P.text2, fontSize: 11 };
  var AXIS_LINE = { lineStyle: { color: P.lineStrong } };
  var SPLIT_LINE = { lineStyle: { color: P.line, type: 'dashed' } };
  /* 不显示网格的轴也显式带上同一网格色：ECharts 出厂默认 splitLine 是浅色 #E0E6F1，
     否则 getOption 中一页并存两套网格色（隐藏轴上不可见，但配置仍是浅色）。 */
  var SPLIT_LINE_OFF = { show: false, lineStyle: { color: P.line, type: 'dashed' } };
  var TOOLTIP = {
    backgroundColor: 'rgba(10,18,32,0.96)',
    borderColor: P.lineStrong,
    borderWidth: 1,
    padding: [8, 11],
    textStyle: { color: P.text, fontSize: 12, lineHeight: 18 },
    extraCssText: 'box-shadow:0 8px 26px rgba(0,0,0,.5);border-radius:8px;max-width:320px;white-space:normal;'
  };
  var TITLE_STYLE = { color: P.text, fontSize: 12 };

  /* 右上角快捷操作：保存图片 / 还原视图（所有图表统一） */
  function toolbox(id) {
    return {
      right: 4,
      top: 0,
      itemSize: 13,
      itemGap: 8,
      iconStyle: { borderColor: P.text2 },
      emphasis: { iconStyle: { borderColor: P.cyan } },
      feature: {
        restore: { title: '还原视图' },
        saveAsImage: { title: '保存为图片', name: id, pixelRatio: 2, backgroundColor: P.bg }
      }
    };
  }

  /* 联动主题词：跨图 hover 联动按主题词取交集（如 metric:xxx / disease:xxx） */
  function linkTopic(prefix, value) {
    return value == null || value === '' ? null : prefix + value;
  }

  function compactTopics(list) {
    return list.filter(function (t) { return !!t; });
  }

  function el(id) {
    return document.getElementById(id);
  }

  /* 懒初始化 + 复用实例；容器尺寸变化自动 resize */
  function ensure(id) {
    var container = el(id);
    if (!container) return null;
    var hit = instances[id];
    if (hit && hit.container === container) return hit.chart;
    if (hit) { hit.chart.dispose(); delete instances[id]; }
    var chart = window.echarts.init(container, THEME, { renderer: 'canvas' });
    instances[id] = { chart: chart, container: container };
    /* 地图：排除区域（波多黎各 '72'）在绘制层置为不可见，见 hideExcludedRegions() */
    if (id === 'chart-geo') bindExcludedRegionHide(chart);
    if (window.ResizeObserver) {
      var ro = new ResizeObserver(function () { chart.resize(); });
      ro.observe(container);
      instances[id].ro = ro;
    }
    return chart;
  }

  function render(id, option) {
    var chart = ensure(id);
    if (!chart) return null;
    chart.setOption(option, true);
    return chart;
  }

  function on(id, eventName, handler) {
    var chart = ensure(id);
    if (chart) chart.on(eventName, handler);
  }

  function clear(id) {
    var chart = ensure(id);
    if (chart) chart.clear();
  }

  function disposeAll() {
    Object.keys(instances).forEach(function (id) {
      try { instances[id].chart.dispose(); } catch (e) { /* noop */ }
      if (instances[id].ro) { try { instances[id].ro.disconnect(); } catch (e) { /* noop */ } }
      delete instances[id];
    });
  }

  function resizeAll() {
    Object.keys(instances).forEach(function (id) {
      try { instances[id].chart.resize(); } catch (e) { /* noop */ }
    });
  }

  /* ---------------------------------------------------- 通用：横向条形 */
  function hbar(rows, opts) {
    /* rows: [{ name, value(展示值), color, tooltip }]，已按需要的顺序排好（自内向外） */
    return {
      color: CHART_COLORS,
      animationDuration: 420,
      grid: { left: 8, right: 76, top: opts.top || 26, bottom: 8, containLabel: true },
      toolbox: toolbox(opts.id),
      tooltip: Object.assign({ trigger: 'item', formatter: function (p) { return rows[p.dataIndex].tooltip || p.name; } }, TOOLTIP),
      xAxis: {
        type: 'value',
        axisLabel: Object.assign({ formatter: opts.valueFormatter || '{value}', hideOverlap: true }, AXIS_LABEL),
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: SPLIT_LINE
      },
      yAxis: {
        type: 'category',
        inverse: true,
        data: rows.map(function (r) { return r.name; }),
        axisLabel: Object.assign({ width: opts.labelWidth || 108, overflow: 'truncate' }, AXIS_LABEL),
        axisLine: AXIS_LINE,
        splitLine: SPLIT_LINE_OFF,
        axisTick: { show: false }
      },
      series: [{
        type: 'bar',
        data: rows.map(function (r) {
          return { value: r.value, itemStyle: { color: r.color, borderRadius: [0, 4, 4, 0] } };
        }),
        barMaxWidth: opts.barWidth || 16,
        label: {
          show: true,
          position: 'right',
          color: P.text,
          fontSize: 11,
          formatter: opts.labelFormatter || function (p) { return rows[p.dataIndex].label; }
        },
        emphasis: { itemStyle: { shadowBlur: 12, shadowColor: 'rgba(79,140,255,.55)' } },
        itemStyle: { borderRadius: [0, 4, 4, 0] }
      }]
    };
  }

  /* ---------------------------------------------------- 2. 各慢病患病率 */
  function prevalenceOption(payload) {
    var items = (payload.items || []).slice().sort(function (a, b) {
      return (b.prevalence || 0) - (a.prevalence || 0);
    });
    var rows = items.map(function (it) {
      return {
        name: it.name,
        value: Number((it.prevalence || 0) * 100),
        color: D.DISEASE_COLOR[it.key] || P.primary,
        label: D.pct(it.prevalence),
        tooltip: '<b>' + it.name + '</b><br/>患病率：' + D.pct(it.prevalence) +
          '<br/>病例数：' + D.int(it.cases) + ' 人' +
          '<br/>有效样本 n = ' + D.int(it.validSamples) +
          '<br/><span style="color:' + P.dim + '">分母：该病标志位非缺失记录</span>'
      };
    });
    var opt = hbar(rows, {
      id: 'chart-prevalence',
      labelWidth: 120,
      valueFormatter: function (v) { return v + '%'; },
      top: 26
    });
    opt.linkEntries = items.map(function (it, i) {
      return {
        name: it.name, seriesIndex: 0, dataIndex: i,
        topics: compactTopics(['disease:' + it.key, linkTopic('metric:', D.DISEASE_TO_METRIC[it.key])])
      };
    });
    opt.xAxis.name = '患病率(%)';
    opt.xAxis.nameTextStyle = Object.assign({ align: 'right' }, TITLE_STYLE, { color: P.dim, padding: [0, 0, 0, 10] });
    opt.xAxis.nameLocation = 'end';
    opt.xAxis.max = function (v) { return Math.ceil((v.max || 10) * 1.18); };
    return opt;
  }

  /* ---------------------------------------------------- 3. 年度趋势 */
  function hexToRgba(hex, alpha) {
    var h = String(hex).replace('#', '');
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    var n = parseInt(h, 16);
    return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + alpha + ')';
  }

  function trendOption(payload) {
    var isRatio = payload.unit === 'ratio';
    var lineColor = D.metricColor(payload.metric);
    var series = (payload.series || []).slice().sort(function (a, b) { return a.year - b.year; });
    var years = series.map(function (s) { return String(s.year); });
    var values = series.map(function (s) { return isRatio ? Number((s.value * 100).toFixed(3)) : Number(s.value); });
    var unitText = isRatio ? '率(%)' : (payload.metric === 'chronic_avg' ? '种/人' : '样本量(人)');
    var opt = {
      color: CHART_COLORS,
      animationDuration: 420,
      grid: { left: 10, right: 18, top: 42, bottom: 6, containLabel: true },
      toolbox: toolbox('chart-trend'),
      tooltip: Object.assign({
        trigger: 'axis',
        formatter: function (ps) {
          var p = ps[0];
          var s = series[p.dataIndex];
          var lines = [
            '<b>' + p.axisValue + ' 年</b>',
            payload.label + '：' + p.data + (isRatio ? '%' : '')
          ];
          if (s && s.denominator != null) lines.push('分母 n = ' + D.int(s.denominator));
          if (s && s.numerator != null) lines.push('分子 = ' + D.int(s.numerator));
          lines.push('<span style="color:' + P.dim + '">口径：' + payload.label + ' · ' + unitText + '</span>');
          return lines.join('<br/>');
        }
      }, TOOLTIP),
      xAxis: {
        type: 'category',
        data: years,
        boundaryGap: false,
        axisLabel: AXIS_LABEL,
        axisLine: AXIS_LINE,
        splitLine: SPLIT_LINE_OFF,
        axisTick: { show: false }
      },
      yAxis: {
        type: 'value',
        name: unitText,
        nameGap: 16,
        nameTextStyle: { color: P.dim, fontSize: 11, align: 'left' },
        scale: true,
        axisLabel: Object.assign({ formatter: isRatio ? '{value}%' : '{value}' }, AXIS_LABEL),
        splitLine: SPLIT_LINE,
        axisLine: { show: false }
      },
      series: [{
        name: payload.label,
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 8,
        data: values,
        lineStyle: { width: 2.4, color: lineColor },
        itemStyle: { color: lineColor, borderColor: '#0b1322', borderWidth: 2 },
        areaStyle: {
          color: new window.echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: hexToRgba(lineColor, 0.42) },
            { offset: 1, color: hexToRgba(lineColor, 0.02) }
          ])
        },
        label: {
          show: true,
          position: 'top',
          color: P.text,
          fontSize: 11,
          formatter: function (p) { return isRatio ? (p.data + '%') : p.data; }
        }
      }]
    };
    opt.linkEntries = series.map(function (s, i) {
      return {
        name: String(s.year), seriesIndex: 0, dataIndex: i,
        topics: compactTopics([linkTopic('metric:', payload.metric), linkTopic('year:', s.year)])
      };
    });
    return opt;
  }

  /* ---------------------------------------------------- 5. 危险因素暴露率 */
  function factorOption(payload) {
    var items = (payload.items || []).slice().sort(function (a, b) { return (a.rate || 0) - (b.rate || 0); });
    var rows = items.map(function (it) {
      return {
        name: it.name,
        value: Number((it.rate * 100).toFixed(2)),
        color: it.rate >= 0.5 ? P.rose : (it.rate >= 0.25 ? P.amber : P.teal),
        label: D.pct(it.rate, 1) + ' · n=' + D.compact(it.validSamples),
        tooltip: '<b>' + it.name + '</b><br/>暴露率：' + D.pct(it.rate) +
          '<br/>暴露人数：' + D.int(it.exposed) +
          '<br/>有效样本 n = ' + D.int(it.validSamples) +
          '<br/><span style="color:' + P.dim + '">字段 ' + (it.field || '') + '；分母为该字段非缺失记录</span>'
      };
    });
    var opt = hbar(rows, { id: 'chart-factors', labelWidth: 132, valueFormatter: function (v) { return v + '%'; }, top: 26, barWidth: 13 });
    opt.linkEntries = items.map(function (it, i) {
      return {
        name: it.name, seriesIndex: 0, dataIndex: i,
        topics: compactTopics(['factor:' + it.key, linkTopic('metric:', D.FACTOR_TO_METRIC[it.key])])
      };
    });
    opt.xAxis.name = '暴露率(%)';
    opt.xAxis.nameTextStyle = { color: P.dim, fontSize: 11 };
    opt.xAxis.nameLocation = 'end';
    opt.xAxis.max = function (v) { return Math.ceil((v.max || 10) * 1.1); };
    return opt;
  }

  /* ---------------------------------------------------- 6a. 风险分层堆叠条 */
  function stratifyLevelOption(payload) {
    var levels = payload.levels || [];
    var colorOf = { '低风险': P.low, '中风险': P.mid, '高风险': P.high };
    var series = levels.map(function (lv) {
      return {
        name: lv.level,
        type: 'bar',
        stack: 'level',
        barWidth: 44,
        data: [Number((lv.share * 100).toFixed(3))],
        itemStyle: { color: colorOf[lv.level] || P.primary },
        label: {
          show: true,
          color: '#08111f',
          fontSize: 11,
          fontWeight: 600,
          formatter: function (p) { return lv.share >= 0.04 ? (p.data.toFixed(1) + '%') : ''; }
        }
      };
    });
    var opt = {
      color: CHART_COLORS,
      animationDuration: 420,
      grid: { left: 8, right: 8, top: 26, bottom: 30, containLabel: true },
      toolbox: toolbox('chart-stratify-level'),
      legend: {
        bottom: 0,
        textStyle: { color: P.text2, fontSize: 11 },
        itemWidth: 10,
        itemHeight: 8,
        formatter: function (name) {
          var hit = levels.filter(function (x) { return x.level === name; })[0];
          return hit ? (name + ' ' + D.pct(hit.share, 1)) : name;
        }
      },
      tooltip: Object.assign({
        trigger: 'item',
        formatter: function (p) {
          var lv = levels[p.seriesIndex] || {};
          return '<b>' + p.seriesName + '</b><br/>样本：' + D.int(lv.samples) +
            '<br/>占比：' + D.pct(lv.share) + '<br/><span style="color:' + P.dim + '">规则：' + (lv.rule || '') + '</span>';
        }
      }, TOOLTIP),
      xAxis: {
        type: 'value', max: 100, axisLabel: Object.assign({ formatter: '{value}%' }, AXIS_LABEL),
        splitLine: SPLIT_LINE, axisLine: { show: false }
      },
      yAxis: { type: 'category', data: ['风险分层构成'], axisLabel: AXIS_LABEL, axisLine: AXIS_LINE, splitLine: SPLIT_LINE_OFF, axisTick: { show: false } },
      series: series
    };
    opt.linkEntries = levels.map(function (lv, si) {
      return { name: lv.level, seriesIndex: si, dataIndex: 0, topics: ['level:' + lv.level] };
    });
    return opt;
  }

  /* ---------------------------------------------------- 6b. 慢病数分布 */
  function chronicDistOption(payload) {
    var dist = payload.distribution || [];
    var opt = {
      color: CHART_COLORS,
      animationDuration: 420,
      grid: { left: 8, right: 12, top: 30, bottom: 6, containLabel: true },
      toolbox: toolbox('chart-chronic-dist'),
      tooltip: Object.assign({
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: function (ps) {
          var p = ps[0];
          var item = dist[p.dataIndex] || {};
          return '<b>' + p.axisValue + ' 慢病</b><br/>样本：' + D.int(item.samples) +
            '<br/>占比：' + D.pct(item.share) + '<br/><span style="color:' + P.dim + '">占有效样本 ' + D.int(payload.validSamples) + '</span>';
        }
      }, TOOLTIP),
      xAxis: {
        type: 'category',
        data: dist.map(function (d) { return d.label; }),
        axisLabel: AXIS_LABEL, axisLine: AXIS_LINE, splitLine: SPLIT_LINE_OFF, axisTick: { show: false }
      },
      yAxis: {
        type: 'value', name: '样本量(人)', nameTextStyle: { color: P.dim, fontSize: 11 },
        axisLabel: Object.assign({ formatter: function (v) { return D.compact(v); }, hideOverlap: true }, AXIS_LABEL),
        splitLine: SPLIT_LINE, axisLine: { show: false }
      },
      series: [{
        type: 'bar',
        barMaxWidth: 42,
        data: dist.map(function (d) { return d.samples; }),
        itemStyle: {
          borderRadius: [4, 4, 0, 0],
          color: new window.echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: P.cyan }, { offset: 1, color: 'rgba(34,211,238,0.18)' }
          ])
        },
        label: {
          show: true, position: 'top', color: P.text, fontSize: 10,
          formatter: function (p) { return D.pct(dist[p.dataIndex].share, 1); }
        }
      }]
    };
    opt.linkEntries = dist.map(function (d, i) {
      return { name: d.label, seriesIndex: 0, dataIndex: i, topics: ['bucket:' + d.label] };
    });
    return opt;
  }

  /* ---------------------------------------------------- 4. 州级地图 */
  /* 地图 series 额外剔除的 FIPS：'72' 波多黎各在 us-states.geojson 里是本土框外的一块孤立方块
     （AK/HI 是 inset 画在大陆框内），易被误读为本土州。只剔除地图 series 数据，
     不动 vendor/geojson 源文件、不动接口返回、不影响任何其它面板口径。 */
  var MAP_EXCLUDE_FIPS = ['72'];
  /* 连续色带：冷端不再用 #123456（与面板底色 #152238 几乎同色，低值州会成"黑洞"），
     改为与底色可辨的深蓝起，仍保持"冷=低、暖=高"的原语义与档数级差。 */
  var GEO_RAMP = ['#2b6cb0', '#22a3b8', '#2dd4bf', '#f5a524', '#fb7185'];
  /* 无数据州：中灰，与底色可辨，且不与色带任意一档重合 */
  var GEO_NO_DATA = '#3a4a63';
  function geoOption(payload, metricKey, selectedFips) {
    var isRatio = payload.unit === 'ratio';
    var items = payload.items || [];
    var data = items
      .filter(function (it) {
        var fips = D.padFips(it.stateFips);
        return D.NO_GEOMETRY.indexOf(fips) < 0 && MAP_EXCLUDE_FIPS.indexOf(fips) < 0;
      })
      .map(function (it) {
        return {
          name: D.padFips(it.stateFips),
          value: isRatio ? Number((it.value * 100).toFixed(3)) : Number(it.value),
          raw: it
        };
      });
    var values = data.map(function (d) { return d.value; });
    var min = values.length ? Math.min.apply(null, values) : 0;
    var max = values.length ? Math.max.apply(null, values) : 1;
    var opt = {
      color: CHART_COLORS,
      animationDuration: 520,
      toolbox: toolbox('chart-geo'),
      tooltip: Object.assign({
        trigger: 'item',
        formatter: function (p) {
          /* 排除区域（波多黎各）保留了绘制元素与命中（避免提示/下钻穿透到相邻州），此处不给任何提示 */
          if (p && p.name != null && MAP_EXCLUDE_FIPS.indexOf(String(p.name)) >= 0) return '';
          var raw = p.data && p.data.raw;
          if (!raw) return '<b>' + D.stateFull(p.name) + '</b><br/>无数据（该州未返回）';
          return '<b>' + D.stateFull(raw.stateFips) + '</b><br/>' +
            payload.label + '：' + (isRatio ? D.pct(raw.value) : D.int(raw.value)) +
            '<br/>分子：' + D.int(raw.numerator) + '<br/>分母 n = ' + D.int(raw.denominator) +
            '<br/><span style="color:' + P.dim + '">点击查看该州慢病明细</span>';
        }
      }, TOOLTIP),
      visualMap: {
        type: 'continuous',
        min: Number(min.toFixed(3)),
        max: Number(max.toFixed(3)),
        left: 6,
        bottom: 6,
        itemWidth: 12,
        itemHeight: 92,
        calculable: true,
        text: [isRatio ? '高 ' + max.toFixed(1) + '%' : '高 ' + D.compact(max), isRatio ? '低 ' + min.toFixed(1) + '%' : '低 ' + D.compact(min)],
        textStyle: { color: P.text2, fontSize: 10 },
        inRange: { color: GEO_RAMP }
      },
      series: [{
        name: payload.label,
        type: 'map',
        map: 'brfss-usa',
        roam: true,
        zoom: 1.04,
        selectedMode: 'single',
        layoutCenter: ['50%', '50%'],
        layoutSize: '96%',
        label: { show: false, formatter: function (p) { return D.stateShort(p.name); } },
        itemStyle: {
          areaColor: GEO_NO_DATA,
          borderColor: 'rgba(120,152,200,0.45)',
          borderWidth: 0.7,
          shadowColor: 'rgba(0,0,0,0.45)',
          shadowBlur: 6
        },
        emphasis: {
          label: { show: true, color: '#fff', fontSize: 11, formatter: function (p) { return D.stateShort(p.name); } },
          itemStyle: { areaColor: P.primary, borderColor: '#fff', borderWidth: 1.1 }
        },
        select: {
          label: { show: true, color: '#fff', fontSize: 11, formatter: function (p) { return D.stateShort(p.name); } },
          itemStyle: { areaColor: P.amber, borderColor: '#fff', borderWidth: 1.2 }
        },
        /* 排除区域（波多黎各）覆盖声明。注意：ECharts 5 的 map series 区域样式取自数据项模型，
           regions 只被 geo 组件消费，这里的覆盖对 map series 是空操作（实测像素与 tooltip 均无变化）。
           真正的"渲染层不可见"由 hideExcludedRegions() 在每次重绘后完成，此声明保留用于表达意图。 */
        regions: MAP_EXCLUDE_FIPS.map(function (fips) {
          return {
            name: fips,
            silent: true,
            itemStyle: { areaColor: 'transparent', borderColor: 'transparent', borderWidth: 0 },
            label: { show: false },
            emphasis: {
              label: { show: false },
              itemStyle: { areaColor: 'transparent', borderColor: 'transparent', borderWidth: 0 }
            }
          };
        }),
        data: data
      }]
    };
    /* 该指标的极值州：指标级 hover 联动时地图高亮它，而不是整块变蓝 */
    opt.linkPeak = data.reduce(function (best, d, i) {
      return (best < 0 || Number(d.value) > Number(data[best].value)) ? i : best;
    }, -1);
    if (opt.linkPeak < 0) opt.linkPeak = null;
    opt.linkEntries = data.map(function (d, i) {
      var raw = d.raw || {};
      return {
        name: d.name, seriesIndex: 0, dataIndex: i,
        topics: compactTopics([linkTopic('fips:', D.padFips(raw.stateFips || d.name)), linkTopic('metric:', metricKey)])
      };
    });
    return opt;
  }

  /* ---- 排除区域（波多黎各 FIPS '72'）的渲染层剔除 ----
     ECharts 5 的 map series 会把地图中未出现在 series.data 的区域补成空数据项继续绘制，
     这些区域的样式来自数据项模型，series.regions 对其不生效（见上面 regions 处的说明）。
     这里在每次重绘后把该区域的绘制元素改成"全透明 + 无状态样式"：
       · 透明填充/描边、无阴影 ⇒ 视觉上完全不可见（不依赖底色，也不会变成另一种可见色块）；
       · 保留命中（不置 ignore/silent）⇒ 鼠标落在原方块位置命中的是它自己，不会穿透到相邻州
         （实测置 silent 后该点会落到佛州 bbox 上，弹出佛州提示），点击下钻也仍指向该州；
       · 清空 states ⇒ 悬停不换色、不弹 label；
       · 悬停提示由 geoOption 的 tooltip.formatter 对该州返回空串。
     区域元素由 MapDraw 在每次重绘时重建（resize / restore / setOption 都会触发），
     所以挂在 'rendered' 事件上反复执行；元素上的 ECData（ECharts 内部数据索引）用于定位区域。 */
  var EC_DATA_KEY = null;
  function ecData(el) {
    if (!EC_DATA_KEY) {
      var keys = Object.keys(el);
      for (var k = 0; k < keys.length; k++) {
        if (keys[k].indexOf('__ec_inner_') === 0) { EC_DATA_KEY = keys[k]; break; }
      }
    }
    return EC_DATA_KEY ? el[EC_DATA_KEY] : null;
  }

  function hideExcludedRegions(chart) {
    var model = chart.getModel && chart.getModel();
    var series = model && model.getSeriesByIndex(0);
    var data = series && series.getData && series.getData();
    if (!data || !data.count || !data.count()) return;
    var indexes = MAP_EXCLUDE_FIPS
      .map(function (fips) { return data.indexOfName(fips); })
      .filter(function (idx) { return idx >= 0; });
    if (!indexes.length) return;
    var list = chart.getZr().storage.getDisplayList();
    var changed = false;
    for (var i = 0; i < list.length; i++) {
      var el = list[i];
      var ec = ecData(el);
      if (!ec || ec.seriesIndex !== 0 || indexes.indexOf(ec.dataIndex) < 0) continue;
      var style = el.style;
      if (style && style.fill !== 'transparent') {
        style.fill = 'transparent';
        style.stroke = 'transparent';
        style.lineWidth = 0;
        style.shadowBlur = 0;
        style.shadowColor = 'transparent';
        changed = true;
      }
      el.silent = false;   /* 保留命中：挡在相邻州前面，提示与下钻都不会落到别的州 */
      el.states = {};      /* 悬停/选中态失效：不换色、不弹 label */
      if (el.dirtyStyle) el.dirtyStyle();
    }
    /* 本帧已经画上去的像素需要再刷新一次才会消失；下一次 'rendered' 时 changed 为 false，不会递归 */
    if (changed) chart.getZr().refresh();
  }

  function bindExcludedRegionHide(chart) {
    if (!chart || chart.__excludedRegionBound) return;
    chart.__excludedRegionBound = true;
    chart.on('rendered', function () {
      try { hideExcludedRegions(chart); } catch (e) { /* 内部结构变化时不阻断主流程 */ }
    });
  }

  /* ---------------------------------------------------- 7. 模型指标对比 */
  /* 模型中文短名：x 轴空间有限，完整名放在 tooltip / 图例里 */
  function shortModelName(name) {
    var set = '';
    if (/_SetA_tuned$/.test(name)) { set = 'A·调优'; name = name.replace(/_SetA_tuned$/, ''); }
    else if (/_SetA$/.test(name)) { set = 'A'; name = name.replace(/_SetA$/, ''); }
    else if (/_SetB$/.test(name)) { set = 'B'; name = name.replace(/_SetB$/, ''); }
    var base = { LogisticRegression: 'LR', RandomForest: 'RF', LightGBM: 'LGBM' }[name] || name;
    return set ? base + '-' + set : base;
  }

  /* 指标中文说明（tooltip 显示） */
  var METRIC_CN = {
    auc_roc: 'AUC-ROC', auc_pr: 'PR-AUC', f1: 'F1', accuracy: '准确率',
    recall: '召回率', brier: 'Brier 分数', cv_auc_mean: '交叉验证 AUC 均值',
    cv_auc_std: '交叉验证 AUC 标准差', auc_gain_after_tuning: '调优后 AUC 增量'
  };

  /* 默认只展开 2 个核心指标；其余通过图例点选，
     避免 7 模型 × 9 指标 = 63 根柱挤在 300px 面板里导致标签互相覆盖。 */
  var CORE_METRICS = ['auc_roc', 'auc_pr'];

  function modelMetricOption(payload) {
    var items = payload.items || [];
    var models = [];
    var metricsAll = [];
    items.forEach(function (it) {
      if (models.indexOf(it.model_name) < 0) models.push(it.model_name);
      if (metricsAll.indexOf(it.metric) < 0) metricsAll.push(it.metric);
    });
    /* 核心指标排前面，保证颜色与图例顺序稳定 */
    var metrics = CORE_METRICS.filter(function (m) { return metricsAll.indexOf(m) >= 0; })
      .concat(metricsAll.filter(function (m) { return CORE_METRICS.indexOf(m) < 0; }));

    var colorList = [P.primary, P.teal, P.amber, P.violet, P.rose, P.cyan];
    var nCore = CORE_METRICS.filter(function (m) { return metricsAll.indexOf(m) >= 0; }).length || 1;

    /* 按当前可见柱数估算每根柱可用宽度，决定标签是否显示、字号多大。
       面板宽约 470px，7 个模型分组。 */
    var groupWidth = 470 / Math.max(models.length, 1);
    var barWidth = groupWidth / Math.max(nCore, 1);
    var labelFontSize = barWidth >= 34 ? 10 : (barWidth >= 26 ? 9 : 8);
    var showLabel = barWidth >= 24;          // 太窄就不显示，交给 tooltip
    var labelDigits = barWidth >= 40 ? 4 : (barWidth >= 30 ? 3 : 2);

    var selected = {};
    metrics.forEach(function (m) { selected[m.toUpperCase()] = CORE_METRICS.indexOf(m) >= 0; });

    var series = metrics.map(function (metric, mi) {
      var isCore = CORE_METRICS.indexOf(metric) >= 0;
      return {
        name: metric.toUpperCase(),
        type: 'bar',
        barMaxWidth: 22,
        barGap: '15%',
        barCategoryGap: '38%',
        itemStyle: { color: colorList[mi % colorList.length], borderRadius: [3, 3, 0, 0] },
        label: {
          show: showLabel && isCore,
          position: 'top',
          color: P.text,
          fontSize: labelFontSize,
          distance: 3,
          formatter: function (pt) {
            return pt.data == null ? '' : Number(pt.data).toFixed(labelDigits);
          }
        },
        emphasis: { focus: 'series' },
        /* 兜底：用户在图例里展开更多指标后柱会变窄，
           ECharts 会自动隐藏互相重叠的标签，避免再次糊在一起 */
        labelLayout: { hideOverlap: true },
        data: models.map(function (m) {
          var hit = items.filter(function (it) { return it.model_name === m && it.metric === metric; })[0];
          return hit ? Number(hit.value) : null;
        })
      };
    });

    var opt = {
      color: CHART_COLORS,
      animationDuration: 420,
      /* top 由 34 → 46：图例固定单行（scroll），并给 y 轴名称留出空隙 */
      grid: { left: 10, right: 14, top: 46, bottom: 8, containLabel: true },
      toolbox: toolbox('chart-metrics'),
      legend: {
        top: 2,
        type: 'scroll',                 // 单行横向滚动，避免换行后压住绘图区
        pageIconSize: 8,
        pageTextStyle: { color: P.text2, fontSize: 10 },
        itemWidth: 9,
        itemHeight: 8,
        itemGap: 12,
        textStyle: { color: P.text2, fontSize: 10 },
        selected: selected
      },
      tooltip: Object.assign({
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: function (ps) {
          var full = ps[0].axisValue;
          var head = '<b>' + full + '</b>';
          var body = ps.map(function (pt) {
            var name = METRIC_CN[pt.seriesName.toLowerCase()] || pt.seriesName;
            return pt.marker + ' ' + name + '：' + (pt.data == null ? '—' : Number(pt.data).toFixed(4));
          }).join('<br/>');
          return head + '<br/>' + body;
        }
      }, TOOLTIP),
      xAxis: {
        type: 'category',
        data: models,
        axisLabel: Object.assign({}, AXIS_LABEL, {
          interval: 0,
          fontSize: 10,
          rotate: 0,
          formatter: shortModelName
        }),
        axisLine: AXIS_LINE,
        splitLine: SPLIT_LINE_OFF,
        axisTick: { show: false }
      },
      yAxis: {
        type: 'value',
        name: '值(0–1)',
        nameLocation: 'end',
        nameGap: 8,
        nameTextStyle: { color: P.dim, fontSize: 10, align: 'left', padding: [0, 0, 0, -26] },
        min: 0,
        max: 1,
        axisLabel: AXIS_LABEL,
        splitLine: SPLIT_LINE,
        axisLine: { show: false }
      },
      series: series
    };
    opt.linkEntries = [];
    models.forEach(function (m, mi) {
      series.forEach(function (s, si) {
        opt.linkEntries.push({ name: m, seriesIndex: si, dataIndex: mi, topics: ['model:' + m] });
      });
    });
    return opt;
  }

  /* ---------------------------------------------------- 8. 年龄组共病率 */
  function ageOption(payload) {
    var rows = (payload.byAge || []).slice().sort(function (a, b) { return a.ageGrp - b.ageGrp; });
    var opt = {
      color: CHART_COLORS,
      animationDuration: 420,
      grid: { left: 8, right: 18, top: 34, bottom: 6, containLabel: true },
      toolbox: toolbox('chart-age'),
      legend: { top: 0, textStyle: { color: P.text2, fontSize: 11 }, itemWidth: 10, itemHeight: 8 },
      tooltip: Object.assign({
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: function (ps) {
          var r = rows[ps[0].dataIndex] || {};
          return '<b>' + r.ageLabel + ' 岁</b><br/>样本量 n = ' + D.int(r.samples) +
            '<br/>共病病例：' + D.int(r.multimorbidityCases) +
            '<br/>共病率：' + D.pct(r.multimorbidityRate);
        }
      }, TOOLTIP),
      xAxis: {
        type: 'category',
        data: rows.map(function (r) { return r.ageLabel; }),
        axisLabel: Object.assign({ rotate: rows.length > 10 ? 32 : 0, hideOverlap: true }, AXIS_LABEL),
        axisLine: AXIS_LINE,
        splitLine: SPLIT_LINE_OFF,
        axisTick: { show: false }
      },
      yAxis: [
        {
          type: 'value', name: '样本量(人)', nameTextStyle: { color: P.dim, fontSize: 11 },
          axisLabel: Object.assign({ formatter: function (v) { return D.compact(v); } }, AXIS_LABEL),
          splitLine: SPLIT_LINE, axisLine: { show: false }
        },
        {
          type: 'value', name: '共病率(%)', nameTextStyle: { color: P.amber, fontSize: 11 },
          axisLabel: Object.assign({ formatter: '{value}%' }, AXIS_LABEL),
          splitLine: SPLIT_LINE_OFF, axisLine: { show: false }
        }
      ],
      series: [
        {
          name: '样本量(人)',
          type: 'bar',
          barMaxWidth: 30,
          data: rows.map(function (r) { return r.samples; }),
          itemStyle: {
            borderRadius: [3, 3, 0, 0],
            color: new window.echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(79,140,255,0.92)' },
              { offset: 1, color: 'rgba(79,140,255,0.16)' }
            ])
          }
        },
        {
          name: '共病率(%)',
          type: 'line',
          yAxisIndex: 1,
          smooth: true,
          symbol: 'circle',
          symbolSize: 6,
          data: rows.map(function (r) { return Number((r.multimorbidityRate * 100).toFixed(2)); }),
          lineStyle: { width: 2.2, color: P.amber },
          itemStyle: { color: P.amber, borderColor: '#0b1322', borderWidth: 1.5 }
        }
      ]
    };
    opt.linkEntries = [];
    rows.forEach(function (r, i) {
      [0, 1].forEach(function (si) {
        opt.linkEntries.push({ name: r.ageLabel, seriesIndex: si, dataIndex: i, topics: ['age:' + r.ageLabel] });
      });
    });
    return opt;
  }

  /* ---------------------------------------------------- 9. 预测概率仪表 */
  function gaugeOption(probability, riskLevel) {
    var pctVal = Number((probability * 100).toFixed(2));
    var color = riskLevel === '高风险' ? P.high : (riskLevel === '中风险' ? P.mid : P.low);
    return {
      animationDuration: 500,
      toolbox: toolbox('chart-gauge'),
      series: [{
        type: 'gauge',
        startAngle: 205,
        endAngle: -25,
        min: 0,
        max: 100,
        radius: '92%',
        center: ['50%', '70%'],
        progress: { show: true, width: 12, itemStyle: { color: color } },
        axisLine: { lineStyle: { width: 12, color: [[1, 'rgba(120,152,200,0.16)']] } },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { show: false },
        pointer: { width: 4, length: '58%', itemStyle: { color: color } },
        anchor: { show: true, size: 8, itemStyle: { color: color } },
        detail: {
          valueAnimation: true,
          offsetCenter: [0, '-14%'],
          fontSize: 28,
          fontWeight: 700,
          color: '#fff',
          formatter: function (v) { return v.toFixed(1) + '%'; }
        },
        title: { show: false },
        data: [{ value: pctVal, name: '共病阳性预测概率' }]
      }]
    };
  }

  NS.charts = {
    ensure: ensure, render: render, on: on, clear: clear, resizeAll: resizeAll, disposeAll: disposeAll,
    prevalenceOption: prevalenceOption,
    trendOption: trendOption,
    factorOption: factorOption,
    stratifyLevelOption: stratifyLevelOption,
    chronicDistOption: chronicDistOption,
    geoOption: geoOption,
    modelMetricOption: modelMetricOption,
    ageOption: ageOption,
    gaugeOption: gaugeOption
  };
})(window.BRFSS = window.BRFSS || {});
