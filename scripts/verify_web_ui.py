# -*- coding: utf-8 -*-
"""原生大屏改造验收：Selenium + 无头 Edge 驱动本地页面，对 A1–A7 做真实 DOM 断言、截图并留存日志。

用法：D:/期末作业/.venv/Scripts/python.exe scripts/verify_web_ui.py
前置：后端 127.0.0.1:8000 已启动（本脚本只读联调，不写任何后端/数据文件）。
产物：artifacts/screenshots/*.png、artifacts/verify_web_ui.log、artifacts/verify_web_ui_summary.txt
"""
import base64, json, re, sys, time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.edge.options import Options
from selenium.webdriver.edge.service import Service

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "index.html"
DRIVER = ROOT / "crawler" / "drivers" / "msedgedriver.exe"
SHOTS = ROOT / "artifacts" / "screenshots"
LOGP = ROOT / "artifacts" / "verify_web_ui.log"
SUMP = ROOT / "artifacts" / "verify_web_ui_summary.txt"
API = "http://127.0.0.1:8000"
URL = WEB.as_uri() + "?api=" + API


class Tee(object):
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            try:
                st.write(s)
            except Exception:
                pass

    def flush(self):
        for st in self.streams:
            try:
                st.flush()
            except Exception:
                pass


SHOTS.mkdir(parents=True, exist_ok=True)
_fh = open(str(LOGP), "w", encoding="utf-8")
sys.stdout = Tee(sys.__stdout__, _fh)
try:
    sys.stdout.streams[0].reconfigure(encoding="utf-8")
except Exception:
    pass

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(("PASS  " if ok else "FAIL  ") + name + (("  | " + str(detail)) if detail else ""))
    return ok


def js(driver, script, *args):
    return driver.execute_script(script, *args)


def wait_for(driver, script, timeout=25, poll=0.25):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        last = js(driver, script)
        if last:
            return last
        time.sleep(poll)
    return last


opts = Options()
opts.add_argument("--headless=new")
opts.add_argument("--disable-gpu")
opts.add_argument("--no-sandbox")
opts.add_argument("--window-size=1600,1200")
opts.add_argument("--force-device-scale-factor=1")
opts.set_capability("goog:loggingPrefs", {"browser": "ALL"})
service = Service(executable_path=str(DRIVER)) if DRIVER.exists() else Service()
driver = webdriver.Edge(service=service, options=opts)
driver.set_window_size(1600, 1200)


def clip_shot(name, box, scale=1):
    """按页面坐标裁剪截图（走 CDP clip，不需要 Pillow，也不会产生空图）。"""
    x, y, x2, y2 = box
    pad = 8
    x, y, x2, y2 = max(0.0, x - pad), max(0.0, y - pad), x2 + pad, y2 + pad
    if x2 - x < 6 or y2 - y < 6:
        print("  跳过退化区域截图:", name, "(%.0f,%.0f,%.0f,%.0f)" % (x, y, x2, y2))
        return None
    data = driver.execute_cdp_cmd("Page.captureScreenshot", {
        "format": "png", "captureBeyondViewport": True,
        "clip": {"x": x, "y": y, "width": x2 - x, "height": y2 - y, "scale": scale}})
    path = SHOTS / name
    path.write_bytes(base64.b64decode(data["data"]))
    print("截图:", path, "(%.0f,%.0f,%.0f,%.0f)" % (x, y, x2, y2))
    return path


def page_rect(driver, sel):
    return js(driver, "var e = document.querySelector(arguments[0]); if (!e) return null;"
                      "var b = e.getBoundingClientRect();"
                      "return { x: b.left, y: b.top + window.scrollY, w: b.width, h: b.height };", sel)


def full_shot(name):
    m = driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
    css = m.get("cssContentSize") or m["contentSize"]
    return clip_shot(name, (0, 0, int(css["width"]), int(css["height"])), scale=1)


