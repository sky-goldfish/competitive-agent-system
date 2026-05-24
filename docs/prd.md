# AI全栈挑战赛：竞品分析 Agent 协作系统 PRD

## 1. 文档信息

- 项目名称：AI 驱动的竞品分析 Agent 协作系统
- 文档类型：PRD / 产品需求文档
- 适用阶段：MVP 开发与 Codex 代码生成
- 首版 demo 对象：企业 SaaS、通用产品、通用商品
- Agent 框架：LangGraph
- 技术栈建议：React + Vite + TypeScript + Tailwind CSS + shadcn/ui + FastAPI + SQLite + LangGraph
- 当前版本：v0.2

---

## 2. 项目背景

集团信息系统部负责企业内部信息系统建设，覆盖人事、财务、法务、采购、审批、职场等多个领域，同时也持续关注安全、隐私、合规和 AIGC 创新落地。

在企业产品团队中，竞品分析是一类高频且重复的工作。一次完整竞品分析通常包含：

1. 明确目标产品或产品想法
2. 搜索并识别可能的竞品
3. 收集竞品公开资料
4. 对比功能、定位、用户、价格、口碑等维度
5. 整理 SWOT 和关键洞察
6. 输出结构化报告

传统流程高度依赖人工搜索、人工整理和人工判断，存在以下问题：

- 信息源分散，搜索和整理成本高
- 分析维度不稳定，不同人产出的报告结构差异大
- 结论来源不透明，难以追溯
- 重复劳动多，报告复用性低
- 对分析人员行业认知要求较高

本项目希望通过多 Agent 协作系统模拟一个“数字调研小组”，自动完成从用户需求理解、竞品发现、公开资料采集、结构化分析到报告生成的完整链路。

---

## 3. 产品目标

### 3.1 一句话定义

一个面向企业 SaaS、通用产品和商品分析场景的多 Agent 竞品分析系统。用户只需输入已有产品名称或想做的产品描述，系统即可自动发现候选竞品，经过用户确认后采集公开资料，完成结构化对比分析，并生成带来源证据的竞品分析报告。

### 3.2 核心目标

1. 降低竞品分析的信息搜集成本
2. 提高竞品报告结构化程度
3. 让分析结论具备来源支撑和可追溯性
4. 通过人在环确认机制降低自动竞品发现跑偏风险
5. 通过 LangGraph 展示清晰的 Agent 协作流程
6. 为后续加入质检 Agent、反馈闭环和企业知识库集成预留空间

### 3.3 MVP 成功标准

MVP 跑通后，应当能够完成：

- 用户输入一个已有产品或产品想法
- 系统理解输入并生成标准化分析任务
- 系统自动推荐 3-5 个候选竞品
- 用户确认、删除或补充竞品
- 系统采集目标产品和竞品的公开资料
- 系统按固定维度完成结构化对比分析
- 系统生成 Markdown 格式竞品分析报告
- 报告中的关键结论能够关联来源证据
- 页面展示 Agent 执行流程、状态、来源数量和最终报告

---

## 4. 用户画像与使用场景

### 4.1 目标用户

1. 企业产品经理
   - 需要调研竞品功能、定位、差异化和机会点

2. 企业战略 / 市场分析人员
   - 需要快速了解某一赛道主要玩家与市场格局

3. 创新孵化团队
   - 有一个产品想法，需要判断市场中已有相似方案

4. 运营 / 商业分析人员
   - 需要分析同类商品、服务或品牌的打法

5. 企业内部信息系统团队
   - 需要分析 SaaS、办公系统、流程工具和 AI 工具的功能与企业适配度

### 4.2 典型使用场景

#### 场景 A：已有产品竞品分析

用户输入：

> 帮我分析 Notion AI 的竞品。

系统流程：

1. 判断目标产品为 Notion AI
2. 搜索 Notion AI 相关信息
3. 推断其所属领域为 AI productivity / knowledge management
4. 推荐候选竞品，如 Coda AI、Confluence AI、ClickUp AI、Mem、飞书知识问答等
5. 用户选择其中 2-3 个竞品
6. 系统采集资料并生成报告

#### 场景 B：产品想法竞品分析

用户输入：

> 我想做一个面向中小企业的 AI 自动竞品分析工具，可以自动搜索公开资料并生成报告。

系统流程：

1. 判断输入类型为 product_idea
2. 抽取目标用户、核心能力和应用场景
3. 搜索相关市场和工具
4. 推荐候选竞品，如 Perplexity、ChatGPT Deep Research、Similarweb、Genspark、Manus 等
5. 用户确认竞品
6. 系统采集和分析资料，生成报告

#### 场景 C：通用商品竞品分析

用户输入：

> 帮我分析一款面向办公室人群的智能保温杯可能有哪些竞品。

系统流程：

