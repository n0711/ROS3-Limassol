use ros3_core::{AuthKey, LinkMonitor, Observation, Telemetry};

fn payload(session: &str, sequence: i64) -> String {
    format!(
        r#"{{"schema_version":1,"robot_id":"usv01","session_id":"{session}","sequence":{sequence},"timestamp_ns":0,"latitude_deg":34.67,"longitude_deg":33.04,"heading_deg":0,"speed_m_s":0.6,"battery_pct":100}}"#
    )
}
fn monitor(key: Option<AuthKey>) -> LinkMonitor {
    LinkMonitor::new("usv01", 1.0, 2, key).unwrap()
}
fn key() -> AuthKey {
    AuthKey::new(vec![42; 32]).unwrap()
}

#[test]
fn blackout_boundary_recovery_and_clock() {
    let mut m = monitor(None);
    assert_eq!(m.snapshot(0.0).unwrap().state, "WAITING");
    assert!(m.ingest(&payload("a", 0), 0.0).unwrap());
    assert_eq!(m.snapshot(0.999).unwrap().state, "HEALTHY");
    assert_eq!(m.snapshot(1.0).unwrap().state, "STALE");
    assert!(!m.ingest(&payload("a", 0), 1.0).unwrap());
    assert_eq!(m.snapshot(1.0).unwrap().age_s, Some(1.0));
    assert!(m.ingest(&payload("a", 1), 2.0).unwrap());
    assert_eq!(m.snapshot(2.0).unwrap().state, "HEALTHY");
    assert!(m.snapshot(1.0).is_err());
    assert!(m.snapshot(f64::NAN).is_err());
    assert_eq!(m.snapshot(2.0).unwrap().accepted, 2);
}
#[test]
fn retired_sessions_and_capacity_fail_closed() {
    let mut m = monitor(None);
    assert!(m.ingest(&payload("a", 0), 0.0).unwrap());
    assert!(m.ingest(&payload("b", 0), 1.0).unwrap());
    assert!(!m.ingest(&payload("a", 1), 2.0).unwrap());
    assert!(!m.ingest(&payload("c", 0), 2.0).unwrap());
    assert!(m.ingest(&payload("b", 1), 2.0).unwrap());
    assert_eq!(
        m.snapshot(2.0).unwrap().last_rejection,
        Some("session_limit")
    );
}
#[test]
fn strict_contract_rejects_ambiguous_and_oversized_input() {
    let valid = payload("a", 0);
    assert!(Telemetry::parse(&valid).is_ok());
    for invalid in [
        valid.replace(
            "\"schema_version\":1",
            "\"schema_version\":1,\"schema_version\":1",
        ),
        valid.replace("\"sequence\":0", "\"sequence\":true"),
        valid.replace("\"sequence\":0", "\"sequence\":9223372036854775808"),
        valid.replace("\"heading_deg\":0", "\"heading_deg\":360"),
        valid.replace("\"battery_pct\":100", "\"battery_pct\":NaN"),
        valid.replace("\"robot_id\":\"usv01\"", "\"robot_id\":\"USV01\""),
        valid.replace("\"schema_version\":1", "\"extra\":0,\"schema_version\":1"),
        " ".repeat(4097),
    ] {
        assert!(Telemetry::parse(&invalid).is_err(), "{invalid}");
    }
}
#[test]
fn authenticated_messages_reject_tampering_wrong_key_and_unsigned_downgrade() {
    let signer = key();
    let signed = signer.sign(&payload("a", 0)).unwrap();
    assert!(signer.verify(&signed).is_ok());
    assert!(AuthKey::new(vec![1; 32]).unwrap().verify(&signed).is_err());
    assert!(signer.verify(&signed.replace("usv01", "usv02")).is_err());
    let mut m = monitor(Some(key()));
    assert!(!m.ingest(&payload("a", 0), 0.0).unwrap());
    assert!(!m.ingest(&signed.replace("usv01", "usv02"), 0.0).unwrap());
    assert_eq!(m.snapshot(0.0).unwrap().state, "WAITING");
    assert!(m.ingest(&signed, 0.0).unwrap());
    assert!(!m.ingest(&signed, 1.0).unwrap());
    assert_eq!(m.snapshot(1.0).unwrap().state, "STALE");
    assert!(!m
        .ingest(
            &key()
                .sign(&payload("b", 0))
                .unwrap()
                .replace("usv01", "usv02"),
            1.0
        )
        .unwrap());
    assert!(m
        .ingest(&key().sign(&payload("b", 0)).unwrap(), 1.0)
        .unwrap());
}
#[test]
fn record_envelope_requires_all_fields_and_rejects_duplicates() {
    assert!(Observation::parse(r#"{"record_version":1,"time_s":0,"payload":null}"#).is_ok());
    for raw in [
        r#"{"record_version":1,"time_s":0}"#,
        r#"{"record_version":1,"time_s":0,"payload":null,"payload":null}"#,
        r#"{"record_version":1,"time_s":-1,"payload":null}"#,
        r#"{"record_version":2,"time_s":0,"payload":null}"#,
    ] {
        assert!(Observation::parse(raw).is_err());
    }
}
#[test]
fn configuration_and_key_bounds() {
    assert!(AuthKey::new(vec![0; 31]).is_err());
    assert!(AuthKey::new(vec![0; 4097]).is_err());
    assert!(LinkMonitor::new("bad/id", 1.0, 128, None).is_err());
    assert!(LinkMonitor::new("usv01", 0.0, 128, None).is_err());
    assert!(LinkMonitor::new("usv01", 1.0, 0, None).is_err());
}
