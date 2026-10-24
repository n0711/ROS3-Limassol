# Contributing to OpenPELAOS / ROS3-Limassol

Start with a reproducible problem, a small change, and a clear explanation of the
result. Discuss new transports or major interfaces before implementing them.

Use Python 3.10 or newer for core work. ROS adapter targets are Humble on Ubuntu
22.04 (system Python 3.10) and Jazzy on Ubuntu 24.04 (system Python 3.12).
Keep their workspaces and sourced environments separate. The core must remain
importable and runnable without ROS.

Before opening a pull request:

```bash
python -m unittest discover -s tests -v
python -m ros3_limassol.demo
python -m compileall -q ros3_limassol launch tests
```

For a transport change, run the ROS graph tests against both supported
distributions through CI or separate sourced ROS workspaces, and run the launch
file. State every skipped or unavailable check. Changing a
telemetry field or its meaning requires updating the schema document and tests.

Contributions use the project's Apache-2.0 license. Do not include private logs,
credentials, personal data, or code that you are not authorized to contribute.
Use synthetic or explicitly shareable data in examples.

Keep discussions respectful and technical. Describe observable behavior rather
than personal judgments. Include reproduction steps when reporting a problem.
