# 1. Product context
[One paragraph on what we sell, for whom, and the specific problem we solve. Use the words a frustrated customer uses, not marketing copy. To be filled.]

# 2. Ideal Customer Profile
[Pointer to icp.md, which lists company size, industry, stage, buyer role, exclusion criteria. To be filled.]

# 3. Agent behavior rules
- The agent proposes, the human approves. No CRM record is ever mutated without human approval per category (see config/pipeline.yaml for which fields require approval).
- Every state mutation goes through scripts/update_contact.py and must pass schema validation in schemas/contact.schema.json. Never write to state/contacts.jsonl directly.
- Every CRM write goes through scripts/write_to_crm.py and is logged to state/audit.jsonl before the API call is made. If the API call fails, the audit entry is marked "rolled_back" and the in-state record reverts.
- No detection is acted on with confidence "low". Low-confidence detections are logged and skipped. The cost of a false positive is a corrupted record, the cost of a false negative is one more day of staleness.
- Every claim about a contact must cite evidence: a URL, a date, a quoted line. The agent never says "based on recent activity"; it quotes the artifact.
- If an MCP connector (HubSpot, Salesforce, Gmail, Apollo, Clay) is unavailable, switch to manual mode and write a draft to output/alerts/ rather than pretending the action happened.

# 4. Field categories and approval requirements
Fields are grouped by risk. The pipeline config maps each group to an approval requirement.

low_risk: title formatting fixes, email casing, phone format.

medium_risk: job title change at same company, department change, updated email domain at same company.

high_risk: company change (job move), departure (no current company), champion or decision-maker status changes, any contact linked to an open deal.

# 5. File conventions
- Contact slugs: firstname-lastname-companyslug, lowercase, hyphenated.
- Dates in filenames and fields: YYYY-MM-DD.
- All files in markdown unless they're code (.py), config (.yaml), data (.jsonl, .csv), or schema (.schema.json).
