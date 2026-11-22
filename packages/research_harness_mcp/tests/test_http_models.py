import pytest
from pydantic import ValidationError


def test_http_models_preserve_http_api_aliases():
    from research_harness_mcp import http_api, http_models

    assert http_api.PaginationMeta is http_models.PaginationMeta
    assert http_api.PaginatedResponse is http_models.PaginatedResponse
    assert http_api.DomainSummary is http_models.DomainSummary
    assert http_api.DomainDetail is http_models.DomainDetail
    assert http_api.CreateDomainRequest is http_models.CreateDomainRequest
    assert http_api.PatchDomainRequest is http_models.PatchDomainRequest
    assert http_api.PatchTopicRequest is http_models.PatchTopicRequest
    assert http_api.TopicSummary is http_models.TopicSummary
    assert http_api.TopicDetail is http_models.TopicDetail
    assert http_api.PaperDetail is http_models.PaperDetail
    assert http_api.RecordArtifactRequest is http_models.RecordArtifactRequest
    assert http_api.ForceAdvanceRequest is http_models.ForceAdvanceRequest
    assert http_api.CreateExperimentRequest is http_models.CreateExperimentRequest
    assert http_api.CreateTopicRequest is http_models.CreateTopicRequest
    assert http_api.AdvanceRequest is http_models.AdvanceRequest
    assert http_api.ExpansionRequest is http_models.ExpansionRequest
    assert http_api.PaperIngestRequest is http_models.PaperIngestRequest
    assert http_api.BatchEnrichRequest is http_models.BatchEnrichRequest
    assert http_api.RollbackRequest is http_models.RollbackRequest


def test_patch_topic_request_keeps_clear_domain_id_and_forbids_extra_fields():
    from research_harness_mcp.http_models import PatchTopicRequest

    request = PatchTopicRequest(name="Topic", domain_id=None)

    assert request.name == "Topic"
    assert request.domain_id is None
    with pytest.raises(ValidationError):
        PatchTopicRequest(name="Topic", unexpected=True)


def test_experiment_and_expansion_request_defaults_stay_stable():
    from research_harness_mcp.http_models import (
        CreateExperimentRequest,
        ExpansionRequest,
    )

    experiment = CreateExperimentRequest(
        task_description="Run task",
        primary_metric="score",
    )
    expansion = ExpansionRequest()

    assert experiment.name == ""
    assert experiment.fixture_files == {}
    assert experiment.mode == "agent"
    assert experiment.timeout_sec == 300.0
    assert experiment.max_iterations == 5
    assert expansion.retrieval_target == 100
    assert expansion.deep_read_target == 20
    assert expansion.rounds == 3
