# Synthetic field dependencies

**These are declared demo dependencies, not discovered or official Emirates lineage.**

| Upstream field | Downstream field or report |
| --- | --- |
| core_hr.is_primary | report:active_headcount_dubai |
| core_hr.effective_from | report:active_headcount_dubai |
| core_hr.effective_to | report:active_headcount_dubai |
| core_hr.effective_from | report:leaver_enabled_accounts |
| core_hr.effective_to | report:leaver_enabled_accounts |
| core_hr.employment_status | report:active_headcount_dubai |
| core_hr.location | report:active_headcount_dubai |
| core_hr.hire_date | report:active_headcount_dubai |
| core_hr.termination_date | report:active_headcount_dubai |
| core_hr.termination_date | report:leaver_enabled_accounts |
| core_hr.employment_status | report:leaver_enabled_accounts |
| core_hr.hire_date | report:leaver_enabled_accounts |
| access_directory.account_status | report:leaver_enabled_accounts |
| access_directory.access_exempt_until | report:leaver_enabled_accounts |
| core_hr.department | payroll.dept |
| core_hr.department | learning.department_code |
| core_hr.job_code | payroll.position_code |
| core_hr.job_code | learning.job_code |
| core_hr.department | report:payroll_reconciliation |
| payroll.department | report:payroll_reconciliation |
| core_hr.job_code | report:payroll_reconciliation |
| payroll.job_code | report:payroll_reconciliation |
| core_hr.location | report:payroll_reconciliation |
| payroll.location | report:payroll_reconciliation |
| core_hr.hire_date | report:payroll_reconciliation |
| payroll.hire_date | report:payroll_reconciliation |
| core_hr.termination_date | report:payroll_reconciliation |
| payroll.termination_date | report:payroll_reconciliation |

Executable reports: `active_headcount_dubai`, `leaver_enabled_accounts`, `payroll_reconciliation`. Other system paths describe potential exposure. Application transformations, propagation timing and monetary payroll amounts are not simulated. Confirm the official dependency document before adapting the policy.
