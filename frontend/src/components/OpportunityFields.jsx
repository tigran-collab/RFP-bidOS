const REVIEW_STATUSES = [
  "New",
  "Needs Review",
  "Pursue",
  "Do Not Pursue",
  "Watchlist",
  "Archived",
];
const PRIORITIES = ["High", "Medium", "Low"];
const NEXT_ACTIONS = [
  "Download Documents",
  "Parse Documents",
  "Run AI Evaluation",
  "Extract Requirements",
  "Verify Portal",
  "Manual Review",
  "No Action",
];

function Text({ label, field, values, onChange, type = "text" }) {
  return (
    <label className="form-field">
      <span>{label}</span>
      <input
        type={type}
        value={values[field] ?? ""}
        onChange={(event) => onChange(field, event.target.value)}
      />
    </label>
  );
}

function Area({ label, field, values, onChange }) {
  return (
    <label className="form-field">
      <span>{label}</span>
      <textarea
        rows="2"
        value={values[field] ?? ""}
        onChange={(event) => onChange(field, event.target.value)}
      />
    </label>
  );
}

function Select({ label, field, values, onChange, options, allowBlank = true }) {
  return (
    <label className="form-field">
      <span>{label}</span>
      <select
        value={values[field] ?? ""}
        onChange={(event) => onChange(field, event.target.value)}
      >
        {allowBlank ? <option value="">-</option> : null}
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function OpportunityFields({ values, onChange }) {
  return (
    <div className="opportunity-form">
      <h3>Core</h3>
      <div className="form-grid">
        <Text label="Title *" field="title" values={values} onChange={onChange} />
        <Text label="Agency" field="agency" values={values} onChange={onChange} />
        <Text label="Solicitation #" field="solicitation_number" values={values} onChange={onChange} />
        <Text label="Source URL" field="source_url" values={values} onChange={onChange} />
        <Text label="Portal URL" field="portal_url" values={values} onChange={onChange} />
        <Text label="Location" field="location" values={values} onChange={onChange} />
        <Text label="Service Type" field="service_type" values={values} onChange={onChange} />
        <Text label="Contract Type" field="contract_type" values={values} onChange={onChange} />
        <Text label="Estimated Value" field="estimated_value" values={values} onChange={onChange} type="number" />
      </div>

      <h3>Logistics</h3>
      <div className="form-grid">
        <Text label="Due Date" field="due_date" values={values} onChange={onChange} type="date" />
        <Text label="Q&A Deadline" field="q_and_a_deadline" values={values} onChange={onChange} type="date" />
        <Text label="Pre-Bid Date" field="pre_bid_date" values={values} onChange={onChange} type="date" />
        <label className="form-field">
          <span>Pre-Bid Mandatory</span>
          <input
            type="checkbox"
            checked={Boolean(values.pre_bid_mandatory)}
            onChange={(event) => onChange("pre_bid_mandatory", event.target.checked)}
          />
        </label>
        <Text label="Submission Method" field="submission_method" values={values} onChange={onChange} />
        <Text label="Submission Portal" field="submission_portal" values={values} onChange={onChange} />
        <Area label="Required Forms Summary" field="required_forms_summary" values={values} onChange={onChange} />
      </div>

      <h3>Workflow</h3>
      <div className="form-grid">
        <Select label="Review Status" field="review_status" values={values} onChange={onChange} options={REVIEW_STATUSES} allowBlank={false} />
        <Select label="Priority" field="priority" values={values} onChange={onChange} options={PRIORITIES} />
        <Select label="Next Action" field="next_action" values={values} onChange={onChange} options={NEXT_ACTIONS} />
      </div>
      <Area label="Description" field="description" values={values} onChange={onChange} />
      <Area label="Notes" field="notes" values={values} onChange={onChange} />
      <Area label="Review Notes" field="review_notes" values={values} onChange={onChange} />
    </div>
  );
}

// Build an API payload from form values: drop empty strings, coerce types.
export function buildOpportunityPayload(values) {
  const payload = {};
  const stringFields = [
    "title",
    "agency",
    "solicitation_number",
    "source_url",
    "portal_url",
    "location",
    "service_type",
    "contract_type",
    "submission_method",
    "submission_portal",
    "required_forms_summary",
    "description",
    "notes",
    "review_notes",
    "review_status",
    "priority",
    "next_action",
  ];
  for (const field of stringFields) {
    const value = values[field];
    if (value !== undefined && value !== null && value !== "") {
      payload[field] = value;
    }
  }
  for (const field of ["due_date", "q_and_a_deadline", "pre_bid_date"]) {
    if (values[field]) {
      payload[field] = values[field];
    }
  }
  if (values.estimated_value !== undefined && values.estimated_value !== "") {
    const num = Number(values.estimated_value);
    if (!Number.isNaN(num)) {
      payload.estimated_value = num;
    }
  }
  payload.pre_bid_mandatory = Boolean(values.pre_bid_mandatory);
  return payload;
}
