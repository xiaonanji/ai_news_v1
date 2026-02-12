from __future__ import annotations

from dataclasses import dataclass

from openai import OpenAI

from .config import LLMConfig


@dataclass
class LLMClient:
    config: LLMConfig

    def __post_init__(self) -> None:
        if self.config.provider != "openai":
            raise ValueError(f"Unsupported LLM provider: {self.config.provider}")
        self._client = OpenAI(api_key=self.config.api_key)

    def _run(self, instructions: str, input_text: str) -> str:
        resp = self._client.responses.create(
            model=self.config.model,
            instructions=instructions,
            input=input_text,
        )
        return (resp.output_text or "").strip()

    def summarize_zh(self, text: str) -> str:
        instructions = (
            "Summarize the given news article in Chinese. "
            "Keep it concise (2-5 sentences), factual, and neutral. "
            "Do not add information not present in the text."
        )
        return self._run(instructions, text)

    def analyze_source(self, url: str, content: str) -> str:
        instructions = (
            "You are a news source inspector. "
            "Given a URL, infer the source type (rss, html, js, or api) and "
            "output a YAML snippet that can be pasted under collector.sources. "
            "It MUST match this structure exactly:\n"
            "- name: <string>\n"
            "  url: <string>\n"
            "  type: rss|html|js|api\n"
            "  howto:\n"
            "    rss:\n"
            "      item_limit: <int>\n"
            "      date_field: published|updated\n"
            "    html:\n"
            "      list_selector: <css>\n"
            "      title_selector: <css>\n"
            "      date_selector: <css>\n"
            "      content_selector: <css>\n"
            "    js:\n"
            "      list_selector: <css>\n"
            "      title_selector: <css>\n"
            "      date_selector: <css>\n"
            "      content_selector: <css>\n"
            "      wait_for: <css>\n"
            "      wait_ms: <int>\n"
            "      strategy: browser_automation|api\n"
            "      notes: <string>\n"
            "    api:\n"
            "      items_path: <path>\n"
            "      url_field: <field>\n"
            "      title_field: <field>\n"
            "      date_field: <field>\n"
            "      content_field: <field>\n"
            "Populate only the subsection for the chosen type; omit the others. "
            "Return only YAML, no extra text."
        )
        input_text = f"URL:\n{url}\n\nCONTENT:\n{content}"
        return self._run(instructions, input_text)

    def blog_from_summary(
        self, summary_md: str, markdown_instructions: str | None = None
    ) -> str:
        instructions = (
            "Write a weekly blog post in markdown based on the provided news summary. "
            "Include a Highlights section (bulleted) and a Detailed Coverage section "
            "with short commentary per item. Use clear, professional Chinese."
        )
        if markdown_instructions:
            instructions = (
                f"{instructions}\n\nFormatting rules:\n{markdown_instructions}"
            )
        return self._run(instructions, summary_md)
