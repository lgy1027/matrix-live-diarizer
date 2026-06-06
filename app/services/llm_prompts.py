"""LLM Prompt 模板（用户可在 settings 页面修改）"""

PROMPTS = {
    "summarize": (
        "请根据以下转写生成 {max_words} 字以内的摘要，"
        "重点保留关键信息和决议：\n\n{transcript}"
    ),
    "action_items": (
        "从以下会议转写中提取所有行动项，每条一行，"
        "以「- 」开头。如果没有行动项，回复「无」。\n\n{transcript}"
    ),
    "minutes": (
        "请按以下结构生成会议纪要：\n"
        "## 议题\n（主要讨论的话题）\n"
        "## 决议\n（达成的结论）\n"
        "## 行动项\n（待办事项及负责人）\n\n"
        "转写内容：\n{transcript}"
    ),
}
