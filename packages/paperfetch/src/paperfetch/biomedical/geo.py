"""从本地 GEO SOFT 与 filelist 构建公共生物医学事实记录。"""

from __future__ import annotations

import gzip
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from paperfetch.biomedical.models import (
    BiomedicalDatasetRecord,
    DataArtifact,
    Derivation,
    ExperimentalEntity,
    ExperimentalRelation,
    FieldAssertion,
    MeasurementDesign,
    ReplicationLevel,
    ReplicationProfile,
    SourceArtifactSnapshot,
    attach_digest,
)


PARSER_VERSION = "spc.biomedical-geo-parser.v0.1"


@dataclass(frozen=True)
class SoftValue:
    key: str
    value: str
    locator: str


@dataclass
class SoftSection:
    section_type: str
    section_id: str
    values: dict[str, list[SoftValue]] = field(default_factory=dict)

    def add(self, value: SoftValue) -> None:
        self.values.setdefault(value.key, []).append(value)

    def all(self, key: str) -> list[SoftValue]:
        return list(self.values.get(key, []))

    def first(self, key: str) -> SoftValue | None:
        values = self.values.get(key, [])
        return values[0] if values else None


@dataclass(frozen=True)
class GeoSoftDocument:
    series: SoftSection
    samples: tuple[SoftSection, ...]
    platforms: tuple[SoftSection, ...]


def _open_text(path: Path):
    return (
        gzip.open(path, "rt", encoding="utf-8", errors="replace")
        if path.suffix == ".gz"
        else path.open("r", encoding="utf-8", errors="replace")
    )


