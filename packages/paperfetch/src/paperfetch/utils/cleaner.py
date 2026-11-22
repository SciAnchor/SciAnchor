# -*- coding: utf-8 -*-
"""
cleaner 模块
提供 MetadataCleanPipeline 类，对抓取到的学术元数据进行文本净化、标签剥离与 Unicode 修复。
"""

import re
import html
from typing import Optional


class MetadataCleanPipeline:
    """
    MetadataCleanPipeline 文本清洗管道

    用于清洗论文标题与摘要，滤除 HTML 标签、转义实体字符、标准化零宽空格及多余空白，提供一致的纯文本输出。
    """

    @staticmethod
    def strip_xml_html_tags(text: str) -> str:
        """
        递归剥离 XML/HTML 标签，同时对 <sup> 与 <sub> 进行纯文本语义替换。

        Args:
            text (str): 待剥离标签的文本。

        Returns:
            str: 剥离后的文本。
        """
        if not text:
            return ""

        # 行内注释：使用正则语义化替换上下标：x<sup>2</sup> -> x^2，x<sub>2</sub> -> x_2
        # 去掉外层括号以使格式更简洁，采用分组匹配
        text = re.sub(r"<(sup|SUP)>(.*?)</\1>", r"^\2", text)
        text = re.sub(r"<(sub|SUB)>(.*?)</\1>", r"_\2", text)

        # 行内注释：剥离其他所有不需要的 HTML/XML 标签对或自闭合标签
        text = re.sub(r"<[^>]+>", "", text)
        return text

    @staticmethod
    def escape_html_entities(text: str) -> str:
        """
        将常见的 HTML 字符实体转义为标准字符。

        Args:
            text (str): 待转义字符。

        Returns:
            str: 转义后的标准字符。
        """
        if not text:
            return ""
        return html.unescape(text)

    @staticmethod
    def clean_unicode_spaces(text: str) -> str:
        """
        移除非 ASCII 零宽字符、非打印控制字符，并压缩连续的空白。

        Args:
            text (str): 输入文本。

        Returns:
            str: 压缩排版后的干净字符串。
        """
        if not text:
            return ""

        # 行内注释：移零宽空格 (\u200b)、零宽不连字 (\u200c)、零宽连字 (\u200d)、字节顺序标记 (\ufeff)
        zero_width_chars = ["\u200b", "\u200c", "\u200d", "\ufeff"]
        for char in zero_width_chars:
            text = text.replace(char, "")

        # 行内注释：压缩非标准 Unicode 空白字符 (如不换行空格 \xa0、全角空格 \u3000) 为单空格
        text = re.sub(r"[\s\u3000\xa0\u2000-\u200a\u2028\u2029]+", " ", text)

        return text.strip()

    @classmethod
    def clean(cls, text: Optional[str]) -> str:
        """
        对输入的源文本执行完整的清洗流水线。

        Args:
            text (Optional[str]): 待清洗的原始字符串。

        Returns:
            str: 净化后的纯文本。
        """
        if not text:
            return ""

        # 1. 剥离格式标签并替换上下标语义
        cleaned = cls.strip_xml_html_tags(text)

        # 2. 还原转义的 HTML 实体字符
        cleaned = cls.escape_html_entities(cleaned)

        # 3. 清理 Unicode 格式杂质及多余空白
        cleaned = cls.clean_unicode_spaces(cleaned)

        return cleaned
