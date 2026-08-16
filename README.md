# VVVF GTO Simulator MK3 — Phase 1 Stage C

철도용 VVVF 변조 패턴을 PC에서 연구하기 위한 Python 시뮬레이터입니다.
녹음된 MP3/WAV를 속도에 맞춰 재생하지 않고, 외부 프로파일에 따라 3상 기준파와
PWM switching을 계산하여 waveform, FFT, 가상 모터음에 반영합니다.
Stage C는 같은 DSP를 deterministic offline renderer에서도 재사용해 full-cycle
WAV, state/event CSV, metadata와 spectrogram을 생성합니다.

현재 구조의 핵심은 vehicle speed와 inverter control을 분리하고, 실제 경과 시간을
사용하는 Drive Simulation 계층을 기존 MK2 코어 위에 추가한 것입니다.

```text
DIRECT CONTROL FREQUENCY ─┐
VIRTUAL VEHICLE SPEED ────┼─> Control Frequency [Hz]
  └─ configurable mapper  │            │
DRIVE SIMULATION ─────────┘            ├─> POWERING / COAST / BRAKING profile
  └─ Master Controller                 ├─> Modulation + amplitude
     + elapsed-time dynamics           └─> Waveform / FFT / audio
```

VVVF modulation engine은 `vehicle_speed_kmh`를 받지 않습니다. 속도 입력은 반드시
`LinearFrequencyMapper`를 거쳐 `control_frequency_hz`로 변환됩니다.

## 데이터 신뢰성 고지

`profiles/mck01c_research.json`은 Toshiba 제조사 공식 control table이 아닙니다.

> **Observed from a third-party Toshiba MCK01C VVVF recreation video.**
>
> **Not verified manufacturer control data.**

- `verified: false`
- `evidence_level: observed_from_third_party_recreation`
- transition과 amplitude 수치는 제3자 재현 영상에서 판독한 연구 관찰값
- 0–120 km/h → 0–106.8 Hz mapping은 `SIMULATOR TUNING`
- 4.0초 coast decay는 `NOT VERIFIED SOURCE TIMING DATA`
- 3.0 Hz/s 역행·제동 rate는 제3자 재현 영상의 근사 관찰값이며 제조사 차량
  dynamics가 아님
- motor resonance 값도 실제 차량 검증값이 아닌 simulator tuning

관찰 원본의 전사본은 `research/observations/mck01c_observed.csv`, 출처 및 제한은
`research/SOURCES.md`에 기록합니다. 분석용 MP4는 `research/raw/`에 로컬로 둘 수
있지만 Git에 포함되지 않습니다.

## 설치와 실행

요구 환경은 Windows 10/11과 Python 3.11 이상입니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

Windows에서는 [run_vvvf.bat](run_vvvf.bat)을 더블클릭해 같은 로컬 가상환경으로
실행할 수 있습니다.

다른 JSON profile을 지정할 수 있습니다.

```powershell
python main.py --profile .\profiles\mck01c_research.json
```

처음 실행할 때 audio는 정지 상태이며 master volume은 20%입니다. `START AUDIO`를
누르기 전에 Windows 출력 장치와 시스템 볼륨을 확인하십시오.

## MK3 GUI

- `DIRECT CONTROL FREQ`: 0.0–106.8 Hz, slider와 0.1 Hz spinbox
- `VIRTUAL SPEED`: 0.0–120.0 km/h를 profile mapper로 변환
- `DRIVE SIMULATION`: 중앙 중립형 `-100…+100` Master Controller 명령을 실제
  경과 시간으로 적분해 control frequency를 변경
- `POWERING`, `COAST`, `BRAKING` 직접 선택
- control/carrier/fundamental frequency를 서로 다른 필드로 표시
- modulation mode, pulse count, normalized amplitude(%) 표시
- 현재 drive-state transition table과 active region highlight
- U reference/U switching waveform과 switching-excitation FFT
- `START AUDIO`, `STOP AUDIO`, 0–100% master volume
- `LEGACY SWITCHING` / `MOTOR EMULATOR` 실시간 A/B selector
- Loudness Compensation ON/OFF와 현재 monitor gain 표시
- `RUN FULL CYCLE`: 75.2초 실시간 POWERING → COAST → BRAKING preview
- `RENDER FULL CYCLE`: 별도 worker에서 빠른 deterministic artifact export
- `ABORT`, progress, phase status와 output directory 표시
- 실행 중 `Reload Profile`