def parse_geo_soft(path: str | Path) -> GeoSoftDocument:
    """解析本地 SOFT；不访问网络，也不根据上下文补造字段。"""

    source = Path(path).expanduser().resolve()
    sections: list[SoftSection] = []
    current: SoftSection | None = None
    with _open_text(source) as handle:
        for _line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\r\n")
            if line.startswith("^") and "=" in line:
                kind, identifier = (item.strip() for item in line[1:].split("=", 1))
                current = SoftSection(kind.upper(), identifier)
                sections.append(current)
                continue
            if current is None or not line.startswith("!") or "=" not in line:
                continue
            key, value = (item.strip() for item in line[1:].split("=", 1))
            occurrence = len(current.values.get(key, [])) + 1
            current.add(
                SoftValue(
                    key=key,
                    value=value,
                    locator=(
                        f"{source.name}#{current.section_type}:{current.section_id}!"
                        f"{key}[{occurrence}]"
                    ),
                )
            )
    series = next((item for item in sections if item.section_type == "SERIES"), None)
    if series is None:
        raise ValueError(f"SOFT 文件缺少 SERIES 段：{source}")
    return GeoSoftDocument(
        series=series,
        samples=tuple(item for item in sections if item.section_type == "SAMPLE"),
        platforms=tuple(item for item in sections if item.section_type == "PLATFORM"),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _assertion(
    *,
    field_name: str,
    source: SoftValue,
    observed_at: datetime,
    normalized_value=None,
    derivation: Derivation = Derivation.SOURCE_OBSERVED,
    normalization_system: str | None = None,
    requires_review: bool = False,
) -> FieldAssertion:
    return FieldAssertion(
        field_name=field_name,
        raw_value=source.value,
        normalized_value=source.value if normalized_value is None else normalized_value,
        normalization_system=normalization_system,
        source_type="geo_soft",
        source_locator=source.locator,
        observed_at=observed_at,
        availability="present",
        derivation=derivation,
        requires_review=requires_review,
        parser_version=PARSER_VERSION,
    )


def _characteristics(sample: SoftSection) -> dict[str, SoftValue]:
    result: dict[str, SoftValue] = {}
    for item in sample.all("Sample_characteristics_ch1"):
        if ":" not in item.value:
            continue
        key, value = (part.strip() for part in item.value.split(":", 1))
        result[_normalized_token(key)] = SoftValue(item.key, value, item.locator)
    return result


def _group_label(sample: SoftSection) -> tuple[str, SoftValue | None]:
    characteristics = _characteristics(sample)
    treatment = characteristics.get("treatment")
    raw = treatment.value.lower() if treatment else ""
    if "sham" in raw:
        return "sham_control", treatment
    if "ligation" in raw or "dvt" in raw:
        return "dvt_ivc_ligation", treatment
    title = sample.first("Sample_title")
    return _normalized_token(title.value if title else sample.section_id), title


def _pool_counts(
    values: Iterable[SoftValue],
) -> tuple[dict[str, int], SoftValue | None]:
    pattern = re.compile(
        r"single-cell suspensions from\s+(\d+)\s+(.+?)\s+or\s+(\d+)\s+(.+?)\s+were pooled together as one sample",
        re.IGNORECASE,
    )
    for item in values:
        match = pattern.search(item.value)
        if not match:
            continue
        counts: dict[str, int] = {}
        for count, label in (
            (match.group(1), match.group(2)),
            (match.group(3), match.group(4)),
        ):
            lowered = label.lower()
            if "sham" in lowered:
                counts["sham_control"] = int(count)
            elif "dvt" in lowered or "ligation" in lowered:
                counts["dvt_ivc_ligation"] = int(count)
            else:
                counts[_normalized_token(label)] = int(count)
        return counts, item
    return {}, None


def _parse_reported_counts(
    document: GeoSoftDocument,
) -> tuple[int | None, int | None, SoftValue | None]:
    for item in document.series.all("Series_summary"):
        match = re.search(
            r"([\d,]+)\s+single cells\s+from\s+(\d+)\s+patients",
            item.value,
            re.IGNORECASE,
        )
        if match:
            return int(match.group(2)), int(match.group(1).replace(",", "")), item
    return None, None, None


def _parse_filelist(path: Path | None) -> list[tuple[str, int | None, str]]:
    if path is None or not path.is_file():
        return []
    result: list[tuple[str, int | None, str]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        if not line or line.startswith("#") or line.startswith("Archive/File"):
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        name = parts[1].strip()
        size = int(parts[3]) if parts[3].strip().isdigit() else None
        result.append((name, size, f"{path.name}#line:{line_number}"))
    return result


def _artifact_kind(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith("_raw.tar"):
        return "raw_archive"
    if (
        "adult_or_peidatric" in lowered
        or "annotation" in lowered
        or lowered.endswith(".xlsx")
    ):
        return "sample_annotation"
    if any(marker in lowered for marker in ("matrix", "tpm", "count")):
        return "processed_expression_matrix"
    return "supplementary_file"


def _build_artifacts(
    document: GeoSoftDocument,
    dataset_dir: Path,
    soft_path: Path,
    filelist_path: Path | None,
) -> list[DataArtifact]:
    urls: dict[str, tuple[str, str]] = {}
    for section in (document.series, *document.samples):
        for key, values in section.values.items():
            if "supplementary_file" not in key.lower():
                continue
            for item in values:
                filename = Path(item.value).name
                urls[filename] = (item.value, item.locator)
    artifacts: list[DataArtifact] = []
    listed: set[str] = set()
    for filename, size, locator in _parse_filelist(filelist_path):
        listed.add(filename)
        local = dataset_dir / filename
        source_url, soft_locator = urls.get(filename, (None, locator))
        artifacts.append(
            DataArtifact(
                artifact_id=_normalized_token(filename)[:120],
                filename=filename,
                kind=_artifact_kind(filename),
                source_url=source_url,
                size_bytes=size,
                sha256=_sha256(local) if local.is_file() else None,
                local_path=str(local) if local.is_file() else None,
                availability="local_verified"
                if local.is_file()
                else "remote_available",
                source_locator=soft_locator,
            )
        )
    for filename, (source_url, locator) in sorted(urls.items()):
        if filename in listed:
            continue
        local = dataset_dir / filename
        artifacts.append(
            DataArtifact(
                artifact_id=_normalized_token(filename)[:120],
                filename=filename,
                kind=_artifact_kind(filename),
                source_url=source_url,
                size_bytes=local.stat().st_size if local.is_file() else None,
                sha256=_sha256(local) if local.is_file() else None,
                local_path=str(local) if local.is_file() else None,
                availability="local_verified"
                if local.is_file()
                else "remote_available",
                source_locator=locator,
            )
        )
    for role, path in (("geo_soft", soft_path), ("geo_filelist", filelist_path)):
        if path is None or not path.is_file():
            continue
        artifacts.append(
            DataArtifact(
                artifact_id=f"source_{role}",
                filename=path.name,
                kind="source_metadata",
                size_bytes=path.stat().st_size,
                sha256=_sha256(path),
                local_path=str(path),
                availability="local_verified",
                source_locator=path.name,
            )
        )
    return artifacts


def build_geo_dataset_record(
    soft_file: str | Path,
    *,
    filelist_file: str | Path | None = None,
    observed_at: datetime | None = None,
) -> BiomedicalDatasetRecord:
    """基于本地来源文件构建记录；搜索和检查阶段不会隐式下载。"""

    soft_path = Path(soft_file).expanduser().resolve()
    filelist_path = (
        Path(filelist_file).expanduser().resolve() if filelist_file else None
    )
    observed = observed_at or datetime.now(timezone.utc)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("observed_at 必须包含 UTC 偏移")
    document = parse_geo_soft(soft_path)
    accession = document.series.section_id.upper()
    title_value = document.series.first("Series_title")
    if title_value is None:
        raise ValueError("GEO SOFT 缺少 Series_title")
    summary_values = document.series.all("Series_summary")
    summary = " ".join(item.value for item in summary_values) or None
    assertions: list[FieldAssertion] = [
        _assertion(field_name="dataset.title", source=title_value, observed_at=observed)
    ]
    assertions.extend(
        _assertion(field_name="dataset.summary", source=item, observed_at=observed)
        for item in summary_values
    )

    organisms: set[str] = set()
    tissues: set[str] = set()
    groups: dict[str, SoftValue | None] = {}
    all_protocols: list[SoftValue] = []
    platforms: set[str] = set()
    assay_technologies: set[str] = set()
    measurement_spaces: set[str] = set()
    library_strategies: set[str] = set()
    reference_genomes: set[str] = set()
    modalities: set[str] = set()
    feature_spaces: set[str] = set()
    for sample in document.samples:
        organism = sample.first("Sample_organism_ch1")
        if organism:
            normalized = organism.value.strip()
            organisms.add(normalized)
            assertions.append(
                _assertion(
                    field_name="biological.organism",
                    source=organism,
                    observed_at=observed,
                    normalized_value=normalized,
                    derivation=Derivation.DETERMINISTIC_NORMALIZATION,
                    normalization_system="NCBI_Taxonomy_label",
                )
            )
        source_name = sample.first("Sample_source_name_ch1")
        if source_name:
            tissue = _normalized_token(source_name.value)
            tissues.add(tissue)
            assertions.append(
                _assertion(
                    field_name="biological.tissue",
                    source=source_name,
                    observed_at=observed,
                    normalized_value=tissue,
                    derivation=Derivation.DETERMINISTIC_NORMALIZATION,
                    normalization_system="spc.anatomy.v0.1",
                )
            )
        group_id, group_source = _group_label(sample)
        groups[group_id] = group_source
        if group_source:
            assertions.append(
                _assertion(
                    field_name="experimental.group",
                    source=group_source,
                    observed_at=observed,
                    normalized_value=group_id,
                    derivation=Derivation.DETERMINISTIC_NORMALIZATION,
                    normalization_system="spc.experimental-group.v0.1",
                )
            )
        all_protocols.extend(sample.all("Sample_extract_protocol_ch1"))
        all_protocols.extend(sample.all("Sample_treatment_protocol_ch1"))
        instrument = sample.first("Sample_instrument_model")
        if instrument:
            platforms.add(instrument.value)
        strategy = sample.first("Sample_library_strategy")
        if strategy:
            library_strategies.add(strategy.value)
        signals = " ".join(
            item.value
            for key in (
                "Sample_library_source",
                "Sample_characteristics_ch1",
                "Sample_extract_protocol_ch1",
            )
            for item in sample.all(key)
        ).lower()
        if "single cell" in signals or "single-cell" in signals:
            modalities.add("single_cell_rna_seq")
        if "smart-seq2" in signals or "smartseq2" in signals:
            assay_technologies.add("Smart-seq2")
            measurement_spaces.add("smartseq2_full_length_expression")
        if "10x" in signals or "chromium" in signals:
            assay_technologies.add("10X Chromium")
            measurement_spaces.add("10x_droplet_expression")
        for item in sample.all("Sample_data_processing"):
            for match in re.findall(
                r"(?:assembly|genome_build)\s*:\s*([A-Za-z0-9_.-]+)",
                item.value,
                re.IGNORECASE,
            ):
                reference_genomes.add(match)
            lowered = item.value.lower()
            if "tpm" in lowered:
                feature_spaces.add("TPM")
            if "umi count" in lowered or "feature counts" in lowered:
                feature_spaces.add("raw_UMI_counts")

    combined_series = f"{title_value.value} {summary or ''}".lower()
    if any(
        marker in combined_series
        for marker in ("single-cell rna", "single cell rna", "scrna-seq")
    ):
        modalities.add("single_cell_rna_seq")
    if "smartseq2" in combined_series or "smart-seq2" in combined_series:
        assay_technologies.add("Smart-seq2")
        measurement_spaces.add("smartseq2_full_length_expression")
    if "10x" in combined_series:
        assay_technologies.add("10X Chromium")
        measurement_spaces.add("10x_droplet_expression")
    disease_terms: list[str] = []
    if "deep vein thrombosis" in combined_series:
        disease_terms.append("deep_vein_thrombosis")
    if "glioblastoma" in combined_series:
        disease_terms.append(
            "glioblastoma_idh_wildtype"
            if "idh-wildtype" in combined_series
            else "glioblastoma"
        )

    pool_counts, pool_source = _pool_counts(all_protocols)
    patient_count, reported_cell_count, reported_count_source = _parse_reported_counts(
        document
    )
    entities: list[ExperimentalEntity] = [
        ExperimentalEntity(
            entity_id=f"geo:{accession}",
            entity_type="project",
            label=accession,
            source_locators=[title_value.locator],
        )
    ]
    relations: list[ExperimentalRelation] = []
    if patient_count is not None and reported_count_source is not None:
        cohort_id = f"geo:{accession}:reported-patient-cohort"
        entities.append(
            ExperimentalEntity(
                entity_id=cohort_id,
                entity_type="cohort",
                label="来源报告的患者队列",
                aggregate_count=patient_count,
                count_scope="total",
                source_locators=[reported_count_source.locator],
            )
        )
        relations.append(
            ExperimentalRelation(
                relation_id=f"{cohort_id}:within:{accession}",
                source_entity_id=cohort_id,
                target_entity_id=f"geo:{accession}",
                relation_type="nested_within",
                source_locator=reported_count_source.locator,
            )
        )
        assertions.append(
            _assertion(
                field_name="count.reported_patients",
                source=reported_count_source,
                observed_at=observed,
                normalized_value=patient_count,
                derivation=Derivation.DETERMINISTIC_NORMALIZATION,
            )
        )
        assertions.append(
            _assertion(
                field_name="count.reported_single_cells",
                source=reported_count_source,
                observed_at=observed,
                normalized_value=reported_cell_count,
                derivation=Derivation.DETERMINISTIC_NORMALIZATION,
            )
        )

    group_entities: dict[str, str] = {}
    for group_id, count in sorted(pool_counts.items()):
        entity_id = f"geo:{accession}:subject-group:{group_id}"
        group_entities[group_id] = entity_id
        entities.append(
            ExperimentalEntity(
                entity_id=entity_id,
                entity_type="subject_group",
                label=group_id,
                group_id=group_id,
                aggregate_count=count,
                count_scope="per_group",
                source_locators=[pool_source.locator] if pool_source else [],
            )
        )
        relations.append(
            ExperimentalRelation(
                relation_id=f"{entity_id}:within:{accession}",
                source_entity_id=entity_id,
                target_entity_id=f"geo:{accession}",
                relation_type="nested_within",
                source_locator=pool_source.locator
                if pool_source
                else title_value.locator,
            )
        )
    if pool_source:
        assertions.append(
            _assertion(
                field_name="experimental.pooling_before_library",
                source=pool_source,
                observed_at=observed,
                normalized_value=True,
                derivation=Derivation.DETERMINISTIC_NORMALIZATION,
            )
        )

    sample_groups: dict[str, str] = {}
    for sample in document.samples:
        gsm = sample.section_id
        group_id, group_source = _group_label(sample)
        sample_groups[gsm] = group_id
        sample_id = f"geo:{accession}:sample:{gsm}"
        suspension_id = f"geo:{accession}:cell-suspension:{gsm}"
        library_id = f"geo:{accession}:library:{gsm}"
        locator = (sample.first("Sample_title") or group_source or title_value).locator
        entities.extend(
            [
                ExperimentalEntity(
                    entity_id=sample_id,
                    entity_type="biological_sample",
                    label=gsm,
                    group_id=group_id,
                    source_locators=[locator],
                ),
                ExperimentalEntity(
                    entity_id=suspension_id,
                    entity_type="cell_suspension",
                    label=f"{gsm} cell suspension",
                    group_id=group_id,
                    source_locators=[locator],
                ),
                ExperimentalEntity(
                    entity_id=library_id,
                    entity_type="library",
                    label=f"{gsm} library",
                    group_id=group_id,
                    source_locators=[locator],
                ),
            ]
        )
        relations.extend(
            [
                ExperimentalRelation(
                    relation_id=f"{sample_id}:within:{accession}",
                    source_entity_id=sample_id,
                    target_entity_id=f"geo:{accession}",
                    relation_type="nested_within",
                    source_locator=locator,
                ),
                ExperimentalRelation(
                    relation_id=f"{suspension_id}:from:{sample_id}",
                    source_entity_id=suspension_id,
                    target_entity_id=sample_id,
                    relation_type="derived_from",
                    source_locator=locator,
                ),
                ExperimentalRelation(
                    relation_id=f"{library_id}:from:{suspension_id}",
                    source_entity_id=library_id,
                    target_entity_id=suspension_id,
                    relation_type="derived_from",
                    source_locator=locator,
                ),
            ]
        )
        if group_id in group_entities and pool_source:
            relations.append(
                ExperimentalRelation(
                    relation_id=f"{sample_id}:pooled-from:{group_id}",
                    source_entity_id=sample_id,
                    target_entity_id=group_entities[group_id],
                    relation_type="pooled_from",
                    source_locator=pool_source.locator,
                )
            )

    dataset_dir = soft_path.parent
    artifacts = _build_artifacts(document, dataset_dir, soft_path, filelist_path)
    for artifact in artifacts:
        gsm = next(
            (
                candidate
                for candidate in sample_groups
                if artifact.filename.startswith(candidate)
            ),
            None,
        )
        if gsm is None:
            continue
        file_id = f"geo:{accession}:file:{artifact.artifact_id}"
        entities.append(
            ExperimentalEntity(
                entity_id=file_id,
                entity_type="data_file",
                label=artifact.filename,
                group_id=sample_groups[gsm],
                source_locators=[artifact.source_locator],
            )
        )
        relations.append(
            ExperimentalRelation(
                relation_id=f"{file_id}:from-library:{gsm}",
                source_entity_id=file_id,
                target_entity_id=f"geo:{accession}:library:{gsm}",
                relation_type="derived_from",
                source_locator=artifact.source_locator,
            )
        )

    if pool_counts:
        replication = ReplicationProfile(
            pooling_detected=True,
            subject_sample_mapping="missing",
            biological_group_units_recoverable=False,
            levels=[
                ReplicationLevel(
                    entity_type="animal",
                    total=sum(pool_counts.values()),
                    per_group=pool_counts,
                    independence="partially_confirmed",
                    usable_for_group_inference=False,
                    reason="来源报告了每组动物数，但建库前按组池化，个体身份和个体表达不可恢复",
                    source_locators=[pool_source.locator] if pool_source else [],
                ),
                ReplicationLevel(
                    entity_type="library",
                    total=len(document.samples),
                    per_group={group: 1 for group in pool_counts},
                    independence="not_independent",
                    usable_for_group_inference=False,
                    reason="每组只有一个池化样本文库，不能估计组内动物变异",
                    source_locators=[pool_source.locator] if pool_source else [],
                ),
            ],
        )
    else:
        mapping_artifact = any(item.kind == "sample_annotation" for item in artifacts)
        replication = ReplicationProfile(
            pooling_detected=False,
            subject_sample_mapping="partial" if mapping_artifact else "unknown",
            biological_group_units_recoverable=None,
            levels=[
                ReplicationLevel(
                    entity_type="patient"
                    if patient_count is not None
                    else "biological_sample",
                    total=patient_count,
                    per_group={},
                    independence="partially_confirmed"
                    if patient_count is not None
                    else "unknown",
                    usable_for_group_inference=False,
                    reason=(
                        "来源报告患者总数，但 SOFT 未包含逐患者到细胞/样本的映射；需校验注释制品"
                        if patient_count is not None
                        else "来源未提供可恢复的独立受试者映射"
                    ),
                    source_locators=[reported_count_source.locator]
                    if reported_count_source
                    else [],
                )
            ],
        )

    series_design = " ".join(
        item.value for item in document.series.all("Series_overall_design")
    )
    time_design = "unknown"
    if re.search(r"after\s+24\s+hours", series_design, re.IGNORECASE) and {
        "sham_control",
        "dvt_ivc_ligation",
    }.issubset(groups):
        time_design = "single_timepoint_cross_sectional"

    snapshots = [
        SourceArtifactSnapshot(
            role="geo_soft",
            path=soft_path.name,
            sha256=_sha256(soft_path),
            bytes=soft_path.stat().st_size,
        )
    ]
    if filelist_path and filelist_path.is_file():
        snapshots.append(
            SourceArtifactSnapshot(
                role="geo_filelist",
                path=filelist_path.name,
                sha256=_sha256(filelist_path),
                bytes=filelist_path.stat().st_size,
            )
        )

    unresolved: list[str] = []
    if pool_counts:
        unresolved.extend(
            [
                "池化前的单只动物身份与逐动物表达无法从公共制品恢复",
                "8,000 表示每个样本上机加载细胞数，不是独立生物学重复数",
                "sham surgery 是手术对照，不能自动规范为未处理健康正常组织",
                "24 小时单时点的不同动物组不是纵向配对设计",
            ]
        )
    if patient_count is not None:
        unresolved.extend(
            [
                "逐患者、成人/儿童、肿瘤与单细胞映射需要下载并校验注释制品",
                "Smart-seq2 与 10X 测量空间不同，不能仅凭同一 GSE 直接合并原始矩阵",
            ]
        )

    payload = {
        "schema_version": "spc.biomedical-dataset-record.v0.1",
        "lifecycle_status": "provisional",
        "dataset_ref": f"dataset:geo:{accession}@soft-{_sha256(soft_path)[:16]}",
        "source": "NCBI_GEO",
        "accession": accession,
        "title": title_value.value,
        "summary": summary,
        "organisms": sorted(organisms),
        "disease_terms": disease_terms,
        "tissue_terms": sorted(tissues),
        "field_assertions": [item.model_dump(mode="json") for item in assertions],
        "entities": [item.model_dump(mode="json") for item in entities],
        "relations": [item.model_dump(mode="json") for item in relations],
        "replication_profile": replication.model_dump(mode="json"),
        "measurement_design": MeasurementDesign(
            modalities=sorted(modalities),
            platforms=sorted(platforms),
            assay_technologies=sorted(assay_technologies),
            measurement_spaces=sorted(measurement_spaces),
            library_strategies=sorted(library_strategies),
            reference_genomes=sorted(reference_genomes),
            feature_spaces=sorted(feature_spaces),
            time_design=time_design,
        ).model_dump(mode="json"),
        "artifacts": [item.model_dump(mode="json") for item in artifacts],
        "unresolved_questions": unresolved,
        "source_snapshots": [item.model_dump(mode="json") for item in snapshots],
        "parsed_at": observed.isoformat(),
    }
    return BiomedicalDatasetRecord.model_validate(
        attach_digest(
            payload,
            excluded_fields=frozenset(
                {"content_digest", "parsed_at", "observed_at", "local_path"}
            ),
        )
    )
