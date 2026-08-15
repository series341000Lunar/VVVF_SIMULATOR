# MCK01C Research Sources

## Evidence classification

The MK3 research profile is based on values transcribed from a third-party Toshiba
MCK01C VVVF recreation video described in the project requirements.

- Evidence level: `observed_from_third_party_recreation`
- Manufacturer verification: **none**
- Source type: third-party simulator/recreation video
- Exact video URL: not supplied with the current observation set
- Transcription: `observations/mck01c_observed.csv`
- Derived simulator profile: `../profiles/mck01c_research.json`

These observations must not be described as Toshiba factory control data.
Transition values marked `MEDIUM` and amplitude samples marked `APPROXIMATE`
may change after frame-accurate review or better source material is supplied.

## Drive-dynamics observation

The Stage A default powering and braking rates are both `3.0 Hz/s`, derived from
the approximate displayed change of 6 Hz over 2 seconds described in the project
requirements. This is an observation of a third-party recreation video, not a
measurement of train acceleration and not Toshiba manufacturer vehicle-dynamics
data. The values remain configurable in `drive_dynamics` inside the profile.

## Raw media policy

Locally acquired analysis videos belong under `research/raw/`. Raw videos are
not committed because of file size and source-rights concerns. The root
`.gitignore` excludes raw-directory contents and all `*.mp4` files while keeping
the empty directory marker.

## Simulator-only values

The following settings are not measurements from the observed source:

- 0–120 km/h to 0–106.8 Hz virtual-speed mapping
- `coast_decay_seconds = 4.0`
- coast envelope timing positions between the observed amplitude sequence
- motor acoustic resonance frequencies, gains, and Q values
- motor electrical-current proxy time constant (`1.5 ms`)
- motor flux proxy time constant (`3.0 ms`)
- virtual stator probe count, angular positions, and asymmetric weights
- force high-pass cutoff (`20 Hz`)
- force/leakage mix (`97% / 3%`) and motor output gain
- audio-model crossfade duration (`50 ms`)

They are explicitly labelled `SIMULATOR TUNING — NOT VERIFIED MOTOR DATA` in
the profile and must not be presented as measured MCK01C motor parameters,
manufacturer data, or a validated electromagnetic motor model.
