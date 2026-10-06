# AlphaMaxxin

[English](README.md) · **简体中文**

一个本地运行的投资研究工作台。Python 从数据源计算技术面、基本面、宏观、风险
与催化剂指标，再由一组 AI「分析师视角」解读所提供的信息，形成结构化研究报告，
覆盖你的**投资组合**、任意**单只标的**或
**自选清单**。持仓可从 moomoo / IBKR / Tiger 实时同步（**只读**）。

本项目仍属于实验性研究工具，评分与仓位规则是启发式方法，AI 输出和模型结果
需要独立核实。当前局限见 [研究局限说明](RESEARCH_LIMITATIONS.md)。

> **免责声明：** AlphaMaxxin 是研究与学习工具，不是投资顾问。它的输出——包括
> 价格、目标位以及任何「建议」性质的措辞——都是 AI 辅助分析，**不构成投资建议**，
> 并且可能出错、过时或基于不完整的数据。它不会下单，也不会转移资金；所有投资
> 决定的责任完全在你自己。请自担风险，并在依据其输出采取行动前咨询持牌的
> 财务顾问。

## 架构（v2）

```
数据源 ──▶ 确定性技能 ──▶ 分析师视角 ──▶ 一次综合调用
(免费 API)  (纯 Python，零成本)  (廉价 LLM，输入 JSON)   (撰写报告)
```

1. **技能层**（纯 Python，零 AI 成本）：RSI / MACD / 布林带 / ATR / 成交量分布、
   估值比率与质量标记、FRED 宏观状态、VaR / Beta / 集中度、财报与 IPO 日历、
   市场筛选、新闻摘要、国会议员交易查询、基于 ATR 止损的仓位测算。
2. **分析师视角**（每个视角一次廉价 LLM 调用）：宏观、基本面、技术面与期权、
   新闻与催化剂、风险、盘口与流动性、ML Alpha。每个视角只接收技能层输出的
   紧凑 JSON，提示词要求使用已有数字并如实报告缺失数据。AI 输出仍需对照来源核实。
   没有可用免费数据源的视角会保持**停用**（而不是删除），并在报告的覆盖度
   章节中标注为关闭，不消耗任何 token。
3. **综合层**（一次更高级别的调用）：把各视角合成为可决策的报告——结论、
   建议表格、逐视角论据、明确的**冲突点**，以及一个说明报告**没能看到什么**
   的覆盖度章节。

报告费用取决于所选模型、启用的视角与服务商定价。24 小时内的相同请求可使用
本地响应缓存，成本计量器会估算服务商调用的用量。

## Codex 与 Claude Code 研究技能

仓库的 [`.agents/skills`](.agents/skills/README.md) 包含十个可复用的研究技能，
覆盖宏观、基本面、市场信号、催化剂、量化验证与组合风险。可按
[独立安装指南](INSTALL_SKILLS.md) 下载技能包，无需安装应用。
Codex 使用 `$alpha-macro` 或 `$alpha-research`；Claude Code 插件使用
`/alphamaxx-research:alpha-macro` 或 `/alphamaxx-research:alpha-research`。
这些是智能体研究指引，
与应用内的 Python 计算技能和分析流程分别运行。

## 设计取向

- **只读券商访问。** 同步持仓与行情，不含任何下单代码路径。
- **数字由 Python 算，AI 只负责解读。** 视角层拿到的是算好的 JSON，
  它的职责是解释，不是计算。
- **诚实地报告盲区。** 每份报告都列出未覆盖的内容，而不是用沉默掩盖。

## 快速开始

1. 安装 [Python 3.11 或更新版本](https://www.python.org/downloads/)（Windows 上记得勾选
   **Add Python to PATH**）与 [Node.js 24](https://nodejs.org)（用于网页界面）。
2. 下载本项目（绿色 **Code** 按钮 → **Download ZIP** 后解压，或 `git clone`）。
3. 按 [README.md](README.md) 的 Quickstart 完成其余步骤：安装依赖、
   填写 `.env`、启动前后端。

详细的安装、券商连接与配置说明以英文 README 为准；本文档介绍的是项目的
定位与工作原理。

## 本地运行与数据处理

`python run.py` 默认仅监听 `127.0.0.1:8000`。API 没有用户认证，供个人在本机
使用；不要将它作为互联网服务公开。详见 [安全与数据处理](SECURITY.md)。

`.env`、`Portfolio.md`、`external_holdings.json`、生成的报告与 `data_store/`
会被 Git 忽略，避免个人信息进入常规提交。这不代表数据始终留在本机：行情服务商
会收到查询请求；使用云端 AI 生成报告时，所选服务商会收到计算后的组合上下文，
可能包括标的、数量、成本、市值与权重。本地模型则在你配置的端点地址处理这些数据。

## 可选的 moomoo 智能体工具

AlphaMaxxin 直接使用 Python SDK，同步持仓和读取行情，无需安装 moomoo 的
智能体技能。本项目不再捆绑这些第三方文件。如需独立使用，请按
[Moomoo Agent Hub 官方指南](https://github.com/MoomooOpen/moomoo-agent-hub#quick-start)
安装到个人智能体环境。官方工具支持下单、改单与撤单，其能力不属于本应用的只读
券商接口。来源与许可说明见 [第三方说明](THIRD_PARTY_NOTICES.md)。

## 测试

在 `backend/` 运行 `python -m pytest -q`；测试使用固定数据与模拟服务商，
`ALPHAMAXXIN_OFFLINE=1` 会阻止真实服务调用。仓库根目录的
`python run.py --check` 可检查离线启动。前端在 `frontend/` 执行 `npm ci`
与 `npm run build`（Windows PowerShell 使用 `npm.cmd`）。安装依赖需要网络；
这些检查不验证真实券商连接或模型响应。开发与 CI 不调用付费 API。
详见 [贡献指南](CONTRIBUTING.md)。

## 许可

项目原创代码采用 [MIT](LICENSE) 许可。依赖与可选厂商工具保留各自的许可，
见 [第三方说明](THIRD_PARTY_NOTICES.md)。
