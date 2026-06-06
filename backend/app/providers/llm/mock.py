import json
import logging
import re
from typing import Any

from app.providers.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class MockLLMProvider(LLMProvider):
    name = "mock"

    def understand_requirement(self, user_requirement: str) -> dict[str, Any]:
        text = user_requirement.lower()
        input_type = "unclear"
        target_product = None
        product_description = None
        domain = "通用产品"
        target_users = ["业务团队", "产品团队", "普通用户"]
        core_capabilities = ["核心流程自动化", "信息整理", "报告生成"]
        analysis_dimensions = ["产品定位", "核心功能", "价格与商业模式", "用户评价与痛点"]

        if any(keyword in text for keyword in ["notion", "notion ai", "飞书文档", "语雀", "协作文档", "知识管理", "笔记", "obsidian", "logseq"]):
            input_type = "existing_product"
            target_product = "Notion AI" if "notion" in text else "笔记软件"
            domain = "AI 知识管理"
            target_users = ["知识工作者", "团队协作成员", "内容创作者"]
            core_capabilities = ["文档生成", "内容总结", "知识库问答", "团队协作"]
        elif any(keyword in text for keyword in ["飞书", "钉钉", "企业微信", "slack", "teams", "办公", "协作", "企业协作"]):
            input_type = "existing_product"
            if "飞书" in text:
                target_product = "飞书"
            elif "钉钉" in text:
                target_product = "钉钉"
            else:
                target_product = "企业微信"
            domain = "企业协作办公平台"
            target_users = ["企业员工", "团队管理者", "组织成员"]
            core_capabilities = ["即时沟通", "文档协作", "会议", "日程", "项目协作"]
        elif any(keyword in text for keyword in ["会议", "纪要", "otter", "fireflies", "转写"]):
            input_type = "existing_product"
            target_product = "AI 会议纪要工具"
            domain = "会议"
            target_users = ["商务人士", "销售团队", "远程协作者"]
            core_capabilities = ["会议转写", "自动摘要", "发言人识别", "团队共享"]
        elif any(keyword in text for keyword in ["编程", "coding", "代码", "程序员", "开发者", "ide", "cursor", "copilot"]):
            input_type = "product_idea"
            target_product = "AI 编程工具"
            product_description = user_requirement
            domain = "AI 编程"
            target_users = ["软件工程师", "开发团队", "技术负责人"]
            core_capabilities = ["代码补全", "代码生成", "上下文问答", "代码审查", "IDE 集成"]
        elif any(keyword in text for keyword in ["竞品分析", "市场调研", "competitive analysis"]):
            input_type = "product_idea"
            target_product = None
            product_description = user_requirement
            domain = "竞品分析"
            target_users = ["产品经理", "市场分析师", "战略团队"]
            core_capabilities = ["公开资料搜索", "来源引用", "竞品识别", "结构化报告生成"]
        elif any(keyword in text for keyword in ["保温杯", "水杯", "水壶", "水瓶", "杯子", "饮具", "mug", "cup", "bottle"]):
            input_type = "existing_product"
            target_product = "水壶产品" if any(keyword in text for keyword in ["水壶", "水瓶", "bottle"]) else "智能保温杯"
            domain = "水壶/饮具"
            target_users = ["办公室人群", "通勤人士", "户外运动人群", "健康关注者"]
            core_capabilities = ["保温保冷", "便携设计", "材质安全", "容量规格", "饮水体验"]
        else:
            input_type = "product_idea"
            product_description = user_requirement

        return {
            "input_type": input_type,
            "target_product": target_product,
            "product_description": product_description,
            "domain": domain,
            "summary": f"围绕“{user_requirement}”开展竞品发现、资料采集和结构化分析。",
            "target_users": target_users,
            "core_capabilities": core_capabilities,
            "use_cases": [],
            "possible_market_category": domain,
            "analysis_dimensions": analysis_dimensions,
            "needs_clarification": False,
            "clarification_questions": [],
            "confidence": 0.78,
            "warnings": [],
            "queries": [
                f'"{target_product or domain}" competitors alternatives 2026',
                f"{target_product or domain} 竞品 替代品 对比"
            ],
            "query": f"{target_product or domain} 竞品 替代品 对比",
        }

    def extract_focus_profile(self, user_requirement: str, requirement: dict[str, Any]) -> dict[str, Any]:
        text = user_requirement.lower()
        explicit_focuses = []
        focus_specs = [
            (
                "local_storage",
                ["本地", "离线", "local", "offline", "local-first", "local first"],
                "本地存储/离线可用",
                "优先查找官方文档、帮助中心或产品说明中关于本地存储、离线能力和数据同步方式的证据。",
                ["local storage", "offline", "local-first", "本地存储", "离线"],
            ),
            (
                "privacy_security",
                ["隐私", "安全", "加密", "数据所有权", "privacy", "security", "encryption"],
                "隐私、安全与数据所有权",
                "优先查找官方安全说明、隐私政策、加密和数据控制相关文档。",
                ["privacy", "security", "encryption", "data ownership", "隐私", "安全", "加密"],
            ),
            (
                "pricing",
                ["价格", "定价", "收费", "预算", "pricing", "price", "cost"],
                "价格与套餐",
                "优先查找官方价格页、套餐说明和企业版收费信息。",
                ["pricing", "plans", "价格", "收费", "套餐"],
            ),
            (
                "collaboration",
                ["协作", "团队", "共享", "多人", "collaboration", "team"],
                "团队协作能力",
                "优先查找协作、权限、评论、共享和团队空间相关功能证据。",
                ["collaboration", "team workspace", "sharing", "协作", "权限", "共享"],
            ),
            (
                "ai_capability",
                ["ai", "智能", "生成", "总结", "问答", "agent"],
                "AI 能力",
                "优先查找生成、总结、问答、自动化和模型能力相关官方说明或测评。",
                ["AI", "assistant", "summary", "automation", "智能", "总结", "问答"],
            ),
        ]
        has_focus_intent = _has_focus_intent(text)
        for key, keywords, label, evidence_expectation, query_terms in focus_specs:
            if any(keyword in text for keyword in keywords):
                if key in {"ai_capability", "collaboration"} and not has_focus_intent:
                    continue
                explicit_focuses.append(
                    {
                        "key": key,
                        "label": label,
                        "priority": "high",
                        "evidence_expectation": evidence_expectation,
                        "query_terms": query_terms,
                    }
                )

        inferred_focuses = []
        domain_text = f"{requirement.get('domain', '')} {requirement.get('possible_market_category', '')}"
        if not explicit_focuses and any(keyword in domain_text for keyword in ["会议", "协作", "办公"]):
            inferred_focuses.append(
                {
                    "key": "workflow_integration",
                    "label": "工作流集成与团队落地",
                    "priority": "medium",
                    "evidence_expectation": "关注集成、权限、团队空间和实际工作流落地证据。",
                    "query_terms": ["integrations", "workflow", "team", "集成", "团队协作"],
                }
            )

        needs_clarification = not explicit_focuses and _should_mock_ask_clarification(user_requirement, requirement)
        return {
            "explicit_focuses": explicit_focuses,
            "inferred_focuses": inferred_focuses,
            "clarification_needed": needs_clarification,
            "clarifying_question": _clarifying_question(requirement) if needs_clarification else None,
            "assumptions": [] if explicit_focuses else ["如果用户未补充侧重点，报告将按功能、价格、评价和市场定位进行均衡分析。"],
        }

    def understand_target(self, requirement: dict[str, Any], target_search_results: list[dict[str, Any]]) -> dict[str, Any]:
        name = requirement.get("target_product") or requirement.get("product_description") or requirement.get("domain", "目标对象")
        domain = requirement.get("possible_market_category") or requirement.get("domain", "通用产品")
        text = "\n".join(f"{item.get('title', '')} {item.get('snippet', '')}" for item in target_search_results)
        if "企业协作" in domain or "办公" in domain:
            capabilities = ["即时沟通", "文档协作", "会议", "日程", "项目协作", "开放平台"]
            use_cases = ["内部沟通", "团队协作", "知识管理", "会议协同", "组织管理"]
            positioning = f"{name} 是面向组织的企业协作办公平台，覆盖沟通、文档、会议和组织协同场景。"
        elif "AI 知识管理" in domain or "协作文档" in domain:
            capabilities = ["文档生成", "内容总结", "知识库问答", "团队协作", "信息整理"]
            use_cases = ["文档写作", "知识管理", "团队协作", "项目资料沉淀"]
            positioning = f"{name} 是面向文档和知识管理场景的 AI 助手。"
        elif "会议" in domain:
            capabilities = ["会议转写", "自动摘要", "发言人识别", "团队共享"]
            use_cases = ["商务会议", "销售沟通", "远程协作"]
            positioning = f"{name} 面向会议场景提供记录、转写和摘要能力。"
        elif "AI 编程" in domain or "编程" in domain:
            capabilities = ["代码补全", "代码生成", "代码库问答", "重构建议", "IDE 集成"]
            use_cases = ["日常编码", "代码理解", "重构维护", "团队研发提效"]
            positioning = f"{name} 面向开发者提供 AI 辅助编码、代码理解和研发效率提升能力。"
        elif "竞品分析" in domain or "市场调研" in domain:
            capabilities = ["公开资料搜索", "来源引用", "竞品识别", "结构化报告生成"]
            use_cases = ["竞品调研", "市场分析", "产品决策", "报告自动化"]
            positioning = f"{name} 面向产品和市场团队提供 AI 调研与竞品分析自动化能力。"
        elif any(keyword in domain for keyword in ["保温杯", "水杯", "水壶", "水瓶", "饮具"]):
            capabilities = ["保温保冷", "便携设计", "材质安全", "容量规格", "饮水体验"]
            use_cases = ["办公室饮水", "通勤携带", "户外运动", "健康管理"]
            positioning = f"{name} 面向日常饮水、通勤和户外场景，解决便携、保温和饮水体验需求。"
        else:
            capabilities = requirement.get("core_capabilities") or ["核心流程自动化", "信息整理", "报告生成"]
            use_cases = requirement.get("use_cases") or ["业务调研", "团队协作"]
            positioning = f"{name} 属于“{domain}”方向，具体定位需结合公开资料进一步确认。"
        return {
            "name": str(name),
            "category": domain,
            "positioning": positioning,
            "target_users": requirement.get("target_users", []),
            "core_capabilities": capabilities,
            "primary_use_cases": use_cases,
            "source_ids": [item.get("url") for item in target_search_results[:3] if item.get("url")],
            "evidence_ids": [],
            "confidence": 0.84 if text else 0.62,
            "warnings": [] if text else ["目标理解缺少搜索结果支撑"],
        }

    def extract_competitors(
        self,
        requirement: dict[str, Any],
        target_understanding: dict[str, Any],
        search_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        categories = ["direct_competitor", "direct_competitor", "indirect_competitor", "substitute_solution"]
        target_name = str(target_understanding.get("name") or requirement.get("target_product") or "")
        names = _extract_product_names(search_results, target_name)
        target_category = target_understanding.get("category") or requirement.get("domain", "")
        target_name_lower = target_name.lower()
        names = [name for name in names if name.lower() != target_name_lower]
        
        global_names = []
        china_names = []
        global_websites = {}
        china_websites = {}
        
        if "企业协作" in target_category or "办公" in target_category or "钉钉" in target_name_lower:
            global_names = ["Slack", "Microsoft Teams", "Google Workspace", "Notion"]
            global_websites = {
                "Slack": "https://slack.com",
                "Microsoft Teams": "https://teams.microsoft.com",
                "Google Workspace": "https://workspace.google.com",
                "Notion": "https://notion.so"
            }
            china_names = ["钉钉", "企业微信", "飞书", "飞书会议"]
            china_websites = {
                "钉钉": "https://dingtalk.com",
                "企业微信": "https://weixin.qq.com/work",
                "飞书": "https://feishu.cn",
                "飞书会议": "https://feishu.cn/meeting"
            }
        elif "AI 知识管理" in target_category or "协作文档" in target_category:
            global_names = ["Coda AI", "Confluence AI", "ClickUp AI", "Mem"]
            global_websites = {
                "Coda AI": "https://coda.io",
                "Confluence AI": "https://atlassian.com/software/confluence",
                "ClickUp AI": "https://clickup.com",
                "Mem": "https://mem.ai"
            }
            china_names = ["飞书文档", "语雀", "有道云笔记", "印象笔记"]
            china_websites = {
                "飞书文档": "https://feishu.cn/docx",
                "语雀": "https://yuque.com",
                "有道云笔记": "https://note.youdao.com",
                "印象笔记": "https://yinxiang.com"
            }
        elif "会议" in target_category:
            global_names = ["Otter.ai", "Fireflies.ai", "Fathom", "tl;dv"]
            global_websites = {
                "Otter.ai": "https://otter.ai",
                "Fireflies.ai": "https://fireflies.ai",
                "Fathom": "https://fathom.video",
                "tl;dv": "https://tldv.io"
            }
            china_names = ["讯飞听见", "听脑AI", "科会通", "飞书妙计"]
            china_websites = {
                "讯飞听见": "https://www.iflyrec.com",
                "听脑AI": "https://tingnao.ai",
                "科会通": "https://kehuitong.com",
                "飞书妙计": "https://feishu.cn/medias"
            }
        elif "AI 编程" in target_category or "编程" in target_category:
            global_names = ["Cursor", "GitHub Copilot", "Windsurf", "Codeium"]
            global_websites = {
                "Cursor": "https://cursor.com",
                "GitHub Copilot": "https://github.com/features/copilot",
                "Windsurf": "https://windsurf.com",
                "Codeium": "https://codeium.com",
            }
            china_names = ["通义灵码", "豆包 MarsCode", "百度 Comate", "腾讯云 AI 代码助手"]
            china_websites = {
                "通义灵码": "https://tongyi.aliyun.com/lingma",
                "豆包 MarsCode": "https://www.marscode.cn",
                "百度 Comate": "https://comate.baidu.com",
                "腾讯云 AI 代码助手": "https://cloud.tencent.com/product/acc",
            }
        elif "竞品分析" in target_category or "市场调研" in target_category:
            global_names = ["Perplexity", "ChatGPT Deep Research", "Similarweb", "Crayon"]
            global_websites = {
                "Perplexity": "https://perplexity.ai",
                "ChatGPT Deep Research": "https://chat.openai.com",
                "Similarweb": "https://similarweb.com",
                "Crayon": "https://crayon.co"
            }
            china_names = ["天眼查", "企查查", "爱企查", "启信宝"]
            china_websites = {
                "天眼查": "https://tianyancha.com",
                "企查查": "https://qcc.com",
                "爱企查": "https://aiqicha.baidu.com",
                "启信宝": "https://qixin.com"
            }
        elif any(keyword in target_category for keyword in ["保温杯", "水杯", "水壶", "水瓶", "饮具"]):
            global_names = ["Stanley Quencher", "Hydro Flask", "YETI Rambler", "Fellow Carter"]
            global_websites = {
                "Stanley Quencher": "https://www.stanley1913.com",
                "Hydro Flask": "https://www.hydroflask.com",
                "YETI Rambler": "https://www.yeti.com",
                "Fellow Carter": "https://fellowproducts.com",
            }
            china_names = ["膳魔师保温杯", "象印保温杯", "哈尔斯水杯", "富光水杯"]
            china_websites = {
                "膳魔师保温杯": "https://www.thermos.com.cn",
                "象印保温杯": "https://www.zojirushi.com.cn",
                "哈尔斯水杯": "https://haers.com",
                "富光水杯": "https://www.fuguangchina.com",
            }
        else:
            global_names = names[:4] if len(names) >= 4 else (names + ["Slack", "Microsoft Teams"])[:4]
            china_names = (names[4:8] if len(names) >= 8 else names[4:] + ["钉钉", "企业微信"])[:4]
            global_websites = {}
            china_websites = {}
        
        competitors = []
        for index, name in enumerate(global_names[:4]):
            related_result = _find_related_result(name, search_results)
            competitors.append(
                {
                    "name": name,
                    "website": global_websites.get(name) or related_result.get("url"),
                    "description": _describe_candidate(name, related_result, requirement),
                    "category": categories[index] if index < len(categories) else "direct_competitor",
                    "region": "global",
                    "reason": _build_candidate_reason(name, target_understanding),
                    "matched_dimensions": _matched_dimensions(target_understanding),
                    "source_ids": [related_result.get("url")] if related_result.get("url") else [],
                    "evidence_ids": [],
                    "selected_by_default": True,
                    "confidence": max(0.55, 0.82 - index * 0.07),
                    "discovery_source": "search_heuristic",
                }
            )
        for index, name in enumerate(china_names[:4]):
            related_result = _find_related_result(name, search_results)
            competitors.append(
                {
                    "name": name,
                    "website": china_websites.get(name) or related_result.get("url"),
                    "description": _describe_candidate(name, related_result, requirement),
                    "category": categories[index] if index < len(categories) else "direct_competitor",
                    "region": "china",
                    "reason": _build_candidate_reason(name, target_understanding),
                    "matched_dimensions": _matched_dimensions(target_understanding),
                    "source_ids": [related_result.get("url")] if related_result.get("url") else [],
                    "evidence_ids": [],
                    "selected_by_default": True,
                    "confidence": max(0.55, 0.82 - index * 0.07),
                    "discovery_source": "search_heuristic",
                }
            )
        return competitors

    def analyze_competitor(self, competitor: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
        name = competitor["name"]
        evidence_ids = [item.get("id") or item.get("source_url") or item.get("related_dimension", "evidence") for item in evidence]
        focus_analysis = _mock_focus_analysis(competitor.get("_focus_schema"), evidence)
        return {
            "positioning": f"{name} 面向目标用户提供较完整的相关工作流，强调效率提升和团队协作。",
            "target_users": json.dumps(["业务团队", "产品团队", "管理者"], ensure_ascii=False),
            "core_features_json": json.dumps(["核心流程自动化", "信息整理", "团队协作", "第三方集成"], ensure_ascii=False),
            "pricing_summary": "MVP Mock 数据显示其通常采用免费试用或分层订阅模式，具体价格需以后续真实采集为准。",
            "strengths_json": json.dumps(["功能覆盖较完整", "使用门槛较低", "适合快速试用"], ensure_ascii=False),
            "weaknesses_json": json.dumps(["深度定制能力有限", "不同来源信息仍需人工复核"], ensure_ascii=False),
            "opportunities_json": json.dumps(["可在垂直场景、证据可信度和中文本地化体验上做差异化"], ensure_ascii=False),
            "custom_focus_analysis_json": json.dumps(focus_analysis, ensure_ascii=False),
            "evidence_ids_json": json.dumps(evidence_ids, ensure_ascii=False),
        }

    def generate_report(self, run: dict[str, Any], analyses: list[dict[str, Any]], sources: list[dict[str, Any]]) -> dict[str, str]:
        title = f"{run.get('title', '竞品分析任务')}报告"
        bundle_by_competitor = {
            item.get("competitor_id"): item
            for item in run.get("citation_bundle", [])
            if isinstance(item, dict)
        }
        lines = [
            f"# {title}",
            "",
            "## 执行摘要",
            "",
            "本次竞品分析任务已完成，系统通过多 Agent 协作自动完成了需求理解、竞品发现、公开资料采集与结构化分析全流程。",
            "",
            "## 分析概览",
            "",
            f"- 分析对象：{run.get('user_requirement', '未指定')}",
            f"- 分析竞品数量：{len(analyses)} 个",
            f"- 采集来源数量：{len(sources)} 条",
            "",
        ]
        for analysis in analyses:
            competitor_name = analysis.get("competitor_name", "未知竞品")
            dynamic_claims = _dynamic_bundle_claims(bundle_by_competitor.get(analysis.get("competitor_id")))
            lines.extend([
                f"## {competitor_name}",
                "",
                f"### 产品定位",
                analysis.get("positioning", "暂无定位信息"),
                "",
                f"### 目标用户",
                "",
            ])
            try:
                target_users = json.loads(analysis.get("target_users", "[]"))
                for user in target_users:
                    lines.append(f"- {user}")
            except (json.JSONDecodeError, TypeError):
                lines.append(analysis.get("target_users", "暂无目标用户信息"))
            lines.extend([
                "",
                f"### 核心功能",
                "",
            ])
            try:
                core_features = json.loads(analysis.get("core_features_json", "[]"))
                for feature in core_features:
                    lines.append(f"- {feature}")
            except (json.JSONDecodeError, TypeError):
                lines.append(analysis.get("core_features_json", "暂无核心功能信息"))
            lines.extend([
                "",
                f"### 价格与商业模式",
                analysis.get("pricing_summary", "暂无价格信息"),
                "",
                f"### 优势",
                "",
            ])
            try:
                strengths = json.loads(analysis.get("strengths_json", "[]"))
                for s in strengths:
                    lines.append(f"- {s}")
            except (json.JSONDecodeError, TypeError):
                lines.append(analysis.get("strengths_json", "暂无优势信息"))
            lines.extend([
                "",
                f"### 劣势与用户痛点",
                "",
            ])
            try:
                weaknesses = json.loads(analysis.get("weaknesses_json", "[]"))
                for w in weaknesses:
                    lines.append(f"- {w}")
            except (json.JSONDecodeError, TypeError):
                lines.append(analysis.get("weaknesses_json", "暂无劣势信息"))
            lines.extend([
                "",
                f"### 机会点",
                "",
            ])
            try:
                opportunities = json.loads(analysis.get("opportunities_json", "[]"))
                for o in opportunities:
                    lines.append(f"- {o}")
            except (json.JSONDecodeError, TypeError):
                lines.append(analysis.get("opportunities_json", "暂无机会点信息"))
            if dynamic_claims:
                lines.extend(["", "### 用户关注点动态字段", ""])
                for claim in dynamic_claims:
                    citation = _claim_citation(claim)
                    lines.append(f"- {claim.get('label')}: {claim.get('text')}{citation}")
            lines.append("")
        lines.extend([
            "## 参考来源",
            "",
        ])
        for idx, source in enumerate(sources, 1):
            title = source.get("title", f"来源 {idx}")
            url = source.get("url", "")
            if url:
                lines.append(f"{idx}. [[{idx}]]({url}) [{title}]({url})")
            else:
                lines.append(f"{idx}. [{idx}] {title}")
        return {
            "title": title,
            "summary": f"已完成 {len(analyses)} 个竞品的结构化分析，共采集 {len(sources)} 条公开来源。",
            "markdown_content": "\n".join(lines),
        }

    def qa_check_report(
        self,
        report: dict[str, str],
        analyses: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        evidence_ref_ids = {e.get("reference_id") for e in evidence if e.get("reference_id")}
        competitor_evidence_count: dict[str, int] = {}
        for item in evidence:
            cid = item.get("competitor_id", "unknown")
            competitor_evidence_count[cid] = competitor_evidence_count.get(cid, 0) + 1

        for analysis in analyses:
            name = analysis.get("competitor_name", analysis.get("name", "未知"))
            cid = analysis.get("competitor_id", "")
            ev_count = competitor_evidence_count.get(cid, 0)
            if ev_count < 3:
                issues.append({
                    "dimension": "coverage_gaps",
                    "severity": "critical" if ev_count == 0 else "major",
                    "competitor_name": name,
                    "description": f"{name} 仅有 {ev_count} 条证据，覆盖不足",
                    "fix_suggestion": f"补充搜索 {name} 的核心功能和定价信息",
                })
            pricing = str(analysis.get("pricing_summary", ""))
            if not pricing or "未涉及" in pricing or "Mock" in pricing:
                issues.append({
                    "dimension": "schema_completeness",
                    "severity": "major",
                    "competitor_name": name,
                    "description": f"{name} 的定价信息缺失或为占位文本",
                    "fix_suggestion": f"补充搜索 {name} pricing plans",
                })

        markdown = report.get("markdown_content", "")
        import re
        cited_refs = re.findall(r"\[\[(\d+)\]\]", markdown)
        for ref_str in cited_refs:
            ref_id = int(ref_str)
            if ref_id not in evidence_ref_ids:
                issues.append({
                    "dimension": "citation_accuracy",
                    "severity": "minor",
                    "competitor_name": "report",
                    "description": f"报告引用了不存在的来源 [[{ref_id}]]",
                    "fix_suggestion": "移除或修正无效引用",
                })

        dimension_scores = {
            "evidence_grounding": 0.82,
            "citation_accuracy": 0.92,
            "schema_completeness": 0.88,
            "coverage_gaps": 0.9,
            "cross_competitor_consistency": 0.86,
            "factual_plausibility": 0.9,
        }
        for issue in issues:
            dimension = issue.get("dimension")
            if dimension not in dimension_scores:
                continue
            penalty = 0.28 if issue.get("severity") == "critical" else 0.18 if issue.get("severity") == "major" else 0.08
            dimension_scores[dimension] = max(0.3, dimension_scores[dimension] - penalty)

        retry_instructions = "; ".join(i["fix_suggestion"] for i in issues if i.get("fix_suggestion")) or None

        retry_queries = []
        for issue in issues:
            comp = issue.get("competitor_name", "")
            if comp in {"report", "system", ""}:
                continue
            dim = issue.get("dimension", "")
            if dim in {"coverage_gaps", "evidence_grounding"}:
                retry_queries.append({"competitor_name": comp, "slot": "core_features", "query": f"{comp} core features capabilities detailed"})
                retry_queries.append({"competitor_name": comp, "slot": "pricing", "query": f"{comp} pricing plans detailed cost"})
            elif dim == "schema_completeness":
                retry_queries.append({"competitor_name": comp, "slot": "pricing", "query": f"{comp} pricing plans tiers comparison"})

        return {
            "dimension_scores": {key: round(value, 2) for key, value in dimension_scores.items()},
            "retry_instructions": retry_instructions,
            "retry_queries": retry_queries,
            "issues": issues,
        }

    def qa_verify_issues(
        self,
        report: dict[str, str],
        analyses: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        open_issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        analysis_by_name = {a.get("competitor_name"): a for a in analyses}
        competitor_id_by_name = {a.get("competitor_name"): a.get("competitor_id") for a in analyses}
        evidence_count_by_name: dict[str, int] = {}
        for item in evidence:
            name = item.get("related_product")
            cid = item.get("competitor_id")
            if name:
                evidence_count_by_name[name] = evidence_count_by_name.get(name, 0) + 1
            for comp_name, comp_id in competitor_id_by_name.items():
                if comp_id and cid == comp_id:
                    evidence_count_by_name[comp_name] = evidence_count_by_name.get(comp_name, 0) + 1

        markdown = report.get("markdown_content", "")
        resolutions = []
        for issue in open_issues:
            issue_id = issue.get("id", "")
            comp = issue.get("competitor_name", "")
            dimension = issue.get("dimension", "")
            resolved = False
            reason = "Mock 复核未发现足够证据证明该问题已解决。"
            if dimension in {"coverage_gaps", "evidence_grounding"}:
                ev_count = evidence_count_by_name.get(comp, 0)
                resolved = ev_count >= 3
                reason = f"{comp} 当前证据数为 {ev_count}。"
            elif dimension == "schema_completeness":
                pricing = str((analysis_by_name.get(comp) or {}).get("pricing_summary", ""))
                resolved = bool(pricing and "未涉及" not in pricing and "Mock" not in pricing)
                reason = f"{comp} 当前定价字段{'已有实质内容' if resolved else '仍缺少实质内容'}。"
            elif dimension == "citation_accuracy":
                resolved = "不存在的来源" not in markdown
                reason = "报告引用复核完成。"
            resolutions.append(
                {
                    "issue_id": issue_id,
                    "status": "resolved" if resolved else "open",
                    "resolution_reason": reason,
                    "retry_queries": [] if resolved else [
                        {"competitor_name": comp, "slot": "core_features", "query": f"{comp} core features evidence"}
                    ] if comp not in {"report", "system", ""} and dimension in {"coverage_gaps", "evidence_grounding"} else [],
                }
            )
        unresolved = [item for item in resolutions if item["status"] != "resolved"]
        return {
            "resolutions": resolutions,
            "retry_instructions": "; ".join(
                issue.get("fix_suggestion", "") for issue in open_issues if issue.get("id") in {item["issue_id"] for item in unresolved}
            ) or None,
        }

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return [
            {
                "title": f"Mock 搜索结果 1 - {query}",
                "url": f"https://example.com/result-1",
                "snippet": f"这是关于 {query} 的第一条 Mock 搜索结果，包含相关产品信息。",
                "raw_content": f"# Mock 搜索结果 1\n\n这是关于 {query} 的详细内容，提供产品的基本介绍和功能说明。",
            },
            {
                "title": f"Mock 搜索结果 2 - {query}",
                "url": f"https://example.com/result-2",
                "snippet": f"这是关于 {query} 的第二条 Mock 搜索结果，包含用户评价。",
                "raw_content": f"# Mock 搜索结果 2\n\n这是关于 {query} 的用户评价内容，讨论产品的优缺点。",
            },
        ][:limit]


def _extract_product_names(search_results: list[dict[str, Any]], target_name: str) -> list[str]:
    names = []
    for result in search_results:
        text = f"{result.get('title', '')} {result.get('snippet', '')}"
        found = re.findall(r'[A-Za-z0-9\u4e00-\u9fa5]{2,30}', text)
        for name in found:
            if len(name) >= 2 and name.lower() != target_name.lower() and not _looks_mock_generic_name(name):
                names.append(name)
    seen = set()
    unique = []
    for name in names:
        if name.lower() not in seen:
            seen.add(name.lower())
            unique.append(name)
    return unique[:8]


def _looks_mock_generic_name(name: str) -> bool:
    stripped = name.lower().replace(" ", "")
    generic_terms = {
        "我想做", "我要做", "想做", "要做", "同类产品榜单", "与竞品对比", "竞品对比",
        "alternatives", "competitors", "用户需求", "替代方案讨论", "产品榜单", "同类产品",
        "这是关于", "包含相关产品信息", "包含用户评价",
    }
    if stripped in generic_terms:
        return True
    if stripped.startswith(("我想", "我要", "想做", "要做")):
        return True
    return any(term in stripped for term in ["同类产品榜单", "竞品对比", "替代方案讨论"])


def _find_related_result(name: str, search_results: list[dict[str, Any]]) -> dict[str, Any]:
    for result in search_results:
        text = f"{result.get('title', '')} {result.get('snippet', '')}".lower()
        if name.lower() in text:
            return result
    return {}


def _describe_candidate(name: str, related_result: dict[str, Any], requirement: dict[str, Any]) -> str:
    if related_result and related_result.get("snippet"):
        return str(related_result.get("snippet", ""))[:200]
    return f"{name} 是同赛道的相关竞品产品，具备相似的核心能力与目标用户群体。"


def _build_candidate_reason(name: str, target_understanding: dict[str, Any]) -> str:
    return f"基于目标画像与公开资料匹配，{name} 属于同赛道竞品。"


def _matched_dimensions(target_understanding: dict[str, Any]) -> list[str]:
    return ["产品定位", "目标用户", "核心功能", "使用场景"]


def _dynamic_bundle_claims(bundle_item: object) -> list[dict[str, Any]]:
    if not isinstance(bundle_item, dict):
        return []
    claims = bundle_item.get("claims")
    if not isinstance(claims, list):
        return []
    return [
        claim
        for claim in claims
        if isinstance(claim, dict) and str(claim.get("claim_type", "")).startswith("focus:")
    ]


def _claim_citation(claim: dict[str, Any]) -> str:
    evidence = claim.get("evidence")
    if not isinstance(evidence, list):
        return ""
    for item in evidence:
        if not isinstance(item, dict):
            continue
        ref_id = item.get("source_reference_id")
        url = item.get("source_url")
        if ref_id and url:
            return f" [[{ref_id}]]({url})"
    return ""


def _mock_focus_analysis(focus_schema: object, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(focus_schema, list):
        return []
    results = []
    for focus in focus_schema[:6]:
        if not isinstance(focus, dict) or not focus.get("label"):
            continue
        label = str(focus["label"])
        matched = [
            item
            for item in evidence
            if label in str(item.get("related_dimension", "")) or label in str(item.get("summary", ""))
        ]
        if not matched:
            matched = evidence[:2]
        evidence_ids = [item.get("id") for item in matched if item.get("id")]
        verdict = f"围绕“{label}”，现有证据显示该产品已有相关信息，但仍需结合真实来源复核。"
        if not evidence_ids:
            verdict = "证据中未涉及"
        results.append(
            {
                "focus_key": str(focus.get("key") or f"focus_{len(results) + 1}"),
                "label": label,
                "verdict": verdict,
                "evidence_ids": evidence_ids[:4],
                "confidence": 0.72 if evidence_ids else 0.0,
            }
        )
    return results


def _should_mock_ask_clarification(user_requirement: str, requirement: dict[str, Any]) -> bool:
    text = user_requirement.strip().lower()
    if any(keyword in text for keyword in ["关注", "侧重", "重点", "尤其", "比较", "是否", "privacy", "pricing", "local"]):
        return False
    domain = str(requirement.get("domain") or requirement.get("possible_market_category") or "")
    return any(keyword in domain for keyword in ["知识管理", "会议", "办公", "通用产品", "竞品分析", "AI 编程", "编程", "水壶", "水杯", "饮具"]) or any(
        keyword in text for keyword in ["笔记", "文档", "工具", "软件", "竞品"]
    )


def _has_focus_intent(text: str) -> bool:
    return any(keyword in text for keyword in ["关注", "侧重", "重点", "尤其", "比较", "是否", "优先", "看重", "差异"])


def _clarifying_question(requirement: dict[str, Any]) -> str:
    domain = str(requirement.get("domain") or requirement.get("possible_market_category") or "这个方向")
    if any(keyword in domain for keyword in ["知识管理", "文档", "笔记"]):
        return "你希望这份竞品报告重点关注哪类差异：本地存储/隐私、AI 能力、团队协作、价格，还是迁移成本？"
    if any(keyword in domain for keyword in ["会议", "办公", "协作"]):
        return "你希望这份竞品报告重点关注哪类差异：转写/总结质量、团队协作、CRM/日程集成、数据安全，还是价格？"
    if any(keyword in domain for keyword in ["AI 编程", "编程"]):
        return "你希望这份竞品报告重点关注哪类差异：代码生成质量、IDE/工作流集成、代码库上下文、团队协作、安全合规，还是价格？"
    if any(keyword in domain for keyword in ["水壶", "水杯", "饮具", "保温杯"]):
        return "你希望这份竞品报告重点关注哪类差异：保温性能、材质安全、便携设计、容量规格、用户评价，还是价格？"
    return "你希望这份竞品报告优先回答什么问题？例如功能差异、价格、用户痛点、隐私安全、落地成本或市场机会。"
