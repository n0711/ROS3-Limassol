// SPDX-License-Identifier: Apache-2.0
//! Transport-independent arrival monitoring. HEALTHY never proves measurement freshness.
use hmac::{Hmac, Mac};
use serde::{Deserialize, Serialize};
use sha2::Sha256;
use std::collections::HashSet;

pub const MAX_PAYLOAD_BYTES: usize = 4096;
pub const MAX_RECORD_BYTES: usize = 32768;
pub const MAX_RECORDS: usize = 1_000_000;
const DOMAIN: &[u8] = b"ROS3-Limassol/telemetry-hmac/v1\0";
type HmacSha256 = Hmac<Sha256>;
pub type Result<T> = std::result::Result<T, &'static str>;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Telemetry {
    pub schema_version: u8,
    pub robot_id: String,
    pub session_id: String,
    pub sequence: i64,
    pub timestamp_ns: i64,
    pub latitude_deg: f64,
    pub longitude_deg: f64,
    pub heading_deg: f64,
    pub speed_m_s: f64,
    pub battery_pct: f64,
}

fn robot_id_valid(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 32
        && id.as_bytes()[0].is_ascii_lowercase()
        && id
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
}

impl Telemetry {
    pub fn parse(raw: &str) -> Result<Self> {
        if raw.len() > MAX_PAYLOAD_BYTES {
            return Err("payload_limit");
        }
        let packet: Self = serde_json::from_str(raw).map_err(|_| "invalid_payload")?;
        packet.validate()?;
        Ok(packet)
    }
    pub fn validate(&self) -> Result<()> {
        if self.schema_version != 1
            || !robot_id_valid(&self.robot_id)
            || self.session_id.is_empty()
            || self.session_id.len() > 64
            || !self
                .session_id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
            || self.sequence < 0
            || self.timestamp_ns < 0
        {
            return Err("invalid_payload");
        }
        for (value, min, max) in [
            (self.latitude_deg, -90.0, 90.0),
            (self.longitude_deg, -180.0, 180.0),
            (self.heading_deg, 0.0, 360.0),
            (self.speed_m_s, 0.0, 100.0),
            (self.battery_pct, 0.0, 100.0),
        ] {
            if !value.is_finite() || value < min || value > max {
                return Err("invalid_payload");
            }
        }
        if self.heading_deg == 360.0 {
            return Err("invalid_payload");
        }
        Ok(())
    }
}

