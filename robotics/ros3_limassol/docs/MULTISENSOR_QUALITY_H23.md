# H23 offline multisensor timestamp quality

From the package directory run `python -m ros3_limassol.multisensor_quality manifest.json`.
This synthetic fixture declares a camera and IMU, with one camera observation.

```json
{"version":1,"expected":["camera","imu"],"reports":{"camera":{"schema_version":1,"freshness_limit_s":0.5,"calibration":{"offset_s":1,"uncertainty_s":0.25,"drift_ppm":0,"elapsed_s":0},"samples":[{"sample_id":"1","capture_time_s":7,"receive_time_s":8}]}}}
```

The camera age lies between 0 and 0.25 seconds under the supplied assumptions.
The IMU row records missing observations. Supply a separate H21 batch per observed
sensor and use null calibration for an observed sensor with unknown clock offset.
Sample IDs are local to a sensor. The report does not pair samples across devices.
A missing sensor refers to the whole supplied batch. Within-stream dropout detection
would require an expected cadence or a schedule.

The input is limited to 65,536 bytes, 16 expected sensors and 128 samples per
observed sensor. Unknown sensors and malformed batches invalidate the report.
See [H21](CLOCK_ALIGNMENT_H21.md) for the clock sign, permitted ranges and drift model.
Results describe timing only. Calibration accuracy, cross-device synchronization and
sensor measurement accuracy require independent evidence.
