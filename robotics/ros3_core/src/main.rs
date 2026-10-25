// SPDX-License-Identifier: Apache-2.0
use ros3_core::{AuthKey, LinkMonitor, Observation, MAX_RECORDS, MAX_RECORD_BYTES};
use std::fs::File;
use std::io::{self, BufRead, BufReader, Read, Write};

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args().skip(1);
    let path = args.next().ok_or(
        "usage: ros3-core RECORDING [--robot-id ID] [--stale-after SECONDS] [--key-file PATH]",
    )?;
    let mut robot = String::from("usv01");
    let mut stale = 1.0;
    let mut key = None;
    while let Some(option) = args.next() {
        let value = args.next().ok_or("option requires a value")?;
        match option.as_str() {
            "--robot-id" => robot = value,
            "--stale-after" => stale = value.parse()?,
            "--key-file" => {
                let file = File::open(value)?;
                #[cfg(unix)]
                {
                    use std::os::unix::fs::PermissionsExt;
                    if file.metadata()?.permissions().mode() & 0o077 != 0 {
                        return Err(
                            "key file must not be accessible by group or others (chmod 600)".into(),
                        );
                    }
                }
                let mut bytes = Vec::new();
                file.take(4097).read_to_end(&mut bytes)?;
                key = Some(AuthKey::new(bytes)?);
            }
            _ => return Err("unknown option".into()),
        }
    }
    let mut monitor = LinkMonitor::new(&robot, stale, 128, key)?;
    let mut reader = BufReader::new(File::open(path)?);
    let stdout = io::stdout();
    let mut writer = io::BufWriter::new(stdout.lock());
    let mut line = Vec::with_capacity(MAX_RECORD_BYTES + 1);
    let mut records = 0;
    loop {
        line.clear();
        let count = (&mut reader)
            .take((MAX_RECORD_BYTES + 1) as u64)
            .read_until(b'\n', &mut line)?;
        if count == 0 {
            break;
        }
        if count > MAX_RECORD_BYTES || records == MAX_RECORDS {
            return Err("recording limit exceeded".into());
        }
        records += 1;
        let observation = Observation::parse(std::str::from_utf8(&line)?)?;
        if let Some(payload) = observation.payload {
            monitor.ingest(&payload, observation.time_s)?;
        }
        let status = monitor.snapshot(observation.time_s)?;
        serde_json::to_writer(&mut writer, &status)?;
        writeln!(writer)?;
    }
    writer.flush()?;
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("ros3-core: {error}");
        std::process::exit(1);
    }
}
