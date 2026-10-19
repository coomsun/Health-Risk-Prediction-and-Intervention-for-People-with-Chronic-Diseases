/* web/vue/js/api.js — Vue 版数据访问层（统一信封解析 + 超时重试） */
(function (global) {
  "use strict";
  var BASE = (location.hostname === "127.0.0.1" || location.hostname === "localhost")
    ? "http://127.0.0.1:8000"
    : "http://127.0.0.1:8000";

  function withTimeout(promise, ms) {
    return new Promise(function (resolve, reject) {
      var t = setTimeout(function () { reject(new Error("请求超时（" + ms + "ms）")); }, ms);
      promise.then(function (v) { clearTimeout(t); resolve(v); },
                   function (e) { clearTimeout(t); reject(e); });
    });
  }

  function get(path, retries) {
    retries = retries === undefined ? 2 : retries;
    var url = BASE + path;
    var attempt = function (n) {
      return withTimeout(fetch(url).then(function (r) {
        return r.json().then(function (body) {
          if (body.code !== 0) throw new Error(body.message || ("接口返回 code=" + body.code));
          return body.data;
        });
      }), 15000).catch(function (e) {
        if (n > 0) {
          return new Promise(function (res) { setTimeout(res, 400 * (3 - n)); })
            .then(function () { return attempt(n - 1); });
        }
        throw e;
      });
    };
    return attempt(retries);
  }

  function post(path, payload, token) {
    var headers = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = "Bearer " + token;
    return withTimeout(fetch(BASE + path, {
      method: "POST", headers: headers, body: JSON.stringify(payload)
    }).then(function (r) {
      return r.json().then(function (body) {
        if (body.code !== 0) throw new Error(body.message || ("接口返回 code=" + body.code));
        return body.data;
      });
    }), 20000);
  }

  global.API = { base: BASE, get: get, post: post };
})(window);
