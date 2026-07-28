"""monitor HTTP 服务: GET /snapshot /history / (内置白底 HTML)。跑在 server 节点 8100 端口。"""
import asyncio
import pathlib

from aiohttp import web

from .collector import Collector

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>tokiln monitor</title>
<style>
body{background:#fff;color:#1a1a2e;font-family:ui-monospace,Menlo,Consolas,monospace;margin:24px}
h1{font-size:18px} .kpi{display:inline-block;border:1px solid #d0d4dc;border-radius:8px;
padding:10px 16px;margin:6px;min-width:120px} .kpi b{display:block;font-size:22px}
.kpi span{font-size:11px;color:#5a6270} table{border-collapse:collapse;margin-top:12px}
td,th{border:1px solid #e2e5ea;padding:4px 10px;font-size:12px} th{background:#f4f6f9}
#cli{margin-top:12px;padding:8px 12px;background:#f4f6f9;border-radius:8px;font-size:12px}
</style></head><body><h1>tokiln monitor — <span id="host"></span> <small id="ts"></small></h1>
<div id="kpis"></div><table id="gpus"></table><div id="cli"></div>
<script>
async function tick(){
 const s=await (await fetch('snapshot')).json(); if(!s.server) return;
 document.getElementById('host').textContent=s.host;
 document.getElementById('ts').textContent=s.time+(s.server.up?' · UP':' · DOWN');
 const v=s.server, k=[['running',v.running],['queued',v.queued],
  ['KV usage',((v.token_usage||0)*100).toFixed(1)+'%'],['gen tok/s',(v.gen_throughput||0).toFixed(1)],
  ['cache hit',(v.cache_hit_pct||0)+'%'],['TTFT avg',(v.ttft_avg_s||0)+'s'],
  ['ITL avg',(v.itl_avg_ms||0)+'ms'],['aborted',v.aborted_total||0]];
 document.getElementById('kpis').innerHTML=k.map(x=>`<div class="kpi"><b>${x[1]??'-'}</b><span>${x[0]}</span></div>`).join('');
 document.getElementById('gpus').innerHTML='<tr><th>GPU</th><th>util%</th><th>mem</th><th>W</th></tr>'+
  s.gpu.map(g=>`<tr><td>${g.idx}</td><td>${g.util_pct}</td><td>${g.mem_used_gb}/${g.mem_total_gb}G</td><td>${g.power_w}</td></tr>`).join('');
 document.getElementById('cli').textContent=s.client.active?`client [${s.client.run}] ${s.client.progress}`:'client: idle';
}
setInterval(tick,3000); tick();
</script></body></html>"""


def build_app(col: Collector) -> web.Application:
    async def snapshot(_):
        return web.json_response(col.snapshot)

    async def history(_):
        return web.json_response(col.history)

    async def index(_):
        return web.Response(text=PAGE, content_type="text/html")

    app = web.Application()
    app.add_routes([web.get("/", index), web.get("/snapshot", snapshot),
                    web.get("/history", history)])
    return app


async def _loop(col: Collector):
    while True:
        await asyncio.get_event_loop().run_in_executor(None, col.tick)
        await asyncio.sleep(col.interval)


def serve(sglang_url: str, runs_dir: pathlib.Path, port: int = 8100, interval: float = 5.0):
    col = Collector(sglang_url, runs_dir, interval)
    app = build_app(col)

    async def main():
        asyncio.create_task(_loop(col))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        print(f"tokiln monitor serving on :{port} (snapshot/history/浏览器页) → {sglang_url}")
        while True:
            await asyncio.sleep(3600)

    asyncio.run(main())
