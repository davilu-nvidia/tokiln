"""终端实时看板 (win/mac/linux 通用, 仅 stdlib)。
用法: python -m tokiln.monitor.watch --url http://10.6.131.9:8100
     或 tokiln monitor watch --url ...
单文件无第三方依赖 —— 没装 tokiln 的机器可直接拷这个文件运行。"""
import argparse
import json
import os
import sys
import time
import urllib.request

BLOCKS = "▁▂▃▄▅▆▇█"
CSI = "\x1b["


def _fetch(url: str):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


def spark(vals, width=48):
    vals = vals[-width:]
    if not vals:
        return ""
    hi = max(vals) or 1
    return "".join(BLOCKS[min(7, int(v / hi * 7.999))] for v in vals)


def bar(frac, width=24):
    n = int(max(0.0, min(1.0, frac)) * width)
    return "█" * n + "░" * (width - n)


def render(snap: dict, hist: list) -> str:
    L = []
    srv = snap.get("server", {})
    up = "UP ✓" if srv.get("up") else "DOWN ✗"
    L.append(f"┌─ tokiln monitor ── {snap.get('host','?')} ── {snap.get('time','')} ── server {up} "
             f"── model {srv.get('model','-')}")
    usage = srv.get("token_usage", 0.0)
    L.append(f"│ running {int(srv.get('running',0)):>4}   queued {int(srv.get('queued',0)):>4}   "
             f"gen {srv.get('gen_throughput',0):>8.1f} tok/s   aborted {int(srv.get('aborted_total',0))}")
    L.append(f"│ KV usage [{bar(usage)}] {usage*100:5.1f}%   "
             f"cache hit {srv.get('cache_hit_pct',0):5.1f}%   "
             f"TTFT {srv.get('ttft_avg_s','-')}s   ITL {srv.get('itl_avg_ms','-')}ms")
    gpus = snap.get("gpu", [])
    if gpus:
        util = " ".join(f"{int(g['util_pct']):3d}" for g in gpus)
        avg_mem = sum(g["mem_used_gb"] for g in gpus) / len(gpus)
        pw = sum(g["power_w"] for g in gpus)
        L.append(f"│ GPU util% [{util}]  mem {avg_mem:.0f}G/卡  power {pw:.0f}W")
    if hist:
        L.append(f"│ tput  {spark([h['gen_throughput'] for h in hist])}")
        L.append(f"│ run#  {spark([h['running'] for h in hist])}")
        L.append(f"│ kv%   {spark([h['token_usage'] for h in hist])}")
    cli = snap.get("client", {})
    if cli.get("active"):
        L.append(f"│ client [{cli.get('run','')}] {cli.get('progress','')}")
    else:
        L.append("│ client: idle (无进行中的 loadgen)")
    L.append("└" + "─" * 78)
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="tokiln 终端监控看板")
    ap.add_argument("--url", default="http://localhost:8100", help="monitor serve 地址")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--once", action="store_true", help="只渲染一帧 (调试/截图用)")
    args = ap.parse_args()

    if os.name == "nt":
        os.system("")          # 激活 Win10+ 终端的 ANSI 转义支持
    base = args.url.rstrip("/")
    err_streak = 0
    while True:
        try:
            snap = _fetch(f"{base}/snapshot")
            hist = _fetch(f"{base}/history")
            frame = render(snap, hist)
            err_streak = 0
        except Exception as e:
            err_streak += 1
            frame = f"┌─ tokiln monitor ── 连不上 {base} ({e})\n└" + "─" * 78
            if args.once or err_streak > 30:
                print(frame)
                sys.exit(1)
        if args.once:
            print(frame)
            return
        sys.stdout.write(f"{CSI}2J{CSI}H" + frame + "\n")
        sys.stdout.flush()
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