1. 判断输入为商品想法
2. 抽取商品类别、目标用户和核心卖点
3. 推荐同类智能杯、传统保温杯、高端办公水杯等竞品
4. 采集公开信息，如商品描述、价格、卖点、用户评论
5. 输出商品定位、价格带、卖点和用户痛点分析

---

## 5. 核心概念定义

### 5.1 竞品

竞品不是简单的同类产品，而是在某一明确业务场景下，与目标对象争夺相同用户需求、预算、时间、注意力或决策资源的产品、服务、商品、平台或替代工作流。

竞品类型包括：

1. 直接竞品
   - 产品形态、目标用户和核心功能高度相似

2. 间接竞品
   - 产品形态不同，但解决相似需求

3. 替代方案
   - 用户当前用来完成同一任务的人工流程、组合工具或传统方案

### 5.2 来源 Source

来源是采集 Agent 获取信息的原始出处。

常见来源类型：

- 官方网站
- 官方文档
- 价格页
- 帮助中心
- 应用商店
- 电商平台页面
- 新闻报道
- 行业报告
- 用户评论
- 社区讨论
- 用户手动补充资料

### 5.3 证据 Evidence

Evidence 是从 source 中提取出的可支撑分析结论的片段或摘要。

每个 evidence 至少包含：

- evidence_id
- source_id
- quote
- summary
- related_product
- related_dimension
- confidence

### 5.4 人在环 Human-in-the-loop

人在环是指系统在关键决策节点让用户参与确认。

MVP 中的人在环节点为：

- 系统推荐候选竞品后，用户需要确认最终分析对象
- 用户可以删除不相关竞品
- 用户可以手动添加系统未发现的竞品

该设计用于提高企业场景中的可控性和可信度。

### 5.5 Agent 协作

Agent 协作是指不同 Agent 基于明确职责和结构化输入输出完成任务流转。

MVP 中的 Agent 包括：

- 需求理解 Agent
- 采集 Agent
- 分析师 Agent
- 报告撰写 Agent

质检 Agent 作为 P1 能力预留。

---

## 6. 产品整体流程

```text
用户输入产品名称或产品描述
  ↓
需求理解 Agent
  ↓
采集 Agent：目标理解与候选竞品发现
  ↓
用户确认竞品
  ↓
采集 Agent：目标产品与竞品资料采集
  ↓
分析师 Agent：结构化对比分析
  ↓
报告撰写 Agent：生成完整报告
  ↓
报告展示：结论、表格、来源证据
```

---

## 7. Agent 角色与职责

### 7.1 需求理解 Agent

#### 职责

- 理解用户输入
- 判断输入类型
- 抽取目标产品或产品想法
- 抽取目标用户、核心能力、使用场景
- 判断是否需要追问
- 生成标准化 analysis task

#### 输入

```json
{
  "user_input": "我想做一个面向中小企业的 AI 自动竞品分析工具"
}
```

#### 输出

```json
{
  "input_type": "product_idea",
  "target_product": null,
  "product_description": "面向中小企业的 AI 自动竞品分析工具",
  "target_users": ["中小企业", "产品经理", "市场分析人员"],
  "core_capabilities": ["竞品发现", "公开资料采集", "结构化报告生成"],
  "market_category": "AI research agent / market intelligence tool",
  "needs_clarification": false,
  "clarification_questions": []
}
```

---

### 7.2 采集 Agent

采集 Agent 包含两个阶段：

1. 竞品发现
2. 资料采集

#### 阶段一：竞品发现

职责：

- 调用搜索���务搜索目标产品或产品想法
- 判断目标对象所属赛道
- 识别候选竞品
- 输出候选竞品列表、推荐理由和置信度

输出示例：

```json
{
  "candidate_competitors": [
    {
      "name": "Perplexity",
      "type": "indirect_competitor",
      "reason": "提供 AI 搜索和研究能力，可替代部分人工调研流程",
      "confidence": 0.82
    },
    {
      "name": "ChatGPT Deep Research",
      "type": "direct_or_adjacent_competitor",
      "reason": "支持自动化深度研究和报告生成",
      "confidence": 0.9
    }
  ]
}
```

#### 阶段二：资料采集

职责：

- 对目标产品和用户确认后的竞品进行资料搜索
- 采集公开来源信息
- 提取可用于分析的事实和证据
- 为每条来源计算来源权重
- 为每条 evidence 记录关联维度
- 标记信息缺失、冲突和低可信内容

采集范围：

1. 基础信息
   - 产品名称
   - 所属公司
   - 官网
   - 所在行业
   - 一句话定位
   - 目标用户

2. 功能信息
   - 核心功能
   - 特色能力
   - 支持平台
   - 集成能力
   - API 或生态

3. 价格与商业模式
   - 免费版
   - 订阅价格
   - 企业版
   - 计费单位
   - 商品价格带
   - 增值服务

4. 用户评价
   - 正面评价
   - 负面评价
   - 高频需求
   - 高频问题
   - 情绪倾向

