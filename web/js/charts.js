/* =============================================================
   charts.js —— ECharts 实例管理 + 各图表 Option 构造器
   所有图表共用一套色板/字号/坐标轴样式，只在此处集中定义
   ============================================================= */
(function (NS) {
  'use strict';

  var D = NS.dict;
  var P = D.PALETTE;
  var instances = {};   /* id -> { chart, container } */

  var AXIS_LABEL = { color: P.text2, fontSize: 11 };
  var AXIS_LINE = { lineStyle: { color: P.lineStrong } };
  var SPLIT_LINE = { lineStyle: { color: P.line, type: 'dashed' } };
  var TOOLTIP = {
    backgroundColor: 'rgba(10,18,32,0.96)',
    borderColor: P.lineStrong,
    borderWidth: 1,
    padding: [8, 11],
    textStyle: { color: P.text, fontSize: 12, lineHeight: 18 },
    extraCssText: 'box-shadow:0 8px 26px rgba(0,0,0,.5);border-radius:8px;max-width:320px;white-space:normal;'
  };
  var TITLE_STYLE = { color: P.text, fontSize: 12 };

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
    var chart = window.echarts.init(container, null, { renderer: 'canvas' });
    instances[id] = { chart: chart, container: container };
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
      animationDuration: 420,
      grid: { left: 8, right: 76, top: opts.top || 14, bottom: 8, containLabel: true },
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
      labelWidth: 120,
      valueFormatter: function (v) { return v + '%'; },
      top: 10
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
    return {
      animationDuration: 420,
      grid: { left: 10, right: 18, top: 30, bottom: 6, containLabel: true },
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
        axisTick: { show: false }
      },
      yAxis: {
        type: 'value',
        name: unitText,
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
    var opt = hbar(rows, { labelWidth: 132, valueFormatter: function (v) { return v + '%'; }, top: 6, barWidth: 13 });
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
    return {
      animationDuration: 420,
      grid: { left: 8, right: 8, top: 8, bottom: 30, containLabel: true },
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
      yAxis: { type: 'category', data: ['风险分层构成'], axisLabel: AXIS_LABEL, axisLine: AXIS_LINE, axisTick: { show: false } },
      series: series
    };
  }

  /* ---------------------------------------------------- 6b. 慢病数分布 */
  function chronicDistOption(payload) {
    var dist = payload.distribution || [];
    return {
      animationDuration: 420,
      grid: { left: 8, right: 12, top: 26, bottom: 6, containLabel: true },
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
        axisLabel: AXIS_LABEL, axisLine: AXIS_LINE, axisTick: { show: false }
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
  }

  /* ---------------------------------------------------- 4. 州级地图 */
  function geoOption(payload, metricKey, selectedFips) {
    var isRatio = payload.unit === 'ratio';
    var items = payload.items || [];
    var data = items
      .filter(function (it) { return D.NO_GEOMETRY.indexOf(D.padFips(it.stateFips)) < 0; })
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
    return {
      animationDuration: 520,
      tooltip: Object.assign({
        trigger: 'item',
        formatter: function (p) {
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
        inRange: { color: ['#123456', '#1b5e8a', '#22a3b8', '#2dd4bf', '#f5a524', '#fb7185'] }
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
          areaColor: '#16233a',
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
        data: data
      }]
    };
  }

  /* ---------------------------------------------------- 7. 模型指标对比 */
  function modelMetricOption(payload) {
    var items = payload.items || [];
    var models = [];
    var metrics = [];
    items.forEach(function (it) {
      if (models.indexOf(it.model_name) < 0) models.push(it.model_name);
      if (metrics.indexOf(it.metric) < 0) metrics.push(it.metric);
    });
    var colorList = [P.primary, P.teal, P.amber, P.violet, P.rose, P.cyan];
    var series = metrics.map(function (metric, mi) {
      return {
        name: metric.toUpperCase(),
        type: 'bar',
        barMaxWidth: 26,
        barGap: '20%',
        itemStyle: { color: colorList[mi % colorList.length], borderRadius: [4, 4, 0, 0] },
        label: { show: true, position: 'top', color: P.text, fontSize: 10, formatter: function (p) { return p.data == null ? '' : Number(p.data).toFixed(4); } },
        data: models.map(function (m) {
          var hit = items.filter(function (it) { return it.model_name === m && it.metric === metric; })[0];
          return hit ? Number(hit.value) : null;
        })
      };
    });
    return {
      animationDuration: 420,
      grid: { left: 8, right: 12, top: 34, bottom: 6, containLabel: true },
      legend: { top: 0, textStyle: { color: P.text2, fontSize: 11 }, itemWidth: 10, itemHeight: 8 },
      tooltip: Object.assign({
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: function (ps) {
          var head = '<b>' + ps[0].axisValue + '</b>';
          var body = ps.map(function (p) {
            return p.marker + ' ' + p.seriesName + '：' + (p.data == null ? '—' : Number(p.data).toFixed(4));
          }).join('<br/>');
          return head + '<br/>' + body;
        }
      }, TOOLTIP),
      xAxis: { type: 'category', data: models, axisLabel: AXIS_LABEL, axisLine: AXIS_LINE, axisTick: { show: false } },
      yAxis: {
        type: 'value',
        name: '指标值（0–1）',
        nameTextStyle: { color: P.dim, fontSize: 11 },
        min: 0,
        max: 1,
        axisLabel: AXIS_LABEL,
        splitLine: SPLIT_LINE,
        axisLine: { show: false }
      },
      series: series
    };
  }

  /* ---------------------------------------------------- 8. 年龄组共病率 */
  function ageOption(payload) {
    var rows = (payload.byAge || []).slice().sort(function (a, b) { return a.ageGrp - b.ageGrp; });
    return {
      animationDuration: 420,
      grid: { left: 8, right: 18, top: 34, bottom: 6, containLabel: true },
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
          splitLine: { show: false }, axisLine: { show: false }
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
  }

  /* ---------------------------------------------------- 9. 预测概率仪表 */
  function gaugeOption(probability, riskLevel) {
    var pctVal = Number((probability * 100).toFixed(2));
    var color = riskLevel === '高风险' ? P.high : (riskLevel === '中风险' ? P.mid : P.low);
    return {
      animationDuration: 500,
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
