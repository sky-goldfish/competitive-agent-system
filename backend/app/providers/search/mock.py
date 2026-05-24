from app.providers.search.base import SearchResult


class MockSearchProvider:
    name = "mock"

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        query_lower = query.lower()
        if "ember mug" in query_lower and self._matches(query_lower, ["京东", "天猫", "淘宝", "小红书", "知乎", "b站", "差评", "评价", "测评", "体验", "参数"]):
            results = self._smart_cup_materials(query_lower)
        elif "slack" in query_lower and self._matches(query_lower, ["pricing", "docs", "reviews", "g2", "capterra", "features"]):
            results = self._slack_materials(query_lower)
        elif self._matches(query_lower, ["保温杯", "智能杯", "水杯", "thermos", "mug", "ember"]):
            results = self._smart_cup_tools()
        elif self._matches(query_lower, ["飞书", "feishu", "lark", "协作", "协同", "办公平台", "dingtalk", "wecom", "slack", "teams"]):
            results = self._collaboration_tools()
        elif self._matches(query_lower, ["会议", "meeting", "minutes", "纪要"]):
            results = self._meeting_tools()
        elif self._matches(query_lower, ["crm", "客户", "sales"]):
            results = self._crm_tools()
        elif self._matches(query_lower, ["竞品", "research", "analysis", "调研"]):
            results = self._research_tools()
        else:
            results = self._fallback_tools(query)
        return results[:limit]

    @staticmethod
    def _matches(text: str, keywords: list[str]) -> bool:
        return any(keyword.lower() in text for keyword in keywords)

    @staticmethod
    def _collaboration_tools() -> list[SearchResult]:
        return [
            SearchResult(
                title="钉钉（DingTalk 企业协同办公平台）",
                url="https://example.com/dingtalk",
                snippet="钉钉提供即时沟通、组织管理、文档协作、会议和低代码能力，是飞书在中国企业协作办公市场的直接竞品。",
                raw_content="钉钉围绕企业即时通讯、在线文档、视频会议、审批和组织数字化构建协同办公套件。",
            ),
            SearchResult(
                title="企业微信（WeCom 企业通讯与客户连接平台）",
                url="https://example.com/wecom",
                snippet="企业微信覆盖企业通讯、组织管理、客户联系和办公应用集成，与飞书在企业协作和组织连接场景竞争。",
                raw_content="企业微信提供企业通讯录、群聊、客户联系、会议和第三方应用生态，适合企业办公协作。",
            ),
            SearchResult(
                title="Slack（团队沟通与工作流协作平台）",
                url="https://example.com/slack",
                snippet="Slack 主打频道化沟通、应用集成和自动化工作流，是飞书/Lark 在国际团队协作市场的主要竞品。",
                raw_content="Slack 以团队沟通、频道、应用集成和工作流自动化为核心，服务知识工作者和跨职能团队。",
            ),
            SearchResult(
                title="Microsoft Teams（Microsoft 365 协作与会议平台）",
                url="https://example.com/microsoft-teams",
                snippet="Microsoft Teams 集成聊天、会议、文件协作和 Microsoft 365 生态，是飞书面向企业办公套件时的重要替代方案。",
                raw_content="Teams 提供企业聊天、视频会议、文件协作和 Office 生态集成，面向中大型组织。",
            ),
            SearchResult(
                title="Google Workspace（云端办公与协作套件）",
                url="https://example.com/google-workspace",
                snippet="Google Workspace 覆盖 Gmail、Docs、Meet、Calendar 等协作工具，在云端办公套件层面与飞书形成替代竞争。",
                raw_content="Google Workspace 面向组织提供邮件、文档、日程、会议和云端协作能力。",
            ),
        ]

    @staticmethod
    def _meeting_tools() -> list[SearchResult]:
        return [
            SearchResult(
                title="Otter.ai（AI 会议记录与转写工具）",
                url="https://example.com/otter-ai",
                snippet="面向会议场景的 AI 记录工具，提供实时转写、发言人识别、会议摘要和团队协作能力，适合作为 AI 会议纪要产品的直接竞品。",
                raw_content="Otter.ai 提供实时会议转写、发言人识别、自动摘要和团队共享能力，主要服务商务会议、销售沟通和远程协作场景。",
            ),
            SearchResult(
                title="Fireflies.ai（AI 会议助手与对话分析工具）",
                url="https://example.com/fireflies-ai",
                snippet="自动录制、转写并分析会议内容，强调可搜索会议记录、对话洞察和 CRM 集成，是偏销售与客户沟通场景的直接竞品。",
                raw_content="Fireflies.ai 支持会议录制、可搜索转写稿、对话智能分析和 CRM 集成，常用于销售会议、客户访谈和团队知识沉淀。",
            ),
            SearchResult(
                title="Fathom（销售会议摘要工具）",
                url="https://example.com/fathom",
                snippet="主打快速生成会议摘要、重点片段和跟进事项，适合销售与客户成功团队，是 AI 会议纪要方向的间接竞品。",
                raw_content="Fathom 围绕会议摘要、重点标记、跟进事项和团队分享构建产品体验，重点服务销售电话和客户会议。",
            ),
            SearchResult(
                title="tl;dv（视频会议录制与摘要工具）",
                url="https://example.com/tldv",
                snippet="提供视频会议录制、多语言转写、片段剪辑和摘要能力，更偏视频会议知识沉淀，可视为替代方案型竞品。",
                raw_content="tl;dv 强调视频会议录制、多语言转写、片段剪辑、标签管理和客户研究协作工作流。",
            ),
        ]

    @staticmethod
    def _crm_tools() -> list[SearchResult]:
        return [
            SearchResult(
                title="HubSpot CRM（中小企业 CRM 与营销自动化平台）",
                url="https://example.com/hubspot-crm",
                snippet="覆盖销售管道、营销自动化和客户服务，免费入口明显，适合作为中小企业 CRM 产品的直接竞品。",
                raw_content="HubSpot 面向成长型团队，提供免费 CRM、营销自动化、销售管线管理和客户服务套件。",
            ),
            SearchResult(
                title="Salesforce Sales Cloud（企业级 CRM 平台）",
                url="https://example.com/salesforce-sales-cloud",
                snippet="面向企业销售组织，强调高度定制、工作流自动化、预测分析和生态集成，是企业 CRM 的标杆竞品。",
                raw_content="Salesforce Sales Cloud 定位企业级销售管理，提供定制化、销售预测、自动化流程和丰富集成生态。",
            ),
            SearchResult(
                title="Pipedrive CRM（销售管道管理工具）",
                url="https://example.com/pipedrive-crm",
                snippet="主打可视化销售管道、易用性和销售动作提醒，适合 SMB 销售团队，是轻量 CRM 直接竞品。",
                raw_content="Pipedrive 强调易用的销售管线、商机跟进、活动提醒和中小团队销售流程管理。",
            ),
            SearchResult(
                title="Zoho CRM（高性价比 CRM 套件）",
                url="https://example.com/zoho-crm",
                snippet="提供销售、支持和多渠道客户沟通能力，价格相对友好，是预算敏感团队常见替代选择。",
                raw_content="Zoho CRM 面向成本敏感团队，提供业务套件集成、自动化和多渠道客户沟通。",
            ),
        ]

    @staticmethod
    def _research_tools() -> list[SearchResult]:
        return [
            SearchResult(
                title="Perplexity",
                url="https://example.com/perplexity",
                snippet="Perplexity provides answer search with citations for research workflows.",
                raw_content="Perplexity combines search and answer generation, citing web sources and supporting research follow-up questions.",
            ),
            SearchResult(
                title="ChatGPT Deep Research",
                url="https://example.com/chatgpt-deep-research",
                snippet="Deep research tools synthesize information from multiple web sources into structured reports.",
                raw_content="Deep research workflows focus on multi-step browsing, synthesis, source attribution, and long-form report generation.",
            ),
            SearchResult(
                title="Similarweb",
                url="https://example.com/similarweb",
                snippet="Similarweb offers digital intelligence, traffic analytics, and market benchmarking.",
                raw_content="Similarweb helps teams compare market performance, website traffic, channels, and competitor benchmarks.",
            ),
        ]

    @staticmethod
    def _slack_materials(query: str) -> list[SearchResult]:
        if "reviews" in query or "g2" in query or "capterra" in query:
            return [
                SearchResult(
                    title="Slack Reviews 2026: pros and cons",
                    url="https://www.g2.com/products/slack/reviews",
                    snippet="Users praise Slack integrations and channels, while noting notification overload and enterprise cost concerns.",
                    raw_content="G2 reviews show Slack is valued for integrations, search and collaboration, with common complaints around noise and pricing.",
                ),
                SearchResult(
                    title="Teams discuss Slack notification pain points",
                    url="https://www.reddit.com/r/slack/comments/example",
                    snippet="Community discussions mention notification management, workspace sprawl and onboarding issues.",
                    raw_content="Reddit users discuss Slack pain points including noisy channels, workspace switching and information overload.",
                ),
            ]
        if "pricing" in query:
            return [
                SearchResult(
                    title="Slack Pricing Plans",
                    url="https://slack.com/pricing",
                    snippet="Slack lists Free, Pro, Business+ and Enterprise Grid plans for different team needs.",
                    raw_content="Slack pricing page describes plan limits, enterprise features and paid collaboration capabilities.",
                ),
                SearchResult(
                    title="Slack pricing comparison",
                    url="https://www.capterra.com/p/135003/Slack/pricing/",
                    snippet="Capterra summarizes Slack pricing and user-reported value for money.",
                    raw_content="Third-party pricing summaries compare Slack plan tiers and user sentiment.",
                ),
            ]
        if "docs" in query:
            return [
                SearchResult(
                    title="Slack API and workflow docs",
                    url="https://api.slack.com/docs",
                    snippet="Slack developer docs explain workflow automation, apps, APIs and integrations.",
                    raw_content="Slack docs cover app platform capabilities, workflow builder, messaging APIs and admin controls.",
                ),
                SearchResult(
                    title="Slack Help Center",
                    url="https://slack.com/help/categories/200111606",
                    snippet="Slack help center documents channels, huddles, search and workspace administration.",
                    raw_content="Official help content explains product features and team collaboration workflows.",
                ),
            ]
        return [
            SearchResult(
                title="Slack official product overview",
                url="https://slack.com/product",
                snippet="Slack is an AI-powered work platform for communication, channels, automation and app integrations.",
                raw_content="Slack positions itself as a work operating system for team communication, knowledge sharing and automation.",
            ),
            SearchResult(
                title="Slack launches new enterprise collaboration features",
                url="https://techcrunch.com/example/slack-enterprise-features",
                snippet="A media report covers Slack's enterprise collaboration updates and market positioning.",
                raw_content="TechCrunch reports on Slack enterprise updates, collaboration features and competitive positioning.",
            ),
        ]

    @staticmethod
    def _smart_cup_materials(query: str) -> list[SearchResult]:
        if any(keyword in query for keyword in ["小红书", "知乎", "b站", "差评", "评价"]):
            return [
                SearchResult(
                    title="Ember Mug 使用体验：办公室恒温杯值不值",
                    url="https://www.xiaohongshu.com/explore/ember-mug-review",
                    snippet="小红书用户反馈 Ember Mug 保温体验好，但价格高、清洁和续航存在争议。",
                    raw_content="社交平台用户评价提到温控稳定、适合办公桌面，也提到价格高、电池续航和清洗限制。",
                ),
                SearchResult(
                    title="智能恒温杯是不是智商税？",
                    url="https://www.zhihu.com/question/ember-mug",
                    snippet="知乎讨论集中在使用频率、价格合理性、续航和替代方案。",
                    raw_content="社区讨论反映用户对 Ember Mug 的购买动机、痛点和替代品看法。",
                ),
            ]
        if any(keyword in query for keyword in ["京东", "天猫", "淘宝", "价格"]):
            return [
                SearchResult(
                    title="Ember Mug 智能恒温杯 京东商品页",
                    url="https://item.jd.com/ember-mug.html",
                    snippet="京东商品页展示 Ember Mug 的售价、容量、温控参数和促销信息。",
                    raw_content="电商商品页提供 Ember Mug 价格、库存、参数、售后和购买入口。",
                ),
                SearchResult(
                    title="Ember Mug 天猫海外旗舰店商品介绍",
                    url="https://detail.tmall.com/item.htm?id=ember-mug",
                    snippet="天猫商品页展示 Ember Mug 商品详情、规格参数和用户问答。",
                    raw_content="天猫渠道页包含 Ember Mug 规格、详情图、价格与用户问答。",
                ),
            ]
        if any(keyword in query for keyword in ["测评", "体验", "功能", "参数"]):
            return [
                SearchResult(
                    title="Ember Mug Review: temperature control mug tested",
                    url="https://www.theverge.com/reviews/ember-mug-review",
                    snippet="专业测评关注 Ember Mug 的温控准确性、App 体验、续航和使用限制。",
                    raw_content="Professional review tests temperature control, battery life, charging coaster, mobile app and daily usability.",
                ),
                SearchResult(
                    title="Ember Mug 官方商品介绍",
                    url="https://ember.com/products/ember-mug-2",
                    snippet="Ember 官网介绍 Mug 2 的温度控制、App 设置和续航参数。",
                    raw_content="Official product page lists temperature range, battery life, charging coaster and app controls.",
                ),
            ]
        return [
            SearchResult(
                title="Ember Mug 官方商品介绍",
                url="https://ember.com/products/ember-mug-2",
                snippet="Ember 官网介绍 Mug 2 的温度控制、App 设置和续航参数。",
                raw_content="Official product page lists temperature range, battery life, charging coaster and app controls.",
            ),
            SearchResult(
                title="Ember Mug 品牌故事与产品定位",
                url="https://ember.com/pages/about",
                snippet="Ember 品牌围绕精准温控和高端饮品体验定位智能杯产品。",
                raw_content="Brand content explains Ember's temperature-control product positioning and target use cases.",
            ),
        ]

    @staticmethod
    def _smart_cup_tools() -> list[SearchResult]:
        return [
            SearchResult(
                title="Ember Mug（智能恒温杯）",
                url="https://example.com/ember-mug",
                snippet="Ember Mug 通过电子温控让饮品保持设定温度，是办公室智能保温杯场景的直接竞品。",
                raw_content="Ember Mug 主打精准温控、手机 App 设置温度、办公桌面使用和高端礼品市场。",
            ),
            SearchResult(
                title="Fellow Carter（高端随行保温杯）",
                url="https://example.com/fellow-carter",
                snippet="Fellow Carter 强调咖啡香气保留、便携设计和高端材质，是办公室与通勤水杯的高端替代选择。",
                raw_content="Fellow Carter 面向咖啡和办公用户，强调保温、饮用体验、杯口设计和便携性。",
            ),
            SearchResult(
                title="小米智能保温杯",
                url="https://example.com/xiaomi-smart-cup",
                snippet="小米生态智能杯提供温度显示、饮水提醒和高性价比，是智能保温杯方向的重要竞品。",
                raw_content="小米智能保温杯围绕温度显示、长效保温、饮水提醒和智能硬件生态构建卖点。",
            ),
            SearchResult(
                title="Vanow 智能保温杯",
                url="https://example.com/vanow-smart-bottle",
                snippet="Vanow 等国产智能保温杯强调温度显示、材质安全和办公便携，覆盖大众价格带。",
                raw_content="Vanow 智能保温杯提供 LED 温度显示、不锈钢内胆和多容量选择，适合办公室和通勤人群。",
            ),
        ]


    @staticmethod
    def _fallback_tools(query: str) -> list[SearchResult]:
        return [
            SearchResult(
                title="候选竞品 A（同类工作流产品）",
                url="https://example.com/competitor-a",
                snippet=f"围绕“{query}”发现的直接竞品，解决相似用户需求，功能路径与目标产品高度接近。",
                raw_content="候选竞品 A 提供相似核心工作流，目标用户接近，主要在功能完整度和交付效率上竞争。",
            ),
            SearchResult(
                title="候选竞品 B（轻量替代产品）",
                url="https://example.com/competitor-b",
                snippet=f"围绕“{query}”发现的间接竞品，用更轻量或更低成本方式解决同一类用户任务。",
                raw_content="候选竞品 B 通过不同工作流解决相同用户任务，主要在价格、易用性和部署速度上竞争。",
            ),
            SearchResult(
                title="候选竞品 C（人工流程或通用工具替代方案）",
                url="https://example.com/competitor-c",
                snippet=f"围绕“{query}”发现的替代方案，可能不是同类软件，但用户会用它完成相似目标。",
                raw_content="候选竞品 C 是用户采用专门软件前常用的替代方案，例如人工流程、表格或通用工具组合。",
            ),
        ]
