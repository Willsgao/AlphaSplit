# AlphaSplit 架构设计（与当前可运行 Demo 对齐）

## 一、方案定位

面向 **第五届中国研究生金融科技创新大赛 · 自拟赛题**  
方向：**人工智能技术在金融领域的创新应用**

核心问题：量化平台中，可复用知识资产（因子）产生的超额收益，如何在研究员与多策略 PM 之间公平分配？

设计原则：

1. **Agent 协商是前台**：各方陈述主张、交换论据、调整诉求。
2. **贡献值公式是终裁**：`C = Labor × Impact × Scarcity × Reuse`，保证可审计的公平下限。
3. **Mock 优先**：路演默认播放打磨过的协商脚本；可选 LLM 模式验证智能能力。
4. **对照可解释**：KPI / 纯公式 / Agent+公式 三组机制仿真（非真实历史回测）。

---

## 二、系统分层

```
Web (engine/web)  →  FastAPI (engine/api)  →  agentic/ + core/
     四面板 SPA         /api/*                 协商 · 演化 · 公式
```

| 层 | 路径 | 职责 |
|----|------|------|
| 前端 | `engine/web/` | 对话流 / 三组对照 / 演化曲线 / 公式表；Chart.js 已本地化（`chart.umd.min.js`） |
| API | `engine/api/main.py` | REST 入口，静态资源 |
| 协商 | `engine/agentic/` | Mock/LLM 多轮协商、演化对照 |
| 核心 | `engine/core/` | 贡献值公式、场景加载 |
| 数据 | `data/scenarios/*.json` | 可替换场景 |

---

## 三、贡献值公式（金融化四维）

```
Labor    = hours × (complexity / 5)
Impact   = 优先读取场景显式 impact_score（Demo 可审计标定）
           缺省时回退：研究员用归因占比映射；PM 用 1−factor_reliance + AUM 上修
Scarcity = 1 / (1 + k · pool_size)
Reuse    = 1 + ρ · (reuse_count − 1)

C_i = Labor_i × Impact_i × Scarcity_i × Reuse_i
份额 = C_i / ΣC ，金额 = 份额 × 可分配池
```

量化基金场景标定目标（张 > 李 > 陈）：张 Impact=0.78，李/陈=0.55，体现「变现靠执行、AUM 更大份额更高」。

可分配池 = 奖金总额 × (1 − platform_share)

> 说明：不再宣称未实现的「六轨」。四维均可从场景 JSON 读取或推导。

---

## 四、协商协议

1. 各方给出 `initial_claim`（可 >100% 总和，制造冲突）。
2. 多轮发言 → 归一化份额 → 计算相对上轮变化。
3. 连续 2 轮最大份额变化 < `convergence_threshold`（默认 5%）→ 收敛。
4. 超过 `max_negotiation_rounds` 未收敛 → 仲裁介入。
5. **最终落账以公式份额为准**（协商影响陈述与满意度，不篡改审计终值）。

Mock 脚本见 `engine/agentic/agents.py` 中 `MOCK_DIALOGUE`。

---

## 五、演化对照（诚实边界）

| 组别 | 规则 | 预期特征 |
|------|------|----------|
| KPI | 利润跟账户走，研究员固定小份额 | 高 Gini、低复用激励 |
| 公式 | 纯 C_i 分配 | 中等均度、客观但缺少「被听见」 |
| Agent | 协商过程 + 公式终裁 | 同公式份额，更高满意度与协作指标 |

API/前端展示时附带 disclaimer：机制仿真，非真实基金回测。

---

## 六、API

| 路由 | 方法 | 功能 |
|------|------|------|
| `/` | GET | SPA |
| `/api/health` | GET | 健康检查 |
| `/api/scenario` | GET | 场景 JSON |
| `/api/calculate` | POST | 单次公式分配 |
| `/api/simulate` | POST | 多轮 cap 模拟 |
| `/api/negotiate` | POST | Agent 协商 |
| `/api/evolution` | POST | N 轮三组对照 |

---

## 七、启动

```bash
pip install -r requirements.txt
python -m engine.simulate          # CLI
python -m engine.api.main          # Web → http://127.0.0.1:8000
python -m engine.api.main --mode llm   # 需 DEEPSEEK_API_KEY
```

---

## 八、赛事交付物映射

| 赛事要求 | 本仓库对应 |
|----------|------------|
| 可运行成果 | FastAPI + Web Demo / `engine.simulate` |
| 技术文档 | 本文件 + README |
| 精益画布 | 决赛前按组委会模板填写（问题/方案/指标/落地） |
| 原创性声明 | 提交前签署官网模板 |

---

## 九、已知边界（答辩可主动说）

- Demo 场景为合成脱敏数据，非真实客户奖金。
- Mock 对话为路演稳定性设计；LLM 模式结果有波动。
- 演化指标含受控噪声，用于展示机制差异趋势。
- 生产落地需接入企业 HR/绩效与合规审批流。
