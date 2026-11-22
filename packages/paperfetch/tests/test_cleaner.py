# -*- coding: utf-8 -*-
"""
test_cleaner.py
针对 MetadataCleanPipeline 元数据清洗管道进行单元测试。
"""

from paperfetch.utils.cleaner import MetadataCleanPipeline


def test_cleaner_strip_tags():
    pipeline = MetadataCleanPipeline()
    # 1. 测试上下标提取与语义化替换
    text1 = "E = mc<sup>2</sup> and H<sub>2</sub>O"
    assert pipeline.strip_xml_html_tags(text1) == "E = mc^2 and H_2O"

    # 2. 测试其他常规 XML/HTML 标签剥离
    text2 = "<div>Hello <b>World</b>!</div>"
    assert pipeline.strip_xml_html_tags(text2) == "Hello World!"


def test_cleaner_escape_entities():
    pipeline = MetadataCleanPipeline()
    # 3. 测试 HTML 实体转义还原
    assert pipeline.escape_html_entities("A &amp; B &lt; C") == "A & B < C"
    assert pipeline.escape_html_entities("John&apos;s Paper") == "John's Paper"


def test_cleaner_unicode_spaces():
    pipeline = MetadataCleanPipeline()
    # 4. 测试零宽字符过滤
    text = "Hello\u200bWorld\ufeff!"
    assert pipeline.clean_unicode_spaces(text) == "HelloWorld!"

    # 5. 测试多余连续空白、全角空格、不换行空格压缩
    text2 = "  Hello \t\n  World \xa0\u3000! "
    assert pipeline.clean_unicode_spaces(text2) == "Hello World !"


def test_cleaner_integrate():
    # 6. 测试整条清洗管道的集成清洗效果
    raw_text = "  <div>E &amp; mc<sup>2</sup>\u200b</div>  "
    assert MetadataCleanPipeline.clean(raw_text) == "E & mc^2"
