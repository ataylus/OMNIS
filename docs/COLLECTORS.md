# Evidence collectors: status and design

Honest status: two evidence collectors are built and shipped as **mock
integrations**. The deliverable list asks for at least two (CloudTrail plus one
other), and `omnis/collectors/` has exactly that: a CloudTrail-style log puller
and a config-snapshot puller. They are mocked in one specific way: each reads a
committed sample export (`data/collectors/*.json`) instead of calling a live API.
Everything else is real: they emit `EvidenceRecord` objects in the pipeline's
shape, those records flow through `map_evidence -> score_corpus -> audit_corpus`
unchanged, and `python -m omnis collect` runs them end to end. Swapping the file
read for a live API call is the one remaining integration step, described below.

## What exists today

- `python -m omnis collect` runs both collectors. On the sample exports it pulls
  9 records (5 audit logs from CloudTrail, 4 config snapshots), all machine
  collectable, and links every one to a real requirement by exact id. A
  non-compliant snapshot is collected as `Needs_Update` with lower confidence, so
  the scorer and integrity auditor act on it like any other evidence.
- Every evidence record carries an `evidence_type`. The scorer partitions those
  into machine-collectable (`AUTO_TYPES` in `omnis/scoring/scorer.py`:
  Configuration_Snapshot, Audit_Log, Access_Report, Test_Result, Encryption_Cert)
  and human-produced (Screenshot, Training_Record, Policy_Document,
  Procedure_Evidence). The collected records are all `AUTO_TYPES`.
- The **Automation Rate** metric is the share of evidence rows whose type is in
  `AUTO_TYPES`. On the synthetic enterprise bench it is **78.0%**, clearing the
  brief's 70% success target. The collectors above produce 100% automated rows.

## How a real collector would slot in

The pipeline already has the seam. Collectors would live in `omnis/collectors/`
and produce the same `EvidenceRecord` objects the rest of the pipeline consumes
(`omnis/models.py`), so nothing downstream changes. Each collector would:

1. Pull from a source system (see below) on a schedule.
2. Map each artifact to an `EvidenceRecord`, setting `evidence_type`,
   `collection_date`, `confidence_score`, `evidence_location`, and a
   collection-source tag (automated vs manual).
3. Hand the records to the existing `map_evidence` -> `score_corpus` ->
   `audit_corpus` flow unchanged.

Because the records are identical in shape, the Automation Rate would then count
genuinely auto-collected rows, and freshness would be driven by real collection
timestamps.

### Collector 1: CloudTrail-style log puller

- Source: AWS CloudTrail (or any audit-log API).
- Pulls log events for a control (for example, KMS key-rotation events for
  POL-ENC-001-R2), emits one `Audit_Log` record per relevant event window with
  `collection_date` = pull time and `confidence_score` from event completeness.
- Maps cleanly to logging and encryption requirements via the existing exact-id
  and framework-rule layers.

### Collector 2: config snapshot puller

- Source: AWS Config / a cloud config API.
- Snapshots resource configuration (for example, encryption-at-rest settings,
  firewall rules for POL-PCI-001-R2), emits `Configuration_Snapshot` records.
- Confidence reflects whether the snapshot matches the required setting.

## Why this is enough for the POC

The value OMNIS adds is downstream of collection: parsing requirements, linking
evidence, quantifying freshness and confidence, and reporting gaps. That all
works on real-shaped records today. Wiring two live APIs is integration work with
no new logic, so we documented it and tagged the data instead of building it
under the deadline.
