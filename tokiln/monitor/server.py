"""Monitor HTTP service: GET /snapshot /history / (built-in dashboard GUI).
Runs on the serving node, port 8100. The page is served same-origin, so any
browser (Mac/Windows) pointed at http://<node>:8100/ gets a live GUI with no CORS setup."""
import asyncio
import os
import pathlib
import signal
import subprocess
import sys
import time

from aiohttp import web

from .collector import Collector

# Workloads the GUI may launch: two primary modes — synthetic and real-trajectory SWE replay.
BENCH_WORKLOADS = {
    "smoke": {"mode": "synth", "label": "Smoke — synthetic, 8 conc, 2 min"},
    "agentic-synth": {"mode": "synth", "label": "AA-AgentPerf — synthetic, 64 conc, 10 min"},
    "agentic-replay": {"mode": "replay", "label": "SWE-bench replay — real trajectories, 32 conc"},
}


class BenchController:
    """Launch/stop tokiln bench as a child process, one at a time."""

    def __init__(self, root: pathlib.Path, url: str, model: str = "glm52"):
        self.root, self.url, self.model = root, url, model
        self.proc: subprocess.Popen | None = None
        self.info: dict = {}

    def status(self) -> dict:
        running = self.proc is not None and self.proc.poll() is None
        out = {"running": running, **self.info, "workloads": {
            k: v["label"] for k, v in BENCH_WORKLOADS.items()}}
        if self.proc is not None and not running:
            out["rc"] = self.proc.returncode
        return out

    def start(self, workload: str, arm: str) -> tuple[int, dict]:
        if workload not in BENCH_WORKLOADS:
            return 400, {"error": f"unknown workload {workload}"}
        if arm not in ("A", "B"):
            return 400, {"error": "arm must be A or B"}
        if self.proc is not None and self.proc.poll() is None:
            return 409, {"error": "a bench is already running", **self.status()}
        log = f"/tmp/tokiln_bench_{time.strftime('%Y%m%d-%H%M%S')}_{workload}_arm{arm}.log"
        cmd = [sys.executable, "-m", "tokiln.cli", "bench", "--workload", workload,
               "--arm", arm, "--profile", "m0-sglang-only",
               "--url", f"{self.url}/v1", "--model", self.model]
        with open(log, "w") as lf:
            self.proc = subprocess.Popen(cmd, cwd=self.root, stdout=lf,
                                         stderr=subprocess.STDOUT, start_new_session=True)
        self.info = {"workload": workload, "arm": arm,
                     "mode": BENCH_WORKLOADS[workload]["mode"],
                     "started": time.strftime("%H:%M:%S"), "log": log}
        return 200, self.status()

    def stop(self) -> dict:
        if self.proc is not None and self.proc.poll() is None:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        return self.status()

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>tokiln monitor</title>
<style>
  .viz-root{
    color-scheme: light;
    --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
    --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10);
    --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --good:#0ca30c; --crit:#d03b3b;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--page);color:var(--ink);
       font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
  .wrap{max-width:1180px;margin:0 auto;padding:20px 24px 48px}
  header{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:14px}
  h1{font-size:18px;margin:0}
  .sub{color:var(--ink2);font-size:13px}
  .pill{font-size:12px;font-weight:600;border-radius:99px;padding:2px 10px}
  .pill.up{background:#e3f4e3;color:var(--good)}
  .pill.down{background:#fbe9e7;color:var(--crit)}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:10px;margin-bottom:16px}
  .kpi{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:10px 14px}
  .kpi b{display:block;font-size:21px;font-weight:650;letter-spacing:-.01em}
  .kpi span{font-size:11.5px;color:var(--muted)}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 16px;position:relative}
  .card.wide{grid-column:1/-1}
  .card h2{font-size:13px;font-weight:600;margin:0 0 2px;color:var(--ink)}
  .legend{display:flex;gap:14px;font-size:11.5px;color:var(--ink2);margin-bottom:6px}
  .legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
  svg{display:block;width:100%}
  .tip{position:absolute;pointer-events:none;background:var(--surface);border:1px solid var(--border);
       border-radius:8px;box-shadow:0 2px 8px rgba(11,11,11,.08);padding:7px 10px;font-size:11.5px;
       color:var(--ink2);display:none;z-index:9;white-space:nowrap}
  .tip b{color:var(--ink);font-weight:600}
  .tip .row{display:flex;align-items:center;gap:6px;margin-top:2px}
  .tip i{display:inline-block;width:8px;height:8px;border-radius:2px}
  .gpu-row{display:grid;grid-template-columns:52px 1fr 120px;gap:10px;align-items:center;font-size:12px;margin:5px 0}
  .gpu-row .lbl{color:var(--muted)}
  .gpu-bar{height:10px;background:var(--grid);border-radius:5px;overflow:hidden}
  .gpu-bar div{height:100%;background:var(--s1);border-radius:5px 4px 4px 5px}
  .gpu-row .val{color:var(--ink2);text-align:right;font-variant-numeric:tabular-nums}
  .client{font-size:12.5px;color:var(--ink2)}
  .client code{background:var(--page);border:1px solid var(--border);border-radius:5px;padding:1px 6px;font-size:11.5px}
  footer{margin-top:14px;font-size:11.5px;color:var(--muted)}
  .ctl{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
  .ctl select{font:12.5px system-ui;padding:5px 8px;border:1px solid var(--border);border-radius:7px;background:var(--surface);color:var(--ink)}
  .ctl button{font:12.5px system-ui;font-weight:600;padding:5px 14px;border-radius:7px;border:1px solid var(--border);cursor:pointer}
  .ctl .go{background:var(--s1);border-color:var(--s1);color:#fff}
  .ctl .go:disabled{background:var(--grid);border-color:var(--grid);color:var(--muted);cursor:default}
  .ctl .halt{background:var(--surface);color:var(--crit)}
  .bstat{font-size:11.5px;color:var(--muted);margin-bottom:6px}
</style></head>
<body class="viz-root"><div class="wrap">
<header>
  <h1>tokiln monitor</h1>
  <span class="sub" id="host"></span>
  <span class="pill down" id="status">connecting…</span>
  <span class="sub" id="model"></span>
  <span class="sub" id="ts" style="margin-left:auto"></span>
</header>
<div class="kpis" id="kpis"></div>
<div class="grid">
  <div class="card wide"><h2>Generation throughput (tok/s)</h2><div id="c_tput"></div></div>
  <div class="card"><h2>Requests</h2>
    <div class="legend"><span><i style="background:var(--s1)"></i>running</span><span><i style="background:var(--s2)"></i>queued</span></div>
    <div id="c_req"></div></div>
  <div class="card"><h2>Utilization (%)</h2>
    <div class="legend"><span><i style="background:var(--s1)"></i>GPU util</span><span><i style="background:var(--s2)"></i>KV usage</span><span><i style="background:var(--s3)"></i>cache hit</span></div>
    <div id="c_util"></div></div>
  <div class="card"><h2>GPUs</h2><div id="gpus"></div></div>
  <div class="card"><h2>Load client</h2>
    <div class="ctl">
      <select id="b_wl">
        <option value="smoke">Smoke — synthetic, 8 conc, 2 min</option>
        <option value="agentic-synth">AA-AgentPerf — synthetic, 64 conc, 10 min</option>
        <option value="agentic-replay">SWE-bench replay — real trajectories, 32 conc</option>
      </select>
      <select id="b_arm"><option>A</option><option>B</option></select>
      <button class="go" id="b_go">Start</button>
      <button class="halt" id="b_halt">Stop</button>
    </div>
    <div class="bstat" id="b_stat"></div>
    <div class="client" id="client">–</div></div>
</div>
<footer>polls /snapshot + /history every 3 s · history window ≈ 1 h at 5 s granularity</footer>
</div>
<script>
const $=id=>document.getElementById(id);
const fmt=(v,d=1)=>v==null?'–':(+v).toFixed(d);
const W=520,H=150,PL=44,PR=10,PT=8,PB=22;

function chart(el,hist,series,yMax){
  if(!hist.length){el.innerHTML='<div style="color:var(--muted);font-size:12px;padding:24px 0">collecting…</div>';return;}
  const xs=hist.map(h=>h.ts),x0=xs[0],x1=xs[xs.length-1]||x0+1;
  const X=t=>PL+(t-x0)/((x1-x0)||1)*(W-PL-PR);
  const max=yMax??Math.max(1,...series.flatMap(s=>hist.map(h=>+h[s.k]||0)))*1.1;
  const Y=v=>PT+(1-v/max)*(H-PT-PB);
  let g='';
  for(let i=0;i<=3;i++){const v=max*i/3,y=Y(v);
    g+=`<line x1="${PL}" x2="${W-PR}" y1="${y}" y2="${y}" stroke="var(--grid)" stroke-width="1"/>`+
       `<text x="${PL-6}" y="${y+3.5}" text-anchor="end" font-size="10" fill="var(--muted)">${v>=100?Math.round(v):fmt(v,v<10?1:0)}</text>`;}
  const t2s=t=>new Date(t*1000).toTimeString().slice(0,5);
  [0,.5,1].forEach(f=>{const t=x0+(x1-x0)*f;
    g+=`<text x="${X(t)}" y="${H-6}" text-anchor="middle" font-size="10" fill="var(--muted)">${t2s(t)}</text>`;});
  series.forEach((s,si)=>{
    const pts=hist.map(h=>`${X(h.ts).toFixed(1)},${Y(Math.min(+h[s.k]||0,max)).toFixed(1)}`);
    if(series.length===1)
      g+=`<path d="M${pts.join('L')}L${X(x1).toFixed(1)},${Y(0)}L${X(x0).toFixed(1)},${Y(0)}Z" fill="${s.c}" opacity="0.12"/>`;
    g+=`<path d="M${pts.join('L')}" fill="none" stroke="${s.c}" stroke-width="2" stroke-linejoin="round"/>`;});
  g+=`<line id="xh" y1="${PT}" y2="${H-PB}" stroke="var(--axis)" stroke-width="1" visibility="hidden"/>`;
  series.forEach((s,i)=>g+=`<circle id="m${i}" r="4" fill="${s.c}" stroke="var(--surface)" stroke-width="2" visibility="hidden"/>`);
  el.innerHTML=`<svg viewBox="0 0 ${W} ${H}"></svg><div class="tip"></div>`;
  el.querySelector('svg').innerHTML=g;
  const svg=el.querySelector('svg'),tip=el.querySelector('.tip');
  svg.onmousemove=e=>{
    const r=svg.getBoundingClientRect(),mx=(e.clientX-r.left)/r.width*W;
    let bi=0,bd=1e18;
    hist.forEach((h,i)=>{const d=Math.abs(X(h.ts)-mx);if(d<bd){bd=d;bi=i;}});
    const h=hist[bi],x=X(h.ts);
    svg.querySelector('#xh').setAttribute('visibility','visible');
    svg.querySelector('#xh').setAttribute('x1',x);svg.querySelector('#xh').setAttribute('x2',x);
    series.forEach((s,i)=>{const m=svg.querySelector('#m'+i);
      m.setAttribute('visibility','visible');m.setAttribute('cx',x);m.setAttribute('cy',Y(Math.min(+h[s.k]||0,max)));});
    tip.style.display='block';
    tip.innerHTML=`<b>${t2s(h.ts)}</b>`+series.map(s=>
      `<div class="row"><i style="background:${s.c}"></i>${s.n}: <b>${fmt(h[s.k],s.d)}</b></div>`).join('');
    const tw=tip.offsetWidth,px=e.clientX-r.left;
    tip.style.left=Math.min(Math.max(px+14,0),r.width-tw-4)+'px';
    tip.style.top='10px';};
  svg.onmouseleave=()=>{tip.style.display='none';
    svg.querySelector('#xh').setAttribute('visibility','hidden');
    series.forEach((s,i)=>svg.querySelector('#m'+i).setAttribute('visibility','hidden'));};
}

async function tick(){
  let s,hist;
  try{[s,hist]=await Promise.all([fetch('snapshot').then(r=>r.json()),fetch('history').then(r=>r.json())]);}
  catch(e){$('status').textContent='unreachable';$('status').className='pill down';return;}
  if(!s.server)return;
  const v=s.server;
  $('host').textContent=s.host||'';
  $('model').textContent=v.model?('model '+v.model):'';
  $('ts').textContent=s.time||'';
  $('status').textContent=v.up?'server up':'server down';
  $('status').className='pill '+(v.up?'up':'down');
  const kv=(v.token_usage||0)*100;
  $('kpis').innerHTML=[
    ['running',v.running??'–',0],['queued',v.queued??'–',0],
    ['gen tok/s',fmt(v.gen_throughput)],['KV usage',fmt(kv)+'%'],
    ['cache hit',fmt(v.cache_hit_pct)+'%'],['TTFT avg',fmt(v.ttft_avg_s,2)+' s'],
    ['ITL avg',fmt(v.itl_avg_ms)+' ms'],['aborted',v.aborted_total??'–',0]
  ].map(k=>`<div class="kpi"><b>${typeof k[1]==='number'?Math.round(k[1]):k[1]}</b><span>${k[0]}</span></div>`).join('');
  const hs=hist.map(h=>({...h,kv_pct:(h.token_usage||0)*100}));
  chart($('c_tput'),hs,[{k:'gen_throughput',n:'gen tok/s',c:'var(--s1)',d:1}]);
  chart($('c_req'),hs,[{k:'running',n:'running',c:'var(--s1)',d:0},{k:'queued',n:'queued',c:'var(--s2)',d:0}]);
  chart($('c_util'),hs,[{k:'gpu_util_avg',n:'GPU util %',c:'var(--s1)',d:0},{k:'kv_pct',n:'KV usage %',c:'var(--s2)',d:1},{k:'cache_hit_pct',n:'cache hit %',c:'var(--s3)',d:1}],100);
  $('gpus').innerHTML=(s.gpu||[]).map(g=>
    `<div class="gpu-row"><span class="lbl">GPU ${g.idx}</span>`+
    `<div class="gpu-bar"><div style="width:${Math.min(100,g.util_pct)}%"></div></div>`+
    `<span class="val">${Math.round(g.util_pct)}% · ${fmt(g.mem_used_gb,0)}/${fmt(g.mem_total_gb,0)}G</span></div>`).join('');
  const c=s.client||{};
  $('client').innerHTML=c.active
    ?`<code>${c.run||''}</code><br>${c.progress||''}<br><span style="color:var(--muted)">updated ${fmt(c.age_s,0)} s ago</span>`
    :'<span style="color:var(--muted)">idle — no loadgen in progress</span>';
}
async function btick(){
  try{
    const b=await fetch('bench').then(r=>r.json());
    $('b_go').disabled=b.running;
    $('b_stat').textContent=b.running
      ?`running: ${b.workload} (${b.mode}) arm ${b.arm} — started ${b.started}`
      :(b.workload?`last: ${b.workload} arm ${b.arm}${b.rc!=null?' — rc='+b.rc+(b.rc===0?' (pass)':b.rc===4?' (criteria failed)':''):''}`:'no bench launched yet');
  }catch(e){}
}
async function benchPost(path,body){
  const hdrs={'Content-Type':'application/json'};
  const tok=localStorage.getItem('tokiln_ctl_token');
  if(tok)hdrs['X-Control-Token']=tok;
  let r=await fetch(path,{method:'POST',headers:hdrs,body});
  if(r.status===401){
    const t=prompt('This monitor requires a control token to start/stop benches:');
    if(t){localStorage.setItem('tokiln_ctl_token',t);
      hdrs['X-Control-Token']=t;
      r=await fetch(path,{method:'POST',headers:hdrs,body});}}
  return r;}
$('b_go').onclick=async()=>{
  $('b_go').disabled=true;
  await benchPost('bench/start',JSON.stringify({workload:$('b_wl').value,arm:$('b_arm').value}));
  btick();};
$('b_halt').onclick=async()=>{await benchPost('bench/stop');btick();};
setInterval(tick,3000);setInterval(btick,3000);tick();btick();
</script></body></html>"""


def build_app(col: Collector, bench: "BenchController", control_token: str = "") -> web.Application:
    async def snapshot(_):
        return web.json_response(col.snapshot, headers={"Access-Control-Allow-Origin": "*"})

    async def history(_):
        return web.json_response(col.history, headers={"Access-Control-Allow-Origin": "*"})

    async def index(_):
        return web.Response(text=PAGE, content_type="text/html")

    async def bench_get(_):
        return web.json_response(bench.status())

    def _authorized(req) -> bool:
        return not control_token or req.headers.get("X-Control-Token", "") == control_token

    async def bench_start(req):
        if not _authorized(req):
            return web.json_response({"error": "control token required"}, status=401)
        body = await req.json()
        code, out = bench.start(body.get("workload", "smoke"), body.get("arm", "A"))
        return web.json_response(out, status=code)

    async def bench_stop(req):
        if not _authorized(req):
            return web.json_response({"error": "control token required"}, status=401)
        return web.json_response(bench.stop())

    app = web.Application()
    app.add_routes([web.get("/", index), web.get("/snapshot", snapshot),
                    web.get("/history", history), web.get("/bench", bench_get),
                    web.post("/bench/start", bench_start), web.post("/bench/stop", bench_stop)])
    return app


async def _loop(col: Collector):
    while True:
        await asyncio.get_event_loop().run_in_executor(None, col.tick)
        await asyncio.sleep(col.interval)


def serve(sglang_url: str, runs_dir: pathlib.Path, port: int = 8100, interval: float = 5.0,
          control_token: str = ""):
    control_token = control_token or os.environ.get("TOKILN_MONITOR_TOKEN", "")
    col = Collector(sglang_url, runs_dir, interval)
    bench = BenchController(runs_dir.parent, col.sglang_url)
    app = build_app(col, bench, control_token)

    async def main():
        asyncio.create_task(_loop(col))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        print(f"tokiln monitor serving on :{port} (snapshot/history/dashboard) → {sglang_url}")
        while True:
            await asyncio.sleep(3600)

    asyncio.run(main())
