# MCK01C Research Sources

## Evidence classification

The MK2 profile is based on values transcribed from a third-party Toshiba
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

They are explicitly labelled `SIMULATOR TUNING` in the profile and UI.
