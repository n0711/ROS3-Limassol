# H24 synthetic localization dataset and H25 odometry scoring

From robotics/ros3_limassol run

    python -m ros3_limassol.localization_replay examples/h24_synthetic.json

## Version 1 contract

The fixture defines a local, right-handed East/North/Up world with a shared
arbitrary origin. The base frame is Forward/Left/Up at the trajectory point.
All timestamps are integer milliseconds since the same synthetic session
origin, strictly increasing within each stream. Streams may have different rates.

| Stream | Observation | Frame and units |
| --- | --- | --- |
| GNSS | Antenna position | World ENU, metres |
| IMU | Specific force including the stationary gravity response, angular velocity | Base-aligned FLU, m/s² and rad/s |
| Odometry | Estimated base position | World ENU, metres |
| Reference | Generated base position at each evaluation epoch | Same world origin, axes and point as odometry |

Calibration declares the vector from base origin to GNSS antenna in base FLU
metres and requires IMU axes already aligned with base. The fixture assumes
ideal IMU scale and zero bias. GNSS and IMU are input-format examples.
The scorer reads the supplied odometry directly and performs no sensor fusion.

## Scoring

Use every reference epoch as the denominator for coverage. Pair odometry by
exact time. Count extra estimate epochs separately. Compute 3D position RMSE
over matches. Return null when there are zero matches. Consecutive missing
reference epochs form one gap. The first subsequent match closes it, and a
trailing gap has a null resumption time. Resumption measures estimate availability,
irrespective of position error.

The example matches two of three epochs, with errors of 0 m and 1 m. The
result is sqrt(1/2) m. One gap starts at 1000 ms and closes at 2000 ms.
The CLI includes a SHA-256 digest of the exact input file for reproduction.

## Independent trajectory intake (pending)

For a measured session archive the raw GNSS, IMU, odometry and reference files
with checksums, sensor identities, clock domains, conversion scripts, ENU origin,
frame transforms and calibration uncertainties. Record the reference instrument,
tracked point, timing uncertainty and registration method. Document independence
from estimator inputs and reserve evaluation sessions before parameter tuning.
A measured-data importer and a held-out baseline run remain separate milestones.
