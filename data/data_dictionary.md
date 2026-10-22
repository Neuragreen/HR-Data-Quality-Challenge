# Synthetic data dictionary

**Synthetic demo policy only; these are not official Emirates definitions.**

This reference matches `config/demo_policy.json` version demo-2026-10-v2. All IDs and employment IDs are source-local. Do not join their suffixes across systems.

## Sources and fields

### core_hr

one source observation per employment assignment. Dates: %Y-%m-%d.

| Semantic field | Source columns | Required | Valid values |
| --- | --- | --- | --- |
| source_id | employee_id | Yes |  |
| name | name | Yes |  |
| email | email | No |  |
| birth_date | birth_date | No |  |
| employment_id | employment_id | No |  |
| department | department | Yes | FIN-01, OPS-01, HR-01, IT-01, ENG-01 |
| job_code | job_code | Yes | ANALYST, MANAGER, ENGINEER, HRBP, SPECIALIST |
| employment_status | employment_status, status | Yes | ACTIVE, ON_LEAVE, TERMINATED |
| location | location | Yes | DUBAI, ABU_DHABI, LONDON, SINGAPORE |
| hire_date | hire_date | Yes |  |
| termination_date | termination_date | No |  |
| effective_from | effective_from | No |  |
| effective_to | effective_to | No |  |
| updated_at | updated_at | No |  |
| is_primary | is_primary | No |  |

Value mappings: `{"employment_status": {"LEAVE": "ON_LEAVE", "ON LEAVE": "ON_LEAVE", "LEAVER": "TERMINATED"}, "location": {"DXB": "DUBAI", "ABU DHABI": "ABU_DHABI"}}`.

### payroll

one source observation per payroll employment. Dates: %d/%m/%Y, %Y-%m-%d.

| Semantic field | Source columns | Required | Valid values |
| --- | --- | --- | --- |
| source_id | emp_id | Yes |  |
| name | employee_name | Yes |  |
| email | work_email | No |  |
| birth_date | birth_date | No |  |
| employment_id | employment_id | No |  |
| department | dept | Yes | FIN-01, OPS-01, HR-01, IT-01, ENG-01 |
| job_code | position_code | Yes | ANALYST, MANAGER, ENGINEER, HRBP, SPECIALIST |
| payroll_status | payroll_status | Yes | ELIGIBLE, FINAL_SETTLEMENT, INACTIVE |
| location | office_location | Yes | DUBAI, ABU_DHABI, LONDON, SINGAPORE |
| hire_date | start_date | Yes |  |
| termination_date | end_date | No |  |
| updated_at | updated_at | No |  |

Value mappings: `{"location": {"DXB": "DUBAI", "ABU DHABI": "ABU_DHABI"}}`.

### learning

one learning profile per person. Dates: %Y-%m-%d, %d-%b-%Y.

| Semantic field | Source columns | Required | Valid values |
| --- | --- | --- | --- |
| source_id | person_id | Yes |  |
| name | full_name | Yes |  |
| email | email_address | No |  |
| birth_date | birth_date | No |  |
| employment_id | employment_id | No |  |
| department | department_code | Yes | FIN-01, OPS-01, HR-01, IT-01, ENG-01 |
| job_code | job_code | Yes | ANALYST, MANAGER, ENGINEER, HRBP, SPECIALIST |
| location | location | Yes | DUBAI, ABU_DHABI, LONDON, SINGAPORE |
| updated_at | updated_at | No |  |

Value mappings: `{"location": {"DXB": "DUBAI", "ABU DHABI": "ABU_DHABI"}}`.

### access_directory

one source observation per directory account. Dates: %Y-%m-%d, %d/%m/%Y.

| Semantic field | Source columns | Required | Valid values |
| --- | --- | --- | --- |
| source_id | staff_id | Yes |  |
| name | worker_name | Yes |  |
| email | email | No |  |
| birth_date | birth_date | No |  |
| account_status | account_status, employee_status | Yes | ENABLED, DISABLED |
| location | work_location | No |  |
| updated_at | last_updated | No |  |
| access_exempt_until | access_exempt_until | No |  |

Value mappings: `{"account_status": {"ACTIVE": "ENABLED", "INACTIVE": "DISABLED"}, "location": {"DXB": "DUBAI", "ABU DHABI": "ABU_DHABI"}}`.

## Interpretation

- Core HR owns the configured department, job, location and employment dates within the same employment context. Invalid, stale or ambiguous authority cannot supply a fix.
- ACTIVE and ON_LEAVE are headcount-eligible. Employment ends inclusively; assignment effective-to is exclusive.
- Payroll ELIGIBLE / FINAL_SETTLEMENT / INACTIVE and directory ENABLED / DISABLED are separate domains. They are never copied from employment status.
- Record age beyond 730 days requests review. Core-to-payroll lag is 3 days; learning lag is 7 days. Leaver account grace is 3 days.
- Learning has one profile per matched person. Core and payroll profile uniqueness is scoped to employment/observation dates; concurrent and historical employments remain legitimate.
- Nullable termination dates on active employments are meaningful. Optional identity fields may be absent.
- Report definitions remain provisional until business-owner confirmation. No data is written back.