Direct mode에서는 정확한 연구 threshold를 위해 hysteresis가 꺼집니다. Virtual
Speed mode에서는 profile의 `transition_hysteresis_hz`를 사용하여 경계 chatter를
줄입니다.

Drive Simulation에서는 `+2`보다 큰 명령이 POWERING, `-2…+2`가 COAST,
`-2`보다 작은 명령이 BRAKING입니다. Full command의 기본 rate는 프로파일에 기록된
3.0 Hz/s이며 command 절대값에 선형 비례합니다. COAST 중 control frequency는
감소하지 않고 기존 3P amplitude envelope만 진행합니다. 0 Hz와 106.8 Hz에서
frequency를 clamp하며, 표시 속도는 inverse frequency mapper로 계산합니다.

Drive Simulation 중에는 Master Controller가 Drive State의 유일한 권한입니다.
따라서 Drive State combo와 Command Level은 비활성화되며, profile amplitude를
Master Controller 크기로 다시 곱하지 않습니다. 기존 Direct/Virtual mode에서는
두 컨트롤을 계속 수동으로 사용할 수 있습니다.

## Phase 1 Stage C — Analysis workflow

`RUN FULL CYCLE`은 실시간 preview의 authoritative controller가 됩니다. 실행 중에는
Direct/Virtual/Master/Drive State와 profile reload가 잠기며 `ABORT` 후 복구됩니다.
`RENDER FULL CYCLE`은 realtime audio device나 GUI timer를 사용하지 않고 별도 worker
thread와 별도 DSP state로 다음 profile-derived cycle을 렌더합니다.

```text
POWERING  0.0 → 106.8 Hz   35.6 s  (106.8 / 3.0)
COAST     106.8 Hz hold      4.0 s  (profile coast duration)
BRAKING   106.8 → 0.0 Hz    35.6 s  (106.8 / 3.0)
TOTAL                         75.2 s
```

Offline simulation은 48 kHz, 480-sample/10 ms 고정 block을 사용합니다. State log는
정확히 50 Hz이며 같은 profile/scenario/sample rate에서 audio와 state records가
deterministic하게 재현됩니다. Realtime 경로의 `AudioSynthesizer`, modulator, Motor
Emulator, loudness compensation, limiter를 그대로 사용하며 sounddevice callback을
녹음하지 않습니다.

CLI에서도 실행할 수 있습니다.

```powershell
python -m tools.render_full_cycle
python -m tools.render_full_cycle --legacy
```

각 실행은 Git에서 제외되는 다음 Windows-compatible 폴더를 만듭니다.

```text
research/runs/YYYYMMDD_HHMMSS_mck01c_full_cycle/
├─ motor.wav          # canonical, 48 kHz mono 16-bit PCM
├─ legacy.wav         # --legacy에서만 생성
├─ state.csv          # 50 Hz normalized state log
├─ events.csv         # phase/pulse transition timestamps
├─ run_metadata.json  # profile SHA-256, tuning, Git state, validation
└─ spectrogram.png    # motor.wav 기반 0–6 kHz analysis
```

Canonical Motor WAV는 Stage B DSP 뒤에 0.8 master scale을 적용하며, validation은
finite/non-silent/near-silence뿐 아니라 0.95 limiter 경계에 닿은 sample이 0개인지도
검사합니다.

`state.csv`는 time, scenario phase, master command, drive state, virtual speed,
control/modulation/carrier/effective-switching frequency, pulse count, profile
amplitude, monitor gain과 audio model을 기록합니다. Spectrogram은 최종 PCM WAV를
다시 읽어 만들며 POWERING/COAST/BRAKING 구간과 modulation transition을 표시합니다.

## MCK01C research profile

POWERING:

| Control frequency | Pattern |
|---|---|
| 0.0–8.5 Hz | ASYNC PWM, carrier 365 Hz |
| 8.5–16.0 Hz | 27P |
| 16.0–30.0 Hz | 15P |
| 30.0–48.0 Hz | 9P |
| 48.0–60.0 Hz | 5P |
| 60.0–73.0 Hz | 3P |
| 73.0–106.8 Hz | 1P |

BRAKING은 별도 table을 사용하며 transition은 16, 30, 50, 74, 100 Hz입니다.
모든 region은 마지막 끝점을 제외한 half-open interval이고 최종 106.8 Hz만
포함합니다. 106.8 Hz보다 큰 입력은 clamp됩니다.

Amplitude curve는 `LINEAR`, `STEP`, `HOLD` keyframe을 읽습니다. POWERING의
48.5 Hz step(0.516 → 0.659)과 BRAKING의 7.5 Hz 저속 cutoff(0 → 0.063)를
평균내지 않고 표현합니다.

