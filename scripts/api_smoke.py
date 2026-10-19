
import json, urllib.request, time
B = "http://127.0.0.1:8000"
def g(p):
    t = time.time()
    with urllib.request.urlopen(B + p, timeout=30) as r:
        return r.status, json.loads(r.read().decode()), round((time.time()-t)*1000)
paths = ["/health", "/overview", "/chronic/prevalence?year=2023", "/trend",
         "/risk/factors?year=2023", "/risk/stratify", "/geo/states", "/model/metrics"]
allok = True
for p in paths:
    try:
        s, d, ms = g("/api/v1" + p)
        good = (s == 200 and d.get("code") == 0)
        allok &= good
        extra = ""
        if p == "/health": extra = " factRows=%s" % d["data"].get("factRows")
        if p == "/risk/factors?year=2023": extra = " source=%s items=%d" % (d["data"].get("source"), len(d["data"]["items"]))
        if p == "/model/metrics": extra = " metrics=%d" % len(d["data"].get("items", []))
        print("%-34s %s code=%s %4sms%s" % (p, s, d.get("code"), ms, extra))
    except Exception as e:
        allok = False
        print("%-34s FAIL %s" % (p, e))
body = {"age":68,"sex":1,"bmi":31.5,"smoker3":1,"phys_activity":0,"heavy_drink":1,"medcost":1,
        "checkup":2,"persdoc":3,"educa":2,"income_grp":2,"year":2023,"state_fips":6,"race":1,
        "hispanic":2,"employ":1,"marital":1,"veteran":2,"obese":1}
req = urllib.request.Request(B+"/api/v1/predict", data=json.dumps(body).encode(),
                             headers={"Content-Type":"application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=30) as r:
    d = json.loads(r.read().decode())
    dd = d["data"]
    print("%-34s %s code=%s prob=%.4f risk=%s" % ("POST /predict", r.status, d.get("code"),
          dd["probability"], dd["riskLevel"]))
    allok &= (r.status == 200 and d.get("code") == 0)
print("\nALL 9 ENDPOINTS OK:" , allok)
