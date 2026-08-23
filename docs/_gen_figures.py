from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

out = Path(__file__).resolve().parent / "figures"
out.mkdir(parents=True, exist_ok=True)


def font(size, bold=False):
    candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def rounded_rect(draw, xy, fill, outline="#333333", width=2, radius=18):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def center_text(draw, box, text, f, fill="#222222"):
    x0, y0, x1, y1 = box
    lines = text.split("\n")
    heights, widths = [], []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=f)
        widths.append(bbox[2] - bbox[0])
        heights.append(bbox[3] - bbox[1])
    total_h = sum(heights) + (len(lines) - 1) * 6
    cy = y0 + (y1 - y0 - total_h) / 2
    for i, line in enumerate(lines):
        tw = widths[i]
        tx = x0 + (x1 - x0 - tw) / 2
        draw.text((tx, cy), line, font=f, fill=fill)
        cy += heights[i] + 6


def arrow(draw, x1, y1, x2, y2, fill="#555555"):
    draw.line((x1, y1, x2, y2), fill=fill, width=3)
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 > x1 else -1
        draw.polygon(
            [(x2, y2), (x2 - 10 * direction, y2 - 6), (x2 - 10 * direction, y2 + 6)],
            fill=fill,
        )
    else:
        direction = 1 if y2 > y1 else -1
        draw.polygon(
            [(x2, y2), (x2 - 6, y2 - 10 * direction), (x2 + 6, y2 - 10 * direction)],
            fill=fill,
        )


title = font(36, True)
body = font(26)
small = font(22)

# fig2-1
im = Image.new("RGB", (1400, 900), "white")
d = ImageDraw.Draw(im)
d.text((80, 30), "图2-1  AlphaSplit 系统总体架构", font=title, fill="#111")
layers = [
    (60, 110, 1340, 260, "#E8F4FC", "输出层", "贡献系数 · 可视化报告 · 人工确认接口"),
    (60, 290, 1340, 440, "#EAF7EE", "智能层", "多智能体：规划回测方案 → 调度执行 → 评估 → 重试/收敛（默认 Mock）"),
    (60, 470, 1340, 620, "#FFF6E5", "计量层", "特征函数 v(S) · 控制变量/Leave-One-Out · 对齐 Shapley 贡献系数"),
    (60, 650, 1340, 800, "#F3EEFF", "信号层", "公开行情/场景数据 · 因子库（角色决策输入的可计算代理）"),
]
for x0, y0, x1, y1, c, t, desc in layers:
    rounded_rect(d, (x0, y0, x1, y1), c)
    d.text((x0 + 30, y0 + 35), t, font=font(28, True), fill="#111")
    d.text((x0 + 220, y0 + 55), desc, font=body, fill="#333")
d.text(
    (180, 830),
    "直接计量单位：投研角色　　底层工具：因子（套壳表达决策输入）",
    font=small,
    fill="#444",
)
im.save(out / "fig2-1_architecture.png")

# fig2-2
im = Image.new("RGB", (1400, 820), "white")
d = ImageDraw.Draw(im)
d.text((80, 25), "图2-2  仓库模块与调用关系（engine）", font=title, fill="#111")
boxes = [
    (60, 100, 420, 220, "#DDEEFF", "web/\n前端可视化 Demo"),
    (500, 100, 860, 220, "#DDEEFF", "api/\nFastAPI 接口层"),
    (940, 100, 1320, 220, "#DDEEFF", "启动入口\npython -m engine.api.main"),
    (60, 300, 680, 480, "#DFF0D8", "agentic/\nattribution_agent · negotiation\n规划 / 解读 / 协商辅助"),
    (740, 300, 1320, 480, "#FFF2CC", "core/\nbacktest · settlement · calculator\n回测归因 / 确认带宽 / 计算"),
    (60, 540, 1320, 740, "#F5F5F5", "data/scenarios/  场景与先验参数（如 quant_fund）\n默认本地可运行：合成/场景数据 + Mock，不依赖外网 LLM"),
]
for x0, y0, x1, y1, c, t in boxes:
    rounded_rect(d, (x0, y0, x1, y1), c)
    center_text(d, (x0, y0, x1, y1), t, body)
arrow(d, 680, 220, 680, 295)
arrow(d, 1030, 220, 1030, 295)
d.text((280, 760), "浏览器 → API → agentic/core；确认接口走 settlement 带宽规则", font=small, fill="#555")
im.save(out / "fig2-2_modules.png")

