import asyncio
import inspect
from io import BytesIO

import pytest
from pypdf import PdfWriter


@pytest.fixture(autouse=True)
def _reset_spc_settings():
    from paperfetch.core.settings import reset_settings

    reset_settings()
    yield
    reset_settings()


@pytest.fixture
def make_pdf_bytes():
    """生成带论文身份元数据的可解析测试 PDF。"""

    def factory(*, title: str, doi: str = "") -> bytes:
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        metadata = {"/Title": title}
        if doi:
            metadata["/Subject"] = f"doi:{doi}"
        writer.add_metadata(metadata)
        buffer = BytesIO()
        writer.write(buffer)
        return buffer.getvalue()

    return factory


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: run async test functions in a local event loop"
    )


def pytest_pyfunc_call(pyfuncitem):
    if "asyncio" not in pyfuncitem.keywords:
        return None
    testfunction = pyfuncitem.obj
    if not inspect.iscoroutinefunction(testfunction):
        return None

    kwargs = {
        name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames
    }
    asyncio.run(testfunction(**kwargs))
    return True
