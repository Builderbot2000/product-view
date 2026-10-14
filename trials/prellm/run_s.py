"""Group S of the embedding-route upgrade trials: B0, the stack, and drop-one
ablations on the dev window (end 2026-09-22), 5 input orders each.

    .venv/Scripts/python.exe -X utf8 trials/prellm/run_s.py VARIANT [--runs-only NAME ...]

VARIANT names a threshold set in VARIANTS (at most 3, tuned on V1), or "final"
for stack.FINAL (written as F.json under v2/). Results go to
trials/runs/prellm/S/<variant>/<run>.json (measures per order, medians, ranges,
ARI, runtimes, step info) and labels-<run>.npy.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from trials.prellm import harness as H, stack as S  # noqa: E402

END = "2026-09-22"
VARIANTS = {
    # v1: thresholds from priors and label-free distributions (see result-S.md)
    "v1": S.StackOptions(spec_min=6.0, reach=0.40, pull=0.50, join=0.75, neg_min=0.40, runs=20, tau=0.5,
                         search="legacy"),
    # v2: the band search keeps the ascending flank (v1's S-U4 collapse); U4 keeps a unit
    # when P(neg) >= P(pos) (v1 lost 20 of 107 issue points to neutral-sounding complaints)
    "v2": S.StackOptions(spec_min=6.0, reach=0.40, pull=0.50, join=0.75, neg_min=0.0, runs=20, tau=0.5,
                         search="flank"),
}


def configs(base: S.StackOptions):
    if base is S.FINAL:
        yield "F", base
        return
    yield "S", base
    for fix in ("U1", "U2", "U3", "U4", "U6"):
        yield f"S-{fix}", base.drop(fix)


def main():
    variant = sys.argv[1]
    only = set(sys.argv[2:])
    # "final": the stack left after rule 2 on v2 (not a tuning variant), saved under v2/
    base = S.FINAL if variant == "final" else VARIANTS[variant]
    out = H.OUT / "S" / ("v2" if variant == "final" else variant)
    out.mkdir(parents=True, exist_ok=True)
    plan = ([] if variant == "final" else [("B0", None)]) + list(configs(base))
    windows = {}
    for name, opts in plan:
        if only and name not in only:
            continue
        if name == "B0" and (out / "B0.json").exists() and not only:
            continue
        key = "neg" if opts is None or not opts.u4 else f"sent{opts.neg_min}"
        if key not in windows:
            windows[key] = H.load_window(END) if key == "neg" else S.window(END, opts)
        w = windows[key]
        infos = []
        if opts is None:
            fn = lambda s: H.cluster_b0(w, s)  # noqa: E731
        else:
            def fn(s, opts=opts, w=w):
                lab, info = S.cluster(w, s, opts)
                infos.append(info)
                return lab
        t = time.perf_counter()
        r = H.run_orders(fn, w, n=5)
        labs = r.pop("labels")
        np.save(out / f"labels-{name}.npy", np.vstack(labs))
        r["infos"] = infos
        r["opts"] = asdict(opts) if opts else "B0"
        r["window"] = {"stream": w.stream, "units": len(w), "reviews": len(w.rows), "info": w.info}
        (out / f"{name}.json").write_text(json.dumps(r, indent=1, default=H._jsonable), encoding="utf-8")
        md, rg = r["median"], r["range"]
        print(f"{name:7s} {time.perf_counter() - t:6.1f}s units {len(w):4d}  "
              f"P {md['P']:.3f} [{rg['P'][0]:.3f}-{rg['P'][1]:.3f}]  R {md['R']:.3f} [{rg['R'][0]:.3f}-{rg['R'][1]:.3f}]  "
              f"tone {md['tone']} [{rg['tone'][0]}-{rg['tone'][1]}]  grab {md['grab_bags']} [{rg['grab_bags'][0]}-{rg['grab_bags'][1]}]  "
              f"split {md['split']}  ARI {r['ARI']:.3f}  cov {md['coverage']:.2f} misc {md['misc_share']:.2f} "
              f"gen {md['general_share']:.2f} k {md['n_clusters']}  qp {md['qp_close']}/{md['qp_thumbs']}",
              flush=True)


if __name__ == "__main__":
    main()
