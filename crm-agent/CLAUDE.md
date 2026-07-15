# 1. Product context
Atwoods is a membership at a work resort in the Catskills where a leadership team leaves the office to get through the strategic work it never finishes there — the planning, the hard alignment conversations, the decisions everyone keeps punting on in the weekly meeting. The alternative most companies use is a hotel conference room or a generic offsite venue, built for travelers passing through, not for a team trying to think together for two or three days straight: the rooms aren't set up for working sessions, no one is managing the schedule or the logistics, and the team ends up running the same laptop-and-Slack routine in a different building. Atwoods is built around the working session instead of the stay — accommodations, meeting space, and programming designed for the retreat itself. The buyer is whoever owns the offsite budget and logistics — Founder, CEO, COO, Chief of Staff, Head of People, Head of Operations, or an Executive Assistant, depending on company size — but that person is often not the one in the room: the users are the leadership team, employees, advisors, board members, and other invited guests actually doing the work on-site.

# 2. Ideal Customer Profile
See icp.md for company size, stage, industry, geography, and exclusion criteria, plus the decision-maker/champion/user title mapping and what counts as a champion move worth alerting on.

# 3. Agent behavior rules
- The agent proposes, the human approves. No CRM record is ever mutated without human approval per category (see config/pipeline.yaml for which fields require approval).
- Every state mutation goes through scripts/update_contact.py and must pass schema validation in schemas/contact.schema.json. Never write to state/contacts.jsonl directly.
- Every CRM write goes through scripts/write_to_crm.py and is logged to state/audit.jsonl before the API call is made. If the API call fails, the audit entry is marked "rolled_back" and the in-state record reverts.
- No detection is acted on with confidence "low". Low-confidence detections are logged and skipped. The cost of a false positive is a corrupted record, the cost of a false negative is one more day of staleness.
- Every claim about a contact must cite evidence: a URL, a date, a quoted line. The agent never says "based on recent activity"; it quotes the artifact.
- If an MCP connector (HubSpot, Salesforce, Gmail, Apollo, Clay) is unavailable, switch to manual mode and write a draft to output/alerts/ rather than pretending the action happened.
- When config/crm.yaml api_via is "mcp" (current setup: HubSpot), scripts/write_to_crm.py cannot call the connector itself -- only the agent has MCP tool access. `push` stages the change and leaves the audit entry "pending" with the exact MCP call to make; the agent makes that call, then runs `mark-result` to resolve the audit entry to success or failed (with rollback). Never mark an audit entry success without having actually made the MCP call.

# 4. Field categories and approval requirements
Fields are grouped by risk. The pipeline config maps each group to an approval requirement.

low_risk: title formatting fixes, email casing, phone format.

medium_risk: job title change at same company, department change, updated email domain at same company.

high_risk: company change (job move), departure (no current company), champion or decision-maker status changes, any contact linked to an open deal.

# 5. File conventions
- Contact slugs: firstname-lastname-companyslug, lowercase, hyphenated.
- Dates in filenames and fields: YYYY-MM-DD.
- All files in markdown unless they're code (.py), config (.yaml), data (.jsonl, .csv), or schema (.schema.json).