5. 市场与传播
   - 新闻报道
   - 官方博客
   - 版本更新
   - 媒体测评
   - 行业报告摘要

6. 证据
   - 来源标题
   - 来源 URL
   - 引用片段
   - 摘要
   - 关联维度

---

### 7.3 分析师 Agent

#### 职责

- 接收采集 Agent 的结构化材料包
- 按固定分析维度对齐不同竞品
- 根据来源权重和 evidence confidence 进行综合判断
- 输出结构化对比结果
- 输出 SWOT
- 输出关键洞察、机会点和风险点
- 确保每条关键结论绑定 evidence_ids

#### 分析维度

MVP 固定维度：

1. 产品定位
2. 目标用户
3. 核心功能
4. 价格与商业模式
5. 用户评价与痛点
6. 差异化优势
7. 风险与机会

#### 来源权重建议

| 来源类型 | 权重 |
|---|---:|
| 官方网站 / 官方文档 / 价格页 | 0.95 |
| 权威媒体 / 行业报告 | 0.85 |
| 应用商店 / 电商平台评论 | 0.75 |
| 产品社区 / 用户论坛 | 0.7 |
| 社交媒体讨论 | 0.6 |
| 用户手动补充资料 | 0.5-0.8 |
| 无明确来源文本 | 0.3 |

#### 输出示例

```json
{
  "dimension": "价格与商业模式",
  "comparison_summary": "不同产品均采用订阅制，但企业版能力和用量限制差异明显。",
  "product_findings": [
    {
      "product": "Product A",
      "finding": "采用个人订阅和企业订阅双层模式",
      "evidence_ids": ["ev_001", "ev_002"],
      "confidence": 0.9
    }
  ],
  "insights": [
    {
      "title": "企业版能力正在成为 SaaS 产品差异化重点",
      "supporting_evidence_ids": ["ev_011", "ev_018"],
      "confidence": 0.86
    }
  ]
}
```

---

### 7.4 报告撰写 Agent

#### 职责

- 将分析师 Agent 输出的结构化分析结果转成可阅读报告
- 生成执行摘要、对比表、分维度分析、SWOT、机会建议
- 保留来源引用
- 避免生成无 evidence 支撑的关键结论
- 输出 Markdown 报告

#### 报告结构

1. 执行摘要
2. 分析任务说明
3. 目标产品与竞品范围
4. 竞品基础画像表
5. 分维度对比分析
6. SWOT 分析
7. 核心洞察
8. 机会点与建议
9. 信息来源与证据列表
10. 数据局限性说明

---

### 7.5 质检 Agent，P1 预留

MVP 暂不实现独立质检 Agent，但在架构中预留节点。

P1 中质检 Agent 可负责：

- 检查报告结论是否有 evidence 支撑
- 检查各维度是否覆盖充分
- 检查来源是否过度依赖低可信资料
- 检查是否存在明显幻觉或无来源判断
- 对不合格环节进行打回

---

## 8. LangGraph 工作流设计

### 8.1 MVP Graph 节点

```text
START
  ↓
requirement_understanding
  ↓
competitor_discovery
  ↓
human_confirm_competitors
  ↓
material_collection
  ↓
structured_analysis
  ↓
report_generation
  ↓
END
```

### 8.2 节点说明

| 节点 | 对应 Agent / 功能 | 是否自动 |
|---|---|---|
| requirement_understanding | 需求理解 Agent | 自动 |
| competitor_discovery | 采集 Agent：竞品发现 | 自动 |
| human_confirm_competitors | 用户确认竞品 | 人在环 |
| material_collection | 采集 Agent：资料采集 | 自动 |
| structured_analysis | 分析师 Agent | 自动 |
| report_generation | 报告撰写 Agent | 自动 |

### 8.3 状态定义

每个节点状态包括：

- pending
- running
- waiting_for_user
- success
- failed
- skipped

### 8.4 人在环中断机制

当 graph 执行到 human_confirm_competitors 节点时：

1. 后端保存当前 graph state
2. 前端展示候选竞品列表
3. 用户勾选、删除或新增竞品
4. 用户点击“开始深度分析”
5. 后端恢复 graph state，继续执行 material_collection

---

## 9. 页面与交互设计

### 9.1 首页 / 对话输入页

功能：

- 输入已有产品名称
- 输入产品想法描述
- 选择分析类型
- 选择分析深度，MVP 可固定为标准分析
- 提交分析任务

示例输入：

```text
帮我分析 Notion AI 的竞品。
```

```text
我想做一个面向中小企业的 AI 自动竞品分析工具，可以自动搜索公开资料并生成报告。
```

---

### 9.2 竞品确认页

功能：

- 展示系统推荐的 3-5 个候选竞品
- 展示每个竞品的类型、推荐理由、置信度
- 支持用户勾选竞品
- 支持删除竞品
- 支持手动新增竞品
- 点击按钮进入深度分析