/// A shared secret owned by the caller; never serialized or included in Debug.
/// Use an independent, randomly generated key of at least 32 bytes per robot.
pub struct AuthKey(Vec<u8>);
impl AuthKey {
    pub fn new(bytes: Vec<u8>) -> Result<Self> {
        if !(32..=4096).contains(&bytes.len()) {
            return Err("key_length");
        }
        Ok(Self(bytes))
    }
    fn mac(&self, payload: &str) -> HmacSha256 {
        let mut mac =
            HmacSha256::new_from_slice(&self.0).expect("HMAC accepts arbitrary key lengths");
        mac.update(DOMAIN);
        mac.update(payload.as_bytes());
        mac
    }
    /// Authenticate exact UTF-8 payload bytes; JSON reformatting invalidates the MAC.
    pub fn sign(&self, payload: &str) -> Result<String> {
        Telemetry::parse(payload)?;
        let tag = self.mac(payload).finalize().into_bytes();
        let mac_hex: String = tag.iter().map(|b| format!("{b:02x}")).collect();
        let raw = serde_json::to_string(&Envelope {
            auth_version: 1,
            payload: payload.to_owned(),
            mac_hex,
        })
        .map_err(|_| "invalid_envelope")?;
        // Fits the existing v1 observation payload bound, including envelope overhead.
        if raw.len() > MAX_PAYLOAD_BYTES {
            return Err("payload_limit");
        }
        Ok(raw)
    }
    pub fn verify(&self, raw: &str) -> Result<Telemetry> {
        if raw.len() > MAX_PAYLOAD_BYTES {
            return Err("payload_limit");
        }
        let envelope: Envelope = serde_json::from_str(raw).map_err(|_| "invalid_envelope")?;
        if envelope.auth_version != 1 || envelope.mac_hex.len() != 64 {
            return Err("authentication_failed");
        }
        let mut tag = [0_u8; 32];
        for (i, byte) in tag.iter_mut().enumerate() {
            let pair = &envelope.mac_hex.as_bytes()[i * 2..i * 2 + 2];
            fn nibble(b: u8) -> Result<u8> {
                match b {
                    b'0'..=b'9' => Ok(b - b'0'),
                    b'a'..=b'f' => Ok(b - b'a' + 10),
                    _ => Err("authentication_failed"),
                }
            }
            *byte = (nibble(pair[0])? << 4) | nibble(pair[1])?;
        }
        self.mac(&envelope.payload)
            .verify_slice(&tag)
            .map_err(|_| "authentication_failed")?;
        Telemetry::parse(&envelope.payload)
    }
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Envelope {
    auth_version: u8,
    payload: String,
    mac_hex: String,
}

#[derive(Debug, Serialize, PartialEq)]
pub struct LinkStatus {
    pub robot_id: String,
    pub state: &'static str,
    pub age_s: Option<f64>,
    pub accepted: u64,
    pub rejected: u64,
    pub last_sequence: Option<i64>,
    pub last_rejection: Option<&'static str>,
}

/// Each instance serves exactly one robot and one optional pre-provisioned key.
/// Keyed mode never falls back to unsigned messages. State changes follow verification.
pub struct LinkMonitor {
    robot_id: String,
    stale_after_s: f64,
    max_sessions: usize,
    key: Option<AuthKey>,
    clock: Option<f64>,
    last_received: Option<f64>,
    session: Option<String>,
    seen: HashSet<String>,
    last_sequence: Option<i64>,
    accepted: u64,
    rejected: u64,
    last_rejection: Option<&'static str>,
}
impl LinkMonitor {
    pub fn new(
        robot_id: &str,
        stale_after_s: f64,
        max_sessions: usize,
        key: Option<AuthKey>,
    ) -> Result<Self> {
        if !robot_id_valid(robot_id)
            || !stale_after_s.is_finite()
            || stale_after_s <= 0.0
            || !(1..=4096).contains(&max_sessions)
        {
            return Err("invalid_configuration");
        }
        Ok(Self {
            robot_id: robot_id.into(),
            stale_after_s,
            max_sessions,
            key,
            clock: None,
            last_received: None,
            session: None,
            seen: HashSet::new(),
            last_sequence: None,
            accepted: 0,
            rejected: 0,
            last_rejection: None,
        })
    }
    fn advance(&mut self, now: f64) -> Result<()> {
        if !now.is_finite() || now < 0.0 || self.clock.is_some_and(|previous| now < previous) {
            return Err("invalid_receiver_clock");
        }
        self.clock = Some(now);
        Ok(())
    }
    fn reject(&mut self, reason: &'static str) -> Result<bool> {
        self.rejected = self.rejected.saturating_add(1);
        self.last_rejection = Some(reason);
        Ok(false)
    }
    pub fn ingest(&mut self, raw: &str, now: f64) -> Result<bool> {
        self.advance(now)?;
        let packet = match &self.key {
            Some(key) => key.verify(raw),
            None => Telemetry::parse(raw),
        };
        let packet = match packet {
            Ok(p) => p,
            Err(reason) => return self.reject(reason),
        };
        if packet.robot_id != self.robot_id {
            return self.reject("unexpected_robot");
        }
        if self.session.as_ref() == Some(&packet.session_id) {
            if self
                .last_sequence
                .is_some_and(|last| packet.sequence <= last)
            {
                return self.reject("duplicate_or_out_of_order");
            }
        } else {
            if self.seen.contains(&packet.session_id) {
                return self.reject("retired_session");
            }
            if self.seen.len() >= self.max_sessions {
                return self.reject("session_limit");
            }
            self.seen.insert(packet.session_id.clone());
            self.session = Some(packet.session_id);
        }
        self.last_sequence = Some(packet.sequence);
        self.last_received = Some(now);
        self.accepted = self.accepted.saturating_add(1);
        Ok(true)
    }
    pub fn snapshot(&mut self, now: f64) -> Result<LinkStatus> {
        self.advance(now)?;
        let age_s = self.last_received.map(|arrival| now - arrival);
        let state = match age_s {
            None => "WAITING",
            Some(age) if age >= self.stale_after_s => "STALE",
            _ => "HEALTHY",
        };
        Ok(LinkStatus {
            robot_id: self.robot_id.clone(),
            state,
            age_s,
            accepted: self.accepted,
            rejected: self.rejected,
            last_sequence: self.last_sequence,
            last_rejection: self.last_rejection,
        })
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Observation {
    pub record_version: u8,
    pub time_s: f64,
    pub payload: Option<String>,
}
impl Observation {
    pub fn parse(raw: &str) -> Result<Self> {
        if raw.len() > MAX_RECORD_BYTES {
            return Err("record_limit");
        }
        let record: Self = serde_json::from_str(raw).map_err(|_| "invalid_record")?;
        if record.record_version != 1
            || !record.time_s.is_finite()
            || record.time_s < 0.0
            || record
                .payload
                .as_ref()
                .is_some_and(|p| p.len() > MAX_PAYLOAD_BYTES)
        {
            return Err("invalid_record");
        }
        // serde treats missing Option fields as None; require the field explicitly.
        let value: serde_json::Value = serde_json::from_str(raw).map_err(|_| "invalid_record")?;
        if value.as_object().map(|o| o.len()) != Some(3) {
            return Err("invalid_record");
        }
        Ok(record)
    }
}
