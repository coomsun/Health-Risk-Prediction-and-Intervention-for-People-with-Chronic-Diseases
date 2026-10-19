/* web/vue/js/app.js — Vue 3 根组件：编排数据加载与图表 option 构造 */
(function (global) {
  "use strict";
  var vue = global.Vue;
  var createApp = vue.createApp;
  var defineComponent = vue.defineComponent;
  var ref = vue.ref;
  var computed = vue.computed;
  var onMounted = vue.onMounted;
  var C = global.VueComponents;

  var PALETTE = ["#2E6DA4", "#E45756", "#54A24B", "#F58518", "#B279A2",
                 "#EECA3B", "#4C78A8", "#9D755D", "#72B7B2"];

  function yuan(n) {
    if (n === null || n === undefined) return "—";
    if (n >= 1e8) return (n / 1e8).toFixed(2) + " 亿";
    if (n >= 1e4) return (n / 1e4).toFixed(1) + " 万";
    return String(n);
  }
  function pct(x) {
    return (x === null || x === undefined) ? "—" : (x * 100).toFixed(2) + "%";
  }

  var App = defineComponent({
    name: "App",
    components: { KpiCards: C.KpiCards, ChartCard: C.ChartCard, PredictForm: C.PredictForm },
    setup: function () {
      var loading = ref(true);
      var error = ref(null);
      var overview = ref(null);
      var prevalence = ref(null);
      var trend = ref(null);
      var factors = ref(null);
      var stratify = ref(null);

      function loadAll() {
        loading.value = true; error.value = null;
        Promise.all([
          global.API.get("/api/v1/overview"),
          global.API.get("/api/v1/chronic/prevalence?year=2023"),
          global.API.get("/api/v1/trend?metric=multimorbidity_rate"),
          global.API.get("/api/v1/risk/factors?year=2023"),
          global.API.get("/api/v1/risk/stratify")
        ]).then(function (res) {
          overview.value = res[0];
          prevalence.value = res[1];
          trend.value = res[2];
          factors.value = res[3];
          stratify.value = res[4];
        }).catch(function (e) {
          error.value = e.message || String(e);
        }).finally(function () { loading.value = false; });
      }

      onMounted(loadAll);

      var kpis = computed(function () {
        var o = overview.value || {};
        var span = o.yearSpan || {};
        return [
          { label: "总样本量", value: yuan(o.totalSamples) },
          { label: "年份跨度", value: (span.min && span.max) ? (span.min + "–" + span.max + "（" + span.years + " 年）") : "—" },
          { label: "共病率", value: pct(o.multimorbidityRate) },
          { label: "慢病种类 / 州数", value: (o.chronicTypes || "—") + " 类 / " + (o.stateCount || "—") }
        ];
      });

      var prevalenceOption = computed(function () {
        var d = prevalence.value;
        if (!d || !d.items) return null;
        // 注意：患病率接口字段名是 prevalence（不是 rate）
        var rows = d.items.slice().sort(function (a, b) { return a.prevalence - b.prevalence; });
        return {
          color: PALETTE,
          grid: { left: 90, right: 40, top: 20, bottom: 40 },
          tooltip: { trigger: "axis", valueFormatter: function (v) { return (v * 100).toFixed(2) + "%"; } },
          xAxis: { type: "value", axisLabel: { formatter: function (v) { return (v * 100).toFixed(0) + "%"; } } },
          yAxis: { type: "category", data: rows.map(function (r) { return r.name; }) },
          series: [{ type: "bar", data: rows.map(function (r) { return r.prevalence; }),
                     itemStyle: { borderRadius: [0, 4, 4, 0] },
                     label: { show: true, position: "right",
                              formatter: function (p) { return (p.value * 100).toFixed(1) + "%"; } } }]
        };
      });

      var trendOption = computed(function () {
        var d = trend.value;
        if (!d || !d.series) return null;
        var items = d.series;
        return {
          color: [PALETTE[0]],
          grid: { left: 60, right: 30, top: 30, bottom: 40 },
          tooltip: { trigger: "axis", valueFormatter: function (v) { return (v * 100).toFixed(2) + "%"; } },
          xAxis: { type: "category", data: items.map(function (r) { return r.year; }) },
          yAxis: { type: "value", axisLabel: { formatter: function (v) { return (v * 100).toFixed(0) + "%"; } } },
          series: [{ type: "line", smooth: true, symbolSize: 7,
                     data: items.map(function (r) { return r.value; }),
                     areaStyle: { opacity: .12 }, lineStyle: { width: 2.5 } }]
        };
      });

      var factorOption = computed(function () {
        var d = factors.value;
        if (!d || !d.items) return null;
        var rows = d.items.filter(function (r) { return r.rate !== null && r.rate !== undefined; })
                          .sort(function (a, b) { return b.rate - a.rate; });
        return {
          color: [PALETTE[1]],
          grid: { left: 130, right: 50, top: 20, bottom: 40 },
          tooltip: { trigger: "axis", valueFormatter: function (v) { return (v * 100).toFixed(2) + "%"; } },
          xAxis: { type: "value", axisLabel: { formatter: function (v) { return (v * 100).toFixed(0) + "%"; } } },
          yAxis: { type: "category", data: rows.map(function (r) { return r.name; }) },
          series: [{ type: "bar", data: rows.map(function (r) { return r.rate; }),
                     itemStyle: { borderRadius: [0, 4, 4, 0] },
                     label: { show: true, position: "right",
                              formatter: function (p) { return (p.value * 100).toFixed(1) + "%"; } } }]
        };
      });

      var stratifyOption = computed(function () {
        var d = stratify.value;
        if (!d || !d.distribution) return null;
        var rows = d.distribution;
        return {
          color: PALETTE,
          grid: { left: 70, right: 30, top: 30, bottom: 40 },
          tooltip: { trigger: "axis" },
          xAxis: { type: "category", data: rows.map(function (r) { return r.label; }) },
          yAxis: { type: "value", name: "样本量" },
          series: [{ type: "bar", data: rows.map(function (r) { return r.samples; }),
                     itemStyle: { borderRadius: [4, 4, 0, 0] },
                     label: { show: true, position: "top",
                              formatter: function (p) { return yuan(p.value); } } }]
        };
      });

      return { loading: loading, error: error, kpis: kpis, loadAll: loadAll,
               prevalenceOption: prevalenceOption, trendOption: trendOption,
               factorOption: factorOption, stratifyOption: stratifyOption };
    }
  });

  var app = createApp(App);
  app.mount("#app");
  global.__VUE_APP__ = app;
})(window);