推荐字段：

- 产品名称
- 竞品类型
- 推荐理由
- 置信度
- 是否选中

---

### 9.3 任务执行页

布局建议：

```text
┌──────────────────────────────────────────────┐
│ 顶部：任务名称 / 当前状态                      │
├──────────────┬──────────────┬────────────────┤
│ 左侧对话区    │ 中间 Agent 流程 │ 右侧结果预览    │
│ 用户输入      │ 需求理解       │ 当前步骤输出     │
│ 系统回复      │ 竞品发现       │ 来源数量         │
│ 用户确认      │ 竞品确认       │ evidence 数量    │
│              │ 资料采集       │ 报告预览         │
│              │ 分析中         │                │
│              │ 报告生成       │                │
└──────────────┴──────────────┴────────────────┘
```

---

### 9.4 报告页

功能：

- Markdown 报告展示
- 对比表展示
- 来源证据列表
- 点击 evidence 展开 source
- 复制报告
- 重新分析，P1
- 导出 PDF，P1

---

## 10. 数据结构与 Schema

### 10.1 AnalysisTask

```json
{
  "task_id": "task_001",
  "user_input": "帮我分析 Notion AI 的竞品",
  "input_type": "existing_product",
  "target_product": "Notion AI",
  "product_description": null,
  "status": "waiting_for_user",
  "created_at": "2026-05-23T10:00:00Z"
}
```

### 10.2 CompetitorCandidate

```json
{
  "name": "Coda AI",
  "type": "direct_competitor",
  "reason": "同样面向知识管理和协作文档场景提供 AI 能力",
  "confidence": 0.86,
  "selected": true
}
```

### 10.3 Source

```json
{
  "source_id": "src_001",
  "title": "Product Official Pricing Page",
  "url": "https://example.com/pricing",
  "source_type": "official_pricing_page",
  "retrieved_at": "2026-05-23T10:10:00Z",
  "credibility_score": 0.95
}
```

### 10.4 EvidenceItem

```json
{
  "evidence_id": "ev_001",
  "source_id": "src_001",
  "related_product": "Product A",
  "related_dimension": "价格与商业模式",
  "quote": "Pro plan starts at ...",
  "summary": "该产品采用个人订阅和团队订阅模式",
  "confidence": 0.92
}
```

### 10.5 DimensionAnalysis

```json
{
  "dimension": "核心功能",
  "summary": "各竞品均覆盖基础 AI 辅助能力，但在企业协作和自动化深度上存在差异。",
  "findings": [
    {
      "product": "Product A",
      "claim": "具备自动生成报告能力",
      "evidence_ids": ["ev_001", "ev_003"],
      "confidence": 0.88
    }
  ]
}
```

### 10.6 FinalReport

```json
{
  "report_id": "report_001",
  "task_id": "task_001",
  "title": "Notion AI 竞品分析报告",
  "markdown_content": "# Notion AI 竞品分析报告...",
  "evidence_ids": ["ev_001", "ev_002"],
  "created_at": "2026-05-23T10:30:00Z"
}
```

---

## 11. 数据库设计，MVP

建议 SQLite 表：

1. analysis_tasks
2. agent_runs
3. competitor_candidates
4. selected_competitors
5. sources
6. evidence_items
7. dimension_analyses
8. final_reports

### 11.1 agent_runs

用于展示 Agent trace。

字段建议：

- id
- task_id
- node_name
- agent_name
- status
- input_summary
- output_summary
- started_at
- ended_at
- error_message

---

## 12. 技术架构

### 12.1 前端

- React
- Vite
- TypeScript
- Tailwind CSS
- shadcn/ui
- React Router
- Markdown renderer

### 12.2 后端

- FastAPI
- Python
- LangGraph
- SQLite
- SQLModel 或 SQLAlchemy
- Pydantic

### 12.3 外部能力抽象

#### LLM Provider

需要抽象统一接口，避免业务代码绑定具体模型。

```python
class LLMProvider:
    async def generate_text(self, prompt: str) -> str:
        ...

    async def generate_json(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        ...
```

#### Search Provider

```python
class SearchProvider:
    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        ...
```

MVP 至少支持：

- RealSearchProvider
- MockSearchProvider

MockSearchProvider 用于 demo 兜底。

---

## 13. 目录结构建议

```text
frontend/
  src/
    pages/
      HomePage.tsx
      CompetitorConfirmPage.tsx
      TaskRunPage.tsx
      ReportPage.tsx
    components/
      ChatInput.tsx
      AgentTimeline.tsx
      CompetitorCard.tsx
      ReportViewer.tsx
      SourceDrawer.tsx
    api/
      client.ts
    types/
      schema.ts

backend/
  app/
    main.py
    api/
      tasks.py
      competitors.py
      reports.py
    graph/
      workflow.py
      state.py
      nodes.py
    agents/
      requirement_agent.py
      collection_agent.py
      analyst_agent.py
      report_agent.py
    services/
      llm_service.py
      search_service.py
      source_weighting.py
      evidence_service.py
    schemas/
      task.py
      competitor.py
      source.py
      evidence.py
      analysis.py
      report.py
    db/
      models.py
      session.py
    mock/
      demo_search_results.json
```