try:
    driver.get(URL)
    loaded = wait_for(driver, "return !!(window.BRFSS && BRFSS.app && BRFSS.app.state.cache.health "
                              "&& document.querySelectorAll('#panel-kpi .kpi').length === 6 "
                              "&& document.querySelectorAll('.skeleton').length === 0);", timeout=40)
    print("== 页面加载完成:", loaded, "| URL:", URL)
    print("   后端:", js(driver, "return BRFSS.api.state.base;"), "| 已预取令牌:",
          js(driver, "return !!(BRFSS.api.auth.token);"))
    time.sleep(1.2)

    # ---------------- A1 网格：geo 与 drill 同排相邻 ----------------
    layout = js(driver, """
      var out = [];
      Array.prototype.slice.call(document.querySelectorAll('#main-grid > .panel')).forEach(function (p) {
        var r = p.getBoundingClientRect();
        var span = p.classList.contains('span-3') ? 3 : (p.classList.contains('span-2') ? 2 : 1);
        out.push({ id: p.id, span: span, top: Math.round(r.top), left: Math.round(r.left), right: Math.round(r.right) });
      });
      return out;
    """)
    rows, order = {}, []
    for it in layout:
        rows.setdefault(it["top"] // 4, []).append(it)
        order.append("%s(span%d)" % (it["id"].replace("panel-", ""), it["span"]))
    print("面板顺序:", " > ".join(order))
    for k in sorted(rows):
        grp = rows[k]
        print("  行 top≈%-5s %-34s 跨度合计=%d" % (grp[0]["top"], " + ".join(g["id"] for g in grp),
                                                sum(g["span"] for g in grp)))
    check("A1a 每行 span 合计 = 3", all(sum(g["span"] for g in grp) == 3 for grp in rows.values()),
          "共 %d 行" % len(rows))
    geo = [x for x in layout if x["id"] == "panel-geo"][0]
    drl = [x for x in layout if x["id"] == "panel-drill"][0]
    dtop, gap = abs(geo["top"] - drl["top"]), drl["left"] - geo["right"]
    print("  geo: top=%d left=%d right=%d | drill: top=%d left=%d | Δtop=%d gap=%d"
          % (geo["top"], geo["left"], geo["right"], drl["top"], drl["left"], dtop, gap))
    check("A1b geo/drill 同一水平位置 (Δtop<=2)", dtop <= 2, "Δtop=%d" % dtop)
    check("A1c drill 紧跟 geo 右侧 (left>=right-2)", gap >= -2, "gap=%dpx" % gap)
    ids = [x["id"] for x in layout]
    check("A1d drill 在 DOM 中紧跟 geo", ids[ids.index("panel-geo") + 1] == "panel-drill")
    check("A1e 面板相对顺序符合方案",
          ids == ["panel-kpi", "panel-prevalence", "panel-trend", "panel-geo", "panel-drill",
                  "panel-factors", "panel-stratify", "panel-age", "panel-metrics", "panel-predict"],
          " > ".join(i.replace("panel-", "") for i in ids))

    # ---------------- A2 panel-hint 数量 + 信息是否转入 title ----------------
    hints = js(driver, """
      var all = Array.prototype.slice.call(document.querySelectorAll('.panel-hint'));
      var visible = all.filter(function (h) { return h.offsetParent !== null && h.getBoundingClientRect().height > 0; });
      return { total: all.length, visible: visible.length, texts: visible.map(function (h) { return h.textContent.trim(); }) };
    """)
    print("panel-hint: 总数=%d 可见=%d" % (hints["total"], hints["visible"]))
    for t in hints["texts"]:
        print("   保留:", t)
    check("A2 可见 panel-hint <= 3", hints["visible"] <= 3, "可见=%d（改造前 10）" % hints["visible"])
    titles = js(driver, "return Array.prototype.slice.call(document.querySelectorAll('#main-grid > .panel'))"
                        ".map(function (p) { return [p.id, (p.getAttribute('title') || '').length]; });")
    print("  各面板 title 长度:", titles)
    check("A2b 被删说明文字已转入 panel title（无面板缺 title）",
          all(t[1] > 0 for t in titles), "缺 title: %s" % [t[0] for t in titles if t[1] == 0])

    # ---------------- A3 顶栏状态文案 ----------------
    status = js(driver, "var e = document.querySelector('#api-status .status-text');"
                        "return { text: e ? e.textContent.trim() : null,"
                        " title: document.getElementById('api-status').getAttribute('title') };")
    print("顶栏 status.textContent =", repr(status["text"]))
    print("顶栏 title =", repr((status["title"] or "").replace("\n", " / ")))
    check("A3 顶栏严格为「后端正常」", status["text"] == "后端正常", "实际=%r" % status["text"])
    check("A3b 版本/行数等细节仍在 title（信息未丢）", "version" in (status["title"] or ""))

    # ---------------- A4/A5 页脚 ----------------
    foot = js(driver, "return { text: document.querySelector('footer.footer').textContent.replace(/\\s+/g,' ').trim(),"
                      " trace: !!document.getElementById('footer-trace'), api: !!document.getElementById('footer-api') };")
    print("页脚文本 =", repr(foot["text"]))
    check("A4a 页脚已无 #footer-trace / #footer-api", (not foot["trace"]) and (not foot["api"]))
    check("A4b 页脚不含 traceId", "traceId" not in foot["text"])
    check("A4c 页脚不含 /api/v1", "/api/v1" not in foot["text"])
    check("A5 页脚数据来源仅保留 CDC BRFSS", foot["text"] == "数据来源：CDC BRFSS", repr(foot["text"]))

    # ---------------- A6⑤ toolbox ----------------
    tb = js(driver, """
      var ids = ['chart-prevalence','chart-trend','chart-geo','chart-factors','chart-stratify-level',
                 'chart-chronic-dist','chart-metrics','chart-age'];
      return ids.map(function (id) {
        var el = document.getElementById(id);
        if (!el) return [id, '容器缺失'];
        var c = window.echarts.getInstanceByDom(el);
        if (!c) return [id, '未初始化'];
        var t = (c.getOption().toolbox || [])[0] || {};
        return [id, Object.keys(t.feature || {})];
      });
    """)
    for r in tb:
        print("  toolbox", r[0], "->", r[1])
    check("A6⑤ 8 张图均提供 toolbox.saveAsImage",
          all(isinstance(r[1], list) and "saveAsImage" in r[1] for r in tb))

    # ---------------- A6① 跨图 hover 联动 ----------------
    px = js(driver, """
      var el = document.getElementById('chart-trend');
      var c = window.echarts.getInstanceByDom(el);
      var opt = c.getOption();
      var v = opt.series[0].data[0];
      var p = c.convertToPixel({ seriesIndex: 0 }, [0, v]);
      var r = el.getBoundingClientRect();
      return { x: p[0], y: p[1], w: r.width, h: r.height, value: v, name: opt.xAxis[0].data[0] };
    """)
    print("趋势图首个数据点: %s=%s 像素=(%.0f,%.0f)" % (px["name"], px["value"], px["x"], px["y"]))
    ActionChains(driver).move_to_element(driver.find_element(By.ID, "chart-trend")).move_by_offset(
        px["x"] - px["w"] / 2.0, px["y"] - px["h"] / 2.0).perform()
    time.sleep(0.8)
    hv = js(driver, """
      return { link: document.body.getAttribute('data-hover-link'),
               topics: document.body.getAttribute('data-hover-topics'),
               geoLinked: document.getElementById('panel-geo').classList.contains('is-hover-linked'),
               audit: BRFSS.app.hoverAudit(),
               linkedPanels: Array.prototype.slice.call(document.querySelectorAll('.panel.is-hover-linked'))
                               .map(function (p) { return p.id; }) };
    """)
    print("hover(趋势图) 结果:", hv)
    check("A6① hover 触发跨图联动（body[data-hover-link] 有值）", bool(hv["link"]), "link=%r" % hv["link"])
    check("A6① 相关图 geo 面板被同步高亮", hv["geoLinked"], "已高亮面板=%s" % hv["linkedPanels"])
    check("A6① 真实派发 echarts dispatchAction highlight", (hv["audit"] or 0) > 0, "hoverAudit=%s" % hv["audit"])
    hover_shot = full_shot("web_hover_linked_full.png")
    ActionChains(driver).move_to_element(driver.find_element(By.CSS_SELECTOR, ".brand")).perform()
    time.sleep(0.8)
    after = js(driver, "return { link: document.body.getAttribute('data-hover-link'),"
                       " linked: document.querySelectorAll('.panel.is-hover-linked').length };")
    check("A6① 离开后取消高亮（downplay + 清除标记）", after["link"] is None and after["linked"] == 0, json.dumps(after))

    # ---------------- A6④ KPI / 图表容器 hover 反馈 ----------------
    flat = js(driver, "var cs = getComputedStyle(document.querySelector('#panel-kpi .kpi'));"
                      "return { transform: cs.transform, border: cs.borderTopColor };")
    ActionChains(driver).move_to_element(driver.find_element(By.CSS_SELECTOR, "#panel-kpi .kpi")).perform()
    time.sleep(0.6)
    hov = js(driver, "var cs = getComputedStyle(document.querySelector('#panel-kpi .kpi'));"
                     "return { transform: cs.transform, border: cs.borderTopColor };")
    print("KPI 常态:", flat, " 悬停:", hov)
    check("A6④ KPI 卡片有可见 hover 反馈", flat != hov, "%s -> %s" % (flat, hov))
    clip_shot("web_kpi_hover.png", (page_rect(driver, "#panel-kpi")["x"], page_rect(driver, "#panel-kpi")["y"],
                                    page_rect(driver, "#panel-kpi")["x"] + page_rect(driver, "#panel-kpi")["w"],
                                    page_rect(driver, "#panel-kpi")["y"] + page_rect(driver, "#panel-kpi")["h"]))
    ActionChains(driver).move_to_element(driver.find_element(By.CSS_SELECTOR, ".brand")).perform()
    time.sleep(0.4)
    host_flat = js(driver, "var h = document.querySelector('#panel-prevalence .chart-host');"
                           "return h ? getComputedStyle(h).boxShadow : null;")
    ActionChains(driver).move_to_element(driver.find_element(By.CSS_SELECTOR, "#panel-prevalence .chart-host")).perform()
    time.sleep(0.5)
    host_hov = js(driver, "var h = document.querySelector('#panel-prevalence .chart-host');"
                          "return h ? getComputedStyle(h).boxShadow : null;")
    print("chart-host box-shadow 常态:", host_flat, " 悬停:", host_hov)
    check("A6④ 图表容器有可见 hover 反馈", host_flat != host_hov, "%s -> %s" % (host_flat, host_hov))

    # ---------------- A6② chip 显示与一键清除 ----------------
    js(driver, "BRFSS.app.drillInto('06'); BRFSS.app.applyMetricLink('diabetes_rate', '联调脚本');")
    wait_for(driver, "return document.querySelectorAll('#chip-bar .chip').length >= 2;", timeout=25)
    chips = js(driver, "var b = document.getElementById('chip-bar');"
                       "return { hidden: b.hidden, texts: Array.prototype.slice.call(b.querySelectorAll('.chip'))"
                       ".map(function (c) { return c.getAttribute('data-chip') + ':' + c.textContent.trim(); }) };")
    print("chip 条:", chips)
    check("A6② 联动/下钻显示为 chip", (not chips["hidden"]) and len(chips["texts"]) >= 2, str(chips["texts"]))
    cb = page_rect(driver, "#chip-bar")
    if cb:
        clip_shot("web_chipbar.png", (cb["x"], cb["y"], cb["x"] + cb["w"], cb["y"] + cb["h"]))
    driver.find_element(By.CSS_SELECTOR, '#chip-bar [data-chip-clear="drill"]').click()
    wait_for(driver, "return !BRFSS.app.state.drill && document.querySelectorAll('#chip-bar .chip[data-chip=drill]').length === 0;", timeout=20)
    st = js(driver, "return { drill: BRFSS.app.state.drill, stateFilter: document.getElementById('filter-state').value,"
                    " drillBox: document.getElementById('panel-drill').querySelector('.state-box') ? '未选择州占位' : '无',"
                    " chips: document.querySelectorAll('#chip-bar .chip').length };")
    print("清除下钻 chip 后:", st)
    check("A6② 清除下钻 chip → state.drill=null 且筛选回到全部州（恢复全量）",
          st["drill"] is None and st["stateFilter"] == "" and st["chips"] == 1 and st["drillBox"] == "未选择州占位", json.dumps(st))
    driver.find_element(By.CSS_SELECTOR, '#chip-bar [data-chip-clear="metric"]').click()
    wait_for(driver, "return BRFSS.app.state.trendMetric === 'multimorbidity_rate';", timeout=20)
    st2 = js(driver, "return { metric: BRFSS.app.state.trendMetric,"
                     " trendSel: document.getElementById('trend-metric').value,"
                     " geoSel: document.getElementById('geo-metric').value,"
                     " chips: document.querySelectorAll('#chip-bar .chip').length,"
                     " barHidden: document.getElementById('chip-bar').hidden,"
                     " geoTitle: document.getElementById('panel-geo').classList.contains('is-hover-linked') };")
    print("清除指标 chip 后:", st2)
    check("A6② 清除指标 chip → 恢复默认指标且 chip 条收起",
          st2["metric"] == "multimorbidity_rate" and st2["trendSel"] == "multimorbidity_rate"
          and st2["geoSel"] == "multimorbidity_rate" and st2["chips"] == 0 and st2["barHidden"], json.dumps(st2))

    # ---------------- A6③ Esc ----------------
    js(driver, "BRFSS.app.drillInto('48'); BRFSS.app.applyMetricLink('obese_rate', '联调脚本');")
    wait_for(driver, "return document.querySelectorAll('#chip-bar .chip').length >= 2;", timeout=25)
    driver.find_element(By.TAG_NAME, "body").click()
    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    esc_ok = wait_for(driver, "return BRFSS.app.state.drill === null && BRFSS.app.state.trendMetric === 'multimorbidity_rate';", timeout=8)
    esc_mode = "真实按键 send_keys(ESCAPE)"
    if not esc_ok:
        js(driver, "document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));")
        esc_ok = wait_for(driver, "return BRFSS.app.state.drill === null && BRFSS.app.state.trendMetric === 'multimorbidity_rate';", timeout=8)
        esc_mode = "KeyboardEvent 兜底"
    both = js(driver, "return { drill: BRFSS.app.state.drill, metric: BRFSS.app.state.trendMetric,"
                      " chips: document.querySelectorAll('#chip-bar .chip').length };")
    print("Esc 清除后:", both, "| 触发方式:", esc_mode)
    check("A6③ Esc 清除联动与下钻", bool(esc_ok), json.dumps(both) + " 触发方式=" + esc_mode)

    # 正常路径的 console 必须干净（在故障注入之前统计；get_log 会 drain）
    pre_logs = driver.get_log("browser")
    pre_severe = [l for l in pre_logs if l.get("level") == "SEVERE"]
    print("\n[A6 阶段结束] console 条目=%d SEVERE=%d" % (len(pre_logs), len(pre_severe)))
    for l in pre_severe[:5]:
        print("   SEVERE:", l.get("message", "")[:300])
    check("console SEVERE = 0（正常路径：加载/hover/chip/Esc）", len(pre_severe) == 0, "SEVERE=%d" % len(pre_severe))

    # ---------------- A7 预测表单加固 ----------------
    print("\n== A7 预测表单加固 ==")
    js(driver, """
      window.__predictCalls = [];
      window.__timerLog = [];
      window.__realFetch = window.fetch;
      window.__realTimeout = window.setTimeout;
      window.__canned = { probability: 0.4159, prediction: 1, riskLevel: '中风险',
        thresholds: { low: 0.1, high: 0.3 }, model: { fileName: 'model.joblib' },
        missingFeatures: ['year'], features: { bmi: 29.5, smoker3: 4 },
        latencyMs: 137, traceId: 'deadbeefdeadbeefdeadbeefdeadbeef' };
      window.setTimeout = function (fn, ms) { window.__timerLog.push(ms); return window.__realTimeout.apply(window, arguments); };
      window.fetch = function (url, init) {
        if (String(url).indexOf('/predict') >= 0) {
          window.__predictCalls.push(String(url));
          return new Promise(function (res) {
            window.__realTimeout(function () {
              res(new Response(JSON.stringify({ code: 0, message: 'ok', data: window.__canned,
                traceId: 'deadbeefdeadbeefdeadbeefdeadbeef', timestamp: Date.now() }),
                { status: 200, headers: { 'Content-Type': 'application/json',
                  'X-Trace-Id': 'deadbeefdeadbeefdeadbeefdeadbeef', 'X-Response-Time': '9.9' } }));
            }, 700);
          });
        }
        return window.__realFetch.apply(window, arguments);
      };
    """)
    js(driver, "var f = document.querySelector('#predict-form');"
               "f.dispatchEvent(new Event('submit', {cancelable:true, bubbles:true}));"
               "f.dispatchEvent(new Event('submit', {cancelable:true, bubbles:true}));")
    wait_for(driver, "return !document.getElementById('predict-submit').disabled", timeout=15)
    time.sleep(0.4)
    r1 = js(driver, """
      var msg = document.getElementById('predict-msg').textContent.trim();
      var tag = document.querySelector('.risk-tag');
      return { calls: window.__predictCalls.length, msg: msg,
               longTimers: window.__timerLog.filter(function (v) { return v >= 1000; }),
               has32hex: /[0-9a-f]{32}/i.test(msg), hasTrace: msg.indexOf('traceId') >= 0,
               riskTag: tag ? tag.textContent : null,
               riskTopics: tag ? tag.getAttribute('data-link-topics') : null,
               lines: document.querySelectorAll('#predict-lines .result-line').length,
               advice: document.querySelectorAll('#predict-advice li').length };
    """)
    print("连发两次 submit:", json.dumps(r1, ensure_ascii=False))
    check("A7① in-flight 守卫：连点两次只发 1 次请求", r1["calls"] == 1, "实际请求数=%d" % r1["calls"])
    check("A7④ /predict 显式 timeoutMs=20000", 20000 in r1["longTimers"], "长定时器=%s" % r1["longTimers"])
    check("A4 预测成功提示为「预测完成 · 延迟 N ms」", bool(re.match(r"^预测完成 · 延迟 \d+ ms$", r1["msg"])), "实际=%r" % r1["msg"])
    check("A4e 提示不含 traceId / 32 位十六进制串", (not r1["hasTrace"]) and (not r1["has32hex"]))
    check("A7③ 结果正常渲染（风险标签 + 明细行 + 建议）",
          r1["riskTag"] is not None and r1["lines"] >= 6 and r1["advice"] >= 1,
          "tag=%s topics=%s lines=%d advice=%d" % (r1["riskTag"], r1["riskTopics"], r1["lines"], r1["advice"]))
    clip_shot("web_predict_result.png", (lambda r: (r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"]))(page_rect(driver, "#panel-predict")))

    # 渲染异常不得伪装成「预测失败」
    js(driver, "window.__gauge = BRFSS.charts.gaugeOption; BRFSS.charts.gaugeOption = function () { throw new Error('模拟渲染异常'); };"
               "document.querySelector('#predict-form').dispatchEvent(new Event('submit', {cancelable:true, bubbles:true}));")
    wait_for(driver, "return !document.getElementById('predict-submit').disabled", timeout=15)
    time.sleep(0.4)
    r2 = js(driver, "return { msg: document.getElementById('predict-msg').textContent.trim(),"
                    " banner: !document.getElementById('js-error-banner').hidden,"
                    " errors: document.body.getAttribute('data-js-errors') };")
    print("注入渲染异常时:", json.dumps(r2, ensure_ascii=False))
    check("A7③ 渲染异常不伪装成「预测失败」",
          r2["msg"].startswith("预测已成功返回") and "预测失败" not in r2["msg"], r2["msg"][:70])
    check("A7③ 渲染异常走全局错误条（显性化）", r2["banner"], "data-js-errors=%s" % r2["errors"])
    js(driver, "BRFSS.charts.gaugeOption = window.__gauge; BRFSS.app.state.errors = 0;"
               "document.getElementById('js-error-banner').hidden = true;"
               "document.body.removeAttribute('data-js-errors');")

    # 越界值：就地提示且不发请求
    js(driver, "window.__predictCalls.length = 0; var b = document.getElementById('pf-bmi'); b.value = '99';"
               "b.dispatchEvent(new Event('input', {bubbles:true}));"
               "document.querySelector('#predict-form').dispatchEvent(new Event('submit', {cancelable:true, bubbles:true}));")
    time.sleep(0.6)
    r3 = js(driver, "var b = document.getElementById('pf-bmi');"
                    "return { calls: window.__predictCalls.length, msg: document.getElementById('predict-msg').textContent.trim(),"
                    " invalid: b.classList.contains('is-invalid'), fieldErr: document.getElementById('pfe-bmi').textContent.trim(),"
                    " value: b.value };")
    print("越界 BMI=99:", json.dumps(r3, ensure_ascii=False))
    check("A7② 越界就地提示字段名与区间且不发请求",
          r3["calls"] == 0 and "BMI" in r3["msg"] and "10–70" in r3["msg"] and r3["invalid"] and r3["fieldErr"] != "",
          "请求数=%d msg=%r 字段提示=%r" % (r3["calls"], r3["msg"][:70], r3["fieldErr"]))
    clip_shot("web_predict_invalid.png", (lambda r: (r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"]))(page_rect(driver, "#panel-predict")))

    # 网络失败：retries=1 → 共 2 次尝试，且表单数值保留
    js(driver, """
      window.__predictCalls.length = 0;
      document.getElementById('pf-bmi').value = '29.9';
      window.fetch = function (url, init) {
        if (String(url).indexOf('/predict') >= 0) {
          window.__predictCalls.push(String(url));
          return Promise.reject(new TypeError('Failed to fetch'));
        }
        return window.__realFetch.apply(window, arguments);
      };
    """)
    t0 = time.time()
    js(driver, "document.querySelector('#predict-form').dispatchEvent(new Event('submit', {cancelable:true, bubbles:true}));")
    wait_for(driver, "return !document.getElementById('predict-submit').disabled", timeout=20)
    time.sleep(0.3)
    r4 = js(driver, "return { attempts: window.__predictCalls.length,"
                    " msg: document.getElementById('predict-msg').textContent.trim(),"
                    " bmi: document.getElementById('pf-bmi').value,"
                    " age: document.getElementById('pf-age_grp').value };")
    print("网络失败路径(%.1fs):" % (time.time() - t0), json.dumps(r4, ensure_ascii=False))
    check("A7④ retries=1：网络失败只尝试 2 次（旧配置为 4 次）", r4["attempts"] == 2, "尝试次数=%d" % r4["attempts"])
    check("A7⑤ 失败后保留已填数值", r4["bmi"] == "29.9" and r4["age"] == "8", "bmi=%s age_grp=%s" % (r4["bmi"], r4["age"]))
    check("A7 失败提示仍为「预测失败：…」", r4["msg"].startswith("预测失败："), r4["msg"][:60])

    # ---------------- 真实后端端到端 ----------------
    js(driver, "window.fetch = window.__realFetch; window.setTimeout = window.__realTimeout;"
               "document.getElementById('pf-bmi').value = '29.9';"
               "document.getElementById('pf-smoker3').value = '1';"
               "document.querySelector('#predict-form').dispatchEvent(new Event('submit', {cancelable:true, bubbles:true}));")
    t1 = time.time()
    wait_for(driver, "var m = document.getElementById('predict-msg').textContent.trim();"
                     "return m.indexOf('预测完成') === 0 || m.indexOf('预测失败') === 0;", timeout=40)
    elapsed = time.time() - t1
    real = js(driver, "return { msg: document.getElementById('predict-msg').textContent.trim(),"
                      " firstLine: (document.querySelector('#predict-lines .result-line b') || {}).textContent || null,"
                      " advice: document.querySelectorAll('#predict-advice li').length,"
                      " tokenPrefetched: !!(BRFSS.api.auth.token),"
                      " authUser: BRFSS.api.auth.username };")
    print("真实后端预测(%.2fs):" % elapsed, json.dumps(real, ensure_ascii=False))
    check("端到端：真实 /predict 成功且提示格式达标",
          bool(re.match(r"^预测完成 · 延迟 \d+ ms$", real["msg"])) and real["advice"] >= 1,
          "%s（含建议 %d 条，接口往返 %.2fs）" % (real["msg"], real["advice"], elapsed))
    check("A7 页面加载即预取令牌（首查不必等登录）", real["tokenPrefetched"], "auth=%s" % real["authUser"])

    # ---------------- 控制台与最终截图 ----------------
    inj_logs = driver.get_log("browser")
    inj_severe = [l for l in inj_logs if l.get("level") == "SEVERE"]
    print("\n[故障注入阶段] console 条目=%d SEVERE=%d（注入的渲染异常应恰好 1 条）" % (len(inj_logs), len(inj_severe)))
    for l in inj_severe[:5]:
        print("   SEVERE:", l.get("message", "")[:300])
    js_err = js(driver, "return { n: document.body.getAttribute('data-js-errors'),"
                        " banner: !document.getElementById('js-error-banner').hidden };")
    print("页面自报异常:", js_err)
    check("注入渲染异常只产生 1 条由 reportError 主动上报的 SEVERE",
          len(inj_severe) == 1 and "预测结果渲染异常" in inj_severe[0].get("message", ""),
          "SEVERE=%d" % len(inj_severe))

    driver.get(URL)
    wait_for(driver, "return !!(window.BRFSS && BRFSS.app && BRFSS.app.state.cache.health "
                     "&& document.querySelectorAll('#panel-kpi .kpi').length === 6 "
                     "&& document.querySelectorAll('.skeleton').length === 0);", timeout=40)
    time.sleep(2.0)
    full_shot("web_full.png")
    g, d = page_rect(driver, "#panel-geo"), page_rect(driver, "#panel-drill")
    clip_shot("web_geo_drill_row.png", (min(g["x"], d["x"]), g["y"], max(g["x"] + g["w"], d["x"] + d["w"]),
                                        max(g["y"] + g["h"], d["y"] + d["h"])))
    t, f = page_rect(driver, ".topbar"), page_rect(driver, "footer.footer")
    clip_shot("web_topbar.png", (t["x"], t["y"], t["x"] + t["w"], t["y"] + t["h"]))
    clip_shot("web_footer.png", (f["x"], f["y"], f["x"] + f["w"], f["y"] + f["h"]))
    fin_logs = driver.get_log("browser")
    fin_severe = [l for l in fin_logs if l.get("level") == "SEVERE"]
    print("最终刷新后 console 条目=%d SEVERE=%d" % (len(fin_logs), len(fin_severe)))
    for l in fin_severe[:5]:
        print("   SEVERE:", l.get("message", "")[:300])
    check("最终刷新后 console SEVERE = 0", len(fin_severe) == 0, "SEVERE=%d" % len(fin_severe))
finally:
    driver.quit()

bad = [r for r in RESULTS if not r[1]]
print("\n==== 汇总：%d / %d 通过 ====" % (len(RESULTS) - len(bad), len(RESULTS)))
for name, _, detail in bad:
    print("  未通过:", name, "|", detail)
with open(str(SUMP), "w", encoding="utf-8") as fh:
    fh.write("验收汇总：%d / %d 通过\n" % (len(RESULTS) - len(bad), len(RESULTS)))
    for name, ok, detail in RESULTS:
        fh.write(("PASS  " if ok else "FAIL  ") + name + " | " + str(detail) + "\n")
print("逐项结果已存:", SUMP, "| 完整日志:", LOGP)
sys.exit(1 if bad else 0)
