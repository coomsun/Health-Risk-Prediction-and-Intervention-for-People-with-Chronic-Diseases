/* web/vue/js/components.js — Vue 3 组件定义（无构建步骤，直接用全局构建） */
(function (global) {
  "use strict";
  var vue = global.Vue;
  var defineComponent = vue.defineComponent;
  var h = vue.h;
  var ref = vue.ref;
  var onMounted = vue.onMounted;
  var watch = vue.watch;
  var onBeforeUnmount = vue.onBeforeUnmount;

  /* ---------- 通用：ECharts 容器组件 ---------- */
  var EChart = defineComponent({
    name: "EChart",
    props: { option: { type: Object, default: null }, height: { type: String, default: "320px" } },
    setup: function (props) {
      var el = ref(null);
      var chart = null;
      function render() {
        if (!el.value || !window.echarts) return;
        if (!chart) chart = window.echarts.init(el.value);
        if (props.option) chart.setOption(props.option, true);
      }
      onMounted(function () {
        render();
        window.addEventListener("resize", resize);
      });
      onBeforeUnmount(function () {
        window.removeEventListener("resize", resize);
        if (chart) { chart.dispose(); chart = null; }
      });
      function resize() { if (chart) chart.resize(); }
      watch(function () { return props.option; }, render, { deep: true });
      return function () { return h("div", { ref: el, style: { height: props.height, width: "100%" } }); };
    }
  });

  /* ---------- 通用：带标题/加载/错误的图表面板 ---------- */
  var ChartCard = defineComponent({
    name: "ChartCard",
    components: { EChart: EChart },
    props: {
      title: String,
      option: { type: Object, default: null },
      loading: Boolean,
      error: { type: String, default: null }
    },
    template:
      '<div class="comp-card">' +
      '  <h3 style="margin:.1rem 0 .7rem;font-size:.98rem;color:#1F3B57">{{ title }}</h3>' +
      '  <p v-if="error" class="err">{{ error }}</p>' +
      '  <p v-else-if="loading" class="loading">加载中…</p>' +
      '  <e-chart v-else :option="option"></e-chart>' +
      '</div>'
  });

  /* ---------- KPI 卡片 ---------- */
  var KpiCards = defineComponent({
    name: "KpiCards",
    props: { items: { type: Array, default: function () { return []; } } },
    template:
      '<div class="comp-card">' +
      '  <div class="kpi-grid">' +
      '    <div class="kpi-item" v-for="it in items" :key="it.label">' +
      '      <div class="v">{{ it.value }}</div>' +
      '      <div class="l">{{ it.label }}</div>' +
      '    </div>' +
      '  </div>' +
      '</div>'
  });

  /* ---------- 在线预测表单 ---------- */
  var PredictForm = defineComponent({
    name: "PredictForm",
    setup: function () {
      var form = ref({ age: 68, sex: 1, bmi: 31.5, smoker3: 1, phys_activity: 0,
                       heavy_drink: 1, medcost: 1, checkup: 2, persdoc: 3 });
      var result = ref(null);
      var error = ref(null);
      var busy = ref(false);
      var token = ref("");

      function getToken() {
        // 演示用：先登录拿令牌，再调受保护接口
        return global.API.post("/api/v1/auth/login", { username: "demo", password: "demo12345" })
          .then(function (d) { token.value = d.accessToken; return d.accessToken; })
          .catch(function () { return ""; });
      }

      function submit() {
        busy.value = true; error.value = null; result.value = null;
        var payload = {};
        Object.keys(form.value).forEach(function (k) {
          var v = form.value[k];
          if (v !== "" && v !== null && v !== undefined) payload[k] = Number(v);
        });
        getToken().then(function (tk) {
          return global.API.post("/api/v1/predict", payload, tk);
        }).then(function (d) {
          result.value = d;
        }).catch(function (e) {
          error.value = e.message || String(e);
        }).finally(function () { busy.value = false; });
      }

      return { form: form, result: result, error: error, busy: busy, submit: submit };
    },
    template:
      '<div>' +
      '  <div class="form-row">' +
      '    <div v-for="(label, key) in {age:\'年龄\',sex:\'性别(1男2女)\',bmi:\'BMI\',smoker3:\'吸烟(1-4)\',' +
      '         phys_activity:\'运动(1有0无)\',heavy_drink:\'酗酒(1是0否)\',medcost:\'费用障碍(1是0否)\',' +
      '         checkup:\'体检(1-8)\',persdoc:\'固定医生(1-3)\'}" :key="key">' +
      '      <label>{{ label }}</label>' +
      '      <input v-model="form[key]" type="number" step="0.1" style="width:110px" />' +
      '    </div>' +
      '    <button @click="submit" :disabled="busy">{{ busy ? "预测中…" : "提交预测" }}</button>' +
      '  </div>' +
      '  <p v-if="error" class="err" style="margin-top:.7rem">{{ error }}</p>' +
      '  <div v-if="result" style="margin-top:.9rem">' +
      '    <div class="kpi-grid">' +
      '      <div class="kpi-item"><div class="v">{{ (result.probability*100).toFixed(2) }}%</div>' +
      '        <div class="l">共病概率</div></div>' +
      '      <div class="kpi-item"><div class="v">{{ result.riskLevel }}</div><div class="l">风险等级</div></div>' +
      '      <div class="kpi-item"><div class="v">{{ result.prediction }}</div><div class="l">预测标签</div></div>' +
      '    </div>' +
      '    <p class="loading" style="margin-top:.6rem">模型：{{ result.model && result.model.fileName }}</p>' +
      '  </div>' +
      '</div>'
  });

  global.VueComponents = {
    EChart: EChart, ChartCard: ChartCard, KpiCards: KpiCards, PredictForm: PredictForm
  };
})(window);