COAST 진입 시 현재 control frequency를 hold하고 3P로 전환합니다. amplitude
envelope는 82.7%, 60.4%, 44.4%, 28.0%, 0% 관찰 순서를 사용하지만, 각 점의
시간은 검증되지 않았으므로 전체 decay 시간은 profile tuning parameter입니다.

## Profile schema

MK3 profile은 `schema_version: 2`이며 다음 normalized sections를 사용합니다.

```text
metadata
input_mapping
limits
transition_hysteresis_hz
drive_dynamics
powering.regions / powering.amplitude
braking.regions / braking.amplitude
coast
motor_acoustics
```

Loader는 기존 schema version 1 JSON도 control-frequency 내부 모델로 변환합니다.
버전이 없는 MK1 파일은 v1으로 처리하며, 알 수 없는 future schema는 명확한
`Unsupported profile schema_version` 오류로 거부합니다.

Canonical one-pulse 표현은 v2에서 `mode: SYNC_PULSE`, `pulse_count: 1`입니다.
v1 loader는 하위 호환성을 위해 기존 `ONE_PULSE` 문자열도 보존합니다.

## Motor Acoustic Emulator

기본 audio model은 `MOTOR EMULATOR`이며 Legacy Switching을 삭제하지 않고 즉시
A/B 전환할 수 있습니다. 전환 시 50 ms crossfade를 사용하며 inverter fundamental
phase와 carrier phase는 reset하지 않습니다.

```text
3-Phase Switching
        ↓ common-mode removal
Normalized Phase Voltage ABC
        ↓ 1.5 ms stateful response
Winding Current Proxy
        ↓ 3.0 ms stateful flux response
Flux ABC → Clarke-like αβ
        ↓ 8 asymmetric stator probes, B²
Radial Force Proxy
        ↓ 20 Hz high-pass
650 / 1200 / 2400 Hz Structural Resonance
        ↓
97% Motor Force + 3% Switching Leakage
```

전류·자속·force·resonance 상태는 audio block 사이에서 유지되며 profile reload,
application restart 또는 명시적인 audio reset에서만 초기화됩니다. 모든 값은
normalized synthesis parameter이며 실제 Toshiba motor R/L, slot geometry 또는
SPL 데이터가 아닙니다.

비교 sweep은 다음 명령으로 실행합니다.

```powershell
python -m tools.motor_audio_sweep
```

현재 결과는 `research/analysis/motor_emulator_sweep.csv`에 기록되어 있습니다.
GUI waveform과 Switching Excitation FFT는 계속 inverter source를 표시합니다.

## Monitor Loudness Compensation

청취용 음량 보정은 VVVF profile amplitude를 변경하지 않고 audio output에만
적용됩니다.

```text
Selected Acoustic Model
        ↓
Monitor Loudness Compensation
        ↓
Limiter
        ↓
Master Volume
```

PWM modulation index는 switching duty/pulse width를 결정합니다. Normalized bridge
voltage level에는 amplitude를 다시 곱하지 않아 저속 신호의 중복 감쇠를 피합니다.
Profile amplitude curve와 pulse transition 자체는 그대로 유지됩니다.

Legacy와 Motor model은 각각 독립적인 1 Hz POWERING calibration map을 캐시합니다.
기본 target은 -20 dBFS, gain 범위는
-6…+18 dB이며 주파수 curve smoothing과 150 ms attack/500 ms release를 적용합니다.
이 값들은 모두 `motor_acoustics.monitor_loudness`의 simulator tuning입니다.

GUI의 `Loudness Compensation` ON/OFF로 즉시 A/B 비교할 수 있으며 기본값은
ON입니다. 보상 gain은 현재 Coast envelope의 RMS를 추적하지 않으므로 fade-out과
BRAKING 저주파 cutoff를 되살리지 않습니다.

동일한 diagnostic sweep은 다음 명령으로 CSV 형태로 출력합니다.

```powershell
python -m tools.audio_rms_sweep
```

현재 기준 결과는 `research/analysis/mk3_audio_loudness_sweep.csv`에 기록되어
있습니다.

## 구현 구조

