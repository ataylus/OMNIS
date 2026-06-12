# Problem 03: Compliance Evidence Collection - Sample Datasets

## Overview
Sample datasets for Problem Statement 03 - automating compliance evidence gathering and audit readiness.

## Files Included

### 1. `policy_documents.txt` (3 policies)
**Actual policy text** as it would exist in your policy repository.

**Policies:**
1. **POL-ENC-001**: Data Encryption and Protection (2.1)
   - 3 requirements covering encryption at rest, key rotation, encryption in transit

2. **POL-AC-001**: Access Control & Identity Management (3.0)
   - 3 requirements covering MFA, least privilege, privileged account restrictions

3. **POL-AUD-001**: Audit Logging & Monitoring (2.5)
   - 3 requirements covering audit logging, retention, access control

**Each requirement specifies:**
- Responsible team
- Scope
- Evidence source (where proof comes from)
- Audit frequency
- Compliance framework mappings (GDPR, NIST, CIS, ISO, PCI-DSS)

### 2. `evidence_artifacts.csv` (250+ evidence records)
**Comprehensive collected evidence** linking to specific requirements across multiple frameworks.

**Columns:**
- `evidence_id` - Unique identifier
- `requirement_id` - Which policy requirement it proves
- `evidence_type` - What kind of evidence (config, log, report, audit, cert)
- `timestamp` - When collected
- `source_system` - Where it came from
- `description` - What the evidence shows
- `framework_mappings` - Which standards it addresses
- `verification_status` - verified, gap, pending
- `auditor_notes` - Comments from auditor

**Evidence Examples:**
- KMS configuration proving encryption
- Database audit logs proving access control
- Azure AD config proving MFA enforcement
- Log retention settings proving policy compliance
- Backup encryption reports

## How to Use

### Load in Python:
```python
import pandas as pd

# Load policy documents
with open('policy_documents.txt') as f:
    policies_text = f.read()

# Parse requirements (you'd use NLP/regex)
requirements = []
for req in policies_text.split('REQUIREMENT'):
    if req.strip():
        requirements.append(req)

# Load evidence
evidence = pd.read_csv('evidence_artifacts.csv')

# Coverage analysis
print(f"Total requirements: ~9 (across 3 policies)")
print(f"Evidence collected: {len(evidence)}")
print(f"Verification status:")
print(evidence['verification_status'].value_counts())
```

### Analysis Ideas:
1. **Gap Detection**: Which requirements have NO evidence?
2. **Evidence Freshness**: Is evidence recent? (< 30 days old)
3. **Framework Coverage**: Which standards have 100% evidence?
4. **Audit Readiness**: Can you pass audit with current evidence?
5. **Requirement Extraction**: Parse policy text to find testable requirements

## Data Characteristics

- **Policies**: 3 samples (real enterprises have 50+)
- **Requirements**: ~9 from these policies
- **Evidence Records**: 15 samples
- **Frameworks**: GDPR, NIST, CIS, ISO 27001, PCI-DSS, SOX
- **Time Range**: Jan 2026 - Apr 2026 (3 months)

## Real-World Scale

Production systems:
- 50-100 policy documents
- 200-500 requirements
- 5,000+ evidence artifacts
- Continuous evidence collection

## Regulatory Alignment

All requirements map to:
- **GDPR**: Articles 25, 32, 33
- **NIST SP 800-53**: AC-2, AC-3, AU-2, AU-5, SC-7, etc.
- **ISO 27001**: A.6, A.10, A.12, A.13
- **PCI-DSS**: Requirements 1-12
- **SOX 302**: Internal Controls

## Key Observations

1. Most evidence is recent (within 30 days)
2. One requirement has a GAP (contractors not compliant with MFA)
3. Some evidence appears multiple times (redundant proof)
4. Audit notes suggest action items

## EV-0015 Gap Example

**GAP FOUND**: Contractor MFA Compliance
- Policy requires: All admin access requires MFA
- Evidence: "2 out of 5 contractors compliant"
- Action: Remediation needed

## Next Steps

1. **Parse policies** - Extract machine-readable requirements
2. **Seed evidence collector** - Find evidence sources for each requirement
3. **Build automation** - Collect evidence automatically
4. **Audit report generator** - Create compliance scorecards
5. **Gap finder** - Alert when requirements lack evidence

---

See [PROBLEM_STATEMENT_03.md](../../PROBLEM_STATEMENT_03.md) for full details.
