#!/usr/bin/env python3
"""
AlphaSplit CLI 快速演示（无需启动 Web）。

用法（在仓库根目录）：
  python -m engine.simulate
  python -m engine.simulate --evolution 50
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.agentic.evolution import run_evolution
from engine.agentic.negotiation import run_negotiation
from engine.core.calculator import calculate_once
from engine.core.scenario import agents_to_contributors, load_scenario, scenario_params


def _print_header(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="AlphaSplit CLI demo")
    parser.add_argument("--scenario", default="quant_fund")
    parser.add_argument("--mode", choices=["mock", "llm"], default="mock")
    parser.add_argument("--evolution", type=int, default=20, help="演化轮数")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    args = parser.parse_args()

    scenario = load_scenario(args.scenario)
    params = scenario_params(scenario)
    contributors = agents_to_contributors(scenario)

    _print_header(f"场景: {scenario['scenario']['name']}")
    print(scenario["scenario"]["description"])
    print(f"奖金池: ¥{params['profit']:,.0f}  平台份额: {params['platform_share']:.0%}")

    calc = calculate_once(
        contributors,
        profit=params["profit"],
        platform_share=params["platform_share"],
        k=params["k"],
        cap_multiplier=params["cap_multiplier"],
        traditional_rate=params["traditional_rate"],
        rho=params["rho"],
    )

    _print_header("贡献值公式分配")
    print(f"公式: {calc['formula']}")
    print(f"可分配池: ¥{calc['distributable']:,.2f}")
    for c in calc["contributors"]:
        print(
            f"  {c['name']:6s}  C={c['contribution']:8.2f}  "
            f"份额={c['share_pct']:5.1f}%  金额=¥{c['profit']:,.2f}"
        )

    neg = run_negotiation(args.scenario, mode=args.mode)
    _print_header(f"Agent 协商 ({neg['mode']})")
    for rnd in neg["rounds"]:
        print(f"\n-- Round {rnd['round']} [{rnd['phase']}] consensus={rnd.get('consensus', 0):.0%} --")
        for u in rnd["utterances"]:
            print(f"  [{u['speaker']}] {u['text'][:80]}{'…' if len(u['text']) > 80 else ''}")
    print("\n仲裁发言:")
    print(neg["arbiter_statement"])
    print("\n系统建议案（待人工确认）:")
    for name, s in neg["settlement"].items():
        print(
            f"  {name}: 建议 {s['proposed_share']:.1%} "
            f"(锚点 {s['formula_share']:.1%} · 带宽 {s['band_low']:.1%}–{s['band_high']:.1%}) "
            f"→ ¥{s['amount']:,.2f}"
        )
    print(f"状态: {neg.get('status')} · band=±{neg.get('band', 0.05):.0%}")

    evo = run_evolution(args.scenario, rounds=args.evolution, seed=42)
    _print_header(f"三组对照演化 ({evo['rounds']} 轮均值)")
    print(evo["disclaimer"])
    for g, label in [("kpi", "KPI"), ("formula", "公式"), ("agent", "Agent")]:
        s = evo["summary"][g]
        print(
            f"  {label:6s}  Gini={s['gini']:.3f}  "
            f"满意度={s['satisfaction']:.1%}  "
            f"复用激励={s['reuse_incentive']:.1%}"
        )

    if args.json:
        _print_header("JSON dump")
        print(json.dumps({"calculate": calc, "negotiate": neg, "evolution": evo}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