- `vvvf/frequency.py`: input mapper와 finite clamp
- `vvvf/dynamics.py`: master-command state 판정과 elapsed-time frequency 적분
- `vvvf/profile.py`: v1/v2 validation 및 normalized data model
- `vvvf/state.py`: input/drive/coast/hysteresis state
- `vvvf/modulation.py`: vectorized 3상 ASYNC/SYNC/1P switching
- `vvvf/motor_emulator.py`: phase voltage, current, flux, force, resonance DSP
- `vvvf/loudness.py`: calibration curve, gain clamp, realtime gain smoothing
- `vvvf/audio.py`: model selection/crossfade, loudness, limiter, stream lifecycle
- `vvvf/scenario.py`: profile-derived full-cycle definition과 fixed-time runner
- `vvvf/offline_renderer.py`: device-independent deterministic DSP rendering
- `vvvf/run_export.py`: WAV/CSV/metadata export와 automatic validation
- `vvvf/spectrogram.py`: canonical WAV spectrogram과 transition overlays
- `ui/main_window.py`: Qt controls, plots, worker-thread Auto Test/Export

Audio는 48 kHz/512-sample block으로 생성합니다. limiter, 낮은 기본 master volume,
block-edge smoothing을 적용하고 STOP/창 종료 시 stream을 닫습니다.

## 테스트

```powershell
python -m unittest discover -s tests -v
```

자동 테스트 범위:

- v1/v2 profile loading, invalid/future schema, contiguous regions
- POWERING/BRAKING transition과 half-open equality
- direct input bypass, virtual speed mapper, direct-mode hysteresis off
- inverse frequency mapper, configurable dead-zone와 full/partial command rate
- Drive Simulation의 Power/Coast/Brake 적분, clamp, finite 입력, profile amplitude
- amplitude keyframe, linear interpolation, discontinuity, braking cutoff, clamp
- 3상 120도 offset, ASYNC 365 Hz, 27P/15P/3P/1P switching 차이
- phase voltage balance, current/flux state continuity, force DC removal
- 365 Hz tonal energy, 모든 pulse-mode 차이, structural resonance와 force/leakage mix
- Legacy/Motor distinct output, 50 ms crossfade와 model별 loudness calibration
- 30초 Motor Emulator finite/bounded stability
- COAST frequency hold, 3P, envelope decay
- audio finite/silence, loudness gain clamp, low/high RMS spread, Coast/Brake 보존
- loudness ON/OFF와 stream start/stop cleanup
- GUI startup, input modes, drive states, active transition, waveform와 FFT data
- profile-derived 75.2초 scenario와 0 → max → hold → 0 endpoint
- exact short-render determinism, 48 kHz mono WAV와 50 Hz CSV
- profile SHA-256/Stage B tuning metadata와 POWERING 7/7, BRAKING 6/6 validation
- final WAV 기반 non-empty spectrogram PNG와 non-blocking GUI worker/ABORT

## 알려진 제한

- 실제 MCK01C 제조사 control table이나 차량 dynamics가 아닙니다.
- rolling resistance, aerodynamic drag와 실제 열차 질량/가속도는 아직 모델링하지
  않습니다.
- Motor Emulator는 normalized physically-inspired proxy이며 실제 induction-motor
  equivalent circuit, FEM, slot geometry 또는 제조사 motor model이 아닙니다.
- Realtime rolling spectrogram과 manual-drive recording은 구현하지 않았습니다.
- spectrogram의 미적 품질과 실제 speaker/device 호환성은 자동 테스트 대상이
  아닙니다.
- VvvfGeeks YAML importer는 optional 후속 작업이며 이번 MK3에는 없습니다.
- CAN, OBD-II, Bluetooth, serial, ESP32/STM32, gate driver, MOSFET/IGBT,
  고전압 inverter 및 실제 차량 제어는 구현하지 않습니다.

## 사용자 청취 확인 항목

1. 저속 ASYNC 365 Hz 특징이 유지되는지
2. 27P 전환이 구분되는지
3. 15P / 9P / 5P / 3P / 1P가 각각 다르게 들리는지
4. Legacy보다 raw electronic 느낌이 감소했는지
5. Motor Emulator가 지나치게 둔탁하지 않은지
6. 저속 음량이 다시 작아지지 않았는지
7. 고속에서 harsh clipping이 없는지
8. Power → Coast → Brake 전환이 자연스러운지

Stage B의 주관적 Motor 음색은 사용자 청취 확인을 통과한 baseline이며, Stage C는
97% Motor Force / 3% Switching Leakage 및 기존 acoustic/loudness tuning을 변경하지
않습니다.

## Project status

```text
PHASE 1

MCK01C Profile           PASS
Drive Dynamics           PASS
Audio Compensation       PASS
Motor Acoustic Emulator  PASS
Analysis Workflow        PASS

VVVF_SIMULATOR — PHASE 1 COMPLETE

PHASE 2

EV6 Data Logger / OBD    NOT STARTED
```
