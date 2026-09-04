# External reporting integration

Manager's Suite is deliberately independent of message platforms and background
workers. It owns employee, location, roster, target, performance-report and
alert data through its web interface.

Any separate reporting backend is responsible for its own credentials, uptime,
message collection, authorization and exports. Integrations must remain
explicit and semi-manual until a stable exchange format is agreed.

The initial exchange should use manager-reviewed CSV files with employee names,
report timestamps, locations, cumulative employee totals and cumulative
location totals. Do not let an external process write directly to this
application's database.