---

## 14. API 设计

### 14.1 创建分析任务

```http
POST /api/tasks
```

请求：

```json
{
  "user_input": "帮我分析 Notion AI 的竞品"
}
```

响应：

```json
{
  "task_id": "task_001",
  "status": "running"
}
```

### 14.2 获取任务状态

```http
GET /api/tasks/{task_id}
```

### 14.3 获取候选竞品

```http
GET /api/tasks/{task_id}/competitor-candidates
```

### 14.4 确认竞品

```http
POST /api/tasks/{task_id}/confirm-competitors
```

请求：

```json
{
  "selected_competitors": ["Coda AI", "Confluence AI"],
  "custom_competitors": ["飞书知识问答"]
}
```

### 14.5 获取 Agent 执行记录

```http
GET /api/tasks/{task_id}/agent-runs
```

### 14.6 获取报告

```http
GET /api/tasks/{task_id}/report
```

### 14.7 获取来源证据

```http
GET /api/tasks/{task_id}/evidence
```

---

## 15. MVP 功能清单

### 必做

- 对话式输入
- 需求理解 Agent
- 竞品发现
- 用户确认竞品
- 资料采集
- 来源权重计算
- evidence 生成
- 结构化分析
- Markdown 报告生成
- Agent Timeline 展示
- 来源证据展示
- Mock 搜索兜底

### 暂不做

- 登录 / 权限
- 多用户协作
- PDF 导出
- 定时监控
- 自动邮件发送
- 复杂数据可视化
- 第三方付费平台接入
- 独立质检 Agent
- 自动打回重跑

---

## 16. 非功能需求

### 16.1 稳定性

- 外部搜索失败时使用 mock 数据或提示用户重试
- LLM 输出 JSON 失败时需要 retry 一次
- 单个来源解析失败不能导致整个任务失败

### 16.2 可追溯性

- 每条关键结论必须尽量绑定 evidence_ids
- 每条 evidence 必须绑定 source_id
- 报告页应允许用户查看来源列表

### 16.3 可观察性

- 每个 LangGraph 节点需要记录 agent_run
- 前端展示节点状态、开始时间、结束时间、输出摘要

### 16.4 合规性

- 仅采集公开信息和用户主动提供资料
- 不绕过登录、验证码、权限或付费墙
- 不采集隐私数据
- 报告中需要标注数据局限性

---

## 17. Codex 开发任务拆解

### 第一阶段：项目骨架

1. 创建 frontend React + Vite 项目
2. 创建 backend FastAPI 项目
3. 配置 SQLite 和 ORM
4. 定义 Pydantic schemas
5. 定义基础 API 路由

### 第二阶段：LangGraph 工作流

1. 定义 graph state
2. 创建 requirement_understanding 节点
3. 创建 competitor_discovery 节点
4. 创建 human_confirm_competitors 中断节点
5. 创建 material_collection 节点
6. 创建 structured_analysis 节点
7. 创建 report_generation 节点
8. 将节点执行记录写入 agent_runs

### 第三阶段：Agent 实现

1. 实现 LLM Provider 抽象
2. 实现 Search Provider 抽象
3. 实现 MockSearchProvider
4. 实现需求理解 Agent
5. 实现采集 Agent
6. 实现分析师 Agent
7. 实现报告撰写 Agent

### 第四阶段：前端页面

1. 首页输入框
2. 竞品确认页
3. 任务执行页
4. Agent Timeline 组件
5. 报告展示组件
6. Source / Evidence 展开组件

### 第五阶段：联调与 demo 数据

1. 准备企业 SaaS demo 样例
2. 准备通用商品 demo 样例
3. 接通完整链路
4. 测试搜索失败 fallback
5. 测试用户确认竞品后 graph 继续执行
6. 准备答辩演示脚本

---

## 18. 验收标准

### 18.1 功能验收

- 输入产品或产品想法后，系统能生成候选竞品
- 用户能确认、删除和新增竞品
- 确认后系统能继续执行分析流程
- 系统能生成结构化报告
- 报告包含来源证据
- Agent 执行过程可见

### 18.2 报告验收

报告必须包含：

- 执行摘要
- 竞品范围
- 基础画像表
- 分维度对比
- SWOT
- 核心洞察
- 机会建议
- 来源证据
- 数据局限性说明

### 18.3 技术验收

- 后端使用 FastAPI
- Agent workflow 使用 LangGraph
- 数据持久化使用 SQLite
- 前端使用 React + TypeScript
- 有 mock search fallback
- Agent run trace 入库

---

