"""Probe primitives: each probe returns a ProbeResult; `tokiln probe all` aggregates them into Go/No-Go."""
import dataclasses, json, time


@dataclasses.dataclass
class ProbeResult:
    name: str
    ok: bool
    detail: dict
    duration_s: float

    def line(self) -> str:
        mark = "PASS" if self.ok else "FAIL"
        return f"[{mark}] {self.name} ({self.duration_s:.1f}s) {json.dumps(self.detail, ensure_ascii=False)}"


def timed(name):
    def deco(fn):
        async def wrap(*a, **kw):
            t0 = time.time()
            ok, detail = await fn(*a, **kw)
            return ProbeResult(name, ok, detail, time.time() - t0)
        return wrap
    return deco
