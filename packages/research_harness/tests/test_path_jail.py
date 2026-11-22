"""RH_PATH_JAIL keeps caller-supplied paths inside one tree."""

from __future__ import annotations

import pytest

from research_harness import path_jail


@pytest.fixture()
def jail(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "work").mkdir(parents=True)
    monkeypatch.setenv("RH_PATH_JAIL", str(home))
    return home


def test_no_jail_allows_everything(monkeypatch):
    monkeypatch.delenv("RH_PATH_JAIL", raising=False)
    path_jail.check_arguments({"code_path": "/srv/rh/app"}, tool="deposit_zenodo")
    path_jail.check_argv(["exemplar", "plan", "--target-file=/srv/rh/app/x.py"])


def test_inside_jail_allowed(jail):
    path_jail.check_arguments(
        {"output_dir": str(jail / "work")}, tool="figure_generate"
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {"code_path": "/srv/rh/app/research-harness"},
        {"source": "/srv/git/research-harness.git/config"},
        {"figure": {"output_dir": "/srv/rh/app"}},
        {"paths": ["/tmp/ok", "/srv/rh/app"]},
    ],
)
def test_escaping_argument_refused(jail, arguments):
    with pytest.raises(path_jail.PathJailError):
        path_jail.check_arguments(arguments, tool="t")


def test_traversal_and_symlink_refused(jail):
    link = jail / "work" / "peek"
    link.symlink_to("/srv")
    with pytest.raises(path_jail.PathJailError):
        path_jail.check_arguments({"pdf_path": str(link / "rh")}, tool="t")
    with pytest.raises(path_jail.PathJailError):
        path_jail.check_arguments({"pdf_path": f"{jail}/../../srv/rh"}, tool="t")


def test_free_text_is_not_scanned(jail):
    # Prose and identifiers carry slashes; only path-named arguments are checked.
    path_jail.check_arguments(
        {"query": "n/a: see /srv/rh/app", "manuscript": "10.1000/xyz"}, tool="t"
    )
    path_jail.check_arguments({"source": "https://arxiv.org/abs/2401.1"}, tool="t")


def test_argv_both_spellings_refused(jail):
    with pytest.raises(path_jail.PathJailError):
        path_jail.check_argv(["exemplar", "plan", "--target-file", "/srv/rh/app/x"])
    with pytest.raises(path_jail.PathJailError):
        path_jail.check_argv(["exemplar", "plan", "--target-file=/srv/rh/app/x"])
    path_jail.check_argv(["topic", "show", "--name", "direction/max"])


def test_bare_doi_is_an_identifier_not_a_location(jail):
    # `source` is a path word and a DOI carries a slash, so ingesting a paper by
    # DOI was refused on every jailed host.
    path_jail.check_arguments({"source": "10.1038/s41586-021-03819-2"}, tool="t")
    path_jail.check_arguments({"source": "10.1000/xyz"}, tool="t")
    path_jail.check_argv(["paper", "ingest", "--source", "10.1000/xyz"])


def test_doi_shape_does_not_open_the_jail(jail):
    for escape in (
        "10.1234/../../srv/rh/app",
        "10.1234//srv/rh/app",
        "10.1234/x/../../../etc/passwd",
    ):
        with pytest.raises(path_jail.PathJailError):
            path_jail.check_arguments({"source": escape}, tool="t")


def test_a_doi_shaped_path_through_a_planted_link_is_refused(jail, monkeypatch):
    # Reviewer repro: a link named like a DOI prefix inside the jail points outside it, and an
    # output path spelled as a DOI rode the identifier exemption past realpath.
    outside = jail.parent / "outside"
    outside.mkdir()
    (jail / "10.1234").symlink_to(outside, target_is_directory=True)
    monkeypatch.chdir(jail)
    for name in ("output_file", "source"):
        with pytest.raises(path_jail.PathJailError):
            path_jail.check_arguments({name: "10.1234/app.txt"}, tool="t")
    with pytest.raises(path_jail.PathJailError):
        path_jail.check_argv(["paper", "export", "--output-file", "10.1234/app.txt"])


def test_the_doi_exemption_is_only_for_an_ingest_source(jail, monkeypatch):
    monkeypatch.chdir(jail.parent)
    with pytest.raises(path_jail.PathJailError):
        path_jail.check_arguments(
            {"output_file": "10.1038/s41586-021-03819-2"}, tool="t"
        )
    path_jail.check_arguments({"source": "10.1038/s41586-021-03819-2"}, tool="t")