## 19. 后续迭代计划

### P1

- 增加质检 Agent
- 增加 QC 打回与自动修订
- 增加 PDF 导出
- 增加用户上传资料
- 增加更多分析模板
- 增加报告编辑功能

### P2

- 企业知识库接入
- 多任务管理
- 团队协作
- 定时竞品监控
- 历史报告对比
- 多语言竞品分析

---

## 20. 当前版本总结

本 PRD 的核心取舍是：

1. 首版聚焦企业 SaaS、通用产品和商品分析，不绑定单一平台
2. 保留用户确认竞品的人在环步骤，增强企业场景可控性
3. MVP 暂不实现质检 Agent��但在 LangGraph 架构中预留后续扩展
4. 技术栈采用 FastAPI + React + SQLite + LangGraph
5. 重点展示真实 Agent 协作、结构化分析和来源可追溯，而不是堆砌功能

最终目标是做出一个可以在比赛答辩中讲清楚、跑得通、看得见、信得过的竞品分析 Agent 协作系统。



---

## 21. 搜索引擎、网页抓取与多源资料采集增强

### 21.1 背景与问题

竞品分析报告的质量高度依赖搜索与资料采集质量。当前 MVP 已经具备基础 Search Provider、来源分类、来源权重和证据链展示能力，但如果只依赖单一搜索引擎或简单关键词搜索，仍然容易出现以下问题：

1. 候选竞品召回不全，尤其是跨语言、跨地区、跨品类时更明显。
2. 搜索结果可能混入同名但不同品类的品牌、SEO 聚合页、百科页或低质量转载页。
3. 不同来源的可信度差异没有充分体现，例如官网、电商评价、社交平台评论不应该被同等对待。
4. 资料采集角度可能不均衡，例如只采到官网介绍，缺少价格、用户评价、社区讨论和专业测评。
5. 搜索结果通常只有 title 和 snippet，不足以支撑高质量 evidence，需要进一步抽取网页正文。
6. 最终报告需要解释结论来自哪类来源，否则用户难以判断可信度。

因此，搜索模块不应只是“调用搜索引擎拿前 N 条结果”，而应升级为：

```text
多阶段 query planning
  ↓
多搜索引擎 / 多 Provider 召回
  ↓
URL 去重与域名过滤
  ↓
来源类型分类
  ↓
来源权重与维度匹配重排序
  ↓
网页正文抽取
  ↓
Evidence 抽取与报告引用
```

### 21.2 搜索能力目标

搜索与资料采集模块需要支持以下能力：

1. 多阶段搜索
   - 目标理解搜索：理解目标产品或产品想法的定位、用户和核心能力。
   - 竞品发现搜索：发现直接竞品、间接竞品和替代方案。
   - 资料采集搜索：围绕已确认竞品按分析维度采集资料。
   - 官网解析搜索：尽可能解析候选竞品的官方站点。

2. 多角度资料采集
   - 产品定位。
   - 核心功能。
   - 价格与商业模式。
   - 用户评价与痛点。
   - 差异化机会。
   - 风险、限制与负面反馈。

3. 多 Provider 支持
   - 当前 MVP 可继续保留 DuckDuckGo 或 Mock Search。
   - 后续支持 Tavily、Exa、Brave Search、SerpAPI / Serper 等搜索 Provider。
   - 支持 CompositeSearchProvider 对多个搜索源进行融合。

4. 网页正文抽取
   - 搜索结果只提供标题和摘要，不足以支撑高质量证据。
   - 后续应支持 Jina Reader、Firecrawl 或 Browser / Playwright 抽取网页正文。
   - 对动态网页、电商详情页、评价页，可使用浏览器自动化作为 fallback。

5. 来源分类与权重重排序
   - 系统需要识别来源类型。
   - 不同来源类型赋予不同可信度权重。
   - 召回结果进入证据抽取前，需要按权重和维度匹配度重排序。
   - 最终展示时，需要明确标注来源类型、权重和分类原因。

### 21.3 推荐搜索 Provider 规划

#### 21.3.1 MVP 已有 Provider

| Provider | 作用 | 说明 |
|---|---|---|
| MockSearchProvider | 本地测试和 demo | 提供稳定、可控的 mock 结果 |
| DuckDuckGoSearchProvider | 真实搜索 MVP | 无需 API key，但稳定性和结果质量有限 |

#### 21.3.2 推荐扩展 Provider

| Provider | 定位 | 适用场景 | 优先级 |
|---|---|---|---|
| TavilySearchProvider | AI Agent / RAG 搜索 | 资料采集、带引用研究、报告型搜索 | P0 |
| ExaSearchProvider | 语义搜索 | 海外 SaaS、相似产品发现、文章/榜单发现 | P1 |
| BraveSearchProvider | 独立网页索引 | 稳定通用搜索、海外产品资料 | P1 |
| SerpApiSearchProvider / SerperSearchProvider | 搜索结果页 API | Google / Baidu / Shopping / News 风格搜索 | P2 |
| JinaReaderExtractor | URL 转 Markdown | 网页正文抽取、RAG 资料读取 | P1 |
| FirecrawlExtractor | Search + Crawl + Extract | 网页正文抽取、批量抓取、结构化提取 | P2 |
| BrowserFetchProvider | 浏览器自动化 | JS 渲染页面、电商详情页、动态评价页 | P3 |

