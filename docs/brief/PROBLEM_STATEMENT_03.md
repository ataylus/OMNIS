#  Problem Statement 03: Automated Compliance Evidence Collection & Audit

> **Enterprise Challenge:** Auditors ask "Prove your controls are working" — governance teams spend weeks gathering evidence instead of managing risk.

---

## The Business Problem

**Scenario:** Enterprise must prove compliance with:
- SOX (financial controls)
- GDPR (data protection)
- HIPAA (healthcare data)
- PCI-DSS (payment card data)
- ISO 27001 (information security)
- NIST Cybersecurity Framework

**Current Process (Manual & Slow):**
```
1. Auditor asks: "Show me evidence that encryption is working"
   ↓
2. Compliance team sends emails to:
   - Infrastructure team ("Get me encryption logs")
   - Security team ("Get me key rotation records")
   - Database team ("Get me access controls")
   ↓
3. Teams gather data (3-5 days)
   ↓
4. Compliance team manually correlates evidence
   ↓
5. Generates audit report (Excel!?)
   ↓
6. Auditor reviews, requests clarifications (iteration cycle)
```

**The Pain:**
-  **72+ hours per audit** (manual gathering & correlation)
-  **Inconsistent evidence** (different people document differently)
-  **Missing audit trails** (discovered mid-audit that evidence wasn't captured)
-  **High cost** (auditor time, internal resources)
-  **Compliance gaps** (evidence not captured = control fails)

**Real Impact:**
- Audit failures delay project approvals by 4-6 weeks
- Controls fail not because they don't exist, but because evidence wasn't documented
- Compliance team is reactive bottleneck, not strategic

---

## Challenge Overview

Build a system to:
1. **Automatically collect** evidence from control systems (logs, configs, reports)
2. **Link evidence** to specific policy requirements
3. **Track** evidence over time (audit trails)
4. **Generate** compliance reports automatically
5. **Enable auditor** to query compliance status with confidence

---

##  Data Reality & Edge Cases

**Real-World Complexity:**
- Evidence formats vary wildly (PDFs, CSVs, API responses, plain text)
- Policy documents poorly written (ambiguous requirements, overlap between policies)
- Automation incomplete (some evidence manual, some automated)
- Historical data gaps (evidence not captured 2+ years ago)
- Compliance framework conflicts (GDPR vs SOX requirements differ)

**Ambiguity You Must Handle:**
- Is evidence "recent enough" to prove compliance? (last month? last quarter?)
- Multiple pieces of evidence for one requirement (which is most important?)
- Conflicting evidence ("Encryption enabled" but "Key rotation untested")
- Temporal gaps (evidence captured 3 months ago, is control still working?)
- Third-party evidence (vendor certifications, can we trust?)

**Your Challenge:**
- **Parse poorly written policies** using NLP (extract clear requirements)
- **Link evidence intelligently** (not all evidence applies to all requirements)
- **Handle missing evidence** (no panic - explain gaps clearly)
- **Generate audit narratives** (LLM-powered: explain compliance posture)

---

##  Approach Options

### Option A: LLM-Powered Evidence Intelligence (Advanced)
**Best for:** NLP enthusiasts, AI engineers

**Technical Approach:**
- **Extract policy requirements** from documents using LLM (fine-tuned ChatGPT) or open-source models
  - Input: "All data at rest must be encrypted using AES-256 or stronger"
  - Output: Structured rule: `{requirement: "encryption", standard: "AES-256+", scope: "data_at_rest"}`
- **Map controls to policies** using semantic search
  - Find all evidence that supports "We use AES-256 encryption"
- **Auto-generate audit narratives:**
  - "We require AES-256 encryption (GDPR Article 32, NIST SC-7). Evidence: AWS KMS configured with AES-256 (last verified 2026-04-15). Status: COMPLIANT"
- **Create audit-ready reports** with LLM-generated executive summaries

**Stack:** Python, Hugging Face Transformers / OpenAI API, semantic search (embeddings), Pandas, reporting
**Complexity:**  (5/5)
**Effort:** 45-55 hours

---

### Option B: Evidence Linking & Automation (Intermediate)
**Best for:** Data + backend engineers

**Technical Approach:**
- Build evidence collection pipeline:
  - Query logs from Splunk/CloudTrail
  - Extract configs from AWS Config, Kubernetes, etc.
  - Fetch audit reports from tools (antivirus, 2FA systems)
- Create mapping database:
  ```
  Policy Requirement ← Links to → Control System ← Links to → Evidence Location
  "Encryption required" ← AWS KMS ← CloudTrail logs
  "Access logging" ← Okta ← IAM audit trails
  ```
- Evidence validator:
  - Has evidence been captured in last 30 days?
  - Is evidence non-repudiable (signed logs)?
  - Does evidence prove requirement was met?
- Generate compliance scorecard (pass/fail per requirement)

**Stack:** Python, data connectors (boto3, requests), SQL database, basic web UI (Flask)
**Complexity:**  (3/5)
**Effort:** 30-40 hours

---

### Option C: Simple Compliance Dashboard (Beginner)
**Best for:** Full-stack web developers, non-technical analysts

**Technical Approach:**
- Build web app interface to manage evidence
- Manual or semi-automated evidence uploads (CSV, PDF, log files)
- Tag evidence to requirements:
  - Select policy: "GDPR Article 32"
  - Select requirement: "Encryption required"
  - Upload evidence: "AWS KMS Report 2026-04-15.pdf"
- Compliance report generator:
  - Shows % requirements with evidence
  - Red/Yellow/Green status indicators
  - Export to PDF for auditor
- Simple search: "Show all evidence for SOX compliance"

**Stack:** Python (Flask/Django), PostgreSQL, basic HTML/CSS/JS, PDF generation
**Complexity:**  (2/5)
**Effort:** 20-30 hours

---

## Sample Data Provided

**Files in `sample_data/`:**

| File | Records | Coverage | Description |
|------|---------|----------|-------------|
| `policy_documents.txt` | 6 policies | GDPR, SOX, NIST, PCI-DSS, ISO 27001, HIPAA | Raw policy text with requirement markers |
| `evidence_artifacts.csv` | 500 | Collected evidence records | Who collected, when, freshness, review status, confidence score |
| `evidence_labels.csv` | 500 | All evidence records | Ground truth: is_anomaly, anomaly_type, severity, explanation |

**Anomaly distribution in labels:**
- Stale evidence: evidence older than 90 days without approval (~34%)
- Missing documentation: incomplete evidence for requirements (~14%)
- Low confidence evidence: approved but below threshold (~15%)
- Rejected evidence: reviewed and rejected (~7%)

**Self-Evaluation:**
```python
import pandas as pd
from sklearn.metrics import precision_score, recall_score

labels = pd.read_csv('evidence_labels.csv')
# labels['predicted_anomaly'] = your_classifier.predict(evidence_artifacts)

y_true = labels['is_anomaly'].astype(int)
y_pred = labels['predicted_anomaly'].astype(int)

print(f"Precision: {precision_score(y_true, y_pred):.2%}")
print(f"Recall:    {recall_score(y_true, y_pred):.2%}")
# Aim for precision > 70%, recall > 60% for a strong submission
```

**Note on the original problem description scale:** The 50 policies / 5,000 evidence records referenced above reflects the *target production scale* your solution should be designed to handle. The sample dataset (500 records) is your development and validation set.

**Example Policy Document:**
```
POLICY: Data Protection and Encryption

REQUIREMENT 1: All personal data must be encrypted at rest using
cryptographic methods approved in NIST SP 800-175B.

REQUIREMENT 2: Encryption keys must be rotated annually
with audit logs maintained.

Maps to:
- GDPR Article 32 (Security)
- NIST SC-7 (Boundary Protection)
- SOX 404 (Internal Controls)
```

**Example Evidence Record:**
```json
{
  "evidence_id": "EV-0012345",
  "type": "aws_config_snapshot",
  "timestamp": "2026-04-15T09:00:00Z",
  "requirement_id": "REQ-ENC-001",
  "content": "AWS KMS configured with AES-256 encryption on RDS instance prod-db-01",
  "compliance_framework": ["GDPR", "SOX", "NIST"],
  "verified": true,
  "auditor_notes": ""
}
```

---

##  Success Criteria

| Metric | Target | Why |
|--------|--------|-----|
| **Evidence Coverage** | 90%+ requirements have evidence | Can pass audit |
| **Time-to-Report** | < 15 min | Enable on-demand auditing |
| **Evidence Freshness** | < 7 days old | Current control status known |
| **Auditor Confidence** | 4.5+/5 rating | Evidence is trustworthy |
| **Automation Rate** | 70%+ evidence auto-collected | Reduces manual work |

---

##  Deliverables

-  **Policy parser** (extracts requirements from documents)
-  **Evidence mapping engine** (links requirements to data sources)
-  **Compliance report generator** (audit-ready PDFs)
-  **Dashboard/UI** (query compliance status)
-  **Evidence collector** (at least 2 integrations: CloudTrail + one other)
-  **Sample audit report** (10-15 requirements with evidence)

---

##  Compliance Frameworks Included

- **GDPR:** Articles 5, 32, 33, 35, 36
- **SOX 404:** Internal Controls Assessment
- **NIST SP 800-53:** AC-2, AU-2, CA-6, CP-2, SC-7
- **ISO 27001:** A.6, A.10, A.12, A.13
- **PCI-DSS:** Requirements 1-12

---

##  Tips for Success

1. **Start with one requirement:** "Prove data is encrypted" → build from there
2. **Map evidence manually first:** Understand relationships before automating
3. **Test with auditor:** "Would you accept this as evidence?"
4. **Version control everything:** Policy versions, evidence versions, report versions
5. **Audit trail is key:** Track who collected what evidence when

---

##  Expected Output

```
COMPLIANCE REPORT - Q2 2026
Generated: 2026-04-15 | Period: 2026-01-01 to 2026-03-31

EXECUTIVE SUMMARY
================
Overall Compliance: 87% (up from 81% in Q1)
Requirements Covered: 178/200 (89%)
Evidence Freshness: 92% < 7 days old
Audit Risk: LOW

GDPR ARTICLE 32 - SECURITY
Requirement: Data Encryption at Rest
Status: COMPLIANT
Evidence:
  1. AWS KMS Report (2026-04-10)
  2. Encryption Audit Trail (2026-04-08)
  3. Key Rotation Log (2026-04-15)
Last Verified: 2026-04-15 09:00 UTC
Auditor Notes: All evidence present and recent

GDPR ARTICLE 33 - INCIDENT NOTIFICATION
Status: COMPLIANT
...
```

---

##  Example Walkthrough

**Input: Policy Text + Evidence**
```
Policy: "All systems housing PII must use encryption at rest with keys
rotated quarterly or per vendor recommendations (minimum 90 days)"

Evidence Found:
- AWS KMS config: AES-256 enabled
- Key rotation logs: Last rotation 2026-01-15 (90 days ago)
- Certificate: Valid until 2026-06-30
```

**Expected Output:**
```json
{
  "requirement_id": "SC-7.1",
  "requirement_text": "Encryption at rest using AES-256+, quarterly key rotation",
  "compliance_status": "COMPLIANT",
  "confidence": 0.95,
  "evidence_links": [
    "AWS_KMS_Config_2026-04-15",
    "KeyRotationLog_Q1-2026",
    "SecurityAudit_2026-04-01"
  ],
  "narrative": "Organization encrypts all customer PII at rest using AES-256. Keys are rotated quarterly. Last rotation: 2026-01-15. Evidence verified and current. Compliant with GDPR Article 32 and NIST SC-7.",
  "next_review_date": "2026-07-15"
}
```

---

##  Evaluation Rubric (100 pts)

- **Policy Extraction (25 pts):** Correctly parse requirements from documents >85% accuracy
- **Evidence Linking (25 pts):** Accurately link evidence to requirements, minimal false matches
- **Report Quality (20 pts):** Clear compliance narratives, audit-ready format, confidence scores
- **Automation (15 pts):** >70% evidence auto-collected, minimal manual work
- **Performance (10 pts):** Analyze 500 requirements + 5K evidence in <60 sec
- **Bonus (5 pts):** Multi-framework correlation, trend analysis, exception tracking

---

##  Deliverables Checklist

- [ ] **GitHub Repo** - runnable code with policy parser
- [ ] **Jupyter Notebook** - evidence exploration & mapping analysis
- [ ] **Compliance Report** (JSON + PDF) - 10-15 requirements with evidence
- [ ] **Policy Parser** - extracts requirements from docs
- [ ] **Evidence Ingestion** - at least 2 integrations (CloudTrail + ...)
- [ ] **Technical Docs** - approach, integrations, scaling notes
- [ ] **5-Min Presentation** - demo + architecture

---

##  Timeline

- **Day 1:** Explore policies & evidence → Parse requirements → Map links
- **Day 2:** Build report generator → Create dashboard → Document
- **Day 3 (optional):** Add integrations → Bonus features → Polish

---

##  Bonus Features

- Multi-framework compliance view (GDPR + SOX + NIST) (+5)
- Compliance trending over time (+3)
- Exception registry & waiver tracking (+3)
- Automated remediation for gaps (+3)

---

##  FAQ

**Q: Do we need real connectors?** A: Mock/sample data OK, show architecture for real integration.
**Q: How fresh does evidence need to be?** A: Define policy (monthly? quarterly?), explain your choice.
**Q: Can we use LLM to parse policies?** A: Yes! Show cost & accuracy vs rule-based.

---

##  Judge Guide

**Green Flags:** Accurate requirement extraction, correct evidence mapping, auditor-ready reports
**Red Flags:** Misses requirements, incorrect evidence links, unclear narratives
**Questions:** "Show us a complex requirement you parsed", "How do you handle missing evidence?", "Would a real auditor accept this?"

---

**Ready to build?** Download templates and sample policies at [DOWNLOAD_LINK]