# fig5-1
im = Image.new("RGB", (1300, 760), "white")
d = ImageDraw.Draw(im)
d.text((60, 25), "图5-1  从角色边际贡献到 Shapley 贡献系数（示意）", font=title, fill="#111")
steps = [
    (50, 120, 400, 360, "#E8F4FC", "① 角色集合 N\n行业/个股/策略/\n量化/风控 …"),
    (450, 120, 800, 360, "#FFF6E5", "② 特征函数 v(S)\n保留子集 S 的\n决策输入时的价值"),
    (850, 120, 1200, 360, "#EAF7EE", "③ Shapley φᵢ\n对所有联盟顺序\n平均边际贡献"),
]
for x0, y0, x1, y1, c, t in steps:
    rounded_rect(d, (x0, y0, x1, y1), c)
    center_text(d, (x0, y0, x1, y1), t, body)
arrow(d, 405, 240, 445, 240)
arrow(d, 805, 240, 845, 240)
rounded_rect(d, (50, 420, 1200, 700), "#FAFAFA", outline="#888888")
d.text((480, 450), "工程落地（当前）", font=font(28, True), fill="#111")
note = (
    "完整 Shapley 需 O(2ⁿ) 次反事实回测。\n"
    "现阶段以控制变量 / Leave-One-Out 估计边际贡献，并归一为角色贡献系数；\n"
    "Shapley 作为公理化目标（有效性、对称性等），可用蒙特卡洛采样逼近。"
)
center_text(d, (80, 500, 1170, 680), note, small, "#333")
im.save(out / "fig5-1_shapley.png")

# fig5-3
im = Image.new("RGB", (1300, 680), "white")
d = ImageDraw.Draw(im)
d.text((60, 25), "图5-3  Leave-One-Out 与 Shapley 的衔接关系", font=title, fill="#111")
rounded_rect(d, (60, 120, 600, 520), "#FFF6E5")
rounded_rect(d, (700, 120, 1240, 520), "#EAF7EE")
center_text(d, (60, 140, 600, 220), "Leave-One-Out / 控制变量", font(28, True))
center_text(
    d,
    (80, 230, 580, 500),
    "固定其他角色，去掉角色 i\n观察组合收益变化\n→ 边际贡献 MPᵢ\n计算量：约 n 次回测\n适合工程快速估计",
    body,
)
center_text(d, (700, 140, 1240, 220), "Shapley 值", font(28, True))
center_text(
    d,
    (720, 230, 1220, 500),
    "对所有加入顺序平均\n角色 i 的边际贡献\n→ 公理化贡献系数 φᵢ\n精确：O(2ⁿ)；可近似采样\n适合作为理论目标与终态",
    body,
)
arrow(d, 610, 320, 690, 320)
d.text((180, 560), "文档口径：LOO 是可运行的工程近似；Shapley 是贡献计量的公理化目标。", font=small, fill="#444")
im.save(out / "fig5-3_loo_shapley.png")

# fig4-3
im = Image.new("RGB", (1200, 620), "white")
d = ImageDraw.Draw(im)
d.text((40, 25), "图4-3  Agent 推理的 Mock / LLM 切换（可运行性保障）", font=title, fill="#111")
rounded_rect(d, (60, 160, 340, 420), "#E8F4FC")
center_text(d, (60, 160, 340, 420), "请求\n规划 / 解读", body)
rounded_rect(d, (420, 160, 720, 420), "#FFF6E5")
center_text(d, (420, 160, 720, 420), "模式开关\ndefault: mock\n可选: llm", body)
rounded_rect(d, (800, 120, 1140, 300), "#EAF7EE")
center_text(d, (800, 120, 1140, 300), "Mock\n稳定本地输出", body)
rounded_rect(d, (800, 340, 1140, 520), "#F0F0F0", outline="#888888")
center_text(d, (800, 340, 1140, 520), "LLM（可选）\n需密钥/外网", body)
arrow(d, 350, 290, 410, 290)
arrow(d, 730, 260, 790, 220)
arrow(d, 730, 320, 790, 400)
d.text((120, 560), "评审标准环境默认走 Mock，保证可运行性测试不因外网失败。", font=small, fill="#444")
im.save(out / "fig4-3_mock.png")

# fig1-1
im = Image.new("RGB", (1500, 480), "white")
d = ImageDraw.Draw(im)
d.text((60, 20), "图1-1  解题思路总流程", font=title, fill="#111")
items = [
    (40, "#E8F4FC", "定义\n投研角色"),
    (330, "#F3EEFF", "因子套壳\n表达决策输入"),
    (620, "#EAF7EE", "Agent规划\n反事实/对照回测"),
    (910, "#FFF6E5", "贡献系数\n(LOO→Shapley)"),
    (1200, "#FCE8E8", "可视化\n+人工确认"),
]
for x, c, t in items:
    rounded_rect(d, (x, 120, x + 250, 340), c)
    center_text(d, (x, 120, x + 250, 340), t, body)
for x in [290, 580, 870, 1160]:
    arrow(d, x, 230, x + 35, 230)
d.text((280, 400), "计量对象是角色；因子是更底层的决策输入代理。", font=small, fill="#444")
im.save(out / "fig1-1_pipeline.png")

print("ok", [p.name for p in out.glob("*.png")])