### 21.4 CompositeSearchProvider 设计

后续系统应支持组合搜索 Provider：

```text
CompositeSearchProvider
├── query planning
├── provider routing
│   ├── DuckDuckGo
│   ├── Tavily
│   ├── Exa
│   ├── Brave
│   └── SerpAPI / Serper
├── result normalization
├── URL / domain deduplication
├── source classification
├── weighted rerank
└── top-k selection for evidence extraction
```

Provider routing 规则：

| 场景 | 推荐 Provider |
|---|---|
| 海外 SaaS 竞品发现 | Exa + Brave + Tavily |
| 中文 SaaS / 企业软件 | Tavily + DuckDuckGo + 中文搜索源 |
| 商品 / 硬件竞品 | SerpAPI / Shopping + DuckDuckGo + 垂直站点 query |
| 专业测评 / 媒体文章 | Tavily + Brave + Firecrawl |
| 用户评价 / 社区讨论 | SerpAPI / Google-style + 站点定向搜索 |
| 网页正文抽取 | Jina Reader / Firecrawl |
| 动态页面或复杂页面 | Playwright / Browserbase fallback |

### 21.5 Query Planning 策略

系统需要根据产品领域生成不同类型的 query，而不是所有产品共用同一套搜索词。

#### SaaS / 软件类

| 分析维度 | Query 方向 |
|---|---|
| 产品定位 | `{product} official product positioning features` |
| 核心功能 | `{product} docs features integrations platform` |
| 价格与商业模式 | `{product} pricing plans enterprise official` |
| 用户评价与痛点 | `{product} reviews user feedback pros cons G2 Capterra Reddit` |

#### 商品 / 硬件类

| 分析维度 | Query 方向 |
|---|---|
| 产品定位 | `{product} 品牌 官网 商品介绍 参数` |
| 核心功能 | `{product} 功能 参数 测评 使用体验` |
| 价格与商业模式 | `{product} 京东 天猫 淘宝 价格` |
| 用户评价与痛点 | `{product} 用户评价 小红书 知乎 B站 京东 差评` |

#### 市场调研 / 竞品情报类

| 分析维度 | Query 方向 |
|---|---|
| 产品定位 | `{product} official competitive intelligence market research` |
| 核心功能 | `{product} features data sources monitoring reports` |
| 价格与商业模式 | `{product} pricing plans enterprise` |
| 用户评价与痛点 | `{product} reviews alternatives comparison user feedback` |

### 21.6 来源分类与权重体系

系统需要对每条召回结果进行来源分类。分类结果用于：

- 资料重排序。
- Evidence confidence 计算。
- 报告引用说明。
- 前端来源卡片展示。

#### SaaS / 软件类来源

| 来源类型 | source_type | 建议权重 | 适用信息 |
|---|---|---:|---|
| 官网介绍 | official_site | 0.94 | 定位、功能、目标用户 |
| 官方文档 / 帮助中心 | official_docs | 0.92 | 功能细节、集成、使用方式 |
| 官方价格页 | official_pricing_page | 0.93 | 定价、套餐、商业模式 |
| 第三方评价站 | review_site | 0.72 | 用户反馈、优缺点、评分 |
| 社区讨论 | community_discussion | 0.62 | 痛点、真实使用争议、非正式反馈 |
| 社交平台评价 | social_review_post | 0.66 | 用户情绪、传播反馈、案例线索 |
| 新闻 / 媒体报道 | news_article | 0.78 | 市场动态、融资、发布、行业评价 |
| 未分类来源 | unknown | 0.42 | 仅作为低置信线索 |

#### 商品 / 硬件类来源

| 来源类型 | source_type | 建议权重 | 适用信息 |
|---|---|---:|---|
| 品牌官网 / 商品介绍 | brand_official_product_page | 0.95 | 产品定位、功能参数、官方卖点 |
| 电商商品页 | ecommerce_product_page | 0.86 | 价格、规格、销量、渠道信息 |
| 电商用户评价 | ecommerce_user_review | 0.78 | 使用反馈、差评、售后问题 |
| 专业测评 | professional_review | 0.82 | 功能体验、横向对比、专业评价 |
| 社交平台评价 | social_review_post | 0.66 | 小红书 / B站 / 微博等真实体验和情绪 |
| 社区讨论 | community_discussion | 0.62 | 知乎 / 论坛 / 什么值得买等讨论 |
| 电商 / 渠道页 | marketplace_listing_unknown_seller | 0.56 | 非官方销售线索、价格参考 |
| 未分类来源 | unknown | 0.42 | 低置信线索 |

