"""Agent 工厂、LLM 调用封装、Mock 模式。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Agent:
    id: str
    name: str
    role: str
    system_prompt: str
    initial_claim: float = 0.33
    claim_rationale: str = ""
    memory: list[dict] = field(default_factory=list)
    current_claim: float = 0.33

    def reset(self) -> None:
        self.memory.clear()
        self.current_claim = self.initial_claim


class AgentFactory:
    @staticmethod
    def from_scenario(scenario: dict) -> tuple[list[Agent], Agent]:
        agents = []
        for raw in scenario.get("agents", []):
            claim = float(raw.get("initial_claim", 0.33))
            agents.append(Agent(
                id=raw["id"],
                name=raw["name"],
                role=raw.get("role", ""),
                system_prompt=raw.get("system_prompt", ""),
                initial_claim=claim,
                claim_rationale=raw.get("claim_rationale", ""),
                current_claim=claim,
            ))
        arb = scenario["arbiter"]
        arbiter = Agent(
            id=arb["id"],
            name=arb["name"],
            role=arb.get("role", "仲裁"),
            system_prompt=arb.get("system_prompt", ""),
            initial_claim=0.0,
            current_claim=0.0,
        )
        return agents, arbiter


def call_llm(
    messages: list[dict],
    *,
    model: str = "deepseek-chat",
    temperature: float = 0.7,
    api_key: Optional[str] = None,
) -> str:
    """
    可选 LLM 模式：兼容 OpenAI 风格接口（DeepSeek）。
    未配置 Key 时抛错，由上层回退 Mock。
    """
    key = api_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，无法使用 LLM 模式")

    try:
        import urllib.request
        import json as _json
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("标准库不可用") from e

    base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    payload = _json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base.rstrip('/')}/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = _json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Mock 对话脚本：为路演打磨，比例逐步向公式结果收敛
# ---------------------------------------------------------------------------

MOCK_DIALOGUE: list[dict[str, Any]] = [
    {
        "round": 1,
        "phase": "opening",
        "utterances": [
            {
                "speaker": "李量化",
                "role": "量化研究员",
                "claim": 0.40,
                "text": (
                    "先摆数据。波动率因子 v2.3 在指数增强线 IC=0.08、IR=1.6，"
                    "归因超额约 ¥1,200 万（占该线超额 35%）；市场中性线 IC=0.06、IR=1.2，"
                    "归因 ¥800 万（占 30%）。两条线合计 ¥2,000 万，没有这个因子两边都会明显缩水。"
                    "我主张可分配池的 40%。"
                ),
            },
            {
                "speaker": "张经理",
                "role": "PM-指数增强",
                "claim": 0.45,
                "text": (
                    "因子是信号输入，不是收益本身。我管着 ¥5 亿 AUM，跟踪误差压在 4%，"
                    "超额 12% 里大约 65% 来自仓位节奏、风格切换和交易执行。"
                    "客户回撤压力也是我扛的。李量化 40% 过高，我要 45%。"
                ),
            },
            {
                "speaker": "陈经理",
                "role": "PM-市场中性",
                "claim": 0.35,
                "text": (
                    "我这边是纯 Alpha，Beta 净敞口 <0.05，确实更吃因子质量——"
                    "波动率因子贡献了大约 45% 超额。但极端行情下的对冲决策，至少避免了 ¥300 万回撤。"
                    "我认因子价值，也坚持执行侧不可替代。我要 35%。"
                ),
            },
        ],
        "claims": {"李量化": 0.40, "张经理": 0.45, "陈经理": 0.35},
        "normalized": {"李量化": 0.333, "张经理": 0.375, "陈经理": 0.292},
        "consensus": 0.22,
    },
    {
        "round": 2,
        "phase": "rebuttal",
        "utterances": [
            {
                "speaker": "李量化",
                "role": "量化研究员",
                "claim": 0.36,
                "text": (
                    "张经理说得对，执行把信号变成钱。但请注意：同一因子被两条线复用一整年，"
                    "传统 KPI 只给我固定年终奖，复用价值完全断档。我可以让到 36%，"
                    "前提是承认「层积式贡献」——复用次数应进入计量。"
                ),
            },
            {
                "speaker": "张经理",
                "role": "PM-指数增强",
                "claim": 0.41,
                "text": (
                    "复用逻辑我部分接受：中性线确实更依赖因子。但指数增强这边，"
                    "因子依赖度大约 35%，其余是组合构建；况且 AUM 是陈经理的近两倍。"
                    "我降到 41%，不能再低——下行风险在我账上。"
                ),
            },
            {
                "speaker": "陈经理",
                "role": "PM-市场中性",
                "claim": 0.30,
                "text": (
                    "我站在中间：比张经理更认因子，也不希望研究员被KPI压成「一次性外包」。"
                    "建议用贡献值公式给一个客观锚点，大家在锚点附近谈。我调到 30%。"
                ),
            },
        ],
        "claims": {"李量化": 0.36, "张经理": 0.41, "陈经理": 0.30},
        "normalized": {"李量化": 0.336, "张经理": 0.383, "陈经理": 0.280},
        "consensus": 0.48,
    },
    {
        "round": 3,
        "phase": "anchor",
        "utterances": [
            {
                "speaker": "李量化",
                "role": "量化研究员",
                "claim": 0.34,
                "text": (
                    "同意引入公式锚点。我的稀缺性更高（能独立做可复用因子的人少），"
                    "再加上双策略复用加成，公式侧应明显高于固定年奖折算。我收到 34%。"
                ),
            },
            {
                "speaker": "张经理",
                "role": "PM-指数增强",
                "claim": 0.39,
                "text": (
                    "可以。公式把执行变现和 AUM 规模写进 Impact——"
                    "信号变成真金白银靠的是仓位与风控，我这边 Impact 应最高。"
                    "我收到 39%，接近公式中枢就收。"
                ),
            },
            {
                "speaker": "陈经理",
                "role": "PM-市场中性",
                "claim": 0.28,
                "text": (
                    "市场中性更吃因子，我的执行侧 Impact 理应低于张经理；"
                    "对冲仍有独立价值，但不能压过 ¥5 亿线。我收到 28%。"
                    "三者与公式偏差小于 5 个点，建议锁定。"
                ),
            },
        ],
        "claims": {"李量化": 0.34, "张经理": 0.39, "陈经理": 0.28},
        "normalized": {"李量化": 0.337, "张经理": 0.386, "陈经理": 0.277},
        "consensus": 0.71,
    },
    {
        "round": 4,
        "phase": "convergence",
        "utterances": [
            {
                "speaker": "李量化",
                "role": "量化研究员",
                "claim": 0.34,
                "text": "最后一轮：我接受向公式份额靠拢，锁定约 34%，具体以计算引擎输出为准。",
            },
            {
                "speaker": "张经理",
                "role": "PM-指数增强",
                "claim": 0.38,
                "text": "同意。指数增强线 AUM 更大、执行权重更高，份额略高于研究员合理。我锁定约 38%。",
            },
            {
                "speaker": "陈经理",
                "role": "PM-市场中性",
                "claim": 0.28,
                "text": "同意收敛。纯 Alpha 线为因子说了公道话，执行侧分成低于张经理也说得通。可以出公式终值。",
            },
        ],
        "claims": {"李量化": 0.34, "张经理": 0.38, "陈经理": 0.28},
        "normalized": {"李量化": 0.340, "张经理": 0.380, "陈经理": 0.280},
        "consensus": 0.88,
    },
]


def mock_arbiter_speech(formula_shares: dict[str, float], negotiated: dict[str, float]) -> str:
    lines = [
        "三方已接近收敛。我按 AlphaSplit 贡献值公式给出待确认的建议份额：",
        "C = Labor × Impact × Scarcity × Reuse。",
    ]
    for name, pct in formula_shares.items():
        neg = negotiated.get(name, pct)
        lines.append(
            f"- {name}：公式 {pct:.1%}，协商意向约 {neg:.1%}，建议方案采用 {pct:.1%}。"
        )
    lines.append("裁决生效：公式保公平下限，协商保留陈述与微调空间，二者以公式终值为准。")
    return "\n".join(lines)
