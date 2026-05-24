# 竞品分析 Agent 协作系统 PRD

## 1. 产品目标

构建一个面向通用产品与企业 SaaS 场景的竞品分析 Agent 协作系统。用户输入一个已有产品或产品想法后，系统能够自动理解需求、发现候选竞品、由用户确认竞品、采集多来源资料、抽取证据、生成结构化分析与 Markdown 报告。

系统需要强调：

- 竞品发现结果可解释。
- 资料采集来源可追溯。
- 不同来源类型具备不同可信度权重。
- 用户能够理解 Agent 正在做什么，以及最终报告依据了哪些来源。

## 2. 核心用户流程

1. 用户输入产品或产品想法。
2. Agent 理解目标对象、所属赛道、目标用户和核心能力。
3. Agent 生成多组搜索 query，发现候选竞品。
4. 用户在候选竞品列表中确认、取消或手动补充竞品。
5. Agent 围绕确认后的竞品进行资料采集。
6. Agent 对召回结果进行来源分类、可信度评分和重排序。
7. Agent 从来源中抽取证据片段。
8. Agent 按维度生成竞品分析。
9. Agent 生成最终 Markdown 报告，并展示来源资料与证据链。

## 3. 搜索与资料采集能力

### 3.1 背景与问题

竞品分析质量高度依赖搜索和资料采集质量。单一搜索引擎或简单关键词搜索容易出现以下问题：

- 候选竞品召回不全，尤其跨语言、跨地区、跨品类时更明显。
- 搜索结果混入无关页面，例如同名品牌、资讯聚合页、低质量 SEO 页面。
- 不同来源的可信度差异没有体现，官网、电商评价、社交平台评论被同等对待。
- 资料采集角度不均衡，可能只采到官网介绍，缺少价格、用户评价、社区讨论或专业测评。
- 最终报告无法解释结论来自哪类来源，用户难以判断可信度。

因此，搜索模块不应只是“调用搜索引擎拿前 N 条结果”，而应升级为“多来源召回 + 来源分类 + 权重重排序 + 证据抽取”的资料采集子系统。

### 3.2 能力目标

搜索与资料采集模块需要支持以下能力：

1. **多阶段搜索**
   - 目标理解搜索：理解目标产品/想法的定位、用户和能力。
   - 竞品发现搜索：发现直接竞品、间接竞品和替代方案。
   - 资料采集搜索：围绕已确认竞品按分析维度采集资料。
   - 官网解析搜索：尽可能解析候选竞品的官方站点。

2. **多角度资料采集**
   - 产品定位。
   - 核心功能。
   - 价格与商业模式。
   - 用户评价与痛点。
   - 差异化机会。
   - 风险、限制与负面反馈。

3. **多搜索引擎/多 Provider 支持**
   - 当前 MVP 可使用 DuckDuckGo 或 Mock Search。
   - 后续支持 Tavily、Exa、Brave Search、SerpAPI/Serper 等搜索 Provider。
   - 支持 CompositeSearchProvider 对多个搜索源进行融合。

4. **网页正文抽取**
   - 搜索结果只提供标题和摘要，不足以支撑高质量证据。
   - 后续应支持 Jina Reader、Firecrawl 或 Browser/Playwright 抽取网页正文。
   - 对动态网页、电商详情页、评价页，可使用浏览器自动化作为 fallback。

5. **来源分类与权重重排序**
   - 系统需要识别来源类型。
   - 不同来源类型赋予不同可信度权重。
   - 召回结果进入证据抽取前，需要按权重和维度匹配度重排序。
   - 最终展示时，需要明确标注来源类型和权重。

### 3.3 搜索 Provider 规划

#### 3.3.1 MVP Provider

| Provider | 作用 | 说明 |
| --- | --- | --- |
| MockSearchProvider | 本地测试和 Demo | 提供稳定、可控的 mock 结果 |
| DuckDuckGoSearchProvider | 真实搜索 MVP | 无需 API key，但稳定性和结果质量有限 |

