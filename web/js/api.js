/* =============================================================
   api.js —— REST 客户端
   · 统一信封解包 {code, message, data, traceId, timestamp}
   · 超时（AbortController）+ 3 次指数退避重试（仅对超时/网络/5xx 生效）
   · 业务错误（如 1001 模型未就绪、400 参数错误）立即抛出，不做无意义重试
   ============================================================= */
(function (NS) {
  'use strict';

  var DEFAULT_BASE = 'http://127.0.0.1:8000';
  var TIME_OUT_MS = 12000;   /* 真库 213 万行时 /risk/stratify 约 6s，留出余量 */
  var MAX_RETRIES = 3;                  /* 首次尝试 + 3 次重试 = 最多 4 次 */
  var BACKOFF_BASE_MS = 300;            /* 300 → 600 → 1200 */

  function resolveBase() {
    var fromQuery = null;
    try { fromQuery = new URLSearchParams(window.location.search).get('api'); } catch (e) { fromQuery = null; }
    var fromStore = null;
    try { fromStore = window.localStorage.getItem('brfss.apiBase'); } catch (e) { fromStore = null; }
    var base = fromQuery || fromStore || DEFAULT_BASE;
    if (fromQuery) {
      try { window.localStorage.setItem('brfss.apiBase', fromQuery); } catch (e) { /* 隐私模式忽略 */ }
    }
    return String(base).replace(/\/+$/, '');
  }

  var state = {
    base: resolveBase(),
    lastTraceId: null,
    lastResponseTime: null,
    lastPath: null
  };

  function ApiError(info) {
    var err = new Error(info.message || '请求失败');
    err.name = 'ApiError';
    err.code = info.code;
    err.traceId = info.traceId || null;
    err.httpStatus = info.httpStatus || 0;
    err.url = info.url || '';
    err.retriable = !!info.retriable;
    return err;
  }

  function buildUrl(path, params) {
    var url = state.base + path;
    if (params) {
      var qs = Object.keys(params)
        .filter(function (k) { return params[k] !== undefined && params[k] !== null && params[k] !== ''; })
        .map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]); })
        .join('&');
      if (qs) url += (url.indexOf('?') >= 0 ? '&' : '?') + qs;
    }
    return url;
  }

  function sleep(ms) {
    return new Promise(function (resolve) { window.setTimeout(resolve, ms); });
  }

  function fetchOnce(url, method, body, timeoutMs) {
    var controller = new AbortController();
    var timer = window.setTimeout(function () { controller.abort(); }, timeoutMs);
    var init = {
      method: method,
      signal: controller.signal,
      headers: { 'Accept': 'application/json' },
      cache: 'no-store'
    };
    if (body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    return window.fetch(url, init).then(function (resp) {
      var rt = resp.headers.get('X-Response-Time');
      var tid = resp.headers.get('X-Trace-Id');
      if (rt) state.lastResponseTime = rt;
      if (tid) state.lastTraceId = tid;
      return resp.text().then(function (text) {
        var json = null;
        try { json = text ? JSON.parse(text) : null; } catch (e) { json = null; }
        return { resp: resp, json: json, text: text };
      });
    }).then(function (r) {
      window.clearTimeout(timer);
      return r;
    }, function (err) {
      window.clearTimeout(timer);
      throw err;
    });
  }

  /**
   * 发起请求并解包信封。
   * @returns {Promise<any>} 信封中的 data 字段
   */
  function request(path, options) {
    options = options || {};
    var method = options.method || 'GET';
    var timeoutMs = options.timeoutMs || TIME_OUT_MS;
    var maxRetries = options.retries == null ? MAX_RETRIES : options.retries;
    var url = buildUrl(path, options.params);
    state.lastPath = path;

    function attempt(round) {
      return fetchOnce(url, method, options.body, timeoutMs).then(function (r) {
        var json = r.json;
        if (!json || typeof json.code === 'undefined') {
          /* 非信封响应：多半是 404 静态页或代理错误 */
          throw ApiError({
            code: r.resp.status || -1,
            message: '响应不是统一信封（HTTP ' + r.resp.status + '）' + (r.text ? '：' + r.text.slice(0, 120) : ''),
            httpStatus: r.resp.status, url: url, retriable: r.resp.status >= 500
          });
        }
        if (json.traceId) state.lastTraceId = json.traceId;
        if (json.code === 0) return json.data;
        throw ApiError({
          code: json.code,
          message: json.message || '业务错误',
          traceId: r.resp.headers.get('X-Trace-Id') || json.traceId,
          httpStatus: r.resp.status,
          url: url,
          retriable: r.resp.status >= 500 || [500, 1003].indexOf(json.code) >= 0
        });
      }).catch(function (err) {
        if (err && err.name === 'ApiError') throw err;
        var isAbort = err && err.name === 'AbortError';
        var wrapped = ApiError({
          code: isAbort ? -2 : -1,
          message: isAbort
            ? ('请求超时（>' + timeoutMs + 'ms）：' + (options.label || path))
            : ('网络请求失败：' + ((err && err.message) || '未知错误') + '（后端是否已启动？）'),
          httpStatus: 0, url: url, retriable: true
        });
        wrapped.name = 'ApiError';
        wrapped.causeName = isAbort ? 'Timeout' : 'Network';
        throw wrapped;
      }).catch(function (err) {
        var canRetry = err && err.retriable && round < maxRetries;
        if (!canRetry) {
          err.attempts = round + 1;
          throw err;
        }
        var delay = BACKOFF_BASE_MS * Math.pow(2, round);
        NS.log && NS.log('[api] 第 ' + (round + 1) + ' 次失败，' + delay + 'ms 后重试：' + path + ' — ' + err.message);
        return sleep(delay).then(function () { return attempt(round + 1); });
      });
    }

    return attempt(0).catch(function (err) {
      if (err && err.name === 'ApiError') throw err;
      throw ApiError({ code: -1, message: String(err && err.message || err), url: url, retriable: false });
    });
  }

  NS.api = {
    state: state,
    request: request,
    get: function (path, params, options) {
      return request(path, Object.assign({ params: params }, options || {}));
    },
    post: function (path, body, options) {
      return request(path, Object.assign({ method: 'POST', body: body }, options || {}));
    },
    health: function (options) {
      return request('/api/v1/health', Object.assign({ retries: 1, timeoutMs: 4000 }, options || {}));
    }
  };
})(window.BRFSS = window.BRFSS || {});