### 21.7 重排序规则

召回结果进入 evidence extraction 前，需要计算综合分：

```text
rank_score = source_type_weight + dimension_match_bonus + domain_quality_bonus - risk_penalty
```

维度匹配加分：

| 分析维度 | 优先来源 |
|---|---|
| 产品定位 | 官网、品牌页、媒体报道、专业测评 |
| 核心功能 | 官网、官方文档、专业测评、商品详情页 |
| 价格与商业模式 | 官方价格页、电商商品页、渠道页 |
| 用户评价与痛点 | 电商评价、第三方评价站、社交平台、社区讨论、专业测评 |

风险扣分：

- URL 域名明显与产品无关。
- 标题命中同名但不同品类品牌。
- 内容来自 SEO 聚合站且缺少一手信息。
- 来源为百科/论坛但被用于定价或官方功能判断。
- 页面不可访问或正文抽取失败。
- 重复 URL 或高度重复内容。

### 21.8 前端展示要求

来源资料卡片需要展示：

- 来源标题。
- URL。
- 摘要。
- 来源类型中文名。
- source_type 原始类型。
- 可信度权重。
- 分类原因。

示例：

```text
Ember Mug 使用体验：办公室恒温杯值不值
来源类型：社交平台评价
权重：66%
分类原因：按领域、域名、标题关键词和“用户评价与痛点”维度匹配为社交平台评价。
```

Evidence 摘要中也应带上来源类型和权重：

```text
[社交平台评价｜权重 0.66] 小红书用户反馈 Ember Mug 保温体验好，但价格高、清洁和续航存在争议。
```

### 21.9 报告生成要求

报告生成 Agent 必须理解来源差异：

- 官网 / 官方文档适合判断定位、功能、定价。
- 电商商品页适合判断商品价格、规格和渠道。
- 电商评价、社交平台、社区讨论适合判断用户痛点和情绪，但不能作为官方事实唯一依据。
- 专业测评适合判断实际体验和横向比较。
- 当不同来源冲突时，优先采用高权重来源，并在报告中说明冲突。

报告的“来源与证据”章节必须包含：

- 来源标题。
- 来源 URL。
- 来源类型。
- 可信度权重。
- 支撑的分析维度。

### 21.10 推荐接入优先级

#### P0：TavilySearchProvider

目标：提升 Agent / RAG 场景搜索质量。

原因：

- Tavily 面向 AI Agent 和 RAG。
- 支持搜索和资料聚合。
- 适合竞品调研与报告型搜索。

#### P1：JinaReaderExtractor

目标：提升网页正文读取能力。

原因：

- 接入成本低。
- 可将 URL 转为 Markdown。
- 适合作为 evidence extraction 的正文输入。

#### P1：CompositeSearchProvider

目标：融合多个搜索源，提升召回质量和稳定性。

需要支持：

- provider 权重。
- 去重。
- source classification。
- weighted rerank。
- fallback。

#### P2：ExaSearchProvider / BraveSearchProvider

目标：增强海外 SaaS 和英文资料搜索。

#### P2：FirecrawlExtractor

目标：增强正文抽取、crawl 和结构化网页提取。

#### P3：Playwright / Browserbase Fallback

目标：处理复杂动态页面、电商详情页和评价页。

### 21.11 验收标准

搜索与资料采集模块应满足：

1. 对每个已确认竞品，至少覆盖 4 个分析维度。
2. 每个维度优先保留 1 到 2 条高质量来源。
3. 每条来源必须包含 source_type、source_type_label、credibility_score 和 classification_reason。
4. Evidence 摘要必须体现来源类型和权重。
5. 商品类场景应至少覆盖以下来源中的 3 类：
   - 品牌官网 / 商品介绍。
   - 电商商品页。
   - 电商用户评价。
   - 社交平台评价。
   - 社区讨论。
   - 专业测评。
6. SaaS 类场景应至少覆盖以下来源中的 3 类：
   - 官网介绍。
   - 官方文档。
   - 官方价格页。
   - 第三方评价站。
   - 社区讨论。
   - 新闻 / 媒体报道。
7. Timeline 中应展示资料采集内部子步骤：
   - 规划资料采集。
   - 搜索来源资料。
   - 分类来源可信度。
   - 抽取证据片段。
   - 检查覆盖度。
8. 最终报告的来源章节必须展示来源类型和权重。

### 21.12 非目标与合规边界

当前阶段不做以下能力：

- 绕过网站反爬、登录、验证码或付费墙。
- 未授权采集私有平台数据。
- 批量抓取受限平台内容。
- 完全自动判断所有来源真实性。
- 替代人工专家判断。

系统应优先使用公开、合规、可访问的来源，并在报告中保留来源链接、来源类型和可信度说明。