#### 3.3.2 推荐扩展 Provider

| Provider | 定位 | 适用场景 | 优先级 |
| --- | --- | --- | --- |
| TavilySearchProvider | AI Agent/RAG 搜索 | 资料采集、带引用研究、报告型搜索 | P0 |
| ExaSearchProvider | 语义搜索 | 海外 SaaS、相似产品发现、文章/榜单发现 | P1 |
| BraveSearchProvider | 独立网页索引 | 稳定通用搜索、海外产品资料 | P1 |
| SerpApiSearchProvider / SerperSearchProvider | 搜索结果页 API | Google/Baidu/Shopping/News 风格搜索 | P2 |
| JinaSearchProvider | 轻量 Search + Reader | URL 转 Markdown、RAG 资料读取 | P2 |
| FirecrawlSearchProvider | Search + Crawl + Extract | 网页正文抽取、批量抓取、结构化提取 | P2 |
| BrowserSearch/BrowserFetchProvider | 浏览器自动化 | JS 渲染页面、电商详情页、动态评价页 | P3 |

### 3.4 CompositeSearchProvider 设计

后续系统应支持一个组合搜索 Provider：

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
├── URL/domain deduplication
├── source classification
├── weighted rerank
└── top-k selection for evidence extraction
```

#### Provider routing 规则

| 场景 | 推荐 Provider |
| --- | --- |
| 海外 SaaS 竞品发现 | Exa + Brave + Tavily |
| 中文 SaaS/企业软件 | Tavily + DuckDuckGo + 中文搜索源 |
| 商品/硬件竞品 | SerpAPI/Shopping + DuckDuckGo + 垂直站点 query |
| 专业测评/媒体文章 | Tavily + Brave + Firecrawl |
| 用户评价/社区讨论 | SerpAPI/Google-style + 站点定向搜索 |
| 网页正文抽取 | Jina Reader / Firecrawl |
| 动态页面或复杂页面 | Playwright / Browserbase fallback |

### 3.5 Query Planning 策略

系统需要根据产品领域生成不同类型的 query，而不是所有产品共用同一套搜索词。

#### SaaS/软件类

| 分析维度 | Query 方向 |
| --- | --- |
| 产品定位 | `{product} official product positioning features` |
| 核心功能 | `{product} docs features integrations platform` |
| 价格与商业模式 | `{product} pricing plans enterprise official` |
| 用户评价与痛点 | `{product} reviews user feedback pros cons G2 Capterra Reddit` |

#### 商品/硬件类

| 分析维度 | Query 方向 |
| --- | --- |
| 产品定位 | `{product} 品牌 官网 商品介绍 参数` |
| 核心功能 | `{product} 功能 参数 测评 使用体验` |
| 价格与商业模式 | `{product} 京东 天猫 淘宝 价格` |
| 用户评价与痛点 | `{product} 用户评价 小红书 知乎 B站 京东 差评` |

#### 市场调研/竞品情报类

| 分析维度 | Query 方向 |
| --- | --- |
| 产品定位 | `{product} official competitive intelligence market research` |
| 核心功能 | `{product} features data sources monitoring reports` |
| 价格与商业模式 | `{product} pricing plans enterprise` |
| 用户评价与痛点 | `{product} reviews alternatives comparison user feedback` |

### 3.6 来源分类体系

系统需要对每条召回结果进行来源分类。分类结果用于：

- 资料重排序。
- Evidence confidence 计算。
- 报告引用说明。
- 前端来源卡片展示。

#### SaaS/软件类来源

| 来源类型 | source_type | 建议权重 | 适用信息 |
| --- | --- | ---: | --- |
| 官网介绍 | official_site | 0.94 | 定位、功能、目标用户 |
| 官方文档/帮助中心 | official_docs | 0.92 | 功能细节、集成、使用方式 |
| 官方价格页 | official_pricing_page | 0.93 | 定价、套餐、商业模式 |
| 第三方评价站 | review_site | 0.72 | 用户反馈、优缺点、评分 |
| 社区讨论 | community_discussion | 0.62 | 痛点、真实使用争议、非正式反馈 |
| 社交平台评价 | social_review_post | 0.66 | 用户情绪、传播反馈、案例线索 |
| 新闻/媒体报道 | news_article | 0.78 | 市场动态、融资、发布、行业评价 |
| 未分类来源 | unknown | 0.42 | 仅作为低置信线索 |

#### 商品/硬件类来源

| 来源类型 | source_type | 建议权重 | 适用信息 |
| --- | --- | ---: | --- |
| 品牌官网/商品介绍 | brand_official_product_page | 0.95 | 产品定位、功能参数、官方卖点 |
| 电商商品页 | ecommerce_product_page | 0.86 | 价格、规格、销量、渠道信息 |
| 电商用户评价 | ecommerce_user_review | 0.78 | 使用反馈、差评、售后问题 |
| 专业测评 | professional_review | 0.82 | 功能体验、横向对比、专业评价 |
| 社交平台评价 | social_review_post | 0.66 | 小红书/B站/微博等真实体验和情绪 |
| 社区讨论 | community_discussion | 0.62 | 知乎/论坛/什么值得买等讨论 |
| 电商/渠道页 | marketplace_listing_unknown_seller | 0.56 | 非官方销售线索、价格参考 |
| 未分类来源 | unknown | 0.42 | 低置信线索 |

### 3.7 重排序规则

召回结果进入 evidence extraction 前，需要计算综合分：

```text
rank_score = source_type_weight + dimension_match_bonus + domain_quality_bonus - risk_penalty
```

#### 维度匹配加分

| 分析维度 | 优先来源 |
| --- | --- |
| 产品定位 | 官网、品牌页、媒体报道、专业测评 |
| 核心功能 | 官网、官方文档、专业测评、商品详情页 |
| 价格与商业模式 | 官方价格页、电商商品页、渠道页 |
| 用户评价与痛点 | 电商评价、第三方评价站、社交平台、社区讨论、专业测评 |

#### 风险扣分

以下情况需要降低排序或过滤：

- URL 域名明显与产品无关。
- 标题命中同名但不同品类品牌。
- 内容来自 SEO 聚合站且缺少一手信息。
- 来源为百科/论坛但被用于定价或官方功能判断。
- 页面不可访问或正文抽取失败。
- 重复 URL 或高度重复内容。

### 3.8 前端展示要求

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

### 3.9 报告生成要求

报告生成 Agent 必须理解来源差异：

- 官网/官方文档适合判断定位、功能、定价。
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

### 3.10 推荐接入优先级

#### P0：TavilySearchProvider

目标：提升 Agent/RAG 场景搜索质量。

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

#### P3：Playwright/Browserbase Fallback

目标：处理复杂动态页面、电商详情页和评价页。

### 3.11 验收标准

搜索与资料采集模块应满足：

1. 对每个已确认竞品，至少覆盖 4 个分析维度。
2. 每个维度优先保留 1 到 2 条高质量来源。
3. 每条来源必须包含 source_type、source_type_label、credibility_score 和 classification_reason。
4. Evidence 摘要必须体现来源类型和权重。
5. 商品类场景应至少覆盖以下来源中的 3 类：
   - 品牌官网/商品介绍。
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
   - 新闻/媒体报道。
7. Timeline 中应展示资料采集内部子步骤：
   - 规划资料采集。
   - 搜索来源资料。
   - 分类来源可信度。
   - 抽取证据片段。
   - 检查覆盖度。
8. 最终报告的来源章节必须展示来源类型和权重。

## 4. 非目标

当前 MVP 暂不承诺：

- 绕过网站反爬或登录限制。
- 未授权采集私有平台数据。
- 批量抓取受限平台内容。
- 完全自动判断所有来源真实性。
- 替代人工专家判断。

系统应优先使用公开、合规、可访问的来源，并在报告中保留来源链接与可信度说明。
