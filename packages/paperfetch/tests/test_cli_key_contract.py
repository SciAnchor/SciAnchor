from paperfetch.cli.root import _configure_standard_stream_encoding, _main


def test_cli_reconfigures_real_streams_to_utf8(monkeypatch):
    calls = []

    class Stream:
        def reconfigure(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr("paperfetch.cli.root.sys.stdout", Stream())
    monkeypatch.setattr("paperfetch.cli.root.sys.stderr", Stream())

    _configure_standard_stream_encoding()

    assert calls == [
        {"encoding": "utf-8", "errors": "replace"},
        {"encoding": "utf-8", "errors": "replace"},
    ]
